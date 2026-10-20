# CIVIX 算法说明：与 quant-learning 225.md 的差异

## 结论

本项目保留了 225.md 的核心思想——用 50ETF 期权复制方差互换、计算各到期月隐含方差，再插值成固定期限波动率——但不直接复用其中的实现。225.md 是 2015 年优矿/Python 2 环境中的教学代码，存在一个明确的 K0 定价笔误，并且没有完整实现现代 Cboe 的流动性筛选和日内分钟级 TTM。

改进后的主指数命名为 **CIVIX**：

- `CIVIX = VIX30`，单位为年化波动率点，例如 25.3 表示 25.3%。
- `VIX60` 是伴随期限指标，不与 CIVIX 混合。
- `Term_Spread = CIVIX - VIX60`；大于 0 表示期限结构倒挂。
- 本指数是自行复刻指标，不是上海证券交易所官方发布指数。

参考资料：

- [quant-learning 225.md](https://github.com/apachecn/quant-learning/blob/master/docs/225.md)
- [Cboe VIX Methodology](https://cdn.cboe.com/resources/vix/VIX_Methodology.pdf)
- [AKShare 期权数据接口](https://akshare.akfamily.xyz/data/option/option.html)

## 算法逐项比较

| 环节 | 225.md | 原始 `ivix_sentiment.py` | 本次改进 |
|---|---|---|---|
| 日线价格 | 期权收盘价 | 收盘价；若有 BBO 则取中间价 | 日线使用收盘价；日内强制整张曲面统一使用 BBO 中间价，禁止同一曲面混用实时 BBO 与陈旧收盘价 |
| 日内价格 | 买一/卖一中间价 | 尚无独立日内入口 | 新增 `cal_snapshot_ivix`，支持真实时间戳和 BBO |
| TTM | `(expiry-date)/365`，日内仍按整天 | 日线自然日/365 | 到上交所 ETF 期权到期日 15:00 的实际秒数，除以 365×24×3600 |
| SHIBOR | 三次样条后直接代入 `exp(rT)` | 自然三次样条，并将简单年利率转连续复利 | 保留原改进；超出曲线范围使用边界值，避免三次样条外推爆炸 |
| 远期价 F | 最小 `abs(Call-Put)` 行权价，通过平价关系计算 | 相同 | 相同，并在重复/调整合约中优先保留成交量较高者 |
| K0 | F 下方行权价；代码将 `(Call + Call)/2` 写入 K0 | 正确使用 `(Call + Put)/2` | 保留正确实现；F 恰好等于行权价时按 Cboe 取“等于或紧邻下方” |
| OTM 边界 | Call `K>F`、Put `K<F`，然后再尝试写 K0 | Call `K>K0`、Put `K<K0`、K0 均价 | 保留正确 K0 边界；BBO 模式从 K0 向两翼扫描 |
| 零买价规则 | 未实现 | 未实现 | 按 Cboe：单个零买价剔除；同一翼遇到两个连续零买价后停止向外纳入 |
| Delta K | 在全部 Call/Put 配对行权价上计算 | 在最终 OTM 行权价上计算 | 保留最终有效行权价计算，避免被已剔除行权价扭曲 |
| VIX30 到期月 | 第 1/2 到期月，临近到期时顺延 | 独立寻找包围 30 日的两个到期月 | 保留严格包围目标期限；不允许无提示外推 |
| VIX60 到期月 | 固定第 2/3 到期月，未验证是否包围 60 日 | 独立寻找包围 60 日的到期月 | 保留严格包围 60 日；期权月份不足时明确报错 |
| 异常处理 | `except:` 后静默删日 | 明确异常 | 增加报价口径、最少 OTM 数、最大中位相对价差、跳过到期月详情 |
| 日内存储 | 每 60 秒覆盖/追加单日 CSV | 无 | 幂等累计 `CIVIX_points.csv`，再聚合 15 分钟和日 OHLC |
| 可视化 | Matplotlib 折线图 | 控制台输出 | 自包含 Plotly 日 K、15 分钟 K；同时显示 VIX60 和期限利差 |

### 225.md 中最重要的实现问题

其 K0 代码为：

```python
(opt_call['price'][strike_ref] + opt_call['price'][strike_ref]) / 2.0
```

第二项应为 Put。这个笔误会把 K0 价格设成 Call 价格，而不是 Call/Put 均价。深度实值/虚值不对称时会直接影响离散积分。

此外，225.md 先用 `K > F` 和 `K < F` 选 OTM，再向一个切片对象写 K0。旧版 Pandas 的链式赋值行为不稳定；改进代码直接构造 K0 行并合并，不依赖链式赋值。

## 数据集与 K 线定义

### 原始点

`CIVIX_points.csv` 每行对应一次完整期权曲面的计算：

- `timestamp`：Asia/Shanghai 交易所本地时间。
- `CIVIX/VIX30`：固定 30 日年化隐含波动率点。
- `VIX60`：固定 60 日年化隐含波动率点。
- `Term_Spread`：CIVIX−VIX60。
- `Quote_Basis`：`bid_ask_mid` 或 `close`。
- `Data_Quality`：报价质量状态。
- `source/is_synthetic`：来源及真实/演示标记。

### 15 分钟 K

`CIVIX_15min.csv` 使用每个连续交易时段内的采集点聚合：

- 上午从 09:30 起每 15 分钟一根；下午从 13:00 重新起算。
- 午休不制造空 K 线。
- 11:30 和 15:00 的边界点分别归入 11:15、14:45 开始的最后一根 K。
- 一分钟轮询时，正常每根 K 约有 15 个观测；`point_count` 可用于判断是否缺采。

### 日 K

`CIVIX_daily.csv` 从当天全部真实日内 CIVIX 点聚合 Open/High/Low/Close。因此：

- 只有启动日内采集器，才可能得到真实日内高低点。
- 单独拿期权日收盘价只能生成日收盘 CIVIX，不能凭空还原当天 Open/High/Low。
- 若机器中途关机，日 K 仍可生成，但 `point_count` 会显示覆盖不足。

## 每个交易日运行

安装公共依赖：

```powershell
pip install -r requirements-ivix.txt
```

MiniQMT 是首选真实数据源，因为它提供成批、同一时点的买一/卖一。登录 MiniQMT 后运行：

```powershell
.\run_ivix_trading_day.ps1 -Source qmt -IntervalSeconds 60
```

如果没有 MiniQMT，可使用东方财富公开行情作为降级源：

```powershell
.\run_ivix_trading_day.ps1 -Source eastmoney -IntervalSeconds 60
```

建议用 Windows 任务计划程序在每个工作日 09:25 启动上述脚本。脚本仅在 09:30–11:30、13:00–15:00 采集，并在 15:05 后退出；节假日数据源无有效报价时不会伪造数据。

输出文件：

```text
outputs/ivix_index/CIVIX_points.csv
outputs/ivix_index/CIVIX_15min.csv
outputs/ivix_index/CIVIX_daily.csv
outputs/ivix_index/CIVIX_15min.html
outputs/ivix_index/CIVIX_daily.html
outputs/ivix_index/latest_parameters.json
```

演示和真实数据禁止写入同一个目录。真实采集时使用新的输出目录，或先移动演示目录。

## 生产限制

- 东方财富/AKShare 属于公开数据适配层，不保证逐笔同步、历史分钟回补或永久接口兼容；正式交易研究应优先使用上交所授权行情或 MiniQMT。
- 15 分钟历史无法仅靠 AKShare 的“只能返回当天分钟数据”接口完整回补；必须每日持续采集，或接入拥有历史期权 BBO 的供应商。
- CIVIX 是波动率风险中性预期，不是标的价格方向预测。`Panic_Buy_Signal` 是规则型观察信号，不等同于交易指令。
