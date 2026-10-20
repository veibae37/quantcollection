# 多维市场情绪共振因子

主程序：`multidimensional_sentiment_backtest.py`

## 核心口径

| 指标 | 输出列 | 买入条件 | 卖出条件 |
|---|---|---:|---:|
| 50ETF PCR | `PCR` | `>= 1.2` | `<= 0.5` |
| 融券相对增长分位数 | `Margin_Short_Percentile` | `>= 0.95` | `<= 0.1` |
| 中国波指 | `iVIX` | `<= 14` | 无 |
| 五年新高占比 | `New_High_Ratio` | `<= 0.001` | `>= 0.5` |
| IF 年化基差分位数 | `Basis_Percentile` | 无 | `>= 0.9` |
| 股债成交热度分位数 | `Stock_Bond_Percentile` | `<= 0.05` | `>= 0.95` |

阈值方向不是由数值大小猜测，而是通过 `buy_operator` 和 `sell_operator`
显式配置。权重会自动归一化，因此最终 `Sentiment_Score` 保持在 `[-1, 1]`。

五年滚动分位数默认使用 1260 个交易日，并把当日值排除在历史样本之外；
相同数值采用经验分布中位秩。默认要求完整 1260 日历史后才输出分位数，可通过
`--min-percentile-history` 调整预热期。

## 数据源与数据契约

运行以下命令生成 CSV 模板：

```powershell
.\.venv-qlib\Scripts\python.exe multidimensional_sentiment_backtest.py init-data
```

程序会通过 AKShare 自动获取并缓存：

- `benchmark.csv`：中证1000指数日线，优先新浪接口，东方财富备用。
- `margin_balance.csv`：上海和深圳市场融券余额之和。

以下数据因 AKShare 没有统一、稳定且完整的多年历史端点，使用标准 CSV 接口：

- `option_volume.csv`：`date,option_type,volume`，覆盖当日全部 50ETF 期权。
- `float_market_cap.csv`：`date,float_market_cap`。
- `ivix.csv`：`date,iVIX`，可接入 `ivix_index_pipeline.py` 持续生成的 VIX30。
- `new_high.csv`：`date,new_high_count,eligible_count`；也可提供
  `stock_daily.csv(date,symbol,close)`，程序会按 1260 日窗口重算。
- `basis.csv`：`date,Basis_Annualized`；也支持
  `date,futures_close,spot_close,expiry`。
- `stock_bond_turnover.csv`：`date,stock_turnover,bond_turnover`。

正式模式不会用模拟数据填补空缺。任何一维缺失、六指标交集不足 60 日，程序都会
终止并输出明确的数据覆盖错误。

## 正式运行

```powershell
.\.venv-qlib\Scripts\python.exe multidimensional_sentiment_backtest.py run `
  --data-dir data\sentiment `
  --start-date 2014-01-01 `
  --end-date 2026-08-25 `
  --output-dir outputs\sentiment_resonance_real
```

自定义阈值文件示例：

```json
{
  "pcr": {"buy_threshold": 1.25},
  "ivix": {"buy_threshold": 15.0},
  "stock_bond": {"sell_threshold": 0.9}
}
```

自定义权重文件必须包含六个键：

```json
{
  "pcr": 0.2,
  "margin": 0.2,
  "ivix": 0.1,
  "new_high": 0.2,
  "basis": 0.1,
  "stock_bond": 0.2
}
```

通过 `--thresholds-json thresholds.json --weights-json weights.json` 传入。

## 回测口径

- 当日收盘后才能知道 `Sentiment_Score`。
- `Score > 0.5`：次日开盘建仓或继续持有。
- `Score < -0.3`：次日开盘清仓。
- 两个阈值之间保持原仓位，形成滞回状态，避免每天无意义换手。
- 收益拆分为前收盘至当日开盘、当日开盘至收盘，正确处理次日开盘成交。
- 可用 `--transaction-cost-bps` 加入单边换仓成本。

输出包括：

- `Sentiment_Factor_Daily.csv`：六个指标值、六个方向信号和最终 Score。
- `Backtest_Daily.csv`：仓位、交易、策略/基准收益、净值和回撤。
- `Backtest_Metrics.json`：累计收益、年化收益、最大回撤等。
- `Data_Coverage.csv`：每个指标的覆盖起止日期与有效行数。
- `Sentiment_Backtest.png`：策略与中证1000净值，以及 Score/阈值图。

## 演示与测试

```powershell
.\.venv-qlib\Scripts\python.exe multidimensional_sentiment_backtest.py demo
.\.venv-qlib\Scripts\python.exe -m pytest tests\test_multidimensional_sentiment_backtest.py -q
```

`demo` 输出均标记为 `SYNTHETIC QA`，只能验证工程与图表，不能解释为历史策略表现。

## AKShare 真实数据一键回填

```powershell
.\.venv-qlib\Scripts\python.exe sentiment_akshare_downloader.py all `
  --data-dir data\sentiment `
  --start-date 2019-01-01 `
  --workers 6
```

下载器支持断点续传，也可以分别运行 `daily`、`basis`、`new-high`、`ivix`
和 `audit`。其中 PCR 使用上交所 510050 期权每日统计；流通市值、股票成交额和
债券成交额合并沪深交易所；IF 主力按每日成交量最大合约确定；五年新高使用
1260 个交易观察期，并纳入可获取的退市股票以减轻生存者偏差。正式数据质检结果
写入 `data/sentiment/data_quality_report.csv` 和 `.json`。

若融券余额原始序列存在交易所缺报，可在保持 1260 日滚动窗口的同时设置
`--min-percentile-history 1000`，要求窗口内至少 1000 个真实有效观测；程序不会
为缺报日伪造融券余额。
