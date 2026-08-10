"""Publish genuine MiniQMT market snapshots to the existing Vercel website.

Run this process on the Windows computer where QMT is open and logged in.  It
does not submit orders and does not upload account identifiers, positions,
credentials or the local terminal path.  A failed QMT query is reported as
unavailable; synthetic/demo data is never generated.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from qmt_auth import resolve_qmt_webhook_secret

from live_snapshot_store import SCHEMA_VERSION, validate_bundle


LOGGER = logging.getLogger("qmt_live_publisher")
DEFAULT_WEBHOOK_URL = "https://quantcollection-aa5n.vercel.app/api/live"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(override=False)
        load_dotenv(".env.local", override=False)
    except ImportError:
        LOGGER.warning("python-dotenv 未安装，仅使用当前进程环境变量")


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (dt.date, dt.datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, np.ndarray, pd.Series)):
        return [_json_safe(item) for item in value]
    raise TypeError(f"无法序列化 QMT 结果类型: {type(value).__name__}")


def _configure_qmt(userdata_path: Path):
    if not userdata_path.is_dir():
        raise RuntimeError("MINI_QMT_PATH 不存在或不是目录")
    data_dir = userdata_path / "datadir"
    if not data_dir.is_dir():
        raise RuntimeError("MINI_QMT_PATH 下未找到 datadir")
    try:
        from xtquant import xtdata
    except Exception as exc:
        raise RuntimeError("当前 Python 环境无法导入 xtquant") from exc
    # Historical bar readers accept this explicit Point-In-Time data directory;
    # realtime ticks still use QMT's logged-in local market-data service.
    xtdata.data_dir = str(data_dir)
    if hasattr(xtdata, "enable_hello"):
        xtdata.enable_hello = False
    return xtdata


def _build_selection(userdata_path: Path, top_n: int) -> dict[str, Any]:
    from miniqmt_kelly_executor import MiniQMTConfig, MiniQMTKellyExecutor

    executor = MiniQMTKellyExecutor(
        MiniQMTConfig(
            userdata_path=str(userdata_path),
            account_id="MARKET_DATA_ONLY",
            session_id=int(os.environ.get("MINIQMT_SESSION_ID", "952701")),
        )
    )
    result = executor.build_qmt_market_selection(top_n=top_n)
    selections = result.get("selections", [])
    for item in selections:
        item["reasons"] = ["QMT 60日动量", "低波动", "流动性与规模"]
        item.setdefault("dynamic_pe", None)
        item.setdefault("pb", None)
        item.setdefault("active_weight_pct", 0.0)
    coverage = sum(float(item.get("target_weight_pct", 0)) for item in selections)
    summary = dict(result.get("summary", {}))
    summary.update(
        {
            "eligible_count": summary.get("optimized_universe_count"),
            "selected_count": len(selections),
            "selected_weight_coverage_pct": round(coverage, 4),
            "expected_active_return_pct": None,
            "active_risk_pct": None,
            "optimized_information_ratio": None,
            "forecast_fundamental_law_ir": None,
            "max_weight_pct": max((float(item.get("target_weight_pct", 0)) for item in selections), default=0),
        }
    )
    result.update(
        {
            "program": "MiniQMT A股市场因子选股",
            "mode": "a_share_selection",
            "data_mode": "live",
            "is_synthetic": False,
            "source": "MiniQMT 沪深A股实时行情与本地前复权日线",
            "data_as_of": _iso_now(),
            "summary": summary,
            "methodology": {
                "factors": "60日动量、实现波动率、成交额流动性、流通市值规模",
                "boundary": "仅使用 QMT 已下载行情；未下载的 PE/PB 不虚构、不补零",
                "execution": "网页只读，不连接交易账户，不提交订单",
            },
        }
    )
    return _json_safe(result)


def _build_portfolio(selection: dict[str, Any]) -> dict[str, Any]:
    holdings = []
    for item in selection["selections"]:
        weight = float(item["target_weight_pct"])
        holdings.append(
            {
                "rank": int(item["rank"]),
                "asset": str(item["ticker"]),
                "industry": str(item["board"]),
                "benchmark_weight_pct": weight,
                "portfolio_weight_pct": weight,
                "active_weight_pct": 0.0,
                "alpha_forecast_pct": float(item["alpha_score"]),
            }
        )
    max_weight = max((item["portfolio_weight_pct"] for item in holdings), default=0) / 100
    return {
        "program": "QMT 市场因子组合",
        "mode": "portfolio_optimization",
        "is_synthetic": False,
        "source": "MiniQMT 沪深A股实时行情与本地历史行情",
        "data_as_of": selection["data_as_of"],
        "summary": {
            "asset_count": len(holdings),
            "displayed_holding_count": len(holdings),
            "max_weight": max_weight,
        },
        "portfolio": holdings,
        "methodology": {
            "allocation": "本轮 QMT 市场因子前 N 名等权只读组合",
            "alpha_score": "由动量、低波动、流动性与规模截面分数组成，不冒充预期收益率",
            "boundary": "缺少 QMT 基本面字段时不运行原合成 QP 模型",
        },
    }


def _build_tw_kelly(userdata_path: Path, selection: dict[str, Any]) -> dict[str, Any]:
    from miniqmt_kelly_executor import MiniQMTConfig, MiniQMTKellyExecutor
    from tw_kelly_strategy import run_tw_kelly_portfolio

    executor = MiniQMTKellyExecutor(
        MiniQMTConfig(
            userdata_path=str(userdata_path),
            account_id="MARKET_DATA_ONLY",
            session_id=int(os.environ.get("MINIQMT_SESSION_ID", "952701")),
        )
    )
    tickers = [str(item["ticker"]) for item in selection["selections"]]
    histories = executor.load_histories(tickers)
    total_asset = float(os.environ.get("QMT_DISPLAY_TOTAL_ASSET", "1000000"))
    result = run_tw_kelly_portfolio(
        top_n=len(tickers),
        selection_result=selection,
        history_mode="provided",
        histories=histories,
        total_asset=total_asset,
        available_cash=total_asset,
        current_positions={},
    )
    result.update(
        {
            "is_synthetic": False,
            "source": "MiniQMT 实盘选股快照与本地前复权 15 分钟 OHLCV",
            "data_as_of": _iso_now(),
        }
    )
    result.setdefault("methodology", {})["account_boundary"] = "展示资产仅用于只读仓位缩放，不读取账户、不下单"
    return _json_safe(result)


def _build_money_flow(xtdata: Any) -> dict[str, Any]:
    etfs = [
        code.strip()
        for code in os.environ.get("QMT_FLOW_ETFS", "510300.SH,510050.SH,159919.SZ").split(",")
        if code.strip()
    ]
    raw = xtdata.get_market_data_ex(
        field_list=["close", "amount", "volume"],
        stock_list=etfs,
        period="1d",
        count=45,
        dividend_type="front_ratio",
        fill_data=True,
    ) or {}
    rows = []
    for code in etfs:
        frame = raw.get(code)
        if frame is None or len(frame) < 21:
            continue
        amount = pd.to_numeric(frame["amount"], errors="coerce").replace(0, np.nan).dropna()
        if len(amount) < 21:
            continue
        baseline = float(amount.iloc[-21:-1].mean())
        latest = float(amount.iloc[-1])
        delta = latest - baseline
        rows.append({"ticker": code, "amount_cny": latest, "baseline_amount_cny": baseline, "amount_delta_cny": delta})
    if not rows:
        raise RuntimeError("QMT 未返回足够的 ETF 日线成交额；请先下载历史行情")
    total_amount = sum(item["amount_cny"] for item in rows)
    total_delta = sum(item["amount_delta_cny"] for item in rows)
    ratio_bps = total_delta / total_amount * 10000 if total_amount > 0 else 0.0
    direction = "INFLOW_PROXY" if total_delta > 0 else "OUTFLOW_PROXY" if total_delta < 0 else "NEUTRAL"
    strength = abs(ratio_bps) / 100
    return {
        "program": "MiniQMT ETF 成交额监控",
        "mode": "market_data",
        "is_synthetic": False,
        "source": "MiniQMT 本地前复权 ETF 日线成交额",
        "data_as_of": _iso_now(),
        "regime": "VOLUME_EXPANSION" if strength >= 1 else "NORMAL",
        "direction": direction,
        "total_net_flow_cny": round(total_delta, 2),
        "flow_ratio_bps": round(ratio_bps, 4),
        "strength_score": round(strength, 4),
        "etf_count": len(rows),
        "etfs": _json_safe(rows),
        "summary": {"etf_count": len(rows), "amount_delta_cny": round(total_delta, 2)},
        "methodology": {
            "proxy": "当日成交额减过去 20 日均值，仅为放量方向代理，不等同资金净流入",
            "source_boundary": "全部价格、成交量和成交额均来自本机 QMT",
        },
    }


def _build_options() -> dict[str, Any]:
    from option_market_scanner import MarketWideBoxScanner, OptionScanConfig
    from scanner_worker import QMTETFOptionProvider, WorkerConfig

    config = WorkerConfig.from_env(require_webhook=False)
    snapshot = QMTETFOptionProvider(config.universe_refresh_seconds).fetch()
    result = MarketWideBoxScanner(
        OptionScanConfig(
            top_n=config.top_n,
            interest_rate=config.interest_rate,
            actionpoint=config.min_true_net_profit_cny,
            min_volume=config.min_depth,
            data_mode="live",
        )
    ).run(snapshot)
    result["is_synthetic"] = False
    result["source"] = "MiniQMT 沪深 ETF 期权实时买一/卖一"
    return _json_safe(result)


def _safe_error(exc: Exception, userdata_path: Path) -> str:
    message = str(exc).replace(str(userdata_path), "%MINI_QMT_PATH%").strip()
    translations = {
        "sufficient daily history": "QMT A股日线历史不足；请在终端下载至少 130 根 1d 前复权行情",
        "insufficient 15m history": "QMT 15分钟历史不足；请为入选股票下载至少 520 根 15m 行情",
        "too few liquid A shares": "QMT 实时快照中的可交易 A 股数量不足",
    }
    for pattern, translated in translations.items():
        if pattern in message:
            return translated
    return f"{type(exc).__name__}: {message[:300]}"


def build_bundle(userdata_path: Path, top_n: int = 20) -> dict[str, Any]:
    xtdata = _configure_qmt(userdata_path)
    programs: dict[str, Any] = {}
    errors: dict[str, str] = {}

    selection = None
    try:
        selection = _build_selection(userdata_path, top_n)
        programs["a_share_selector"] = selection
        programs["quant_portfolio_system"] = _build_portfolio(selection)
    except Exception as exc:
        errors["a_share_selector"] = _safe_error(exc, userdata_path)
        errors["quant_portfolio_system"] = "依赖本轮 QMT A股选股快照"

    if selection is not None:
        try:
            programs["tw_kelly_rebalance"] = _build_tw_kelly(userdata_path, selection)
        except Exception as exc:
            errors["tw_kelly_rebalance"] = _safe_error(exc, userdata_path)
    else:
        errors["tw_kelly_rebalance"] = "依赖本轮 QMT A股选股快照"

    builders: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("bigmoneyflow", lambda: _build_money_flow(xtdata)),
        ("boxoption2", _build_options),
    ]
    for program_id, builder in builders:
        try:
            programs[program_id] = builder()
        except Exception as exc:
            errors[program_id] = _safe_error(exc, userdata_path)

    # QMT market data does not contain the complete analyst-consensus/network
    # event schema required by the HK factor engine.  Keep the page honest.
    errors["hk_factor"] = "QMT 当前未提供境内外一致预期、股东户数及共同分析师网络字段，未生成港股因子值"
    if not programs:
        raise RuntimeError("本轮所有 QMT 数据程序均不可用，保留服务器上一份真实快照")
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "source": "MiniQMT/QMT local Windows publisher",
        "is_synthetic": False,
        "programs": programs,
        "errors": errors,
    }
    return validate_bundle(_json_safe(bundle))


def post_bundle(bundle: dict[str, Any], url: str, secret: str, secret_header: str) -> dict[str, Any]:
    if not url.startswith("https://"):
        raise RuntimeError("QMT_WEBHOOK_URL 必须使用 https://")
    if len(secret) < 24 or secret.lower().startswith("replace_with_"):
        raise RuntimeError("QMT_WEBHOOK_SECRET 至少需要 24 个字符")
    body = json.dumps(bundle, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"POST"}),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    response = session.post(
        url,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            secret_header: secret,
            "X-Payload-SHA256": hashlib.sha256(body).hexdigest(),
            "User-Agent": "QMT-Live-Publisher/1.0",
        },
        timeout=(3.0, float(os.environ.get("QMT_HTTP_TIMEOUT", "20"))),
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Vercel 拒绝 QMT 快照: {payload}")
    return payload


def main() -> None:
    _load_env()
    parser = argparse.ArgumentParser(description="MiniQMT 实盘快照发布器（只读、不下单、无演示回退）")
    parser.add_argument("--once", action="store_true", help="采集并发布一次后退出")
    parser.add_argument("--dry-run", action="store_true", help="只采集校验，不上传")
    parser.add_argument("--top-n", type=int, default=20, help="QMT 选股数量，默认 20")
    args = parser.parse_args()
    if not 5 <= args.top_n <= 50:
        parser.error("--top-n 必须在 5 到 50 之间")

    path_value = os.environ.get("MINI_QMT_PATH", "").strip() or os.environ.get("MINIQMT_PATH", "").strip()
    if not path_value:
        parser.error("请在本机 .env 设置 MINI_QMT_PATH")
    userdata_path = Path(path_value).expanduser().resolve()
    url = os.environ.get("QMT_WEBHOOK_URL", DEFAULT_WEBHOOK_URL).strip()
    secret = resolve_qmt_webhook_secret()
    secret_header = os.environ.get("QMT_SECRET_HEADER", "X-QMT-Secret").strip()
    interval = max(15.0, float(os.environ.get("QMT_PUBLISH_INTERVAL", "60")))

    while True:
        started = time.perf_counter()
        failed = False
        try:
            bundle = build_bundle(userdata_path, args.top_n)
            if args.dry_run:
                LOGGER.info("QMT 校验通过：%s；失败项：%s", sorted(bundle["programs"]), bundle["errors"])
            else:
                acknowledgement = post_bundle(bundle, url, secret, secret_header)
                LOGGER.info("已上传 %s 个 QMT 实盘程序：%s", acknowledgement.get("accepted"), acknowledgement.get("programs"))
        except Exception:
            failed = True
            LOGGER.exception("本轮 QMT 实盘快照未发布")
        if args.once:
            if failed:
                raise SystemExit(1)
            break
        elapsed = time.perf_counter() - started
        time.sleep(max(1.0, interval - elapsed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
