# Reporting 三格式交付实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不破坏现有 PDF/Word 契约的前提下，为 Reporting 增加可安全预览的静态 HTML，并让 AgentOS HTTP 与 CLI 都返回三种格式。

**Architecture:** 运行时从同一份 Markdown 同步生成 PDF、DOCX 和自包含 HTML，三者在同一 revision 目录联合验收并原子发布。HTTP 复用现有 bearer grant 和 PostgreSQL artifact 存储，通过 artifact 类型解析 HTML；CLI 返回 HTML 工作区路径。HTML 响应使用 sandbox CSP，禁止脚本、外链、表单和插件。

**Tech Stack:** Python 3.12、FastAPI、SQLAlchemy async、Pydantic、MarkdownIt、WeasyPrint、python-docx、pytest、Ruff。

---

### Task 1: 冻结三格式运行时契约

**Files:**
- Modify: `smart_reporting/reporting/delivery/report_runtime/validation.py`
- Modify: `smart_reporting/reporting/delivery/report_runtime/runtime.py`
- Modify: `smart_reporting/reporting/delivery/report_runtime/cli.py`
- Test: `smart_reporting/reporting/tests/test_report_runtime.py`

- [ ] **Step 1: 写失败测试，定义 HTML 产物与安全约束**

在 `test_report_runtime.py` 增加测试，断言 `render_markdown` 返回 `html` 身份，HTML 文件扩展名为 `.html`，内容包含 `<!doctype html>`、`lang='zh-CN'`、内联 `<style>`，不包含 `<script`、`<form`、`http://`、`https://` 或 Markdown 原始 HTML；图片使用 `data:image/...`。

- [ ] **Step 2: 运行定点测试确认失败**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_report_runtime.py -q`

预期：新增断言因 `html` 产物尚不存在而失败，现有双格式测试保持可收集。

- [ ] **Step 3: 实现最小 HTML 渲染**

在 `markdown.py` 增加独立 HTML 文档构造函数，复用 `_semantic_documents` 的 `body`、标题上下文和主题 CSS；在 `runtime.py` 中把 HTML 输出路径固定为与 PDF/DOCX 同一目录同名 `.html`，将允许图片读取为字节并转换为 base64 data URL，再写入临时 HTML 文件并计算 artifact 身份。HTML 使用 `MarkdownIt("commonmark", {"html": False})` 的渲染结果，禁止远程资源。

- [ ] **Step 4: 扩展 CLI 参数和回执**

让 `render_markdown` 接收可选 `html_output_path`，默认从 PDF 路径替换后缀为 `.html`；CLI 仍接受原有 payload，输出新增 `htmlPath`、`htmlSize`、`htmlSha256`，旧字段不变。

- [ ] **Step 5: 运行测试确认通过**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_report_runtime.py -q`

预期：新增 HTML 渲染与安全约束测试通过，现有 PDF/Word 测试通过。

- [ ] **Step 6: 提交**

```bash
git add smart_reporting/reporting/delivery/report_runtime smart_reporting/reporting/tests/test_report_runtime.py
git commit -m "feat(reporting): render self-contained html reports"
```

### Task 2: 将 HTML 纳入 Workspace 三格式原子发布

**Files:**
- Modify: `smart_reporting/reporting/workspace.py`
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Test: `smart_reporting/reporting/tests/test_reporting_integration.py`

- [ ] **Step 1: 写失败测试，约束同 revision 三格式**

扩展 `_render_report_pair` 相关测试为三格式：断言临时目录、哈希校验、`validate_pdf` payload 和最终 `render` 同时包含 `pdf`、`word`、`html`；增加 HTML 哈希不一致时整批发布失败且不保留最终目录的测试。

- [ ] **Step 2: 运行定点测试确认失败**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_integration.py -q`

预期：测试因 Workspace 只复制/校验 PDF 与 Word 而失败。

- [ ] **Step 3: 扩展暂存、校验和原子发布**

在 `_render_report_pair` 中派生 `html_output_path`，复制 staged HTML，调用 `ahash_file` 校验三种 artifact，向 `validate_pdf` 传递 `html_path`，发布后回写 `render["html"]` 与结果 `htmlPath`。删除/回滚逻辑保持以 revision 目录为单位。

- [ ] **Step 4: 扩展发布门禁身份校验**

在 `base.py` 的 `_publication_content` 和 `_require_artifact_identity` 中增加 `htmlPath`、`htmlSize`、`htmlSha256`，错误消息明确包含三格式产物；门禁失败回执不得暴露 sandbox HTML 路径。

- [ ] **Step 5: 运行测试并提交**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_integration.py smart_reporting/reporting/tests/test_report_runtime.py -q`

```bash
git add smart_reporting/reporting/workspace.py smart_reporting/reporting/workflow/runtime/publication.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/tests/test_reporting_integration.py
git commit -m "feat(reporting): publish html with report revision"
```

### Task 3: 扩展 PostgreSQL artifact 与 HTTP 预览

**Files:**
- Modify: `smart_reporting/reporting/delivery/publishing.py`
- Test: `smart_reporting/reporting/tests/test_report_artifact_persistence.py`
- Test: `smart_reporting/tests/test_reporting_request_identity.py`

- [ ] **Step 1: 写失败测试**

增加 `html` artifact 持久化/读取测试；增加 `/reports/v1/download/{grant}/html` 测试，断言 `text/html`、`inline`、CSP、`nosniff`、`no-store`；增加过期 grant、scope 不匹配、哈希篡改和缺失 HTML artifact 的拒绝测试。

- [ ] **Step 2: 运行定点测试确认失败**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_report_artifact_persistence.py smart_reporting/tests/test_reporting_request_identity.py -q`

预期：`Literal["pdf", "word"]` 校验和路由缺失导致失败。

- [ ] **Step 3: 扩展 artifact 类型与持久化校验**

将 artifact 类型统一扩展为 `Literal["pdf", "word", "html"]`，保持现有 artifact 表结构；`ReportArtifactPersistenceService.persist` 要求三件产物且逐个校验路径、大小、SHA-256。`_grant_artifact` 对 HTML 通过 repository 按 grant scope/report/revision 查询，不修改既有 PDF/Word grant 字段。

- [ ] **Step 4: 增加 HTML HTTP 路由**

新增 `/reports/v1/download/{opaque_grant}/html`，使用 `service.stream(..., artifact="html")`，返回 `StreamingResponse`，设置 `media_type="text/html"`、`Content-Disposition: inline`、`Content-Length`、`Cache-Control: no-store`、`Content-Security-Policy: sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'`、`X-Content-Type-Options: nosniff` 和 `X-Accel-Buffering: no`。

- [ ] **Step 5: 运行测试并提交**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_report_artifact_persistence.py smart_reporting/tests/test_reporting_request_identity.py -q`

```bash
git add smart_reporting/reporting/delivery/publishing.py smart_reporting/reporting/tests/test_report_artifact_persistence.py smart_reporting/tests/test_reporting_request_identity.py
git commit -m "feat(reporting): serve html preview artifacts"
```

### Task 4: 扩展 HTTP/CLI 发布回执

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/planning.py`
- Modify: `smart_reporting/reporting/delivery/publishing.py`
- Modify: `smart_reporting/reporting/README.md`
- Test: `smart_reporting/reporting/tests/test_reporting_cli.py`
- Test: `smart_reporting/reporting/tests/test_reporting_integration.py`

- [ ] **Step 1: 写失败测试**

断言 CLI 完成结果包含 `htmlPath`；HTTP 发布结果包含 `html.previewUrl`，PDF/Word URL 不变；发布输入缺失 HTML 身份时拒绝，不降级为双格式成功。

- [ ] **Step 2: 实现三格式发布回执**

在 `planning.py` 的 HTTP 持久化调用中传入 HTML `ReportArtifactSpec`，在 grant 后构造 `html.previewUrl`；CLI 路径回执增加 HTML 字段。保持 workspace publication 的既有 PDF/Word 路径字段。

- [ ] **Step 3: 更新文档**

在 `smart_reporting/README.md` 说明 HTTP 的 HTML 预览 URL、CLI 的 `htmlPath`，以及 HTML 的静态安全约束。

- [ ] **Step 4: 运行测试并提交**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_cli.py smart_reporting/reporting/tests/test_reporting_integration.py -q`

```bash
git add smart_reporting/reporting/workflow/runtime/planning.py smart_reporting/reporting/README.md smart_reporting/reporting/tests/test_reporting_cli.py smart_reporting/reporting/tests/test_reporting_integration.py
git commit -m "feat(reporting): expose html delivery links"
```

### Task 5: 更新 Agent 展示与契约测试

**Files:**
- Modify: `smart_reporting/reporting/agent.py`
- Test: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [ ] **Step 1: 写失败测试**

扩展完成回执测试，断言最终 Markdown 同时展示“下载 PDF 报告”“下载 Word 报告”“预览 HTML 报告”，并验证模型不会被重新调用；缺少 HTML URL 时拒绝声明三格式完成。

- [ ] **Step 2: 实现最小展示变更**

在完成回执投影中读取 `report["html"]["previewUrl"]`，按固定顺序追加 HTML 预览链接；保留现有 PDF/Word 文案和相对路径拒绝逻辑。

- [ ] **Step 3: 运行测试并提交**

运行：`.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_agent_projection.py -q`

```bash
git add smart_reporting/reporting/agent.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
git commit -m "feat(reporting): show html preview in agent receipt"
```

### Task 6: 全量定点回归与静态检查

**Files:**
- Verify: `smart_reporting/reporting/delivery/report_runtime/*.py`
- Verify: `smart_reporting/reporting/delivery/publishing.py`
- Verify: `smart_reporting/reporting/workspace.py`
- Verify: `smart_reporting/reporting/workflow/runtime/{base,planning,publication}.py`

- [ ] **Step 1: 运行 Reporting 三格式定点测试**

```bash
.venv-agent/bin/python -m pytest \
  smart_reporting/reporting/tests/test_report_runtime.py \
  smart_reporting/reporting/tests/test_report_artifact_persistence.py \
  smart_reporting/reporting/tests/test_reporting_integration.py \
  smart_reporting/reporting/tests/test_reporting_cli.py \
  smart_reporting/reporting/tests/test_reporting_agent_projection.py \
  smart_reporting/tests/test_reporting_request_identity.py -q
```

- [ ] **Step 2: 运行 Ruff**

```bash
.venv-agent/bin/ruff format --check smart_reporting/reporting/delivery smart_reporting/reporting/workspace.py smart_reporting/reporting/workflow/runtime smart_reporting/reporting/tests smart_reporting/tests/test_reporting_request_identity.py
.venv-agent/bin/ruff check smart_reporting/reporting/delivery smart_reporting/reporting/workspace.py smart_reporting/reporting/workflow/runtime smart_reporting/reporting/tests smart_reporting/tests/test_reporting_request_identity.py
```

- [ ] **Step 3: 检查最终差异和产物边界**

运行 `git diff --check`、`git status --short` 和 `git diff --stat`；确认没有 PDF、HTML、日志、数据库或其他运行产物写入仓库。

预期：定点测试和 Ruff 通过，工作区仅包含源代码、测试、README 与本计划/设计文档变更。
