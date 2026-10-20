# A股六维市场情绪：每日一键更新

双击 `run_market_sentiment_daily.cmd`，程序会依次：

1. 确认最新已收盘交易日；
2. 增量更新 PCR、融资余额、CIVIX、五年新高、IF 基差和股债成交额；
3. 按原六维权重与阈值重新计算；
4. 同步更新上证综指、沪深300和创业板指的 QRS 择时值；
5. 把情绪与 QRS 一并写入网页数据和本地审计结果。

结果文件：

- `outputs/market_sentiment_daily/latest_sentiment.json`
- `outputs/market_sentiment_daily/Sentiment_Factor_Daily.csv`
- `public/market-sentiment-data.json`
- `outputs/qrs_timing/latest_qrs.json`

## 常用命令

```bat
:: 正常每日更新
run_market_sentiment_daily.cmd

:: 网络不可用时，仅用已有真实缓存重算
run_market_sentiment_daily.cmd --no-refresh

:: 指定交易日
run_market_sentiment_daily.cmd --end-date 2026-09-01

:: 已安装官方 Node.js Vercel CLI 时，更新后同时发布网页
run_market_sentiment_daily.cmd --deploy
```

正式同日分要求六个正权重因子在同一交易日全部可用。按当前每日口径，当天尚未发布或质量不足的维度会自动采用前一有效交易日数据，并在网页逐项标出实际数据日期；如果回退后覆盖仍不足 60%，才显示“数据不足”。QRS 是独立的指数择时/仓位覆盖层，不参与六因子情绪分加权，也不是成分股选股型指数增强模型。程序不会混入演示或合成数据。
