"""港股主动量化因子加工系统。

本模块实现一个面向日频回测的 :class:`HongKongFactorGenerator`，核心原则是：

1. 财报和股东数据先压缩到 ``stock + report_period`` 的首次可得记录；
2. 所有同比、差分、滚动统计都先在报告期/事件期完成，再映射到日频；
3. 所有事件均通过 ``effective_trade_date <= signal_date`` 的 backward as-of
   规则映射，绝不使用 forward/nearest join 或 backward-fill；
4. 价格型分母（例如 BP）始终使用信号日当日的 PIT 市值；
5. 最终因子按日进行 2%/98% 严格 trimming、行业内 z-score、行业内去均值
   log 市值中性化，输出 OLS 残差。

数据时点约定
----------
``available_date`` 可以是日期或香港时间的时间戳。若包含时间且时间戳不早于
16:00，则信号从下一港股交易日生效；周末和非交易日自动滚到下一个价格面板中的
交易日。若数据供应商只提供日期而不能区分盘中/盘后，建议在上游保守地把公告日
调整为下一交易日。

本模块输出的是“当日收盘后可知”的因子：当日 close、市值、完整开盘阶段流量等
均可参与计算。因此，默认交易解释是信号日收盘后生成、下一交易日执行。

主要输入字段
------------
price_df
    ``date, stock, open, close, turnover_rate, market_cap, industry``。
    open/close 应使用一致复权口径；market_cap 必须与归母权益保持相同股本口径。
onshore_consensus_df / offshore_consensus_df
    ``stock, available_date, eps, net_profit, target_price``，建议同时提供
    ``forecast_period``。如提供，则境内外比较和 EEChange_3M 均严格匹配同一预测期。
financial_df
    ``stock, report_period, available_date, eps, net_profit, revenue,
    operating_cash_flow, total_assets, total_equity``。利润、收入、现金流应由上游处理成
    可比 TTM/年度口径；本模块不会把累计中报与年度值混合猜测。
shareholder_df
    ``stock, report_period, available_date, shareholder_count``。
southbound_flow_df
    ``date, stock, sb_holding_ratio, inflow_rate_open``。date 应为该观测首个可用于
    收盘后信号的交易日。
analyst_network_df
    PIT pair-level 更新日志：``target_stock, related_stock, available_date,
    sc_weight``；边失效时必须显式写入 ``sc_weight=0`` tombstone。
analyst_surprise_df
    ``stock, available_date, title_positive_surprise, rating_upgrade,
    earnings_revision, upgrade_breadth``。代码把进入覆盖池后的“无事件”解释为 0，
    因而输入应是覆盖研究股票池的完整事件账本。价格/事件历史还应包含至少一个最长
    窗口的 warm-up，避免样本首日丢失仍在有效期内的历史惊喜。

代码仅负责因子研究与数据加工，不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Iterable, Literal, Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FactorConfig:
    """因子窗口、截面处理和时点控制参数。"""

    southbound_window: int = 20
    overnight_year_window: int = 252
    overnight_skip_window: int = 20
    turnover_lead_window: int = 20
    network_surprise_window: int = 20
    shareholder_history_window: int = 8
    shareholder_min_history: int = 4
    quality_min_components: int = 4

    trim_lower: float = 0.02
    trim_upper: float = 0.98
    trimming_mode: Literal["trim", "winsorize"] = "trim"
    min_industry_obs: int = 3
    min_neutralization_obs: int = 10

    # 一致预期最长陈旧期；None 表示严格取“历史最新值”而不额外设期限。
    consensus_max_age_days: int | None = None
    eechange_source: Literal["blend", "onshore", "offshore"] = "blend"
    normalize_network_weights: bool = True

    market_close_time: time = time(16, 0)
    denominator_epsilon: float = 1e-12
    numerical_epsilon: float = 1e-12

    def __post_init__(self) -> None:
        if not 0 <= self.trim_lower < self.trim_upper <= 1:
            raise ValueError("trim_lower/trim_upper 必须满足 0 <= lower < upper <= 1。")
        positive_windows = {
            "southbound_window": self.southbound_window,
            "overnight_year_window": self.overnight_year_window,
            "overnight_skip_window": self.overnight_skip_window,
            "turnover_lead_window": self.turnover_lead_window,
            "network_surprise_window": self.network_surprise_window,
            "shareholder_history_window": self.shareholder_history_window,
        }
        bad = [name for name, value in positive_windows.items() if value <= 0]
        if bad:
            raise ValueError(f"以下窗口必须为正整数：{bad}")
        if self.overnight_skip_window >= self.overnight_year_window:
            raise ValueError("overnight_skip_window 必须小于 overnight_year_window。")
        if not 1 <= self.quality_min_components <= 4:
            raise ValueError("quality_min_components 必须位于 1 到 4。")
        if self.trimming_mode not in {"trim", "winsorize"}:
            raise ValueError("trimming_mode 只能是 'trim' 或 'winsorize'。")
        if self.eechange_source not in {"blend", "onshore", "offshore"}:
            raise ValueError(
                "eechange_source 只能是 'blend'、'onshore' 或 'offshore'。"
            )
        if self.min_industry_obs <= 0 or self.min_neutralization_obs <= 0:
            raise ValueError("行业标准化和中性化最小样本数必须为正。")
        if self.shareholder_min_history <= 0:
            raise ValueError("shareholder_min_history 必须为正。")
        if self.shareholder_min_history > self.shareholder_history_window:
            raise ValueError(
                "shareholder_min_history 不能大于 shareholder_history_window。"
            )
        for name, value in (
            ("denominator_epsilon", self.denominator_epsilon),
            ("numerical_epsilon", self.numerical_epsilon),
        ):
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name} 必须是有限正数。")
        if self.consensus_max_age_days is not None and self.consensus_max_age_days < 0:
            raise ValueError("consensus_max_age_days 不能为负。")


class HongKongFactorGenerator:
    """模块化、PIT 安全的港股量化因子生成器。"""

    FACTOR_COLUMNS: tuple[str, ...] = (
        "dual_gap_eps",
        "dual_gap_net_profit",
        "dual_gap_target_price",
        "SB_Holding_Change",
        "inflow_rate_open",
        "analyst_network_diffusion",
        "QQC",
        "HN_z",
        "BP",
        "mmt_overnight_A",
        "corr_ret_turn_post_1M",
        "EEChange_3M",
    )

    CONSENSUS_VALUE_COLUMNS: tuple[str, ...] = (
        "eps",
        "net_profit",
        "target_price",
    )

    def __init__(
        self,
        price_df: pd.DataFrame,
        onshore_consensus_df: pd.DataFrame,
        offshore_consensus_df: pd.DataFrame,
        shareholder_df: pd.DataFrame,
        southbound_flow_df: pd.DataFrame,
        financial_df: pd.DataFrame,
        analyst_network_df: pd.DataFrame | None = None,
        analyst_surprise_df: pd.DataFrame | None = None,
        config: FactorConfig | None = None,
    ) -> None:
        self.config = config or FactorConfig()
        self._cache: dict[str, pd.DataFrame] = {}

        self.price_df = self._prepare_price(price_df)
        self.trading_dates = pd.DatetimeIndex(
            self.price_df["date"].drop_duplicates().sort_values()
        )

        self.onshore_consensus_df = self._prepare_consensus(
            onshore_consensus_df, "onshore_consensus_df"
        )
        self.offshore_consensus_df = self._prepare_consensus(
            offshore_consensus_df, "offshore_consensus_df"
        )
        self._validate_consensus_contract()

        self.financial_df = self._prepare_event_frame(
            financial_df,
            "financial_df",
            required=(
                "stock",
                "report_period",
                "available_date",
                "eps",
                "net_profit",
                "revenue",
                "operating_cash_flow",
                "total_assets",
                "total_equity",
            ),
            report_period=True,
            numeric=(
                "eps",
                "net_profit",
                "revenue",
                "operating_cash_flow",
                "total_assets",
                "total_equity",
            ),
        )
        self.shareholder_df = self._prepare_event_frame(
            shareholder_df,
            "shareholder_df",
            required=("stock", "report_period", "available_date", "shareholder_count"),
            report_period=True,
            numeric=("shareholder_count",),
        )
        self.southbound_flow_df = self._prepare_southbound(southbound_flow_df)

        if analyst_network_df is None:
            self.analyst_network_df = None
        else:
            self.analyst_network_df = self._prepare_event_frame(
                analyst_network_df,
                "analyst_network_df",
                required=(
                    "target_stock",
                    "related_stock",
                    "available_date",
                    "sc_weight",
                ),
                numeric=("sc_weight",),
            )
            if (self.analyst_network_df["sc_weight"] < 0).any():
                raise ValueError("analyst_network_df.sc_weight 必须非负。")
            self.analyst_network_df = self.analyst_network_df.loc[
                self.analyst_network_df["target_stock"]
                != self.analyst_network_df["related_stock"]
            ].copy()
            self.analyst_network_df = (
                self.analyst_network_df.sort_values(
                    [
                        "target_stock",
                        "related_stock",
                        "_effective_date",
                        "available_date",
                    ],
                    kind="mergesort",
                )
                .drop_duplicates(
                    ["target_stock", "related_stock", "_effective_date"],
                    keep="last",
                )
                .reset_index(drop=True)
            )

        if analyst_surprise_df is None:
            self.analyst_surprise_df = None
        else:
            self.analyst_surprise_df = self._prepare_event_frame(
                analyst_surprise_df,
                "analyst_surprise_df",
                required=(
                    "stock",
                    "available_date",
                    "title_positive_surprise",
                    "rating_upgrade",
                    "earnings_revision",
                    "upgrade_breadth",
                ),
                numeric=("earnings_revision", "upgrade_breadth"),
            )
            for flag_column in ("title_positive_surprise", "rating_upgrade"):
                self.analyst_surprise_df[flag_column] = self._coerce_boolean(
                    self.analyst_surprise_df[flag_column],
                    f"analyst_surprise_df.{flag_column}",
                )

    # ------------------------------------------------------------------
    # 输入验证与时间边界
    # ------------------------------------------------------------------
    @staticmethod
    def _require_columns(df: pd.DataFrame, columns: Iterable[str], name: str) -> None:
        missing = sorted(set(columns) - set(df.columns))
        if missing:
            raise ValueError(f"{name} 缺少必需字段：{missing}")

    @staticmethod
    def _ensure_unique(df: pd.DataFrame, keys: Sequence[str], name: str) -> None:
        duplicated = df.duplicated(list(keys), keep=False)
        if duplicated.any():
            sample = df.loc[duplicated, list(keys)].head(5).to_dict("records")
            raise ValueError(f"{name} 在 {list(keys)} 上不唯一，示例：{sample}")

    @staticmethod
    def _require_nonmissing_keys(
        df: pd.DataFrame, columns: Iterable[str], name: str
    ) -> None:
        for column in columns:
            missing = df[column].isna()
            if pd.api.types.is_object_dtype(df[column]) or isinstance(
                df[column].dtype, pd.StringDtype
            ):
                blank = df[column].astype("string").str.strip().eq("").fillna(True)
                missing |= blank
            if missing.any():
                raise ValueError(f"{name}.{column} 主键字段不能为缺失或空字符串。")

    @staticmethod
    def _coerce_numeric(df: pd.DataFrame, columns: Iterable[str], name: str) -> None:
        for column in columns:
            converted = pd.to_numeric(df[column], errors="coerce")
            newly_missing = converted.isna() & df[column].notna()
            if newly_missing.any():
                raise ValueError(f"{name}.{column} 含无法转换为数值的记录。")
            non_finite = converted.notna() & ~np.isfinite(converted)
            if non_finite.any():
                raise ValueError(f"{name}.{column} 含正负无穷等非有限值。")
            df[column] = converted.astype(float)

    @staticmethod
    def _coerce_boolean(series: pd.Series, name: str) -> pd.Series:
        """严格解析 bool/0/1/常见字符串，防止 ``bool('False') is True``。"""

        mapping: dict[object, bool] = {
            True: True,
            False: False,
            1: True,
            0: False,
            "1": True,
            "0": False,
            "true": True,
            "false": False,
            "yes": True,
            "no": False,
            "y": True,
            "n": False,
        }

        def parse(value: object) -> object:
            if pd.isna(value):
                return pd.NA
            normalized: object = value.strip().lower() if isinstance(value, str) else value
            if normalized not in mapping:
                raise ValueError(f"{name} 含无法识别的布尔值：{value!r}")
            return mapping[normalized]

        return series.map(parse).astype("boolean")

    @staticmethod
    def _to_naive_hk_datetime(series: pd.Series, name: str) -> pd.Series:
        """转为无时区香港本地时间；naive 输入按香港时间解释。"""

        try:
            parsed = pd.to_datetime(series, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} 含无法解析的日期时间。") from exc

        if isinstance(parsed.dtype, pd.DatetimeTZDtype):
            parsed = parsed.dt.tz_convert("Asia/Hong_Kong").dt.tz_localize(None)
        return parsed

    def _effective_trade_date(self, available_at: pd.Series) -> pd.Series:
        """把知识时间映射到首个真正可用于收盘后信号的港股交易日。"""

        ts = self._to_naive_hk_datetime(available_at, "available_date")
        normalized = ts.dt.normalize()
        close_delta = pd.Timedelta(
            hours=self.config.market_close_time.hour,
            minutes=self.config.market_close_time.minute,
            seconds=self.config.market_close_time.second,
        )
        after_close = (ts - normalized) >= close_delta
        candidate = normalized + pd.to_timedelta(after_close.astype(int), unit="D")

        calendar = self.trading_dates.to_numpy(dtype="datetime64[ns]")
        candidate_values = candidate.to_numpy(dtype="datetime64[ns]")

        # 样本区间外不能夹到首/末交易日，否则多个历史 vintage 会被压成同一天，
        # 既破坏 3M as-of，也会把陈旧数据误判为刚发布。区间外至少保留真实日期顺序，
        # 周末用工作日保守顺延；精确港股假期应由上游提供足够长的交易日历覆盖。
        fallback = candidate.map(
            lambda value: value
            if pd.isna(value) or value.dayofweek < 5
            else value + pd.offsets.BDay(0)
        )
        result = fallback.to_numpy(dtype="datetime64[ns]")
        if len(calendar) == 0:
            return pd.Series(result, index=available_at.index, dtype="datetime64[ns]")

        within_calendar = (candidate_values >= calendar[0]) & (
            candidate_values <= calendar[-1]
        )
        positions = np.searchsorted(calendar, candidate_values, side="left")
        mapped = within_calendar & (positions < len(calendar))
        result[mapped] = calendar[positions[mapped]]
        return pd.Series(result, index=available_at.index, dtype="datetime64[ns]")

    def _prepare_price(self, df: pd.DataFrame) -> pd.DataFrame:
        name = "price_df"
        required = (
            "date",
            "stock",
            "open",
            "close",
            "turnover_rate",
            "market_cap",
            "industry",
        )
        self._require_columns(df, required, name)
        out = df.copy(deep=True)
        out["date"] = self._to_naive_hk_datetime(out["date"], f"{name}.date").dt.normalize()
        self._require_nonmissing_keys(out, ("date", "stock"), name)
        out["stock"] = out["stock"].astype(str)
        self._coerce_numeric(
            out, ("open", "close", "turnover_rate", "market_cap"), name
        )
        self._ensure_unique(out, ("date", "stock"), name)
        if (out[["open", "close"]] <= 0).any().any():
            raise ValueError("price_df.open/close 必须为正。")
        if (out["market_cap"] <= 0).any():
            raise ValueError("price_df.market_cap 必须为正。")
        out["industry"] = out["industry"].where(out["industry"].notna())
        return out.sort_values(["stock", "date"], kind="mergesort").reset_index(drop=True)

    def _prepare_event_frame(
        self,
        df: pd.DataFrame,
        name: str,
        *,
        required: Sequence[str],
        report_period: bool = False,
        numeric: Sequence[str] = (),
    ) -> pd.DataFrame:
        self._require_columns(df, required, name)
        out = df.copy(deep=True)
        out["available_date"] = self._to_naive_hk_datetime(
            out["available_date"], f"{name}.available_date"
        )
        stock_keys = [
            column
            for column in ("stock", "target_stock", "related_stock")
            if column in out.columns
        ]
        self._require_nonmissing_keys(out, ("available_date", *stock_keys), name)
        out["_effective_date"] = self._effective_trade_date(out["available_date"])
        if report_period:
            out["report_period"] = self._to_naive_hk_datetime(
                out["report_period"], f"{name}.report_period"
            ).dt.normalize()
            self._require_nonmissing_keys(out, ("report_period",), name)
            invalid_order = out["available_date"].dt.normalize() < out["report_period"]
            if invalid_order.any():
                sample = out.loc[
                    invalid_order, ["stock", "report_period", "available_date"]
                ].head(5)
                raise ValueError(
                    f"{name} 存在 available_date 早于 report_period 的记录："
                    f"{sample.to_dict('records')}"
                )
        for stock_col in ("stock", "target_stock", "related_stock"):
            if stock_col in out.columns:
                out[stock_col] = out[stock_col].astype(str)
        self._coerce_numeric(out, numeric, name)
        return out

    def _prepare_consensus(self, df: pd.DataFrame, name: str) -> pd.DataFrame:
        self._require_columns(
            df,
            ("stock", "available_date", *self.CONSENSUS_VALUE_COLUMNS),
            name,
        )
        out = self._prepare_event_frame(
            df,
            name,
            required=("stock", "available_date", *self.CONSENSUS_VALUE_COLUMNS),
            numeric=self.CONSENSUS_VALUE_COLUMNS,
        )
        if "forecast_period" in out.columns:
            out["forecast_period"] = self._to_naive_hk_datetime(
                out["forecast_period"], f"{name}.forecast_period"
            ).dt.normalize()
            self._require_nonmissing_keys(out, ("forecast_period",), name)
        if "analyst_count" in out.columns:
            self._coerce_numeric(out, ("analyst_count",), name)

        keys = ["stock"]
        if "forecast_period" in out.columns:
            keys.append("forecast_period")
        keys.append("_effective_date")

        # 同一可交易生效日若有多次盘中更新，收盘信号可使用该日最后一次已知更新。
        # 先按真实 available_date 排序，随后确定性地保留最后一条。
        out = out.sort_values([*keys, "available_date"], kind="mergesort")
        out = out.drop_duplicates(keys, keep="last").reset_index(drop=True)
        return out

    def _validate_consensus_contract(self) -> None:
        on_has_period = "forecast_period" in self.onshore_consensus_df.columns
        off_has_period = "forecast_period" in self.offshore_consensus_df.columns
        if on_has_period != off_has_period:
            raise ValueError(
                "境内外一致预期必须同时提供 forecast_period，或同时不提供。"
            )

    def _prepare_southbound(self, df: pd.DataFrame) -> pd.DataFrame:
        name = "southbound_flow_df"
        required = ("date", "stock", "sb_holding_ratio", "inflow_rate_open")
        self._require_columns(df, required, name)
        out = df.copy(deep=True)
        out["date"] = self._to_naive_hk_datetime(out["date"], f"{name}.date").dt.normalize()
        self._require_nonmissing_keys(out, ("date", "stock"), name)
        out["stock"] = out["stock"].astype(str)
        self._coerce_numeric(out, ("sb_holding_ratio", "inflow_rate_open"), name)
        self._ensure_unique(out, ("date", "stock"), name)
        return out.sort_values(["stock", "date"], kind="mergesort").reset_index(drop=True)

    # ------------------------------------------------------------------
    # 通用 backward as-of 映射
    # ------------------------------------------------------------------
    @staticmethod
    def _group_key(value: object) -> tuple[object, ...]:
        return value if isinstance(value, tuple) else (value,)

    def _asof_lookup(
        self,
        left: pd.DataFrame,
        right: pd.DataFrame,
        *,
        query_date_col: str,
        source_date_col: str,
        keys: Sequence[str],
        value_cols: Sequence[str],
        prefix: str,
    ) -> pd.DataFrame:
        """按 keys 分组执行严格 backward as-of，并返回带前缀的来源字段。"""

        self._require_columns(left, (query_date_col, *keys), "asof.left")
        self._require_columns(
            right, (source_date_col, *keys, *value_cols), "asof.right"
        )

        lwork = left.reset_index(drop=True).copy()
        lwork["_row_position"] = np.arange(len(lwork), dtype=int)
        rwork = right.loc[right[source_date_col].notna()].copy()

        grouper: str | list[str]
        grouper = keys[0] if len(keys) == 1 else list(keys)
        right_groups = {
            self._group_key(key): group
            for key, group in rwork.groupby(grouper, sort=False, dropna=False)
        }

        matched_parts: list[pd.DataFrame] = []
        for key, lgroup in lwork.groupby(grouper, sort=False, dropna=False):
            lgroup = lgroup.loc[lgroup[query_date_col].notna()]
            if lgroup.empty:
                continue
            rgroup = right_groups.get(self._group_key(key))
            if rgroup is None or rgroup.empty:
                continue

            # 相同知识日的最后一条记录已在输入预处理中确定；这里再次防御性去重。
            rgroup = (
                rgroup.sort_values(source_date_col, kind="mergesort")
                .drop_duplicates(source_date_col, keep="last")
            )
            lsorted = lgroup[["_row_position", query_date_col]].sort_values(
                query_date_col, kind="mergesort"
            )
            rsorted = rgroup[[source_date_col, *value_cols]].sort_values(
                source_date_col, kind="mergesort"
            )
            merged = pd.merge_asof(
                lsorted,
                rsorted,
                left_on=query_date_col,
                right_on=source_date_col,
                direction="backward",
                allow_exact_matches=True,
            )
            matched_parts.append(merged)

        output_names = [f"{prefix}source_effective_date"] + [
            f"{prefix}{column}" for column in value_cols
        ]
        result = pd.DataFrame(index=np.arange(len(lwork)))
        result[output_names[0]] = pd.NaT
        for column, output_name in zip(value_cols, output_names[1:]):
            if pd.api.types.is_datetime64_any_dtype(right[column]):
                result[output_name] = pd.NaT
            elif pd.api.types.is_numeric_dtype(right[column]):
                result[output_name] = np.nan
            else:
                result[output_name] = pd.Series(
                    [None] * len(result), index=result.index, dtype="object"
                )

        if matched_parts:
            matched = pd.concat(matched_parts, ignore_index=True).set_index("_row_position")
            result.loc[matched.index, output_names[0]] = matched[source_date_col].to_numpy()
            for column, output_name in zip(value_cols, output_names[1:]):
                result.loc[matched.index, output_name] = matched[column].to_numpy()

        result.index = left.index
        return result

    def _latest_report_period_lookup(
        self,
        left: pd.DataFrame,
        right: pd.DataFrame,
        *,
        query_date_col: str,
        source_date_col: str,
        value_cols: Sequence[str],
        prefix: str,
    ) -> pd.DataFrame:
        """映射截至查询日已知的最高报告期，而非简单选择最后发布事件。

        财报披露时间通常随报告期单调递增，但迟发/补发的旧报告会打破该假设。
        普通 ``merge_asof`` 会让“最后发布的旧报告”覆盖已知的新报告。本方法按知识
        时间在线扫描，同时维护截至当日可用的最大 ``report_period``，从而同时满足：

        - ``signal_available_date <= query_date``；
        - 在所有已知记录中选择最大的 ``report_period``。
        """

        self._require_columns(left, ("stock", query_date_col), "period_asof.left")
        self._require_columns(
            right,
            ("stock", "report_period", source_date_col, *value_cols),
            "period_asof.right",
        )

        lwork = left.reset_index(drop=True).copy()
        lwork["_row_position"] = np.arange(len(lwork), dtype=int)
        rwork = right.dropna(subset=["stock", "report_period", source_date_col]).copy()
        right_groups = {
            stock: group.sort_values(
                [source_date_col, "report_period"], kind="mergesort"
            ).reset_index(drop=True)
            for stock, group in rwork.groupby("stock", sort=False)
        }

        output_names = [f"{prefix}source_effective_date"] + [
            f"{prefix}{column}" for column in value_cols
        ]
        result = pd.DataFrame(index=np.arange(len(lwork)))
        result[output_names[0]] = pd.NaT
        for column, output_name in zip(value_cols, output_names[1:]):
            if pd.api.types.is_datetime64_any_dtype(right[column]):
                result[output_name] = pd.NaT
            elif pd.api.types.is_numeric_dtype(right[column]):
                result[output_name] = np.nan
            else:
                result[output_name] = pd.Series(
                    [None] * len(result), index=result.index, dtype="object"
                )

        for stock, left_group in lwork.groupby("stock", sort=False):
            right_group = right_groups.get(stock)
            if right_group is None or right_group.empty:
                continue
            left_sorted = left_group.loc[left_group[query_date_col].notna()].sort_values(
                query_date_col, kind="mergesort"
            )
            if left_sorted.empty:
                continue

            event_dates = right_group[source_date_col].to_numpy(dtype="datetime64[ns]")
            report_periods = right_group["report_period"].to_numpy(
                dtype="datetime64[ns]"
            )
            query_dates = left_sorted[query_date_col].to_numpy(dtype="datetime64[ns]")
            chosen = np.full(len(left_sorted), -1, dtype=int)
            pointer = 0
            best_row = -1
            best_period = np.datetime64("NaT")
            for query_idx, query_date in enumerate(query_dates):
                while pointer < len(right_group) and event_dates[pointer] <= query_date:
                    candidate_period = report_periods[pointer]
                    if best_row < 0 or candidate_period >= best_period:
                        best_row = pointer
                        best_period = candidate_period
                    pointer += 1
                chosen[query_idx] = best_row

            has_match = chosen >= 0
            if not has_match.any():
                continue
            row_positions = left_sorted.loc[has_match, "_row_position"].to_numpy(dtype=int)
            selected = right_group.iloc[chosen[has_match]]
            result.loc[row_positions, output_names[0]] = selected[
                source_date_col
            ].to_numpy()
            for column, output_name in zip(value_cols, output_names[1:]):
                result.loc[row_positions, output_name] = selected[column].to_numpy()

        result.index = left.index
        return result

    @staticmethod
    def _safe_ratio(
        numerator: pd.Series,
        denominator: pd.Series,
        epsilon: float,
    ) -> pd.Series:
        num = pd.to_numeric(numerator, errors="coerce").astype(float)
        den = pd.to_numeric(denominator, errors="coerce").astype(float)
        valid = num.notna() & den.notna() & (den.abs() > epsilon)
        out = pd.Series(np.nan, index=num.index, dtype=float)
        out.loc[valid] = num.loc[valid] / den.loc[valid]
        return out.replace([np.inf, -np.inf], np.nan)

    def _base_panel(self) -> pd.DataFrame:
        return self.price_df[["date", "stock", "industry", "market_cap"]].copy()

    # ------------------------------------------------------------------
    # 一致预期：目标预测期选择、境内外差异、3M 修订
    # ------------------------------------------------------------------
    def _consensus_target_base(self) -> pd.DataFrame:
        cache_key = "consensus_target_base"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        base = self.price_df[["date", "stock"]].copy()
        if "forecast_period" not in self.onshore_consensus_df.columns:
            self._cache[cache_key] = base
            return base.copy()

        metadata = pd.concat(
            [
                self.onshore_consensus_df[
                    ["stock", "forecast_period", "_effective_date"]
                ],
                self.offshore_consensus_df[
                    ["stock", "forecast_period", "_effective_date"]
                ],
            ],
            ignore_index=True,
        )
        metadata = (
            metadata.dropna(subset=["_effective_date", "forecast_period"])
            .groupby(["stock", "forecast_period"], as_index=False)["_effective_date"]
            .min()
            .rename(columns={"_effective_date": "first_available_date"})
        )

        selected = pd.Series(pd.NaT, index=base.index, dtype="datetime64[ns]")
        for stock, positions in base.groupby("stock", sort=False).groups.items():
            stock_meta = metadata.loc[metadata["stock"] == stock].sort_values(
                "forecast_period"
            )
            if stock_meta.empty:
                continue
            periods = stock_meta["forecast_period"].to_numpy(dtype="datetime64[ns]")
            first_available = stock_meta["first_available_date"].to_numpy(
                dtype="datetime64[ns]"
            )
            dates = base.loc[positions, "date"].to_numpy(dtype="datetime64[ns]")
            choices = np.full(len(dates), np.datetime64("NaT"), dtype="datetime64[ns]")
            for idx, current_date in enumerate(dates):
                # 只允许选择截至当日已经出现过的预测期，避免用“未来才会被覆盖”本身泄露。
                eligible = (periods >= current_date) & (first_available <= current_date)
                if eligible.any():
                    choices[idx] = periods[np.flatnonzero(eligible)[0]]
            selected.loc[positions] = choices

        base["forecast_period"] = selected
        self._cache[cache_key] = base
        return base.copy()

    def _map_consensus_source(
        self,
        base: pd.DataFrame,
        source: pd.DataFrame,
        *,
        prefix: str,
        query_date_col: str,
        values: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        value_cols = list(values or self.CONSENSUS_VALUE_COLUMNS)
        for optional in ("available_date", "currency", "share_basis", "analyst_count"):
            if optional in source.columns and optional not in value_cols:
                value_cols.append(optional)
        keys = ["stock"]
        if "forecast_period" in base.columns:
            keys.append("forecast_period")

        mapped = self._asof_lookup(
            base,
            source,
            query_date_col=query_date_col,
            source_date_col="_effective_date",
            keys=keys,
            value_cols=value_cols,
            prefix=prefix,
        )
        max_age = self.config.consensus_max_age_days
        if max_age is not None:
            age = (
                base[query_date_col] - mapped[f"{prefix}source_effective_date"]
            ).dt.days
            stale = age > max_age
            for column in mapped.columns:
                if column != f"{prefix}source_effective_date":
                    mapped.loc[stale, column] = np.nan
        return mapped

    def compute_dual_consensus_gaps(self) -> pd.DataFrame:
        """计算境内/境外 EPS、净利润、目标价相对偏离度。"""

        base = self._consensus_target_base()
        onshore = self._map_consensus_source(
            base,
            self.onshore_consensus_df,
            prefix="onshore_",
            query_date_col="date",
        )
        offshore = self._map_consensus_source(
            base,
            self.offshore_consensus_df,
            prefix="offshore_",
            query_date_col="date",
        )
        out = pd.concat([base, onshore, offshore], axis=1)

        comparable = pd.Series(True, index=out.index)
        for optional in ("currency", "share_basis"):
            on_col = f"onshore_{optional}"
            off_col = f"offshore_{optional}"
            if on_col in out.columns and off_col in out.columns:
                comparable &= out[on_col].notna() & out[off_col].notna()
                comparable &= out[on_col].astype(str) == out[off_col].astype(str)

        for metric in self.CONSENSUS_VALUE_COLUMNS:
            ratio = self._safe_ratio(
                out[f"onshore_{metric}"],
                out[f"offshore_{metric}"],
                self.config.denominator_epsilon,
            )
            out[f"dual_gap_{metric}"] = (ratio - 1.0).where(comparable)
        return out

    def compute_eechange_3m(self) -> pd.DataFrame:
        """按相同预测期、三个日历月前的知识截止日计算盈利预期变动。"""

        current = self.compute_dual_consensus_gaps()
        base_cols = ["date", "stock"]
        if "forecast_period" in current.columns:
            base_cols.append("forecast_period")
        base = current[base_cols].copy()
        base["_three_month_cutoff"] = base["date"] - pd.DateOffset(months=3)

        historical_on = self._map_consensus_source(
            base,
            self.onshore_consensus_df,
            prefix="hist_onshore_",
            query_date_col="_three_month_cutoff",
            values=("net_profit",),
        )
        historical_off = self._map_consensus_source(
            base,
            self.offshore_consensus_df,
            prefix="hist_offshore_",
            query_date_col="_three_month_cutoff",
            values=("net_profit",),
        )

        source = self.config.eechange_source
        if source == "onshore":
            current_profit = current["onshore_net_profit"]
            historical_profit = historical_on["hist_onshore_net_profit"]
        elif source == "offshore":
            current_profit = current["offshore_net_profit"]
            historical_profit = historical_off["hist_offshore_net_profit"]
        else:
            # 未提供总体一致预期时使用境内/境外等权均值，但两个时点都必须两侧
            # 完整，避免“历史只有境内、当前新增境外”被误当成盈利预测修订。
            current_pair = current[
                ["onshore_net_profit", "offshore_net_profit"]
            ]
            historical_pair = pd.concat(
                [
                    historical_on["hist_onshore_net_profit"],
                    historical_off["hist_offshore_net_profit"],
                ],
                axis=1,
            )
            blend_valid = current_pair.notna().all(axis=1) & historical_pair.notna().all(
                axis=1
            )
            for optional in ("currency", "share_basis"):
                current_on = f"onshore_{optional}"
                current_off = f"offshore_{optional}"
                hist_on = f"hist_onshore_{optional}"
                hist_off = f"hist_offshore_{optional}"
                if all(
                    column in frame.columns
                    for column, frame in (
                        (current_on, current),
                        (current_off, current),
                        (hist_on, historical_on),
                        (hist_off, historical_off),
                    )
                ):
                    blend_valid &= current[current_on] == current[current_off]
                    blend_valid &= historical_on[hist_on] == historical_off[hist_off]
                    blend_valid &= current[current_on] == historical_on[hist_on]

            current_profit = current_pair.mean(axis=1).where(blend_valid)
            historical_profit = historical_pair.mean(axis=1).where(blend_valid)

        out = base[["date", "stock"]].copy()
        out["EEChange_3M"] = self._safe_ratio(
            current_profit,
            historical_profit,
            self.config.denominator_epsilon,
        ) - 1.0
        return out

    # ------------------------------------------------------------------
    # 南向资金与价格行为因子
    # ------------------------------------------------------------------
    def compute_southbound_factors(self) -> pd.DataFrame:
        """计算 20 日持仓占比变化与 20 日开盘流入率均值。"""

        panel = self.price_df[["date", "stock"]].merge(
            self.southbound_flow_df,
            on=["date", "stock"],
            how="left",
            validate="one_to_one",
        )
        panel = panel.sort_values(["stock", "date"], kind="mergesort")
        window = self.config.southbound_window
        grouped = panel.groupby("stock", sort=False, group_keys=False)
        panel["SB_Holding_Change"] = grouped["sb_holding_ratio"].diff(window)
        panel["inflow_rate_open"] = grouped["inflow_rate_open"].transform(
            lambda values: values.rolling(window, min_periods=window).mean()
        )
        return panel[
            ["date", "stock", "SB_Holding_Change", "inflow_rate_open"]
        ].sort_values(["stock", "date"], kind="mergesort")

    def compute_overnight_momentum(self) -> pd.DataFrame:
        """过去 252 日隔夜收益和，剔除最近 20 日。"""

        panel = self.price_df[["date", "stock", "open", "close"]].copy()
        panel = panel.sort_values(["stock", "date"], kind="mergesort")
        grouped = panel.groupby("stock", sort=False, group_keys=False)
        previous_close = grouped["close"].shift(1)
        panel["_overnight_return"] = self._safe_ratio(
            panel["open"], previous_close, self.config.denominator_epsilon
        ) - 1.0

        year_window = self.config.overnight_year_window
        skip_window = self.config.overnight_skip_window
        long_sum = panel.groupby("stock", sort=False)["_overnight_return"].transform(
            lambda values: values.rolling(
                year_window, min_periods=year_window
            ).sum()
        )
        short_sum = panel.groupby("stock", sort=False)["_overnight_return"].transform(
            lambda values: values.rolling(skip_window, min_periods=skip_window).sum()
        )
        panel["mmt_overnight_A"] = long_sum - short_sum
        return panel[["date", "stock", "mmt_overnight_A"]]

    def compute_turnover_lead_corr(self) -> pd.DataFrame:
        """20 个已实现配对中，t 日换手率与 t+1 日收盘收益率的相关系数。

        信号日 d 的窗口为：
        ``turnover[d-20:d-1]`` 对 ``close_return[d-19:d]``。
        因此实现使用 ``turnover.shift(1)`` 与当日 close return 滚动相关，绝不
        在 d 行直接使用 ``return.shift(-1)``。
        """

        panel = self.price_df[
            ["date", "stock", "close", "turnover_rate"]
        ].copy()
        panel = panel.sort_values(["stock", "date"], kind="mergesort")
        window = self.config.turnover_lead_window
        pieces: list[pd.DataFrame] = []
        for _, group in panel.groupby("stock", sort=False):
            group = group.copy()
            close_return = group["close"].pct_change(fill_method=None)
            lagged_turnover = group["turnover_rate"].shift(1)
            group["corr_ret_turn_post_1M"] = lagged_turnover.rolling(
                window, min_periods=window
            ).corr(close_return)
            pieces.append(group[["date", "stock", "corr_ret_turn_post_1M"]])
        return pd.concat(pieces, ignore_index=True)

    # ------------------------------------------------------------------
    # PIT 财报与股东因子
    # ------------------------------------------------------------------
    def _first_available_report_records(
        self, df: pd.DataFrame, name: str
    ) -> pd.DataFrame:
        """每个报告期冻结首次可得版本，防止最终修订值回写历史。"""

        ordered = df.sort_values(
            ["stock", "report_period", "available_date"], kind="mergesort"
        )
        first = ordered.drop_duplicates(["stock", "report_period"], keep="first")
        self._ensure_unique(first, ("stock", "report_period"), name)
        return first.reset_index(drop=True)

    def _financial_period_factors(self) -> pd.DataFrame:
        cache_key = "financial_period_factors"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        current = self._first_available_report_records(
            self.financial_df, "financial_df(first_available)"
        ).sort_values(["stock", "report_period"], kind="mergesort")

        # 用“同一财政期的一年前”做可比基准，而不是假定数据完整后简单 shift(4)。
        current["_prior_period"] = current["report_period"] - pd.DateOffset(years=1)
        lag_source = current[
            [
                "stock",
                "report_period",
                "_effective_date",
                "eps",
                "total_assets",
                "total_equity",
            ]
        ].rename(
            columns={
                "report_period": "_prior_period",
                "_effective_date": "_prior_effective_date",
                "eps": "_prior_eps",
                "total_assets": "_prior_total_assets",
                "total_equity": "_prior_total_equity",
            }
        )
        period = current.merge(
            lag_source,
            on=["stock", "_prior_period"],
            how="left",
            validate="many_to_one",
        )

        average_equity = (period["total_equity"] + period["_prior_total_equity"]) / 2.0
        average_assets = (period["total_assets"] + period["_prior_total_assets"]) / 2.0
        period["roe"] = self._safe_ratio(
            period["net_profit"], average_equity, self.config.denominator_epsilon
        ).where(average_equity > 0)

        eps_base_valid = period["_prior_eps"] > self.config.denominator_epsilon
        period["eps_growth"] = self._safe_ratio(
            period["eps"] - period["_prior_eps"],
            period["_prior_eps"].abs(),
            self.config.denominator_epsilon,
        ).where(eps_base_valid)

        period["asset_turnover"] = self._safe_ratio(
            period["revenue"], average_assets, self.config.denominator_epsilon
        ).where(average_assets > 0)
        period["accrual_ratio"] = self._safe_ratio(
            period["net_profit"] - period["operating_cash_flow"],
            average_assets,
            self.config.denominator_epsilon,
        ).where(average_assets > 0)

        base_dependency_dates = period[["_effective_date", "_prior_effective_date"]]
        period["_base_quality_available_date"] = base_dependency_dates.max(axis=1).where(
            base_dependency_dates.notna().all(axis=1)
        )
        period["asset_turnover_available_date"] = period[
            "_base_quality_available_date"
        ]

        prior_turnover = period[
            [
                "stock",
                "report_period",
                "asset_turnover",
                "asset_turnover_available_date",
            ]
        ].rename(
            columns={
                "report_period": "_prior_period",
                "asset_turnover": "_prior_asset_turnover",
                "asset_turnover_available_date": "_prior_asset_turnover_available_date",
            }
        )
        period = period.merge(
            prior_turnover,
            on=["stock", "_prior_period"],
            how="left",
            validate="many_to_one",
        )
        period["asset_turnover_change"] = (
            period["asset_turnover"] - period["_prior_asset_turnover"]
        )
        period["earnings_quality"] = -period["accrual_ratio"]
        period["book_equity"] = period["total_equity"]

        # 资产周转变化还依赖“上期资产周转率”，而后者继续依赖上上期资产；因此
        # QQC 的完整知识时间必须传播 t、t-1、t-2 的全部依赖，不能只 max(t,t-1)。
        quality_dependency_dates = period[
            ["_base_quality_available_date", "_prior_asset_turnover_available_date"]
        ]
        period["quality_available_date"] = quality_dependency_dates.max(axis=1).where(
            quality_dependency_dates.notna().all(axis=1)
        )
        self._cache[cache_key] = period
        return period.copy()

    def _map_financial_to_daily(
        self, *, source_date_col: str, value_cols: Sequence[str], prefix: str = ""
    ) -> pd.DataFrame:
        base = self.price_df[["date", "stock"]].copy()
        period = self._financial_period_factors()
        return self._latest_report_period_lookup(
            base,
            period,
            query_date_col="date",
            source_date_col=source_date_col,
            value_cols=value_cols,
            prefix=prefix,
        )

    @staticmethod
    def _plain_cross_section_zscore(values: pd.Series, epsilon: float) -> pd.Series:
        finite = values.replace([np.inf, -np.inf], np.nan).dropna()
        out = pd.Series(np.nan, index=values.index, dtype=float)
        if len(finite) < 2:
            return out
        std = finite.std(ddof=0)
        if not np.isfinite(std) or std <= epsilon:
            out.loc[finite.index] = 0.0
        else:
            out.loc[finite.index] = (finite - finite.mean()) / std
        return out

    def _quality_component_zscore(self, values: pd.Series) -> pd.Series:
        """QQC 子项先做 2%/98% winsorization，再标准化以实现真实等权。"""

        finite = values.replace([np.inf, -np.inf], np.nan).dropna().astype(float)
        prepared = pd.Series(np.nan, index=values.index, dtype=float)
        if finite.empty:
            return prepared
        if len(finite) >= 3:
            lower = finite.quantile(self.config.trim_lower, interpolation="linear")
            upper = finite.quantile(self.config.trim_upper, interpolation="linear")
            finite = finite.clip(lower=lower, upper=upper)
        std = finite.std(ddof=0)
        if not np.isfinite(std) or std <= self.config.numerical_epsilon:
            prepared.loc[finite.index] = 0.0
        else:
            prepared.loc[finite.index] = (finite - finite.mean()) / std
        return prepared

    def compute_qqc(self) -> pd.DataFrame:
        """等权合成 ROE、EPS 同比、资产周转同比变化与负应计比率。"""

        base = self.price_df[["date", "stock"]].copy()
        component_names = (
            "roe",
            "eps_growth",
            "asset_turnover_change",
            "earnings_quality",
        )
        mapped = self._map_financial_to_daily(
            source_date_col="quality_available_date",
            value_cols=("report_period", *component_names),
        )
        panel = pd.concat([base, mapped], axis=1)

        standardized: list[str] = []
        for component in component_names:
            z_col = f"_{component}_z"
            panel[z_col] = panel.groupby("date", sort=False)[component].transform(
                self._quality_component_zscore
            )
            standardized.append(z_col)

        valid_count = panel[standardized].notna().sum(axis=1)
        panel["QQC"] = panel[standardized].mean(axis=1, skipna=True).where(
            valid_count >= self.config.quality_min_components
        )
        panel["QQC_component_count"] = valid_count
        return panel[
            ["date", "stock", "QQC", "QQC_component_count", "source_effective_date", "report_period"]
        ]

    def compute_hn_z(self) -> pd.DataFrame:
        """在股东披露事件序列计算历史 z-score，再映射到日频。"""

        events = self._first_available_report_records(
            self.shareholder_df, "shareholder_df(first_available)"
        ).sort_values(["stock", "report_period"], kind="mergesort")
        window = self.config.shareholder_history_window
        min_history = self.config.shareholder_min_history

        pieces: list[pd.DataFrame] = []
        for _, group in events.groupby("stock", sort=False):
            group = group.copy()
            history = group["shareholder_count"].shift(1)
            historical_mean = history.rolling(window, min_periods=min_history).mean()
            historical_std = history.rolling(window, min_periods=min_history).std(ddof=0)
            group["HN_z"] = self._safe_ratio(
                group["shareholder_count"] - historical_mean,
                historical_std,
                self.config.denominator_epsilon,
            )

            # HN_z 的历史窗口也有自己的知识时间。若某个旧报告迟发，当前报告的
            # z-score 只能在该历史窗口全部达到 min_history 个可得记录之后生效。
            history_dates = group["_effective_date"].shift(1)
            history_ns = history_dates.astype("int64").where(history_dates.notna())
            history_max_ns = history_ns.rolling(
                window, min_periods=min_history
            ).max()
            history_max_date = pd.to_datetime(history_max_ns, errors="coerce")
            hn_dependency_dates = pd.concat(
                [group["_effective_date"], history_max_date], axis=1
            )
            group["HN_available_date"] = hn_dependency_dates.max(axis=1).where(
                hn_dependency_dates.notna().all(axis=1)
            )
            pieces.append(group)
        period = pd.concat(pieces, ignore_index=True)

        base = self.price_df[["date", "stock"]].copy()
        mapped = self._latest_report_period_lookup(
            base,
            period,
            query_date_col="date",
            source_date_col="HN_available_date",
            value_cols=("report_period", "HN_z"),
            prefix="shareholder_",
        )
        out = base.copy()
        out["HN_z"] = mapped["shareholder_HN_z"]
        out["shareholder_source_effective_date"] = mapped[
            "shareholder_source_effective_date"
        ]
        out["shareholder_report_period"] = mapped["shareholder_report_period"]
        return out

    def compute_bp(self) -> pd.DataFrame:
        """PIT 净资产除以每个交易日的当日总市值。"""

        base = self.price_df[["date", "stock", "market_cap"]].copy()
        mapped = self._map_financial_to_daily(
            source_date_col="_effective_date",
            value_cols=("report_period", "book_equity"),
            prefix="financial_",
        )
        out = pd.concat([base, mapped], axis=1)
        out["BP"] = self._safe_ratio(
            out["financial_book_equity"],
            out["market_cap"],
            self.config.denominator_epsilon,
        )
        return out[
            [
                "date",
                "stock",
                "BP",
                "financial_source_effective_date",
                "financial_report_period",
            ]
        ]

    # ------------------------------------------------------------------
    # 共同分析师网络与惊喜扩散
    # ------------------------------------------------------------------
    def _daily_surprise_panel(self) -> pd.DataFrame:
        cache_key = "daily_surprise_panel"
        if cache_key in self._cache:
            return self._cache[cache_key].copy()

        stock_universe_set = set(self.price_df["stock"].dropna().astype(str))
        if self.analyst_surprise_df is not None:
            stock_universe_set.update(
                self.analyst_surprise_df["stock"].dropna().astype(str)
            )
        if self.analyst_network_df is not None:
            stock_universe_set.update(
                self.analyst_network_df["target_stock"].dropna().astype(str)
            )
            stock_universe_set.update(
                self.analyst_network_df["related_stock"].dropna().astype(str)
            )
        stock_universe = sorted(stock_universe_set)
        # 使用完整交易所日期×股票网格，而不是各股票实际行情行。这样关联股停牌或
        # 行情缺行时，事件仍会在交易所生效日进入窗口，不会被永久吞掉。
        base = pd.MultiIndex.from_product(
            [self.trading_dates, stock_universe], names=["date", "stock"]
        ).to_frame(index=False)
        if self.analyst_surprise_df is None:
            base["related_surprise"] = np.nan
            self._cache[cache_key] = base
            return base.copy()

        events = self.analyst_surprise_df.copy()
        title_flag = events["title_positive_surprise"].fillna(False).astype(bool)
        rating_flag = events["rating_upgrade"].fillna(False).astype(bool)
        revision_flag = (events["earnings_revision"] > 0) & (
            events["upgrade_breadth"] > 0
        )
        events["_surprise"] = (title_flag | rating_flag | revision_flag).astype(float)
        # 同公司、同一生效日多条研报只计一次，避免研报数量偏差。
        events = (
            events.dropna(subset=["_effective_date"])
            .groupby(["stock", "_effective_date"], as_index=False)["_surprise"]
            .max()
        )

        pieces: list[pd.DataFrame] = []
        window = self.config.network_surprise_window
        event_groups = {stock: group for stock, group in events.groupby("stock")}
        first_observed_date = self.price_df.groupby("stock", sort=False)["date"].min()
        for stock, daily in base.groupby("stock", sort=False):
            daily = daily.sort_values("date", kind="mergesort").copy()
            impulse = np.zeros(len(daily), dtype=float)
            stock_events = event_groups.get(stock)
            if stock_events is not None:
                event_dates = stock_events["_effective_date"].to_numpy(
                    dtype="datetime64[ns]"
                )
                daily_dates = daily["date"].to_numpy(dtype="datetime64[ns]")
                positions = np.searchsorted(daily_dates, event_dates, side="left")
                inside = (positions < len(daily_dates)) & (
                    event_dates >= daily_dates[0]
                )
                for position, score in zip(
                    positions[inside],
                    stock_events.loc[inside, "_surprise"].to_numpy(dtype=float),
                ):
                    impulse[position] = max(impulse[position], score)
            rolling_surprise = (
                pd.Series(impulse)
                .rolling(window, min_periods=1)
                .max()
                .to_numpy()
            )
            # 股票进入 PIT 可观测/可交易股票池之前，不能利用全样本未来上市信息把
            # “未知”回填成 0；上市/首次观察后，无事件才按完整事件账本解释为 0。
            if stock in first_observed_date.index:
                coverage_start = first_observed_date.loc[stock]
            elif stock_events is not None and not stock_events.empty:
                coverage_start = stock_events["_effective_date"].min()
            else:
                coverage_start = pd.NaT
            if pd.isna(coverage_start):
                covered = np.zeros(len(daily), dtype=bool)
            else:
                covered = daily["date"].to_numpy(
                    dtype="datetime64[ns]"
                ) >= np.datetime64(coverage_start)
            daily["related_surprise"] = np.where(
                covered, rolling_surprise, np.nan
            )
            pieces.append(daily)

        result = pd.concat(pieces, ignore_index=True)
        self._cache[cache_key] = result
        return result.copy()

    def compute_network_diffusion(self) -> pd.DataFrame:
        """PIT 网络边权对关联公司当期正向惊喜做 SC 加权聚合。"""

        base = self.price_df[["date", "stock"]].copy()
        if self.analyst_network_df is None or self.analyst_surprise_df is None:
            base["analyst_network_diffusion"] = np.nan
            return base

        edges = self.analyst_network_df.copy()
        surprises = self._daily_surprise_panel()
        surprise_wide = surprises.pivot(
            index="date", columns="stock", values="related_surprise"
        )

        # 按 target 分块构造 D×K（日期×历史邻居）的小矩阵，避免把全市场扩成
        # date×所有历史边的巨型 DataFrame。边表语义是 pair-level 更新日志；
        # sc_weight=0 是显式失效 tombstone，旧边不会在零权重之后继续生效。
        aggregate_parts: list[pd.DataFrame] = []
        target_date_groups = {
            stock: group["date"].sort_values().drop_duplicates()
            for stock, group in base.groupby("stock", sort=False)
        }
        for target, target_edges in edges.groupby("target_stock", sort=False):
            target_dates_series = target_date_groups.get(target)
            if target_dates_series is None or target_dates_series.empty:
                continue
            target_dates = target_dates_series.to_numpy(dtype="datetime64[ns]")
            related_stocks = target_edges["related_stock"].drop_duplicates().tolist()
            weight_matrix = np.full(
                (len(target_dates), len(related_stocks)), np.nan, dtype=float
            )

            for related_idx, related in enumerate(related_stocks):
                pair_events = target_edges.loc[
                    target_edges["related_stock"] == related
                ].sort_values(["_effective_date", "available_date"], kind="mergesort")
                event_dates = pair_events["_effective_date"].to_numpy(
                    dtype="datetime64[ns]"
                )
                event_weights = pair_events["sc_weight"].to_numpy(dtype=float)
                event_position = np.searchsorted(
                    event_dates, target_dates, side="right"
                ) - 1
                known = event_position >= 0
                weight_matrix[known, related_idx] = event_weights[
                    event_position[known]
                ]

            surprise_matrix = surprise_wide.reindex(
                index=pd.DatetimeIndex(target_dates), columns=related_stocks
            ).to_numpy(dtype=float)
            valid = (
                np.isfinite(weight_matrix)
                & (weight_matrix > self.config.denominator_epsilon)
                & np.isfinite(surprise_matrix)
            )
            weighted_values = np.where(
                valid, weight_matrix * surprise_matrix, 0.0
            )
            valid_weights = np.where(valid, weight_matrix, 0.0)
            weighted_sum = weighted_values.sum(axis=1)
            valid_weight = valid_weights.sum(axis=1)
            neighbor_count = valid.sum(axis=1)
            if self.config.normalize_network_weights:
                diffusion = np.divide(
                    weighted_sum,
                    valid_weight,
                    out=np.full(len(target_dates), np.nan, dtype=float),
                    where=valid_weight > self.config.denominator_epsilon,
                )
            else:
                diffusion = np.where(neighbor_count > 0, weighted_sum, np.nan)

            aggregate_parts.append(
                pd.DataFrame(
                    {
                        "date": pd.DatetimeIndex(target_dates),
                        "stock": target,
                        "analyst_network_diffusion": diffusion,
                        "valid_weight": valid_weight,
                        "neighbor_count": neighbor_count,
                    }
                )
            )

        if aggregate_parts:
            aggregate = pd.concat(aggregate_parts, ignore_index=True)
        else:
            aggregate = pd.DataFrame(
                columns=[
                    "date",
                    "stock",
                    "analyst_network_diffusion",
                    "valid_weight",
                    "neighbor_count",
                ]
            )

        out = base.merge(
            aggregate,
            on=["date", "stock"],
            how="left",
            validate="one_to_one",
        )
        return out

    # ------------------------------------------------------------------
    # 因子面板组装与统一截面处理
    # ------------------------------------------------------------------
    def compute_all_raw_factors(self) -> pd.DataFrame:
        """组装全部原始因子；每个子模块均保持独立可测试。"""

        panel = self._base_panel()
        factor_frames = (
            (
                self.compute_dual_consensus_gaps(),
                ("dual_gap_eps", "dual_gap_net_profit", "dual_gap_target_price"),
            ),
            (
                self.compute_southbound_factors(),
                ("SB_Holding_Change", "inflow_rate_open"),
            ),
            (
                self.compute_network_diffusion(),
                ("analyst_network_diffusion",),
            ),
            (self.compute_qqc(), ("QQC",)),
            (self.compute_hn_z(), ("HN_z",)),
            (self.compute_bp(), ("BP",)),
            (self.compute_overnight_momentum(), ("mmt_overnight_A",)),
            (
                self.compute_turnover_lead_corr(),
                ("corr_ret_turn_post_1M",),
            ),
            (self.compute_eechange_3m(), ("EEChange_3M",)),
        )
        for frame, columns in factor_frames:
            self._ensure_unique(frame, ("date", "stock"), "factor_frame")
            panel = panel.merge(
                frame[["date", "stock", *columns]],
                on=["date", "stock"],
                how="left",
                validate="one_to_one",
            )
        return panel.sort_values(["date", "stock"], kind="mergesort").reset_index(
            drop=True
        )

    def _trim_cross_section(self, values: pd.Series) -> pd.Series:
        out = values.replace([np.inf, -np.inf], np.nan).astype(float).copy()
        finite = out.dropna()
        if len(finite) < 3:
            return out
        lower = finite.quantile(self.config.trim_lower, interpolation="linear")
        upper = finite.quantile(self.config.trim_upper, interpolation="linear")
        if self.config.trimming_mode == "winsorize":
            out.loc[finite.index] = finite.clip(lower=lower, upper=upper)
        else:
            out.loc[(out < lower) | (out > upper)] = np.nan
        return out

    def _industry_zscore_same_sample(self, group: pd.DataFrame) -> pd.Series:
        """在因子、行业、正市值同时有效的样本上做行业内 z-score。"""

        result = pd.Series(np.nan, index=group.index, dtype=float)
        valid = (
            group["_trimmed"].notna()
            & group["industry"].notna()
            & group["market_cap"].notna()
            & (group["market_cap"] > 0)
        )
        valid_group = group.loc[valid]
        for _, positions in valid_group.groupby("industry", sort=False).groups.items():
            values = group.loc[positions, "_trimmed"]
            if len(values) < self.config.min_industry_obs:
                continue
            std = values.std(ddof=0)
            scale = max(1.0, abs(float(values.mean())))
            if not np.isfinite(std) or std <= self.config.numerical_epsilon * scale:
                result.loc[positions] = 0.0
            else:
                result.loc[positions] = (values - values.mean()) / std
        return result

    def _neutralize_one_date(self, group: pd.DataFrame) -> pd.Series:
        """对行业内去均值的 log 市值回归，保留行业均值与规模正交性。"""

        result = pd.Series(np.nan, index=group.index, dtype=float)
        valid = (
            group["_industry_z"].notna()
            & group["industry"].notna()
            & group["market_cap"].notna()
            & (group["market_cap"] > 0)
        )
        sample = group.loc[valid].copy()
        if len(sample) < self.config.min_neutralization_obs:
            return result

        sample["_log_cap"] = np.log(sample["market_cap"].astype(float))
        sample["_log_cap_within_industry"] = sample["_log_cap"] - sample.groupby(
            "industry", sort=False
        )["_log_cap"].transform("mean")

        y = sample["_industry_z"].to_numpy(dtype=float)
        x_size = sample["_log_cap_within_industry"].to_numpy(dtype=float)
        if np.nanstd(x_size) <= self.config.numerical_epsilon:
            residual = y - np.nanmean(y)
        else:
            design = np.column_stack([np.ones(len(sample)), x_size])
            beta, _, rank, _ = np.linalg.lstsq(design, y, rcond=None)
            if rank < design.shape[1]:
                residual = y - np.nanmean(y)
            else:
                residual = y - design @ beta
        result.loc[sample.index] = residual
        return result

    def _trim_panel_by_date(self, work: pd.DataFrame, factor: str) -> pd.Series:
        """向量化逐日分位数处理；与逐组调用 ``_trim_cross_section`` 等价。"""

        values = work[factor].replace([np.inf, -np.inf], np.nan).astype(float)
        grouped = values.groupby(work["date"], sort=False)
        count = grouped.transform("count")
        lower = grouped.transform(
            "quantile", q=self.config.trim_lower, interpolation="linear"
        )
        upper = grouped.transform(
            "quantile", q=self.config.trim_upper, interpolation="linear"
        )
        if self.config.trimming_mode == "winsorize":
            processed = values.clip(lower=lower, upper=upper)
        else:
            processed = values.where((values >= lower) & (values <= upper))
        # 小于 3 个有效值时分位数处理没有稳定含义，保持原值，后续样本门槛会处理。
        return processed.where(count >= 3, values)

    def _industry_zscore_panel(self, work: pd.DataFrame) -> pd.Series:
        """在同一个回归有效样本上向量化计算 date×industry z-score。"""

        valid = (
            work["_trimmed"].notna()
            & work["industry"].notna()
            & work["market_cap"].notna()
            & (work["market_cap"] > 0)
        )
        sample_value = work["_trimmed"].where(valid)
        keys = [work["date"], work["industry"]]
        grouped = sample_value.groupby(keys, sort=False, dropna=False)
        count = grouped.transform("count")
        mean = grouped.transform("mean")
        # 先中心化再平方，避免 E[x^2]-E[x]^2 在大数值、低离散截面上的灾难性消减。
        centered = sample_value - mean
        variance = centered.pow(2).groupby(
            keys, sort=False, dropna=False
        ).transform("mean")
        std = np.sqrt(variance)

        zscore = (sample_value - mean) / std.where(
            std > self.config.numerical_epsilon * mean.abs().clip(lower=1.0)
        )
        eligible = count >= self.config.min_industry_obs
        constant = eligible & (
            std <= self.config.numerical_epsilon * mean.abs().clip(lower=1.0)
        )
        zscore = zscore.where(eligible)
        zscore.loc[constant & sample_value.notna()] = 0.0
        return zscore.replace([np.inf, -np.inf], np.nan)

    def _neutralize_panel_by_date(self, work: pd.DataFrame) -> pd.Series:
        """向量化逐日 OLS：industry_z ~ 1 + 行业内去均值 log(market_cap)。

        对单解释变量带截距 OLS，斜率等于 ``cov(x, y) / var(x)``。闭式写法与
        ``np.linalg.lstsq`` 的残差完全等价，却避免对数千个交易日逐组进入 Python。
        """

        valid = (
            work["_industry_z"].notna()
            & work["industry"].notna()
            & work["market_cap"].notna()
            & (work["market_cap"] > 0)
        )
        y = work["_industry_z"].where(valid)
        log_cap = np.log(work["market_cap"].where(valid))
        industry_keys = [work["date"], work["industry"]]
        log_cap_industry_mean = log_cap.groupby(
            industry_keys, sort=False, dropna=False
        ).transform("mean")
        x = log_cap - log_cap_industry_mean

        date_key = work["date"]
        count = y.groupby(date_key, sort=False).transform("count")
        y_mean = y.groupby(date_key, sort=False).transform("mean")
        x_mean = x.groupby(date_key, sort=False).transform("mean")
        x_centered = x - x_mean
        y_centered = y - y_mean
        covariance = (x_centered * y_centered).groupby(
            date_key, sort=False
        ).transform("mean")
        variance = x_centered.pow(2).groupby(date_key, sort=False).transform("mean")

        slope = self._safe_ratio(
            covariance, variance, self.config.numerical_epsilon
        ).fillna(0.0)
        residual = y_centered - slope * x_centered
        residual = residual.where(count >= self.config.min_neutralization_obs)
        return residual.replace([np.inf, -np.inf], np.nan)

    def postprocess_factors(
        self,
        raw_panel: pd.DataFrame,
        factor_columns: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """依次执行截面 trimming、行业 z-score 与市值中性化。

        返回原始列，并新增 ``<factor>_neutral``。新增列就是最终指定的 OLS
        残差，不再二次 z-score，以免破坏市值正交性。
        """

        factors = tuple(self.FACTOR_COLUMNS if factor_columns is None else factor_columns)
        self._require_columns(
            raw_panel,
            ("date", "stock", "industry", "market_cap", *factors),
            "raw_panel",
        )
        self._ensure_unique(raw_panel, ("date", "stock"), "raw_panel")
        output = raw_panel.copy()

        for factor in factors:
            work = output[["date", "stock", "industry", "market_cap", factor]].copy()
            work[factor] = work[factor].replace([np.inf, -np.inf], np.nan)
            work["_trimmed"] = self._trim_panel_by_date(work, factor)
            work["_industry_z"] = self._industry_zscore_panel(work)
            output[f"{factor}_neutral"] = self._neutralize_panel_by_date(work)

        neutral_columns = [f"{factor}_neutral" for factor in factors]
        output[neutral_columns] = output[neutral_columns].replace(
            [np.inf, -np.inf], np.nan
        )
        return output

    def generate(self) -> pd.DataFrame:
        """一键生成原始因子和统一处理后的中性残差。"""

        raw = self.compute_all_raw_factors()
        return self.postprocess_factors(raw)


# ----------------------------------------------------------------------
# 可运行的 5 只港股合成数据演示
# ----------------------------------------------------------------------
def _make_demo_data(seed: int = 20260808) -> dict[str, pd.DataFrame]:
    """生成只用于接口演示、没有任何投资含义的合成数据。"""

    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-02", periods=340)
    stocks = ["0005.HK", "0700.HK", "1299.HK", "1810.HK", "3690.HK"]

    price_rows: list[dict[str, object]] = []
    flow_rows: list[dict[str, object]] = []
    base_prices = np.array([45.0, 290.0, 58.0, 12.0, 105.0])
    base_caps = np.array([8.0e11, 2.8e12, 9.0e11, 3.0e11, 9.5e11])
    for stock_idx, stock in enumerate(stocks):
        overnight = rng.normal(0.00025 + stock_idx * 0.00003, 0.008, len(dates))
        intraday = rng.normal(0.00010, 0.012, len(dates))
        open_price = np.empty(len(dates))
        close_price = np.empty(len(dates))
        close_price[0] = base_prices[stock_idx]
        open_price[0] = close_price[0] * (1 + overnight[0])
        close_price[0] = open_price[0] * (1 + intraday[0])
        for idx in range(1, len(dates)):
            open_price[idx] = close_price[idx - 1] * (1 + overnight[idx])
            close_price[idx] = open_price[idx] * (1 + intraday[idx])

        turnover = np.clip(
            0.008 + 0.35 * np.abs(intraday) + rng.normal(0, 0.002, len(dates)),
            0.001,
            None,
        )
        market_cap = base_caps[stock_idx] * close_price / close_price[0]
        holding_ratio = np.clip(
            0.025
            + stock_idx * 0.004
            + np.cumsum(rng.normal(0.00002, 0.00022, len(dates))),
            0.001,
            0.25,
        )
        open_inflow = (
            0.15 * np.r_[0.0, np.diff(holding_ratio)] / 0.00022
            + rng.normal(0, 0.04, len(dates))
        )

        for idx, current_date in enumerate(dates):
            price_rows.append(
                {
                    "date": current_date,
                    "stock": stock,
                    "open": open_price[idx],
                    "close": close_price[idx],
                    "turnover_rate": turnover[idx],
                    "market_cap": market_cap[idx],
                    # 5 股样本极小；统一示例行业可让严格 trimming 后仍能演示回归残差。
                    "industry": "综合示例行业",
                }
            )
            flow_rows.append(
                {
                    "date": current_date,
                    "stock": stock,
                    "sb_holding_ratio": holding_ratio[idx],
                    "inflow_rate_open": open_inflow[idx],
                }
            )

    price_df = pd.DataFrame(price_rows)
    southbound_flow_df = pd.DataFrame(flow_rows)

    # 境内外更新日错开；Q4 开始预报下一财政年度，以便跨年后仍可做同预测期 3M 对比。
    consensus_frames: dict[str, list[dict[str, object]]] = {
        "onshore": [],
        "offshore": [],
    }
    schedules = {
        "onshore": dates[::12],
        "offshore": dates[5::14],
    }
    for side, schedule in schedules.items():
        side_bias = 0.055 if side == "onshore" else -0.015
        for stock_idx, stock in enumerate(stocks):
            for event_idx, event_date in enumerate(schedule):
                target_year = event_date.year + int(event_date.month >= 10)
                trend = 1.0 + 0.0015 * event_idx
                eps = (2.0 + 0.35 * stock_idx) * trend * (1 + side_bias)
                profit = (3.0e10 + stock_idx * 8.0e9) * trend * (1 + side_bias)
                target = base_prices[stock_idx] * (1.15 + side_bias + 0.0008 * event_idx)
                # 部分更新放在收盘后，类会自动滚到下一交易日。
                hour = 17 if event_idx % 7 == 0 else 11
                consensus_frames[side].append(
                    {
                        "stock": stock,
                        "available_date": event_date + pd.Timedelta(hours=hour),
                        "forecast_period": pd.Timestamp(target_year, 12, 31),
                        "eps": eps * (1 + rng.normal(0, 0.015)),
                        "net_profit": profit * (1 + rng.normal(0, 0.012)),
                        "target_price": target * (1 + rng.normal(0, 0.01)),
                        "currency": "HKD",
                        "share_basis": "adjusted",
                    }
                )

    onshore_consensus_df = pd.DataFrame(consensus_frames["onshore"])
    offshore_consensus_df = pd.DataFrame(consensus_frames["offshore"])

    report_periods = pd.period_range("2021Q1", "2024Q4", freq="Q").to_timestamp(
        how="end"
    ).normalize()
    financial_rows: list[dict[str, object]] = []
    shareholder_rows: list[dict[str, object]] = []
    for stock_idx, stock in enumerate(stocks):
        for period_idx, report_period in enumerate(report_periods):
            scale = 1.0 + stock_idx * 0.23
            growth = (1.045 + stock_idx * 0.004) ** period_idx
            assets = 4.0e11 * scale * (1.025**period_idx)
            equity = 1.5e11 * scale * (1.03**period_idx)
            net_profit = 1.7e10 * scale * growth
            revenue = 1.3e11 * scale * (1.038**period_idx)
            cfo = net_profit * (1.05 + 0.02 * np.sin(period_idx + stock_idx))
            available = report_period + pd.Timedelta(days=43 + stock_idx)
            available += pd.Timedelta(hours=17 if period_idx % 5 == 0 else 10)
            financial_rows.append(
                {
                    "stock": stock,
                    "report_period": report_period,
                    "available_date": available,
                    "eps": 1.2 * scale * growth,
                    "net_profit": net_profit,
                    "revenue": revenue,
                    "operating_cash_flow": cfo,
                    "total_assets": assets,
                    "total_equity": equity,
                }
            )
            shareholder_rows.append(
                {
                    "stock": stock,
                    "report_period": report_period,
                    "available_date": available + pd.Timedelta(days=3),
                    "shareholder_count": (
                        150_000
                        + stock_idx * 12_000
                        - period_idx * (1_200 + stock_idx * 100)
                        + rng.normal(0, 1_200)
                    ),
                }
            )

    financial_df = pd.DataFrame(financial_rows)
    shareholder_df = pd.DataFrame(shareholder_rows)

    network_rows: list[dict[str, object]] = []
    for update_date in (dates[0], dates[120], dates[240]):
        for target_idx, target in enumerate(stocks):
            for related_idx, related in enumerate(stocks):
                if target == related:
                    continue
                network_rows.append(
                    {
                        "target_stock": target,
                        "related_stock": related,
                        "available_date": update_date + pd.Timedelta(hours=10),
                        "sc_weight": 0.2
                        + 0.08 * ((target_idx + related_idx) % 4)
                        + rng.uniform(0, 0.03),
                    }
                )
    analyst_network_df = pd.DataFrame(network_rows)

    surprise_rows: list[dict[str, object]] = []
    for stock_idx, stock in enumerate(stocks):
        for event_idx, event_date in enumerate(dates[8 + stock_idx :: 17]):
            surprise_rows.append(
                {
                    "stock": stock,
                    "available_date": event_date
                    + pd.Timedelta(hours=17 if event_idx % 4 == 0 else 13),
                    "title_positive_surprise": event_idx % 5 == 0,
                    "rating_upgrade": event_idx % 7 == 0,
                    "earnings_revision": 0.02 if event_idx % 3 == 0 else -0.01,
                    "upgrade_breadth": 0.15 if event_idx % 3 == 0 else -0.05,
                }
            )
    analyst_surprise_df = pd.DataFrame(surprise_rows)

    return {
        "price_df": price_df,
        "onshore_consensus_df": onshore_consensus_df,
        "offshore_consensus_df": offshore_consensus_df,
        "shareholder_df": shareholder_df,
        "southbound_flow_df": southbound_flow_df,
        "financial_df": financial_df,
        "analyst_network_df": analyst_network_df,
        "analyst_surprise_df": analyst_surprise_df,
    }


def main() -> None:
    """Production entry point: refuse to manufacture missing live inputs."""

    raise SystemExit(
        "HongKongFactorGenerator 仅接受真实 PIT 面板。请由 qmt_live_publisher.py "
        "提供 QMT 行情，并另行接入境内外一致预期、股东户数与分析师网络数据；"
        "缺少这些字段时不会生成演示或合成港股因子。"
    )


if __name__ == "__main__":
    main()
