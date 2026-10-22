const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const publicDirectory = path.join(__dirname, "..", "public");
const read = (filename) => fs.readFileSync(path.join(publicDirectory, filename), "utf8");
const cjk = /[\u4e00-\u9fff]/;

class Element {
  constructor(selector) {
    this.selector = selector;
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.dataset = {};
    this.listeners = {};
    this.textContent = "";
    this.innerHTML = "";
    this.clientWidth = 700;
    this.value = "";
    this.classList = {add() {}, remove() {}, toggle() {}};
  }
  append(...children) { this.children.push(...children); }
  appendChild(child) { this.append(child); }
  replaceChildren(...children) { this.children = children; }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return this.attributes[key]; }
  addEventListener(name, listener) { this.listeners[name] = listener; }
  querySelector(selector) { return this.child || (this.child = new Element(selector)); }
  querySelectorAll() { return []; }
  scrollIntoView() {}
  insertAdjacentHTML(position, content) { this.innerHTML += content; }
}

function environment(language = "en", pathname = "/en", search = "", hash = "", fetcher = async () => ({ok: true, json: async () => ({})})) {
  const nodes = new Map();
  const link = new Element(".language-toggle");
  const location = {pathname, search, hash};
  const document = {
    documentElement: {lang: language},
    querySelector(selector) {
      if (!nodes.has(selector)) nodes.set(selector, new Element(selector));
      return nodes.get(selector);
    },
    querySelectorAll(selector) { return selector === ".language-toggle" ? [link] : []; },
    createElement(tag) { return new Element(tag); },
    createElementNS(namespace, tag) { return new Element(tag); },
  };
  const context = vm.createContext({document, location, URLSearchParams, Date, console, fetch: fetcher, setTimeout, clearTimeout, addEventListener() {}, history: {replaceState(state, title, url) {
    const parsed = new URL(url, "https://example.com");
    Object.assign(location, {pathname: parsed.pathname, search: parsed.search, hash: parsed.hash});
  }}});
  context.window = context;
  vm.runInContext(read("site-locale.js"), context);
  return {context, nodes, link};
}

async function runScript(filename, options = {}) {
  const fixture = environment(options.language, options.pathname, options.search, options.hash, options.fetcher);
  vm.runInContext(read(filename), fixture.context);
  await new Promise((resolve) => setImmediate(resolve));
  return fixture;
}

function assertEnglish(node) {
  assert.equal(cjk.test(String(node.textContent) + node.innerHTML), false, node.selector);
}

test("language switches preserve the page, query and fragment in both directions", () => {
  for (const page of ["", "/backtest", "/market-sentiment", "/hk-factor-lab"]) {
    const query = "?market=csi1000&trainMonths=24&testMonths=6&slippageBps=10";
    const english = environment("en", `/en${page}`, query, "#research-engine");
    assert.equal(english.link.getAttribute("href"), `${page || "/"}${query}#research-engine`);
    const chinese = environment("zh-CN", page || "/", query, "#research-engine");
    assert.equal(chinese.link.getAttribute("href"), `/en${page}${query}#research-engine`);
  }
  const fixture = environment("en", "/en/backtest");
  fixture.context.location.search = "?mode=manual&topK=100";
  fixture.link.listeners.click();
  assert.equal(fixture.link.getAttribute("href"), "/backtest?mode=manual&topK=100");
});

test("backtest controls and results are localised without changing calculations", async () => {
  const bundle = JSON.parse(read("backtest-grid.json"));
  const snapshots = [];
  for (const language of ["en", "zh-CN"]) {
    const fixture = await runScript("backtest.js", {language, pathname: language === "en" ? "/en/backtest" : "/backtest", search: "?market=csi1000&mode=auto&trainMonths=24&testMonths=6&maWindow=180&volWindow=20&holdDays=5&topK=50&commissionBps=2&stampDutyBps=5&slippageBps=10", fetcher: async () => ({ok: true, json: async () => bundle})});
    const evaluated = vm.runInContext("JSON.stringify((()=>{const settingsValue=settings();const selected=chooseParameters(settingsValue);return {selected, metrics:periodMetrics(splitRows(settingsValue.market,selected,settingsValue).test,selected.holdDays,costs(settingsValue))};})())", fixture.context);
    snapshots.push(evaluated);
    assert.ok(fixture.nodes.get("#metric-cards").innerHTML.includes(language === "en" ? "Annualised excess return" : "年化超额收益"));
    if (language === "en") {
      for (const node of fixture.nodes.values()) assertEnglish(node);
      assert.ok(fixture.link.getAttribute("href").startsWith("/backtest?market=csi1000"));
      fixture.nodes.get("#mode").value = "manual";
      vm.runInContext("render()", fixture.context);
      assert.match(fixture.nodes.get("#mode-note").textContent, /Exploratory mode/);
      fixture.nodes.get("#testMonths").value = 0;
      vm.runInContext("render()", fixture.context);
      assert.match(fixture.nodes.get("#metric-cards").innerHTML, /Too few rebalance periods/);
    }
  }
  assert.equal(snapshots[0], snapshots[1]);
});

test("sentiment tables, delayed inputs, QRS, chart tooltips and notices use English", async () => {
  const data = JSON.parse(read("market-sentiment-data.json"));
  const fixture = await runScript("market-sentiment.js", {pathname: "/en/market-sentiment", fetcher: async () => ({ok: true, json: async () => data})});
  for (const node of fixture.nodes.values()) assertEnglish(node);
  assert.match(fixture.nodes.get("#weekly-body").innerHTML, /50ETF option put–call ratio/);
  assert.match(fixture.nodes.get("#qrs-body").innerHTML, /Shanghai Composite/);
  assert.match(fixture.nodes.get("#qrs-body").innerHTML, /Cash/);
  assert.match(fixture.nodes.get("#weekly-body").innerHTML, /sessions? earlier/);
  fixture.context.positionTooltip = () => {};
  const tooltip = new Element("tooltip");
  fixture.context.showChartTooltip({}, data.history.at(-1), tooltip);
  assertEnglish(tooltip);
  for (const status of ["formal_complete", "asof_complete", "provisional", "insufficient"]) {
    fixture.context.render({...data, status, refresh_errors: ["源数据延迟"]});
    assertEnglish(fixture.nodes.get("#notice"));
  }
  fixture.context.renderQRS({});
  assert.match(fixture.nodes.get("#qrs-body").innerHTML, /QRS data is unavailable/);
  const chinese = await runScript("market-sentiment.js", {language: "zh-CN", fetcher: async () => ({ok: true, json: async () => data})});
  assert.match(chinese.nodes.get("#weekly-body").innerHTML, /50ETF 期权 PCR/);
});

test("all twelve Hong Kong factors, checks and unavailable-data states use reviewed English", async () => {
  const fixture = await runScript("hk-factor-lab.js", {pathname: "/en/hk-factor-lab", fetcher: async () => ({ok: false, json: async () => ({ok: false, error: "QMT 当前未提供境内外一致预期、股东户数及共同分析师网络字段，未生成港股因子值"})})});
  assert.equal(fixture.nodes.get("#factor-list").children.length, 12);
  assert.equal(fixture.nodes.get("#test-grid").children.length, 12);
  const factors = vm.runInContext("factors", fixture.context);
  for (const factor of factors) {
    fixture.context.selectFactor(factor.key);
    assertEnglish(fixture.nodes.get("#detail-name"));
    assertEnglish(fixture.nodes.get("#detail-description"));
    assert.ok(!fixture.nodes.get("#detail-description").textContent.includes("See the original"));
  }
  assert.match(fixture.nodes.get("#live-status").innerHTML, /point-in-time consensus forecasts/);
  for (const node of fixture.nodes.values()) assertEnglish(node);
  fixture.context.renderLiveTable({rows: []}, {stale: false, generated_at: "2026-10-22T15:00:00+08:00", snapshot_age_seconds: 1});
  assert.match(fixture.nodes.get("#live-content").innerHTML, /no Hong Kong factor records/);
  fixture.context.renderLiveTable({rows: [{ticker: "0005.HK", dual_gap_eps: 0.1}]}, {stale: true, generated_at: "2026-10-22T15:00:00+08:00", snapshot_age_seconds: 1000});
  assert.match(fixture.nodes.get("#live-status").innerHTML, /freshness limit/);
  assertEnglish(fixture.nodes.get("#live-content"));
});

test("dashboard explanations are English while original JSON remains unchanged", async () => {
  const fixture = await runScript("app.js", {fetcher: async () => ({ok: true, json: async () => ({ok: true, config: {subtitle: "研究界面", notice: "只读", python: "3.12"}, programs: [{id: "a_share_selector", status: "ready", file: "a_share_selector.py", parameters: []}]})})});
  const result = {mode: "market_data", is_synthetic: false, source: "AKShare ETF历史日线 + 腾讯当日收盘成交额（真实行情）", source_details: {fallback_used: true, provider: "AKShare / 新浪财经 / 东方财富 / 腾讯财经", frequency: "日线；最近完整交易日"}, data_as_of: "2026-10-22T15:00:00+08:00", regime: "VOLUME_EXPANSION", direction: "OUTFLOW_PROXY", total_net_flow_cny: -100, flow_ratio_bps: 1, strength_score: 1, etf_count: 3, methodology: {source_boundary: "MiniQMT不可用时只替换为AKShare公开真实日线，计算公式不变"}};
  fixture.context.renderResult(result, 1);
  assert.equal(fixture.nodes.get("#json-output").textContent, JSON.stringify(result, null, 2));
  for (const [selector, node] of fixture.nodes) if (selector !== "#json-output") assertEnglish(node);
  assert.match(fixture.nodes.get("#metric-grid").innerHTML, /Outflow proxy/);
  assert.match(fixture.nodes.get("#methodology-content").innerHTML, /calculation is unchanged/);
});
