"""Safe, explicitly registered adapters used by the Vercel web API."""

from __future__ import annotations

import datetime as dt
import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent

PROGRAMS = [
    {
        "id": "a_share_selector",
        "title": "A 股多因子选股",
        "file": "a_share_selector.py",
        "category": "沪深 A 股",
        "status": "ready",
        "description": "从沪深 A 股快照构建可交易池，完成因子预处理、Alpha 压缩和带约束的组合优化。",
        "notice": "自动模式优先使用东方财富实时快照；网络不可用时仅在允许的情况下切换到醒目标注的合成演示数据。",
        "parameters": [
            {
                "name": "data_mode",
                "label": "数据模式",
                "type": "select",
                "value": "auto",
                "options": [
                    {"value": "auto", "label": "自动：实时优先"},
                    {"value": "live", "label": "仅实时数据"},
                    {"value": "demo", "label": "演示数据"},
                ],
            },
            {"name": "top_n", "label": "输出标的数", "type": "number", "value": 20, "min": 5, "max": 50, "step": 1},
            {"name": "universe_size", "label": "优化候选池", "type": "number", "value": 120, "min": 30, "max": 250, "step": 10},
            {"name": "risk_aversion", "label": "风险厌恶系数", "type": "number", "value": 3, "min": 0.5, "max": 20, "step": 0.5},
            {"name": "max_weight_pct", "label": "个股权重上限(%)", "type": "number", "value": 8, "min": 3, "max": 20, "step": 0.5},
        ],
    },
    {
        "id": "boxoption2",
        "title": "全市场期权盒式扫描",
        "file": "boxoption2.py",
        "category": "ETF / 股指期权",
        "status": "ready",
        "description": "扫描沪深 ETF 期权和中金所股指期权，按标的、到期日和行权价配对后寻找盒式价差。",
        "notice": "覆盖真实存在的 ETF/股指期权，不连接 MiniQMT；行情为只读快照，多腿结果不是可执行交易指令。",
        "parameters": [
            {
                "name": "data_mode",
                "label": "数据模式",
                "type": "select",
                "value": "auto",
                "options": [
                    {"value": "auto", "label": "自动：实时优先"},
                    {"value": "live", "label": "仅实时数据"},
                    {"value": "demo", "label": "全市场演示数据"},
                ],
            },
            {"name": "interest_rate", "label": "无风险利率", "type": "number", "value": 0.03, "min": 0, "max": 1, "step": 0.001},
            {"name": "actionpoint", "label": "触发阈值", "type": "number", "value": 0.0001, "min": 0, "max": 100, "step": 0.0001},
            {"name": "desir_mount", "label": "订单数量", "type": "number", "value": 1, "min": 1, "max": 100, "step": 1},
            {"name": "top_n", "label": "输出机会数", "type": "number", "value": 20, "min": 5, "max": 50, "step": 1},
            {"name": "min_volume", "label": "四腿最小成交量", "type": "number", "value": 1, "min": 0, "max": 10000000, "step": 1},
        ],
    },
    {
        "id": "quant_portfolio_system",
        "title": "多因子组合优化",
        "file": "quant_portfolio_system.py",
        "category": "主动组合管理",
        "status": "ready",
        "description": "运行 Alpha 压缩、多因子风险模型和带中性约束的二次规划组合优化。",
        "notice": "使用确定性合成数据演示；云端仅执行内存计算，不写文件、不生成真实订单。",
        "parameters": [
            {"name": "asset_count", "label": "模拟资产数", "type": "number", "value": 60, "min": 20, "max": 120, "step": 10},
            {"name": "top_n", "label": "展示持仓数", "type": "number", "value": 20, "min": 5, "max": 50, "step": 1},
            {"name": "risk_aversion", "label": "主动风险厌恶系数", "type": "number", "value": 4, "min": 0.5, "max": 20, "step": 0.5},
            {"name": "seed", "label": "演示随机种子", "type": "number", "value": 42, "min": 0, "max": 1000000, "step": 1},
        ],
    },
    {
        "id": "tw_kelly_rebalance",
        "title": "TW 概率森林半凯利调仓",
        "file": "TWrandomf.pine → tw_kelly_strategy.py",
        "category": "信号与仓位管理",
        "status": "ready",
        "description": "连接 A 股多因子前 20 标的，计算 P(up)/P(down)，使用二分之一凯利生成目标仓位和调仓单。",
        "notice": "网页仅使用演示 15 分钟行情并输出只读调仓计划；真实 MiniQMT 下单只能在本地通过双重实盘开关执行。",
        "parameters": [
            {"name": "total_asset", "label": "模拟总资产(元)", "type": "number", "value": 1000000, "min": 100000, "max": 1000000000, "step": 100000},
            {"name": "seed", "label": "演示随机种子", "type": "number", "value": 42, "min": 0, "max": 1000000, "step": 1},
            {
                "name": "regime_mode",
                "label": "市场干预状态",
                "type": "select",
                "value": "normal",
                "options": [
                    {"value": "normal", "label": "正常：动量模型"},
                    {"value": "inflow", "label": "干预流入：反转模型"},
                    {"value": "outflow", "label": "干预流出：反转模型"},
                ],
            },
        ],
    },
    {
        "id": "bigmoneyflow",
        "title": "ETF 资金流监控",
        "file": "bigmoneyflow.py",
        "category": "行情采集",
        "status": "ready",
        "description": "通过 AkShare 拉取沪深 300 ETF 与上证 50 ETF 行情，计算盘后放量状态。",
        "notice": "成交额只是代理指标，不代表真实资金净流入，也不构成投资建议。",
        "parameters": [
            {"name": "trade_date", "label": "交易日期", "type": "date", "value": dt.date.today().isoformat(), "min": "2000-01-01", "max": "2099-12-31", "step": 1},
        ],
    },
    {
        "id": "runtime_info",
        "title": "Python 运行环境",
        "file": "web_runner.py",
        "category": "环境诊断",
        "status": "ready",
        "description": "显示 Python、操作系统、Vercel 区域和项目程序数量。",
        "notice": "用于确认 Python Function 已在云端正常启动。",
        "parameters": [],
    },
    {
        "id": "project_overview",
        "title": "项目程序概览",
        "file": "*.py",
        "category": "项目诊断",
        "status": "ready",
        "description": "扫描项目根目录中的 Python 文件并显示云端兼容状态。",
        "notice": "只读取文件名，不执行策略或交易脚本。",
        "parameters": [],
    },
    {
        "id": "qmt_programs",
        "title": "MiniQMT 交易程序",
        "file": "boxoption.py / connect.py / order_588000.py / querytest.py / test.py",
        "category": "本地交易",
        "status": "local_only",
        "description": "依赖 Windows、券商客户端、本地 DLL 和已登录的交易账户。",
        "notice": "Vercel 是 Linux 云函数，无法访问你电脑里的 MiniQMT。",
        "parameters": [],
    },
    {
        "id": "ml_strategy",
        "title": "随机森林策略",
        "file": "ML.py",
        "category": "QMT 策略",
        "status": "local_only",
        "description": "依赖 QMT 的 ContextInfo、TA-Lib 和交易函数，只能在对应策略环境运行。",
        "notice": "后续可抽离纯预测函数，再注册为安全的网页演示。",
        "parameters": [],
    },
]


def _number(
    payload: dict[str, Any], name: str, default: float, minimum: float, maximum: float
) -> float:
    try:
        value = float(payload.get(name, default))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"参数 {name} 必须是数字") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"参数 {name} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _choice(
    payload: dict[str, Any], name: str, default: str, allowed: set[str]
) -> str:
    value = str(payload.get(name, default)).strip().lower()
    if value not in allowed:
        raise ValueError(f"参数 {name} 不在允许范围内")
    return value


def _run_a_share_selector(payload: dict[str, Any]) -> dict[str, Any]:
    from a_share_selector import MarketDataUnavailable, run_a_share_selection

    top_n = int(_number(payload, "top_n", 20, 5, 50))
    universe_size = int(_number(payload, "universe_size", 120, 30, 250))
    risk_aversion = _number(payload, "risk_aversion", 3.0, 0.5, 20)
    max_weight_pct = _number(payload, "max_weight_pct", 8.0, 3.0, 20.0)
    data_mode = _choice(payload, "data_mode", "auto", {"auto", "live", "demo"})
    try:
        return run_a_share_selection(
            top_n=top_n,
            universe_size=universe_size,
            data_mode=data_mode,
            risk_aversion=risk_aversion,
            max_weight=max_weight_pct / 100,
        )
    except MarketDataUnavailable as exc:
        raise ValueError(str(exc)) from exc


def _run_boxoption2(payload: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("ALLOW_DEMO_EXECUTION", "true").lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        raise PermissionError("演示运行已被环境变量 ALLOW_DEMO_EXECUTION 关闭")
    from boxoption2 import run_demo

    interest_rate = _number(payload, "interest_rate", 0.03, 0, 1)
    actionpoint = _number(payload, "actionpoint", 0.0001, 0, 100)
    quantity = int(_number(payload, "desir_mount", 1, 1, 100))
    top_n = int(_number(payload, "top_n", 20, 5, 50))
    min_volume = int(_number(payload, "min_volume", 1, 0, 10_000_000))
    data_mode = _choice(payload, "data_mode", "auto", {"auto", "live", "demo"})
    try:
        return run_demo(
            interest_rate,
            actionpoint,
            quantity,
            data_mode=data_mode,
            top_n=top_n,
            min_volume=min_volume,
        )
    except Exception as exc:
        from option_market_scanner import OptionMarketDataUnavailable

        if isinstance(exc, OptionMarketDataUnavailable):
            raise ValueError(str(exc)) from exc
        raise


def _run_quant_portfolio_system(payload: dict[str, Any]) -> dict[str, Any]:
    """Run the portfolio model without filesystem or plotting side effects."""
    asset_count = int(_number(payload, "asset_count", 60, 20, 120))
    top_n = int(_number(payload, "top_n", 20, 5, 50))
    risk_aversion = _number(payload, "risk_aversion", 4.0, 0.5, 20.0)
    seed = int(_number(payload, "seed", 42, 0, 1_000_000))

    from quant_portfolio_system import run_demo

    result = run_demo(
        output_dir=None,
        asset_count=asset_count,
        seed=seed,
        show=False,
        write_artifacts=False,
        risk_aversion=risk_aversion,
    )
    holdings = result["holdings"].sort_values(
        "portfolio_weight", ascending=False
    ).head(min(top_n, asset_count))
    portfolio = []
    for rank, (asset, row) in enumerate(holdings.iterrows(), start=1):
        portfolio.append(
            {
                "rank": rank,
                "asset": str(asset),
                "industry": str(row["industry"]),
                "benchmark_weight_pct": round(float(row["benchmark_weight"]) * 100, 4),
                "portfolio_weight_pct": round(float(row["portfolio_weight"]) * 100, 4),
                "active_weight_pct": round(float(row["active_weight"]) * 100, 4),
                "alpha_forecast_pct": round(float(row["alpha"]) * 100, 5),
            }
        )

    summary = dict(result["summary"])
    summary["displayed_holding_count"] = len(portfolio)
    return {
        "program": "quant_portfolio_system.py",
        "mode": "portfolio_optimization",
        "is_synthetic": True,
        "source": "确定性合成多因子研究样本",
        "data_as_of": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": summary,
        "portfolio": portfolio,
        "methodology": {
            "objective": "maximize alpha' h_A - lambda_A * h_A' V h_A - transaction costs",
            "alpha_refining": "alpha = residual volatility × IC × standardized score",
            "risk_model": "V = X F X' + Delta",
            "constraints": "全投资、禁止空头、行业/风格中性和个股上限",
            "runtime": "内存计算；不写部署目录，不导入 Matplotlib",
        },
    }


def _run_tw_kelly_rebalance(payload: dict[str, Any]) -> dict[str, Any]:
    total_asset = _number(payload, "total_asset", 1_000_000, 100_000, 1_000_000_000)
    seed = int(_number(payload, "seed", 42, 0, 1_000_000))
    regime_mode = _choice(payload, "regime_mode", "normal", {"normal", "inflow", "outflow"})
    from tw_kelly_strategy import RegimeInput, run_tw_kelly_portfolio

    regimes = {
        "normal": RegimeInput(False, 0.0, 0.0, "NORMAL"),
        "inflow": RegimeInput(True, 1.0, 2.5, "INTERVENTION_INFLOW"),
        "outflow": RegimeInput(True, -1.0, -2.5, "INTERVENTION_OUTFLOW"),
    }
    return run_tw_kelly_portfolio(
        top_n=20,
        universe_size=120,
        selection_data_mode="demo",
        history_mode="demo",
        seed=seed,
        total_asset=total_asset,
        available_cash=total_asset,
        regime=regimes[regime_mode],
    )


def _run_runtime_info(_: dict[str, Any]) -> dict[str, Any]:
    return {
        "program": "Python runtime",
        "mode": "diagnostic",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "is_vercel": bool(os.environ.get("VERCEL")),
            "vercel_region": os.environ.get("VERCEL_REGION", "local"),
            "registered_programs": len(PROGRAMS),
        },
    }


def _run_bigmoneyflow(payload: dict[str, Any]) -> dict[str, Any]:
    raw_date = str(payload.get("trade_date", dt.date.today().isoformat()))
    try:
        trade_date = dt.date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError("交易日期必须使用 YYYY-MM-DD 格式") from exc
    if trade_date > dt.date.today():
        raise ValueError("交易日期不能晚于今天")

    from bigmoneyflow import run_once

    result = run_once(trade_date.isoformat())
    return {
        "program": "bigmoneyflow.py",
        "mode": "market_data",
        "source": "AkShare / Sina + Eastmoney",
        "methodology": "ETF daily turnover is used as a proxy for liquidity inflow",
        **result,
    }


def _run_project_overview(_: dict[str, Any]) -> dict[str, Any]:
    files = sorted(path.name for path in ROOT.glob("*.py") if path.is_file())
    cloud_ready = [item["file"] for item in PROGRAMS if item["status"] == "ready"]
    local_only = [item["file"] for item in PROGRAMS if item["status"] == "local_only"]
    return {
        "program": "Project overview",
        "mode": "diagnostic",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary": {
            "python_file_count": len(files),
            "cloud_ready_entries": len(cloud_ready),
            "local_only_entries": len(local_only),
        },
        "files": files,
        "cloud_ready": cloud_ready,
        "local_only": local_only,
    }


RUNNERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "a_share_selector": _run_a_share_selector,
    "boxoption2": _run_boxoption2,
    "quant_portfolio_system": _run_quant_portfolio_system,
    "tw_kelly_rebalance": _run_tw_kelly_rebalance,
    "bigmoneyflow": _run_bigmoneyflow,
    "runtime_info": _run_runtime_info,
    "project_overview": _run_project_overview,
}


def public_config() -> dict[str, Any]:
    return {
        "name": os.environ.get("APP_NAME", "A 股量化选股看板"),
        "subtitle": os.environ.get(
            "APP_SUBTITLE", "从沪深 A 股可交易池生成可解释的多因子候选组合"
        ),
        "notice": os.environ.get(
            "APP_PUBLIC_NOTICE", "选股结果仅用于研究展示，不构成投资建议，也不会触发真实交易。"
        ),
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def run_registered(program_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    runner = RUNNERS.get(program_id)
    if runner is None:
        raise KeyError("该程序未开放云端运行")
    return runner(payload)
