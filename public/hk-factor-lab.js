const {t, value: localize} = window.SiteLocale;
const factors = [
  { key: "dual_gap_eps", index: "01", name: "EPS 双重预期差", category: "境内外预期", formula: "Onshore EPS / Offshore EPS − 1", description: "境内 EPS 一致预期相对境外预期的偏离度，正值表示境内机构更乐观。" },
  { key: "dual_gap_net_profit", index: "02", name: "净利润双重预期差", category: "境内外预期", formula: "Onshore NP / Offshore NP − 1", description: "比较同一财政预测期的净利润判断，捕捉南下资金与外资研究定价的分歧。" },
  { key: "dual_gap_target_price", index: "03", name: "目标价双重预期差", category: "境内外预期", formula: "Onshore TP / Offshore TP − 1", description: "衡量境内与境外目标价的相对距离，观察潜在估值话语权迁移。" },
  { key: "SB_Holding_Change", index: "04", name: "南向持仓变化", category: "南向资金", formula: "SB shareₜ − SB shareₜ₋₂₀", description: "当前港股通持股占比减去 20 个交易日前水平，识别持续增配与撤离。" },
  { key: "inflow_rate_open", index: "05", name: "开盘资金流入率", category: "南向资金 · 七因子", formula: "mean₂₀(open inflow rate)", description: "最近 20 个交易日开盘阶段流入率均值，刻画早盘聪明资金方向。" },
  { key: "analyst_network_diffusion", index: "06", name: "基本面惊喜扩散", category: "分析师网络", formula: "Σⱼ SCᵢⱼ × Surpriseⱼ / Σⱼ |SCᵢⱼ|", description: "以共同分析师网络权重汇总关联公司的正向惊喜，捕捉低关注股票的信息外溢。" },
  { key: "QQC", index: "07", name: "综合质量因子", category: "经典七因子", formula: "mean[z(ROE), z(EPS g), z(ΔATO), z(−Accrual)]", description: "等权融合盈利、成长、营运效率与盈余质量，各子项先做截面稳健处理。" },
  { key: "HN_z", index: "08", name: "股东户数时序分", category: "经典七因子", formula: "(HNₜ − μhistory) / σhistory", description: "最新股东户数相对自身已知历史的标准分，低值通常对应筹码趋于集中。" },
  { key: "BP", index: "09", name: "账面市值比", category: "经典七因子", formula: "PIT book equity / same-day market cap", description: "只使用当日已披露净资产与信号日总市值，高值代表估值相对便宜。" },
  { key: "mmt_overnight_A", index: "10", name: "一年隔夜动量", category: "经典七因子", formula: "Σ₂₅₂ overnight return − Σ₂₀ overnight return", description: "汇总过去一年隔夜收益并剔除最近一个月，捕捉长效开盘偏好。" },
  { key: "corr_ret_turn_post_1M", index: "11", name: "量能领先因子", category: "经典七因子", formula: "corr₂₀(turnover_d, close return_d₊₁)", description: "使用截至信号日已实现的换手—次日收益配对，观察量能的领先关系。" },
  { key: "EEChange_3M", index: "12", name: "三个月预期修订", category: "经典七因子", formula: "Consensusₜ / Consensus_as-of(ₜ₋₃M) − 1", description: "比较当前与三个月前同一预测期净利润预期，正值代表盈利预期上调。" },
].map((factor) => ({...factor, name: localize(factor.name), category: localize(factor.category), description: localize(factor.description)}));

const checks = [
  "上传数据必须明确 is_synthetic=false", "数据源必须标识 QMT/MiniQMT", "时间戳必须包含时区",
  "盘后事件顺延到下一交易日", "财报先在报告期维度差分", "日频仅 backward as-of 映射",
  "同一预测期才能计算预期差", "未来上市股票不得回填", "换手领先配对不得使用未来收益",
  "2%/98% 去极值逐日执行", "行业内 z-score 使用当日有效样本", "市值中性残差拒绝非有限值",
];

const $ = (selector) => document.querySelector(selector);

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function selectFactor(key) {
  const factor = factors.find((item) => item.key === key);
  document.querySelectorAll("[data-factor]").forEach((button) => {
    const active = button.dataset.factor === key;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
  });
  $("#detail-index").textContent = factor.index;
  $("#detail-category").textContent = factor.category;
  $("#detail-name").textContent = factor.name;
  $("#detail-key").textContent = factor.key;
  $("#detail-description").textContent = factor.description;
  $("#detail-formula").textContent = factor.formula;
}

function renderFactors() {
  const list = $("#factor-list");
  factors.forEach((factor) => {
    const button = make("button", "factor-button");
    button.type = "button";
    button.dataset.factor = factor.key;
    button.setAttribute("aria-pressed", "false");
    button.append(make("span", "", factor.index), make("strong", "", factor.name), make("small", "", factor.category), make("i", "", "→"));
    button.addEventListener("click", () => selectFactor(factor.key));
    list.append(button);
  });
  selectFactor(factors[0].key);
}

function renderChecks() {
  checks.forEach((name, index) => {
    const item = make("li");
    item.append(make("span", "", String(index + 1).padStart(2, "0")), make("strong", "", localize(name)), make("i", "", "ENFORCED"));
    $("#test-grid").append(item);
  });
}

function renderLiveTable(result, meta) {
  const rows = Array.isArray(result.rows) ? result.rows : [];
  const status = $("#live-status");
  status.className = `live-state ${meta.stale ? "stale" : "available"}`;
  status.innerHTML = `<i></i><div><strong>${meta.stale ? t("QMT 实盘快照已过时", "The QMT snapshot is older than the freshness limit") : t("QMT 实盘快照可用", "Validated QMT snapshot available")}</strong><span>${t("生成时间", "Generated")} ${escapeHtml(meta.generated_at)} · ${t("年龄", "age")} ${Number(meta.snapshot_age_seconds)} ${t("秒", "seconds")}</span></div>`;
  if (!rows.length) {
    $("#live-content").innerHTML = `<p class="live-empty">${t("快照已通过来源校验，但本轮没有可展示的港股因子记录。", "The snapshot passed source validation, but this run contains no Hong Kong factor records to display.")}</p>`;
    return;
  }
  const columns = ["ticker", "dual_gap_eps", "SB_Holding_Change", "QQC", "HN_z", "BP", "mmt_overnight_A", "EEChange_3M"];
  const labels = [t("股票", "Stock"), t("EPS 预期差", "EPS expectation gap"), t("南向持仓变化", "Southbound holding change"), "QQC", "HN_z", "BP", t("隔夜动量", "Overnight momentum"), "EEChange_3M"];
  const head = labels.map((label) => `<th>${escapeHtml(label)}</th>`).join("");
  const body = rows.map((row) => `<tr>${columns.map((key, index) => `<${index ? "td" : "th"}>${escapeHtml(formatValue(row[key], index === 0))}</${index ? "td" : "th"}>`).join("")}</tr>`).join("");
  $("#live-content").innerHTML = `<div class="table-shell"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

async function loadLiveSnapshot() {
  try {
    const response = await fetch("/api/live?program=hk_factor", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(localize(payload.error || "QMT 实盘快照不可用", "The snapshot could not be loaded. The source response is available from the API."));
    if (payload.result.is_synthetic !== false) throw new Error(t("服务器返回了非实盘数据，页面已拒绝显示", "The response is not marked as genuine market data and has not been displayed."));
    renderLiveTable(payload.result, payload.snapshot_meta);
  } catch (error) {
    const status = $("#live-status");
    status.className = "live-state unavailable";
    status.innerHTML = `<i></i><div><strong>${t("暂无 QMT 港股因子实盘快照", "No validated Hong Kong factor snapshot is available")}</strong><span>${escapeHtml(error.message)}</span></div>`;
    $("#live-content").innerHTML = `<p class="live-empty">${t("没有演示数据或合成回退。请保持本机 QMT 在线，并为分析师预期与网络字段接入真实 PIT 数据源。", "No demo or synthetic records are substituted. A local QMT connection and genuine point-in-time datasets for analyst expectations and network fields are required.")}</p>`;
  }
}

function formatValue(value, plain = false) {
  if (plain) return String(value ?? "—");
  const number = Number(value);
  return Number.isFinite(number) ? `${number >= 0 ? "+" : ""}${number.toFixed(4)}` : "—";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[char]);
}

renderFactors();
renderChecks();
loadLiveSnapshot();
