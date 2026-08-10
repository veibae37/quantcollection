"""Explicit, read-only adapters for the existing Vercel Quant Console."""

from __future__ import annotations

import datetime as dt
import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent
LIVE_QMT_PROGRAM_IDS = frozenset(
    {
        "a_share_selector",
        "boxoption2",
        "quant_portfolio_system",
        "tw_kelly_rebalance",
        "bigmoneyflow",
    }
)
QMT_NOTICE = "仅显示本机 MiniQMT 上传的真实行情快照；取数失败时不使用模拟、合成或公网替代数据。"


PROGRAMS = [
    {
        "id": "a_share_selector",
        "title": "A 股多因子选股",
        "file": "qmt_live_publisher.py",
        "category": "沪深 A 股",
        "status": "ready",
        "description": "读取本机 MiniQMT 生成的沪深 A 股市场因子选股快照。",
        "notice": QMT_NOTICE,
        "parameters": [],
    },
    {
        "id": "boxoption2",
        "title": "沪深 ETF 期权盒式扫描",
        "file": "scanner_worker.py / qmt_live_publisher.py",
        "category": "沪深 ETF 期权",
        "status": "ready",
        "description": "读取 MiniQMT 沪深 ETF 期权真实买一/卖一快照及费后盒式价差。",
        "notice": QMT_NOTICE,
        "parameters": [],
    },
    {
        "id": "quant_portfolio_system",
        "title": "QMT 市场因子组合",
        "file": "qmt_live_publisher.py",
        "category": "主动组合管理",
        "status": "ready",
        "description": "读取基于 QMT 市场因子构建的只读组合快照。",
        "notice": QMT_NOTICE,
        "parameters": [],
    },
    {
        "id": "tw_kelly_rebalance",
        "title": "TW 概率森林半凯利调仓",
        "file": "tw_kelly_strategy.py / qmt_live_publisher.py",
        "category": "信号与仓位管理",
        "status": "ready",
        "description": "读取 QMT 选股与本地 15 分钟 OHLCV 计算的半凯利只读调仓计划。",
        "notice": QMT_NOTICE,
        "parameters": [],
    },
    {
        "id": "bigmoneyflow",
        "title": "ETF 成交额监控",
        "file": "qmt_live_publisher.py",
        "category": "行情采集",
        "status": "ready",
        "description": "读取 MiniQMT ETF 日线成交额并监控相对过去 20 日均值的放量方向。",
        "notice": QMT_NOTICE,
        "parameters": [],
    },
    {
        "id": "runtime_info",
        "title": "Python 运行环境",
        "file": "web_runner.py",
        "category": "环境诊断",
        "status": "ready",
        "description": "显示 Python、操作系统、Vercel 区域和已注册程序数量。",
        "notice": "仅用于确认 Python Function 正常启动。",
        "parameters": [],
    },
    {
        "id": "project_overview",
        "title": "项目程序概览",
        "file": "*.py",
        "category": "项目诊断",
        "status": "ready",
        "description": "只读扫描项目根目录中的 Python 文件及云端兼容状态。",
        "notice": "只读取文件名，不执行交易脚本。",
        "parameters": [],
    },
    {
        "id": "qmt_programs",
        "title": "MiniQMT 交易程序",
        "file": "boxoption.py / connect.py / order_588000.py / querytest.py / test.py",
        "category": "本地交易",
        "status": "local_only",
        "description": "依赖 Windows、券商客户端、本地 DLL 和已登录交易账户。",
        "notice": "网页仅接收发布器上传的只读市场快照，不连接交易账户。",
        "parameters": [],
    },
    {
        "id": "ml_strategy",
        "title": "随机森林策略",
        "file": "ML.py",
        "category": "QMT 策略",
        "status": "local_only",
        "description": "依赖 QMT ContextInfo、TA-Lib 与本地交易函数，只能在对应策略环境运行。",
        "notice": "公开 API 不执行策略上下文或交易函数。",
        "parameters": [],
    },
]


def _run_qmt_snapshot(program_id: str) -> dict[str, Any]:
    from live_snapshot_store import get_program_snapshot

    result, metadata = get_program_snapshot(program_id)
    if result.get("is_synthetic") is not False:
        raise ValueError("服务器拒绝展示非实盘数据")
    return {**result, "snapshot_meta": metadata}


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
    program_id: (lambda _payload, pid=program_id: _run_qmt_snapshot(pid))
    for program_id in LIVE_QMT_PROGRAM_IDS
}
RUNNERS.update({"runtime_info": _run_runtime_info, "project_overview": _run_project_overview})


def public_programs() -> list[dict[str, Any]]:
    return [dict(item) for item in PROGRAMS]


def public_config() -> dict[str, Any]:
    return {
        "name": os.environ.get("APP_NAME", "A 股量化选股看板"),
        "subtitle": "从 MiniQMT 实盘可交易池生成可解释的只读量化快照",
        "notice": "网页只展示 MiniQMT 上传的真实快照；无模拟回退，不构成投资建议，也不会触发交易。",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
    }


def run_registered(program_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    runner = RUNNERS.get(program_id)
    if runner is None:
        raise KeyError("该程序未开放云端运行")
    return runner(payload)
