# QMT 日内概率森林 + 半凯利建仓

`intraday_vwap_orb.py` 是独立的 1 分钟 VWAP/ORB 信号函数；
`qmt_intraday_kelly_entry.py` 将它接入现有 A 股选股、概率森林、半凯利调仓和 MiniQMT。

## 运行前

1. 启动并登录 MiniQMT，保持极简模式/API 可用。程序发现 `1m`、`15m`、`1d` 本地历史不足时会调用 QMT 的补充历史接口一次；若券商行情权限不允许自动补齐，再在 QMT 客户端手工下载。
2. 在本目录的 `.env` 中确认：

```text
MINIQMT_PATH=C:\你的QMT目录\userdata_mini
MINIQMT_ACCOUNT_ID=你的资金账号
MINIQMT_SESSION_ID=952701
MINIQMT_ENABLE_LIVE_TRADING=disabled
MINIQMT_ENABLE_QMT_SELECTION_LIVE=disabled
```

3. 如当前环境缺少依赖：

```powershell
python -m pip install pandas numpy requests
```

## 建议先做模拟运行

在交易日 10:00 之后运行一次：

```powershell
python qmt_intraday_kelly_entry.py
```

默认不会下单，只输出 `DRY_RUN` 结果。`entry_decisions` 会显示每只待买股票的两个下跌概率、VWAP、开盘区间高点、放量条件和最终是否允许买入。

默认规则与本次要求一致：三个 15 分钟和三日两个下跌概率**同时**超过 68% 才禁买。若希望任一周期超过 68% 就禁买，运行：

```powershell
python qmt_intraday_kelly_entry.py --risk-gate-mode either
```

运行测试：

```powershell
python -m unittest tests.test_intraday_vwap_orb tests.test_qmt_intraday_kelly_entry
```

## 确认后实盘

先查看模拟订单；确认账户、标的、数量和价格均正确后，把 `.env` 的实盘确认改为：

```text
MINIQMT_ENABLE_LIVE_TRADING=I_UNDERSTAND_LIVE_TRADING
```

然后执行：

```powershell
python qmt_intraday_kelly_entry.py --live
```

如果公共基本面快照不可用、程序改用 QMT 市场因子备用选股，还需同时设置：

```text
MINIQMT_ENABLE_QMT_SELECTION_LIVE=I_REVIEWED_QMT_MARKET_ONLY_SELECTION
```

并运行：

```powershell
python qmt_intraday_kelly_entry.py --live --allow-qmt-selection-live
```

每次命令只执行一轮。单只入选股无法补齐 15 分钟/1 分钟历史时会被记录到 `history_excluded_tickers` 并剔除，其余股票重新归一化权重；完整历史少于 5 只则整轮停止。最新 1 分钟 K 线超过 3 分钟、当前不在连续交易时段、分钟线/日线或概率数据缺失时，都会禁止该股票买入，但需要减仓的卖单仍保留。实盘前请先核对 QMT 当日可用资金、未成交委托和 A 股 T+1 限制。
