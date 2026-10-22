# 杂志主题交付

研究页面统一加载 `public/editorial.css`、`public/site-locale.js` 和 `public/editorial-nav.js`，保留原业务脚本及数据接口。每个页面均可通过 `English` / `中文` 切换到同一研究的另一语言版本；导航与侧栏保持当前语言，回测参数及页内锚点随切换保留。

## 中英文页面

- 首页：`/` 与 `/en`。
- 样本外测试：`/backtest` 与 `/en/backtest`。
- 市场情绪：`/market-sentiment` 与 `/en/market-sentiment`。
- 港股因子：`/hk-factor-lab` 与 `/en/hk-factor-lab`。

英文研究页使用 `locales/pages.en.json` 中逐条审核的文案生成，动态标签、图表提示、数据不可用提示和因子说明由共享语言模块及各业务脚本处理。不调用在线机翻，也不改变数据、公式、信号或信息时点。股票名称保留交易所原名，原始 JSON 保留源语言以便核验。

中文结构或静态文案变更后，先更新英文文案字典，再使用 `build_english_pages.py --patch` 生成补丁；通过补丁应用工具更新生成页面。`python build_english_pages.py` 检查生成页是否同步；新增但未经审核的中文会让构建失败，而不是静默漏译。

检查命令：`python -m unittest tests.test_site_localization`、`node --test tests/site_localization.test.js`、`python verify_editorial.py`。前端测试覆盖参数保留、英文动态结果、延迟数据、十二项港股因子和源语言 JSON 保留，并对照两种语言的回测数值。

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
