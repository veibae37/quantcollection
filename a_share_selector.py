"""A-share multi-factor selection and portfolio construction for the web app.

The live path consumes one Eastmoney market snapshot with AkShare-compatible
field definitions so it can finish inside a serverless request.  It deliberately
avoids per-stock history calls and AkShare's intentionally delayed pagination.
The resulting model is a liquid-universe, point-in-time *snapshot* model rather
than a backtest or a claim about future returns.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from dataclasses import dataclass, replace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from quant_portfolio_system import (
    AlphaGenerator,
    DataProcessor,
    DataValidationError,
    PortfolioOptimizer,
)


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
REQUIRED_COLUMNS = {
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "成交额",
    "振幅",
    "换手率",
    "市盈率-动态",
    "市净率",
    "总市值",
    "流通市值",
    "60日涨跌幅",
    "年初至今涨跌幅",
}

_LIVE_CACHE: dict[str, Any] = {}


class MarketDataUnavailable(RuntimeError):
    """Raised when the live A-share snapshot cannot be obtained."""


@dataclass(frozen=True)
class AShareSelectionConfig:
    top_n: int = 20
    universe_size: int = 120
    min_market_cap_cny: float = 3_000_000_000.0
    max_market_cap_cny: float = 3_000_000_000_000.0
    min_turnover_amount_cny: float = 50_000_000.0
    max_dynamic_pe: float = 150.0
    max_pb: float = 20.0
    max_weight: float = 0.08
    active_upper_bound: float = 0.03
    risk_aversion: float = 3.0
    neutrality_tolerance: float = 0.005
    include_chinext: bool = True
    include_star: bool = True
    data_mode: str = "auto"

    def validate(self) -> "AShareSelectionConfig":
        if not 5 <= self.top_n <= 50:
            raise ValueError("选股数量必须在 5 到 50 之间")
        if not max(30, self.top_n + 10) <= self.universe_size <= 250:
            raise ValueError("候选池数量必须在 max(30, 选股数量+10) 到 250 之间")
        if not 0.03 <= self.max_weight <= 0.20:
            raise ValueError("单只股票权重上限必须在 3% 到 20% 之间")
        if self.max_weight * self.universe_size < 1:
            raise ValueError("权重上限与候选池规模组合不可行")
        if not 0 < self.active_upper_bound <= self.max_weight:
            raise ValueError("主动权重上限必须大于 0 且不超过个股权重上限")
        if self.risk_aversion <= 0:
            raise ValueError("风险厌恶系数必须大于 0")
        if self.data_mode not in {"auto", "live", "demo"}:
            raise ValueError("data_mode 仅支持 auto、live 或 demo")
        return self


@dataclass(frozen=True)
class SnapshotResult:
    data: pd.DataFrame
    source: str
    fetched_at: str
    is_synthetic: bool
    fallback_reason: str | None = None


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class AShareDataProvider:
    """Fetch one live market snapshot with a short warm-instance cache."""

    def __init__(self, cache_seconds: int | None = None) -> None:
        self.cache_seconds = cache_seconds or int(
            os.environ.get("A_SHARE_CACHE_SECONDS", "300")
        )

    def fetch(self, mode: str = "auto") -> SnapshotResult:
        if mode == "demo":
            return self._demo_result()
        try:
            return self._fetch_live()
        except Exception as exc:
            if mode == "live" or not _env_flag(
                "A_SHARE_ALLOW_SYNTHETIC_FALLBACK", True
            ):
                raise MarketDataUnavailable(
                    f"A 股实时行情获取失败：{type(exc).__name__}"
                ) from exc
            demo = self._demo_result()
            return replace(
                demo,
                fallback_reason=f"实时数据不可用，已切换为演示数据（{type(exc).__name__}）",
            )

    def _fetch_live(self) -> SnapshotResult:
        now = time.monotonic()
        if (
            _LIVE_CACHE.get("data") is not None
            and now - float(_LIVE_CACHE.get("stored_at", 0)) < self.cache_seconds
        ):
            return SnapshotResult(
                data=_LIVE_CACHE["data"].copy(),
                source="AkShare / 东方财富（缓存快照）",
                fetched_at=str(_LIVE_CACHE["fetched_at"]),
                is_synthetic=False,
            )

        attempts = max(1, min(int(os.environ.get("AKSHARE_RETRY_ATTEMPTS", "2")), 4))
        backoff = max(
            0.0, min(float(os.environ.get("AKSHARE_RETRY_BACKOFF_SECONDS", "0.8")), 3.0)
        )
        last_error: Exception | None = None
        frame: pd.DataFrame | None = None
        for attempt in range(attempts):
            try:
                frame = self._fetch_eastmoney_snapshot()
                if frame is None or frame.empty:
                    raise MarketDataUnavailable("行情接口返回空表")
                break
            except Exception as exc:  # provider/network exceptions vary by version
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(backoff * (attempt + 1))
        if frame is None or frame.empty:
            raise MarketDataUnavailable("无法取得实时行情") from last_error

        fetched_at = dt.datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds")
        _LIVE_CACHE.update(
            data=frame.copy(), stored_at=time.monotonic(), fetched_at=fetched_at
        )
        return SnapshotResult(
            data=frame,
            source="东方财富实时行情（AkShare 兼容字段）",
            fetched_at=fetched_at,
            is_synthetic=False,
        )

    @staticmethod
    def _fetch_eastmoney_snapshot() -> pd.DataFrame:
        """Fetch all A shares in one bounded request for serverless execution."""
        import requests

        timeout = max(
            3.0,
            min(float(os.environ.get("A_SHARE_HTTP_TIMEOUT_SECONDS", "8")), 15.0),
        )
        response = requests.get(
            "https://82.push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1",
                "pz": "6000",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f12",
                "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
                "fields": "f2,f3,f6,f7,f8,f9,f12,f14,f20,f21,f23,f24,f25",
            },
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; QuantConsole/1.0)",
                "Accept": "application/json,text/plain,*/*",
            },
            timeout=(3.0, timeout),
        )
        response.raise_for_status()
        payload = response.json()
        rows = (payload.get("data") or {}).get("diff") or []
        if not rows:
            raise MarketDataUnavailable("东方财富行情接口返回空表")
        frame = pd.DataFrame(rows).rename(
            columns={
                "f12": "代码",
                "f14": "名称",
                "f2": "最新价",
                "f3": "涨跌幅",
                "f6": "成交额",
                "f7": "振幅",
                "f8": "换手率",
                "f9": "市盈率-动态",
                "f23": "市净率",
                "f20": "总市值",
                "f21": "流通市值",
                "f24": "60日涨跌幅",
                "f25": "年初至今涨跌幅",
            }
        )
        return frame[list(REQUIRED_COLUMNS)]

    @staticmethod
    def _demo_result() -> SnapshotResult:
        frame = generate_demo_snapshot()
        return SnapshotResult(
            data=frame,
            source="确定性合成 A 股演示快照",
            fetched_at=dt.datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds"),
            is_synthetic=True,
        )


def _market_board(code: str) -> str | None:
    if code.startswith(("600", "601", "603", "605")):
        return "沪市主板"
    if code.startswith(("000", "001", "002", "003")):
        return "深市主板"
    if code.startswith(("300", "301")):
        return "创业板"
    if code.startswith(("688", "689")):
        return "科创板"
    return None


def _ticker(code: str) -> str:
    return f"{code}.SH" if code.startswith("6") else f"{code}.SZ"


def _cap_weights(raw_values: pd.Series, cap: float) -> pd.Series:
    """Normalize positive values with a deterministic upper-cap water fill."""
    values = raw_values.astype(float).clip(lower=0)
    if values.sum() <= 0 or cap * len(values) < 1 - 1e-12:
        raise DataValidationError("基准权重无法归一化或权重上限不可行")
    weights = pd.Series(0.0, index=values.index)
    remaining = pd.Series(True, index=values.index)
    remaining_mass = 1.0
    for _ in range(len(values) + 1):
        scaled = values[remaining] / values[remaining].sum() * remaining_mass
        over = scaled > cap + 1e-14
        if not over.any():
            weights.loc[scaled.index] = scaled
            break
        capped_names = scaled.index[over]
        weights.loc[capped_names] = cap
        remaining.loc[capped_names] = False
        remaining_mass = 1.0 - float(weights.sum())
    if not np.isclose(weights.sum(), 1.0, atol=1e-10):
        raise DataValidationError("基准权重上限归一化失败")
    return weights.rename("benchmark_weight")


def generate_demo_snapshot(asset_count: int = 360, seed: int = 20260806) -> pd.DataFrame:
    """Create a deterministic, clearly labelled A-share-shaped test snapshot."""
    if asset_count < 80:
        raise ValueError("演示快照至少需要 80 只股票")
    rng = np.random.default_rng(seed)
    prefixes = np.resize(
        np.array(["600", "601", "603", "000", "001", "002", "300", "301", "688"]),
        asset_count,
    )
    codes = [f"{prefix}{position % 1000:03d}" for position, prefix in enumerate(prefixes)]
    market_cap = np.exp(rng.normal(np.log(22e9), 1.05, asset_count)).clip(2e9, 1.8e12)
    float_ratio = rng.uniform(0.35, 1.0, asset_count)
    turnover = rng.lognormal(np.log(2.2), 0.7, asset_count).clip(0.05, 25)
    amount = (market_cap * float_ratio * turnover / 100 * rng.uniform(0.35, 1.3, asset_count)).clip(1e6, 8e9)
    frame = pd.DataFrame(
        {
            "代码": codes,
            "名称": [f"样本公司{position + 1:03d}" for position in range(asset_count)],
            "最新价": rng.lognormal(np.log(18), 0.65, asset_count).clip(1.2, 180),
            "涨跌幅": rng.normal(0.15, 3.2, asset_count).clip(-19.8, 19.8),
            "成交额": amount,
            "振幅": rng.lognormal(np.log(3.2), 0.45, asset_count).clip(0.3, 18),
            "换手率": turnover,
            "市盈率-动态": rng.lognormal(np.log(28), 0.75, asset_count).clip(3, 240),
            "市净率": rng.lognormal(np.log(2.4), 0.65, asset_count).clip(0.35, 28),
            "总市值": market_cap,
            "流通市值": market_cap * float_ratio,
            "60日涨跌幅": rng.normal(4, 19, asset_count).clip(-58, 120),
            "年初至今涨跌幅": rng.normal(7, 27, asset_count).clip(-70, 180),
        }
    )
    frame.loc[0, "名称"] = "ST演示"
    frame.loc[1, "成交额"] = 0
    frame.loc[2, "涨跌幅"] = 10.0
    return frame


class AShareSelector:
    """Build an investable A-share snapshot universe and optimize active weights."""

    FACTOR_IC = {
        "value_pe": 0.025,
        "value_pb": 0.020,
        "momentum_60d": 0.030,
        "momentum_ytd": 0.015,
        "low_volatility": 0.020,
        "turnover_quality": 0.010,
    }
    FACTOR_WEIGHTS = {
        "value_pe": 0.22,
        "value_pb": 0.18,
        "momentum_60d": 0.25,
        "momentum_ytd": 0.10,
        "low_volatility": 0.17,
        "turnover_quality": 0.08,
    }
    FACTOR_LABELS = {
        "value_pe": "低估值(P/E)",
        "value_pb": "低估值(P/B)",
        "momentum_60d": "60日动量",
        "momentum_ytd": "年初至今动量",
        "low_volatility": "低波动",
        "turnover_quality": "适度换手",
    }

    def __init__(self, config: AShareSelectionConfig | None = None) -> None:
        self.config = (config or AShareSelectionConfig()).validate()

    def run(self, snapshot: SnapshotResult) -> dict[str, Any]:
        eligible, filter_stats = self._build_universe(snapshot.data)
        universe = eligible.nlargest(self.config.universe_size, "成交额").copy()
        if len(universe) < max(30, self.config.top_n + 10):
            raise DataValidationError(
                f"过滤后仅剩 {len(universe)} 只股票，不足以构建稳健候选池"
            )

        universe.index = pd.Index(universe["ticker"], name="ticker")
        benchmark = _cap_weights(
            np.sqrt(universe["流通市值"]), cap=min(self.config.max_weight, 0.05)
        )
        raw_factors = self._raw_factors(universe)
        processor = DataProcessor()
        factors = processor.preprocess_factors(
            raw_factors, industries=universe["board"]
        )

        residual_volatility = (
            universe["振幅"].clip(lower=0.5) / 100 * np.sqrt(252) / 1.8
        ).clip(lower=0.15, upper=0.75)
        residual_volatility.name = "residual_volatility"
        alpha_result = AlphaGenerator(score_limit=3.0).generate(
            factors[list(self.FACTOR_IC)],
            residual_volatility,
            expected_ic=self.FACTOR_IC,
            factor_weights=self.FACTOR_WEIGHTS,
            benchmark_weights=benchmark,
            breadth=len(universe) * 12 * 0.20,
            transfer_coefficient=0.70,
        )

        board_dummies = pd.get_dummies(universe["board"], dtype=float)
        risk_exposures = pd.concat(
            [factors, board_dummies.add_prefix("board_")], axis=1
        )
        factor_vol = pd.Series(0.04, index=risk_exposures.columns)
        factor_vol.loc[board_dummies.add_prefix("board_").columns] = 0.06
        factor_covariance = pd.DataFrame(
            np.diag(np.square(factor_vol)),
            index=risk_exposures.columns,
            columns=risk_exposures.columns,
        )
        optimizer = PortfolioOptimizer(
            risk_aversion=self.config.risk_aversion,
            transaction_cost_aversion=0.015,
            individual_max_weight=self.config.max_weight,
            solver_tolerance=1e-9,
            max_iterations=1_000,
        )
        covariance = optimizer.build_factor_covariance(
            risk_exposures,
            factor_covariance,
            specific_variance=np.square(residual_volatility),
        )
        industry_constraints = (
            board_dummies.iloc[:, 1:] if board_dummies.shape[1] > 1 else None
        )
        style_constraints = factors[["size", "liquidity"]]
        optimization = optimizer.optimize(
            alpha_result.composite_alpha,
            covariance,
            benchmark,
            industry_exposure=industry_constraints,
            style_exposure=style_constraints,
            current_weights=benchmark,
            lower_bounds=0.0,
            active_upper_bound=self.config.active_upper_bound,
            neutrality_tolerance=self.config.neutrality_tolerance,
            transaction_costs=1.0,
        )

        all_results = universe[
            [
                "代码",
                "名称",
                "board",
                "最新价",
                "涨跌幅",
                "成交额",
                "换手率",
                "市盈率-动态",
                "市净率",
                "总市值",
                "流通市值",
                "60日涨跌幅",
                "年初至今涨跌幅",
            ]
        ].copy()
        all_results = all_results.join(factors.add_prefix("factor_"))
        all_results["alpha"] = alpha_result.composite_alpha
        all_results["benchmark_weight"] = benchmark
        all_results["portfolio_weight"] = optimization.portfolio_weights
        all_results["active_weight"] = optimization.active_weights
        selected = (
            all_results[all_results["active_weight"] > 0]
            .sort_values(["active_weight", "alpha"], ascending=False)
            .head(self.config.top_n)
        )
        if len(selected) < self.config.top_n:
            selected = all_results.sort_values(
                ["alpha", "active_weight"], ascending=False
            ).head(self.config.top_n)

        selections = [
            self._selection_record(rank, ticker, row)
            for rank, (ticker, row) in enumerate(selected.iterrows(), start=1)
        ]
        selected_weight = float(selected["portfolio_weight"].sum())
        return {
            "program": "A 股多因子选股",
            "mode": "a_share_selection",
            "data_mode": "demo" if snapshot.is_synthetic else "live",
            "is_synthetic": snapshot.is_synthetic,
            "source": snapshot.source,
            "data_as_of": snapshot.fetched_at,
            "fallback_reason": snapshot.fallback_reason,
            "summary": {
                "raw_market_count": int(filter_stats["raw_market_count"]),
                "eligible_count": int(filter_stats["eligible_count"]),
                "optimized_universe_count": int(len(universe)),
                "selected_count": int(len(selected)),
                "selected_weight_coverage_pct": round(selected_weight * 100, 2),
                "forecast_fundamental_law_ir": round(
                    alpha_result.forecast_information_ratio, 4
                ),
                "expected_active_return_pct": round(
                    optimization.expected_active_return * 100, 4
                ),
                "active_risk_pct": round(optimization.active_risk * 100, 4),
                "optimized_information_ratio": round(
                    optimization.expected_information_ratio, 4
                ),
                "turnover_pct": round(optimization.turnover * 100, 2),
                "max_weight_pct": round(
                    float(optimization.portfolio_weights.max()) * 100, 2
                ),
            },
            "filter_stats": filter_stats,
            "constraints": {
                "long_only": True,
                "full_investment": True,
                "individual_max_weight_pct": self.config.max_weight * 100,
                "active_upper_bound_pct": self.config.active_upper_bound * 100,
                "board_neutrality_tolerance_pct": self.config.neutrality_tolerance
                * 100,
                "size_and_liquidity_control": True,
                "max_constraint_violation": optimization.constraint_diagnostics[
                    "max_constraint_violation"
                ],
            },
            "methodology": {
                "universe": "沪深 A 股；剔除 ST/退市、停牌或零成交、接近涨跌停、极端估值及低流动性股票",
                "alpha_formula": "alpha = residual_volatility × IC × standardized_score",
                "alpha_factors": list(self.FACTOR_LABELS.values()),
                "risk_controls": "交易板块中性代理 + 规模/流动性主动暴露控制 + 个股上限",
                "important_limit": "网页快照不含完整申万行业、财报时点和历史残差序列，不可替代正式回测或实盘风控",
            },
            "selections": selections,
        }

    def _build_universe(self, snapshot: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
        missing = REQUIRED_COLUMNS - set(snapshot.columns)
        if missing:
            raise DataValidationError("行情缺少字段：" + "、".join(sorted(missing)))
        frame = snapshot.copy()
        frame["代码"] = frame["代码"].astype(str).str.zfill(6)
        frame["名称"] = frame["名称"].astype(str).str.strip()
        numeric_columns = sorted(REQUIRED_COLUMNS - {"代码", "名称"})
        frame[numeric_columns] = frame[numeric_columns].apply(
            pd.to_numeric, errors="coerce"
        )
        frame["board"] = frame["代码"].map(_market_board)
        frame["ticker"] = frame["代码"].map(_ticker)
        raw_count = len(frame)

        valid_board = frame["board"].notna()
        if not self.config.include_chinext:
            valid_board &= frame["board"] != "创业板"
        if not self.config.include_star:
            valid_board &= frame["board"] != "科创板"
        clean_name = ~frame["名称"].str.contains(r"(?:\*?ST|退)", case=False, regex=True)
        price_and_trade = (
            (frame["最新价"] >= 1.0)
            & (frame["成交额"] >= self.config.min_turnover_amount_cny)
            & (frame["换手率"] > 0)
        )
        valuation = (
            frame["市盈率-动态"].between(0.01, self.config.max_dynamic_pe)
            & frame["市净率"].between(0.01, self.config.max_pb)
        )
        capitalization = frame["总市值"].between(
            self.config.min_market_cap_cny, self.config.max_market_cap_cny
        ) & (frame["流通市值"] > 0)
        limit_threshold = np.where(
            frame["board"].isin(["创业板", "科创板"]), 19.5, 9.5
        )
        tradeable_price = frame["涨跌幅"].abs() < limit_threshold
        completeness = frame[list(REQUIRED_COLUMNS)].notna().all(axis=1)
        keep = (
            valid_board
            & clean_name
            & price_and_trade
            & valuation
            & capitalization
            & tradeable_price
            & completeness
        )
        eligible = frame.loc[keep].drop_duplicates("ticker", keep="first")
        stats = {
            "raw_market_count": int(raw_count),
            "excluded_non_hs_board": int((~valid_board).sum()),
            "excluded_st_or_delisting": int((valid_board & ~clean_name).sum()),
            "excluded_liquidity_or_suspension": int((valid_board & clean_name & ~price_and_trade).sum()),
            "excluded_valuation": int((valid_board & clean_name & price_and_trade & ~valuation).sum()),
            "excluded_market_cap": int((valid_board & clean_name & price_and_trade & valuation & ~capitalization).sum()),
            "excluded_near_price_limit": int((valid_board & clean_name & price_and_trade & valuation & capitalization & ~tradeable_price).sum()),
            "eligible_count": int(len(eligible)),
        }
        return eligible, stats

    @staticmethod
    def _raw_factors(universe: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "value_pe": -np.log(universe["市盈率-动态"]),
                "value_pb": -np.log(universe["市净率"]),
                "momentum_60d": universe["60日涨跌幅"] / 100,
                "momentum_ytd": universe["年初至今涨跌幅"] / 100,
                "low_volatility": -universe["振幅"] / 100,
                "turnover_quality": -np.abs(
                    np.log1p(universe["换手率"]) - np.log1p(3.0)
                ),
                "size": -np.log(universe["流通市值"]),
                "liquidity": np.log(universe["成交额"]),
            },
            index=universe.index,
        )

    def _selection_record(
        self, rank: int, ticker: str, row: pd.Series
    ) -> dict[str, Any]:
        factor_values = {
            factor: float(row[f"factor_{factor}"]) for factor in self.FACTOR_IC
        }
        strongest = sorted(factor_values, key=factor_values.get, reverse=True)[:3]
        return {
            "rank": rank,
            "ticker": ticker,
            "code": str(row["代码"]),
            "name": str(row["名称"]),
            "board": str(row["board"]),
            "latest_price": round(float(row["最新价"]), 3),
            "pct_change": round(float(row["涨跌幅"]), 2),
            "market_cap_yi": round(float(row["总市值"]) / 1e8, 2),
            "turnover_amount_yi": round(float(row["成交额"]) / 1e8, 2),
            "turnover_pct": round(float(row["换手率"]), 2),
            "dynamic_pe": round(float(row["市盈率-动态"]), 2),
            "pb": round(float(row["市净率"]), 2),
            "momentum_60d_pct": round(float(row["60日涨跌幅"]), 2),
            "momentum_ytd_pct": round(float(row["年初至今涨跌幅"]), 2),
            "alpha_score": round(float(row["alpha"]) * 10_000, 3),
            "benchmark_weight_pct": round(float(row["benchmark_weight"]) * 100, 3),
            "target_weight_pct": round(float(row["portfolio_weight"]) * 100, 3),
            "active_weight_pct": round(float(row["active_weight"]) * 100, 3),
            "reasons": [self.FACTOR_LABELS[factor] for factor in strongest],
            "factor_scores": {
                self.FACTOR_LABELS[factor]: round(value, 3)
                for factor, value in factor_values.items()
            },
        }


def run_a_share_selection(
    *,
    top_n: int = 20,
    universe_size: int = 120,
    data_mode: str = "auto",
    risk_aversion: float = 3.0,
    max_weight: float = 0.08,
) -> dict[str, Any]:
    config = AShareSelectionConfig(
        top_n=top_n,
        universe_size=universe_size,
        data_mode=data_mode,
        risk_aversion=risk_aversion,
        max_weight=max_weight,
    ).validate()
    snapshot = AShareDataProvider().fetch(config.data_mode)
    return AShareSelector(config).run(snapshot)


__all__ = [
    "AShareDataProvider",
    "AShareSelectionConfig",
    "AShareSelector",
    "MarketDataUnavailable",
    "SnapshotResult",
    "generate_demo_snapshot",
    "run_a_share_selection",
]
