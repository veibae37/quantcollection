"""Market-wide scanner for exchange-listed options linked to China's A-share market.

Coverage is intentionally limited to products that actually exist: SSE/SZSE
ETF options and CFFEX equity-index options.  Mainland exchanges do not list an
option contract for every individual A-share stock.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


CHINA_TZ = ZoneInfo("Asia/Shanghai")
_OPTION_CACHE: dict[str, Any] = {}


class OptionMarketDataUnavailable(RuntimeError):
    """Raised when a complete live option snapshot cannot be obtained."""


@dataclass(frozen=True)
class OptionScanConfig:
    top_n: int = 20
    interest_rate: float = 0.03
    actionpoint: float = 0.0001
    desir_mount: int = 1
    min_volume: int = 1
    data_mode: str = "auto"

    def validate(self) -> "OptionScanConfig":
        if not 5 <= self.top_n <= 50:
            raise ValueError("输出机会数必须在 5 到 50 之间")
        if not 0 <= self.interest_rate <= 1:
            raise ValueError("无风险利率必须在 0 到 1 之间")
        if not 0 <= self.actionpoint <= 1_000_000:
            raise ValueError("触发阈值必须为非负数")
        if not 1 <= self.desir_mount <= 100:
            raise ValueError("模拟数量必须在 1 到 100 之间")
        if not 0 <= self.min_volume <= 10_000_000:
            raise ValueError("最小成交量必须为非负数")
        if self.data_mode not in {"auto", "live", "demo"}:
            raise ValueError("data_mode 仅支持 auto、live 或 demo")
        return self


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
    """Fetch ETF and equity-index options with bounded concurrent requests."""

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
                    "实时 ETF/股指期权数据不完整，已切换为全市场演示快照"
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
                source="东方财富 ETF/股指期权（缓存快照）",
                fetched_at=str(_OPTION_CACHE["fetched_at"]),
                is_synthetic=False,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            etf_future = executor.submit(self._fetch_etf_options)
            index_future = executor.submit(self._fetch_index_options)
            etf = etf_future.result()
            index = index_future.result()
        if etf.empty or index.empty:
            raise OptionMarketDataUnavailable("ETF 或股指期权数据为空")
        frame = pd.concat([etf, index], ignore_index=True)
        frame = frame.drop_duplicates("code", keep="first")
        fetched_at = dt.datetime.now(CHINA_TZ).isoformat(timespec="seconds")
        _OPTION_CACHE.update(
            data=frame.copy(), stored_at=time.monotonic(), fetched_at=fetched_at
        )
        return OptionSnapshot(
            data=frame,
            source="东方财富 ETF 期权 + 中金所股指期权快照",
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

    @classmethod
    def _fetch_index_options(cls) -> pd.DataFrame:
        import requests

        response = requests.get(
            "https://futsseapi.eastmoney.com/list/option/221",
            params={
                "orderBy": "zdf",
                "sort": "desc",
                "pageSize": "20000",
                "pageIndex": "0",
                "token": "58b2fa8f54638b60b87d69b31969089c",
                "field": "dm,sc,name,p,vol,cje,ccl,xqj,syr,rz,zjsj,o",
            },
            headers={"User-Agent": "Mozilla/5.0 (compatible; QuantConsole/1.0)"},
            timeout=cls._request_timeout(),
        )
        response.raise_for_status()
        rows = response.json().get("list") or []
        if not rows:
            raise OptionMarketDataUnavailable("股指期权接口返回空表")
        raw = pd.DataFrame(rows)
        frame = pd.DataFrame(
            {
                "raw_code": raw.get("dm"),
                "code": raw.get("dm").astype(str) + ".CFFEX",
                "name": raw.get("name"),
                "exchange": "CFFEX",
                "last": raw.get("p"),
                "volume": raw.get("vol"),
                "amount": raw.get("cje"),
                "open_interest": raw.get("ccl"),
                "strike": raw.get("xqj"),
                "remaining_days": raw.get("syr"),
            }
        )
        codes = frame["raw_code"].astype(str).str.upper()
        frame = frame[codes.str.match(r"^(IO|MO|HO)\d{4}-[CP]-\d+")].copy()
        codes = frame["raw_code"].astype(str).str.upper()
        frame["option_type"] = np.where(codes.str.contains("-C-"), "C", "P")
        frame["underlying"] = codes.str[:2].map(
            {"IO": "沪深300股指", "MO": "中证1000股指", "HO": "上证50股指"}
        )
        # The compact CFFEX endpoint exposes last price but not executable BBO.
        frame["bid"] = frame["last"]
        frame["ask"] = frame["last"]
        frame["quote_basis"] = "last_proxy"
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
            source="覆盖沪深 ETF 与中金所股指期权的合成演示快照",
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
    """Generate a broad deterministic market with 12 real product families."""
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
        ("沪深300股指", "CFFEX", 4100.0),
        ("中证1000股指", "CFFEX", 6200.0),
        ("上证50股指", "CFFEX", 2850.0),
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
        opportunities, paired_strikes, group_count = self._scan(frame)
        opportunities.sort(
            key=lambda item: (item["profit_bps"], item["min_leg_volume"]),
            reverse=True,
        )
        top = opportunities[: self.config.top_n]
        positive_count = sum(
            item["profit_per_unit"] >= self.config.actionpoint
            for item in opportunities
        )
        best = top[0] if top else None
        executable_best = bool(
            best
            and best["profit_per_unit"] >= self.config.actionpoint
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
            },
            "summary": {
                "contract_count": int(len(frame)),
                "underlying_count": int(frame["underlying"].nunique()),
                "expiry_group_count": int(group_count),
                "paired_strike_count": int(paired_strikes),
                "box_combination_count": int(len(opportunities)),
                "positive_opportunity_count": int(positive_count),
                "best_profit_per_unit": round(
                    float(best["profit_per_unit"]), 6
                ) if best else None,
                "best_profit_bps": round(float(best["profit_bps"]), 2)
                if best
                else None,
                "bid_ask_contract_count": int(quote_counts.get("bid_ask", 0)),
                "last_proxy_contract_count": int(quote_counts.get("last_proxy", 0)),
            },
            "has_opportunity": executable_best,
            "opportunities": top,
            "orders": orders,
            "methodology": {
                "coverage": "上交所/深交所 ETF 期权与中金所沪深300、中证1000、上证50股指期权",
                "pairing": "同一标的、同一到期日内先按相同行权价配对认购与认沽，再枚举 K_low < K_high",
                "profit": "PV(K_high-K_low) - [Call_low_ask - Put_low_bid + Put_high_ask - Call_high_bid]",
                "quote_rule": "仅 bid_ask 行情可形成模拟四腿；last_proxy 只展示理论排序",
                "market_limit": "中国内地目前不是每只 A 股都有个股期权，覆盖对象是 ETF 与股指期权",
                "risk_notice": "未计手续费、滑点、保证金、行权交收、合约乘数差异和多腿成交风险，不构成交易指令",
            },
        }

    def _clean(self, data: pd.DataFrame) -> pd.DataFrame:
        missing = self.REQUIRED_COLUMNS - set(data.columns)
        if missing:
            raise ValueError("期权快照缺少字段：" + "、".join(sorted(missing)))
        frame = data.copy()
        for column in ["remaining_days", "strike", "bid", "ask", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
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
            discount = math.exp(
                -self.config.interest_rate * float(remaining_days) / 365.0
            )
            for low_position, low_strike in enumerate(strikes[:-1]):
                low_call = call.loc[low_strike]
                low_put = put.loc[low_strike]
                for high_strike in strikes[low_position + 1 :]:
                    high_call = call.loc[high_strike]
                    high_put = put.loc[high_strike]
                    legs_frame = [low_call, low_put, high_put, high_call]
                    min_volume = min(
                        int(max(float(row.get("volume", 0) or 0), 0))
                        for row in legs_frame
                    )
                    if min_volume < self.config.min_volume:
                        continue
                    debit = (
                        float(low_call["ask"])
                        - float(low_put["bid"])
                        + float(high_put["ask"])
                        - float(high_call["bid"])
                    )
                    fair_value = (float(high_strike) - float(low_strike)) * discount
                    if fair_value <= 0:
                        continue
                    profit = fair_value - debit
                    quote_basis = (
                        "bid_ask"
                        if all(row["quote_basis"] == "bid_ask" for row in legs_frame)
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
                            "fair_value": round(fair_value, 6),
                            "net_debit": round(debit, 6),
                            "profit_per_unit": round(profit, 6),
                            "profit_bps": round(profit / fair_value * 10_000, 2),
                            "min_leg_volume": min_volume,
                            "quote_basis": quote_basis,
                            "legs": legs,
                        }
                    )
        for rank, item in enumerate(
            sorted(candidates, key=lambda row: row["profit_bps"], reverse=True),
            start=1,
        ):
            item["rank"] = rank
        return candidates, paired_strikes, group_count

    @staticmethod
    def _leg(row: pd.Series, side: str, option: str, price_field: str) -> dict[str, Any]:
        return {
            "code": str(row["code"]),
            "name": str(row["name"]),
            "side": side,
            "option_type": option,
            "price": round(float(row[price_field]), 6),
        }


def run_option_market_scan(
    *,
    data_mode: str = "auto",
    top_n: int = 20,
    interest_rate: float = 0.03,
    actionpoint: float = 0.0001,
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
    "MarketWideBoxScanner",
    "OptionMarketDataProvider",
    "OptionMarketDataUnavailable",
    "OptionScanConfig",
    "OptionSnapshot",
    "generate_demo_option_market",
    "run_option_market_scan",
]
