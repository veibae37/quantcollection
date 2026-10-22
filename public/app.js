const state = { programs: [], active: null };
const $ = (selector) => document.querySelector(selector);
const isEnglish = document.documentElement.lang === "en";
const t = (zh, en) => isEnglish ? en : zh;

const englishPrograms = {
  a_share_selector: ["A-share Multi-factor Selection", "Mainland A-shares", "Loads a read-only multi-factor selection snapshot from MiniQMT or validated Eastmoney market data.", "MiniQMT is preferred; validated real-market fallback data may be used."],
  quant_portfolio_system: ["Market-factor Portfolio", "Active Portfolio Management", "Loads a read-only portfolio snapshot built from MiniQMT or audited public market data.", "Read-only market snapshot. No trade is sent."],
  tw_kelly_rebalance: ["TW Probability Forest Half-Kelly Rebalance", "Signals and Position Sizing", "Builds a read-only Half-Kelly plan from real selection snapshots and MiniQMT or public 15-minute OHLCV.", "Read-only market snapshot. No trade is sent."],
  bigmoneyflow: ["ETF Turnover Monitor", "Market Data", "Monitors ETF daily turnover against its trailing 20-day average using MiniQMT or AKShare.", "Read-only market snapshot. No trade is sent."],
  boxoption2: ["ETF Option Box-spread Scanner", "Mainland ETF Options", "Scans four-leg box spreads from real MiniQMT or Eastmoney bid and ask quotes.", "Read-only market snapshot. No trade is sent."],
  runtime_info: ["Python Runtime", "Environment Diagnostics", "Shows Python, operating system, Vercel region, and registered program count.", "Used only to verify that the Python Function starts correctly."],
  project_overview: ["Project Program Overview", "Project Diagnostics", "Read-only scan of Python files and their cloud compatibility.", "Reads filenames only and does not execute trading scripts."],
  qmt_programs: ["MiniQMT Trading Programs", "Local Trading", "Requires Windows, the broker client, local DLLs, and a signed-in trading account.", "The website only receives published read-only snapshots and never connects to a trading account."],
  ml_strategy: ["Random Forest Strategy", "QMT Strategy", "Requires QMT ContextInfo, TA-Lib, and local trading functions.", "The public API does not execute strategy context or trading functions."],
};

function localizeProgram(program) {
  const values = englishPrograms[program.id];
  if (!isEnglish || !values) return program;
  return { ...program, title: values[0], category: values[1], description: values[2], notice: values[3] };
}

const statusText = { ready: t("云端可运行", "Cloud ready"), local_only: t("仅本地", "Local only") };

async function loadPrograms() {
  try {
    const response = await fetch("/api/programs");
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || t("API 不可用", "API unavailable"));
    state.programs = payload.programs;
    applyConfig(payload.config);
    renderPrograms();
    $("#runtime-state").textContent = t("API 已连接", "API connected");
    selectProgram((state.programs.find((item) => item.id === "a_share_selector") || state.programs[0]).id);
  } catch (error) {
    $("#runtime-state").textContent = t("API 连接失败", "API connection failed");
    $("#program-list").innerHTML = `<div class="notice error-message">${escapeHtml(error.message)}</div>`;
  }
}

function applyConfig(config) {
  $("#app-subtitle").textContent = t(config.subtitle, "Explainable, source-auditable research snapshots built from real A-share market data.");
  $("#public-notice").textContent = t(config.notice, "MiniQMT is preferred, with validated real-market fallback data. No simulated fallback, investment advice, or live trading.");
  $("#python-version").textContent = config.python;
  $("#program-count").textContent = state.programs.length;
  $("#ready-count").textContent = state.programs.filter((item) => item.status === "ready").length;
  $("#program-total").textContent = state.programs.length;
}

function renderPrograms() {
  $("#program-list").innerHTML = state.programs.map(localizeProgram).map((program) => `
    <button class="program-card" type="button" data-program="${escapeHtml(program.id)}">
      <span class="program-card-top"><strong>${escapeHtml(program.title)}</strong><span class="mini-status ${program.status}"></span></span>
      <p>${escapeHtml(program.file)}</p>
    </button>`).join("");
  document.querySelectorAll(".program-card").forEach((button) => button.addEventListener("click", () => selectProgram(button.dataset.program)));
}

function selectProgram(id) {
  const rawProgram = state.programs.find((item) => item.id === id);
  const program = rawProgram && localizeProgram(rawProgram);
  if (!program) return;
  state.active = program;
  document.querySelectorAll(".program-card").forEach((card) => card.classList.toggle("active", card.dataset.program === id));
  $("#empty-console").classList.add("hidden");
  $("#active-console").classList.remove("hidden");
  $("#active-category").textContent = program.category;
  $("#active-title").textContent = program.title;
  $("#active-description").textContent = program.description;
  $("#active-status").textContent = statusText[program.status] || program.status;
  $("#active-status").className = `status-badge ${program.status}`;
  $("#program-notice").textContent = program.notice;
  $("#program-notice").classList.toggle("hidden", program.status !== "ready");
  $("#local-warning").textContent = program.notice;
  $("#local-warning").classList.toggle("hidden", program.status === "ready");
  $("#parameter-fields").innerHTML = program.parameters.map(fieldTemplate).join("");
  const button = $("#run-button");
  button.disabled = program.status !== "ready";
  button.querySelector(".button-label").textContent = program.status === "ready" ? t("读取最新真实快照", "Load latest real snapshot") : t("当前环境不可运行", "Unavailable in this environment");
  $("#result-area").classList.add("hidden");
}

function fieldTemplate(field) {
  const id = `param-${field.name}`;
  if (field.type === "select") {
    const options = (field.options || []).map((option) => `<option value="${escapeHtml(option.value)}" ${option.value === field.value ? "selected" : ""}>${escapeHtml(option.label)}</option>`).join("");
    return `<div class="field"><label for="${id}">${escapeHtml(field.label)}</label><select id="${id}" name="${escapeHtml(field.name)}">${options}</select></div>`;
  }
  return `<div class="field"><label for="${id}">${escapeHtml(field.label)}</label><input id="${id}" name="${escapeHtml(field.name)}" type="${escapeHtml(field.type)}" value="${escapeHtml(field.value)}" min="${escapeHtml(field.min)}" max="${escapeHtml(field.max)}" step="${escapeHtml(field.step)}" required></div>`;
}

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.active || state.active.status !== "ready") return;
  const button = $("#run-button");
  const label = button.querySelector(".button-label");
  const parameters = Object.fromEntries(new FormData(event.currentTarget).entries());
  button.disabled = true;
  button.classList.add("loading");
  label.textContent = t("读取中", "Loading");
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program: state.active.id, parameters }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || t("运行失败", "Run failed"));
    renderResult(payload.result, payload.duration_ms);
  } catch (error) {
    renderError(error.message);
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    label.textContent = t("刷新真实数据快照", "Refresh real-data snapshot");
  }
});

function renderResult(result, durationMs) {
  const marketModes = new Set(["a_share_selection", "portfolio_optimization", "tw_kelly_rebalance", "market_data"]);
  if (marketModes.has(result.mode) && result.is_synthetic !== false) {
    renderError(t("服务器返回了模拟或合成数据，页面已拒绝显示", "The server returned simulated or synthetic data, so the page refused to display it."));
    return;
  }
  $("#result-area").classList.remove("hidden", "error-message");
  $("#duration").textContent = `${durationMs} ms`;
  $("#metric-grid").innerHTML = buildMetrics(result).map(([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");
  renderSource(result);
  renderSelections(result);
  renderPortfolio(result);
  renderTwKelly(result);
  renderOrders(result);
  renderMethodology(result);
  $("#json-output").textContent = JSON.stringify(result, null, 2);
  $("#result-area").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderSource(result) {
  const banner = $("#source-banner");
  if (!["a_share_selection", "portfolio_optimization", "tw_kelly_rebalance", "market_data"].includes(result.mode)) {
    banner.className = "source-banner hidden";
    banner.textContent = "";
    return;
  }
  const details = result.source_details || {};
  const mode = details.fallback_used ? t("真实行情降级源", "Validated real-market fallback") : t("MiniQMT 真实快照", "MiniQMT real snapshot");
  const fallback = result.fallback_reason ? ` · ${result.fallback_reason}` : "";
  const provenance = [details.provider, details.access_layer, details.frequency, details.price_adjustment]
    .filter(Boolean)
    .map((item) => escapeHtml(String(item)))
    .join(" · ");
  banner.className = "source-banner live-source";
  banner.innerHTML = `<strong>${escapeHtml(mode)}</strong><span>${escapeHtml(result.source)} · ${t("数据时间", "Data as of")} ${escapeHtml(result.data_as_of)}${escapeHtml(fallback)}</span>${provenance ? `<small>${provenance}</small>` : ""}`;
}

function renderPortfolio(result) {
  const portfolio = result.mode === "portfolio_optimization" && Array.isArray(result.portfolio) ? result.portfolio : [];
  $("#portfolio-wrap").classList.toggle("hidden", portfolio.length === 0);
  if (!portfolio.length) {
    $("#portfolio-body").innerHTML = "";
    return;
  }
  $("#portfolio-subtitle").textContent = isEnglish ? `Top ${portfolio.length} optimized weights across ${result.summary.asset_count} assets` : `${result.summary.asset_count} 个资产中展示优化权重最高的 ${portfolio.length} 个`;
  $("#portfolio-body").innerHTML = portfolio.map((item) => `
    <tr>
      <td class="rank">${item.rank}</td>
      <td><strong>${escapeHtml(item.asset)}</strong></td>
      <td><span class="board-tag">${escapeHtml(item.industry)}</span></td>
      <td>${formatNumber(item.benchmark_weight_pct, 4)}%</td>
      <td><strong>${formatNumber(item.portfolio_weight_pct, 4)}%</strong></td>
      <td class="${item.active_weight_pct >= 0 ? "positive" : "negative"}">${formatSigned(item.active_weight_pct, 4)}%</td>
      <td class="${item.alpha_forecast_pct >= 0 ? "positive" : "negative"}">${formatSigned(item.alpha_forecast_pct, 5)}%</td>
    </tr>`).join("");
}

function renderTwKelly(result) {
  const portfolio = result.mode === "tw_kelly_rebalance" && Array.isArray(result.portfolio) ? result.portfolio : [];
  $("#tw-kelly-wrap").classList.toggle("hidden", portfolio.length === 0);
  if (!portfolio.length) {
    $("#tw-kelly-body").innerHTML = "";
    return;
  }
  $("#tw-kelly-subtitle").textContent = isEnglish ? `${portfolio.length} names · ${result.summary.bull_count} long signals · ${formatNumber(result.summary.target_gross_exposure_pct, 2)}% target gross exposure` : `${portfolio.length} 只标的 · 多头信号 ${result.summary.bull_count} 只 · 目标总仓位 ${formatNumber(result.summary.target_gross_exposure_pct, 2)}%`;
  $("#tw-kelly-body").innerHTML = portfolio.map((item) => `
    <tr>
      <td class="rank">${item.position_rank}</td>
      <td><strong>${escapeHtml(item.ticker)}</strong><small>${escapeHtml(item.name)}</small></td>
      <td><span class="board-tag">${escapeHtml(item.model)}</span></td>
      <td><span class="board-tag">${escapeHtml(item.game)}</span></td>
      <td class="positive">${formatNumber(item.up_probability * 100, 2)}%</td>
      <td class="negative">${formatNumber(item.down_probability * 100, 2)}%</td>
      <td>${item.calibration_samples}</td>
      <td>${formatNumber(item.half_kelly_fraction * 100, 3)}%</td>
      <td><strong>${formatNumber(item.target_weight_pct, 4)}%</strong></td>
      <td>${formatNumber(item.latest_price, 3)}</td>
    </tr>`).join("");
}

function renderSelections(result) {
  const selections = Array.isArray(result.selections) ? result.selections : [];
  $("#selection-wrap").classList.toggle("hidden", selections.length === 0);
  if (!selections.length) {
    $("#selection-body").innerHTML = "";
    return;
  }
  $("#selection-subtitle").textContent = isEnglish ? `${selections.length} names from ${result.summary.optimized_universe_count} candidates; ${formatNumber(result.summary.selected_weight_coverage_pct, 2)}% of full portfolio weight` : `${result.summary.optimized_universe_count} 只候选池中输出 ${selections.length} 只；覆盖完整组合权重 ${formatNumber(result.summary.selected_weight_coverage_pct, 2)}%`;
  $("#selection-body").innerHTML = selections.map((stock) => `
    <tr>
      <td class="rank">${stock.rank}</td>
      <td><strong>${escapeHtml(stock.ticker)}</strong><small>${escapeHtml(stock.name)}</small></td>
      <td><span class="board-tag">${escapeHtml(stock.board)}</span></td>
      <td>${formatNumber(stock.latest_price, 2)}</td>
      <td class="${stock.momentum_60d_pct >= 0 ? "positive" : "negative"}">${formatSigned(stock.momentum_60d_pct)}%</td>
      <td>${formatNumber(stock.dynamic_pe, 2)}</td>
      <td>${formatNumber(stock.pb, 2)}</td>
      <td><strong>${formatNumber(stock.target_weight_pct, 3)}%</strong></td>
      <td class="${stock.active_weight_pct >= 0 ? "positive" : "negative"}">${formatSigned(stock.active_weight_pct, 3)}%</td>
      <td><div class="reason-list">${stock.reasons.map((reason) => `<span>${escapeHtml(reason)}</span>`).join("")}</div></td>
    </tr>`).join("");
}

function renderOrders(result) {
  const orders = Array.isArray(result.orders) ? result.orders : [];
  $("#orders-wrap").classList.toggle("hidden", orders.length === 0);
  $("#orders-body").innerHTML = orders.map((order) => {
    const code = order.code ?? order.ticker;
    const quantity = order.qty ?? order.quantity;
    const price = order.price ?? order.reference_price;
    const action = order.action ? (order.action === "open" ? t("开仓", "Open") : t("平仓", "Close")) : t("调仓", "Rebalance");
    return `<tr><td>${escapeHtml(code)}</td><td class="trade-side ${escapeHtml(order.side)}">${order.side === "buy" ? t("买入", "Buy") : t("卖出", "Sell")}</td><td>${action}</td><td>${escapeHtml(quantity)}</td><td>${formatNumber(price, 4)}</td></tr>`;
  }).join("");
}

function renderMethodology(result) {
  const methodology = result.methodology || {};
  const entries = Object.entries(methodology);
  $("#methodology-wrap").classList.toggle("hidden", entries.length === 0);
  $("#methodology-content").innerHTML = entries.map(([key, value]) => `<div><strong>${escapeHtml(key.replaceAll("_", " "))}</strong><span>${escapeHtml(Array.isArray(value) ? value.join("、") : value)}</span></div>`).join("");
}

function buildMetrics(result) {
  if (result.mode === "a_share_selection") {
    const summary = result.summary;
    return [
      [t("数据状态", "Data status"), result.source_details?.fallback_used ? `${result.source_details?.provider || t("公共数据源", "Public provider")} ${t("真实快照", "real snapshot")}` : t("MiniQMT 真实快照", "MiniQMT real snapshot")],
      [t("可投资股票", "Eligible stocks"), summary.eligible_count],
      [t("输出标的", "Selected names"), summary.selected_count],
      [t("组合权重覆盖", "Portfolio weight coverage"), `${formatNumber(summary.selected_weight_coverage_pct, 2)}%`],
      [t("预期主动收益", "Expected active return"), `${formatSigned(summary.expected_active_return_pct, 4)}%`],
      [t("预期主动风险", "Expected active risk"), `${formatNumber(summary.active_risk_pct, 4)}%`],
      [t("优化后 IR", "Optimized IR"), formatNumber(summary.optimized_information_ratio, 4)],
      [t("基本定律 IR", "Fundamental-law IR"), formatNumber(summary.forecast_fundamental_law_ir, 4)],
      [t("最大个股权重", "Maximum name weight"), `${formatNumber(summary.max_weight_pct, 2)}%`],
    ];
  }
  if (result.mode === "portfolio_optimization") {
    const summary = result.summary;
    return [
      [t("资产数量", "Assets"), summary.asset_count],
      [t("展示持仓", "Displayed holdings"), summary.displayed_holding_count],
      [t("预期主动收益", "Expected active return"), `${formatSigned(summary.expected_active_return * 100, 4)}%`],
      [t("主动风险", "Active risk"), `${formatNumber(summary.active_risk * 100, 4)}%`],
      [t("优化后 IR", "Optimized IR"), formatNumber(summary.optimized_information_ratio, 4)],
      [t("基本定律 IR", "Fundamental-law IR"), formatNumber(summary.forecast_fundamental_law_ir, 4)],
      [t("有效 IC", "Effective IC"), formatNumber(summary.effective_ic, 4)],
      [t("换手率", "Turnover"), `${formatNumber(summary.turnover * 100, 2)}%`],
      [t("最大权重", "Maximum weight"), `${formatNumber(summary.max_weight * 100, 2)}%`],
    ];
  }
  if (result.mode === "tw_kelly_rebalance") {
    const summary = result.summary;
    return [
      [t("选股数量", "Selected names"), summary.selected_count],
      [t("多头信号", "Long signals"), summary.bull_count],
      [t("等待信号", "Wait signals"), summary.wait_count],
      [t("空头信号", "Short signals"), summary.bear_count],
      [t("目标总仓位", "Target gross exposure"), `${formatNumber(summary.target_gross_exposure_pct, 2)}%`],
      [t("目标现金", "Target cash"), `${formatNumber(summary.target_cash_pct, 2)}%`],
      [t("调仓单数", "Proposed orders"), summary.proposed_order_count],
      [t("模拟总资产", "Simulated assets"), `¥${formatNumber(summary.total_asset, 0)}`],
      [t("仓位方法", "Sizing method"), t("二分之一凯利", "Half Kelly")],
    ];
  }
  if (result.mode === "market_data") return [[t("状态", "Regime"), result.regime], [t("方向", "Direction"), result.direction], [t("代理流入", "Proxy inflow"), `${formatNumber(result.total_net_flow_cny / 1e8, 2)} ${t("亿元", "CNY 100m")}`], [t("规模占比", "Scale ratio"), `${formatNumber(result.flow_ratio_bps, 2)} bps`], [t("强度分数", "Strength score"), formatNumber(result.strength_score, 2)], [t("ETF 数量", "ETF count"), result.etf_count]];
  return Object.entries(result.summary || {}).slice(0, 9).map(([key, value]) => [key.replaceAll("_", " "), value]);
}

function renderError(message) {
  $("#result-area").classList.remove("hidden");
  $("#result-area").classList.add("error-message");
  $("#duration").textContent = t("失败", "Failed");
  $("#metric-grid").innerHTML = `<div class="metric"><span>ERROR</span><strong>${escapeHtml(message)}</strong></div>`;
  $("#source-banner").className = "source-banner hidden";
  $("#selection-wrap").classList.add("hidden");
  $("#portfolio-wrap").classList.add("hidden");
  $("#tw-kelly-wrap").classList.add("hidden");
  $("#orders-wrap").classList.add("hidden");
  $("#methodology-wrap").classList.add("hidden");
  $("#json-output").textContent = JSON.stringify({ error: message }, null, 2);
}

function formatNumber(value, precision = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(precision) : "—";
}

function formatSigned(value, precision = 2) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number >= 0 ? "+" : ""}${number.toFixed(precision)}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

loadPrograms();
