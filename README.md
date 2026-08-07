# 量化策略运行看板

这是一个可直接部署到 Vercel 的静态网页 + Python Function 项目。网页当前安全开放：

- `a_share_selector.py`：从沪深 A 股快照过滤可交易池，完成多因子 Alpha 和带约束 QP 优化，并在网页输出候选标的与目标权重。
- `boxoption2.py`：扫描沪深 ETF 期权，展示按标的、到期日和行权价正确配对且扣费后真实净利润为正的盒式价差候选。
- `bigmoneyflow.py`：通过 AkShare 获取 ETF 行情，展示成交额代理流入与盘后放量状态。
- Python 运行环境：确认 Vercel Function 的 Python 版本、区域和运行状态。
- 项目程序概览：列出根目录 Python 文件及云端兼容状态。

页面不会连接 MiniQMT，也不会执行真实下单。`bigmoneyflow.py` 的“流入”是成交额代理指标，并非真实资金净流入。`boxoption.py`、`connect.py`、`order_588000.py` 等程序依赖本机 Windows/QMT/券商账户，只在页面展示状态，不开放云端执行。

期权扫描覆盖 QMT“上证期权”和“深证期权”板块中的沪深 ETF 期权。中国市场并不是每只 A 股都有独立个股期权，因此程序不会伪造“全体股票个股期权”。本地工作进程会动态发现当前全部有效 ETF 期权合约，不再依赖固定四张合约；网页演示模式覆盖 9 个 ETF 产品族、数百张合约结构。

盒式套利严格使用买卖一可执行方向。所有权利金和行权价先保留为每单位价格；每单位理论利润乘合约乘数 10000 后才成为一套组合的人民币毛利润，随后扣除 `1.7 × 4 = 6.8` 元手续费和 `0.0001 × 10000 × 4 = 4.0` 元滑点。网页和 webhook 只输出 `True_Net_Profit_CNY > 0` 的结果。

## A 股选股网页

首页默认打开“A 股多因子选股”。自动模式优先调用东方财富的 AkShare 兼容字段实时快照，依次剔除非沪深标的、ST/退市、停牌或零成交、低流动性、极端估值以及接近涨跌停的股票，再使用价值、60 日动量、年初至今动量、低波动和适度换手因子生成 Alpha。优化器执行全投资、禁止空头、个股上限、交易板块中性代理以及规模/流动性主动暴露控制。

网页快速版只调用一次全市场快照，因此不把当日振幅代理包装成完整历史残差风险，也不把交易板块当成申万行业。生产实盘应接入 point-in-time 财报、复权历史行情、正式行业分类、涨跌停状态和退市样本库。

本地直接验证 A 股演示路径：

```powershell
python -c "from a_share_selector import run_a_share_selection; print(run_a_share_selection(data_mode='demo')['selections'][:3])"
```

## 部署到 Vercel

1. 把本目录推送到 GitHub、GitLab 或 Bitbucket。
2. 在 Vercel 新建项目并导入仓库，Root Directory 选择本项目根目录。
3. Framework Preset 选择 `Other`，Build Command 与 Output Directory 保持为空。
4. 可在 Project Settings → Environment Variables 中按 `.env.example` 添加变量；这些变量都有默认值，不添加也能运行。
5. 点击 Deploy。部署完成后访问 Vercel 分配的 `*.vercel.app` 地址。

Vercel 会依据 `.python-version` 使用 Python 3.12，并从 `requirements.txt` 安装 AkShare、pandas、NumPy 和 SciPy。`public/` 是静态页面，`api/` 中的文件会成为 Python Functions。

## MiniQMT 实时期权扫描与推送

`scanner_worker.py` 只能在已启动并登录 QMT/MiniQMT 的本地 Windows 主机运行。程序默认推送到 `https://quantcollection-aa5n.vercel.app/api/options`，也可用 `OPTIONS_WEBHOOK_URL` 覆盖。程序会依次加载本地 `.env` 和 `.env.local`；请在 Vercel 项目和本地配置相同的 `OPTIONS_WEBHOOK_SECRET`（以及可选的 `OPTIONS_SECRET_HEADER`）。真实密钥不要提交 Git。

当前仓库是静态网页 + Python Functions，因此实际部署接收端为 `api/options.py`，URL 是 `/api/options`。同时提供了用户要求的 Next.js App Router 版本 `app/api/options/route.ts`；将来迁移到 Next.js 时可直接采用，但不要在同一部署中同时维护两套同路径运行时。

先本地只算不推送：

```powershell
python -B scanner_worker.py --once --dry-run
```

确认输出后启动每 5 秒扫描并推送：

```powershell
$env:OPTIONS_WEBHOOK_URL="https://your-project.vercel.app/api/options"
$env:OPTIONS_WEBHOOK_SECRET="使用至少24位的随机密钥"
python -B scanner_worker.py
```

Vercel 接口会验证共享密钥、JSON 大小、四腿结构、10000 乘数、6.8 元手续费、4.0 元滑点以及正的真实净利润，再返回 `200 OK`。接口当前只确认接收，不保存历史；若要让不同访问者查询最新推送，需要再接入持久化数据库。

## 本地验证

先安装项目依赖（务必使用运行脚本的同一个 Python）：

```powershell
python -m pip install -r requirements.txt
```

单独运行 ETF 资金流程序：

```powershell
python bigmoneyflow.py --date 2026-08-05
```

不传 `--date` 时使用今天；如果当天尚未收盘、周末或节假日，程序会采用最近一个有完整日线的交易日。默认结果写入 Windows 的 `C:\qmt_regime`；Vercel 会自动写入临时目录 `/tmp/qmt_regime`。

直接验证 Python 运行适配器：

```powershell
python -c "from web_runner import run_registered; print(run_registered('boxoption2', {}))"
```

完整预览网页与 API：

```powershell
python dev_server.py
```

然后访问 `http://127.0.0.1:8000`。如已安装 Vercel CLI，也可运行 `vercel dev`。

## 接入其他 Python 程序

不要让网页直接执行任意文件名。将程序的纯计算部分整理成“接收字典、返回可 JSON 序列化字典”的函数，然后在 `web_runner.py` 的 `PROGRAMS` 和 `RUNNERS` 中显式注册。真实交易、无限循环、桌面客户端和需要本机 DLL 的程序不应放进公开的 Web API。

## 多因子选股与组合优化

`quant_portfolio_system.py` 提供 DataProcessor、FactorLibrary、AlphaGenerator 与 PortfolioOptimizer，覆盖三标准差去极值、标准化、行业中性化、Alpha 黄金尺度转换、多因子风险模型和带交易成本的主动 QP。

```powershell
python -m pip install -r requirements-portfolio.txt
python quant_portfolio_system.py --output-dir outputs/portfolio_demo
python -m unittest tests.test_quant_portfolio_system -v
```

演示仅使用确定性的合成数据，输出完整权重 CSV、处理后因子、Alpha 预测、摘要 JSON 与权重对比图。生产数据必须使用 point-in-time 基本面并处理退市样本，避免前视偏差和幸存者偏差。

## TW 概率森林、半凯利与 MiniQMT

`tw_kelly_strategy.py` 将 `TWrandomf.pine` 的两套九票规则森林、三根 K 线目标、滚动分箱校准及概率 EMA 转换为 Python。它连接 A 股多因子选股前 20 只，并按等赔率二分之一凯利公式计算多头仓位：

```text
half_kelly = max(0, 0.5 * (P(up) - P(down)))
```

网页只展示确定性演示行情和模拟调仓单。MiniQMT 必须在安装了交易终端的本地 Windows 主机运行。先复制/编辑项目根目录下被 Git 忽略的 `.env`，填写真实的 `MINIQMT_PATH` 与 `MINIQMT_ACCOUNT_ID`，然后执行默认 dry-run：

```powershell
python -B miniqmt_kelly_executor.py --selection-data-mode live
```

提交真实委托需要同时传入 `--live`，并显式设置实盘确认变量：

```powershell
$env:MINIQMT_ENABLE_LIVE_TRADING="I_UNDERSTAND_LIVE_TRADING"
python -B miniqmt_kelly_executor.py --selection-data-mode live --live
```

若东方财富公共快照被网络拦截，dry-run 会改用 MiniQMT 的真实沪深 A 股板块、实时成交额和本地日线，按 60 日动量、低波动、流动性及规模生成备用前 20；不会伪造 PE/PB。该备用模型不会静默用于实盘。审阅 dry-run 后如确需使用，必须同时传入 `--allow-qmt-selection-live` 并设置：

```powershell
$env:MINIQMT_ENABLE_QMT_SELECTION_LIVE="I_REVIEWED_QMT_MARKET_ONLY_SELECTION"
```

运行前还需确认 MiniQMT 已登录，且候选股票的日线与 15 分钟历史行情已下载。执行器采用卖单优先、100 股整手、T+1 可卖数量限制和买卖一附近保护限价。Spyder Runtime 若存在 NumPy/SciPy 原生 DLL 问题，优化器会自动切换到满足同一组约束的投影梯度 QP。

项目架构和限制以 Vercel 当前的 [Python Runtime 文档](https://vercel.com/docs/functions/runtimes/python) 为准。
