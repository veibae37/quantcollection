# 本地运行与部署手册

[← 返回研究主页](../README.md)

本文件完整保留 README 改版前的运行、部署与研究管线说明。它记录各模块当时的配置口径；数据来源与降级策略以当前代码、实际输出及模块专属文档为准。

---

# Quant Console：MiniQMT 实盘快照网站

这是现有 Vercel 项目 `quantcollection` 的代码仓库。网页不直接连接交易账户。原有市场程序统一由本机已登录的 QMT/MiniQMT 读取并上传只读快照；新增的 `/fcb2016` 期权实验室遵循“QMT 优先、不可用才读外部真实盘口”的单独链路。

生产链路：

```text
Windows QMT 终端
  → qmt_live_publisher.py（只读行情，不连接交易账户）
  → POST /api/live（共享密钥 + SHA-256）
  → Vercel Private Blob（latest.json）
  → /api/run 与网页只读展示
```

原有 QMT 快照链路任何一步失败时，网站会显示“暂无 QMT 实盘快照”，不会回退到演示、随机或合成数据。`/fcb2016` 是唯一例外：QMT 不可连接时会读取新浪财经真实五档期权盘口，但同样拒绝演示或合成行情，并明确显示来源与盘口时间。

## 当前实盘程序

- A 股市场因子选股：MiniQMT 实时快照 + 本地前复权日线。
- 沪深 ETF 期权盒式扫描：MiniQMT 有效合约元数据 + 实时买一/卖一深度。
- QMT 市场因子组合：由本轮真实选股快照生成只读组合。
- TW 半凯利：QMT 选股 + 本地前复权 15 分钟 OHLCV；网页不下单。
- ETF 成交额监控：QMT 日线成交额相对过去 20 日均值的放量代理，不等同真实资金净流入。
- 港股因子实验室：保留十二因子与 PIT 方法；只有完整的真实字段才展示个股值。

## fcb2016 A股 ETF 期权套利实验室

访问 `/fcb2016`。核心实现位于 `fcb2016_strategy.py`，API 为 `POST /api/fcb2016`。

复现口径：

- 同一标的、同一到期日配对认购与认沽，构造“买购卖沽”的长合成与“买沽卖购”的短合成；
- 枚举正向盒、反向盒以及可选的同执行价平价偏离；
- 按五档真实挂量逐档计算目标套数的成交均价，`depth_cap_per_level=10` 对应原脚本 `cap=10`；
- 先在每份 ETF 维度计算折现支付与四腿净权利金，再乘合约单位 10,000；
- 最后扣除经手费、结算费、券商佣金、额外滑点、预期行权费、保证金融资和其他成本；
- 默认 `min_net_profit_cny=12` 对应原脚本 `actionpoint=12`，页面只输出限价草案，不报单。

直接在本机验证真实行情：

```powershell
& ".\.venv-qlib\Scripts\python.exe" -c "from fcb2016_strategy import run_live_fcb2016; print(run_live_fcb2016({'source':'auto','underlying':'510050'})['summary'])"
```

主要可调参数包括 `underlying`、`expiry_month`、`interest_rate`、`quantity`、`min_net_profit_cny`、`min_depth`、`depth_cap_per_level`、三类逐张费用、卖出开仓费用豁免、行权腿数、额外滑点、保证金占用与资金率。券商净佣金默认 0.10 元仅为示例，必须按真实账户协议修改。

## 港股数据边界

`hong_kong_factor_generator.py` 实现境内外分析师预期差、南向资金、共同分析师网络、QQC、HN_z、BP、隔夜动量、量能领先与三个月预期修订等接口，并执行逐日 2%/98% trimming、行业内 z-score 和市值中性化。

MiniQMT 可以提供已下载的行情、成交额及部分财务字段，但通常不含境内/境外分析师一致预期、研报标题、评级变化和共同分析师覆盖网络。因此：

- QMT 行情可以进入因子管线；
- 缺失的分析师与网络字段必须接入额外真实 PIT 数据表；
- 字段不完整时 `hk_factor` 保持不可用，不生成五股示例。

## 本机配置

项目根目录的 `.env` 已被 Git 忽略。至少配置：

```dotenv
MINI_QMT_PATH=C:\path\to\userdata_mini
MINIQMT_PATH=C:\path\to\userdata_mini
QMT_WEBHOOK_URL=https://quantcollection-aa5n.vercel.app/api/live
QMT_WEBHOOK_SECRET=使用至少24位的随机密钥
QMT_SECRET_HEADER=X-QMT-Secret
QMT_PUBLISH_INTERVAL=60
A_SHARE_SOURCE_POLICY=auto
WIND_PYTHON_PATH=C:\Wind\Wind.NET.Client\WindNET\x64
```

`MINIQMT_PATH` 是旧脚本兼容别名。真实账户 ID 不是发布实盘行情所必需，也不会上传到网站。

`A_SHARE_SOURCE_POLICY=auto` 现在按 **Wind实时截面 → MiniQMT → 公开真实行情**
降级；设为 `wind` 可强制 A 股选股只使用 Wind 实时行情。Wind 账号只有实时权限时，
60 日动量、20 日波动率、换手稳定性、协方差和动态 IC 会从新浪前复权日线补齐，
失败再回退腾讯前复权日线；历史不足 60 个交易日的股票直接剔除，不会拿当日涨幅冒充历史因子。

首次运行可先检查 Wind SDK、终端登录与权限：

```powershell
python -B wind_data_source.py
python -B qmt_live_publisher.py --source wind --once --dry-run
```

Wind 安装器即使没有向当前虚拟环境写入 `WindPy.pth` 也没关系，项目会自动发现
`C:\Wind\Wind.NET.Client\WindNET\x64`。如果安装在其他位置，用
`WIND_PYTHON_PATH` 指向同时含有 `WindPy.py` 与 `WindPy.dll` 的目录。

安装依赖并做一次只读采集校验：

```powershell
python -m pip install -r requirements.txt
python -B qmt_live_publisher.py --once --dry-run
```

确认 QMT 已登录，且 A 股日线、15 分钟线、ETF 日线及期权板块数据已经下载。校验通过后发布一次：

```powershell
python -B qmt_live_publisher.py --once
```

持续发布：

```powershell
python -B qmt_live_publisher.py
```

若只需要在 A 股午盘和收盘各刷新一次，使用计划任务入口：

```powershell
python -B qmt_close_refresh.py --dry-run --full-history
python -B qmt_close_refresh.py
```

`qmt_close_refresh.py` 会先按 QMT 交易日历跳过周末/休市日，再增量补齐日线和
1 分钟基础数据，要求 A股选股、市场组合、TW 半凯利、ETF 成交额和期权盒式扫描
五个程序全部生成后才上传。推荐 Windows 计划任务在工作日 11:35 与 15:05 运行；
任务应设置为“仅用户登录时运行”，因为 QMT 终端必须已启动并登录。运行日志写入
`.runtime/qmt-close-refresh.log`。

发布器不会读取账户持仓，也不会提交订单。`QMT_DISPLAY_TOTAL_ASSET` 只是 TW-Kelly 网页展示的仓位缩放基数，默认 100 万元。

## 现有 Vercel 项目配置

不需要新建网站。在当前 `quantcollection` Vercel 项目中：

1. 连接一个 Private Vercel Blob store，使项目获得 `BLOB_READ_WRITE_TOKEN`。
2. 将 Blob 面板给出的 `QMT_STORE_ID` 与 `BLOB_READ_WRITE_TOKEN` 仅复制到本机忽略提交的 `.env`。若未显式设置 `QMT_WEBHOOK_SECRET`，服务端与发布器会用 HMAC-SHA256 单向派生独立的请求密钥，Blob 主令牌不会进入请求头或网页。
3. 可选新增 `QMT_SECRET_HEADER=X-QMT-Secret`、`QMT_SNAPSHOT_STALE_SECONDS=900`。
4. 部署本仓库后访问首页；港股方法页为 `/hk-factor-lab`。

`BLOB_READ_WRITE_TOKEN` 只能存在于 Vercel 私有环境和本机忽略提交的 `.env`，绝不能写进发布 JSON、网页或 Git。

## API

- `POST /api/live`：仅本机发布器使用；校验共享密钥、内容哈希、JSON 大小、来源、时区及 `is_synthetic=false`。
- `GET /api/live?program=<id>`：读取一个最新实盘结果及快照年龄。
- `POST /api/run`：现有首页入口；五个市场数据程序只读取 Blob 快照，不执行云端行情抓取。
- `GET /api/programs`：返回网页程序列表，股票数据程序没有 demo/data_mode 参数。
- `GET|POST /api/fcb2016`：运行独立的 fcb2016 真实期权盘口扫描；POST 可同时提交参数与净持仓对象。

## 验证

```powershell
python -m unittest discover -s tests -v
python -m compileall -q api live_snapshot_store.py qmt_live_publisher.py web_runner.py hong_kong_factor_generator.py
```

## XAlpha 研报吸收（RMA）

`rma_pipeline.py` 将公开或已授权的研究文本切成证据片段，并按 XAlpha 的
A/B/C 结构写入 `.runtime/rma-memory.json`。默认来源包括东方财富公开研报、
CF40、YouTube `@oldpowerful` 的公开视频元数据/用户提供字幕、Wind 授权导出，
以及 `RMA_LOCAL_RESEARCH_DIR` 指向的本地 PDF/TXT/Markdown 研报目录。未配置时，
本地来源默认读取 `%USERPROFILE%\Documents\图书\CICCresearch`。它不会绕过登录、
付费墙或 Wind 许可，也不会把研报全文写入记忆文件；仅保存来源、内容哈希、
有限证据和分类结果。

严格模式遵循论文的日频 Level-1 OHLCV 契约：宏观数据、基本面、一致预期、
分析师评级、新闻情绪、Tick/订单簿和私有资金流本身均为 A0。只有文本明确
给出可用 `open/high/low/close/volume` 表达或稳定代理的机制时才进入 B/C
原型记忆。因此 CF40/Wind/视频内容可以被采集和审计，但不会自动污染可执行
OHLCV 因子池。

配置 `.env` 后运行：

```powershell
python -B rma_pipeline.py --sources eastmoney,cf40,youtube,wind,local --days 14 --limit 20
```

仅测试公开元数据和规则分类、不下载研报 PDF：

```powershell
python -B rma_pipeline.py --sources eastmoney,cf40 --metadata-only --rules-only --limit 5
```

如需分析 YouTube 正文，将合法取得的字幕按 `<video_id>.txt` 命名并放入
`RMA_YOUTUBE_TRANSCRIPTS_DIR`。YouTube 视频列表使用官方 Data API，需设置
`YOUTUBE_API_KEY`。Wind 接入读取 `RMA_WIND_EXPORT_DIR` 下的 TXT、Markdown、
CSV、JSON 或 JSONL 授权导出，不直接抓取 Wind 网站。本地 `local` 来源会递归
读取 `RMA_LOCAL_RESEARCH_DIR` 下的 PDF、TXT 与 Markdown；单份损坏文件会被
跳过，不影响其余研报。

### Macro Brain 周期规划

`macro_brain.py` 读取 RMA 记忆与 Cross Brain 历史，选择一个主 B-Layer、
3–4 个辅助 B-Layer，并生成包含 3–5 个 Research Agent 的严格 JSON 计划。
`MEMORY_DRIVEN` 会奖励低覆盖且有 GOOD 经验的方向，并惩罚高覆盖、连续
BAD 或疑似过度拟合的原型；Cross Memory 尚不存在时则明确进入冷启动。

```powershell
python -B macro_brain.py --routing-mode MEMORY_DRIVEN
python -B macro_brain.py --routing-mode COARSE_GUIDED --coarse-direction "量价背离下的趋势失效"
python -B macro_brain.py --routing-mode FIXED_THEME --fixed-theme "低波动压缩后的方向释放"
```

默认读取 `.runtime/rma-memory.json` 和 `.runtime/cross-memory.json`，输出到
`.runtime/macro-brain-plan.json`。Cross Memory 可使用逐条记录，例如：

```json
{
  "experiences": [
    {"c_archetype_code": "C101", "outcome": "GOOD", "coverage": 0.25},
    {"c_archetype_code": "C102", "outcome": "BAD", "consecutive_failures": 2}
  ]
}
```

### Micro Brain 因子进化与质量门

`micro_brain.py` 将 Macro Brain 的 C-Layer 假设转换为受限 Python 因子代码，
支持 `SEED_INIT`、`MUTATION`、`CROSSOVER`、`REFINEMENT` 和
`NOVELTY_INJECTION`。生成代码只能访问日频 `open/high/low/close/volume`，并且
只能调用 `xalpha_operators.py` 中的七个因果向量化算子；`import`、属性调用、
负向窗口、控制流和任意内置函数都会被 AST Gate 拒绝。

最小运行示例：

```powershell
python -B micro_brain.py --evolution-mode SEED_INIT --input-context "C101 趋势启动与早期扩散"
```

C-Layer 使用 `rma_taxonomy.py` 中固定的 48 个 research type（C101–C1603）。
每个 Macro Agent 都会输出规范的 `c_layer_research_type`，包含 B-Layer code、
C-Layer code、英文名称和机制定义，并附带可直接执行的 `micro_brain_input`。
整份 Macro Brain 计划可以直接批量送入 Micro Brain：

```powershell
python -B macro_brain.py --routing-mode COARSE_GUIDED --coarse-direction "趋势启动与量价确认"
python -B micro_brain.py --macro-plan .runtime\macro-brain-plan.json --output .runtime\micro-brain-from-macro.json
```

批量结果为 `xalpha-macro-to-micro.v1`，逐个保留 Agent ID、B-Layer、规范
research type、生成代码、四道质量门结果和准入动作。若 code、类型名称或定义
被篡改而不再匹配规范 taxonomy，Macro/Micro 边界校验会直接拒绝。

父代代码较长时建议写入 JSON 文件，再传文件路径：

```json
{
  "c_archetype_code": "C101",
  "hypothesis": "趋势启动加入成交参与度加速确认",
  "parent_code": "def compute_factor(data):\n    close = data[\"close\"]\n    return cs_rank(ts_delta(close, 10) / (ts_std(close, 20) + 1e-8))\n"
}
```

```powershell
python -B micro_brain.py --evolution-mode MUTATION --input-context .runtime\micro-input.json
```

默认用固定随机种子的合成面板执行管线自检，输出到
`.runtime/micro-brain-result.json`；这只能证明代码和检查器可运行，不能当作实证
有效性。正式评估应通过 `--data` 提供含
`date,asset,open,high,low,close,volume` 的真实历史 CSV。四道质量门依次检查
静态语法/未来函数、假设—代码—金融解释对齐、无效值与低信息比例，以及截断
与未来噪声不变性。新颖性模式还必须提供 `factor_pool_codes`，实测最大绝对相关
系数小于 `0.95` 才能准入。

### Qlib 因子回测与 Plotly Dashboard

`qlib_backtest_visualizer.py` 可读取单个 Micro Brain JSON、Macro→Micro 批量结果
中的指定因子、受限 Micro 表达式或原生 Qlib 表达式。它在动态股票池上完成
截面 MAD 去极值、PIT 行业/对数市值中性化、Z-Score、Rank IC/ICIR、五分组
回测和 Qlib `TopkDropoutStrategy` 组合回测，并生成独立可交互 HTML。

Windows 上建议单独使用 Python 3.12 环境；当前稳定版 `pyqlib==0.9.7` 没有
CPython 3.13 的 Windows wheel：

```powershell
py -3.12 -m venv .venv-qlib
& ".\.venv-qlib\Scripts\python.exe" -m pip install -r requirements.txt
```

运行 Macro→Micro 结果中的第一个因子：

```powershell
& ".\.venv-qlib\Scripts\python.exe" -B qlib_backtest_visualizer.py `
  --factor .runtime\micro-brain-from-macro.json `
  --factor-index 0 `
  --market-universe csi300 `
  --start-date 2020-01-01 `
  --end-date 2025-12-31 `
  --top-k 50 `
  --hold-days 5 `
  --provider-uri "C:\qlib_data\cn_data" `
  --exposure-csv "C:\qlib_data\sw_market_cap_pit.csv" `
  --output backtest_report.html
```

暴露 CSV 必须包含 `datetime,instrument,industry,market_cap`，脚本只做向后
as-of 匹配，禁止使用未来行业或市值。若 Qlib 数据源本身已有字段，也可以使用
`--industry-field` 和 `--market-cap-field`。默认严格要求暴露覆盖率达到 70%；只有
显式传入 `--allow-missing-neutralization` 才允许缺失股票退化为截面去均值。

交易模型按卖出印花税 0.05%、双边佣金 0.02%、双边滑点 0.1% 执行；一字涨停
只禁止买入、一字跌停只禁止卖出，缺失收盘价按停牌不可交易处理。输出同时包含
`backtest_report.html` 和同名 `.metrics.json`。公开 Qlib 示例行情不含可靠的申万
行业与 PIT 市值，不能把缺失中性化暴露的结果包装成专业回测。

#### 多指数、多因子可选回测

`xalpha_index_backtest.py` 用一个入口选择股票池和因子，并输出带因子下拉框的
合并 HTML。先查看本地数据实际可用的选项：

```powershell
& ".\.venv-qlib\Scripts\python.exe" xalpha_index_backtest.py --list-options
```

运行 C801 在沪深300、中证500和中证1000中的对比回测：

```powershell
& ".\.venv-qlib\Scripts\python.exe" xalpha_index_backtest.py `
  --markets csi300,csi500,csi1000 `
  --factor-names C801 `
  --start-date 2021-01-04 `
  --end-date latest `
  --top-k 50 `
  --hold-days 5 `
  --output-dir .runtime\xalpha-index-backtests
```

`--factor-names` 可使用 C-Layer（如 `C801`）、完整因子名、因子序号，或 `all`；
`--markets` 可选 `csi300,csi500,csi800,csi1000,csiall,all_a,microcap400`。
默认复用参数完全一致的历史结果；加 `--force` 强制重跑。`microcap400` 是当前
静态成分回填历史，只适合敏感性测试，不等同于逐时点微盘指数回测。

使用本地研报与 Qlib 真实日线一键运行完整链路：

```powershell
& ".\.venv-qlib\Scripts\python.exe" -B xalpha_real_pipeline.py `
  --provider-uri ".runtime\qlib-cn-2026-08-11"
```

该命令汇总所有已配置来源，执行 RMA、Macro Brain、基于真实 Qlib OHLCV 的
Micro Brain 四重质量门、所有通过因子的 Qlib 回测、Cross Brain GOOD/BAD 经验
汇总，以及使用历史经验的下一轮 `MEMORY_DRIVEN` Macro 计划。输出位于
`.runtime/xalpha-real-run`。脚本只会在全部 HTML 确实生成后返回完成状态；若研报
日期晚于回测起点，会明确标注为回溯性机制检验，而不是无前视偏差的样本外验证。
两个 Qlib 入口默认启用 Windows 低内存模式：BLAS/OMP 单线程、Qlib 单 kernel、
Joblib threading 后端，避免 32 核机器派生几十个 Python/OpenBLAS worker。

本地网页预览：

```powershell
$env:QMT_LIVE_SNAPSHOT_FILE=".runtime\qmt-live.json"
python dev_server.py
```

本地文件模式仍只接受通过同一校验器的真实 QMT bundle，不会生成 fallback。
