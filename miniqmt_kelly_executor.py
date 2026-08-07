"""Local MiniQMT adapter for the TW half-Kelly A-share rebalance.

Nothing in this module trades merely because it is imported or because the
Vercel page is opened.  Real orders require both ``--live`` and the exact
environment acknowledgement ``MINIQMT_ENABLE_LIVE_TRADING=I_UNDERSTAND_LIVE_TRADING``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import random
from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from tw_kelly_strategy import KellyConfig, run_tw_kelly_portfolio


LIVE_ACKNOWLEDGEMENT = "I_UNDERSTAND_LIVE_TRADING"
QMT_FALLBACK_ACKNOWLEDGEMENT = "I_REVIEWED_QMT_MARKET_ONLY_SELECTION"


def _load_local_miniqmt_env() -> None:
    """Load only MINIQMT_* keys from the ignored local .env file."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8-sig") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if not key.startswith("MINIQMT_"):
                    continue
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))
    except OSError as exc:
        raise MiniQMTConfigurationError(f"cannot read local .env: {exc}") from exc


class MiniQMTConfigurationError(RuntimeError):
    """Raised when local MiniQMT settings are incomplete or unsafe."""


class MiniQMTConnectionError(RuntimeError):
    """Raised when MiniQMT cannot be connected or queried."""


@dataclass(frozen=True)
class MiniQMTConfig:
    userdata_path: str
    account_id: str
    session_id: int
    period: str = "15m"
    history_bars: int = 520
    price_slippage_bps: float = 5.0

    @classmethod
    def from_env(cls) -> "MiniQMTConfig":
        _load_local_miniqmt_env()
        path = os.environ.get("MINIQMT_PATH", "").strip()
        account_id = os.environ.get("MINIQMT_ACCOUNT_ID", "").strip()
        if (
            not path
            or not account_id
            or "\\path\\to\\" in path.lower()
            or account_id.lower().startswith("replace_with_")
        ):
            raise MiniQMTConfigurationError(
                "edit the local .env and set real MINIQMT_PATH and MINIQMT_ACCOUNT_ID values"
            )
        return cls(
            userdata_path=path,
            account_id=account_id,
            session_id=int(os.environ.get("MINIQMT_SESSION_ID", random.randint(100000, 999999))),
        )


class MiniQMTKellyExecutor:
    """Query account state, load 15m bars and optionally submit guarded orders."""

    def __init__(self, config: MiniQMTConfig) -> None:
        self.config = config
        self.trader = None
        self.account = None

    def connect(self) -> None:
        try:
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount
        except Exception as exc:
            raise MiniQMTConfigurationError(
                "xtquant is unavailable; run this command on the Windows MiniQMT host"
            ) from exc
        self.trader = XtQuantTrader(self.config.userdata_path, self.config.session_id)
        self.trader.start()
        result = self.trader.connect()
        if result != 0:
            self.trader.stop()
            self.trader = None
            raise MiniQMTConnectionError(f"MiniQMT connection failed with code {result}")
        self.account = StockAccount(self.config.account_id, "STOCK")
        subscribe_result = self.trader.subscribe(self.account)
        if subscribe_result != 0:
            self.close()
            raise MiniQMTConnectionError(
                f"MiniQMT account subscription failed with code {subscribe_result}"
            )

    def close(self) -> None:
        if self.trader is not None:
            self.trader.stop()
            self.trader = None

    def account_snapshot(self) -> tuple[float, float, dict[str, dict[str, float]]]:
        if self.trader is None or self.account is None:
            raise MiniQMTConnectionError("MiniQMT is not connected")
        asset = self.trader.query_stock_asset(self.account)
        if asset is None:
            raise MiniQMTConnectionError("MiniQMT returned no account asset record")
        raw_positions = self.trader.query_stock_positions(self.account) or []
        positions = {
            str(item.stock_code): {
                "volume": float(item.volume),
                "can_use_volume": float(item.can_use_volume),
                "last_price": float(item.last_price),
                "market_value": float(item.market_value),
            }
            for item in raw_positions
            if float(item.volume) > 0
        }
        return float(asset.total_asset), float(asset.cash), positions

    def load_histories(self, tickers: list[str]) -> dict[str, pd.DataFrame]:
        try:
            from xtquant import xtdata
        except Exception as exc:
            raise MiniQMTConfigurationError("xtquant market-data module is unavailable") from exc
        fields = ["open", "high", "low", "close", "volume"]
        raw = xtdata.get_market_data_ex(
            field_list=fields,
            stock_list=tickers,
            period=self.config.period,
            count=self.config.history_bars,
            dividend_type="front_ratio",
            fill_data=True,
        )
        histories: dict[str, pd.DataFrame] = {}
        for ticker in tickers:
            frame = raw.get(ticker)
            if frame is None or len(frame) < 100:
                raise MiniQMTConnectionError(
                    f"insufficient {self.config.period} history for {ticker}; download history in QMT first"
                )
            histories[ticker] = frame.loc[:, fields].dropna().copy()
        return histories

    def build_qmt_market_selection(
        self,
        *,
        top_n: int = 20,
        candidate_count: int = 360,
    ) -> dict[str, object]:
        """Select real A shares from QMT when the public snapshot is unavailable.

        This fallback intentionally uses only fields QMT can supply reliably:
        60-day momentum, realized volatility, trading amount and float market
        capitalization.  It does not invent PE/PB values when fundamentals
        have not been downloaded in the local QMT terminal.
        """
        try:
            from xtquant import xtdata
        except Exception as exc:
            raise MiniQMTConfigurationError(
                "xtquant market-data module is unavailable"
            ) from exc

        all_codes = list(xtdata.get_stock_list_in_sector("沪深A股") or [])
        all_codes = [
            str(code)
            for code in all_codes
            if str(code).endswith((".SH", ".SZ"))
            and str(code).split(".", 1)[0].startswith(
                ("600", "601", "603", "605", "000", "001", "002", "003", "300", "301", "688", "689")
            )
        ]
        if len(all_codes) < max(50, top_n * 2):
            raise MiniQMTConnectionError(
                "QMT returned too few 沪深A股 constituents; update sector data in QMT"
            )

        ticks: dict[str, dict[str, object]] = {}
        for start in range(0, len(all_codes), 500):
            batch = xtdata.get_full_tick(all_codes[start : start + 500]) or {}
            ticks.update(batch)

        liquid = []
        for ticker in all_codes:
            tick = ticks.get(ticker) or {}
            last_price = float(tick.get("lastPrice") or 0.0)
            amount = float(tick.get("amount") or 0.0)
            last_close = float(tick.get("lastClose") or 0.0)
            if last_price > 0 and last_close > 0 and amount > 0:
                pct_change = (last_price / last_close - 1.0) * 100
                if abs(pct_change) < (19.5 if ticker.startswith(("300", "301", "688", "689")) else 9.5):
                    liquid.append((ticker, amount, last_price, pct_change))
        liquid.sort(key=lambda item: item[1], reverse=True)
        pool_size = max(top_n * 3, min(int(candidate_count), 600))
        pool = liquid[:pool_size]
        if len(pool) < max(30, top_n + 10):
            raise MiniQMTConnectionError("QMT realtime snapshot has too few liquid A shares")

        pool_codes = [item[0] for item in pool]
        daily = xtdata.get_market_data_ex(
            field_list=["close", "high", "low", "amount"],
            stock_list=pool_codes,
            period="1d",
            count=130,
            dividend_type="front_ratio",
            fill_data=True,
        ) or {}
        details = xtdata.get_instrument_detail_list(pool_codes) or {}
        rows: list[dict[str, object]] = []
        tick_lookup = {item[0]: item for item in pool}
        for ticker in pool_codes:
            history = daily.get(ticker)
            if history is None or "close" not in history or len(history) < 65:
                continue
            close = pd.to_numeric(history["close"], errors="coerce").replace(0, np.nan).dropna()
            if len(close) < 65:
                continue
            returns = close.pct_change(fill_method=None).dropna().tail(60)
            if len(returns) < 40:
                continue
            detail = details.get(ticker) or {}
            name = str(detail.get("InstrumentName") or ticker)
            if "ST" in name.upper() or "退" in name:
                continue
            _, realtime_amount, last_price, pct_change = tick_lookup[ticker]
            amount_series = pd.to_numeric(
                history.get("amount", pd.Series(dtype=float)), errors="coerce"
            ).replace(0, np.nan).dropna().tail(20)
            average_amount = float(amount_series.mean()) if not amount_series.empty else realtime_amount
            float_shares = float(detail.get("FloatVolume") or 0.0)
            float_market_cap = last_price * float_shares if float_shares > 0 else np.nan
            rows.append(
                {
                    "ticker": ticker,
                    "name": name,
                    "board": "沪市" if ticker.endswith(".SH") else "深市",
                    "latest_price": last_price,
                    "pct_change": pct_change,
                    "momentum_60d_pct": (float(close.iloc[-1] / close.iloc[-61]) - 1.0) * 100,
                    "volatility": float(returns.std(ddof=0) * math.sqrt(252)),
                    "average_amount": max(average_amount, 1.0),
                    "float_market_cap": float_market_cap,
                }
            )
        frame = pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()
        if len(frame) < top_n:
            raise MiniQMTConnectionError(
                f"only {len(frame)} QMT candidates have sufficient daily history; download 1d history first"
            )
        if frame["float_market_cap"].notna().any():
            cap_fill = float(frame["float_market_cap"].dropna().median())
        else:
            cap_fill = 1.0
        raw_factors = pd.DataFrame(
            {
                "momentum": frame["momentum_60d_pct"],
                "low_volatility": -frame["volatility"],
                "liquidity": np.log(frame["average_amount"]),
                "size": np.log(frame["float_market_cap"].fillna(cap_fill).clip(lower=1.0)),
            },
            index=frame.index,
        )
        from quant_portfolio_system import DataProcessor

        factors = DataProcessor().preprocess_factors(raw_factors, frame["board"])
        frame["alpha_score"] = (
            factors["momentum"] * 0.45
            + factors["low_volatility"] * 0.25
            + factors["liquidity"] * 0.20
            + factors["size"] * 0.10
        )
        selected = frame.nlargest(top_n, "alpha_score").copy()
        base_weight_pct = 100.0 / top_n
        selections: list[dict[str, object]] = []
        for rank, (ticker, row) in enumerate(selected.iterrows(), start=1):
            selections.append(
                {
                    "rank": rank,
                    "ticker": ticker,
                    "code": ticker.split(".", 1)[0],
                    "name": str(row["name"]),
                    "board": str(row["board"]),
                    "latest_price": round(float(row["latest_price"]), 3),
                    "pct_change": round(float(row["pct_change"]), 3),
                    "momentum_60d_pct": round(float(row["momentum_60d_pct"]), 3),
                    "alpha_score": round(float(row["alpha_score"]), 6),
                    "target_weight_pct": base_weight_pct,
                    "reasons": ["QMT 60日动量", "低波动", "流动性/规模"],
                }
            )
        return {
            "program": "MiniQMT A股市场因子备用选股",
            "mode": "a_share_selection",
            "data_mode": "live",
            "selection_method": "qmt_market_only_fallback",
            "is_synthetic": False,
            "source": "MiniQMT 沪深A股实时行情 + 本地前复权日线",
            "data_as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
            "fallback_reason": "公共基本面快照不可用；未虚构 PE/PB，改用 QMT 市场因子",
            "summary": {
                "raw_market_count": len(all_codes),
                "optimized_universe_count": len(frame),
                "selected_count": len(selections),
            },
            "selections": selections,
        }

    def submit_orders(
        self,
        orders: Iterable[dict[str, object]],
        *,
        live: bool = False,
    ) -> list[dict[str, object]]:
        order_list = list(orders)
        if not live:
            return [{**order, "status": "DRY_RUN", "order_id": None} for order in order_list]
        if os.environ.get("MINIQMT_ENABLE_LIVE_TRADING") != LIVE_ACKNOWLEDGEMENT:
            raise MiniQMTConfigurationError(
                "live trading blocked: set MINIQMT_ENABLE_LIVE_TRADING="
                f"{LIVE_ACKNOWLEDGEMENT} and pass --live"
            )
        if self.trader is None or self.account is None:
            raise MiniQMTConnectionError("MiniQMT is not connected")

        from xtquant import xtconstant, xtdata

        submitted: list[dict[str, object]] = []
        # Orders are already sell-first. Each order is synchronous so failures
        # are visible before moving to the next stock.
        for order in order_list:
            ticker = str(order["ticker"])
            side = str(order["side"])
            quantity = int(order["quantity"])
            tick = (xtdata.get_full_tick([ticker]) or {}).get(ticker, {})
            bid = float((tick.get("bidPrice") or [0])[0] or 0)
            ask = float((tick.get("askPrice") or [0])[0] or 0)
            if side == "buy":
                quote = ask
                order_type = xtconstant.STOCK_BUY
                multiplier = 1 + self.config.price_slippage_bps / 10_000
            else:
                quote = bid
                order_type = xtconstant.STOCK_SELL
                multiplier = 1 - self.config.price_slippage_bps / 10_000
            if quote <= 0:
                submitted.append({**order, "status": "SKIPPED_NO_QUOTE", "order_id": None})
                continue
            limit_price = round(quote * multiplier, 2)
            order_id = self.trader.order_stock(
                account=self.account,
                stock_code=ticker,
                order_type=order_type,
                order_volume=quantity,
                price_type=xtconstant.FIX_PRICE,
                price=limit_price,
                strategy_name="TW_HALF_KELLY",
                order_remark="TW probability forest half-Kelly rebalance",
            )
            submitted.append(
                {
                    **order,
                    "limit_price": limit_price,
                    "status": "SUBMITTED" if order_id > 0 else "REJECTED",
                    "order_id": int(order_id),
                }
            )
        return submitted


def run_local_miniqmt_rebalance(
    *,
    live: bool = False,
    selection_data_mode: str = "live",
    allow_qmt_selection_live: bool = False,
    seed: int = 42,
) -> dict[str, object]:
    """End-to-end local flow: select, signal, size, query and submit/dry-run."""
    from a_share_selector import MarketDataUnavailable, run_a_share_selection

    executor = MiniQMTKellyExecutor(MiniQMTConfig.from_env())
    executor.connect()
    try:
        try:
            selection = run_a_share_selection(
                top_n=20,
                universe_size=120,
                data_mode=selection_data_mode,
            )
        except MarketDataUnavailable as public_error:
            if selection_data_mode == "demo":
                raise
            try:
                selection = executor.build_qmt_market_selection(top_n=20)
            except Exception as qmt_error:
                raise MiniQMTConnectionError(
                    "both public A-share snapshot and QMT fallback failed: "
                    f"public={public_error}; qmt={type(qmt_error).__name__}: {qmt_error}"
                ) from qmt_error
            selection["fallback_reason"] = (
                f"公共快照失败（{public_error}）；已切换到 QMT 市场因子备用模型"
            )
        if live and bool(selection.get("is_synthetic")):
            raise MiniQMTConfigurationError(
                "live trading is blocked because the selection contains synthetic data"
            )
        using_qmt_fallback = selection.get("selection_method") == "qmt_market_only_fallback"
        if live and using_qmt_fallback and not allow_qmt_selection_live:
            raise MiniQMTConfigurationError(
                "live trading with the QMT market-only fallback is blocked; review the dry-run, "
                "then pass --allow-qmt-selection-live"
            )
        if live and using_qmt_fallback and os.environ.get(
            "MINIQMT_ENABLE_QMT_SELECTION_LIVE"
        ) != QMT_FALLBACK_ACKNOWLEDGEMENT:
            raise MiniQMTConfigurationError(
                "set MINIQMT_ENABLE_QMT_SELECTION_LIVE="
                f"{QMT_FALLBACK_ACKNOWLEDGEMENT} before using the fallback for live orders"
            )
        tickers = [str(item["ticker"]) for item in selection["selections"]]
        histories = executor.load_histories(tickers)
        total_asset, available_cash, positions = executor.account_snapshot()
        result = run_tw_kelly_portfolio(
            top_n=20,
            selection_data_mode=selection_data_mode,
            history_mode="provided",
            seed=seed,
            total_asset=total_asset,
            available_cash=available_cash,
            histories=histories,
            current_positions=positions,
            selection_result=selection,
            kelly_config=KellyConfig(),
        )
        result["execution"] = executor.submit_orders(result["orders"], live=live)
        result["execution_mode"] = "LIVE" if live else "DRY_RUN"
        return result
    finally:
        executor.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run guarded TW half-Kelly MiniQMT rebalance")
    parser.add_argument("--live", action="store_true", help="submit real orders; requires the live acknowledgement environment variable")
    parser.add_argument("--selection-data-mode", choices=["live", "demo"], default="live")
    parser.add_argument(
        "--allow-qmt-selection-live",
        action="store_true",
        help="after reviewing dry-run, permit the QMT market-only fallback in live mode",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        result = run_local_miniqmt_rebalance(
            live=args.live,
            selection_data_mode=args.selection_data_mode,
            allow_qmt_selection_live=args.allow_qmt_selection_live,
            seed=args.seed,
        )
    except (MiniQMTConfigurationError, MiniQMTConnectionError) as exc:
        parser.exit(2, f"MiniQMT rebalance failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
