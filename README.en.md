<div align="center">

[中文](README.md) · [English](README.en.md)

<img src="docs/assets/research-header.svg" width="100%" alt="veibaequant — Quantitative Research & Data Analytics" />

# veibaequant

**Quantitative Research & Data Analytics**

By **veibaequant** · [@veibae37](https://github.com/veibae37)<br />
Notes and experiments on Chinese equity and options markets.

[Website](https://quantcollection-aa5n.vercel.app/) · [Selected Research](#selected-research) · [Profile](https://github.com/veibae37) · [Explore the Lab](#explore-the-lab)

---

[Selected Research](#selected-research) · [My Contribution](#my-contribution) · [Data and Evaluation](#data-and-evaluation) · [References](#references) · [License](#license)

</div>

> **Research notes**<br />
> Each study includes its question, method, evidence and limitations. Historical backtests, retrospective studies and checks using synthetic data are identified separately. Results refer to the stated data version and parameters.

Some research source files are currently kept locally and are shown as filenames below. Linked technical notes and archived results are available in this repository.

## Selected Research

### ① Stock Selection and Out-of-Sample Evaluation
**Moving averages and volatility**

- **Question:** Can a moving average signal with a low volatility filter improve out-of-sample portfolio performance after trading costs?
- **Method:** Use historical Qlib OHLCV data and membership intervals to construct signals. The CLI defaults to 24 months of training followed by 6 months of testing. Parameters are selected on training data, with signals formed after the close and executed at the next session's open.
- **Evidence:** [Interactive backtest](https://quantcollection-aa5n.vercel.app/backtest) · `ma_vol_walkforward_backtest.py` · [Archived results](docs/research/ma-vol-run.json) · `tests/test_ma_vol_walkforward_backtest.py`.
- **Limitations:** The archived run has one six-month holdout period. The CSI 2000 and microcap pools are based on lagged liquidity measures. Changing parameters after reviewing test results is exploratory and requires a further untouched sample.

<details>
<summary><strong>Archived run and reproduction</strong></summary>

The archived data ends on **2026-08-12**. Training covers **2024-02-19 to 2026-02-11**, followed by testing from **2026-02-12 to 2026-08-12**. The selected settings are MA 120 / Vol 20 / 5-day holding period / Top 50. The CSI 1000 portfolio returned about **+3.72%** in the test period, with a maximum drawdown of **−10.43%**. Returns for the CSI 2000 proxy and microcap proxy were **−12.24%** and **−10.61%**, respectively. Results differed across the three pools.

These figures come from a fixed CLI run. Its costs and full results are recorded in the [archived JSON](docs/research/ma-vol-run.json).

With a local Qlib dataset prepared, run this command from the repository root:

```powershell
python ma_vol_walkforward_backtest.py --provider-uri "C:\qlib_data\cn_data" --train-months 24 --test-months 6 --output-dir .runtime/ma-vol-walkforward
```

This evaluates the data you supply. Reproducing the archived figures also requires the same historical data version.

</details>

### ② Market Sentiment
**Six indicators and timing evaluation**

- **Question:** Can options activity, leverage, market breadth, futures basis and stock–bond turnover help describe market conditions and support a timing signal?
- **Method:** Combine six indicator signals using historical rolling percentiles. Distinguish complete observations for the same date from the latest available value of each indicator. Volatility is one input; its calculation and data sources are described separately below.
- **Evidence:** [Sentiment page](https://quantcollection-aa5n.vercel.app/market-sentiment) · [Daily updates](MARKET_SENTIMENT_DAILY_README.md) · [Backtest method](SENTIMENT_RESONANCE_README.md) · [Archived metrics](docs/research/sentiment-metrics.json).
- **Limitations:** The archived backtest covers 923 trading days from 2022-12-01 to 2026-09-18, with 668 complete six-indicator observations. It produced **no trades** under the default thresholds and used zero transaction costs. This does not establish trading value. The daily page uses margin financing, while the earlier resonance experiment uses securities lending; the definitions should be read separately.

### ③ China Volatility Index
**CIVIX calculation and QVIX history**

- **Question:** How can 50ETF option quotes be used to estimate implied volatility at fixed maturities and observe its term structure and intraday changes?
- **Method:** The local CIVIX implementation uses variance swap replication to calculate 30-day implied volatility, alongside a 60-day measure and their spread. Quote timestamps, price conventions and quality flags are retained. Actual observations are aggregated into 15-minute and daily bars. Public 50ETF QVIX daily bars provide a separate historical proxy.
- **Evidence:** `ivix_index_pipeline.py` · [Method and implementation notes](IVIX_ALGORITHM_COMPARISON.md) · [Historical chart notes](CHINA_VIX_KLINE_README.md) · `generate_china_vix_kline.py` · `tests/test_ivix_index_pipeline.py` · `tests/test_generate_china_vix_kline.py`.
- **Limitations:** CIVIX is a research implementation rather than an official exchange index. QVIX uses a different methodology and is kept separate from CIVIX. Closing data alone cannot recover intraday highs and lows. Stale quotes, bid–ask spreads and available expiries can affect the calculation. Implied volatility alone does not indicate market direction.

### ④ From Research Reports to Factors
**Text processing, factor generation and backtesting**

- **Question:** How can a mechanism described in a research report become an executable factor while retaining a record of its sources and evaluation?
- **Method:** Extract passages from public or licensed texts and classify them using the A/B/C taxonomy. Macro Brain plans research directions, and Micro Brain produces restricted OHLCV factor code. Syntax, mechanism alignment, numerical output and sensitivity to future data are checked before Qlib evaluation and feedback are recorded.
- **Evidence:** [Research engine overview](https://quantcollection-aa5n.vercel.app/#research-engine) · `xalpha_real_pipeline.py` · `rma_absorption.py` · `micro_brain.py` · [Archived C801 metrics](docs/research/c801-metrics.json) · [Operating guide](docs/OPERATIONS.md#xalpha-研报吸收rma).
- **Limitations:** Reports published after the backtest begins support retrospective analysis only. The archived C801 run has **zero coverage** for industry and market capitalisation exposures, with a disclosed fallback for neutralisation. Passing code checks does not establish predictive value. Synthetic panels are used for engineering checks. The framework draws on XALPHA v2, listed in [References](#references).

## My Contribution

Work in this repository covers data preparation, research implementation, evaluation and presentation:

- **Data processing:** Integrate Wind, MiniQMT, public quotes and local Qlib data, recording sources, update times, missing fields and fallback status. See the `a_stock_data_source.py` and `sentiment_akshare_downloader.py`.
- **Research implementation:** Implement stock selection, sentiment, CIVIX, options scanning and report-to-factor workflows, with their parameters and timing assumptions. See [stock selection](a_share_selector.py), `ivix_index_pipeline.py` and the `rma_pipeline.py`.
- **Evaluation:** Separate training and testing, apply trading costs, handle historical membership and check whether future data alters past signals. Outputs include portfolio value, drawdown, turnover and Rank IC. See the `qlib_backtest_visualizer.py` and [tests](tests/).
- **Presentation:** Organise results into research pages and publish read-only market snapshots through a local publisher and validator. See the [web pages](public/), [publisher](qmt_live_publisher.py) and [snapshot validation](live_snapshot_store.py).

## Data and Evaluation

### Data Sources

Equity and ETF programs use Wind, MiniQMT or public interfaces according to their configuration. Historical factor evaluation uses local Qlib snapshots. Sentiment inputs retain their exchange or AKShare source, and research texts come from public sources or licensed exports. Source priorities differ by program; the actual output records the source used.

[Sentiment data contract](data/sentiment/README.md) · [Hong Kong data requirements](https://quantcollection-aa5n.vercel.app/hk-factor-lab) · [Evidence and versions](docs/research/README.md)

Some linked technical notes are in Chinese.

### Information Availability

The observation date and the date information became available need to be checked separately. Closing signals are executed at the next session's open. The sentiment page reports each indicator's data date and whether an earlier value is carried forward. Industry, market capitalisation, membership and report dates need to match the decision date. Missing analyst or point-in-time data is left unavailable or handled through a disclosed fallback.

### Training and Testing

Training data is used for parameter selection; test data is used for evaluation. Manual parameter changes, repeated inspection of a holdout period and selection of report mechanisms based on results are exploratory. Rank IC, quantile returns and portfolio backtests in a Qlib report do not by themselves constitute independent out-of-sample evidence.

### Costs and Risk

The archived MA × Vol run uses **2 bps** commission and **10 bps** slippage on each side, plus **5 bps** stamp duty on sales. The sentiment archive uses **zero costs** and needs evaluation with nonzero costs. Options experiments also account for book depth, execution across four legs, exercise and financing costs. Drawdown, turnover, capacity, membership coverage and proxy definitions should be assessed. Cost assumptions differ across experiments.

<sub>These costs are experiment settings. Historical results are research records, not a promise of returns. Dataset permissions, completeness and publication delays also need to be checked.</sub>

## Explore the Lab

**Navigation:** [Research and tools](https://quantcollection-aa5n.vercel.app/) · [English website](https://quantcollection-aa5n.vercel.app/en) · [Local setup and deployment](docs/OPERATIONS.md)

<details open>
<summary><strong>01 / Equities, portfolios and out-of-sample evaluation</strong></summary>

- [A-share factor selection](a_share_selector.py) · [Factor portfolios](quant_portfolio_system.py) · [TW half-Kelly sizing](tw_kelly_strategy.py).
- `ma_vol_breakout_alpha.py` · `ma_vol_walkforward_backtest.py` · `build_web_backtest_bundle.py`.
- `qlib_backtest_visualizer.py` · `xalpha_index_backtest.py` · `xalpha_market_comparison.py` · `xalpha_c801_csi1000_microcap.py`.
- [Hong Kong factor page](https://quantcollection-aa5n.vercel.app/hk-factor-lab) · [Factor implementation](hong_kong_factor_generator.py).

</details>

<details>
<summary><strong>02 / Market sentiment and timing</strong></summary>

- `daily_market_sentiment.py` · `multidimensional_sentiment_backtest.py` · `sentiment_akshare_downloader.py`.
- `daily_qrs_timing_pipeline.py` · [Left-side timing model](CICC_LEFTSIDE_TIMING_README.md) · [ETF turnover monitor](bigmoneyflow.py).

</details>

<details>
<summary><strong>03 / China volatility index and volatility data</strong></summary>

- `ivix_index_pipeline.py` · [Method notes](IVIX_ALGORITHM_COMPARISON.md) · `run_ivix_trading_day.ps1`.
- [China volatility history](CHINA_VIX_KLINE_README.md) · `generate_china_vix_kline.py` · [QVIX for other ETF options](OPTION_QVIX_KLINE_README.md).

</details>

<details>
<summary><strong>04 / Options and intraday studies</strong></summary>

- [ETF options scanner](option_market_scanner.py) · [Box spreads](boxoption2.py) · `fcb2016_strategy.py`.
- `intraday_vwap_orb.py` · [QMT intraday half-Kelly](QMT_INTRADAY_KELLY_README.md) · [TradingView strategy](TWrandomf.pine).

</details>

<details>
<summary><strong>05 / Reports, factor generation and research memory</strong></summary>

- `rma_sources.py` · `rma_taxonomy.py` · `rma_absorption.py` · `rma_pipeline.py`.
- `macro_brain.py` · `micro_brain.py` · `xalpha_operators.py` · `xalpha_lineage.py`.
- `xalpha_real_pipeline.py` · `xalpha_update_qlib_snapshot.py` · `xalpha_micro_diagnostic_report.py`.

</details>

<details>
<summary><strong>06 / Data infrastructure and local programs</strong></summary>

- `wind_data_source.py` · `a_stock_data_source.py` · [MiniQMT publisher](qmt_live_publisher.py) · `qmt_close_refresh.py` · [Snapshot storage](live_snapshot_store.py).
- [Local web server](dev_server.py) · [Program registry](web_runner.py) · [API](api/) · [Repository files](https://github.com/veibae37/quantcollection).
- Local trading and strategy entry points: [QMT connection](connect.py) · [Random forest strategy](ML.py) · [Kelly executor](miniqmt_kelly_executor.py). Read each source file for its purpose and runtime requirements.

</details>

## References

- [XALPHA: A Memory-Driven AI Quant Researcher for Hypothesis-to-Code Alpha Discovery, v2](https://arxiv.org/abs/2607.08332v2): the reference for report abstraction, research memory and hypothesis-to-code workflows in this implementation.
- [Microsoft Qlib](https://github.com/microsoft/qlib): tools for quantitative research, factor evaluation and portfolio backtesting.
- [Cboe VIX Methodology](https://cdn.cboe.com/resources/vix/VIX_Methodology.pdf): the methodological reference for implied variance and fixed-maturity volatility.
- [AKShare options documentation](https://akshare.akfamily.xyz/data/option/option.html): documentation for public market data interfaces.
- [CIVIX implementation notes](IVIX_ALGORITHM_COMPARISON.md): local method comparisons, the earlier teaching implementation and data quality requirements.

## License

This repository currently **has no declared open-source license** and contains no project-level LICENSE file. Permission to use or redistribute the code is subject to an explicit license from the author. Third-party dependencies, data, reports and cited material remain subject to their respective terms.

---

<div align="center">
<sub>veibaequant · Quantitative Research &amp; Data Analytics</sub><br />
<a href="https://quantcollection-aa5n.vercel.app/">Website</a> · <a href="https://github.com/veibae37">Profile</a> · <a href="#selected-research">Back to Research</a>
</div>
