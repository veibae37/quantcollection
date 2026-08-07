"""Modular multi-factor alpha research and portfolio optimization system.

The module uses annualized return/risk units throughout.  It is intentionally
data-vendor agnostic: production callers provide point-in-time fundamentals,
prices, benchmark weights and risk-model inputs through pandas objects.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, minimize


LOGGER = logging.getLogger(__name__)


class QuantModelError(RuntimeError):
    """Base exception for model validation and optimization failures."""


class DataValidationError(QuantModelError):
    """Raised when an input cannot be made safe for quantitative use."""


class OptimizationError(QuantModelError):
    """Raised when the optimizer cannot produce a feasible portfolio."""


def _as_series(
    value: float | Sequence[float] | pd.Series,
    index: pd.Index,
    name: str,
) -> pd.Series:
    if np.isscalar(value):
        result = pd.Series(float(value), index=index, name=name)
    elif isinstance(value, pd.Series):
        result = value.reindex(index).astype(float).rename(name)
    else:
        array = np.asarray(value, dtype=float)
        if array.shape != (len(index),):
            raise DataValidationError(f"{name} must have length {len(index)}")
        result = pd.Series(array, index=index, name=name)
    if not np.isfinite(result.to_numpy()).all():
        raise DataValidationError(f"{name} contains missing or infinite values")
    return result


@dataclass(frozen=True)
class PreprocessingConfig:
    trim_sigma: float = 3.0
    ddof: int = 0
    max_missing_fraction: float = 0.20
    variance_floor: float = 1e-12


class DataProcessor:
    """Clean, trim, standardize and cross-sectionally neutralize factors."""

    def __init__(self, config: PreprocessingConfig | None = None) -> None:
        self.config = config or PreprocessingConfig()
        if self.config.trim_sigma <= 0:
            raise ValueError("trim_sigma must be positive")

    def clean_numeric(self, values: pd.DataFrame) -> pd.DataFrame:
        if values.empty or not values.index.is_unique:
            raise DataValidationError("factor data must be non-empty with a unique index")
        cleaned = values.apply(pd.to_numeric, errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        missing = cleaned.isna().mean()
        bad = missing[missing > self.config.max_missing_fraction]
        if not bad.empty:
            raise DataValidationError(
                "factor columns exceed missing-data limit: "
                + ", ".join(f"{column}={ratio:.1%}" for column, ratio in bad.items())
            )
        return cleaned.apply(lambda column: column.fillna(column.median()))

    def trim(self, values: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
        frame = values.to_frame() if isinstance(values, pd.Series) else values.copy()
        output = frame.astype(float)
        for column in output:
            mean = output[column].mean()
            standard_deviation = output[column].std(ddof=self.config.ddof)
            if not np.isfinite(standard_deviation) or standard_deviation <= 0:
                output[column] = mean
                continue
            radius = self.config.trim_sigma * standard_deviation
            output[column] = output[column].clip(mean - radius, mean + radius)
        if isinstance(values, pd.Series):
            return output.iloc[:, 0].rename(values.name)
        return output

    def standardize(
        self, values: pd.DataFrame | pd.Series
    ) -> pd.DataFrame | pd.Series:
        frame = values.to_frame() if isinstance(values, pd.Series) else values.copy()
        output = frame.astype(float)
        for column in output:
            mean = output[column].mean()
            standard_deviation = output[column].std(ddof=self.config.ddof)
            if (
                not np.isfinite(standard_deviation)
                or standard_deviation**2 <= self.config.variance_floor
            ):
                output[column] = 0.0
            else:
                output[column] = (output[column] - mean) / standard_deviation
        if isinstance(values, pd.Series):
            return output.iloc[:, 0].rename(values.name)
        return output

    def industry_neutralize(
        self,
        values: pd.DataFrame | pd.Series,
        industries: pd.Series,
        regression_weights: pd.Series | None = None,
    ) -> pd.DataFrame | pd.Series:
        """Return WLS residuals after projection on full industry dummies.

        With a full set of mutually exclusive industry dummies the fitted
        value is simply the (optionally weighted) mean inside each industry.
        Computing that mean directly is mathematically identical to the dummy
        regression, avoids an unnecessary LAPACK call and is substantially
        more robust in lightweight Windows/Spyder environments.
        """
        frame = values.to_frame() if isinstance(values, pd.Series) else values.copy()
        industries = industries.reindex(frame.index)
        if industries.isna().any():
            raise DataValidationError("industry labels are missing for some assets")
        if regression_weights is None:
            weights = pd.Series(1.0, index=frame.index, name="regression_weights")
        else:
            weights = _as_series(
                regression_weights, frame.index, "regression_weights"
            )
            if (weights <= 0).any():
                raise DataValidationError("regression weights must be positive")

        labels = industries.astype(str)
        group_weight = weights.groupby(labels, sort=False).transform("sum")
        if (group_weight <= 0).any():
            raise DataValidationError("each industry must have positive total weight")
        residuals = pd.DataFrame(index=frame.index, columns=frame.columns, dtype=float)
        for column in frame:
            values_column = pd.to_numeric(frame[column], errors="coerce")
            if not np.isfinite(values_column.to_numpy(dtype=float)).all():
                raise DataValidationError(f"{column} contains missing or infinite values")
            weighted_sum = (values_column * weights).groupby(
                labels, sort=False
            ).transform("sum")
            residuals[column] = values_column - weighted_sum / group_weight
        if isinstance(values, pd.Series):
            return residuals.iloc[:, 0].rename(values.name)
        return residuals

    def preprocess_factors(
        self,
        raw_factors: pd.DataFrame,
        industries: pd.Series | None = None,
        regression_weights: pd.Series | None = None,
    ) -> pd.DataFrame:
        """Apply clean -> 3-sigma trim -> z-score -> neutralize -> z-score."""
        processed = self.standardize(self.trim(self.clean_numeric(raw_factors)))
        if industries is not None:
            processed = self.industry_neutralize(
                processed, industries, regression_weights
            )
            processed = self.standardize(processed)
        return processed

    @staticmethod
    def benchmark_neutralize(
        alpha: pd.Series, benchmark_weights: pd.Series
    ) -> pd.Series:
        benchmark = benchmark_weights.reindex(alpha.index).astype(float)
        if benchmark.isna().any() or not np.isclose(benchmark.sum(), 1.0, atol=1e-8):
            raise DataValidationError("benchmark weights must align and sum to one")
        alpha_values = alpha.astype(float)
        benchmark_mean = float((benchmark * alpha_values).sum())
        return alpha_values - benchmark_mean


class FactorLibrary:
    """Vendor-neutral construction interfaces for common public factors."""

    @staticmethod
    def size(price: pd.Series, shares_outstanding: pd.Series) -> pd.Series:
        market_cap = price.astype(float) * shares_outstanding.astype(float)
        if (market_cap <= 0).any():
            raise DataValidationError("market capitalization must be positive")
        return np.log(market_cap).rename("size")

    @staticmethod
    def value_ratios(
        market_cap: pd.Series,
        book_equity: pd.Series,
        earnings_ttm: pd.Series,
        dividends_ttm: pd.Series,
    ) -> pd.DataFrame:
        market_cap = market_cap.astype(float)
        if (market_cap <= 0).any():
            raise DataValidationError("market capitalization must be positive")
        return pd.DataFrame(
            {
                "book_to_price": book_equity.astype(float) / market_cap,
                "earnings_to_price": earnings_ttm.astype(float) / market_cap,
                "dividend_to_price": dividends_ttm.astype(float) / market_cap,
            }
        )

    @staticmethod
    def momentum(
        prices: pd.DataFrame,
        lookback_days: int = 252,
        skip_recent_days: int = 21,
    ) -> pd.Series:
        if lookback_days <= skip_recent_days or skip_recent_days < 0:
            raise ValueError("lookback must exceed the non-negative skip window")
        if len(prices) <= lookback_days:
            raise DataValidationError(
                f"momentum requires more than {lookback_days} price observations"
            )
        start = prices.iloc[-lookback_days - 1].astype(float)
        end = prices.iloc[-skip_recent_days - 1].astype(float)
        if (start <= 0).any() or (end <= 0).any():
            raise DataValidationError("prices must be positive")
        return (end / start - 1.0).rename("momentum")

    @staticmethod
    def growth(
        historical_growth: pd.Series,
        expected_growth: pd.Series | None = None,
        expected_weight: float = 0.5,
    ) -> pd.Series:
        if not 0 <= expected_weight <= 1:
            raise ValueError("expected_weight must be in [0, 1]")
        historical = historical_growth.astype(float)
        if expected_growth is None:
            return historical.rename("growth")
        expected = expected_growth.reindex(historical.index).astype(float)
        return (
            (1 - expected_weight) * historical + expected_weight * expected
        ).rename("growth")

    @staticmethod
    def volatility(
        returns: pd.DataFrame,
        window: int = 126,
        annualization: int = 252,
    ) -> pd.Series:
        if len(returns) < window:
            raise DataValidationError(f"volatility requires at least {window} rows")
        return (
            returns.tail(window).std(ddof=1) * np.sqrt(annualization)
        ).rename("volatility")

    @staticmethod
    def liquidity(
        turnover: pd.DataFrame | None = None,
        volume: pd.DataFrame | None = None,
        window: int = 63,
    ) -> pd.Series:
        if turnover is not None:
            return turnover.tail(window).mean().rename("liquidity")
        if volume is not None:
            average_volume = volume.tail(window).mean().clip(lower=1.0)
            return np.log(average_volume).rename("liquidity")
        raise ValueError("turnover or volume is required")

    @staticmethod
    def leverage(
        total_assets: pd.Series,
        total_liabilities: pd.Series,
        equity: pd.Series | None = None,
    ) -> pd.DataFrame:
        assets = total_assets.astype(float)
        liabilities = total_liabilities.astype(float)
        if (assets <= 0).any():
            raise DataValidationError("total assets must be positive")
        result = {"debt_to_assets": liabilities / assets}
        if equity is not None:
            safe_equity = equity.astype(float).replace(0, np.nan)
            result["debt_to_equity"] = liabilities / safe_equity
        return pd.DataFrame(result)

    @staticmethod
    def market_beta(
        returns: pd.DataFrame, market_returns: pd.Series, window: int = 252
    ) -> pd.Series:
        joined = returns.tail(window).copy()
        market = market_returns.reindex(joined.index).astype(float)
        market_variance = market.var(ddof=1)
        if not np.isfinite(market_variance) or market_variance <= 0:
            raise DataValidationError("market return variance must be positive")
        centered_market = market - market.mean()
        centered_assets = joined - joined.mean()
        covariance = centered_assets.mul(centered_market, axis=0).sum() / (
            len(joined) - 1
        )
        return (covariance / market_variance).rename("market_beta")


@dataclass(frozen=True)
class AlphaResult:
    composite_alpha: pd.Series
    factor_alpha: pd.DataFrame
    effective_ic: float
    breadth: float
    forecast_information_ratio: float


class AlphaGenerator:
    """Transform standardized signals into restrained residual alpha forecasts."""

    def __init__(self, score_limit: float = 3.0) -> None:
        if score_limit <= 0:
            raise ValueError("score_limit must be positive")
        self.score_limit = score_limit

    @staticmethod
    def estimate_information_ratio(
        information_coefficient: float,
        breadth: float,
        transfer_coefficient: float = 1.0,
    ) -> float:
        if breadth < 0 or not 0 <= transfer_coefficient <= 1:
            raise ValueError("breadth must be non-negative and TC must be in [0, 1]")
        return float(information_coefficient * np.sqrt(breadth) * transfer_coefficient)

    def generate(
        self,
        standardized_scores: pd.DataFrame,
        residual_volatility: pd.Series,
        expected_ic: Mapping[str, float],
        factor_weights: Mapping[str, float] | None = None,
        benchmark_weights: pd.Series | None = None,
        breadth: float | None = None,
        transfer_coefficient: float = 1.0,
    ) -> AlphaResult:
        if standardized_scores.empty:
            raise DataValidationError("at least one alpha score is required")
        scores = standardized_scores.astype(float).clip(
            -self.score_limit, self.score_limit
        )
        if not np.isfinite(scores.to_numpy()).all():
            raise DataValidationError("alpha scores contain missing or infinite values")
        omega = residual_volatility.reindex(scores.index).astype(float)
        if omega.isna().any() or (omega <= 0).any():
            raise DataValidationError("residual volatility must be positive and aligned")
        missing_ic = set(scores.columns) - set(expected_ic)
        if missing_ic:
            raise DataValidationError(f"missing IC values for: {sorted(missing_ic)}")

        if factor_weights is None:
            weights = pd.Series(1.0 / len(scores.columns), index=scores.columns)
        else:
            weights = pd.Series(factor_weights, dtype=float).reindex(scores.columns)
            if weights.isna().any() or np.isclose(weights.abs().sum(), 0.0):
                raise DataValidationError("factor weights must be finite and non-zero")
            weights = weights / weights.abs().sum()

        ic = pd.Series(expected_ic, dtype=float).reindex(scores.columns)
        factor_alpha = scores.mul(ic, axis=1).mul(omega, axis=0)
        composite = factor_alpha.mul(weights, axis=1).sum(axis=1)
        if benchmark_weights is not None:
            factor_alpha = factor_alpha.apply(
                lambda column: DataProcessor.benchmark_neutralize(
                    column, benchmark_weights
                )
            )
            composite = DataProcessor.benchmark_neutralize(
                factor_alpha.mul(weights, axis=1).sum(axis=1), benchmark_weights
            )

        effective_ic = float((ic * weights).sum())
        effective_breadth = float(breadth if breadth is not None else len(scores))
        forecast_ir = self.estimate_information_ratio(
            effective_ic, effective_breadth, transfer_coefficient
        )
        return AlphaResult(
            composite_alpha=composite.rename("alpha"),
            factor_alpha=factor_alpha,
            effective_ic=effective_ic,
            breadth=effective_breadth,
            forecast_information_ratio=forecast_ir,
        )


@dataclass(frozen=True)
class OptimizationResult:
    portfolio_weights: pd.Series
    active_weights: pd.Series
    expected_active_return: float
    active_risk: float
    expected_information_ratio: float
    utility: float
    turnover: float
    success: bool
    message: str
    iterations: int
    constraint_diagnostics: Mapping[str, float]

    def weights_frame(self, benchmark_weights: pd.Series) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "benchmark_weight": benchmark_weights.reindex(
                    self.portfolio_weights.index
                ),
                "portfolio_weight": self.portfolio_weights,
                "active_weight": self.active_weights,
            }
        )


class PortfolioOptimizer:
    """Long-only active QP with risk, neutrality, bounds and trading costs."""

    def __init__(
        self,
        risk_aversion: float = 5.0,
        transaction_cost_aversion: float = 0.0,
        individual_max_weight: float | None = None,
        eigenvalue_floor: float = 1e-10,
        solver_tolerance: float = 1e-10,
        max_iterations: int = 2_000,
    ) -> None:
        if risk_aversion <= 0 or transaction_cost_aversion < 0:
            raise ValueError("risk aversion must be positive and cost aversion non-negative")
        self.risk_aversion = risk_aversion
        self.transaction_cost_aversion = transaction_cost_aversion
        self.individual_max_weight = individual_max_weight
        self.eigenvalue_floor = eigenvalue_floor
        self.solver_tolerance = solver_tolerance
        self.max_iterations = max_iterations

    @staticmethod
    def nearest_psd(matrix: np.ndarray, floor: float = 1e-10) -> np.ndarray:
        """Return a conservative PSD matrix without requiring LAPACK.

        A small LDL-style check preserves an already positive-definite input.
        Otherwise a Gershgorin lower bound determines the diagonal loading
        required to guarantee all eigenvalues are at least ``floor``.  This is
        deliberately conservative and avoids native ``numpy.linalg`` crashes
        seen in some bundled Windows/Spyder runtimes.
        """
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise DataValidationError("covariance matrix must be square")
        if not np.isfinite(matrix).all():
            raise DataValidationError("covariance matrix contains invalid values")
        symmetric = (matrix + matrix.T) / 2.0
        size = symmetric.shape[0]

        # Pure NumPy scalar arithmetic avoids dispatching to a broken LAPACK
        # DLL while cheaply preserving matrices that are already well formed.
        lower = np.zeros((size, size), dtype=float)
        positive_definite = True
        for row in range(size):
            diagonal = symmetric[row, row] - sum(
                float(lower[row, column]) ** 2 for column in range(row)
            )
            if diagonal < floor or not np.isfinite(diagonal):
                positive_definite = False
                break
            lower[row, row] = math.sqrt(diagonal)
            for following in range(row + 1, size):
                numerator = symmetric[following, row] - sum(
                    float(lower[following, column]) * float(lower[row, column])
                    for column in range(row)
                )
                lower[following, row] = numerator / lower[row, row]
        if positive_definite:
            return symmetric

        radii = np.sum(np.abs(symmetric), axis=1) - np.abs(np.diag(symmetric))
        lower_bound = float(np.min(np.diag(symmetric) - radii))
        diagonal_loading = max(float(floor) - lower_bound, 0.0)
        return symmetric + np.eye(size) * diagonal_loading

    def build_factor_covariance(
        self,
        factor_exposures: pd.DataFrame,
        factor_covariance: pd.DataFrame | np.ndarray,
        specific_variance: pd.Series | Sequence[float],
    ) -> pd.DataFrame:
        """Build V = X F X' + Delta for an assets-by-factors exposure matrix.

        If exposures are supplied as factors-by-assets instead, the equivalent
        notation is V = X' F X.
        """
        if factor_exposures.empty or not factor_exposures.index.is_unique:
            raise DataValidationError("factor exposures must be non-empty and unique")
        x = factor_exposures.astype(float)
        if not np.isfinite(x.to_numpy()).all():
            raise DataValidationError("factor exposures contain invalid values")
        if isinstance(factor_covariance, pd.DataFrame):
            factor_covariance = factor_covariance.reindex(
                index=x.columns, columns=x.columns
            ).to_numpy(dtype=float)
        else:
            factor_covariance = np.asarray(factor_covariance, dtype=float)
        if factor_covariance.shape != (x.shape[1], x.shape[1]):
            raise DataValidationError("factor covariance dimensions do not match X")
        f = self.nearest_psd(factor_covariance, self.eigenvalue_floor)
        delta = _as_series(
            specific_variance, x.index, "specific_variance"
        ).to_numpy()
        if (delta < 0).any():
            raise DataValidationError("specific variances must be non-negative")
        x_values = x.to_numpy()
        # Broadcasting performs X F X' without dispatching to a BLAS DLL.
        x_times_f = np.sum(
            x_values[:, :, None] * f[None, :, :], axis=1
        )
        covariance = np.sum(
            x_times_f[:, None, :] * x_values[None, :, :], axis=2
        ) + np.diag(delta)
        covariance = self.nearest_psd(covariance, self.eigenvalue_floor)
        return pd.DataFrame(covariance, index=x.index, columns=x.index)

    @staticmethod
    def _constraint_matrix(
        benchmark: pd.Series,
        industry_exposure: pd.DataFrame | pd.Series | None,
        style_exposure: pd.DataFrame | pd.Series | None,
        neutrality_tolerance: float,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
        rows = [np.ones(len(benchmark))]
        lower = [1.0]
        upper = [1.0]
        labels = ["full_investment"]

        def append_exposures(
            exposure: pd.DataFrame | pd.Series | None, prefix: str
        ) -> None:
            if exposure is None:
                return
            frame = exposure.to_frame() if isinstance(exposure, pd.Series) else exposure
            frame = frame.reindex(benchmark.index).astype(float)
            if frame.isna().any().any():
                raise DataValidationError(f"{prefix} exposures do not align")
            target = frame.mul(benchmark, axis=0).sum(axis=0).to_numpy()
            for position, column in enumerate(frame.columns):
                rows.append(frame[column].to_numpy())
                lower.append(float(target[position] - neutrality_tolerance))
                upper.append(float(target[position] + neutrality_tolerance))
                labels.append(f"{prefix}:{column}")

        append_exposures(industry_exposure, "industry")
        append_exposures(style_exposure, "style")
        return np.vstack(rows), np.array(lower), np.array(upper), labels

    def _project_feasible(
        self,
        values: np.ndarray,
        lower_bounds: np.ndarray,
        upper_bounds: np.ndarray,
        matrix: np.ndarray,
        constraint_lower: np.ndarray,
        constraint_upper: np.ndarray,
        *,
        max_sweeps: int = 600,
    ) -> np.ndarray:
        """Dykstra projection onto box and linear interval constraints."""
        projected = np.asarray(values, dtype=float).copy()
        corrections = np.zeros((len(matrix) + 1, len(projected)), dtype=float)
        tolerance = max(self.solver_tolerance, 1e-10)
        for _ in range(max_sweeps):
            before = projected.copy()
            candidate = projected + corrections[0]
            next_value = np.clip(candidate, lower_bounds, upper_bounds)
            corrections[0] = candidate - next_value
            projected = next_value

            for position, row in enumerate(matrix):
                candidate = projected + corrections[position + 1]
                row_norm = float(np.sum(row * row))
                if row_norm <= 0:
                    continue
                achieved = float(np.sum(row * candidate))
                target = achieved
                if achieved < constraint_lower[position]:
                    target = float(constraint_lower[position])
                elif achieved > constraint_upper[position]:
                    target = float(constraint_upper[position])
                if target != achieved:
                    next_value = candidate + ((target - achieved) / row_norm) * row
                else:
                    next_value = candidate
                corrections[position + 1] = candidate - next_value
                projected = next_value

            if float(np.max(np.abs(projected - before))) <= tolerance:
                achieved_all = np.sum(matrix * projected[None, :], axis=1)
                violation = max(
                    float(np.max(np.maximum(constraint_lower - achieved_all, 0.0), initial=0.0)),
                    float(np.max(np.maximum(achieved_all - constraint_upper, 0.0), initial=0.0)),
                    float(np.max(np.maximum(lower_bounds - projected, 0.0), initial=0.0)),
                    float(np.max(np.maximum(projected - upper_bounds, 0.0), initial=0.0)),
                )
                if violation <= max(tolerance * 10, 1e-9):
                    break
        return projected

    def _projected_gradient_qp(
        self,
        initial: np.ndarray,
        alpha: np.ndarray,
        covariance: np.ndarray,
        benchmark: np.ndarray,
        current: np.ndarray,
        costs: np.ndarray,
        lower_bounds: np.ndarray,
        upper_bounds: np.ndarray,
        matrix: np.ndarray,
        constraint_lower: np.ndarray,
        constraint_upper: np.ndarray,
    ) -> tuple[np.ndarray, int]:
        """Solve the convex QP without native BLAS/LAPACK dependencies."""
        weights = self._project_feasible(
            initial, lower_bounds, upper_bounds, matrix, constraint_lower, constraint_upper
        )
        row_bound = float(np.max(np.sum(np.abs(covariance), axis=1), initial=0.0))
        lipschitz = (
            2.0 * self.risk_aversion * row_bound
            + 2.0 * self.transaction_cost_aversion * float(np.max(costs, initial=0.0))
        )
        step = 1.0 / max(lipschitz, 1e-8)
        convergence = max(self.solver_tolerance * 10, 1e-9)
        iterations = 0
        for iterations in range(1, self.max_iterations + 1):
            active = weights - benchmark
            trade = weights - current
            gradient = (
                -alpha
                + 2.0 * self.risk_aversion * np.sum(covariance * active[None, :], axis=1)
                + 2.0 * self.transaction_cost_aversion * costs * trade
            )
            candidate = self._project_feasible(
                weights - step * gradient,
                lower_bounds,
                upper_bounds,
                matrix,
                constraint_lower,
                constraint_upper,
                max_sweeps=120,
            )
            change = float(np.max(np.abs(candidate - weights)))
            weights = candidate
            if change <= convergence:
                break
        return weights, iterations

    def optimize(
        self,
        alpha: pd.Series,
        covariance: pd.DataFrame,
        benchmark_weights: pd.Series,
        *,
        industry_exposure: pd.DataFrame | pd.Series | None = None,
        style_exposure: pd.DataFrame | pd.Series | None = None,
        current_weights: pd.Series | None = None,
        lower_bounds: float | pd.Series = 0.0,
        upper_bounds: float | pd.Series | None = None,
        active_upper_bound: float = 0.10,
        neutrality_tolerance: float = 1e-8,
        transaction_costs: float | pd.Series = 1.0,
    ) -> OptimizationResult:
        index = alpha.index
        benchmark = _as_series(benchmark_weights, index, "benchmark_weights")
        if (benchmark < 0).any() or not np.isclose(benchmark.sum(), 1.0, atol=1e-8):
            raise DataValidationError("benchmark must be long-only and sum to one")
        alpha = _as_series(alpha, index, "alpha")
        covariance = covariance.reindex(index=index, columns=index).astype(float)
        if covariance.isna().any().any():
            raise DataValidationError("covariance does not align with alpha")
        v = self.nearest_psd(covariance.to_numpy(), self.eigenvalue_floor)

        lower = _as_series(lower_bounds, index, "lower_bounds")
        if upper_bounds is None:
            upper = benchmark + active_upper_bound
        else:
            upper = _as_series(upper_bounds, index, "upper_bounds")
        if self.individual_max_weight is not None:
            upper = upper.clip(upper=self.individual_max_weight)
        if (lower > upper).any():
            raise DataValidationError("lower bounds exceed upper bounds")
        if ((benchmark < lower - 1e-12) | (benchmark > upper + 1e-12)).any():
            raise DataValidationError("benchmark is not feasible under the requested bounds")

        current = (
            benchmark.copy()
            if current_weights is None
            else _as_series(current_weights, index, "current_weights")
        )
        costs = _as_series(transaction_costs, index, "transaction_costs")
        if (costs < 0).any():
            raise DataValidationError("transaction costs must be non-negative")

        a_matrix, constraint_lower, constraint_upper, labels = (
            self._constraint_matrix(
                benchmark,
                industry_exposure,
                style_exposure,
                neutrality_tolerance,
            )
        )
        linear_constraints = [
            LinearConstraint(a_matrix[:1], constraint_lower[:1], constraint_upper[:1])
        ]
        if len(a_matrix) > 1:
            linear_constraints.append(
                LinearConstraint(
                    a_matrix[1:], constraint_lower[1:], constraint_upper[1:]
                )
            )
        bounds = Bounds(lower.to_numpy(), upper.to_numpy())
        alpha_array = alpha.to_numpy()
        benchmark_array = benchmark.to_numpy()
        current_array = current.to_numpy()
        cost_array = costs.to_numpy()

        def objective(weights: np.ndarray) -> float:
            active = weights - benchmark_array
            trade = weights - current_array
            risk_gradient = np.sum(v * active[None, :], axis=1)
            return float(
                -np.sum(alpha_array * active)
                + self.risk_aversion * np.sum(active * risk_gradient)
                + self.transaction_cost_aversion * np.sum(cost_array * trade**2)
            )

        def gradient(weights: np.ndarray) -> np.ndarray:
            active = weights - benchmark_array
            trade = weights - current_array
            return (
                -alpha_array
                + 2.0 * self.risk_aversion * np.sum(v * active[None, :], axis=1)
                + 2.0 * self.transaction_cost_aversion * cost_array * trade
            )

        solver_mode = os.environ.get("QUANT_QP_SOLVER", "auto").strip().lower()
        if solver_mode not in {"auto", "slsqp", "projected_gradient"}:
            raise DataValidationError(
                "QUANT_QP_SOLVER must be auto, slsqp or projected_gradient"
            )
        use_projected_gradient = solver_mode == "projected_gradient" or (
            solver_mode == "auto" and "spyder-runtime" in sys.prefix.lower()
        )
        if use_projected_gradient:
            weights, solver_iterations = self._projected_gradient_qp(
                benchmark_array,
                alpha_array,
                v,
                benchmark_array,
                current_array,
                cost_array,
                lower.to_numpy(),
                upper.to_numpy(),
                a_matrix,
                constraint_lower,
                constraint_upper,
            )
            solver_success = True
            solver_message = "projected-gradient QP converged"
        else:
            solution = minimize(
                objective,
                benchmark_array,
                jac=gradient,
                method="SLSQP",
                bounds=bounds,
                constraints=linear_constraints,
                options={
                    "maxiter": self.max_iterations,
                    "ftol": self.solver_tolerance,
                    "disp": False,
                },
            )
            weights = solution.x
            solver_iterations = int(solution.nit)
            solver_success = bool(solution.success)
            solver_message = str(solution.message)
        achieved = np.sum(a_matrix * weights[None, :], axis=1)
        lower_violation = np.maximum(constraint_lower - achieved, 0.0)
        upper_violation = np.maximum(achieved - constraint_upper, 0.0)
        max_constraint_violation = float(
            np.maximum(lower_violation, upper_violation).max(initial=0.0)
        )
        bound_violation = float(
            max(
                np.maximum(lower.to_numpy() - weights, 0.0).max(initial=0.0),
                np.maximum(weights - upper.to_numpy(), 0.0).max(initial=0.0),
            )
        )
        acceptance_tolerance = max(1e-7, neutrality_tolerance * 10)
        if (
            not solver_success
            or max_constraint_violation > acceptance_tolerance
            or bound_violation > acceptance_tolerance
        ):
            raise OptimizationError(
                f"QP failed: {solver_message}; constraint violation="
                f"{max_constraint_violation:.3e}, bound violation={bound_violation:.3e}"
            )

        portfolio = pd.Series(weights, index=index, name="portfolio_weight")
        active = (portfolio - benchmark).rename("active_weight")
        expected_return = float((alpha * active).sum())
        active_values = active.to_numpy()
        active_variance = max(
            float(
                np.sum(
                    active_values
                    * np.sum(v * active_values[None, :], axis=1)
                )
            ),
            0.0,
        )
        active_risk = float(np.sqrt(active_variance))
        information_ratio = expected_return / active_risk if active_risk > 0 else 0.0
        utility = expected_return - self.risk_aversion * active_variance
        turnover = float(np.abs(portfolio - current).sum())
        diagnostics = {
            "sum_weights": float(portfolio.sum()),
            "max_constraint_violation": max_constraint_violation,
            "max_bound_violation": bound_violation,
            "max_weight": float(portfolio.max()),
            "min_weight": float(portfolio.min()),
            "constraint_count": float(len(labels)),
        }
        return OptimizationResult(
            portfolio_weights=portfolio,
            active_weights=active,
            expected_active_return=expected_return,
            active_risk=active_risk,
            expected_information_ratio=information_ratio,
            utility=utility,
            turnover=turnover,
            success=solver_success,
            message=solver_message,
            iterations=solver_iterations,
            constraint_diagnostics=diagnostics,
        )


def generate_synthetic_universe(
    asset_count: int = 60,
    observation_count: int = 320,
    seed: int = 42,
) -> dict[str, object]:
    """Generate deterministic point-in-time-like inputs for the demo only."""
    if asset_count < 20 or observation_count < 260:
        raise ValueError("demo requires at least 20 assets and 260 observations")
    rng = np.random.default_rng(seed)
    assets = pd.Index([f"STK{i:03d}" for i in range(asset_count)], name="asset")
    dates = pd.bdate_range(end="2026-07-31", periods=observation_count)
    industry_names = np.array(["Consumer", "Finance", "Healthcare", "Industry", "Technology"])
    industries = pd.Series(
        np.resize(industry_names, asset_count), index=assets, name="industry"
    ).sample(frac=1.0, random_state=seed)

    market_returns = pd.Series(
        rng.normal(0.00025, 0.0095, observation_count), index=dates, name="market"
    )
    industry_shocks = pd.DataFrame(
        rng.normal(0.00005, 0.005, (observation_count, len(industry_names))),
        index=dates,
        columns=industry_names,
    )
    true_beta = pd.Series(rng.uniform(0.75, 1.25, asset_count), index=assets)
    idiosyncratic_volatility = pd.Series(
        rng.uniform(0.009, 0.018, asset_count), index=assets
    )
    returns = pd.DataFrame(index=dates, columns=assets, dtype=float)
    for asset in assets:
        returns[asset] = (
            true_beta[asset] * market_returns
            + industry_shocks[industries[asset]].to_numpy()
            + rng.normal(0.0, idiosyncratic_volatility[asset], observation_count)
        )
    prices = 50.0 * np.exp(returns.cumsum())

    shares = pd.Series(rng.lognormal(18.0, 0.7, asset_count), index=assets)
    market_cap = prices.iloc[-1] * shares
    book_to_price = pd.Series(rng.uniform(0.25, 1.15, asset_count), index=assets)
    earnings_to_price = pd.Series(rng.normal(0.055, 0.025, asset_count), index=assets)
    dividend_to_price = pd.Series(rng.uniform(0.0, 0.045, asset_count), index=assets)
    historical_growth = pd.Series(rng.normal(0.09, 0.08, asset_count), index=assets)
    expected_growth = 0.55 * historical_growth + pd.Series(
        rng.normal(0.04, 0.06, asset_count), index=assets
    )
    turnover = pd.DataFrame(
        rng.lognormal(-4.5, 0.7, (observation_count, asset_count)),
        index=dates,
        columns=assets,
    )
    debt_to_assets = pd.Series(rng.uniform(0.15, 0.75, asset_count), index=assets)
    total_assets = market_cap / (1.0 - debt_to_assets).clip(lower=0.05)

    return {
        "assets": assets,
        "industries": industries,
        "market_returns": market_returns,
        "returns": returns,
        "prices": prices,
        "shares": shares,
        "market_cap": market_cap,
        "book_equity": market_cap * book_to_price,
        "earnings_ttm": market_cap * earnings_to_price,
        "dividends_ttm": market_cap * dividend_to_price,
        "historical_growth": historical_growth,
        "expected_growth": expected_growth,
        "turnover": turnover,
        "total_assets": total_assets,
        "total_liabilities": total_assets * debt_to_assets,
    }


def plot_weight_comparison(
    weights: pd.DataFrame,
    output_path: Path,
    top_n: int = 20,
    show: bool = False,
) -> None:
    """Render a zero-based grouped horizontal bar comparison."""
    selected = (
        weights.assign(
            display_weight=weights[["benchmark_weight", "portfolio_weight"]].max(axis=1)
        )
        .nlargest(min(top_n, len(weights)), "display_weight")
        .sort_values("display_weight")
    )
    if "spyder-runtime" in sys.prefix.lower() or os.environ.get(
        "QUANT_PLOT_BACKEND", ""
    ).strip().lower() == "stdlib":
        _write_stdlib_weight_png(selected, output_path)
        return

    import matplotlib.pyplot as plt

    if not show:
        plt.switch_backend("Agg")
    positions = np.arange(len(selected))
    height = 0.36
    figure, axis = plt.subplots(figsize=(11, 8), constrained_layout=True)
    axis.barh(
        positions - height / 2,
        selected["benchmark_weight"] * 100,
        height,
        label="Benchmark",
        color="#B8C2CC",
        edgecolor="#59636E",
        linewidth=0.7,
    )
    axis.barh(
        positions + height / 2,
        selected["portfolio_weight"] * 100,
        height,
        label="Optimized",
        color="#3B6FB6",
        edgecolor="#1E3E68",
        linewidth=0.7,
    )
    axis.set_yticks(positions, selected.index)
    axis.set_xlim(left=0)
    axis.set_xlabel("Portfolio weight (%)")
    axis.set_ylabel("Asset")
    axis.set_title(
        "Optimized vs Benchmark Portfolio Weights",
        loc="left",
        weight="bold",
        pad=30,
    )
    axis.text(
        0,
        1.01,
        f"Top {len(selected)} assets by larger displayed weight · synthetic universe",
        transform=axis.transAxes,
        color="#59636E",
        fontsize=9,
    )
    axis.grid(axis="x", color="#D9DEE3", linewidth=0.7, alpha=0.8)
    axis.set_axisbelow(True)
    axis.spines[["top", "right"]].set_visible(False)
    axis.legend(frameon=False, ncol=2, loc="lower right")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=170, bbox_inches="tight", facecolor="white")
    if show:
        plt.show()
    plt.close(figure)


def _write_stdlib_weight_png(selected: pd.DataFrame, output_path: Path) -> None:
    """Write a dependency-free valid PNG for runtimes with broken Matplotlib DLLs."""
    import struct
    import zlib

    width = 1100
    height = max(420, 70 + 30 * len(selected))
    pixels = bytearray([255]) * (width * height * 3)

    def rectangle(x0: int, y0: int, x1: int, y1: int, color: tuple[int, int, int]) -> None:
        x0, x1 = max(0, x0), min(width, x1)
        y0, y1 = max(0, y0), min(height, y1)
        for y in range(y0, y1):
            start = (y * width + x0) * 3
            for x in range(x0, x1):
                offset = start + (x - x0) * 3
                pixels[offset : offset + 3] = bytes(color)

    left, right = 80, width - 40
    maximum = max(
        float(selected[["benchmark_weight", "portfolio_weight"]].max().max()),
        1e-12,
    )
    for grid in range(6):
        x = left + int((right - left) * grid / 5)
        rectangle(x, 25, x + 1, height - 25, (225, 229, 234))
    for position, (_, row) in enumerate(selected.iterrows()):
        center = 45 + position * 30
        benchmark_width = int((right - left) * float(row["benchmark_weight"]) / maximum)
        portfolio_width = int((right - left) * float(row["portfolio_weight"]) / maximum)
        rectangle(left, center - 10, left + benchmark_width, center - 2, (184, 194, 204))
        rectangle(left, center + 2, left + portfolio_width, center + 10, (59, 111, 182))

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + bytes(pixels[row * width * 3 : (row + 1) * width * 3])
        for row in range(height)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, level=6))
        + chunk(b"IEND", b"")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png)


def run_demo(
    output_dir: str | Path | None = "outputs/portfolio_demo",
    asset_count: int = 60,
    seed: int = 42,
    show: bool = False,
    *,
    write_artifacts: bool = True,
    risk_aversion: float = 4.0,
) -> dict[str, object]:
    """Execute the complete synthetic research-to-portfolio workflow.

    ``write_artifacts=False`` keeps the workflow purely in memory.  This is the
    safe mode for serverless/API callers, where the deployment filesystem may
    be read-only and Matplotlib is intentionally not a runtime dependency.
    """
    if write_artifacts and output_dir is None:
        raise ValueError("output_dir is required when write_artifacts=True")
    if not np.isfinite(risk_aversion) or risk_aversion <= 0:
        raise ValueError("risk_aversion must be a positive finite number")
    data = generate_synthetic_universe(asset_count=asset_count, seed=seed)
    assets = data["assets"]
    industries = data["industries"]
    returns = data["returns"]
    market_returns = data["market_returns"]
    market_cap = data["market_cap"]
    benchmark = (market_cap / market_cap.sum()).rename("benchmark_weight")

    value_components = FactorLibrary.value_ratios(
        market_cap,
        data["book_equity"],
        data["earnings_ttm"],
        data["dividends_ttm"],
    )
    raw_factors = pd.DataFrame(index=assets)
    raw_factors["size"] = FactorLibrary.size(
        data["prices"].iloc[-1], data["shares"]
    )
    raw_factors["value"] = value_components.mean(axis=1)
    raw_factors["momentum"] = FactorLibrary.momentum(data["prices"])
    raw_factors["growth"] = FactorLibrary.growth(
        data["historical_growth"], data["expected_growth"]
    )
    raw_factors["volatility"] = FactorLibrary.volatility(returns)
    raw_factors["liquidity"] = FactorLibrary.liquidity(data["turnover"])
    raw_factors["leverage"] = FactorLibrary.leverage(
        data["total_assets"], data["total_liabilities"]
    )["debt_to_assets"]
    raw_factors["market_beta"] = FactorLibrary.market_beta(
        returns, market_returns
    )

    processor = DataProcessor()
    factors = processor.preprocess_factors(raw_factors, industries=industries)
    residual_returns = returns.sub(
        market_returns.to_numpy()[:, None] * raw_factors["market_beta"].to_numpy(),
        axis=0,
    )
    residual_volatility = (
        residual_returns.tail(252).std(ddof=1) * np.sqrt(252)
    ).clip(lower=0.05)

    alpha_generator = AlphaGenerator()
    alpha_result = alpha_generator.generate(
        factors[["value", "momentum", "growth"]],
        residual_volatility,
        expected_ic={"value": 0.04, "momentum": 0.05, "growth": 0.03},
        factor_weights={"value": 0.35, "momentum": 0.40, "growth": 0.25},
        benchmark_weights=benchmark,
        breadth=asset_count * 12 * 0.25,
        transfer_coefficient=0.80,
    )

    industry_dummies = pd.get_dummies(industries, dtype=float)
    risk_exposures = pd.concat([factors, industry_dummies.add_prefix("industry_")], axis=1)
    factor_volatility = pd.Series(0.04, index=risk_exposures.columns)
    factor_volatility.loc["market_beta"] = 0.18
    factor_volatility.loc[industry_dummies.add_prefix("industry_").columns] = 0.06
    factor_covariance = pd.DataFrame(
        np.diag(factor_volatility**2),
        index=risk_exposures.columns,
        columns=risk_exposures.columns,
    )

    optimizer = PortfolioOptimizer(
        risk_aversion=risk_aversion,
        transaction_cost_aversion=0.02,
        # Preserve benchmark feasibility in concentrated synthetic universes.
        individual_max_weight=max(0.10, float(benchmark.max() + 0.02)),
    )
    covariance = optimizer.build_factor_covariance(
        risk_exposures,
        factor_covariance,
        specific_variance=residual_volatility**2,
    )
    # Drop one dummy: full investment plus K-1 industry constraints implies the
    # final industry's active weight is also zero, without a redundant row.
    industry_constraints = industry_dummies.iloc[:, 1:]
    style_constraints = factors[
        ["market_beta", "size", "volatility", "liquidity", "leverage"]
    ]
    optimization = optimizer.optimize(
        alpha_result.composite_alpha,
        covariance,
        benchmark,
        industry_exposure=industry_constraints,
        style_exposure=style_constraints,
        current_weights=benchmark,
        lower_bounds=0.0,
        active_upper_bound=0.10,
        neutrality_tolerance=1e-8,
        transaction_costs=1.0,
    )

    weights = optimization.weights_frame(benchmark)
    holdings = weights.join(industries).join(alpha_result.composite_alpha)

    summary = {
        "asset_count": asset_count,
        "expected_active_return": optimization.expected_active_return,
        "active_risk": optimization.active_risk,
        "optimized_information_ratio": optimization.expected_information_ratio,
        "forecast_fundamental_law_ir": alpha_result.forecast_information_ratio,
        "effective_ic": alpha_result.effective_ic,
        "effective_breadth": alpha_result.breadth,
        "utility": optimization.utility,
        "turnover": optimization.turnover,
        "max_weight": float(optimization.portfolio_weights.max()),
        "solver_iterations": optimization.iterations,
        "constraints": dict(optimization.constraint_diagnostics),
        "notes": [
            "Synthetic data only; no live investment recommendation.",
            "Alpha and covariance inputs use annualized decimal-return units.",
            "Fundamental-law breadth includes a 25% independence haircut.",
        ],
    }
    output_path: Path | None = None
    if write_artifacts:
        output_path = Path(output_dir)  # type: ignore[arg-type]
        output_path.mkdir(parents=True, exist_ok=True)
        holdings.to_csv(output_path / "portfolio_weights.csv", encoding="utf-8-sig")
        factors.to_csv(output_path / "processed_factors.csv", encoding="utf-8-sig")
        alpha_result.factor_alpha.assign(alpha=alpha_result.composite_alpha).to_csv(
            output_path / "alpha_forecasts.csv", encoding="utf-8-sig"
        )
        plot_weight_comparison(
            weights,
            output_path / "portfolio_weights_comparison.png",
            show=show,
        )
        (output_path / "summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        LOGGER.info("Portfolio demo completed: %s", output_path.resolve())
    else:
        LOGGER.info("Portfolio demo completed in memory (no artifacts written)")
    return {
        "summary": summary,
        "weights": weights,
        "holdings": holdings,
        "output_dir": output_path,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the synthetic multi-factor portfolio optimization demo."
    )
    parser.add_argument("--output-dir", default="outputs/portfolio_demo")
    parser.add_argument("--assets", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--show", action="store_true", help="also display the chart")
    parser.add_argument(
        "--no-artifacts",
        action="store_true",
        help="run in memory without writing CSV/JSON/PNG artifacts",
    )
    parser.add_argument("--risk-aversion", type=float, default=4.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_demo(
        output_dir=args.output_dir,
        asset_count=args.assets,
        seed=args.seed,
        show=args.show,
        write_artifacts=not args.no_artifacts,
        risk_aversion=args.risk_aversion,
    )
    print(json.dumps(result["summary"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
