"""Validated persistence for live snapshots published by the local MiniQMT host.

Vercel cannot connect to a Windows QMT terminal.  The local publisher therefore
calculates read-only results and uploads one bounded JSON bundle.  This module is
the only cloud-side persistence boundary and rejects demo/synthetic payloads.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "qmt-live-bundle.v1"
BLOB_PATH = "qmt-live/latest.json"
ALLOWED_PROGRAM_IDS = frozenset(
    {
        "a_share_selector",
        "boxoption2",
        "quant_portfolio_system",
        "tw_kelly_rebalance",
        "bigmoneyflow",
        "hk_factor",
    }
)


class LiveSnapshotError(RuntimeError):
    """Base class for live snapshot failures."""


class LiveSnapshotUnavailable(LiveSnapshotError):
    """Raised when no genuine QMT snapshot is currently readable."""


class LiveSnapshotValidationError(LiveSnapshotError, ValueError):
    """Raised when an uploaded payload violates the live-only contract."""


def _parse_iso_datetime(value: Any, field: str) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise LiveSnapshotValidationError(f"{field} 必须是 ISO-8601 时间") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LiveSnapshotValidationError(f"{field} 必须包含时区")
    return parsed.astimezone(dt.timezone.utc)


def _validate_finite(value: Any, path: str = "payload") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LiveSnapshotValidationError(f"{path} 含有 NaN 或 Infinity")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_finite(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise LiveSnapshotValidationError(f"{path} 的键必须是字符串")
            _validate_finite(item, f"{path}.{key}")
        return
    raise LiveSnapshotValidationError(f"{path} 含有不可序列化类型 {type(value).__name__}")


def validate_bundle(payload: Any) -> dict[str, Any]:
    """Validate and return a live-only QMT bundle without mutating it."""
    if not isinstance(payload, dict):
        raise LiveSnapshotValidationError("上传内容必须是 JSON 对象")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise LiveSnapshotValidationError(f"schema_version 必须为 {SCHEMA_VERSION}")
    generated_at = _parse_iso_datetime(payload.get("generated_at"), "generated_at")
    if generated_at > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise LiveSnapshotValidationError("generated_at 不能位于未来")

    source = str(payload.get("source", ""))
    if "qmt" not in source.lower():
        raise LiveSnapshotValidationError("source 必须明确标识 QMT/MiniQMT")
    if payload.get("is_synthetic") not in (None, False):
        raise LiveSnapshotValidationError("拒绝演示或合成数据")

    programs = payload.get("programs")
    if not isinstance(programs, dict) or not programs:
        raise LiveSnapshotValidationError("programs 必须至少包含一个实盘程序快照")
    unknown = set(programs) - ALLOWED_PROGRAM_IDS
    if unknown:
        raise LiveSnapshotValidationError(f"存在未注册程序: {', '.join(sorted(unknown))}")

    for program_id, result in programs.items():
        if not isinstance(result, dict):
            raise LiveSnapshotValidationError(f"programs.{program_id} 必须是对象")
        if result.get("is_synthetic") is not False:
            raise LiveSnapshotValidationError(f"programs.{program_id} 不是明确的实盘结果")
        if "qmt" not in str(result.get("source", "")).lower():
            raise LiveSnapshotValidationError(f"programs.{program_id}.source 不是 QMT 数据源")
        _parse_iso_datetime(result.get("data_as_of"), f"programs.{program_id}.data_as_of")

    errors = payload.get("errors", {})
    if not isinstance(errors, dict) or set(errors) - ALLOWED_PROGRAM_IDS:
        raise LiveSnapshotValidationError("errors 含有非法程序标识")
    _validate_finite(payload)
    return payload


def _local_snapshot_path() -> Path | None:
    raw = os.environ.get("QMT_LIVE_SNAPSHOT_FILE", "").strip()
    if not raw or os.environ.get("VERCEL"):
        return None
    return Path(raw).expanduser().resolve()


def save_live_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a validated snapshot to Vercel Blob (or an explicit local file)."""
    validated = validate_bundle(payload)
    body = json.dumps(validated, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")

    local_path = _local_snapshot_path()
    if local_path is not None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = local_path.with_suffix(local_path.suffix + ".tmp")
        temp_path.write_bytes(body)
        temp_path.replace(local_path)
        return {"pathname": str(local_path), "size": len(body), "storage": "local"}

    if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
        raise LiveSnapshotUnavailable("Vercel 项目尚未配置 BLOB_READ_WRITE_TOKEN")
    try:
        from vercel.blob import put

        result = put(
            BLOB_PATH,
            body,
            access="private",
            content_type="application/json; charset=utf-8",
            add_random_suffix=False,
            overwrite=True,
        )
    except Exception as exc:
        raise LiveSnapshotUnavailable("QMT 实盘快照写入失败") from exc
    return {"pathname": getattr(result, "pathname", BLOB_PATH), "size": len(body), "storage": "vercel_blob"}


def load_live_bundle() -> dict[str, Any]:
    """Load the latest validated QMT bundle; never generate a fallback."""
    local_path = _local_snapshot_path()
    try:
        if local_path is not None:
            body = local_path.read_bytes()
        else:
            if not os.environ.get("BLOB_READ_WRITE_TOKEN"):
                raise LiveSnapshotUnavailable("Vercel 项目尚未配置实盘快照存储")
            from vercel.blob import get

            result = get(BLOB_PATH, access="private")
            if result is None:
                raise LiveSnapshotUnavailable("尚未收到 QMT 实盘快照")
            body = result.content
        payload = json.loads(body.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    except LiveSnapshotUnavailable:
        raise
    except FileNotFoundError as exc:
        raise LiveSnapshotUnavailable("尚未收到 QMT 实盘快照") from exc
    except Exception as exc:
        raise LiveSnapshotUnavailable("无法读取 QMT 实盘快照") from exc
    return validate_bundle(payload)


def get_program_snapshot(program_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return one live program result plus age metadata."""
    if program_id not in ALLOWED_PROGRAM_IDS:
        raise KeyError("该程序未注册实盘快照")
    bundle = load_live_bundle()
    result = bundle["programs"].get(program_id)
    if result is None:
        reason = str(bundle.get("errors", {}).get(program_id, "本轮 QMT 快照未包含该程序"))
        raise LiveSnapshotUnavailable(reason)

    generated_at = _parse_iso_datetime(bundle["generated_at"], "generated_at")
    age_seconds = max(0, int((dt.datetime.now(dt.timezone.utc) - generated_at).total_seconds()))
    stale_after = max(60, int(os.environ.get("QMT_SNAPSHOT_STALE_SECONDS", "900")))
    metadata = {
        "schema_version": bundle["schema_version"],
        "generated_at": bundle["generated_at"],
        "snapshot_age_seconds": age_seconds,
        "stale": age_seconds > stale_after,
        "stale_after_seconds": stale_after,
    }
    return result, metadata
