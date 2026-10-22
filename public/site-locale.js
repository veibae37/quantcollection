(() => {
  const isEnglish = document.documentElement.lang === "en";
  const copy = {
    "BULL": "Long", "BEAR": "Short signal", "WAIT": "Wait", "VOLUME_EXPANSION": "Elevated turnover", "NORMAL": "Normal turnover", "INFLOW_PROXY": "Inflow proxy", "OUTFLOW_PROXY": "Outflow proxy", "NEUTRAL": "Neutral", "OK": "Complete", "DATE_GAPS": "Date gaps", "CORE_NULLS": "Missing core fields",
    "沪深300": "CSI 300", "中证500": "CSI 500", "中证800": "CSI 800", "中证1000": "CSI 1000",
    "中证2000代理": "CSI 2000 proxy", "微盘代理": "Microcap proxy", "上证综指": "Shanghai Composite", "创业板指": "ChiNext",
    "主板": "Main Board", "沪市主板": "Shanghai Main Board", "深市主板": "Shenzhen Main Board", "创业板": "ChiNext", "科创板": "STAR Market", "北交所": "Beijing Stock Exchange",
    "未知行业": "Unclassified industry", "未知": "Not classified",
    "交通运输": "Transport", "传媒娱乐": "Media and entertainment", "建筑建材": "Construction and materials", "有色金属": "Non-ferrous metals", "电子信息": "Information technology", "电子器件": "Electronic components", "金融行业": "Financials",
    "EP/BP估值": "Earnings and book-value yield", "相对换手稳定性": "Stable relative turnover", "行业标准化夏普动量": "Industry-standardised risk-adjusted momentum",
    "低波动": "Low volatility", "成交额流动性": "Turnover-based liquidity", "质量因子": "Quality",
    "多头": "Long", "空仓": "Cash", "中性": "Neutral", "中性偏多": "Mildly bullish", "中性偏空": "Mildly bearish", "偏多": "Bullish", "偏空": "Bearish", "显著偏多": "Clearly bullish", "显著偏空": "Clearly bearish", "强烈看多": "Strongly bullish", "强烈看空": "Strongly bearish", "数据不足": "Insufficient data", "待发布": "Not yet released",
    "50ETF 期权 PCR": "50ETF option put–call ratio", "融资余额强度": "Margin financing intensity", "中国波指 iVIX": "China volatility proxy (iVIX/QVIX)", "五年新高比例": "Share of stocks at five-year highs", "IF 期现基差分位": "CSI 300 futures basis percentile", "股债成交额分位": "Equity–bond turnover percentile",
    "EPS 双重预期差": "Onshore–offshore EPS gap", "净利润双重预期差": "Net-profit expectation gap", "目标价双重预期差": "Target-price expectation gap", "南向持仓变化": "Change in southbound holdings", "开盘资金流入率": "Opening-session inflow rate", "基本面惊喜扩散": "Fundamental surprise diffusion", "综合质量因子": "Composite quality", "股东户数时序分": "Shareholder-count z-score", "账面市值比": "Book-to-market", "一年隔夜动量": "One-year overnight momentum", "量能领先因子": "Turnover lead–lag signal", "三个月预期修订": "Three-month earnings revisions",
    "境内外预期": "Onshore and offshore expectations", "南向资金": "Southbound flows", "南向资金 · 七因子": "Southbound flows / seven-factor framework", "分析师网络": "Analyst networks", "经典七因子": "Seven-factor framework",
    "境内 EPS 一致预期相对境外预期的偏离度，正值表示境内机构更乐观。": "The relative gap between onshore and offshore EPS consensus. A positive value means onshore analysts are more optimistic.",
    "比较同一财政预测期的净利润判断，捕捉南下资金与外资研究定价的分歧。": "Compares net-profit forecasts for the same fiscal period to study differences between mainland and offshore expectations.",
    "衡量境内与境外目标价的相对距离，观察潜在估值话语权迁移。": "Measures the relative difference between onshore and offshore target prices as a possible indication of changing valuation views.",
    "当前港股通持股占比减去 20 个交易日前水平，识别持续增配与撤离。": "The current Stock Connect ownership share less its level twenty trading sessions earlier, tracking sustained additions or reductions.",
    "最近 20 个交易日开盘阶段流入率均值，刻画早盘聪明资金方向。": "The average opening-session inflow rate over twenty trading days, used to describe early-session flow patterns.",
    "以共同分析师网络权重汇总关联公司的正向惊喜，捕捉低关注股票的信息外溢。": "Aggregates positive surprises at linked companies using shared-analyst weights to study information spillovers to less-followed stocks.",
    "等权融合盈利、成长、营运效率与盈余质量，各子项先做截面稳健处理。": "An equal-weight blend of profitability, growth, operating efficiency and earnings quality, with robust cross-sectional treatment of each component.",
    "最新股东户数相对自身已知历史的标准分，低值通常对应筹码趋于集中。": "Standardises the latest shareholder count against its own available history. Lower readings can indicate greater ownership concentration.",
    "只使用当日已披露净资产与信号日总市值，高值代表估值相对便宜。": "Uses only book equity already disclosed by the signal date, divided by that day’s market capitalisation. Higher values indicate a lower valuation relative to book equity.",
    "汇总过去一年隔夜收益并剔除最近一个月，捕捉长效开盘偏好。": "Accumulates overnight returns over the past year, excluding the latest month, to study persistent overnight return patterns.",
    "使用截至信号日已实现的换手—次日收益配对，观察量能的领先关系。": "Relates turnover to the following session’s return using only pairs fully observed by the signal date. No future return enters the calculation.",
    "比较当前与三个月前同一预测期净利润预期，正值代表盈利预期上调。": "Compares current net-profit consensus with the forecast available three months earlier for the same fiscal period. Positive values indicate upward revisions.",
    "上传数据必须明确 is_synthetic=false": "Require an explicit is_synthetic=false flag", "数据源必须标识 QMT/MiniQMT": "Require QMT/MiniQMT provenance", "时间戳必须包含时区": "Require timezone-aware timestamps",
    "盘后事件顺延到下一交易日": "Defer after-close events to the next session", "财报先在报告期维度差分": "Calculate financial changes by reporting period", "日频仅 backward as-of 映射": "Use backward as-of daily alignment only",
    "同一预测期才能计算预期差": "Compare forecasts for the same fiscal period", "未来上市股票不得回填": "Do not backfill stocks before listing", "换手领先配对不得使用未来收益": "Exclude unobserved returns from lead–lag pairs",
    "2%/98% 去极值逐日执行": "Apply daily 2nd/98th-percentile trimming", "行业内 z-score 使用当日有效样本": "Use that day’s valid industry sample for z-scores", "市值中性残差拒绝非有限值": "Reject non-finite market-cap-neutral residuals",
    "QMT 当前未提供境内外一致预期、股东户数及共同分析师网络字段，未生成港股因子值": "The required point-in-time consensus forecasts, shareholder counts and shared-analyst links are not available from QMT. Hong Kong factor values have not been generated.",
    "QMT 实盘快照不可用": "The QMT snapshot is unavailable.", "读取 QMT 实盘快照失败": "The market snapshot could not be loaded.", "尚未收到 QMT 实盘快照": "No validated QMT snapshot has been received yet.", "无法读取 QMT 实盘快照": "The stored market snapshot is not readable.", "Vercel 项目尚未配置实盘快照存储": "Snapshot storage has not been configured for this deployment.",
    "AKShare / 最近一次AKShare真实磁盘快照沪深A股真实行情": "AKShare A-share market data from the latest validated disk snapshot",
    "AKShare / 最近一次AKShare真实磁盘快照沪深A股真实行情 + AKShare 15分钟OHLCV（东方财富前复权优先、新浪不复权回退）": "AKShare selection snapshot with 15-minute OHLCV; adjusted Eastmoney bars preferred, unadjusted Sina bars used as fallback",
    "新浪财经沪深 ETF 期权五档盘口（外部真实行情）": "Sina Finance: observed five-level ETF option quotes from Shanghai and Shenzhen",
    "AKShare ETF历史日线 + 腾讯当日收盘成交额（真实行情）": "AKShare historical ETF bars with Tencent’s current closing turnover",
    "AKShare / 最近一次AKShare真实磁盘快照": "AKShare / latest validated disk snapshot", "本地只读缓存": "Read-only local cache",
    "交易时段实时快照；进程内缓存5分钟；磁盘缓存最多36小时": "Market-session snapshots; five-minute memory cache; disk cache limited to 36 hours",
    "实时价格不复权": "Unadjusted quoted prices", "AKShare / 东方财富 / 新浪财经": "AKShare / Eastmoney / Sina Finance",
    "akshare.stock_zh_a_hist_min_em，失败后 stock_zh_a_minute": "akshare.stock_zh_a_hist_min_em, with stock_zh_a_minute as fallback",
    "15分钟；东方财富前复权优先，新浪不复权回退": "15-minute bars; adjusted Eastmoney data preferred, unadjusted Sina fallback",
    "新浪财经": "Sina Finance", "直接 HTTPS ETF 期权实时行情接口": "Direct HTTPS access to observed ETF option quotes",
    "交易时段实时快照；进程内最多缓存180秒": "Market-session snapshots; memory cache limited to 180 seconds",
    "AKShare / 新浪财经 / 东方财富 / 腾讯财经": "AKShare / Sina Finance / Eastmoney / Tencent Finance",
    "历史日线 + qt.gtimg.cn 当日收盘截面": "Historical daily bars plus the current closing snapshot from qt.gtimg.cn",
    "日线；最近完整交易日": "Daily data through the latest completed trading session",
    "网页只读，不读取交易账户，不提交订单": "Read-only research output. No trading account is accessed and no order is submitted.",
    "先在成交额前300股票池计算全部因子；3-MAD缩尾+行业Z-Score：25%夏普动量 + 20%成交额流动性 + 15%低波动 + 15%EP + 10%BP + 15%相对换手稳定": "Factors are calculated for the 300 highest-turnover stocks, with 3-MAD clipping and within-industry z-scores: 25% risk-adjusted momentum, 20% turnover liquidity, 15% low volatility, 15% earnings yield, 10% book yield and 15% relative-turnover stability.",
    "选中股票最近最多160期真实前复权日收益率协方差，70%样本协方差+30%对角收缩；长仓、满仓、单股不超过8%、单一行业不超过30%": "Covariance uses up to 160 adjusted daily return observations, blending 70% sample covariance with 30% diagonal shrinkage. The portfolio is long-only and fully invested, capped at 8% per stock and 30% per industry.",
    "预期收益=z(alpha)×个股波动率×有效IC；有效IC使用下一交易日收益的截面Rank IC（每期N≥30），按(N×IC+10×0.0223)/(N+10)做贝叶斯收缩": "Expected return = z(alpha) × stock volatility × effective IC. Effective IC uses cross-sectional Rank IC against realised next-session returns (at least 30 names per observation), shrunk as (N × IC + 10 × 0.0223) / (N + 10).",
    "PE>0时EP=1/PE，PE≤0时EP=-1；PB>0时BP=1/PB，否则BP=0；无完整60交易日历史不使用1日涨跌幅替代；Dynamic IC有效日期不足才回退0.0223": "EP is 1/PE when PE is positive and −1 otherwise; BP is 1/PB when PB is positive and 0 otherwise. A one-day return never substitutes for missing 60-session history. IC falls back to 0.0223 only when there are too few valid historical dates.",
    "本轮真实市场因子前 N 名，经真实历史协方差约束的只读组合": "A read-only portfolio of the current top-ranked names, constrained using covariance estimated from observed historical returns.",
    "由行业中性动量、低波动、流动性、PE/PB价值、质量和相对换手组成；alpha_forecast使用年化波动率与动态Rank IC缩放": "The score combines industry-neutral momentum, low volatility, liquidity, PE/PB value, quality and relative turnover. Alpha forecasts are scaled by annualised volatility and dynamic Rank IC.",
    "组合只使用本轮已审计的真实行情选股结果，不读取交易账户、不下单": "The portfolio uses this run’s audited market-data selections only. It neither reads a trading account nor submits orders.",
    "MiniQMT不可用时仅替换行情访问层；概率森林与半凯利公式保持不变": "When MiniQMT is unavailable, only the market-data access layer changes. The probability forest and Half-Kelly calculation are unchanged.",
    "仅扫描合约乘数为 10000 的上交所/深交所 ETF 期权": "Scans Shanghai and Shenzhen ETF options with a contract multiplier of 10,000 only.",
    "同一标的、同一到期日内先按相同行权价配对认购与认沽，再枚举 K_low < K_high": "Pairs calls and puts at matching strikes for the same underlying and expiry, then enumerates strike pairs with K_low < K_high.",
    "先算每单位理论利润，再乘 10000 转为人民币，最后扣除 6.8 元手续费与 4.0 元滑点": "Calculates theoretical profit per unit, multiplies by 10,000 to obtain CNY per set, then deducts CNY 6.8 in fees and CNY 4.0 in slippage.",
    "四条腿均使用可执行买一/卖一；缺失真实 BBO 的合约不进入结果": "All four legs use observed best bid/ask quotes. Contracts without genuine two-sided quotes are excluded.",
    "1.7 元/张/腿 × 4 腿 = 6.8 元/套；0.0001 × 10000 × 4 腿 = 4.0 元/套": "Fees: CNY 1.7 per contract × four legs = CNY 6.8 per set. Slippage: 0.0001 × 10,000 × four legs = CNY 4.0 per set.",
    "净利润仍未覆盖四腿不同步成交、撤单、保证金占用、价格跳变及行权交收风险，不构成交易指令": "Reported net profit does not cover asynchronous fills across four legs, cancellations, margin usage, price jumps or exercise and settlement risk. It is not a trading instruction.",
    "成交额达到过去20日均值的110%后，结合前收至收盘及日内价格方向，对放量成交额差赋正负号；仅为价量代理，不等同净流入": "When turnover reaches 110% of its trailing 20-day average, the excess is signed using close-to-close and intraday price direction. This is a price–volume proxy, not measured net capital inflow.",
    "MiniQMT不可用时只替换为AKShare公开真实日线，计算公式不变": "If MiniQMT is unavailable, observed public daily bars accessed through AKShare replace the feed; the calculation is unchanged."
  };
  function value(input, fallback = "See the original source record.") {
    if (!isEnglish || typeof input !== "string") return input;
    if (Object.hasOwn(copy, input)) return copy[input];
    if (!/[\u4e00-\u9fff]/.test(input)) return input;
    if (input.startsWith("新浪行业-")) return `Sina industry: ${value(input.slice(5), "Unclassified")}`;
    const carried = input.match(/^自动采用 (\d{4}-\d{2}-\d{2}) 最近有效值$/);
    if (carried) return `Latest valid observation carried from ${carried[1]}`;
    return fallback;
  }
  function languageUrl(pathname, search = "", hash = "") {
    const path = pathname.replace(/\.html$/, "").replace(/\/$/, "");
    const english = path === "/en" || path.startsWith("/en/");
    const translated = english ? (path.slice(3) || "/") : (path === "" || path === "/index" ? "/en" : `/en${path}`);
    return translated + search + hash;
  }
  function syncLanguageLinks() {
    document.querySelectorAll(".language-toggle").forEach((link) => {
      link.setAttribute("href", languageUrl(location.pathname, location.search, location.hash));
    });
  }
  window.SiteLocale = Object.freeze({isEnglish, t: (zh, en) => isEnglish ? en : zh, value, languageUrl, syncLanguageLinks});
  syncLanguageLinks();
  document.querySelectorAll(".language-toggle").forEach((link) => {
    link.addEventListener("pointerdown", syncLanguageLinks);
    link.addEventListener("focus", syncLanguageLinks);
    link.addEventListener("click", syncLanguageLinks);
  });
  window.addEventListener("hashchange", syncLanguageLinks);
  window.addEventListener("popstate", syncLanguageLinks);
})();
