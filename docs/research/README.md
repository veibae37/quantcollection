# Research evidence

[← 返回研究主页](../../README.md)

这里保存 README 引用的历史实验摘要，便于仓库读者检查日期、参数、成本与局限。整理日期：2026-10-20。此次文档改版未重新下载数据或重跑研究。

部分研究源码目前保留在本地，以文件名标注；文档与结果链接指向本次发布的文件。

## 真实页面截图

[研究页面截图](../assets/research-dashboard.png) 原文件为本地 `.runtime/backtest-production.png`，按原图复制，没有重绘或修改数值。它记录浏览器研究页的历史视图：

- 实际数据截止：2026-08-12；页面当时请求更新至 2026-08-27。
- 中证1000，训练 24 个月，测试 6 个月。
- MA 180、Vol 20、持有 5 日、Top 50。
- 佣金 2 bps、卖出印花税 5 bps、单边滑点 10 bps。
- 页面显示测试累计收益 −3.70%、最大回撤 −15.67%。

截图属于浏览器按所选市场训练集选参的实验。下方 MA 120 归档属于 CLI 跨股票池训练目标选参的另一次实验；两者选参范围和配置不同，不能将一个实验的截图作为另一个实验数值的证明。截图的原始采集时间未在源文件内记录，因此这里只声明其可见的数据日期。

## ① MA × Vol 归档

[ma-vol-run.json](ma-vol-run.json) 来源：`.runtime/ma-vol-walkforward/run-summary.json`。

保留原始运行的训练/测试区间、选参说明、股票池诊断、费用与完整测试指标；仅将机器绝对路径改成仓库相对路径。它使用本地 Qlib 2026-08-12 快照。README 展示的百分数为 JSON 小数转换后的四舍五入值。

该 CLI 实验按跨股票池训练目标选出 MA 120 / Vol 20 / 持有 5 日 / Top 50。中证1000为 Qlib 逐时点成分区间，中证2000和微盘为流动性代理池。一次留出区间的表现不足以证明跨时期稳定性；当前源代码与历史归档之间也可能存在后续修改，精确复现还需固定代码版本与原始数据快照。

## ② 情绪回测归档

[sentiment-metrics.json](sentiment-metrics.json) 来源：`outputs/market_sentiment_daily/Backtest_Metrics.json`，逐字段原样导出。

- 2022-12-01—2026-09-18，923 个交易日，六因子完整观测 668 行。
- `is_synthetic=false`；`trade_count=0`；`transaction_cost_bps=0`。
- 默认进入阈值 0.5、退出阈值 −0.3，策略净值平坦对应没有交易。
- 该归档中的 `margin` 阈值沿用旧共振实验口径；每日看板后来使用融资强度。应连同专属文档阅读，不将两者解释为相同指标版本。

这是无交易的历史回测记录，不能用于证明收益、有效风控或非零成本下的可交易性。

## ③ 中国波指的实现与数据口径

本模块提供计算实现、数据说明和测试入口；本次整理未新增波指实测结果或性能结论。

- `../../ivix_index_pipeline.py`与[算法说明](../../IVIX_ALGORITHM_COMPARISON.md)：自行计算 30 日、60 日隐含波动率及期限利差，保留报价口径与质量字段。
- `../../generate_china_vix_kline.py`与[使用说明](../../CHINA_VIX_KLINE_README.md)：使用公开 50ETF QVIX 历史日线作为观察代理，不与本地 CIVIX 拼接。
- `../../tests/test_ivix_index_pipeline.py`与`../../tests/test_generate_china_vix_kline.py`：覆盖计算和数据处理的工程检查，测试通过不代表指标有预测能力。

本地 CIVIX 的 15 分钟及日 K 线需要实际日内采集点；只有收盘数据时，不能据此恢复日内高低点。CIVIX 为研究实现，不是交易所官方发布指数。

## ④ C801 因子归档

[c801-metrics.json](c801-metrics.json) 来源：`.runtime/xalpha-real-run/factor-backtests/03-C801-Factor_C801_Seed_v1.metrics.json`。

保留原始因子代码、股票池、回测期、费用、质量诊断、IC、分组和组合指标及原有警告；移除机器本地输出路径字段 `artifacts`。回测区间为 2021-01-04—2026-07-31。

该次完整管线运行的研报日期覆盖 2023-02-06—2026-08-13，部分材料晚于回测起点，因此属于回溯性机制检验。该因子归档的 `exposure_coverage=0`、`neutralization=partial_exposure_with_explicit_fallback`；不能宣称已完成完整行业/市值中性化。质量门和 IC 指标亦不能代替独立样本外评估。

## 访问与复现

README 中的在线链接沿用仓库既有 Vercel 地址；页面的实时可达性与数据新鲜度须以实际访问为准。此处归档可直接在仓库内阅读。

原始行情、本地研究记忆和运行目录没有随本次文档改版导出。重新运行需要自行准备相应数据、授权和依赖，参见[运行手册](../OPERATIONS.md)。合成数据自检与真实历史评估应始终分开。
