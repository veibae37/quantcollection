import json
import math
import unittest

from option_market_scanner import (
    MarketWideBoxScanner,
    OptionScanConfig,
    OptionSnapshot,
    generate_demo_option_market,
    run_option_market_scan,
)
from web_runner import run_registered


class MarketWideOptionTests(unittest.TestCase):
    def test_demo_covers_all_supported_product_families(self):
        frame = generate_demo_option_market()
        self.assertEqual(len(frame), 648)
        self.assertEqual(frame["underlying"].nunique(), 12)
        self.assertEqual(set(frame["exchange"]), {"SSE", "SZSE", "CFFEX"})
        self.assertEqual(set(frame["option_type"]), {"C", "P"})

    def test_scanner_pairs_within_same_underlying_and_expiry(self):
        frame = generate_demo_option_market()
        snapshot = OptionSnapshot(
            data=frame,
            source="unit-test",
            fetched_at="2026-08-06T16:00:00+08:00",
            is_synthetic=True,
        )
        result = MarketWideBoxScanner(OptionScanConfig(top_n=20)).run(snapshot)
        self.assertEqual(result["summary"]["expiry_group_count"], 36)
        self.assertEqual(result["summary"]["paired_strike_count"], 324)
        self.assertEqual(result["summary"]["box_combination_count"], 1296)
        for candidate in result["opportunities"]:
            self.assertLess(candidate["low_strike"], candidate["high_strike"])
            self.assertEqual(len(candidate["legs"]), 4)

    def test_best_profit_formula_recomputes(self):
        result = run_option_market_scan(data_mode="demo", top_n=10)
        best = result["opportunities"][0]
        legs = best["legs"]
        debit = legs[0]["price"] - legs[1]["price"] + legs[2]["price"] - legs[3]["price"]
        fair = (best["high_strike"] - best["low_strike"]) * math.exp(
            -result["input"]["interest_rate"] * best["remaining_days"] / 365
        )
        self.assertAlmostEqual(best["net_debit"], debit, places=6)
        self.assertAlmostEqual(best["fair_value"], fair, places=6)
        self.assertAlmostEqual(best["profit_per_unit"], fair - debit, places=6)
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_web_boxoption_uses_market_scanner_not_four_contract_fixture(self):
        result = run_registered(
            "boxoption2",
            {"data_mode": "demo", "top_n": "10", "min_volume": "1"},
        )
        self.assertEqual(result["mode"], "option_market_scan")
        self.assertGreater(result["summary"]["contract_count"], 4)
        self.assertEqual(len(result["opportunities"]), 10)


if __name__ == "__main__":
    unittest.main()
