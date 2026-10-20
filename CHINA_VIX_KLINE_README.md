# 中国波指最近一个月日K

## 随时生成

在项目目录打开 PowerShell 或命令提示符，执行：

```powershell
.\generate_china_vix_kline.cmd
```

脚本会先在线更新 50ETF QVIX 历史日线，再取数据源最新日期往前一个月，生成：

```text
outputs/ivix_monthly/China_VIX_1M_daily.html
outputs/ivix_monthly/China_VIX_1M_daily.csv
outputs/ivix_monthly/China_VIX_history.csv
```

HTML 内置 Plotly，无网络也能打开和交互；可缩放、悬停查看 OHLC，也可用工具栏导出 PNG。

若临时无法联网，可用最近一次缓存生成：

```powershell
.\generate_china_vix_kline.cmd --no-refresh
```

也可以直接运行 Python，并指定截止日或更长窗口：

```powershell
.\.venv-qlib\Scripts\python.exe generate_china_vix_kline.py --as-of 2026-08-28
.\.venv-qlib\Scripts\python.exe generate_china_vix_kline.py --months 3
```

## 每天自动生成

可以在 Windows“任务计划程序”中新建任务，在每个交易日 15:20 执行：

```text
powershell.exe -ExecutionPolicy Bypass -File "C:\Users\baby liu\Downloads\新建文件夹\generate_china_vix_kline.ps1"
```

“起始于”目录设置为：

```text
C:\Users\baby liu\Downloads\新建文件夹
```

## 口径说明

- 图中历史 OHLC 来自公开的 50ETF QVIX 日线，是之前本地 `CIVIX` 模型的历史代理。
- 本地 `CIVIX` 按 Cboe 方差互换方法自行计算；QVIX 与 CIVIX 口径接近但不完全相同，脚本不会把两者拼成一条日K。
- 中国波指反映期权市场隐含波动率，不预测 50ETF 或 A 股涨跌方向。
