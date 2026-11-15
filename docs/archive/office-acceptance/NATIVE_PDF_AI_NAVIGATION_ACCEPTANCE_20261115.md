# PDF goto_page 与助手 UI 对齐验收（2026-11-15）

来源固定为 GenOffice f8c17004。用户继续要求工具与 UI 同时对齐、可复用来源 UI、用户端不可选择模型；实现复用现有 Agno 与网页编辑器，不搬入桌面 AgentLoop。

## PDF 工具

阅读客户端捕获 viewPageId，明确支持跳页后才注册 goto_page(page)。整数页号从 1 开始，使用 StrictInt 避免 Agno 自动将布尔、字符串、浮点转换后绕过类型验证。冻结选区继续限制可导航页面；无效目标不登记导航，不修改文件、不增加正文读取覆盖，也不生成引用。纯导航仍保留无阅读证据提示。模型最终 schema 仅含 answer/citations，可信目标来自阅读器自己的状态。

沿用既有阅读工具的草稿页码：存在投影时 page 是 effective 页号。导航将实际应用的重排、删除、插入空白页顺序映射到宿主稳定 pageId，浏览器验证当前顺序和 ID 匹配。来源桌面使用原文件页号，属于明确的网页适配差异；不直接拿投影页号猜原始页。

viewPageId 绑定请求幂等身份，旧客户端省略时不增加规划器参数或改变摘要。阅读证据／追问身份仍只由原件、草稿及授权选区决定，跳页后可继续理解同一授权文档上的指代，且上轮对话仍只是待重新核验的上下文。

服务端返回 navigation_requested。浏览器先验证来源、草稿、选区、捕获的当前页及任务生命周期，再调用现有真实页面导航。下一帧检查实际活动页、页面 DOM 身份和视口交集后才显示“已定位”。编辑模式、搜索渲染、预览、打印、保存、未提交编辑和过期任务不跳页；失败保留阅读答案并明确说明，取消或卸载不能显示迟到成功。旧引用按钮行为保留。

## 共用助手 UI

按固定来源 PDF/docs/slides AiPanel 的 48px 规则适配现有共用侧栏：在底部时跟随新回答和工具进度，向上阅读时保持位置。新对话和每次接受新任务均恢复跟随；七类阅读／编辑控制器及预设任务统一接入 beforeTask。隐藏期间完成的任务重新展开后等待实际布局帧再滚到最新内容，保留手工停止跟随，并在卸载时清理观察器、监听器和待执行帧。

沿用既有来源布局、图标和授权范围控件；明确不搬入来源模型选择器。用户端 composer 不显示模型选择、combobox；模型由服务端配置。另修复既有 PDF Home 打印命令已注册但按钮未挂入 Ribbon 的问题，两项原有打印入口测试先失败后通过。

## 测试与复核

后端 64 项相关节点分批通过，包含真实 Agno 调用和严格类型、API 与请求身份、阅读和引用覆盖、原生 PDF 重排／删除／空白页真实投影、取消以及跨页追问。前端 149 项相关节点分批通过，覆盖真实宿主状态、实际 DOM 目标检查、异步布局、阅读／批注／表单／Word／XLSX／PPTX 控制器与共用 UI。

独立复核发现的 Agno 强制转换、编辑模式仍允许跳页、接受新任务不恢复跟随均已通过 RED→GREEN 修复。隐藏完成后的重新展开问题按现有“收起时任务继续”行为提高优先级，面板及其父停靠栏异步展开均有失败后通过的回归。较早的 PPTX 样式测试夹具返回了不同任务 ID，按新的任务身份契约修正夹具，不削弱生产校验。

首次生产构建通过但共享 PDF 控件块为 251.2 KiB，超出原有 250 KiB 限额；将既有 pdf-extract-dialog 保留为独立构建边界，不提高预算。后续构建及预算通过；最终验证记录另列。未重复完整测试套件。

## 实际浏览器证据与范围

脚本 frontend/smoke/pdf-ai-navigation-smoke.mjs 使用真实原生授权、HTTP、工作区、Agno 和 PDF.js；模型为 ScriptedModel、修订查询为限定内存实现，不计为真实外部模型或生产数据库验收。源 PDF 的第 2 页 contains “Second page: expenses are 12.”；检查实际 DOM、活动页及页码控件，截图人工核对目标文字可见。无编辑权限的阅读器仍能跳页；原件 SHA 和本地草稿不变，没有编辑 preview、采纳或保存 POST，没有页面错误。

工具全量一对一对齐和全部 UI 对齐仍在继续；本轮不声称其他 PDF 编辑工具或桌面即时回执已完成。

最终联合构建：npm run build（TypeScript + Vite）及 check:budget 通过，未提高资源预算。最终真实浏览器 /workspace/scratch/pr245-pdf-ui-verified-browser/evidence.json、navigated.png、reopened.png 通过并人工检查：第 2 页费用文字实际可见；第二次任务收起后完成，再展开实际停靠栏跟随到最新回答；70 个加载 JS/CSS 的 SHA 与磁盘构建一致，无页面错误、无编辑 preview/采纳/保存 POST、无用户模型选择控件。跳页后的授权追问身份分离回归也已通过。

复跑命令：

```sh
PDF_AI_NAVIGATION_DIRECTORY=/tmp/pr245-pdf-navigation \
PDF_AI_NAVIGATION_PORT=4369 \
REPORT_EDITOR_CHROMIUM_EXECUTABLE=/usr/bin/chromium \
node smart_reporting/report_editor/frontend/smoke/pdf-ai-navigation-smoke.mjs
```
