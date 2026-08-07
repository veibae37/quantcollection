import datetime as dt
import json
import math
import os
import unittest
from unittest.mock import patch

from option_market_scanner import (
    MarketWideBoxScanner,
    OptionScanConfig,
    OptionSnapshot,
    calculate_true_box_profit_cny,
    generate_demo_option_market,
    run_option_market_scan,
)
from scanner_worker import (
    DEFAULT_WEBHOOK_URL,
    QMTETFOptionProvider,
    WorkerConfig,
    WorkerConfigurationError,
    build_push_payload,
    scan_once,
)
from api.options import _valid_payload
from web_runner import run_registered


class MarketWideOptionTests(unittest.TestCase):
    def test_worker_uses_project_webhook_url_when_environment_is_missing_it(self):
        with patch.dict(
            os.environ,
            {"OPTIONS_WEBHOOK_SECRET": "shared-secret"},
            clear=True,
        ):
            config = WorkerConfig.from_env(require_webhook=True)
        self.assertEqual(config.webhook_url, DEFAULT_WEBHOOK_URL)

    def test_worker_accepts_existing_nonempty_short_shared_secret(self):
        with patch.dict(
            os.environ,
            {
                "OPTIONS_WEBHOOK_URL": "https://example.vercel.app/api/options",
                "OPTIONS_WEBHOOK_SECRET": "short-but-shared",
            },
            clear=True,
        ):
            config = WorkerConfig.from_env(require_webhook=True)
        self.assertEqual(config.webhook_secret, "short-but-shared")

    def test_worker_still_rejects_missing_shared_secret(self):
        with patch.dict(
            os.environ,
            {"OPTIONS_WEBHOOK_URL": "https://example.vercel.app/api/options"},
            clear=True,
        ):
            with self.assertRaises(WorkerConfigurationError):
                WorkerConfig.from_env(require_webhook=True)

    def test_demo_covers_all_supported_product_families(self):
        frame = generate_demo_option_market()
        self.assertEqual(len(frame), 486)
        self.assertEqual(frame["underlying"].nunique(), 9)
        self.assertEqual(set(frame["exchange"]), {"SSE", "SZSE"})
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
        self.assertEqual(result["summary"]["expiry_group_count"], 27)
        self.assertEqual(result["summary"]["paired_strike_count"], 243)
        self.assertEqual(result["summary"]["box_combination_count"], 972)
        for candidate in result["opportunities"]:
            self.assertLess(candidate["low_strike"], candidate["high_strike"])
            self.assertEqual(len(candidate["legs"]), 4)
            self.assertGreater(candidate["true_net_profit_cny"], 0)

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
        gross = (fair - debit) * 10_000
        self.assertAlmostEqual(best["absolute_gross_profit_cny"], gross, places=2)
        self.assertAlmostEqual(best["fees_cny"], 6.8, places=6)
        self.assertAlmostEqual(best["slippage_cny"], 4.0, places=6)
        self.assertAlmostEqual(best["true_net_profit_cny"], gross - 6.8 - 4.0, places=2)
        json.dumps(result, ensure_ascii=False, allow_nan=False)

    def test_exact_five_step_dimension_conversion(self):
        result = calculate_true_box_profit_cny(
            call_low_ask=0.21,
            put_low_bid=0.01,
            put_high_ask=0.01,
            call_high_bid=0.19,
            low_strike=3.0,
            high_strike=3.1,
            interest_rate=0.03,
            remaining_days=30,
        )
        unit_debit = 0.21 - 0.01 + 0.01 - 0.19
        unit_fair = 0.1 * math.exp(-0.03 * 30 / 365.0)
        self.assertAlmostEqual(result["unit_debit"], unit_debit)
        self.assertAlmostEqual(result["unit_fair_value"], unit_fair)
        self.assertAlmostEqual(
            result["absolute_gross_profit_cny"],
            (unit_fair - unit_debit) * 10_000,
        )
        self.assertAlmostEqual(
            result["true_net_profit_cny"],
            (unit_fair - unit_debit) * 10_000 - 6.8 - 4.0,
        )

    def test_webhook_payload_contains_positive_opportunities_only(self):
        result = run_option_market_scan(data_mode="demo", top_n=50)
        result["opportunities"].append(
            {"true_net_profit_cny": -1.0, "legs": []}
        )
        payload = build_push_payload(result)
        self.assertTrue(payload["opportunities"])
        self.assertTrue(
            all(item["true_net_profit_cny"] > 0 for item in payload["opportunities"])
        )
        self.assertTrue(_valid_payload(payload))
        payload["opportunities"][0]["true_net_profit_cny"] = 0
        self.assertFalse(_valid_payload(payload))

    def test_qmt_worker_batches_bbo_and_builds_valid_payload(self):
        expiry = (dt.date.today() + dt.timedelta(days=90)).strftime("%Y%m%d")
        details = {
            "CL.SHO": ("低购", "CALL", 3.0),
            "PL.SHO": ("低沽", "PUT", 3.0),
            "CH.SHO": ("高购", "CALL", 3.1),
            "PH.SHO": ("高沽", "PUT", 3.1),
        }
        sector_codes = [*details, "BROKEN.SHO"]
        ticks = {
            "CL.SHO": {"bidPrice": [0.049], "askPrice": [0.050], "bidVol": [20], "askVol": [20]},
            "PL.SHO": {"bidPrice": [0.010], "askPrice": [0.011], "bidVol": [20], "askVol": [20]},
            "CH.SHO": {"bidPrice": [0.040], "askPrice": [0.041], "bidVol": [20], "askVol": [20]},
            "PH.SHO": {"bidPrice": [0.009], "askPrice": [0.010], "bidVol": [20], "askVol": [20]},
        }

        class FakeXtData:
            @staticmethod
            def get_stock_list_in_sector(sector):
                return sector_codes if sector == "上证期权" else []

            @staticmethod
            def get_option_detail_data(code):
                raise TypeError("unsupported operand type(s) for +")

            @staticmethod
            def _get_instrument_detail(code):
                if code == "BROKEN.SHO":
                    return {}
                name, kind, strike = details[code]
                return {
                    "ExchangeID": "SHO",
                    "InstrumentName": name,
                    "ExpireDate": expiry,
                    "VolumeMultiple": 10_000,
                    "ProductID": "50ETF(510050)",
                    "ExtendInfo": {
                        "OptionType": 0 if kind == "CALL" else 1,
                        "OptExercisePrice": strike,
                        "OptUndlCode": "510050",
                        "OptUndlUniCode": None,
                        "OptUndlMarket": "SH",
                    },
                }

            @staticmethod
            def get_full_tick(codes):
                return {code: ticks[code] for code in codes}

        provider = QMTETFOptionProvider()
        provider._xtdata = lambda: FakeXtData
        config = WorkerConfig(
            webhook_url="https://example.invalid/api/options",
            webhook_secret="x" * 24,
            top_n=10,
        )
        payload = scan_once(config, provider, None)
        self.assertEqual(payload["opportunity_count"], 1)
        self.assertTrue(_valid_payload(payload))

    def test_web_boxoption_uses_market_scanner_not_four_contract_fixture(self):
        result = run_registered(
            "boxoption2",
            {"data_mode": "demo", "top_n": "10", "min_volume": "1"},
        )
        self.assertEqual(result["mode"], "option_market_scan")
        self.assertGreater(result["summary"]["contract_count"], 4)
        self.assertGreater(len(result["opportunities"]), 0)
        self.assertLessEqual(len(result["opportunities"]), 10)
        self.assertTrue(
            all(item["true_net_profit_cny"] > 0 for item in result["opportunities"])
        )


if __name__ == "__main__":
    unittest.main()
