const $ = (selector) => document.querySelector(selector);
const {isEnglish, t: translate, value: localize} = window.SiteLocale;
const factorFormat = {
  pcr: (v) => number(v, 3), margin: (v) => percentile(v), ivix: (v) => number(v, 2),
  new_high: (v) => percent(v, 2), basis: (v) => percentile(v), stock_bond: (v) => percentile(v),
};

fetch("/market-sentiment-data.json", { cache: "no-store" })
  .then((response) => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(render)
  .catch((error) => showNotice(translate(`数据读取失败：${error.message}`, `The data could not be loaded: ${localize(error.message)}`)));

function render(data) {
  const score = data.display_score == null ? Number.NaN : Number(data.display_score);
  const formal = data.status === "formal_complete";
  $("#generated-at").textContent = formatTime(data.generated_at);
  $("#target-date").textContent = translate(`数据日 ${data.target_date || "—"}`, `Data date ${data.target_date || "—"}`);
  $("#score-status").textContent = formal ? translate("正式同日六因子", "All six inputs share this date") : data.status === "asof_complete" ? translate("逐因子最近有效值", "Latest available input per factor") : translate("盘后暂定", "Provisional reading");
  $("#score").textContent = Number.isFinite(score) ? signed(score, 2) : "—";
  $("#score-label").textContent = localize(data.display_label);
  $("#score-caption").textContent = formal ? translate("六个维度同日完整", "Complete same-day observations") : data.status === "asof_complete" ? translate(`${data.carried_factor_count || 0} 项尚未发布，已自动回退`, `${data.carried_factor_count || 0} ${data.carried_factor_count === 1 ? "input uses" : "inputs use"} a prior valid release`) : translate(`有效覆盖 ${percent(data.signal_coverage, 0)}`, `${percent(data.signal_coverage, 0)} available coverage`);
  const left = Number.isFinite(score) ? Math.max(0, Math.min(100, (score + 1) * 50)) : 50;
  $("#meter-pin").style.left = `${left}%`;
  $("#bullish-count").textContent = data.bullish_signal_count ?? "—";
  $("#bearish-count").textContent = data.bearish_signal_count ?? "—";
  $("#coverage").textContent = percent(data.signal_coverage, 0);
  renderWeekly(data.weekly_comparison || {});
  renderChart(data.history || []);
  renderQRS(data.qrs || {});
  renderWeights(data.factors || []);
  renderQuality(data.quality || []);
  const messages = [];
  if (!formal) {
    const latestFormal = `${data.formal_date || "—"} (${signed(data.latest_formal_score, 2)})`;
    if (data.status === "asof_complete") messages.push(translate(`未发布或质量不足的指标已逐项采用此前最近有效交易日；最近一次六项同日完整分数为 ${latestFormal}。`, `Delayed or invalid inputs use their most recent valid prior observation. The last complete same-day score was ${latestFormal}.`));
    if (data.status === "provisional") messages.push(translate(`最近有效数据覆盖 ${percent(data.signal_coverage, 0)}；最近一次六项同日完整分数为 ${latestFormal}。`, `Available coverage is ${percent(data.signal_coverage, 0)}. The last complete same-day score was ${latestFormal}.`));
    if (data.status === "insufficient") messages.push(translate(`回退后数据覆盖仍不足，暂不输出可靠分数；最近一次六项同日完整分数为 ${latestFormal}。`, `Coverage remains too low to report a reliable score, even with prior observations. The last complete same-day score was ${latestFormal}.`));
  }
  if (data.refresh_errors?.length) messages.push(translate(`本次刷新警告：${data.refresh_errors.join("；")}`, `${data.refresh_errors.length} source ${data.refresh_errors.length === 1 ? "update" : "updates"} reported a warning. Available observations retain their actual data dates.`));
  if (messages.length) showNotice(messages.join(" "));
}

function renderWeekly(weekly) {
  const dates = weekly.dates || [], scores = weekly.daily_scores || [], rows = weekly.rows || [];
  if (!dates.length) return;
  $("#weekly-head").innerHTML = `<tr><th>${translate("指标 / 权重", "Indicator / weight")}</th>${dates.map((date) => `<th>${shortDate(date)}<br><small>${weekday(date)}</small></th>`).join("")}</tr>`;
  const scoreRow = `<tr class="score-row"><td>${translate("每日综合得分", "Daily composite score")}</td>${scores.map((item) => `<td><span class="daily-score">${signed(item.score, 2)}</span><span class="daily-label">${escapeHtml(localize(item.label || "数据不足"))}${item.carried_factor_count ? translate(` · ${item.carried_factor_count}项回退`, ` · ${item.carried_factor_count} carried`) : ""}</span></td>`).join("")}</tr>`;
  const factorRows = rows.map((row) => {
    const formatter = factorFormat[row.id] || ((value) => number(value, 3));
    const values = (row.values || []).map((item) => {
      const klass = item.signal === 1 ? "up" : item.signal === -1 ? "down" : "flat";
      const signalText = item.signal === 1 ? translate("+1 看多", "+1 Bullish") : item.signal === -1 ? translate("−1 看空", "−1 Bearish") : item.signal === 0 ? translate("0 中性", "0 Neutral") : translate("待发布", "Pending");
      const dateLine = item.carried_forward ? translate(`${shortDate(item.as_of_date)} · 回退${item.lag_sessions}日`, `${shortDate(item.as_of_date)} · ${item.lag_sessions} ${item.lag_sessions === 1 ? "session" : "sessions"} earlier`) : translate(`数据 ${shortDate(item.as_of_date)}`, `As of ${shortDate(item.as_of_date)}`);
      return `<td title="${escapeHtml(localize(item.quality_reason || "", "The latest valid prior observation is used."))}"><span class="factor-number">${formatter(item.value)}</span><span class="signal-chip ${klass}">${signalText}</span><span class="factor-date ${item.carried_forward ? "carried" : ""}">${dateLine}</span></td>`;
    }).join("");
    return `<tr><td><span class="factor-name">${escapeHtml(localize(row.label))}</span><span class="factor-weight">${translate("权重", "Weight")} ${(Number(row.weight) * 100).toFixed(0)}%</span></td>${values}</tr>`;
  }).join("");
  $("#weekly-body").innerHTML = scoreRow + factorRows;
}

function renderChart(history) {
  const svg = $("#history-chart");
  const valid = history.filter((item) => item.score != null && Number.isFinite(Number(item.score)));
  if (!valid.length) { svg.innerHTML = ""; return; }
  const width = 1000, height = 380, pad = { l: 55, r: 62, t: 34, b: 44 };
  const plotWidth = width - pad.l - pad.r, plotHeight = height - pad.t - pad.b;
  const x = (index) => pad.l + index * plotWidth / Math.max(1, valid.length - 1);
  const sentimentY = (value) => pad.t + (1 - (Number(value) + 1) / 2) * plotHeight;
  const marketValues = valid.flatMap((item) => [item.shanghai_rebased, item.csi300_rebased])
    .filter((value) => value != null).map(Number).filter(Number.isFinite);
  const rawMin = marketValues.length ? Math.min(...marketValues, 100) : 95;
  const rawMax = marketValues.length ? Math.max(...marketValues, 100) : 105;
  const marketPadding = Math.max(1, (rawMax - rawMin) * .1);
  const marketMin = rawMin - marketPadding, marketMax = rawMax + marketPadding;
  const marketY = (value) => pad.t + (marketMax - Number(value)) / (marketMax - marketMin) * plotHeight;
  const seriesPoints = (field, yScale) => valid.map((item, index) => {
    if (item[field] == null) return null;
    const value = Number(item[field]);
    return Number.isFinite(value) ? `${x(index).toFixed(1)},${yScale(value).toFixed(1)}` : null;
  }).filter(Boolean).join(" ");
  const scorePoints = seriesPoints("score", sentimentY);
  const shanghaiPoints = seriesPoints("shanghai_rebased", marketY);
  const csi300Points = seriesPoints("csi300_rebased", marketY);
  const grids = [-1, -.5, 0, .5, 1].map((value) => `<line class="${value === 0 ? "zero-line" : "grid-line"}" x1="${pad.l}" y1="${sentimentY(value)}" x2="${width - pad.r}" y2="${sentimentY(value)}"/><text class="axis-label" text-anchor="end" x="${pad.l - 9}" y="${sentimentY(value) + 4}">${signed(value, 1)}</text>`).join("");
  const thresholds = [.5, -.3].map((value) => `<line class="threshold-line" x1="${pad.l}" y1="${sentimentY(value)}" x2="${width - pad.r}" y2="${sentimentY(value)}"/>`).join("");
  const marketTicks = Array.from({ length: 5 }, (_, index) => marketMin + index * (marketMax - marketMin) / 4);
  const rightLabels = marketTicks.map((value) => `<text class="right-axis-label" x="${width - pad.r + 9}" y="${marketY(value) + 4}">${value.toFixed(1)}</text>`).join("");
  const labelPositions = [...new Set([0, Math.floor((valid.length - 1) / 2), valid.length - 1])];
  const dateLabels = labelPositions.map((index) => `<text class="date-label" text-anchor="${index === 0 ? "start" : index === valid.length - 1 ? "end" : "middle"}" x="${x(index)}" y="${height - 13}">${valid[index].date}</text>`).join("");
  const circles = valid.map((item, index) => `<circle class="score-point ${item.carried_factor_count ? "carried" : ""}" cx="${x(index)}" cy="${sentimentY(item.score)}" r="${index === valid.length - 1 ? 4.2 : 2.3}"/>`).join("");
  const hitWidth = Math.max(8, plotWidth / valid.length);
  const hits = valid.map((item, index) => `<rect class="chart-hit" data-index="${index}" x="${x(index) - hitWidth / 2}" y="${pad.t}" width="${hitWidth}" height="${plotHeight}"/>`).join("");
  svg.innerHTML = `<text class="axis-title" x="${pad.l}" y="16">${translate("情绪分", "Sentiment")}</text><text class="axis-title" text-anchor="end" x="${width - pad.r}" y="16">${translate("指数（首日=100）", "Indices (start = 100)")}</text>${grids}${thresholds}${rightLabels}${shanghaiPoints ? `<polyline class="market-line shanghai" points="${shanghaiPoints}"/>` : ""}${csi300Points ? `<polyline class="market-line csi300" points="${csi300Points}"/>` : ""}<polyline class="score-line" points="${scorePoints}"/>${circles}${dateLabels}${hits}`;
  $("#history-range").textContent = `${valid[0].date} — ${valid.at(-1).date} · ${valid.length} ${translate("个交易日", "trading sessions")}`;
  const tooltip = $("#chart-tooltip");
  svg.querySelectorAll(".chart-hit").forEach((hit) => {
    hit.addEventListener("pointerenter", (event) => showChartTooltip(event, valid[Number(hit.dataset.index)], tooltip));
    hit.addEventListener("pointermove", (event) => positionTooltip(event, tooltip));
    hit.addEventListener("pointerleave", () => { tooltip.hidden = true; });
  });
}

function showChartTooltip(event, item, tooltip) {
  const indexLine = (label, close, rebased, asOf, carried) => close == null ? `${label} —` : `${label} ${number(close, 2)} <span class="tooltip-market">(${number(rebased, 2)})${carried ? translate(` · 截至 ${asOf}`, ` · as of ${asOf}`) : ""}</span>`;
  tooltip.innerHTML = `<strong>${item.date}</strong><br>${translate("情绪", "Sentiment")} ${signed(item.score, 2)} · ${translate("覆盖", "coverage")} ${percent(item.coverage, 0)}${item.carried_factor_count ? `<br>${translate(`${item.carried_factor_count} 项情绪指标使用前序值`, `${item.carried_factor_count} inputs use prior observations`)}` : ""}<br>${indexLine(translate("上证", "Shanghai"), item.shanghai_close, item.shanghai_rebased, item.shanghai_as_of_date, item.shanghai_carried_forward)}<br>${indexLine(translate("沪深300", "CSI 300"), item.csi300_close, item.csi300_rebased, item.csi300_as_of_date, item.csi300_carried_forward)}`;
  tooltip.hidden = false;
  positionTooltip(event, tooltip);
}

function positionTooltip(event, tooltip) {
  const wrap = tooltip.parentElement.getBoundingClientRect();
  tooltip.style.left = `${Math.min(wrap.width - tooltip.offsetWidth - 6, Math.max(6, event.clientX - wrap.left + 12))}px`;
  tooltip.style.top = `${Math.max(6, event.clientY - wrap.top - tooltip.offsetHeight - 12)}px`;
}

function renderQRS(qrs) {
  const body = $("#qrs-body");
  const rows = Array.isArray(qrs.results) ? [...qrs.results] : [];
  const order = { "000001.SH": 0, "000300.SH": 1, "399006.SZ": 2 };
  rows.sort((a, b) => (order[a.index_code] ?? 99) - (order[b.index_code] ?? 99));
  $("#qrs-date").textContent = qrs.report_date ? translate(`数据截至 ${qrs.report_date}`, `Data through ${qrs.report_date}`) : translate("暂无可发布 QRS 数据", "No QRS observations are currently available");
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="7">${translate("暂无真实 QRS 数据；情绪得分仍可独立读取。", "QRS data is unavailable. The sentiment score remains independent and can still be read.")}</td></tr>`;
    return;
  }
  body.innerHTML = rows.map((item) => {
    const state = String(item.signal_state || "—");
    const stateClass = state === "多头" ? "long" : state === "空仓" ? "cash" : "neutral";
    const value = Number(item.qrs_value);
    const valueClass = Number.isFinite(value) && value > .15 ? "positive" : Number.isFinite(value) && value < -.15 ? "negative" : "inside-band";
    const diagnostics = item.diagnostics || {};
    const absorption = diagnostics.absorption_triggered ? `<small class="absorption">${translate("放量吸收已触发", "Volume absorption detected")}</small>` : "";
    return `<tr>
      <td><span class="qrs-name">${escapeHtml(localize(item.index_name || "—"))}</span><small>${escapeHtml(item.index_code || "—")} · ${escapeHtml(item.data_source || "—")}</small></td>
      <td class="qrs-close">${number(item.close, 2)}</td>
      <td><strong class="qrs-value ${valueClass}">${signed(item.qrs_value, 3)}</strong>${absorption}</td>
      <td><span class="qrs-state ${stateClass}">${escapeHtml(localize(state))}</span></td>
      <td>${escapeHtml(item.signal_date || "—")}</td>
      <td class="qrs-return ${Number(item.cum_return_since_signal) >= 0 ? "gain" : "loss"}">${percent(item.cum_return_since_signal, 2)}</td>
      <td>${percent(diagnostics.kernel_sigma, 2)}</td>
    </tr>`;
  }).join("");
}

function renderWeights(factors) { $("#factor-weights").innerHTML = factors.map((factor) => `<div class="weight-row"><span>${escapeHtml(localize(factor.label))}</span><b>${(Number(factor.weight) * 100).toFixed(0)}%</b></div>`).join(""); }
function renderQuality(rows) { const ok = rows.filter((row) => row.status === "OK").length; $("#quality-summary").textContent = `${ok}/${rows.length} ${translate("项完整", "complete")}`; $("#quality-list").innerHTML = rows.map((row) => `<div class="quality-row"><span>${escapeHtml(row.file || "—")}</span><b class="${row.status === "OK" ? "ok" : "warn"}">${escapeHtml(localize(row.status || "—"))}</b><small>${row.rows ?? 0} ${translate("行", "rows")}</small><small>${translate("截至", "Through")} ${row.end_date || "—"}</small></div>`).join(""); }
function showNotice(message) { const element = $("#notice"); element.textContent = message; element.classList.add("show"); }
function number(value, digits) { if (value == null || value === "") return "—"; const parsed = Number(value); return Number.isFinite(parsed) ? parsed.toFixed(digits) : "—"; }
function signed(value, digits) { if (value == null || value === "") return "—"; const parsed = Number(value); return Number.isFinite(parsed) ? `${parsed >= 0 ? "+" : ""}${parsed.toFixed(digits)}` : "—"; }
function percent(value, digits) { if (value == null || value === "") return "—"; const parsed = Number(value); return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(digits)}%` : "—"; }
function percentile(value) { if (value == null || value === "") return "—"; const parsed = Number(value); return Number.isFinite(parsed) ? `P${(parsed * 100).toFixed(1)}` : "—"; }
function formatTime(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(isEnglish ? "en-GB" : "zh-CN", { hour12: false, timeZone: "Asia/Shanghai" }) + " UTC+8"; }
function shortDate(value) { if (!value) return "—"; const parts = String(value).split("-"); return parts.length === 3 ? `${parts[1]}.${parts[2]}` : value; }
function weekday(value) { const date = new Date(`${value}T12:00:00+08:00`); return Number.isNaN(date.getTime()) ? "" : (isEnglish ? ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] : ["周日", "周一", "周二", "周三", "周四", "周五", "周六"])[date.getUTCDay()]; }
function escapeHtml(value) { return String(value).replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char])); }
