# Reporting 三格式交付设计

## 目标

Reporting 同时提供 PDF、Word（DOCX）和 HTML 三种正式报告产物。三种产物必须来自同一份已验收 Markdown，并作为同一 revision 原子发布。

HTML 在 AgentOS HTTP 服务中支持浏览器内联预览，在 Reporting CLI 中返回工作区相对路径。

## 范围与兼容性

- 保留现有 PDF、Word 生成逻辑、下载路径和回执字段。
- 为 HTML 增加正式产物身份、持久化记录、下载/预览 URL 和 CLI 路径。
- 不新增独立前端，不在请求时依赖已清理的 Daytona sandbox 动态生成 HTML。
- 不修改报告业务数据、Workflow ID、数据库 schema 名称或权限模型。
- 现有双格式调用方继续可读取 `pdf`、`word` 字段；三格式完整成功时额外返回 `html`。

## 架构与数据流

1. `ReportRuntime.render_markdown` 解析并校验 Markdown，复用现有文档上下文、标题锚点、目录和视觉主题。
2. 运行时从同一正文生成 PDF、DOCX 和静态 HTML。HTML 使用独立 `.html` 文件，不引用 sandbox 相对路径。
3. HTML 只允许服务端生成的安全内容：Markdown 原始 HTML 已禁用；脚本、表单、外部资源和插件能力全部禁止；已登记图片转为内嵌 data URL。
4. `WorkspaceReportService` 在同一 revision 临时目录暂存三件产物，分别计算大小和 SHA-256，完成三格式联合验收后执行原子目录发布。
5. HTTP Reporting 发布将三件产物流式固化到现有 PostgreSQL artifact 存储，再签发同一个 bearer grant。artifact 类型扩展为 `pdf`、`word`、`html`，不修改现有 grant 表结构。HTML 由 artifact repository 按 grant 已绑定的完整 scope、report、revision 和 `html` 类型精确解析，再使用该记录的大小和 SHA-256 校验内容。
6. AgentOS 暴露 `/reports/v1/download/{grant}/html`。该端点复用现有 grant 的有效期、撤销状态和作用域约束，并验证 HTML artifact 的身份，返回 `text/html; charset=utf-8` 与 `Content-Disposition: inline`。
7. CLI 完成回执增加 `htmlPath`、`htmlSize`、`htmlSha256`；HTTP 回执增加 `html.previewUrl`。HTML 链接不可替代 PDF/Word 下载链接。

## 安全响应约束

HTML 预览响应设置：

- `Content-Security-Policy: sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'`
- `X-Content-Type-Options: nosniff`
- `Cache-Control: no-store`
- `X-Accel-Buffering: no`

不把原始 HTML、bearer token 或敏感业务字段写入日志。授权过期、撤销、scope 不匹配、artifact 缺失或哈希不一致时拒绝响应。

## 失败处理

- HTML 生成失败、资源无法内嵌、文件超限或三格式身份不一致时，整批 revision 拒绝发布。
- 联合验收失败时不签发 HTTP grant，不删除仍需诊断的 sandbox；沿用现有失败清理契约。
- 持久化成功前不删除 sandbox；持久化或清理失败时保持现有失败关闭行为。
- HTTP 预览只在 artifact 已持久化且 grant 有效时提供，不回退到工作区路径。

## 测试与验证

定点测试覆盖：

- HTML 文档生成、目录/标题锚点、图片 data URL 和脚本/外链/表单拒绝。
- 三格式暂存、联合验收、哈希校验和 revision 原子发布/失败回滚。
- PostgreSQL artifact 的 `html` 持久化、流式读取及篡改/大小边界拒绝。
- HTML HTTP 路由的 media type、inline disposition、安全响应头、过期和无效 grant。
- HTTP/CLI 完成回执以及 Agent 展示三个入口。

验证顺序：先运行 Reporting Runtime、publishing、workflow publication、CLI 和 Agent projection 定点 pytest，再对改动文件运行 Ruff format/lint；不依赖真实外网或共享数据库。

## 非目标

- 不提供 PDF 或 Word 的页面内预览。
- 不在 HTML 中执行模型生成的 JavaScript，不加载远程字体、脚本、图片或 iframe。
- 不把三种格式拆成相互独立的 revision 或授权。
