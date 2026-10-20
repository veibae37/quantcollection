# 沪深300与双创ETF期权 QVIX 日K

## 一键生成

在本目录双击 `generate_option_qvix_kline.cmd`，或在命令行运行：

```cmd
generate_option_qvix_kline.cmd
```

默认联网刷新并生成最近三个月的四个自包含 HTML：一个总览，以及沪深300ETF、科创板ETF、创业板ETF三个单品图。HTML 已内嵌 Plotly，可直接复制到其他电脑离线打开。

每次成功生成新图后，程序会自动删除输出目录中以前月份窗口的 HTML 和窗口 CSV，只保留本次图表及三个稳定的 `*_history.csv` 历史缓存。历史缓存体积很小，并且是 `--no-refresh` 离线运行所必需的。若联网或生成失败，旧图不会被删除。

常用参数：

```cmd
:: 最近六个月
generate_option_qvix_kline.cmd --months 6

:: 截止到指定日期
generate_option_qvix_kline.cmd --as-of 2026-08-28

:: 只生成科创板与创业板
generate_option_qvix_kline.cmd --products kcb cyb

:: 网络不可用时使用上次缓存
generate_option_qvix_kline.cmd --no-refresh
```

输出目录：`outputs\option_qvix_3m`。

文件名中的 `3M`、`6M` 会跟随 `--months` 自动变化；旧窗口文件在新图生成成功后自动清理。

## 数据和口径

- 数据来自 optbbs 公共日度 QVIX 历史表，与 AKShare 的 `index_option_300etf_qvix`、`index_option_kcb_qvix`、`index_option_cyb_qvix` 同源。
- 三个品种分别使用自己的期权标的计算，程序不会把科创板与创业板期权链混合成一个不存在的“合成双创波指”。
- 沪深300这里是沪深300ETF期权 QVIX，不是中金所 IO 沪深300股指期权。当前公开表中的 IO 历史列返回公式错误值，程序不会用 ETF 序列冒充 IO。
- “后三个月”若指未来三个月，真实 K 线尚不存在，程序不会生成或伪造。默认窗口是数据源最新交易日向前滚动三个月。
