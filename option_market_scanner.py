"""Fee-strict box scanner for SSE/SZSE ETF options linked to A shares.

Mainland exchanges do not list an option contract for every individual
A-share stock.  The execution worker therefore discovers all active ETF option
contracts published by the local QMT terminal instead of inventing stock
options or relying on a fixed four-contract fixture.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
import time
from dataclasses import dataclass, replace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


CHINA_TZ = ZoneInfo("Asia/Shanghai")
_OPTION_CACHE: dict[str, Any] = {}

ETF_OPTION_MULTIPLIER = 10_000
BOX_LEG_COUNT = 4
FEE_PER_CONTRACT_CNY = 1.7
SLIPPAGE_TICK_PER_UNIT = 0.0001


class OptionMarketDataUnavailable(RuntimeError):
    """Raised when a complete live option snapshot cannot be obtained."""


@dataclass(frozen=True)
class OptionScanConfig:
    top_n: int = 20
    interest_rate: float = 0.03
    # Minimum TRUE net profit in absolute CNY per complete four-leg box.
    actionpoint: float = 0.0
    desir_mount: int = 1
    min_volume: int = 1
    data_mode: str = "auto"
    contract_multiplier: int = ETF_OPTION_MULTIPLIER
    fee_per_contract_cny: float = FEE_PER_CONTRACT_CNY
    slippage_tick_per_unit: float = SLIPPAGE_TICK_PER_UNIT

    def validate(self) -> "OptionScanConfig":
        if not 1 <= self.top_n <= 500:
            raise ValueError("输出机会数必须在 1 到 500 之间")
        if not 0 <= self.interest_rate <= 1:
            raise ValueError("无风险利率必须在 0 到 1 之间")
        if not 0 <= self.actionpoint <= 1_000_000:
            raise ValueError("最低真实净利润必须为非负人民币金额")
        if not 1 <= self.desir_mount <= 100:
            raise ValueError("模拟数量必须在 1 到 100 之间")
        if not 0 <= self.min_volume <= 10_000_000:
            raise ValueError("最小成交量必须为非负数")
        if self.data_mode not in {"auto", "live", "demo"}:
            raise ValueError("data_mode 仅支持 auto、live 或 demo")
        if self.contract_multiplier != ETF_OPTION_MULTIPLIER:
            raise ValueError("本扫描器仅支持合约乘数为 10000 的沪深 ETF 期权")
        if self.fee_per_contract_cny < 0 or self.slippage_tick_per_unit < 0:
            raise ValueError("手续费和滑点不得为负")
        return self

    @property
    def total_fees_cny(self) -> float:
        return self.fee_per_contract_cny * BOX_LEG_COUNT

    @property
    def total_slippage_cny(self) -> float:
        return (
            self.slippage_tick_per_unit
            * self.contract_multiplier
            * BOX_LEG_COUNT
        )


def calculate_true_box_profit_cny(
    *,
    call_low_ask: float,
    put_low_bid: float,
    put_high_ask: float,
    call_high_bid: float,
    low_strike: float,
    high_strike: float,
    interest_rate: float,
    remaining_days: int,
    contract_multiplier: int = ETF_OPTION_MULTIPLIER,
    fee_per_contract_cny: float = FEE_PER_CONTRACT_CNY,
    slippage_tick_per_unit: float = SLIPPAGE_TICK_PER_UNIT,
) -> dict[str, float]:
    """Calculate an executable long-box profit without mixing dimensions.

    Quotes and strikes are per ETF unit.  Only after the unit theoretical
    profit is known do we multiply by 10,000 to obtain absolute CNY, and only
    then subtract the fixed CNY costs.
    """
    quotes = [call_low_ask, put_low_bid, put_high_ask, call_high_bid]
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in quotes):
        raise ValueError("all four executable option quotes must be positive")
    if high_strike <= low_strike:
        raise ValueError("high_strike must be greater than low_strike")
    if not 0 <= interest_rate <= 1 or remaining_days < 0:
        raise ValueError("invalid interest rate or remaining days")
    if contract_multiplier <= 0 or fee_per_contract_cny < 0 or slippage_tick_per_unit < 0:
        raise ValueError("invalid multiplier, fee or slippage")

    # Step 1: all four premiums remain in per-unit price units.
    unit_debit = (
        float(call_low_ask)
        - float(put_low_bid)
        + float(put_high_ask)
        - float(call_high_bid)
    )
    # Step 2: discounted strike width is also a per-unit value.
    unit_fair_value = (float(high_strike) - float(low_strike)) * math.exp(
        -float(interest_rate) * int(remaining_days) / 365.0
    )
    # Step 3: still per unit; no CNY fixed fees may be subtracted here.
    unit_theoretical_profit = unit_fair_value - unit_debit
    # Step 4: convert per-unit profit to absolute CNY for one contract set.
    absolute_gross_profit_cny = unit_theoretical_profit * int(contract_multiplier)
    total_fees_cny = float(fee_per_contract_cny) * BOX_LEG_COUNT
    total_slippage_cny = (
        float(slippage_tick_per_unit) * int(contract_multiplier) * BOX_LEG_COUNT
    )
    # Step 5: fixed fees/slippage are absolute CNY and are deducted only now.
    true_net_profit_cny = (
        absolute_gross_profit_cny - total_fees_cny - total_slippage_cny
    )
    return {
        "unit_debit": unit_debit,
        "unit_fair_value": unit_fair_value,
        "unit_theoretical_profit": unit_theoretical_profit,
        "absolute_gross_profit_cny": absolute_gross_profit_cny,
        "fees_cny": total_fees_cny,
        "slippage_cny": total_slippage_cny,
        "true_net_profit_cny": true_net_profit_cny,
    }


@dataclass(frozen=True)
class OptionSnapshot:
    data: pd.DataFrame
    source: str
    fetched_at: str
    is_synthetic: bool
    fallback_reason: str | None = None


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class OptionMarketDataProvider:
    """Fetch a bounded, read-only SSE/SZSE ETF-option web snapshot."""

    def __init__(self, cache_seconds: int | None = None) -> None:
        self.cache_seconds = cache_seconds or int(
            os.environ.get("OPTION_CACHE_SECONDS", "180")
        )

    def fetch(self, mode: str = "auto") -> OptionSnapshot:
        if mode == "demo":
            return self._demo_result()
        try:
            return self._fetch_live()
        except Exception as exc:
            if mode == "live" or not _env_flag(
                "OPTION_ALLOW_SYNTHETIC_FALLBACK", True
            ):
                raise OptionMarketDataUnavailable(
                    f"全市场期权行情获取失败：{type(exc).__name__}"
                ) from exc
            return replace(
                self._demo_result(),
                fallback_reason=(
                    "实时沪深 ETF 期权数据不完整，已切换为 ETF 演示快照"
                    f"（{type(exc).__name__}）"
                ),
            )

    def _fetch_live(self) -> OptionSnapshot:
        now = time.monotonic()
        if (
            _OPTION_CACHE.get("data") is not None
            and now - float(_OPTION_CACHE.get("stored_at", 0)) < self.cache_seconds
        ):
            return OptionSnapshot(
                data=_OPTION_CACHE["data"].copy(),
                source="东方财富沪深 ETF 期权（缓存快照）",
                fetched_at=str(_OPTION_CACHE["fetched_at"]),
                is_synthetic=False,
            )

        # This executable scanner is deliberately limited to ETF options whose
        # mandated contract multiplier and fixed-cost model are both 10,000.
        frame = self._fetch_etf_options()
        if frame.empty:
            raise OptionMarketDataUnavailable("沪深 ETF 期权数据为空")
        frame = frame.drop_duplicates("code", keep="first")
        fetched_at = dt.datetime.now(CHINA_TZ).isoformat(timespec="seconds")
        _OPTION_CACHE.update(
            data=frame.copy(), stored_at=time.monotonic(), fetched_at=fetched_at
        )
        return OptionSnapshot(
            data=frame,
            source="东方财富沪深 ETF 期权实时买卖盘快照",
            fetched_at=fetched_at,
            is_synthetic=False,
        )

    @staticmethod
    def _request_timeout() -> tuple[float, float]:
        read_timeout = max(
            3.0,
            min(float(os.environ.get("OPTION_HTTP_TIMEOUT_SECONDS", "8")), 15.0),
        )
        return 3.0, read_timeout

    @classmethod
    def _fetch_etf_options(cls) -> pd.DataFrame:
        import requests

        response = requests.get(
            "https://23.push2.eastmoney.com/api/qt/clist/get",
            params={
                "pn": "1",
                "pz": "6000",
                "po": "1",
                "np": "1",
                "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                "fltt": "2",
                "invt": "2",
                "fid": "f3",
                "fs": "m:10,m:12",
                "fields": (
                    "f2,f5,f6,f12,f13,f14,f28,f31,f32,f108,f161,f162,f163"
                ),
            },
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; QuantConsole/1.0)",
                "Accept": "application/json,text/plain,*/*",
            },
            timeout=cls._request_timeout(),
        )
        response.raise_for_status()
        rows = ((response.json().get("data") or {}).get("diff") or [])
        if not rows:
            raise OptionMarketDataUnavailable("ETF 期权接口返回空表")
        raw = pd.DataFrame(rows)
        frame = pd.DataFrame(
            {
                "raw_code": raw.get("f12"),
                "name": raw.get("f14"),
                "market_id": raw.get("f13"),
                "last": raw.get("f2"),
                "volume": raw.get("f5"),
                "amount": raw.get("f6"),
                "open_interest": raw.get("f108"),
                "strike": raw.get("f161"),
                "remaining_days": raw.get("f162"),
                "bid": raw.get("f31"),
                "ask": raw.get("f32"),
            }
        )
        frame = frame[frame["name"].astype(str).str.contains(r"ETF.*[购沽]")]
        frame["exchange"] = np.where(
            frame["market_id"].astype(str) == "10", "SSE", "SZSE"
        )
        frame["code"] = frame["raw_code"].astype(str) + np.where(
            frame["exchange"] == "SSE", ".SHO", ".SZO"
        )
        frame["option_type"] = np.where(
            frame["name"].astype(str).str.contains("购"), "C", "P"
        )
        frame["underlying"] = frame.apply(
            lambda row: cls._etf_underlying(str(row["name"]), str(row["exchange"])),
            axis=1,
        )
        frame["quote_basis"] = "bid_ask"
        return cls._finish_normalization(frame)

    @staticmethod
    def _etf_underlying(name: str, exchange: str) -> str:
        prefix = re.split(r"[购沽]", name, maxsplit=1)[0]
        prefix = re.sub(r"\s+", "", prefix)
        return f"{prefix}({exchange})"

    @staticmethod
    def _finish_normalization(frame: pd.DataFrame) -> pd.DataFrame:
        numeric = [
            "last",
            "volume",
            "amount",
            "open_interest",
            "strike",
            "remaining_days",
            "bid",
            "ask",
        ]
        for column in numeric:
            if column not in frame:
                frame[column] = np.nan
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        missing_bbo = (frame["bid"] <= 0) | (frame["ask"] <= 0)
        frame.loc[missing_bbo, "bid"] = frame.loc[missing_bbo, "last"]
        frame.loc[missing_bbo, "ask"] = frame.loc[missing_bbo, "last"]
        frame.loc[missing_bbo, "quote_basis"] = "last_proxy"
        frame["remaining_days"] = frame["remaining_days"].clip(lower=1)
        today = dt.datetime.now(CHINA_TZ).date()
        frame["expiry_date"] = frame["remaining_days"].map(
            lambda value: (today + dt.timedelta(days=int(value))).isoformat()
            if pd.notna(value)
            else None
        )
        required = [
            "code",
            "name",
            "underlying",
            "exchange",
            "option_type",
            "strike",
            "remaining_days",
            "bid",
            "ask",
        ]
        frame = frame.dropna(subset=required)
        frame = frame[
            (frame["strike"] > 0)
            & (frame["bid"] > 0)
            & (frame["ask"] > 0)
            & (frame["ask"] >= frame["bid"])
        ]
        return frame[
            [
                "code",
                "name",
                "underlying",
                "exchange",
                "expiry_date",
                "remaining_days",
                "strike",
                "option_type",
                "bid",
                "ask",
                "last",
                "volume",
                "amount",
                "open_interest",
                "quote_basis",
            ]
        ].drop_duplicates("code", keep="first")

    @staticmethod
    def _demo_result() -> OptionSnapshot:
        return OptionSnapshot(
            data=generate_demo_option_market(),
            source="覆盖九个沪深 ETF 期权产品族的合成演示快照",
            fetched_at=dt.datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
            is_synthetic=True,
        )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _black_scholes_pair(
    spot: float, strike: float, rate: float, volatility: float, years: float
) -> tuple[float, float]:
    root_t = math.sqrt(years)
    d1 = (
        math.log(spot / strike) + (rate + volatility**2 / 2) * years
    ) / (volatility * root_t)
    d2 = d1 - volatility * root_t
    call = spot * _normal_cdf(d1) - strike * math.exp(-rate * years) * _normal_cdf(d2)
    put = call - spot + strike * math.exp(-rate * years)
    return max(call, 0.0001), max(put, 0.0001)


def generate_demo_option_market(seed: int = 20260806) -> pd.DataFrame:
    """Generate a deterministic market covering nine ETF option families."""
    rng = np.random.default_rng(seed)
    products = [
        ("50ETF(SSE)", "SSE", 2.85),
        ("300ETF(SSE)", "SSE", 4.10),
        ("500ETF(SSE)", "SSE", 6.20),
        ("科创50ETF(SSE)", "SSE", 1.12),
        ("科创板50ETF(SSE)", "SSE", 1.08),
        ("300ETF(SZSE)", "SZSE", 4.05),
        ("创业板ETF(SZSE)", "SZSE", 2.35),
        ("中证500ETF(SZSE)", "SZSE", 6.10),
        ("深证100ETF(SZSE)", "SZSE", 3.25),
    ]
    rows: list[dict[str, Any]] = []
    today = dt.datetime.now(CHINA_TZ).date()
    for product_index, (underlying, exchange, spot) in enumerate(products):
        relative_step = 0.025 if spot < 100 else 0.025
        strikes = [spot * (1 + relative_step * offset) for offset in range(-4, 5)]
        precision = 3 if spot < 100 else 0
        strikes = [round(value, precision) for value in strikes]
        for expiry_index, remaining in enumerate((21, 49, 112)):
            years = remaining / 365.0
            for strike_index, strike in enumerate(strikes):
                call, put = _black_scholes_pair(
                    spot, strike, 0.03, 0.20 + product_index * 0.004, years
                )
                for option_type, fair in (("C", call), ("P", put)):
                    spread = max(fair * 0.012, 0.0004 if spot < 100 else 0.4)
                    bid = max(fair - spread / 2, 0.0001)
                    ask = fair + spread / 2
                    # Inject one visible but still clearly synthetic opportunity.
                    if product_index == 0 and expiry_index == 0:
                        if strike_index == 3 and option_type == "C":
                            ask *= 0.94
                        if strike_index == 3 and option_type == "P":
                            bid *= 1.06
                        if strike_index == 5 and option_type == "P":
                            ask *= 0.94
                        if strike_index == 5 and option_type == "C":
                            bid *= 1.06
                    code = f"D{product_index:02d}{expiry_index}{strike_index}{option_type}"
                    rows.append(
                        {
                            "code": f"{code}.{exchange}",
                            "name": f"{underlying}{option_type}{strike}",
                            "underlying": underlying,
                            "exchange": exchange,
                            "expiry_date": (today + dt.timedelta(days=remaining)).isoformat(),
                            "remaining_days": remaining,
                            "strike": strike,
                            "option_type": option_type,
                            "bid": round(bid, 5),
                            "ask": round(max(ask, bid), 5),
                            "last": round(fair, 5),
                            "volume": int(rng.integers(30, 20_000)),
                            "amount": float(rng.uniform(1e5, 5e8)),
                            "open_interest": int(rng.integers(100, 80_000)),
                            "quote_basis": "bid_ask",
                        }
                    )
    return pd.DataFrame(rows)


class MarketWideBoxScanner:
    """Pair calls/puts by product, expiry and strike, then scan all strike boxes."""

    REQUIRED_COLUMNS = {
        "code",
        "name",
        "underlying",
        "exchange",
        "expiry_date",
        "remaining_days",
        "strike",
        "option_type",
        "bid",
        "ask",
        "volume",
        "quote_basis",
    }

    def __init__(self, config: OptionScanConfig | None = None) -> None:
        self.config = (config or OptionScanConfig()).validate()

    def run(self, snapshot: OptionSnapshot) -> dict[str, Any]:
        frame = self._clean(snapshot.data)
        all_candidates, paired_strikes, group_count = self._scan(frame)
        threshold_cny = max(float(self.config.actionpoint), 0.0)
        # Never expose a non-positive opportunity as actionable output.
        opportunities = [
            item
            for item in all_candidates
            if item["true_net_profit_cny"] > threshold_cny
        ]
        opportunities.sort(
            key=lambda item: (item["true_net_profit_cny"], item["min_leg_volume"]),
            reverse=True,
        )
        for rank, item in enumerate(opportunities, start=1):
            item["rank"] = rank
        top = opportunities[: self.config.top_n]
        positive_count = len(opportunities)
        best = top[0] if top else None
        executable_best = bool(
            best
            and best["true_net_profit_cny"] > threshold_cny
            and best["quote_basis"] == "bid_ask"
        )
        orders = []
        if executable_best:
            for leg in best["legs"]:
                orders.append(
                    {
                        "code": leg["code"],
                        "action": "open",
                        "side": leg["side"],
                        "qty": self.config.desir_mount,
                        "price": leg["price"],
                    }
                )
        quote_counts = frame["quote_basis"].value_counts().to_dict()
        return {
            "program": "boxoption2.py",
            "mode": "option_market_scan",
            "data_mode": "demo" if snapshot.is_synthetic else "live",
            "is_synthetic": snapshot.is_synthetic,
            "source": snapshot.source,
            "data_as_of": snapshot.fetched_at,
            "fallback_reason": snapshot.fallback_reason,
            "input": {
                "interest_rate": self.config.interest_rate,
                "actionpoint": self.config.actionpoint,
                "desir_mount": self.config.desir_mount,
                "min_volume": self.config.min_volume,
                "top_n": self.config.top_n,
                "contract_multiplier": self.config.contract_multiplier,
                "fee_per_contract_cny": self.config.fee_per_contract_cny,
                "box_leg_count": BOX_LEG_COUNT,
                "total_fees_cny": self.config.total_fees_cny,
                "slippage_tick_per_unit": self.config.slippage_tick_per_unit,
                "total_slippage_cny": self.config.total_slippage_cny,
            },
            "summary": {
                "contract_count": int(len(frame)),
                "underlying_count": int(frame["underlying"].nunique()),
                "expiry_group_count": int(group_count),
                "paired_strike_count": int(paired_strikes),
                "box_combination_count": int(len(all_candidates)),
                "positive_opportunity_count": int(positive_count),
                "best_true_net_profit_cny": round(
                    float(best["true_net_profit_cny"]), 2
                ) if best else None,
                "best_net_profit_bps": round(float(best["net_profit_bps"]), 2)
                if best
                else None,
                "bid_ask_contract_count": int(quote_counts.get("bid_ask", 0)),
                "last_proxy_contract_count": int(quote_counts.get("last_proxy", 0)),
            },
            "has_opportunity": executable_best,
            "opportunities": top,
            "orders": orders,
            "methodology": {
                "coverage": "仅扫描合约乘数为 10000 的上交所/深交所 ETF 期权",
                "pairing": "同一标的、同一到期日内先按相同行权价配对认购与认沽，再枚举 K_low < K_high",
                "profit": "先算每单位理论利润，再乘 10000 转为人民币，最后扣除 6.8 元手续费与 4.0 元滑点",
                "quote_rule": "四条腿均使用可执行买一/卖一；缺失真实 BBO 的合约不进入结果",
                "fee_model": "1.7 元/张/腿 × 4 腿 = 6.8 元/套；0.0001 × 10000 × 4 腿 = 4.0 元/套",
                "risk_notice": "净利润仍未覆盖四腿不同步成交、撤单、保证金占用、价格跳变及行权交收风险，不构成交易指令",
            },
        }

    def _clean(self, data: pd.DataFrame) -> pd.DataFrame:
        missing = self.REQUIRED_COLUMNS - set(data.columns)
        if missing:
            raise ValueError("期权快照缺少字段：" + "、".join(sorted(missing)))
        frame = data.copy()
        for column in ["remaining_days", "strike", "bid", "ask", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        for column in ["bid_volume", "ask_volume"]:
            if column not in frame:
                frame[column] = frame["volume"]
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0)
        frame["option_type"] = frame["option_type"].astype(str).str.upper()
        frame = frame.dropna(
            subset=[
                "code",
                "underlying",
                "expiry_date",
                "remaining_days",
                "strike",
                "bid",
                "ask",
            ]
        )
        frame = frame[
            frame["option_type"].isin(["C", "P"])
            & frame["exchange"].isin(["SSE", "SZSE"])
            & (frame["quote_basis"] == "bid_ask")
            & (frame["remaining_days"] > 0)
            & (frame["strike"] > 0)
            & (frame["bid"] > 0)
            & (frame["ask"] > 0)
            & (frame["ask"] >= frame["bid"])
        ]
        return frame.drop_duplicates("code", keep="first")

    def _scan(self, frame: pd.DataFrame) -> tuple[list[dict[str, Any]], int, int]:
        candidates: list[dict[str, Any]] = []
        paired_strikes = 0
        group_count = 0
        group_columns = ["underlying", "exchange", "expiry_date", "remaining_days"]
        for keys, group in frame.groupby(group_columns, sort=True):
            call = group[group["option_type"] == "C"].set_index("strike")
            put = group[group["option_type"] == "P"].set_index("strike")
            strikes = sorted(set(call.index) & set(put.index))
            if len(strikes) < 2:
                continue
            group_count += 1
            paired_strikes += len(strikes)
            underlying, exchange, expiry_date, remaining_days = keys
            for low_position, low_strike in enumerate(strikes[:-1]):
                low_call = call.loc[low_strike]
                low_put = put.loc[low_strike]
                for high_strike in strikes[low_position + 1 :]:
                    high_call = call.loc[high_strike]
                    high_put = put.loc[high_strike]
                    # Use the executable side's level-1 depth for each leg.
                    leg_depths = [
                        float(low_call.get("ask_volume", 0) or 0),
                        float(low_put.get("bid_volume", 0) or 0),
                        float(high_put.get("ask_volume", 0) or 0),
                        float(high_call.get("bid_volume", 0) or 0),
                    ]
                    min_volume = min(int(max(value, 0)) for value in leg_depths)
                    if min_volume < self.config.min_volume:
                        continue
                    debit = (
                        float(low_call["ask"])
                        - float(low_put["bid"])
                        + float(high_put["ask"])
                        - float(high_call["bid"])
                    )
                    calculation = calculate_true_box_profit_cny(
                        call_low_ask=float(low_call["ask"]),
                        put_low_bid=float(low_put["bid"]),
                        put_high_ask=float(high_put["ask"]),
                        call_high_bid=float(high_call["bid"]),
                        low_strike=float(low_strike),
                        high_strike=float(high_strike),
                        interest_rate=self.config.interest_rate,
                        remaining_days=int(remaining_days),
                        contract_multiplier=self.config.contract_multiplier,
                        fee_per_contract_cny=self.config.fee_per_contract_cny,
                        slippage_tick_per_unit=self.config.slippage_tick_per_unit,
                    )
                    fair_value = calculation["unit_fair_value"]
                    if fair_value <= 0:
                        continue
                    leg_rows = (low_call, low_put, high_put, high_call)
                    quote_basis = (
                        "bid_ask"
                        if all(row["quote_basis"] == "bid_ask" for row in leg_rows)
                        else "last_proxy"
                    )
                    legs = [
                        self._leg(low_call, "buy", "call", "ask"),
                        self._leg(low_put, "sell", "put", "bid"),
                        self._leg(high_put, "buy", "put", "ask"),
                        self._leg(high_call, "sell", "call", "bid"),
                    ]
                    candidates.append(
                        {
                            "underlying": str(underlying),
                            "exchange": str(exchange),
                            "expiry_date": str(expiry_date),
                            "remaining_days": int(remaining_days),
                            "low_strike": round(float(low_strike), 4),
                            "high_strike": round(float(high_strike), 4),
                            "contract_multiplier": self.config.contract_multiplier,
                            "unit_debit": round(calculation["unit_debit"], 6),
                            "unit_fair_value": round(calculation["unit_fair_value"], 6),
                            "unit_theoretical_profit": round(
                                calculation["unit_theoretical_profit"], 6
                            ),
                            "absolute_gross_profit_cny": round(
                                calculation["absolute_gross_profit_cny"], 2
                            ),
                            "fees_cny": round(calculation["fees_cny"], 2),
                            "slippage_cny": round(calculation["slippage_cny"], 2),
                            "true_net_profit_cny": round(
                                calculation["true_net_profit_cny"], 2
                            ),
                            "true_net_profit_total_cny": round(
                                calculation["true_net_profit_cny"]
                                * self.config.desir_mount,
                                2,
                            ),
                            "net_profit_bps": round(
                                calculation["true_net_profit_cny"]
                                / (fair_value * self.config.contract_multiplier)
                                * 10_000,
                                2,
                            ),
                            # Compatibility aliases for existing web clients.
                            "fair_value": round(fair_value, 6),
                            "net_debit": round(debit, 6),
                            "profit_per_unit": round(
                                calculation["unit_theoretical_profit"], 6
                            ),
                            "profit_bps": round(
                                calculation["unit_theoretical_profit"]
                                / fair_value
                                * 10_000,
                                2,
                            ),
                            "min_leg_volume": min_volume,
                            "quote_basis": quote_basis,
                            "legs": legs,
                        }
                    )
        return candidates, paired_strikes, group_count

    @staticmethod
    def _leg(row: pd.Series, side: str, option: str, price_field: str) -> dict[str, Any]:
        volume_field = "ask_volume" if price_field == "ask" else "bid_volume"
        return {
            "code": str(row["code"]),
            "name": str(row["name"]),
            "side": side,
            "option_type": option,
            "price": round(float(row[price_field]), 6),
            "available_volume": int(max(float(row.get(volume_field, 0) or 0), 0)),
        }


def run_option_market_scan(
    *,
    data_mode: str = "auto",
    top_n: int = 20,
    interest_rate: float = 0.03,
    actionpoint: float = 0.0,
    desir_mount: int = 1,
    min_volume: int = 1,
) -> dict[str, Any]:
    config = OptionScanConfig(
        data_mode=data_mode,
        top_n=top_n,
        interest_rate=interest_rate,
        actionpoint=actionpoint,
        desir_mount=desir_mount,
        min_volume=min_volume,
    ).validate()
    snapshot = OptionMarketDataProvider().fetch(config.data_mode)
    return MarketWideBoxScanner(config).run(snapshot)


__all__ = [
    "BOX_LEG_COUNT",
    "ETF_OPTION_MULTIPLIER",
    "FEE_PER_CONTRACT_CNY",
    "MarketWideBoxScanner",
    "OptionMarketDataProvider",
    "OptionMarketDataUnavailable",
    "OptionScanConfig",
    "OptionSnapshot",
    "SLIPPAGE_TICK_PER_UNIT",
    "calculate_true_box_profit_cny",
    "generate_demo_option_market",
    "run_option_market_scan",
]
