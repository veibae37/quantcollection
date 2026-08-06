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
  button.querySelector(".button-label").textContent = program.status === "ready" ? "运行程序" : "当前环境不可运行";
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
  label.textContent = "运行中";
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
    label.textContent = "再次运行";
  }
});

function renderResult(result, durationMs) {
  $("#result-area").classList.remove("hidden", "error-message");
  $("#duration").textContent = `${durationMs} ms`;
  $("#metric-grid").innerHTML = buildMetrics(result).map(([label, value]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");
  renderSource(result);
  renderSelections(result);
  renderOptions(result);
  renderOrders(result);
  renderMethodology(result);
  $("#json-output").textContent = JSON.stringify(result, null, 2);
  $("#result-area").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderSource(result) {
  const banner = $("#source-banner");
  if (!["a_share_selection", "option_market_scan"].includes(result.mode)) {
    banner.className = "source-banner hidden";
    banner.textContent = "";
    return;
  }
  const mode = result.is_synthetic ? "演示数据" : "实时快照";
  const fallback = result.fallback_reason ? ` · ${result.fallback_reason}` : "";
  banner.className = `source-banner ${result.is_synthetic ? "synthetic" : "live-source"}`;
  banner.innerHTML = `<strong>${escapeHtml(mode)}</strong><span>${escapeHtml(result.source)} · 数据时间 ${escapeHtml(result.data_as_of)}${escapeHtml(fallback)}</span>`;
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
      <td>${formatNumber(item.fair_value, 6)}</td>
      <td>${formatNumber(item.net_debit, 6)}</td>
      <td class="${item.profit_per_unit >= 0 ? "positive" : "negative"}">${formatSigned(item.profit_per_unit, 6)}</td>
      <td class="${item.profit_bps >= 0 ? "positive" : "negative"}">${formatSigned(item.profit_bps, 2)} bps</td>
      <td>${item.min_leg_volume}</td>
      <td><span class="board-tag">${item.quote_basis === "bid_ask" ? "买卖一" : "最新价代理"}</span></td>
    </tr>`).join("");
}

function renderOrders(result) {
  const orders = Array.isArray(result.orders) ? result.orders : [];
  $("#orders-wrap").classList.toggle("hidden", orders.length === 0);
  $("#orders-body").innerHTML = orders.map((order) => `<tr><td>${escapeHtml(order.code)}</td><td class="trade-side ${escapeHtml(order.side)}">${order.side === "buy" ? "买入" : "卖出"}</td><td>${order.action === "open" ? "开仓" : "平仓"}</td><td>${escapeHtml(order.qty)}</td><td>${formatNumber(order.price, 4)}</td></tr>`).join("");
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
      ["数据状态", result.is_synthetic ? "演示快照" : "实时快照"],
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
      ["数据状态", result.is_synthetic ? "演示快照" : "实时快照"],
      ["期权合约", summary.contract_count],
      ["标的族", summary.underlying_count],
      ["配对行权价", summary.paired_strike_count],
      ["盒式组合", summary.box_combination_count],
      ["正偏差机会", summary.positive_opportunity_count],
      ["最优单位收益", summary.best_profit_per_unit == null ? "—" : formatSigned(summary.best_profit_per_unit, 6)],
      ["最优收益偏差", summary.best_profit_bps == null ? "—" : `${formatSigned(summary.best_profit_bps, 2)} bps`],
      ["可用买卖一合约", summary.bid_ask_contract_count],
    ];
  }
  if (result.mode === "demo") return [["套利机会", result.has_opportunity ? "满足条件" : "未触发"], ["盒式收益", result.box_profit == null ? "—" : formatNumber(result.box_profit, 6)], ["模拟订单", result.orders.length], ["利率", `${formatNumber(result.input.interest_rate * 100, 2)}%`], ["触发阈值", result.input.actionpoint], ["数据来源", "内置模拟盘口"]];
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
