import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from quant_portfolio_system import (
    AlphaGenerator,
    DataProcessor,
    FactorLibrary,
    PortfolioOptimizer,
    run_demo,
)
from web_runner import run_registered


class DataProcessorTests(unittest.TestCase):
    def test_trim_standardize_and_industry_neutralize(self):
        index = pd.Index([f"A{i}" for i in range(12)])
        values = pd.DataFrame(
            {"factor": [1, 2, 3, 4, 5, 100, 10, 11, 12, 13, 14, 15]},
            index=index,
        )
        industries = pd.Series(["X"] * 6 + ["Y"] * 6, index=index)
        result = DataProcessor().preprocess_factors(values, industries)
        self.assertAlmostEqual(float(result.mean().iloc[0]), 0.0, places=10)
        self.assertAlmostEqual(float(result.std(ddof=0).iloc[0]), 1.0, places=10)
        group_means = result.groupby(industries).mean()["factor"]
        self.assertTrue(np.allclose(group_means, 0.0, atol=1e-10))


class AlphaGeneratorTests(unittest.TestCase):
    def test_zero_ic_returns_zero_alpha(self):
        index = pd.Index(["A", "B", "C"])
        scores = pd.DataFrame({"value": [-1.0, 0.0, 1.0]}, index=index)
        benchmark = pd.Series([0.2, 0.3, 0.5], index=index)
        result = AlphaGenerator().generate(
            scores,
            pd.Series(0.2, index=index),
            expected_ic={"value": 0.0},
            benchmark_weights=benchmark,
        )
        self.assertTrue(np.allclose(result.composite_alpha, 0.0))
        self.assertEqual(result.forecast_information_ratio, 0.0)

    def test_benchmark_weighted_alpha_is_zero(self):
        index = pd.Index(["A", "B", "C"])
        scores = pd.DataFrame({"value": [-1.0, 0.0, 1.0]}, index=index)
        benchmark = pd.Series([0.2, 0.3, 0.5], index=index)
        result = AlphaGenerator().generate(
            scores,
            pd.Series([0.15, 0.20, 0.25], index=index),
            expected_ic={"value": 0.05},
            benchmark_weights=benchmark,
        )
        self.assertAlmostEqual(float(benchmark @ result.composite_alpha), 0.0, places=12)


class RiskAndOptimizationTests(unittest.TestCase):
    def test_factor_covariance_is_psd(self):
        assets = pd.Index(["A", "B", "C", "D"])
        exposures = pd.DataFrame(
            {"market": [0.8, 1.0, 1.2, 0.9], "value": [-1, 0, 1, 0.5]},
            index=assets,
        )
        optimizer = PortfolioOptimizer()
        covariance = optimizer.build_factor_covariance(
            exposures,
            np.array([[0.04, 0.01], [0.01, 0.02]]),
            pd.Series(0.05, index=assets),
        )
        self.assertTrue(np.allclose(covariance, covariance.T))
        self.assertGreaterEqual(float(np.linalg.eigvalsh(covariance).min()), -1e-10)

    def test_optimizer_respects_constraints(self):
        assets = pd.Index([f"A{i}" for i in range(8)])
        benchmark = pd.Series(1 / 8, index=assets)
        alpha = pd.Series(np.linspace(-0.02, 0.02, 8), index=assets)
        covariance = pd.DataFrame(np.eye(8) * 0.04, index=assets, columns=assets)
        industries = pd.get_dummies(
            pd.Series(["X"] * 4 + ["Y"] * 4, index=assets), dtype=float
        ).iloc[:, 1:]
        style = pd.DataFrame(
            {"beta": [0.8, 0.9, 1.0, 1.1, 0.9, 1.0, 1.1, 1.2]}, index=assets
        )
        result = PortfolioOptimizer(
            risk_aversion=3.0, individual_max_weight=0.225
        ).optimize(
            alpha,
            covariance,
            benchmark,
            industry_exposure=industries,
            style_exposure=style,
            active_upper_bound=0.10,
            neutrality_tolerance=1e-8,
        )
        self.assertAlmostEqual(float(result.portfolio_weights.sum()), 1.0, places=8)
        self.assertGreaterEqual(float(result.portfolio_weights.min()), -1e-9)
        self.assertLessEqual(float(result.portfolio_weights.max()), 0.225 + 1e-9)
        self.assertTrue(
            np.allclose(
                industries.T @ result.active_weights,
                0.0,
                atol=2e-7,
            )
        )
        self.assertTrue(
            np.allclose(style.T @ result.active_weights, 0.0, atol=2e-7)
        )

    def test_projected_gradient_fallback_respects_constraints(self):
        assets = pd.Index([f"A{i}" for i in range(8)])
        benchmark = pd.Series(1 / 8, index=assets)
        alpha = pd.Series(np.linspace(-0.02, 0.02, 8), index=assets)
        covariance = pd.DataFrame(np.eye(8) * 0.04, index=assets, columns=assets)
        industries = pd.get_dummies(
            pd.Series(["X"] * 4 + ["Y"] * 4, index=assets), dtype=float
        ).iloc[:, 1:]
        with patch.dict(os.environ, {"QUANT_QP_SOLVER": "projected_gradient"}):
            result = PortfolioOptimizer(
                risk_aversion=3.0, individual_max_weight=0.225
            ).optimize(
                alpha,
                covariance,
                benchmark,
                industry_exposure=industries,
                active_upper_bound=0.10,
                neutrality_tolerance=1e-8,
            )
        self.assertEqual(result.message, "projected-gradient QP converged")
        self.assertAlmostEqual(float(result.portfolio_weights.sum()), 1.0, places=8)
        self.assertLessEqual(result.constraint_diagnostics["max_constraint_violation"], 1e-7)


class EndToEndTests(unittest.TestCase):
    def test_factor_interfaces_and_demo_outputs(self):
        prices = pd.DataFrame(
            np.linspace(10, 20, 300)[:, None] * np.array([[1.0, 1.2]]),
            columns=["A", "B"],
        )
        momentum = FactorLibrary.momentum(prices)
        self.assertEqual(momentum.shape, (2,))
        with tempfile.TemporaryDirectory() as directory:
            result = run_demo(directory, asset_count=30, seed=7)
            output = Path(result["output_dir"])
            self.assertTrue((output / "portfolio_weights.csv").exists())
            self.assertTrue((output / "processed_factors.csv").exists())
            self.assertTrue((output / "alpha_forecasts.csv").exists())
            self.assertTrue((output / "portfolio_weights_comparison.png").exists())
            self.assertTrue((output / "summary.json").exists())

    def test_serverless_mode_is_json_serializable_and_writes_nothing(self):
        result = run_registered(
            "quant_portfolio_system",
            {"asset_count": 30, "top_n": 8, "risk_aversion": 4, "seed": 7},
        )
        self.assertEqual(result["mode"], "portfolio_optimization")
        self.assertTrue(result["is_synthetic"])
        self.assertEqual(result["summary"]["asset_count"], 30)
        self.assertEqual(len(result["portfolio"]), 8)
        self.assertIn("STK", result["portfolio"][0]["asset"])
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
