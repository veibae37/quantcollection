<div align="center">

[中文](README.md) · [English](README.en.md)

<img src="docs/assets/research-header.svg" width="100%" alt="veibaequant — Quantitative Research & Data Analytics" />

# veibaequant

**Quantitative Research & Data Analytics**

作者：**veibaequant** · [@veibae37](https://github.com/veibae37)<br />
围绕中国股票与期权市场的探索和想法。

[访问网站](https://quantcollection-aa5n.vercel.app/) · [代表研究](#selected-research) · [个人主页](https://github.com/veibae37) · [探索实验室](#explore-the-lab)

---

[Selected Research](#selected-research) · [My Contribution](#my-contribution) · [Data and Evaluation](#data-and-evaluation) · [References](#references) · [License](#license)

</div>

> **研究说明**<br />
> 每项研究同时提供问题、方法、证据与局限。真实历史回测、回溯性机制检验和合成数据自检分别标记；结果以对应数据版本和参数为准。

部分研究源码目前保留在本地，下文以文件名标注。已公开的说明文档和归档结果可直接打开。

## Selected Research

### ① 选股与样本外评估
**均线与波动率选股**

- **研究问题 →** 均线趋势与低波动过滤能否在扣除交易成本后，改善不同股票池的样本外表现？
- **方法 →** 使用 Qlib 历史 OHLCV 与逐时点成分区间构造信号；CLI 默认以 24 个月训练、随后 6 个月测试，参数仅由训练集选择，收盘形成信号、下一交易日开盘执行。
- **证据入口 →** [交互回测](https://quantcollection-aa5n.vercel.app/backtest) · `ma_vol_walkforward_backtest.py` · [归档运行结果](docs/research/ma-vol-run.json) · `tests/test_ma_vol_walkforward_backtest.py`。
- **局限 →** 归档实验只有一个 6 个月留出区间；中证2000与微盘使用滞后流动性代理池。反复查看测试结果后改参属于探索性检验，尚需新的未触碰样本验证。

<details>
<summary><strong>查看归档实验与复现入口</strong></summary>

归档数据截至 **2026-08-12**：训练期为 **2024-02-19—2026-02-11**，测试期为 **2026-02-12—2026-08-12**；选中参数为 MA 120 / Vol 20 / 持有 5 日 / Top 50。中证1000测试期累计收益约 **+3.72%**、最大回撤约 **−10.43%**；中证2000代理与微盘代理的同期累计收益分别约 **−12.24%**、**−10.61%**。跨市场结果并不一致。

这些数字来自固定的 CLI 运行归档。费用参数和完整结果见[归档 JSON](docs/research/ma-vol-run.json)。

已准备真实 Qlib 本地数据时，可在仓库根目录运行：

```powershell
python ma_vol_walkforward_backtest.py --provider-uri "C:\qlib_data\cn_data" --train-months 24 --test-months 6 --output-dir .runtime/ma-vol-walkforward
```

此命令使用你提供的数据重新评估；复现归档数值还需要相同的历史数据版本。

</details>

### ② 市场情绪
**六维指标与择时评估**

- **研究问题 →** 期权交易、杠杆资金、市场宽度、期现基差与股债成交热度，能否共同描述市场风险状态，并形成可执行的择时信号？
- **方法 →** 构建六维情绪分与历史滚动分位数，区分同日完整值和逐因子最近可用值；波动率是其中一个输入，指数的计算与数据口径在下方单独说明。
- **证据入口 →** [市场情绪看板](https://quantcollection-aa5n.vercel.app/market-sentiment) · [每日更新说明](MARKET_SENTIMENT_DAILY_README.md) · [情绪回测口径](SENTIMENT_RESONANCE_README.md) · [归档指标](docs/research/sentiment-metrics.json)。
- **局限 →** 归档情绪回测在 2022-12-01—2026-09-18 共 923 个交易日中，六因子完整行仅 668 行，默认阈值下 **0 次交易**，成本设为 0 bps；该结果尚未证明信号具备交易价值。每日更新中的融资口径与旧共振实验的融券口径须分别阅读。

### ③ 中国波指
**CIVIX 计算与 QVIX 历史观察**

- **研究问题 →** 如何从 50ETF 期权报价计算固定期限的隐含波动率，并观察其期限结构和日内变化？
- **方法 →** 本地 CIVIX 按方差互换复制方法计算 30 日隐含波动率，同时计算 60 日指标与期限利差；保留报价时间、价格口径和质量标记，再由实际采集点聚合 15 分钟及日 K 线。另用公开 50ETF QVIX 日线提供历史观察，两条序列分开保存。
- **证据入口 →** `ivix_index_pipeline.py` · [方法与实现差异](IVIX_ALGORITHM_COMPARISON.md) · [历史 K 线说明](CHINA_VIX_KLINE_README.md) · `generate_china_vix_kline.py` · `tests/test_ivix_index_pipeline.py` · `tests/test_generate_china_vix_kline.py`。
- **局限 →** CIVIX 是自行实现的研究指标，并非交易所官方指数；QVIX 是历史代理，不能与 CIVIX 拼接成同一口径。缺少日内报价时不能还原真实日内高低点，报价陈旧、价差和到期月覆盖也会影响计算。隐含波动率本身不判断市场涨跌方向。

### ④ 研报到因子
**文本整理、因子生成与回测**

- **研究问题 →** 如何把研究文本中的机制假设转化为可执行因子，并保存从来源证据到实验结果的追溯关系？
- **方法 →** 对公开或已授权文本切片，按 A/B/C taxonomy 筛选与抽象；由 Macro Brain 规划方向、Micro Brain 生成受限 OHLCV 因子，经过 AST、机制对齐、数值和未来扰动检查，再进入 Qlib 评估与经验回写。
- **证据入口 →** [研究引擎介绍](https://quantcollection-aa5n.vercel.app/#research-engine) · `xalpha_real_pipeline.py` · `rma_absorption.py` · `micro_brain.py` · [C801 归档指标](docs/research/c801-metrics.json) · [实现与运行手册](docs/OPERATIONS.md#xalpha-研报吸收rma)。
- **局限 →** 晚于回测起点的研报只能支持回溯性机制检验；C801 归档的行业/市值暴露覆盖率为 **0**，使用了明确披露的中性化降级。代码通过质量门并不证明预测能力，合成面板只用于工程自检。研究框架参考 XALPHA v2，方法来源见 [References](#references)。

## My Contribution

本仓库的工作集中在将研究方法落到可检查的实现与证据上：

- **数据工程：** 接入 Wind、MiniQMT、公开行情与本地 Qlib 数据，记录来源、更新时间、缺失字段及降级状态；`a_stock_data_source.py`、`sentiment_akshare_downloader.py`。
- **研究实现：** 编写选股、情绪、CIVIX、期权扫描和研报因子管线，保留参数、信号时点与数据契约；[选股实现](a_share_selector.py)、`ivix_index_pipeline.py`、`rma_pipeline.py`。
- **评估与检查：** 实现训练/测试分离、成本扣除、逐时点成分处理及未来数据扰动检查，输出净值、回撤、换手与 Rank IC；`qlib_backtest_visualizer.py`、[测试目录](tests/)。
- **展示与交付：** 将实验结果组织为交互研究页，通过本地发布器与快照校验器向网站提供只读市场数据；[网页](public/)、[发布器](qmt_live_publisher.py)、[快照校验](live_snapshot_store.py)。

## Data and Evaluation

### 数据来源 · Source & Lineage

股票与 ETF 行情按程序配置使用 Wind、MiniQMT 或公开接口；历史因子评估读取本地 Qlib 快照；情绪指标保留交易所/AKShare来源；研报使用公开文本或授权导出。各程序的数据优先级不同，以实际输出的来源字段为准。

[情绪数据契约](data/sentiment/README.md) · [港股信息边界](https://quantcollection-aa5n.vercel.app/hk-factor-lab) · [归档证据与版本](docs/research/README.md)

### 信息时点 · As-of Availability

信号日期与可获得日期分别核查。收盘信号按下一交易日开盘执行；情绪看板逐项披露实际数据日期与沿用状态；行业、市值、成分与研报日期须与决策时点对齐。缺失分析师或 PIT 数据时，相关研究结果保持缺失或显式披露降级。

### 训练与测试 · Training and Testing

训练集负责参数选择，测试集只用于评估。浏览器手动改参、重复查看留出集、根据结果筛选研报机制，均需按探索性研究解释。Qlib 因子报告中的 Rank IC、分组收益与组合回测本身不等于独立样本外验证。

### 成本与风险 · Costs & Risk

MA × Vol 归档使用双边佣金 **2 bps**、卖出印花税 **5 bps**、双边各 **10 bps** 滑点；情绪归档成本为 **0 bps**，需要另做非零成本检验。期权实验还需考虑盘口深度、四腿执行、行权与融资成本。持续关注回撤、换手、容量、成分覆盖和代理池偏差；不同实验的费用口径不可直接混用。

<sub>上述费用为实验参数。历史结果用于研究记录，不构成收益承诺；各数据集仍需检查授权范围、完整性与发布滞后。</sub>

## Explore the Lab

**研究导航：** [全部研究与工具](https://quantcollection-aa5n.vercel.app/) · [English](https://quantcollection-aa5n.vercel.app/en) · [本地运行与部署](docs/OPERATIONS.md)

<details open>
<summary><strong>01 / 股票、组合与样本外评估</strong></summary>

- [A 股多因子选股](a_share_selector.py) · [市场因子组合](quant_portfolio_system.py) · [TW 半凯利](tw_kelly_strategy.py)。
- `ma_vol_breakout_alpha.py` · `ma_vol_walkforward_backtest.py` · `build_web_backtest_bundle.py`。
- `qlib_backtest_visualizer.py` · `xalpha_index_backtest.py` · `xalpha_market_comparison.py` · `xalpha_c801_csi1000_microcap.py`。
- [港股十二因子研究页](https://quantcollection-aa5n.vercel.app/hk-factor-lab) · [港股因子实现](hong_kong_factor_generator.py)。

</details>

<details>
<summary><strong>02 / 市场情绪与择时</strong></summary>

- `daily_market_sentiment.py` · `multidimensional_sentiment_backtest.py` · `sentiment_akshare_downloader.py`。
- `daily_qrs_timing_pipeline.py` · [左侧择时引擎](CICC_LEFTSIDE_TIMING_README.md) · [ETF 成交额监控](bigmoneyflow.py)。

</details>

<details>
<summary><strong>03 / 中国波指与波动率</strong></summary>

- `ivix_index_pipeline.py` · [算法说明](IVIX_ALGORITHM_COMPARISON.md) · `run_ivix_trading_day.ps1`。
- [中国波指历史 K 线](CHINA_VIX_KLINE_README.md) · `generate_china_vix_kline.py` · [其他 ETF 期权 QVIX](OPTION_QVIX_KLINE_README.md)。

</details>

<details>
<summary><strong>04 / 期权与日内实验</strong></summary>

- [ETF 期权市场扫描](option_market_scanner.py) · [盒式价差](boxoption2.py) · `fcb2016_strategy.py`。
- `intraday_vwap_orb.py` · [QMT 日内半凯利](QMT_INTRADAY_KELLY_README.md) · [TradingView 策略源文件](TWrandomf.pine)。

</details>

<details>
<summary><strong>05 / 研报、因子生成与研究记忆</strong></summary>

- `rma_sources.py` · `rma_taxonomy.py` · `rma_absorption.py` · `rma_pipeline.py`。
- `macro_brain.py` · `micro_brain.py` · `xalpha_operators.py` · `xalpha_lineage.py`。
- `xalpha_real_pipeline.py` · `xalpha_update_qlib_snapshot.py` · `xalpha_micro_diagnostic_report.py`。

</details>

<details>
<summary><strong>06 / 数据基础设施与本地程序</strong></summary>

- `wind_data_source.py` · `a_stock_data_source.py` · [MiniQMT 发布](qmt_live_publisher.py) · `qmt_close_refresh.py` · [快照存储](live_snapshot_store.py)。
- [本地网页服务](dev_server.py) · [程序注册表](web_runner.py) · [API](api/) · [全部根目录源文件](https://github.com/veibae37/quantcollection)。
- 本地交易与策略环境入口：[QMT 连接](connect.py) · [随机森林策略](ML.py) · [凯利执行器](miniqmt_kelly_executor.py)。运行条件与用途请先阅读对应源文件。

</details>

## References

- [XALPHA: A Memory-Driven AI Quant Researcher for Hypothesis-to-Code Alpha Discovery, v2](https://arxiv.org/abs/2607.08332v2)：研报抽象、研究记忆与假设到代码框架；本仓库实现以该版本为参考。
- [Microsoft Qlib](https://github.com/microsoft/qlib)：量化研究、因子评估与组合回测基础工具。
- [Cboe VIX Methodology](https://cdn.cboe.com/resources/vix/VIX_Methodology.pdf)：期权隐含方差与固定期限波动率的方法参考。
- [AKShare 期权数据文档](https://akshare.akfamily.xyz/data/option/option.html)：公开市场数据接口说明。
- [CIVIX 实现与算法差异](IVIX_ALGORITHM_COMPARISON.md)：本地方法核对、原教学实现来源与数据质量约束。

## License

本仓库目前**未声明开源许可证**，未包含项目级 LICENSE 文件。代码的使用与再分发授权以作者后续明确发布的许可为准；第三方依赖、数据、研报及引用材料遵循各自的许可与使用条件。

---

<div align="center">
<sub>veibaequant · Quantitative Research &amp; Data Analytics</sub><br />
<a href="https://quantcollection-aa5n.vercel.app/">Website</a> · <a href="https://github.com/veibae37">Profile</a> · <a href="#selected-research">Back to Research</a>
</div>
