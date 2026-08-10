"""HongKongFactorGenerator 的关键时点与数值回归测试。

运行方式：
    python -m unittest tests.test_hong_kong_factor_generator -v
"""

from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from hong_kong_factor_generator import (
    FactorConfig,
    HongKongFactorGenerator,
    _make_demo_data,
)


def _minimal_inputs(
    dates: pd.DatetimeIndex,
    stocks: tuple[str, ...] = ("A.HK",),
) -> dict[str, pd.DataFrame]:
    price_rows: list[dict[str, object]] = []
    flow_rows: list[dict[str, object]] = []
    for stock_idx, stock in enumerate(stocks):
        for date_idx, current_date in enumerate(dates):
            price_rows.append(
                {
                    "date": current_date,
                    "stock": stock,
                    "open": 100.0 + stock_idx + date_idx * 0.1,
                    "close": 100.5 + stock_idx + date_idx * 0.2,
                    "turnover_rate": 0.01 + 0.001 * date_idx + 0.0002 * stock_idx,
                    "market_cap": 1.0e10 * (1 + stock_idx) * (1 + date_idx * 0.01),
                    "industry": "I1" if stock_idx % 2 == 0 else "I2",
                }
            )
            flow_rows.append(
                {
                    "date": current_date,
                    "stock": stock,
                    "sb_holding_ratio": 0.03 + 0.0001 * date_idx,
                    "inflow_rate_open": 0.01 * np.sin(date_idx),
                }
            )

    first_date = dates[0]
    target_period = pd.Timestamp(first_date.year, 12, 31)
    onshore = []
    offshore = []
    financial = []
    shareholder = []
    for stock_idx, stock in enumerate(stocks):
        onshore.append(
            {
                "stock": stock,
                "available_date": first_date + pd.Timedelta(hours=10),
                "forecast_period": target_period,
                "eps": 2.0 + stock_idx,
                "net_profit": 100.0 + stock_idx,
                "target_price": 120.0 + stock_idx,
            }
        )
        offshore.append(
            {
                "stock": stock,
                "available_date": first_date + pd.Timedelta(hours=10),
                "forecast_period": target_period,
                "eps": 1.8 + stock_idx,
                "net_profit": 95.0 + stock_idx,
                "target_price": 110.0 + stock_idx,
            }
        )
        for year_idx, year in enumerate((2020, 2021, 2022, 2023)):
            report_period = pd.Timestamp(year, 12, 31)
            available = pd.Timestamp(year + 1, 3, 31, 10)
            financial.append(
                {
                    "stock": stock,
                    "report_period": report_period,
                    "available_date": available,
                    "eps": 1.0 + year_idx,
                    "net_profit": 10.0 + year_idx,
                    "revenue": 100.0 + 5 * year_idx,
                    "operating_cash_flow": 11.0 + year_idx,
                    "total_assets": 200.0 + 10 * year_idx,
                    "total_equity": 100.0 + 5 * year_idx,
                }
            )
            shareholder.append(
                {
                    "stock": stock,
                    "report_period": report_period,
                    "available_date": available + pd.Timedelta(days=2),
                    "shareholder_count": 1000.0 - 20 * year_idx + stock_idx,
                }
            )

    return {
        "price_df": pd.DataFrame(price_rows),
        "onshore_consensus_df": pd.DataFrame(onshore),
        "offshore_consensus_df": pd.DataFrame(offshore),
        "shareholder_df": pd.DataFrame(shareholder),
        "southbound_flow_df": pd.DataFrame(flow_rows),
        "financial_df": pd.DataFrame(financial),
    }


class HongKongFactorGeneratorTest(unittest.TestCase):
    def test_after_close_consensus_moves_to_next_trade_date(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=5)
        data = _minimal_inputs(dates)
        target = pd.Timestamp("2024-12-31")
        data["onshore_consensus_df"] = pd.DataFrame(
            {
                "stock": ["A.HK"],
                "available_date": [dates[0] + pd.Timedelta(hours=17)],
                "forecast_period": [target],
                "eps": [2.0],
                "net_profit": [110.0],
                "target_price": [125.0],
            }
        )
        data["offshore_consensus_df"] = pd.DataFrame(
            {
                "stock": ["A.HK"],
                "available_date": [dates[0] + pd.Timedelta(hours=10)],
                "forecast_period": [target],
                "eps": [1.0],
                "net_profit": [100.0],
                "target_price": [100.0],
            }
        )
        generator = HongKongFactorGenerator(**data)
        factor = generator.compute_dual_consensus_gaps().set_index("date")

        self.assertTrue(pd.isna(factor.loc[dates[0], "dual_gap_eps"]))
        self.assertAlmostEqual(factor.loc[dates[1], "dual_gap_eps"], 1.0)
        available = factor.loc[dates[1], "onshore_source_effective_date"]
        self.assertLessEqual(available, dates[1])

    def test_eechange_uses_calendar_month_asof_and_same_target(self) -> None:
        dates = pd.bdate_range("2024-01-15", "2024-05-01")
        data = _minimal_inputs(dates)
        target = pd.Timestamp("2024-12-31")
        vintages = pd.DataFrame(
            {
                "stock": ["A.HK"] * 3,
                "available_date": [
                    pd.Timestamp("2024-01-15 10:00"),
                    pd.Timestamp("2024-01-31 10:00"),
                    pd.Timestamp("2024-04-30 10:00"),
                ],
                "forecast_period": [target] * 3,
                "eps": [1.0, 1.0, 1.0],
                "net_profit": [80.0, 100.0, 130.0],
                "target_price": [100.0, 100.0, 100.0],
            }
        )
        data["onshore_consensus_df"] = vintages
        data["offshore_consensus_df"] = vintages.copy()
        generator = HongKongFactorGenerator(
            **data, config=FactorConfig(eechange_source="onshore")
        )
        ee = generator.compute_eechange_3m().set_index("date")["EEChange_3M"]

        self.assertAlmostEqual(ee.loc[pd.Timestamp("2024-04-30")], 130 / 80 - 1)
        self.assertAlmostEqual(ee.loc[pd.Timestamp("2024-05-01")], 130 / 100 - 1)

    def test_financial_period_first_version_and_daily_bp(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=8)
        data = _minimal_inputs(dates)
        data["price_df"]["market_cap"] = np.linspace(1000.0, 1700.0, len(dates))
        data["financial_df"] = pd.DataFrame(
            [
                {
                    "stock": "A.HK",
                    "report_period": "2021-12-31",
                    "available_date": "2022-03-31 10:00",
                    "eps": 1.0,
                    "net_profit": 10.0,
                    "revenue": 100.0,
                    "operating_cash_flow": 11.0,
                    "total_assets": 200.0,
                    "total_equity": 80.0,
                },
                {
                    "stock": "A.HK",
                    "report_period": "2022-12-31",
                    "available_date": "2023-03-31 10:00",
                    "eps": 2.0,
                    "net_profit": 20.0,
                    "revenue": 120.0,
                    "operating_cash_flow": 22.0,
                    "total_assets": 220.0,
                    "total_equity": 100.0,
                },
                {
                    "stock": "A.HK",
                    "report_period": "2023-12-31",
                    "available_date": "2024-01-05 10:00",
                    "eps": 3.0,
                    "net_profit": 30.0,
                    "revenue": 150.0,
                    "operating_cash_flow": 33.0,
                    "total_assets": 250.0,
                    "total_equity": 150.0,
                },
                # 同一报告期的后续修订不得回写首次版本。
                {
                    "stock": "A.HK",
                    "report_period": "2023-12-31",
                    "available_date": "2024-01-09 10:00",
                    "eps": 999.0,
                    "net_profit": 999.0,
                    "revenue": 999.0,
                    "operating_cash_flow": 1.0,
                    "total_assets": 999.0,
                    "total_equity": 999.0,
                },
            ]
        )
        generator = HongKongFactorGenerator(**data)
        base = generator.price_df[["date", "stock"]]
        mapped = generator._map_financial_to_daily(
            # 单独 EPS 同比仅依赖 t、t-1；完整 QQC 的 quality_available_date
            # 还必须传播资产周转变化所需的 t-2 知识时间。
            source_date_col="_base_quality_available_date",
            value_cols=("eps_growth",),
        )
        growth = pd.concat([base, mapped], axis=1).set_index("date")["eps_growth"]
        bp = generator.compute_bp().set_index("date")["BP"]

        self.assertAlmostEqual(growth.loc[pd.Timestamp("2024-01-04")], 1.0)
        self.assertAlmostEqual(growth.loc[pd.Timestamp("2024-01-05")], 0.5)
        self.assertAlmostEqual(growth.loc[pd.Timestamp("2024-01-10")], 0.5)
        self.assertAlmostEqual(
            bp.loc[pd.Timestamp("2024-01-05")],
            150.0 / data["price_df"].set_index("date").loc[pd.Timestamp("2024-01-05"), "market_cap"],
        )
        self.assertNotEqual(bp.iloc[-1], bp.iloc[-2])

    def test_turnover_lead_corr_has_no_future_return(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=7)
        data = _minimal_inputs(dates)
        closes = np.array([100.0, 102.0, 99.0, 103.0, 101.0, 106.0, 97.0])
        turnover = np.array([0.01, 0.04, 0.02, 0.05, 0.03, 0.07, 0.06])
        data["price_df"]["close"] = closes
        data["price_df"]["turnover_rate"] = turnover
        config = FactorConfig(
            turnover_lead_window=3,
            overnight_year_window=4,
            overnight_skip_window=1,
        )
        generator = HongKongFactorGenerator(**data, config=config)
        actual = generator.compute_turnover_lead_corr()["corr_ret_turn_post_1M"]
        close_return = pd.Series(closes).pct_change(fill_method=None)
        expected = pd.Series(turnover).shift(1).rolling(3, min_periods=3).corr(
            close_return
        )
        np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12, equal_nan=True)

        changed = _minimal_inputs(dates)
        changed["price_df"]["close"] = closes
        changed["price_df"]["turnover_rate"] = turnover
        changed["price_df"].loc[
            changed["price_df"]["date"] == dates[-1], "close"
        ] = 1.0e6
        changed_generator = HongKongFactorGenerator(**changed, config=config)
        changed_factor = changed_generator.compute_turnover_lead_corr()[
            "corr_ret_turn_post_1M"
        ]
        np.testing.assert_allclose(
            actual.iloc[:-1],
            changed_factor.iloc[:-1],
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        )

    def test_network_diffusion_is_normalized_and_excludes_self(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=3)
        data = _minimal_inputs(dates, stocks=("A.HK", "B.HK", "C.HK"))
        data["analyst_network_df"] = pd.DataFrame(
            {
                "target_stock": ["A.HK", "A.HK", "A.HK"],
                "related_stock": ["B.HK", "C.HK", "A.HK"],
                "available_date": [dates[0] + pd.Timedelta(hours=10)] * 3,
                "sc_weight": [0.75, 0.25, 100.0],
            }
        )
        data["analyst_surprise_df"] = pd.DataFrame(
            {
                "stock": ["A.HK", "B.HK", "C.HK"],
                "available_date": [dates[0] + pd.Timedelta(hours=10)] * 3,
                "title_positive_surprise": [True, True, False],
                "rating_upgrade": [False, False, False],
                "earnings_revision": [0.0, 0.0, -0.1],
                "upgrade_breadth": [0.0, 0.0, -0.1],
            }
        )
        config = FactorConfig(network_surprise_window=1)
        generator = HongKongFactorGenerator(**data, config=config)
        diffusion = generator.compute_network_diffusion().set_index(["date", "stock"])
        self.assertAlmostEqual(
            diffusion.loc[(dates[0], "A.HK"), "analyst_network_diffusion"], 0.75
        )

        data_scaled = dict(data)
        data_scaled["analyst_network_df"] = data["analyst_network_df"].copy()
        data_scaled["analyst_network_df"]["sc_weight"] *= 10.0
        scaled = HongKongFactorGenerator(**data_scaled, config=config)
        scaled_value = scaled.compute_network_diffusion().set_index(["date", "stock"]).loc[
            (dates[0], "A.HK"), "analyst_network_diffusion"
        ]
        self.assertAlmostEqual(scaled_value, 0.75)

    def test_postprocess_trims_and_is_orthogonal(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=5)
        generator = HongKongFactorGenerator(**_minimal_inputs(dates))

        n = 100
        market_cap = np.exp(np.linspace(20.0, 26.0, n))
        industry = np.where(np.arange(n) < 50, "I1", "I2")
        noise = np.sin(np.arange(n) * 0.7)
        factor = 3.0 * np.log(market_cap) + np.where(industry == "I1", 8.0, -5.0) + noise
        raw = pd.DataFrame(
            {
                "date": pd.Timestamp("2024-01-02"),
                "stock": [f"S{i:03d}" for i in range(n)],
                "industry": industry,
                "market_cap": market_cap,
                "x": factor,
            }
        )
        result = generator.postprocess_factors(raw, factor_columns=("x",))
        residual = result["x_neutral"]
        self.assertTrue(pd.isna(residual.loc[np.argmin(factor)]))
        self.assertTrue(pd.isna(residual.loc[np.argmax(factor)]))

        valid = residual.notna()
        checked = result.loc[valid].copy()
        industry_means = checked.groupby("industry")["x_neutral"].mean().abs()
        self.assertLess(float(industry_means.max()), 1e-10)
        centered_log_cap = np.log(checked["market_cap"])
        centered_log_cap -= centered_log_cap.mean()
        self.assertLess(abs(float(np.dot(checked["x_neutral"], centered_log_cap))), 1e-9)

    def test_full_history_and_knowledge_truncated_prefix_are_identical(self) -> None:
        """新增未来数据不得改变截止日前的原始因子或最终截面残差。"""

        data = _make_demo_data(seed=7)
        config = FactorConfig()
        full_generator = HongKongFactorGenerator(**data, config=config)
        full_raw = full_generator.compute_all_raw_factors()
        full_final = full_generator.postprocess_factors(full_raw)

        cutoff = data["price_df"]["date"].drop_duplicates().sort_values().iloc[250]
        truncated: dict[str, pd.DataFrame] = {}
        for name, frame in data.items():
            subset = frame.copy()
            if name in {"price_df", "southbound_flow_df"}:
                subset = subset.loc[
                    pd.to_datetime(subset["date"]).dt.normalize() <= cutoff
                ]
            elif "available_date" in subset.columns:
                subset = subset.loc[
                    pd.to_datetime(subset["available_date"]).dt.normalize() <= cutoff
                ]
            truncated[name] = subset

        short_generator = HongKongFactorGenerator(**truncated, config=config)
        short_raw = short_generator.compute_all_raw_factors()
        short_final = short_generator.postprocess_factors(short_raw)
        raw_columns = ["date", "stock", *HongKongFactorGenerator.FACTOR_COLUMNS]
        neutral_columns = [
            f"{factor}_neutral" for factor in HongKongFactorGenerator.FACTOR_COLUMNS
        ]

        pd.testing.assert_frame_equal(
            full_raw.loc[full_raw["date"] <= cutoff, raw_columns].reset_index(drop=True),
            short_raw[raw_columns].reset_index(drop=True),
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
        pd.testing.assert_frame_equal(
            full_final.loc[
                full_final["date"] <= cutoff,
                ["date", "stock", *neutral_columns],
            ].reset_index(drop=True),
            short_final[["date", "stock", *neutral_columns]].reset_index(drop=True),
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )

    def test_pre_panel_consensus_vintages_are_not_collapsed(self) -> None:
        dates = pd.bdate_range("2024-04-02", periods=4)
        data = _minimal_inputs(dates)
        target = pd.Timestamp("2024-12-31")
        vintages = pd.DataFrame(
            {
                "stock": ["A.HK", "A.HK"],
                "available_date": [
                    pd.Timestamp("2024-01-02 10:00"),
                    pd.Timestamp("2024-04-02 10:00"),
                ],
                "forecast_period": [target, target],
                "eps": [1.0, 1.0],
                "net_profit": [100.0, 120.0],
                "target_price": [100.0, 100.0],
            }
        )
        data["onshore_consensus_df"] = vintages
        data["offshore_consensus_df"] = vintages.copy()
        generator = HongKongFactorGenerator(
            **data, config=FactorConfig(eechange_source="onshore")
        )
        ee = generator.compute_eechange_3m().set_index("date")["EEChange_3M"]
        self.assertAlmostEqual(ee.loc[dates[0]], 0.2)

    def test_delayed_financial_dependency_and_late_shareholder_are_pit_safe(self) -> None:
        dates = pd.bdate_range("2024-01-02", "2024-01-12")
        data = _minimal_inputs(dates)
        financial_rows = []
        for year, available, scale in (
            (2021, "2024-01-10 10:00", 1.0),
            (2022, "2023-03-31 10:00", 1.2),
            (2023, "2024-01-05 10:00", 1.5),
        ):
            financial_rows.append(
                {
                    "stock": "A.HK",
                    "report_period": f"{year}-12-31",
                    "available_date": available,
                    "eps": scale,
                    "net_profit": 10.0 * scale,
                    "revenue": 100.0 * scale,
                    "operating_cash_flow": 11.0 * scale,
                    "total_assets": 200.0 * scale,
                    "total_equity": 100.0 * scale,
                }
            )
        data["financial_df"] = pd.DataFrame(financial_rows)
        data["shareholder_df"] = pd.DataFrame(
            [
                {
                    "stock": "A.HK",
                    "report_period": "2020-12-31",
                    "available_date": "2021-03-31 10:00",
                    "shareholder_count": 100.0,
                },
                {
                    "stock": "A.HK",
                    "report_period": "2021-12-31",
                    "available_date": "2022-03-31 10:00",
                    "shareholder_count": 110.0,
                },
                {
                    "stock": "A.HK",
                    "report_period": "2022-12-31",
                    "available_date": "2024-01-10 10:00",
                    "shareholder_count": 120.0,
                },
                {
                    "stock": "A.HK",
                    "report_period": "2023-12-31",
                    "available_date": "2024-01-05 10:00",
                    "shareholder_count": 150.0,
                },
            ]
        )
        config = FactorConfig(
            shareholder_history_window=2,
            shareholder_min_history=2,
        )
        generator = HongKongFactorGenerator(**data, config=config)

        period = generator._financial_period_factors().set_index("report_period")
        self.assertEqual(
            period.loc[pd.Timestamp("2023-12-31"), "quality_available_date"],
            pd.Timestamp("2024-01-10"),
        )
        mapped = generator._map_financial_to_daily(
            source_date_col="quality_available_date",
            value_cols=("report_period", "asset_turnover_change"),
        )
        mapped = pd.concat([generator.price_df[["date"]], mapped], axis=1).set_index(
            "date"
        )
        self.assertTrue(
            pd.isna(mapped.loc[pd.Timestamp("2024-01-05"), "asset_turnover_change"])
        )
        self.assertEqual(
            mapped.loc[pd.Timestamp("2024-01-10"), "report_period"],
            pd.Timestamp("2023-12-31"),
        )

        hn = generator.compute_hn_z().set_index("date")
        self.assertTrue(pd.isna(hn.loc[pd.Timestamp("2024-01-05"), "HN_z"]))
        self.assertAlmostEqual(hn.loc[pd.Timestamp("2024-01-10"), "HN_z"], 7.0)
        self.assertEqual(
            hn.loc[pd.Timestamp("2024-01-10"), "shareholder_report_period"],
            pd.Timestamp("2023-12-31"),
        )

    def test_network_handles_string_flags_same_day_updates_and_missing_price_row(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=4)
        data = _minimal_inputs(dates, stocks=("A.HK", "B.HK", "C.HK"))
        # B 在事件日缺行情，但事件应保留在完整交易所日历并影响下一日。
        data["price_df"] = data["price_df"].loc[
            ~(
                (data["price_df"]["stock"] == "B.HK")
                & (data["price_df"]["date"] == dates[0])
            )
        ]
        data["analyst_network_df"] = pd.DataFrame(
            {
                "target_stock": ["A.HK", "A.HK", "A.HK"],
                "related_stock": ["B.HK", "B.HK", "C.HK"],
                # 故意把 15:00 更新放在输入前面，仍应按真实时间取最后更新。
                "available_date": [
                    dates[0] + pd.Timedelta(hours=15),
                    dates[0] + pd.Timedelta(hours=10),
                    dates[0] + pd.Timedelta(hours=10),
                ],
                "sc_weight": [0.75, 0.10, 0.25],
            }
        )
        data["analyst_surprise_df"] = pd.DataFrame(
            {
                "stock": ["B.HK", "C.HK"],
                "available_date": [dates[0] + pd.Timedelta(hours=10)] * 2,
                "title_positive_surprise": ["True", "False"],
                "rating_upgrade": ["False", "False"],
                "earnings_revision": [0.0, -0.1],
                "upgrade_breadth": [0.0, -0.1],
            }
        )
        generator = HongKongFactorGenerator(
            **data, config=FactorConfig(network_surprise_window=2)
        )
        diffusion = generator.compute_network_diffusion().set_index(["date", "stock"])
        self.assertAlmostEqual(
            diffusion.loc[(dates[1], "A.HK"), "analyst_network_diffusion"], 0.75
        )

    def test_future_listing_does_not_backfill_zero_surprise(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=6)
        data = _minimal_inputs(dates, stocks=("A.HK", "B.HK"))
        data["price_df"] = data["price_df"].loc[
            (data["price_df"]["stock"] == "A.HK")
            | (data["price_df"]["date"] >= dates[4])
        ]
        data["analyst_network_df"] = pd.DataFrame(
            {
                "target_stock": ["A.HK"],
                "related_stock": ["B.HK"],
                "available_date": [dates[0] + pd.Timedelta(hours=10)],
                "sc_weight": [1.0],
            }
        )
        data["analyst_surprise_df"] = pd.DataFrame(
            {
                "stock": ["B.HK"],
                "available_date": [dates[4] + pd.Timedelta(hours=10)],
                "title_positive_surprise": [True],
                "rating_upgrade": [False],
                "earnings_revision": [0.0],
                "upgrade_breadth": [0.0],
            }
        )
        full = HongKongFactorGenerator(**data).compute_network_diffusion()
        early = full.loc[
            (full["stock"] == "A.HK") & (full["date"] <= dates[3]),
            "analyst_network_diffusion",
        ]
        self.assertTrue(early.isna().all())

        truncated = dict(data)
        truncated["price_df"] = data["price_df"].loc[
            data["price_df"]["date"] <= dates[3]
        ]
        truncated["southbound_flow_df"] = data["southbound_flow_df"].loc[
            data["southbound_flow_df"]["date"] <= dates[3]
        ]
        truncated["analyst_surprise_df"] = data["analyst_surprise_df"].iloc[0:0]
        short = HongKongFactorGenerator(**truncated).compute_network_diffusion()
        short_early = short.loc[
            short["stock"] == "A.HK", "analyst_network_diffusion"
        ]
        self.assertTrue(short_early.isna().all())

    def test_industry_zscore_is_stable_for_large_low_dispersion_values(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=4)
        generator = HongKongFactorGenerator(**_minimal_inputs(dates))
        work = pd.DataFrame(
            {
                "date": pd.Timestamp("2024-01-02"),
                "stock": [f"S{i}" for i in range(6)],
                "industry": "I",
                "market_cap": np.linspace(1.0e10, 2.0e10, 6),
                "_trimmed": 1.0e10 + np.arange(6, dtype=float),
            }
        )
        zscore = generator._industry_zscore_panel(work)
        self.assertAlmostEqual(float(zscore.std(ddof=0)), 1.0, places=12)


if __name__ == "__main__":
    unittest.main()
