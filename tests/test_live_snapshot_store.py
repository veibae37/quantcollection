from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live_snapshot_store import (
    LiveSnapshotUnavailable,
    LiveSnapshotValidationError,
    SCHEMA_VERSION,
    get_program_snapshot,
    load_live_bundle,
    save_live_bundle,
    validate_bundle,
)
from web_runner import LIVE_QMT_PROGRAM_IDS, public_programs, run_registered


def _bundle() -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "source": "MiniQMT local publisher",
        "is_synthetic": False,
        "programs": {
            "a_share_selector": {
                "program": "QMT selector",
                "mode": "a_share_selection",
                "is_synthetic": False,
                "source": "MiniQMT realtime",
                "data_as_of": now,
                "summary": {"selected_count": 1},
                "selections": [{"ticker": "600000.SH"}],
            }
        },
        "errors": {"hk_factor": "QMT fields unavailable"},
    }


class LiveSnapshotStoreTests(unittest.TestCase):
    def test_rejects_synthetic_program(self) -> None:
        payload = _bundle()
        payload["programs"]["a_share_selector"]["is_synthetic"] = True
        with self.assertRaises(LiveSnapshotValidationError):
            validate_bundle(payload)

    def test_accepts_audited_eastmoney_fallback(self) -> None:
        payload = _bundle()
        selection = payload["programs"]["a_share_selector"]
        selection["source"] = "东方财富实时行情（AkShare 兼容字段）"
        selection["source_details"] = {
            "provider": "东方财富",
            "access_layer": "AkShare 兼容字段（直接 HTTPS）",
            "endpoint": "https://push2.eastmoney.com/api/qt/clist/get",
            "frequency": "交易时段快照",
            "fallback_used": True,
            "quality_checks": ["禁止合成数据"],
        }
        self.assertEqual(
            validate_bundle(payload)["programs"]["a_share_selector"]["source_details"]["provider"],
            "东方财富",
        )

    def test_rejects_eastmoney_fallback_without_provenance(self) -> None:
        payload = _bundle()
        payload["programs"]["a_share_selector"]["source"] = "东方财富实时行情"
        with self.assertRaisesRegex(LiveSnapshotValidationError, "source_details"):
            validate_bundle(payload)

    def test_accepts_wind_primary_snapshot_with_public_history(self) -> None:
        payload = _bundle()
        payload["source"] = "Wind/MiniQMT local publisher"
        selection = payload["programs"]["a_share_selector"]
        selection["source"] = "Wind金融终端实时行情 + 新浪/腾讯前复权日线"
        selection["source_details"] = {
            "provider": "Wind金融终端",
            "access_layer": "WindPy 本地只读接口",
            "endpoint": "WindPy.wsq",
            "frequency": "实时截面 + 日频历史",
            "fallback_used": False,
            "quality_checks": ["禁止合成数据"],
        }
        self.assertEqual(
            validate_bundle(payload)["programs"]["a_share_selector"]["source_details"]["provider"],
            "Wind金融终端",
        )

    def test_accepts_live_boxoption2_snapshot(self) -> None:
        payload = _bundle()
        payload["programs"]["boxoption2"] = {
            "program": "boxoption2.py",
            "is_synthetic": False,
            "source": "MiniQMT realtime",
            "data_as_of": payload["generated_at"],
        }

        validated = validate_bundle(payload)

        self.assertIn("boxoption2", validated["programs"])

    def test_accepts_bundle_containing_only_live_boxoption2(self) -> None:
        payload = _bundle()
        payload["programs"] = {
            "boxoption2": {
                "program": "boxoption2.py",
                "is_synthetic": False,
                "source": "MiniQMT realtime",
                "data_as_of": payload["generated_at"],
            }
        }
        self.assertEqual(set(validate_bundle(payload)["programs"]), {"boxoption2"})

    def test_local_roundtrip_and_runner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            with patch.dict("os.environ", {"QMT_LIVE_SNAPSHOT_FILE": str(path)}, clear=False):
                save_live_bundle(_bundle())
                result, metadata = get_program_snapshot("a_share_selector")
                self.assertFalse(result["is_synthetic"])
                self.assertFalse(metadata["stale"])
                via_runner = run_registered("a_share_selector", {"data_mode": "demo"})
                self.assertFalse(via_runner["is_synthetic"])
                self.assertEqual(via_runner["selections"][0]["ticker"], "600000.SH")

    def test_market_programs_expose_no_demo_parameters(self) -> None:
        by_id = {item["id"]: item for item in public_programs()}
        for program_id in LIVE_QMT_PROGRAM_IDS:
            self.assertEqual(by_id[program_id]["parameters"], [])
            self.assertIn("不使用模拟", by_id[program_id]["notice"])

    def test_invalid_stored_snapshot_is_unavailable(self) -> None:
        payload = _bundle()
        payload["programs"]["a_share_selector"]["is_synthetic"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "latest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch.dict("os.environ", {"QMT_LIVE_SNAPSHOT_FILE": str(path), "VERCEL": ""}):
                with self.assertRaisesRegex(LiveSnapshotUnavailable, "未通过校验"):
                    load_live_bundle()


if __name__ == "__main__":
    unittest.main()
