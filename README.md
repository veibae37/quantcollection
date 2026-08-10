# Quant Console：MiniQMT 实盘快照网站

这是现有 Vercel 项目 `quantcollection` 的代码仓库。网页不直接连接用户电脑，也不在云端抓取公网股票行情；所有市场数据统一由本机已登录的 QMT/MiniQMT 读取，计算成只读快照后通过认证接口上传。

生产链路：

```text
Windows QMT 终端
  → qmt_live_publisher.py（只读行情，不连接交易账户）
  → POST /api/live（共享密钥 + SHA-256）
  → Vercel Private Blob（latest.json）
  → /api/run 与网页只读展示
```

任何一步失败时，网站会显示“暂无 QMT 实盘快照”；不会回退到演示数据、随机数据、合成股票或 AkShare/东方财富等公网替代源。

## 当前实盘程序

- A 股市场因子选股：MiniQMT 实时快照 + 本地前复权日线。
- 沪深 ETF 期权盒式扫描：MiniQMT 有效合约元数据 + 实时买一/卖一深度。
- QMT 市场因子组合：由本轮真实选股快照生成只读组合。
- TW 半凯利：QMT 选股 + 本地前复权 15 分钟 OHLCV；网页不下单。
- ETF 成交额监控：QMT 日线成交额相对过去 20 日均值的放量代理，不等同真实资金净流入。
- 港股因子实验室：保留十二因子与 PIT 方法；只有完整的真实字段才展示个股值。

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
```

`MINIQMT_PATH` 是旧脚本兼容别名。真实账户 ID 不是发布实盘行情所必需，也不会上传到网站。

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

## 验证

```powershell
python -m unittest discover -s tests -v
python -m compileall -q api live_snapshot_store.py qmt_live_publisher.py web_runner.py hong_kong_factor_generator.py
```

本地网页预览：

```powershell
$env:QMT_LIVE_SNAPSHOT_FILE=".runtime\qmt-live.json"
python dev_server.py
```

本地文件模式仍只接受通过同一校验器的真实 QMT bundle，不会生成 fallback。
