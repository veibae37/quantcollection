import json
import os
import unittest
from unittest.mock import patch

from a_share_selector import (
    AShareDataProvider,
    AShareSelectionConfig,
    AShareSelector,
    SnapshotResult,
    generate_demo_snapshot,
    run_a_share_selection,
)
from web_runner import PROGRAMS, run_registered


class AShareUniverseTests(unittest.TestCase):
    def test_auto_mode_labels_synthetic_fallback(self):
        with patch.dict(os.environ, {"A_SHARE_ALLOW_SYNTHETIC_FALLBACK": "true"}):
            with patch.object(
                AShareDataProvider, "_fetch_live", side_effect=OSError("offline")
            ):
                snapshot = AShareDataProvider().fetch("auto")
        self.assertTrue(snapshot.is_synthetic)
        self.assertIn("实时数据不可用", snapshot.fallback_reason)

    def test_a_share_trading_filters_remove_st_zero_turnover_and_price_limit(self):
        frame = generate_demo_snapshot()
        selector = AShareSelector(
            AShareSelectionConfig(top_n=10, universe_size=80, data_mode="demo")
        )
        eligible, stats = selector._build_universe(frame)
        self.assertNotIn("600000", set(eligible["代码"]))
        self.assertNotIn("601001", set(eligible["代码"]))
        self.assertNotIn("603002", set(eligible["代码"]))
        self.assertGreater(stats["eligible_count"], 80)
        self.assertGreaterEqual(stats["excluded_st_or_delisting"], 1)
        self.assertGreaterEqual(stats["excluded_liquidity_or_suspension"], 1)
        self.assertGreaterEqual(stats["excluded_near_price_limit"], 1)

    def test_selector_returns_serializable_ranked_targets(self):
        result = run_a_share_selection(
            data_mode="demo", top_n=15, universe_size=100, max_weight=0.08
        )
        self.assertTrue(result["is_synthetic"])
        self.assertEqual(len(result["selections"]), 15)
        self.assertEqual(
            len({item["ticker"] for item in result["selections"]}), 15
        )
        self.assertLessEqual(result["summary"]["max_weight_pct"], 8.0 + 1e-8)
        self.assertLessEqual(
            result["constraints"]["max_constraint_violation"], 1e-7
        )
        self.assertGreater(result["summary"]["selected_weight_coverage_pct"], 0)
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_snapshot_metadata_is_preserved(self):
        snapshot = SnapshotResult(
            data=generate_demo_snapshot(),
            source="unit-test",
            fetched_at="2026-08-06T15:00:00+08:00",
            is_synthetic=True,
        )
        result = AShareSelector(
            AShareSelectionConfig(top_n=10, universe_size=80, data_mode="demo")
        ).run(snapshot)
        self.assertEqual(result["source"], "unit-test")
        self.assertEqual(result["data_as_of"], snapshot.fetched_at)


class WebRegistrationTests(unittest.TestCase):
    def test_a_share_selector_is_default_cloud_program(self):
        self.assertEqual(PROGRAMS[0]["id"], "a_share_selector")
        result = run_registered(
            "a_share_selector",
            {"data_mode": "demo", "top_n": "10", "universe_size": "80"},
        )
        self.assertEqual(result["mode"], "a_share_selection")
        self.assertEqual(result["summary"]["selected_count"], 10)


if __name__ == "__main__":
    unittest.main()
