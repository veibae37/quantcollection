# 杂志主题交付

研究页面统一加载 `public/editorial.css` 和 `public/editorial-nav.js`，保留原业务脚本及数据接口。中文首页通过 `English` 入口访问 `/en`，英文首页通过 `中文` 返回 `/`。

## 生产部署与版本一致性

`veibaequant.cn` 使用现有 Vercel 项目。GitHub `main` 的提交会触发生产部署，因此必须将页面、共享样式、脚本、公开图表数据及 `vercel.json` 的路由一起保存在 `main`。只在本机通过 CLI 发布页面、随后向仍含旧前端的 `main` 提交文档，可能使生产域名再次显示旧版。

发布后检查 `/`、`/en`、`/backtest`、`/market-sentiment` 和 `/hk-factor-lab`，确认静态资源可访问、中英文入口互通、原有只读 API 继续可用。首页名称由各语言页面自身定义，避免旧 API 配置覆盖新界面的标题。恢复界面不代表更新历史研究数据，页面仍应保留实际数据日期。

## 页面与资源

- `public/editorial.css`：全局颜色、衬线正文、无衬线控件、780px 正文 + 260px 侧栏、响应式导航和深色图表。
- `public/navigation.html`：完整导航 HTML，引用上述 CSS/JS 即可使用。现有页面已直接内嵌此导航，无需额外请求。
- `public/editorial-nav.js`：桌面 Hover/点击、Escape 收起、方向键进入、焦点离开收起、当前栏目标记；手机汉堡及手风琴。
- `public/backtest.js`：原 SVG 回测图改为白色/冰蓝折线、弱虚线网格，并基于真实显示序列计算最大回撤标注。
- `public/chart-example.html` + `public/chart-example.js`：完整 ECharts 示例，访问 `/chart-example.html`。含深蓝卡片、白线、垂直事件虚线和说明标签；明确标记为演示数据，未混入真实回测。

字体通过 Google Fonts 加载 Merriweather 和 Inter；网络不可用时回退 Georgia、宋体与系统无衬线字体。ECharts 示例使用固定版本 5.6.0 的 CDN，失败时显示提示及可读数据；生产回测 SVG 不依赖 CDN。

图表容器通过 ResizeObserver 自适应，参考 [ECharts 官方容器尺寸文档](https://echarts.apache.org/handbook/en/concepts/chart-size/)。

数据更新由 `daily_market_sentiment.py --no-deploy` 完成。浏览器刷新仅重读发布的数据文件，不会自行重新采集行情；应先运行更新脚本、发布数据，再刷新页面。实际数据日期及回退维度仍由原脚本输出。
