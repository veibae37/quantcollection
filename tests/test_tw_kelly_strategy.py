import json
import os
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from miniqmt_kelly_executor import (
    MiniQMTConfig,
    MiniQMTConfigurationError,
    MiniQMTKellyExecutor,
)
from tw_kelly_strategy import (
    KellyConfig,
    PineProbabilityForest,
    generate_synthetic_history,
    half_kelly_fraction,
    plan_rebalance_orders,
    run_tw_kelly_portfolio,
)
from web_runner import PROGRAMS, run_registered


class PineProbabilityTests(unittest.TestCase):
    def test_probabilities_sum_to_one_and_have_valid_games(self):
        history = generate_synthetic_history("600000.SH", seed=9)
        result = PineProbabilityForest().calculate(history)
        self.assertGreater(len(result), 300)
        self.assertTrue(np.allclose(result["up_probability"] + result["down_probability"], 1.0))
        self.assertTrue(set(result["game"]).issubset({"BULL", "WAIT", "BEAR"}))

    def test_walk_forward_result_does_not_change_when_future_bars_are_appended(self):
        history = generate_synthetic_history("000001.SZ", seed=13)
        model = PineProbabilityForest()
        shorter = model.calculate(history.iloc[:350])
        longer = model.calculate(history)
        timestamp = shorter.index[-1]
        self.assertAlmostEqual(
            float(shorter.loc[timestamp, "up_probability"]),
            float(longer.loc[timestamp, "up_probability"]),
            places=12,
        )


class KellyAndRebalanceTests(unittest.TestCase):
    def test_even_odds_half_kelly(self):
        self.assertAlmostEqual(half_kelly_fraction(0.70, 0.30), 0.20)
        self.assertEqual(half_kelly_fraction(0.40, 0.60), 0.0)

    def test_orders_are_sell_first_and_respect_available_volume(self):
        portfolio = [
            {"ticker": "000001.SZ", "target_weight": 0.10, "latest_price": 10.0},
            {"ticker": "600000.SH", "target_weight": 0.00, "latest_price": 12.0},
        ]
        positions = {
            "600000.SH": {"volume": 1000, "can_use_volume": 400, "last_price": 12.0}
        }
        orders = plan_rebalance_orders(
            portfolio,
            total_asset=100_000,
            available_cash=50_000,
            current_positions=positions,
            config=KellyConfig(minimum_trade_value=0),
        )
        self.assertEqual(orders[0]["side"], "sell")
        self.assertEqual(orders[0]["quantity"], 400)
        self.assertEqual(orders[1]["side"], "buy")
        self.assertEqual(orders[1]["quantity"], 1000)

    def test_top_twenty_pipeline_is_json_serializable(self):
        result = run_tw_kelly_portfolio(top_n=20, seed=42)
        self.assertEqual(result["summary"]["selected_count"], 20)
        self.assertEqual(len(result["portfolio"]), 20)
        self.assertLessEqual(result["summary"]["target_gross_exposure_pct"], 95.0)
        self.assertTrue(all(float(item["target_weight_pct"]) <= 10.0 for item in result["portfolio"]))
        json.dumps(result, ensure_ascii=False)


class MiniQMTGuardTests(unittest.TestCase):
    def test_dry_run_never_requires_connection(self):
        executor = MiniQMTKellyExecutor(MiniQMTConfig("dummy", "dummy", 1))
        result = executor.submit_orders(
            [{"ticker": "600000.SH", "side": "buy", "quantity": 100}],
            live=False,
        )
        self.assertEqual(result[0]["status"], "DRY_RUN")

    def test_live_orders_require_explicit_environment_acknowledgement(self):
        executor = MiniQMTKellyExecutor(MiniQMTConfig("dummy", "dummy", 1))
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(MiniQMTConfigurationError):
                executor.submit_orders([], live=True)

    def test_qmt_market_fallback_uses_real_codes_without_fake_fundamentals(self):
        codes = [f"600{number:03d}.SH" for number in range(80)]
        index = pd.bdate_range("2026-01-01", periods=130)

        def ticks(requested):
            return {
                code: {
                    "lastPrice": 10.0 + position / 100,
                    "lastClose": 9.95 + position / 100,
                    "amount": 1_000_000_000 - position * 1_000_000,
                }
                for position, code in enumerate(requested)
            }

        histories = {}
        for position, code in enumerate(codes):
            close = np.linspace(8 + position / 100, 10 + position / 100, 130)
            histories[code] = pd.DataFrame(
                {
                    "close": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "amount": np.linspace(5e8, 8e8 + position * 1e6, 130),
                },
                index=index,
            )

        executor = MiniQMTKellyExecutor(MiniQMTConfig("dummy", "dummy", 1))
        with (
            patch("xtquant.xtdata.get_stock_list_in_sector", return_value=codes),
            patch("xtquant.xtdata.get_full_tick", side_effect=ticks),
            patch("xtquant.xtdata.get_market_data_ex", return_value=histories),
            patch(
                "xtquant.xtdata.get_instrument_detail_list",
                side_effect=lambda requested: {
                    code: {"InstrumentName": f"测试{code[:6]}", "FloatVolume": 1e9}
                    for code in requested
                },
            ),
        ):
            result = executor.build_qmt_market_selection(top_n=20, candidate_count=60)
        self.assertFalse(result["is_synthetic"])
        self.assertEqual(result["selection_method"], "qmt_market_only_fallback")
        self.assertEqual(len(result["selections"]), 20)
        self.assertNotIn("dynamic_pe", result["selections"][0])


class WebRegistrationTests(unittest.TestCase):
    def test_tw_kelly_program_is_registered_and_read_only(self):
        program = next(item for item in PROGRAMS if item["id"] == "tw_kelly_rebalance")
        self.assertEqual(program["status"], "ready")
        result = run_registered(
            "tw_kelly_rebalance",
            {"total_asset": 1_000_000, "seed": 42, "regime_mode": "normal"},
        )
        self.assertEqual(result["mode"], "tw_kelly_rebalance")
        self.assertEqual(len(result["portfolio"]), 20)
        self.assertNotIn("execution", result)


if __name__ == "__main__":
    unittest.main()
