# Host 报告编辑器设计

## 目标

基于 `feat/matplotlib-code-mode-host` 增加发布后可编辑的智能报告 Page。页面使用 Milkdown Crepe 提供笔记本式所见即所得编辑，权威内容仍为 Markdown；用户可保存草稿并导出新的 PDF/Word revision。报告不再生成、持久化或发布 HTML 产物。

## 范围

- 只修改 `smart_reporting`，本期不修改 DSH 插件。
- 直接使用该分支持久保留的 Host workspace，不设计 sandbox、source bundle 或原始数据恢复。
- 首版不集成 Plotly.js、动态图表或任意 JavaScript；现有 PNG/JPEG 图表继续作为图片显示和导出。
- 首版 AI 只处理用户明确选择的正文，不提供整篇生成、光标续写或自由问答。
- PC 和移动端均可编辑；移动端采用单栏、精简工具栏和稳定触控尺寸。

## 数据与版本

- 已发布 revision 永不原地覆盖。
- 打开编辑器时从 Reporting durable state 解析当前 report、scope、workspace key、Markdown 路径和渲染上下文，并重新注册既有 Host workspace。
- 草稿保存在同一报告目录下的 `draft/`，保存使用 Markdown SHA-256 CAS；并发覆盖返回冲突。
- 导出从草稿生成 `revision-N+1` 的 PDF 和 Word，完成现有双格式验收后持久化并签发新下载授权。
- 用户编辑属于发布后人工修订，记录 revision、基础 Markdown SHA-256、编辑后 SHA-256、时间和身份；语义变化产生软告警，不阻断导出。

## 编辑页面

- 使用 `@milkdown/crepe`，通过项目内前端构建生成同源静态资源，不依赖 CDN。
- 使用 Crepe 官方主题结构和 CSS 变量完成品牌化，并按启用的 feature 加载样式，避免携带未使用的 CodeMirror 和 KaTeX 资源。
- 默认是笔记本式所见即所得页面，不要求普通用户理解 Markdown。
- `[[section:*]]` 是隐藏的结构节点；`[[citation:*]]` 显示为只读引用标签。序列化时必须无损恢复协议标记。
- 原始 HTML、脚本、事件属性和外部资源不可执行；图片只从当前报告的受控资源端点读取。
- 页面提供保存状态、显式保存、导出 PDF、导出 Word和冲突提示。

## 选区 AI 改写

- 使用 Crepe 官方 AI feature 提供流式改写和 Diff Review，不自行实现流式编辑、差异接受或回滚交互。
- 仅在选区非空时允许调用，首版提供润色表达、精简内容、扩写说明和专业报告语气四个固定动作。
- 选区包含 `[[section:*]]` 或 `[[citation:*]]` 时拒绝调用；AI 输出仍受现有协议标记 ProseMirror 插件保护。
- 浏览器只调用同源报告编辑 API。服务端从编辑会话恢复 report、revision、database、company、user 和 workspace 身份，并复用现有 Agno/OpenAI-compatible 模型配置流式返回 Markdown。
- 模型 API Key 只存在于服务端；不写入浏览器、URL、Cookie、日志或 durable editor context。
- AI 返回内容先进入 Diff Review，用户接受后才成为编辑器正文；接受后的内容继续使用现有 800ms 自动保存和 SHA-256 CAS，不自动导出新 revision。
- 请求限制选区和指令大小；上游取消、超时或失败时回滚未接受内容并显示软错误，不改变磁盘草稿。

## HTTP 与授权

- 新增独立编辑 grant，与公开下载 grant 分离，绑定 report、revision、database、company、user 和 Host workspace。
- `editor.openUrl` 携带短期一次性 grant；首次打开后交换为 HttpOnly、Secure（生产）、SameSite=Strict 的编辑会话 Cookie，并重定向到无 token URL。
- 编辑 API 校验会话 scope、Origin/CSRF、报告身份和 revision；token、capability 不写入 URL 查询、localStorage 或日志。
- AI API 复用同一编辑会话、Origin 和 CSRF 边界，不新增浏览器 bearer token。
- 首版提供后端 Page 与 API，DSH 如何展示 `editor.openUrl` 后续实现。

## 服务端契约

- MCP/发布结果从 `html.previewUrl` 改为 `editor.openUrl`，PDF/Word 字段不变。
- `ReportRuntime.render_markdown` 和 `validate_pdf` 只生成/验收 PDF 与 Word。
- artifact persistence 只持久化 PDF 与 Word；删除 HTML 下载路由和 HTML artifact 分支。
- 新增 Host report editor service，负责恢复 scope、读取/保存草稿和触发新 revision 渲染；不复制 Reporting Workflow 的分析流程。
- 新增选区 AI provider 适配层，仅负责校验编辑上下文、调用现有模型配置并输出 Markdown 流；不参与报告发布和 artifact persistence。

## 验收

- 发布结果没有 `html`，包含 `editor.openUrl`。
- 编辑 grant 不能作为下载 grant 使用，过期、复用或 scope 不匹配均拒绝。
- Markdown CAS 冲突不会覆盖磁盘内容。
- 协议标记在编辑器载入/保存后无损；恶意 HTML 不执行。
- AI 仅对非空且不含协议标记的选区生效，流式结果可接受、拒绝或取消，拒绝和失败不改变草稿。
- 浏览器请求不包含模型 API Key；AI API 仍通过编辑会话、Origin 和 CSRF 校验。
- PDF/Word 新 revision 通过现有 runtime 定向测试。
- Page 在 PC 与移动 viewport 无横向页面溢出、按钮和文本不重叠。
