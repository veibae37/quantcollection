from __future__ import annotations

import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from live_snapshot_store import (
    LiveSnapshotValidationError,
    SCHEMA_VERSION,
    get_program_snapshot,
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


if __name__ == "__main__":
    unittest.main()
