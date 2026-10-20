# 中金风格左侧择时引擎

主程序：`cicc_leftside_timing_engine.py`

## 日常运行

```bat
:: 更新真实数据、打印报告并导出 JSON
run_cicc_leftside_timing.cmd

:: 指定截止日，只用已有缓存计算
python cicc_leftside_timing_engine.py --date 2026-09-01 --export-json

:: 指定截止日并更新数据
python cicc_leftside_timing_engine.py --update --date 2026-09-01 --export-json
```

默认 JSON：`outputs/cicc_leftside_timing/latest.json`；原始缓存位于
`data/timing_cache/`。网络不可用时不覆盖旧缓存，也不会生成模拟数据。

全市场当日截面优先调用 AkShare/东方财富；若该接口断连，程序会自动按本地股票池
批量读取腾讯真实行情。两条路径都执行成交额大于零（停牌剔除）、ST 名称剔除和
上市超过 5 个交易日过滤，并将实际来源写入缓存。

## 首次初始化前后成交额差异

严格回溯需要历史 ST/停牌事件文件。文件可采用稀疏格式，只列出应剔除的事件：

```csv
date,symbol,is_st,suspended
2024-01-03,000004,true,false
2024-01-04,000004,true,false
2024-01-05,600000,false,true
```

然后运行：

```bat
python cicc_leftside_timing_engine.py --update --bootstrap-cross-section ^
  --stock-status-file data/timing_cache/stock_status_history.csv.gz --export-json
```

若没有历史状态文件，可显式使用
`--allow-degraded-st-history` 初始化，但 JSON 会保留质量警告；程序绝不会把该结果标为严格口径。

## 估值历史限制

当前 AkShare 的沪深300 PE/PB 接口返回的是自 2005 年以来的月末序列，而不是 1250
个真实日频观测。程序会把新数据持续合并到
`data/timing_cache/csi300_valuation.csv`，但在 PE/PB 配对历史少于 750 个真实交易日时，
估值分位和 ERP 分位显示“不可用”。可向该缓存导入真实历史，列格式为：

```csv
date,pe_ttm,pb,source
2021-01-04,15.23,1.61,licensed_real_source
```

禁止用插值、常数或随机数补足历史。

## 口径说明

- 五年窗口 1250 日，至少要求 750 个有效观测；完整窗口下分位即 `Rank/1250`。
- 当前不足 1250 日但达到 750 日时，使用有效样本数作为分母，保持真正的百分位定义。
- 指数成交额取腾讯指数日线的真实成交额字段，不用成交量或价格近似。
- 附件示例中的“顶底阻力 0.34=看多”“量价背离 0.19=看多”与书面阈值冲突；程序以书面阈值为准。
- `Diff=价下成交额-价上成交额` 的经济含义通常是数值越高、下方筹码支撑越强，和书面
  “高分位看空、低分位看多”方向存在解释冲突。当前仍严格执行书面阈值，待研究口径确认后再反转。
- JSON 固定写入 `data_mode=real`、`synthetic_data=false`，并保留每项指标的数据日期和警告。
