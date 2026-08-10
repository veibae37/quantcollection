const state = { programs: [], active: null };
const $ = (selector) => document.querySelector(selector);
const statusText = { ready: "云端可运行", local_only: "仅本地" };

async function loadPrograms() {
  try {
    const response = await fetch("/api/programs");
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "API 不可用");
    state.programs = payload.programs;
    applyConfig(payload.config);
    renderPrograms();
    $("#runtime-state").textContent = "API 已连接";
    selectProgram((state.programs.find((item) => item.id === "a_share_selector") || state.programs[0]).id);
  } catch (error) {
    $("#runtime-state").textContent = "API 连接失败";
    $("#program-list").innerHTML = `<div class="notice error-message">${escapeHtml(error.message)}</div>`;
  }
}

function applyConfig(config) {
  document.title = config.name;
  $("#app-name").innerHTML = `${escapeHtml(config.name)}<br><span>清晰可复核。</span>`;
  $("#app-subtitle").textContent = config.subtitle;
  $("#public-notice").textContent = config.notice;
  $("#python-version").textContent = config.python;
  $("#program-count").textContent = state.programs.length;
  $("#ready-count").textContent = state.programs.filter((item) => item.status === "ready").length;
  $("#program-total").textContent = state.programs.length;
}

function renderPrograms() {
  $("#program-list").innerHTML = state.programs.map((program) => `
    <button class="program-card" type="button" data-program="${escapeHtml(program.id)}">
      <span class="program-card-top"><strong>${escapeHtml(program.title)}</strong><span class="mini-status ${program.status}"></span></span>
      <p>${escapeHtml(program.file)}</p>
    </button>`).join("");
  document.querySelectorAll(".program-card").forEach((button) => button.addEventListener("click", () => selectProgram(button.dataset.program)));
}

function selectProgram(id) {
  const program = state.programs.find((item) => item.id === id);
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
  button.querySelector(".button-label").textContent = program.status === "ready" ? "读取 QMT 实盘快照" : "当前环境不可运行";
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
  label.textContent = "读取中";
  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program: state.active.id, parameters }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || "运行失败");
    renderResult(payload.result, payload.duration_ms);
  } catch (error) {
    renderError(error.message);
  } finally {
    button.disabled = false;
    button.classList.remove("loading");
    label.textContent = "刷新 QMT 实盘快照";
  }
});

function renderResult(result, durationMs) {
  const marketModes = new Set(["a_share_selection", "option_market_scan", "portfolio_optimization", "tw_kelly_rebalance", "market_data"]);
  if (marketModes.has(result.mode) && result.is_synthetic !== false) {
    renderError("服务器返回了非 QMT 实盘数据，页面已拒绝显示");
    return;
  }
  $("#result-area").classList.remove("hidden", "error-message");
  $("#duration").textContent = `${durationMs} ms`;
  $("#metric-grid").innerHTML = buildMetrics(result).map(([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");
  renderSource(result);
  renderSelections(result);
  renderOptions(result);
  renderPortfolio(result);
  renderTwKelly(result);
  renderOrders(result);
  renderMethodology(result);
  $("#json-output").textContent = JSON.stringify(result, null, 2);
  $("#result-area").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderSource(result) {
  const banner = $("#source-banner");
  if (!["a_share_selection", "option_market_scan", "portfolio_optimization", "tw_kelly_rebalance", "market_data"].includes(result.mode)) {
    banner.className = "source-banner hidden";
    banner.textContent = "";
    return;
  }
  const mode = "QMT 实盘快照";
  const fallback = result.fallback_reason ? ` · ${result.fallback_reason}` : "";
  banner.className = "source-banner live-source";
  banner.innerHTML = `<strong>${escapeHtml(mode)}</strong><span>${escapeHtml(result.source)} · 数据时间 ${escapeHtml(result.data_as_of)}${escapeHtml(fallback)}</span>`;
}

function renderPortfolio(result) {
  const portfolio = result.mode === "portfolio_optimization" && Array.isArray(result.portfolio) ? result.portfolio : [];
  $("#portfolio-wrap").classList.toggle("hidden", portfolio.length === 0);
  if (!portfolio.length) {
    $("#portfolio-body").innerHTML = "";
    return;
  }
  $("#portfolio-subtitle").textContent = `${result.summary.asset_count} 个资产中展示优化权重最高的 ${portfolio.length} 个`;
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
  $("#tw-kelly-subtitle").textContent = `${portfolio.length} 只标的 · 多头信号 ${result.summary.bull_count} 只 · 目标总仓位 ${formatNumber(result.summary.target_gross_exposure_pct, 2)}%`;
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
  $("#selection-subtitle").textContent = `${result.summary.optimized_universe_count} 只候选池中输出 ${selections.length} 只；覆盖完整组合权重 ${formatNumber(result.summary.selected_weight_coverage_pct, 2)}%`;
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

function renderOptions(result) {
  const opportunities = Array.isArray(result.opportunities) ? result.opportunities : [];
  $("#option-wrap").classList.toggle("hidden", opportunities.length === 0);
  if (!opportunities.length) {
    $("#option-body").innerHTML = "";
    return;
  }
  $("#option-subtitle").textContent = `${result.summary.contract_count} 张合约 · ${result.summary.underlying_count} 个标的族 · ${result.summary.box_combination_count} 个盒式组合`;
  $("#option-body").innerHTML = opportunities.map((item) => `
    <tr>
      <td class="rank">${item.rank}</td>
      <td><strong>${escapeHtml(item.underlying)}</strong><small>${item.remaining_days} 天</small></td>
      <td><span class="board-tag">${escapeHtml(item.exchange)}</span></td>
      <td>${escapeHtml(item.expiry_date)}</td>
      <td>${formatNumber(item.low_strike, 4)}</td>
      <td>${formatNumber(item.high_strike, 4)}</td>
      <td>${formatNumber(item.unit_fair_value, 6)}</td>
      <td>${formatNumber(item.unit_debit, 6)}</td>
      <td class="${item.absolute_gross_profit_cny >= 0 ? "positive" : "negative"}">${formatSigned(item.absolute_gross_profit_cny, 2)}</td>
      <td>${formatNumber(item.fees_cny + item.slippage_cny, 2)}</td>
      <td class="${item.true_net_profit_cny > 0 ? "positive" : "negative"}"><strong>${formatSigned(item.true_net_profit_cny, 2)}</strong></td>
      <td>${item.min_leg_volume}</td>
    </tr>`).join("");
}

function renderOrders(result) {
  const orders = Array.isArray(result.orders) ? result.orders : [];
  $("#orders-wrap").classList.toggle("hidden", orders.length === 0);
  $("#orders-body").innerHTML = orders.map((order) => {
    const code = order.code ?? order.ticker;
    const quantity = order.qty ?? order.quantity;
    const price = order.price ?? order.reference_price;
    const action = order.action ? (order.action === "open" ? "开仓" : "平仓") : "调仓";
    return `<tr><td>${escapeHtml(code)}</td><td class="trade-side ${escapeHtml(order.side)}">${order.side === "buy" ? "买入" : "卖出"}</td><td>${action}</td><td>${escapeHtml(quantity)}</td><td>${formatNumber(price, 4)}</td></tr>`;
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
      ["数据状态", "QMT 实盘快照"],
      ["可投资股票", summary.eligible_count],
      ["输出标的", summary.selected_count],
      ["组合权重覆盖", `${formatNumber(summary.selected_weight_coverage_pct, 2)}%`],
      ["预期主动收益", `${formatSigned(summary.expected_active_return_pct, 4)}%`],
      ["预期主动风险", `${formatNumber(summary.active_risk_pct, 4)}%`],
      ["优化后 IR", formatNumber(summary.optimized_information_ratio, 4)],
      ["基本定律 IR", formatNumber(summary.forecast_fundamental_law_ir, 4)],
      ["最大个股权重", `${formatNumber(summary.max_weight_pct, 2)}%`],
    ];
  }
  if (result.mode === "option_market_scan") {
    const summary = result.summary;
    return [
      ["数据状态", "QMT 实盘快照"],
      ["期权合约", summary.contract_count],
      ["标的族", summary.underlying_count],
      ["配对行权价", summary.paired_strike_count],
      ["盒式组合", summary.box_combination_count],
      ["真实净利润为正", summary.positive_opportunity_count],
      ["最优真实净利润", summary.best_true_net_profit_cny == null ? "—" : `${formatSigned(summary.best_true_net_profit_cny, 2)} 元`],
      ["最优净利润率", summary.best_net_profit_bps == null ? "—" : `${formatSigned(summary.best_net_profit_bps, 2)} bps`],
      ["可用买卖一合约", summary.bid_ask_contract_count],
    ];
  }
  if (result.mode === "portfolio_optimization") {
    const summary = result.summary;
    return [
      ["资产数量", summary.asset_count],
      ["展示持仓", summary.displayed_holding_count],
      ["预期主动收益", `${formatSigned(summary.expected_active_return * 100, 4)}%`],
      ["主动风险", `${formatNumber(summary.active_risk * 100, 4)}%`],
      ["优化后 IR", formatNumber(summary.optimized_information_ratio, 4)],
      ["基本定律 IR", formatNumber(summary.forecast_fundamental_law_ir, 4)],
      ["有效 IC", formatNumber(summary.effective_ic, 4)],
      ["换手率", `${formatNumber(summary.turnover * 100, 2)}%`],
      ["最大权重", `${formatNumber(summary.max_weight * 100, 2)}%`],
    ];
  }
  if (result.mode === "tw_kelly_rebalance") {
    const summary = result.summary;
    return [
      ["选股数量", summary.selected_count],
      ["多头信号", summary.bull_count],
      ["等待信号", summary.wait_count],
      ["空头信号", summary.bear_count],
      ["目标总仓位", `${formatNumber(summary.target_gross_exposure_pct, 2)}%`],
      ["目标现金", `${formatNumber(summary.target_cash_pct, 2)}%`],
      ["调仓单数", summary.proposed_order_count],
      ["模拟总资产", `¥${formatNumber(summary.total_asset, 0)}`],
      ["仓位方法", "二分之一凯利"],
    ];
  }
  if (result.mode === "market_data") return [["状态", result.regime], ["方向", result.direction], ["代理流入", `${formatNumber(result.total_net_flow_cny / 1e8, 2)} 亿元`], ["规模占比", `${formatNumber(result.flow_ratio_bps, 2)} bps`], ["强度分数", formatNumber(result.strength_score, 2)], ["ETF 数量", result.etf_count]];
  return Object.entries(result.summary || {}).slice(0, 9).map(([key, value]) => [key.replaceAll("_", " "), value]);
}

function renderError(message) {
  $("#result-area").classList.remove("hidden");
  $("#result-area").classList.add("error-message");
  $("#duration").textContent = "失败";
  $("#metric-grid").innerHTML = `<div class="metric"><span>ERROR</span><strong>${escapeHtml(message)}</strong></div>`;
  $("#source-banner").className = "source-banner hidden";
  $("#selection-wrap").classList.add("hidden");
  $("#option-wrap").classList.add("hidden");
  $("#portfolio-wrap").classList.add("hidden");
  $("#tw-kelly-wrap").classList.add("hidden");
  $("#orders-wrap").classList.add("hidden");
  $("#methodology-wrap").classList.add("hidden");
  $("#json-output").textContent = JSON.stringify({ error: message }, null, 2);
}

function formatNumber(value, precision = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(precision) : "—";
}

function formatSigned(value, precision = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  return `${number >= 0 ? "+" : ""}${number.toFixed(precision)}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
}

loadPrograms();
