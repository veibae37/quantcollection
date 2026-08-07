"""TW probability-forest signals, half-Kelly sizing and A-share rebalancing.

This module is a faithful Python translation of ``TWrandomf.pine``.  The Pine
"forest" is an auditable ensemble of nine Boolean votes in each regime, not a
fitted sklearn RandomForest.  Probabilities are walk-forward calibrated using
only outcomes that have matured three bars later, so the implementation does
not introduce look-ahead bias.

The public pipeline is intentionally broker-independent.  It produces target
weights and proposed orders; live MiniQMT execution lives in
``miniqmt_kelly_executor.py`` and is guarded separately.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import math
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping

import numpy as np
import pandas as pd


REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")


class SignalDataError(ValueError):
    """Raised when price history cannot safely produce a signal."""


@dataclass(frozen=True)
class PineForestConfig:
    bull_threshold: float = 0.60
    bear_threshold: float = 0.40
    probability_smoothing: int = 3
    flow_probability_shift: float = 0.08
    training_window: int = 400
    retrain_every_bars: int = 20
    minimum_bin_samples: int = 6
    calibration_weight: float = 0.60
    calibration_bins: int = 10

    def __post_init__(self) -> None:
        if not 0.5 <= self.bull_threshold <= 1:
            raise ValueError("bull_threshold must be between 0.5 and 1")
        if not 0 <= self.bear_threshold <= 0.5:
            raise ValueError("bear_threshold must be between 0 and 0.5")
        if self.bear_threshold > self.bull_threshold:
            raise ValueError("bear_threshold cannot exceed bull_threshold")
        if self.probability_smoothing < 1 or self.training_window < 100:
            raise ValueError("invalid smoothing or training window")
        if self.retrain_every_bars < 1 or self.minimum_bin_samples < 1:
            raise ValueError("invalid calibration settings")
        if not 0 <= self.calibration_weight <= 1:
            raise ValueError("calibration_weight must be between 0 and 1")


@dataclass(frozen=True)
class RegimeInput:
    """External regime state corresponding to the Pine manual/API inputs."""

    intervention: bool = False
    active_flow_value: float = 0.0
    active_flow_z: float = 0.0
    source: str = "NORMAL"

    @property
    def active_direction(self) -> float:
        return float(np.sign(self.active_flow_value))


@dataclass(frozen=True)
class KellyConfig:
    fraction: float = 0.5
    payoff_odds: float = 1.0
    long_only: bool = True
    require_bull_signal: bool = True
    max_stock_weight: float = 0.10
    max_gross_exposure: float = 0.95
    cash_buffer: float = 0.02
    lot_size: int = 100
    minimum_trade_value: float = 2_000.0

    def __post_init__(self) -> None:
        if not 0 < self.fraction <= 1:
            raise ValueError("Kelly fraction must be in (0, 1]")
        if self.payoff_odds <= 0:
            raise ValueError("payoff_odds must be positive")
        if not 0 < self.max_stock_weight <= 1:
            raise ValueError("max_stock_weight must be in (0, 1]")
        if not 0 < self.max_gross_exposure <= 1:
            raise ValueError("max_gross_exposure must be in (0, 1]")
        if not 0 <= self.cash_buffer < 1:
            raise ValueError("cash_buffer must be in [0, 1)")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")


def manual_regime(
    net_flow_bn: float,
    basket_aum_bn: float,
    flow_z: float,
    *,
    vendor_strong: bool = False,
    absolute_flow_threshold_bn: float = 5.0,
    flow_ratio_threshold_bps: float = 20.0,
    flow_z_threshold: float = 2.0,
) -> RegimeInput:
    """Evaluate the Pine manual intervention gates without market look-ahead."""
    ratio_bps = net_flow_bn / basket_aum_bn * 10_000 if basket_aum_bn > 0 else 0.0
    absolute_z_gate = (
        abs(net_flow_bn) >= absolute_flow_threshold_bn
        and abs(flow_z) >= flow_z_threshold
    )
    ratio_gate = abs(ratio_bps) >= flow_ratio_threshold_bps
    return RegimeInput(
        intervention=bool(vendor_strong or absolute_z_gate or ratio_gate),
        active_flow_value=float(net_flow_bn),
        active_flow_z=float(flow_z),
        source="MANUAL_API",
    )


def _rolling_z(values: pd.Series, length: int) -> pd.Series:
    mean = values.rolling(length, min_periods=length).mean()
    deviation = values.rolling(length, min_periods=length).std(ddof=0)
    return ((values - mean) / deviation.replace(0, np.nan)).fillna(0.0)


def _rma(values: pd.Series, length: int) -> pd.Series:
    return values.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    change = close.diff()
    gain = _rma(change.clip(lower=0), length)
    loss = _rma((-change).clip(lower=0), length)
    rs = gain / loss.replace(0, np.nan)
    result = 100 - 100 / (1 + rs)
    return result.where(loss.ne(0), 100.0).where(gain.ne(0), 0.0)


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return _rma(ranges.max(axis=1), length)


def _vote(condition: pd.Series) -> pd.Series:
    return condition.fillna(False).astype(float)


class PineProbabilityForest:
    """Translate the Pine votes and rolling probability calibration exactly."""

    def __init__(self, config: PineForestConfig | None = None) -> None:
        self.config = config or PineForestConfig()

    def calculate(
        self,
        history: pd.DataFrame,
        regime: RegimeInput | pd.Series | None = None,
        active_direction: float | pd.Series | None = None,
    ) -> pd.DataFrame:
        frame = history.copy()
        missing = [column for column in REQUIRED_OHLCV if column not in frame]
        if missing:
            raise SignalDataError(f"OHLCV history missing columns: {missing}")
        frame = frame.loc[:, REQUIRED_OHLCV].apply(pd.to_numeric, errors="coerce")
        frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
        if len(frame) < 100:
            raise SignalDataError("at least 100 complete bars are required")
        if (frame[["open", "high", "low", "close"]] <= 0).any().any():
            raise SignalDataError("OHLC prices must be positive")
        if (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any():
            raise SignalDataError("high price is inconsistent with OHLC")
        if (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any():
            raise SignalDataError("low price is inconsistent with OHLC")

        close = frame["close"]
        rsi14 = _rsi(close, 14)
        atr14 = _atr(frame, 14)
        atr_pct = atr14 / close
        atr_pct_average = atr_pct.rolling(50, min_periods=50).mean()
        momentum10 = close.diff(10)
        momentum_z = _rolling_z(momentum10, 60)
        ema20 = close.ewm(span=20, adjust=False, min_periods=20).mean()
        ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
        ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False, min_periods=9).mean()
        macd_histogram = macd_line - macd_signal
        macd_z = _rolling_z(macd_line, 60)
        return1 = close.pct_change(1, fill_method=None)
        return3 = close.pct_change(3, fill_method=None)
        realized_volatility10 = return1.rolling(10, min_periods=10).std(ddof=0)
        volatility_average = realized_volatility10.rolling(50, min_periods=50).mean()
        bb_middle = close.rolling(20, min_periods=20).mean()
        bb_deviation = close.rolling(20, min_periods=20).std(ddof=0)
        bb_z = ((close - bb_middle) / bb_deviation.replace(0, np.nan)).fillna(0.0)
        candle_range = (frame["high"] - frame["low"]).clip(lower=1e-12)
        lower_wick_ratio = (frame[["open", "close"]].min(axis=1) - frame["low"]) / candle_range

        momentum_votes = sum(
            [
                _vote(momentum_z > 0),
                _vote(rsi14 > 50),
                _vote(macd_line > macd_signal),
                _vote(macd_histogram > 0),
                _vote(close > ema20),
                _vote((momentum_z > 0.50) & (rsi14 < 70)),
                _vote((macd_z > 0) & (atr_pct < atr_pct_average * 1.50)),
                _vote((return3 > 0) & (macd_histogram > macd_histogram.shift(1))),
                _vote((close > bb_middle) & (momentum10 > 0)),
            ]
        )
        reversal_votes = sum(
            [
                _vote(rsi14 < 35),
                _vote(bb_z < -1),
                _vote(return1 < -atr_pct),
                _vote(return3 < -1.50 * atr_pct),
                _vote(lower_wick_ratio > 0.40),
                _vote((close > close.shift(1)) & (frame["low"] < frame["low"].shift(1))),
                _vote((realized_volatility10 > volatility_average) & (rsi14 < 45)),
                _vote((bb_z < 0) & (bb_z > bb_z.shift(1))),
                _vote((rsi14 < 45) & (rsi14 > rsi14.shift(1))),
            ]
        )

        if isinstance(regime, pd.Series):
            intervention = regime.reindex(frame.index).fillna(False).astype(bool)
            regime_source = "SERIES"
        else:
            regime_value = regime or RegimeInput()
            intervention = pd.Series(regime_value.intervention, index=frame.index)
            regime_source = regime_value.source
        if isinstance(active_direction, pd.Series):
            direction = active_direction.reindex(frame.index).fillna(0.0).clip(-1, 1)
        elif active_direction is None:
            scalar = regime.active_direction if isinstance(regime, RegimeInput) else 0.0
            direction = pd.Series(scalar, index=frame.index)
        else:
            direction = pd.Series(float(np.sign(active_direction)), index=frame.index)

        momentum_probability = momentum_votes / 9.0
        reversal_probability = (reversal_votes / 9.0 + direction * self.config.flow_probability_shift).clip(0, 1)
        raw = momentum_probability.where(~intervention, reversal_probability)
        features_ready = (
            rsi14.notna()
            & atr_pct_average.notna()
            & momentum10.rolling(60, min_periods=60).std(ddof=0).notna()
            & realized_volatility10.notna()
        )
        calibrated, samples = self._walk_forward_calibrate(raw, intervention, close, features_ready)
        up_probability = calibrated.ewm(
            span=self.config.probability_smoothing,
            adjust=False,
            min_periods=1,
        ).mean().clip(0, 1)
        down_probability = 1.0 - up_probability
        game = np.select(
            [up_probability >= self.config.bull_threshold, up_probability <= self.config.bear_threshold],
            ["BULL", "BEAR"],
            default="WAIT",
        )
        result = pd.DataFrame(
            {
                "raw_up_probability": raw,
                "up_probability": up_probability,
                "down_probability": down_probability,
                "game": game,
                "model": np.where(intervention, "REVERSAL_VOL", "MOMENTUM"),
                "intervention": intervention,
                "calibration_samples": samples,
                "regime_source": regime_source,
            },
            index=frame.index,
        )
        return result.loc[features_ready]

    def _walk_forward_calibrate(
        self,
        raw: pd.Series,
        intervention: pd.Series,
        close: pd.Series,
        features_ready: pd.Series,
    ) -> tuple[pd.Series, pd.Series]:
        bins = self.config.calibration_bins
        cells = bins * 2
        outcome_sums = np.zeros(cells, dtype=float)
        outcome_counts = np.zeros(cells, dtype=float)
        fitted = np.full(cells, 0.5, dtype=float)
        rolling: deque[tuple[int, float]] = deque()
        blended = pd.Series(np.nan, index=raw.index, dtype=float)
        sample_count = pd.Series(0.0, index=raw.index, dtype=float)

        for position in range(len(raw)):
            matured = position - 3
            if matured >= 0 and bool(features_ready.iloc[matured]) and np.isfinite(raw.iloc[matured]):
                probability = float(np.clip(raw.iloc[matured], 0, 1))
                bin_number = min(int(math.floor(probability * bins)), bins - 1)
                cell = (bins if bool(intervention.iloc[matured]) else 0) + bin_number
                outcome = float(close.iloc[position] > close.iloc[matured])
                outcome_sums[cell] += outcome
                outcome_counts[cell] += 1
                rolling.append((cell, outcome))
                if len(rolling) > self.config.training_window:
                    expired_cell, expired_outcome = rolling.popleft()
                    outcome_sums[expired_cell] -= expired_outcome
                    outcome_counts[expired_cell] = max(outcome_counts[expired_cell] - 1, 0)

            if position % self.config.retrain_every_bars == 0:
                for cell in range(cells):
                    center = ((cell % bins) + 0.5) / bins
                    if outcome_counts[cell] >= self.config.minimum_bin_samples:
                        fitted[cell] = (outcome_sums[cell] + 1) / (outcome_counts[cell] + 2)
                    else:
                        fitted[cell] = center

            probability = raw.iloc[position]
            if not np.isfinite(probability):
                continue
            bin_number = min(int(math.floor(float(np.clip(probability, 0, 1)) * bins)), bins - 1)
            cell = (bins if bool(intervention.iloc[position]) else 0) + bin_number
            count = outcome_counts[cell]
            sample_count.iloc[position] = count
            if count >= self.config.minimum_bin_samples:
                blended.iloc[position] = (
                    float(probability) * (1 - self.config.calibration_weight)
                    + fitted[cell] * self.config.calibration_weight
                )
            else:
                blended.iloc[position] = float(probability)
        return blended.clip(0, 1), sample_count


def half_kelly_fraction(
    up_probability: float,
    down_probability: float | None = None,
    *,
    payoff_odds: float = 1.0,
    fraction: float = 0.5,
    long_only: bool = True,
) -> float:
    """Return fractional Kelly: fraction * (b*p-q)/b.

    With even odds (b=1) and half Kelly this is
    ``0.5 * (P(up)-P(down)) == P(up)-0.5``.
    """
    p = float(up_probability)
    q = float(1 - p if down_probability is None else down_probability)
    if not np.isfinite([p, q]).all() or p < 0 or q < 0 or not np.isclose(p + q, 1, atol=1e-6):
        raise ValueError("up/down probabilities must be finite, non-negative and sum to one")
    if payoff_odds <= 0 or not 0 < fraction <= 1:
        raise ValueError("invalid Kelly odds or fraction")
    value = fraction * (payoff_odds * p - q) / payoff_odds
    return float(max(value, 0.0) if long_only else value)


def generate_synthetic_history(
    ticker: str,
    *,
    bars: int = 520,
    seed: int = 42,
    reference_price: float = 20.0,
    momentum_hint: float = 0.0,
) -> pd.DataFrame:
    """Create deterministic 15-minute OHLCV solely for web/demo validation."""
    if bars < 120:
        raise ValueError("synthetic history requires at least 120 bars")
    stable = int.from_bytes(hashlib.sha256(ticker.encode("utf-8")).digest()[:8], "big")
    rng = np.random.default_rng((stable + int(seed)) % (2**32 - 1))
    drift = float(np.clip(momentum_hint / 100 / 520, -0.0007, 0.0007))
    noise = rng.normal(drift, 0.0065, bars)
    phase = stable % 5
    if phase == 0:
        noise[-36:] += 0.0022
    elif phase == 1:
        noise[-30:] -= 0.0020
    elif phase == 2:
        noise[-8:] += np.linspace(-0.010, 0.012, 8)
    close = max(float(reference_price), 1.0) * np.exp(np.cumsum(noise))
    open_price = np.r_[close[0] * (1 - noise[0] / 2), close[:-1]]
    spread = np.abs(rng.normal(0.0035, 0.0015, bars))
    high = np.maximum(open_price, close) * (1 + spread)
    low = np.minimum(open_price, close) * (1 - spread)
    volume = rng.lognormal(mean=13.1, sigma=0.55, size=bars).round()
    index = pd.date_range(end=dt.datetime.now().replace(second=0, microsecond=0), periods=bars, freq="15min")
    return pd.DataFrame(
        {"open": open_price, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _target_shares(weight: float, total_asset: float, price: float, lot_size: int) -> int:
    if weight <= 0 or total_asset <= 0 or price <= 0:
        return 0
    return int(math.floor(weight * total_asset / price / lot_size) * lot_size)


def plan_rebalance_orders(
    portfolio: list[dict[str, object]],
    *,
    total_asset: float,
    available_cash: float,
    current_positions: Mapping[str, Mapping[str, float]] | None = None,
    config: KellyConfig | None = None,
) -> list[dict[str, object]]:
    """Translate target weights to lot-rounded sell-first A-share orders."""
    settings = config or KellyConfig()
    if total_asset <= 0 or available_cash < 0:
        raise ValueError("invalid account asset values")
    positions = current_positions or {}
    by_ticker = {str(item["ticker"]): item for item in portfolio}
    tickers = sorted(set(by_ticker) | set(positions))
    orders: list[dict[str, object]] = []
    for ticker in tickers:
        item = by_ticker.get(ticker, {})
        position = positions.get(ticker, {})
        price = float(item.get("latest_price", position.get("last_price", 0.0)))
        current = int(position.get("volume", 0))
        available = int(position.get("can_use_volume", current))
        target = _target_shares(float(item.get("target_weight", 0.0)), total_asset, price, settings.lot_size)
        difference = target - current
        if difference < 0:
            quantity = min(-difference, available)
            quantity = quantity // settings.lot_size * settings.lot_size
            if quantity > 0 and quantity * price >= settings.minimum_trade_value:
                orders.append(
                    {"ticker": ticker, "side": "sell", "quantity": quantity, "reference_price": round(price, 3), "estimated_value": round(quantity * price, 2), "reason": "目标权重下降/T+1可卖量约束"}
                )
        elif difference > 0:
            quantity = difference // settings.lot_size * settings.lot_size
            if quantity > 0 and quantity * price >= settings.minimum_trade_value:
                orders.append(
                    {"ticker": ticker, "side": "buy", "quantity": quantity, "reference_price": round(price, 3), "estimated_value": round(quantity * price, 2), "reason": "半凯利目标权重上调"}
                )

    sells = sorted((item for item in orders if item["side"] == "sell"), key=lambda item: str(item["ticker"]))
    buys = sorted((item for item in orders if item["side"] == "buy"), key=lambda item: str(item["ticker"]))
    cash_budget = max(float(available_cash) - total_asset * settings.cash_buffer, 0.0)
    accepted_buys: list[dict[str, object]] = []
    for order in buys:
        value = float(order["estimated_value"])
        if value <= cash_budget + 1e-8:
            accepted_buys.append(order)
            cash_budget -= value
    return sells + accepted_buys


def run_tw_kelly_portfolio(
    *,
    top_n: int = 20,
    universe_size: int = 120,
    selection_data_mode: str = "demo",
    history_mode: str = "demo",
    seed: int = 42,
    total_asset: float = 1_000_000.0,
    available_cash: float | None = None,
    regime: RegimeInput | None = None,
    kelly_config: KellyConfig | None = None,
    histories: Mapping[str, pd.DataFrame] | None = None,
    current_positions: Mapping[str, Mapping[str, float]] | None = None,
    selection_result: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Select 20 A-shares, calculate Pine probabilities and rebalance weights."""
    if not 1 <= top_n <= 50:
        raise ValueError("top_n must be between 1 and 50")
    if history_mode not in {"demo", "provided"}:
        raise ValueError("history_mode must be demo or provided")
    if selection_result is None:
        from a_share_selector import run_a_share_selection

        selection = run_a_share_selection(
            top_n=top_n,
            universe_size=max(universe_size, top_n),
            data_mode=selection_data_mode,
        )
    else:
        selection = dict(selection_result)
    selected = selection["selections"]
    if len(selected) != top_n:
        raise SignalDataError(f"selector returned {len(selected)} stocks, expected {top_n}")

    settings = kelly_config or KellyConfig()
    active_regime = regime or RegimeInput()
    selected_weight_sum = sum(float(item["target_weight_pct"]) for item in selected)
    if selected_weight_sum <= 0:
        raise SignalDataError("selected benchmark weights are not positive")

    def build_position(stock: Mapping[str, object]) -> dict[str, object]:
        ticker = str(stock["ticker"])
        if history_mode == "provided":
            if histories is None or ticker not in histories:
                raise SignalDataError(f"missing provided history for {ticker}")
            history = histories[ticker]
        else:
            history = generate_synthetic_history(
                ticker,
                seed=seed,
                reference_price=float(stock["latest_price"]),
                momentum_hint=float(stock["momentum_60d_pct"]),
            )
        probabilities = PineProbabilityForest().calculate(history, regime=active_regime)
        if probabilities.empty:
            raise SignalDataError(f"probability model produced no valid rows for {ticker}")
        last = probabilities.iloc[-1]
        up = float(last["up_probability"])
        down = float(last["down_probability"])
        kelly = half_kelly_fraction(
            up,
            down,
            payoff_odds=settings.payoff_odds,
            fraction=settings.fraction,
            long_only=settings.long_only,
        )
        game = str(last["game"])
        if settings.require_bull_signal and game != "BULL":
            kelly = 0.0
        base_weight = float(stock["target_weight_pct"]) / selected_weight_sum
        target_weight = min(base_weight * kelly, settings.max_stock_weight)
        target_weight = min(target_weight, settings.max_gross_exposure)
        latest_price = float(history["close"].iloc[-1])
        return {
            "rank": int(stock["rank"]),
            "ticker": ticker,
            "name": str(stock["name"]),
            "board": str(stock["board"]),
            "model": str(last["model"]),
            "game": game,
            "up_probability": round(up, 6),
            "down_probability": round(down, 6),
            "raw_up_probability": round(float(last["raw_up_probability"]), 6),
            "calibration_samples": int(last["calibration_samples"]),
            "half_kelly_fraction": round(kelly, 6),
            "selector_weight_normalized": round(base_weight, 8),
            "target_weight": round(target_weight, 8),
            "target_weight_pct": round(target_weight * 100, 4),
            "latest_price": round(latest_price, 3),
            "selection_alpha_score": float(stock["alpha_score"]),
        }

    # Each symbol has an independent calibration table. Four workers reduce
    # serverless latency while keeping deterministic ordering via map().
    with ThreadPoolExecutor(max_workers=min(4, len(selected))) as executor:
        portfolio = list(executor.map(build_position, selected))

    gross = sum(float(item["target_weight"]) for item in portfolio)
    if gross > settings.max_gross_exposure:
        scale = settings.max_gross_exposure / gross
        for item in portfolio:
            item["target_weight"] = round(float(item["target_weight"]) * scale, 8)
            item["target_weight_pct"] = round(float(item["target_weight"]) * 100, 4)
        gross = settings.max_gross_exposure
    portfolio.sort(key=lambda item: (-float(item["target_weight"]), int(item["rank"])))
    for display_rank, item in enumerate(portfolio, start=1):
        item["position_rank"] = display_rank

    orders = plan_rebalance_orders(
        portfolio,
        total_asset=total_asset,
        available_cash=total_asset if available_cash is None else available_cash,
        current_positions=current_positions,
        config=settings,
    )
    return {
        "program": "TWrandomf.pine → Python half-Kelly rebalance",
        "mode": "tw_kelly_rebalance",
        "is_synthetic": bool(selection.get("is_synthetic")) or history_mode == "demo",
        "source": f"{selection.get('source')} + {'deterministic 15m demo OHLCV' if history_mode == 'demo' else 'provided OHLCV'}",
        "data_as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": {
            "selected_count": len(portfolio),
            "bull_count": sum(item["game"] == "BULL" for item in portfolio),
            "wait_count": sum(item["game"] == "WAIT" for item in portfolio),
            "bear_count": sum(item["game"] == "BEAR" for item in portfolio),
            "target_gross_exposure_pct": round(gross * 100, 4),
            "target_cash_pct": round((1 - gross) * 100, 4),
            "proposed_order_count": len(orders),
            "total_asset": round(float(total_asset), 2),
            "half_kelly": True,
        },
        "portfolio": portfolio,
        "orders": orders,
        "methodology": {
            "pine_translation": "9-vote MOMENTUM/REVERSAL_VOL forest with three-bar walk-forward bin calibration",
            "kelly_formula": "half Kelly = 0.5 × (b×P(up)-P(down))/b; b=1 by default",
            "allocation": "top-20 selector weights are normalized, multiplied by long-only half Kelly, with cash retained",
            "execution": "web output is read-only; MiniQMT execution requires a separate local guarded command",
            "risk_limits": f"single stock <= {settings.max_stock_weight:.0%}; gross <= {settings.max_gross_exposure:.0%}; A-share lots={settings.lot_size}",
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_tw_kelly_portfolio(), ensure_ascii=False, indent=2))
