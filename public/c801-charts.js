(() => {
  const isEnglish = document.documentElement.lang === "en";
  const palette = {
    csi300: "#ffffff",
    csi500: "#7DD3FC",
    csi1000: "#C4B5FD",
    micro400: "#F6C453",
  };
  const NS = "http://www.w3.org/2000/svg";
  const status = document.querySelector("#c801-chart-status");

  const svgNode = (name, attrs = {}, text = "") => {
    const node = document.createElementNS(NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    if (text) node.textContent = text;
    return node;
  };

  const formatDate = (value) => value.replaceAll("-", ".");
  const formatNav = (value) => value.toFixed(2);
  const formatDrawdown = (value) => `${(value * 100).toFixed(0)}%`;
  const marketLabel = (item) => isEnglish ? ({ csi300: "CSI 300", csi500: "CSI 500", csi1000: "CSI 1000", micro400: "Microcap 400" }[item.slug]) : item.market;

  function renderMetrics(series) {
    const body = document.querySelector("#c801-metrics-body");
    if (!body) return;
    body.replaceChildren();
    const percentage = (value) => Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%` : "—";
    series.forEach((item) => {
      if (!item.metrics) throw new Error(isEnglish ? "Factor metrics are missing" : "缺少因子评估指标");
      const metrics = item.metrics;
      const row = document.createElement("tr");
      const values = ["C801 v2", marketLabel(item), item.pit ? (isEnglish ? "Historical membership" : "逐时点历史成分") : (isEnglish ? "Fixed August 2026 cohort" : "2026年8月固定样本"), percentage(metrics.annualized_return), percentage(metrics.annualized_alpha), percentage(metrics.maximum_drawdown), Number.isFinite(metrics.rank_ic_mean) ? metrics.rank_ic_mean.toFixed(4) : "—", item.pit ? (isEnglish ? "Updated evaluation" : "更新评估") : (isEnglish ? "Sensitivity study" : "敏感性测试")];
      values.forEach((value, index) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        if ((index === 3 && metrics.annualized_return > 0) || (index === 4 && metrics.annualized_alpha > 0)) cell.className = "gain";
        row.append(cell);
      });
      body.append(row);
    });
  }

  function makeLegend(id, series) {
    const legend = document.querySelector(id);
    series.forEach((item) => {
      const label = document.createElement("span");
      label.innerHTML = `<i style="--series-color:${palette[item.slug]}"></i>${marketLabel(item)}${item.pit ? "" : "*"}`;
      legend.append(label);
    });
  }

  function drawChart(id, series, field, formatter) {
    const svg = document.querySelector(id);
    const width = 760;
    const height = 340;
    const margin = { top: 22, right: 24, bottom: 42, left: 58 };
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;
    const all = series.flatMap((item) => item.points.map((point) => Number(point[field])));
    let min = Math.min(...all);
    let max = Math.max(...all);
    const range = Math.max(max - min, 0.01);
    min = field === "drawdown" ? Math.min(min - range * 0.08, 0) : min - range * 0.08;
    max = field === "drawdown" ? 0 : max + range * 0.08;
    const maxPoints = Math.max(...series.map((item) => item.points.length));
    const x = (index, total) => margin.left + (index / Math.max(total - 1, 1)) * innerWidth;
    const y = (value) => margin.top + ((max - value) / (max - min)) * innerHeight;

    svg.replaceChildren();
    const grid = svgNode("g", { class: "factor-chart-gridlines" });
    for (let i = 0; i <= 4; i += 1) {
      const value = max - ((max - min) * i) / 4;
      const py = margin.top + (innerHeight * i) / 4;
      grid.append(svgNode("line", { x1: margin.left, x2: width - margin.right, y1: py, y2: py }));
      grid.append(svgNode("text", { x: margin.left - 12, y: py + 4, "text-anchor": "end" }, formatter(value)));
    }
    svg.append(grid);

    const firstDate = series[0].points[0].date;
    const lastDate = series[0].points[series[0].points.length - 1].date;
    svg.append(svgNode("text", { class: "factor-chart-date", x: margin.left, y: height - 12 }, formatDate(firstDate)));
    svg.append(svgNode("text", { class: "factor-chart-date", x: width - margin.right, y: height - 12, "text-anchor": "end" }, formatDate(lastDate)));

    series.forEach((item) => {
      const path = item.points
        .map((point, index) => `${index ? "L" : "M"}${x(index, item.points.length).toFixed(2)},${y(Number(point[field])).toFixed(2)}`)
        .join(" ");
      svg.append(
        svgNode("path", {
          class: `factor-series${item.pit ? "" : " is-static"}`,
          d: path,
          stroke: palette[item.slug],
        }),
      );
    });

    const focusLine = svgNode("line", {
      class: "factor-focus-line",
      y1: margin.top,
      y2: margin.top + innerHeight,
    });
    const focusBox = svgNode("g", { class: "factor-focus-box" });
    const box = svgNode("rect", { width: 164, height: 23 + series.length * 20, rx: 6 });
    focusBox.append(box);
    const dateText = svgNode("text", { x: 10, y: 18, class: "factor-focus-date" });
    focusBox.append(dateText);
    const valueTexts = series.map((item, index) => {
      const dot = svgNode("circle", { cx: 12, cy: 37 + index * 20, r: 3, fill: palette[item.slug] });
      const valueText = svgNode("text", { x: 22, y: 41 + index * 20 });
      focusBox.append(dot, valueText);
      return valueText;
    });
    svg.append(focusLine, focusBox);

    const pointer = svgNode("rect", {
      class: "factor-chart-pointer",
      x: margin.left,
      y: margin.top,
      width: innerWidth,
      height: innerHeight,
    });
    const setFocus = (event) => {
      const bounds = svg.getBoundingClientRect();
      const localX = ((event.clientX - bounds.left) / bounds.width) * width;
      const ratio = Math.max(0, Math.min(1, (localX - margin.left) / innerWidth));
      const guideX = margin.left + ratio * innerWidth;
      const masterIndex = Math.round(ratio * (maxPoints - 1));
      focusLine.setAttribute("x1", guideX);
      focusLine.setAttribute("x2", guideX);
      const first = series[0].points[Math.min(masterIndex, series[0].points.length - 1)];
      dateText.textContent = formatDate(first.date);
      series.forEach((item, index) => {
        const itemIndex = Math.round(ratio * (item.points.length - 1));
        valueTexts[index].textContent = `${marketLabel(item)}  ${formatter(Number(item.points[itemIndex][field]))}`;
      });
      const boxX = guideX > width - margin.right - 174 ? guideX - 172 : guideX + 8;
      focusBox.setAttribute("transform", `translate(${boxX} ${margin.top + 8})`);
      focusLine.classList.add("is-visible");
      focusBox.classList.add("is-visible");
    };
    pointer.addEventListener("pointermove", setFocus);
    pointer.addEventListener("pointerleave", () => {
      focusLine.classList.remove("is-visible");
      focusBox.classList.remove("is-visible");
    });
    svg.append(pointer);
  }

  fetch("/c801-backtest-series.json")
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      renderMetrics(data.series);
      makeLegend("#c801-nav-legend", data.series);
      makeLegend("#c801-dd-legend", data.series);
      drawChart("#c801-nav-chart", data.series, "nav", formatNav);
      drawChart("#c801-dd-chart", data.series, "drawdown", formatDrawdown);
      const starts = data.series.map((item) => item.start).sort();
      const ends = data.series.map((item) => item.end).sort();
      status.textContent = isEnglish ? `Data period ${formatDate(starts[0])}—${formatDate(ends.at(-1))}; charts and metrics come from the same run. * Microcap 400 retains the fixed August 2026 cohort as a sensitivity study.` : `数据区间 ${formatDate(starts[0])}—${formatDate(ends.at(-1))}；图表与指标来自同次评估。* 微盘400沿用2026年8月固定样本，仅作敏感性测试。`;
      if (data.series.every((item) => item.diagnostics?.exposure_coverage === 0)) {
        status.textContent += isEnglish ? " Industry and market-cap exposure coverage is 0%; neutralisation uses the disclosed fallback." : " 本次行业和市值暴露覆盖率为0%，中性化采用已披露的降级处理。";
      }
    })
    .catch((error) => {
      status.textContent = isEnglish ? `Backtest charts could not be loaded: ${error.message}` : `回测曲线暂未载入：${error.message}`;
      status.classList.add("is-error");
    });
})();
