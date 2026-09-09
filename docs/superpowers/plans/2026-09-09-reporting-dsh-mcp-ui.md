# Reporting DSH MCP UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Reporting MCP 增加与 Odoo capability 严格隔离的 DSH 认证，并交付按当前 DSH Session 自动绑定身份的四工具 MCP UI 插件。

**Architecture:** Reporting 的单一 `TokenVerifier` 先解析并精确匹配 JWT header，再分别进入原 capability 验证器或新增 DSH 验证器，绝不回退。插件 Host 启动时用短期 DSH token 发现四个服务端工具，并把隐藏 `threadId` 后的真实 schema 注册给 DSH；每次执行重新签发 token、创建 MCP Client、注入 Session id 并关闭连接。Client 只用持久化的参数与 `presentationMeta` 投影卡片，用户操作通过当前 session scope 的 `conversation.send()` 排队。

**Tech Stack:** Python 3.12、FastMCP/AgentOS、pytest；Node.js ESM、`@modelcontextprotocol/sdk` 1.29、Cordis/DSH tools、React 18、Node `node:test`。

**Spec:** `docs/superpowers/specs/2026-09-09-reporting-dsh-mcp-ui-design.md`

## Global Constraints

- Reporting 只修改 `/home/junge/pros/chat/.worktrees/reporting-mcp-dsh-auth`，不修改 `/home/junge/pros/chat` 主工作区。
- 插件只修改 `/home/junge/pros/dsh-smart-reporting`，不修改 `/home/junge/pros/dsh`，不接入 Odoo，不扩展通用 MCP Client。
- 配置仅为 `SMART_REPORTING_BASE_URL`（默认 `http://127.0.0.1:33046`）和已有 `AGENT_WORKSPACE_HMAC_SECRET`（至少 32 字节）。
- DSH token 固定 `HS256`、`typ=DSH-REPORTING`、`iss=dsh`、`aud=smart-reporting-mcp`、`ver=1`、TTL 300 秒、`database=dsh`、`company=default`、`sub == thread == DSH Session ID`。
- 公开工具名固定为 `mcp__smart_reporting__reporting_start|get|review|cancel`，单次 MCP 调用超时 120000 毫秒。
- 每次调用创建并关闭独立 MCP Client/transport；模型参数、浏览器、日志和工具文本不得暴露 token、密钥或 thread。
- 只运行定点测试、语法检查与 `git diff --check`，禁止重复 Reporting 全量测试。

---

### Task 1: Reporting DSH Token Verification

**Files:**
- Modify: `smart_reporting/reporting_mcp/tests/test_identity.py`
- Modify: `smart_reporting/reporting_mcp/tests/test_http_e2e.py`
- Modify: `smart_reporting/reporting_mcp/identity.py`

**Interfaces:**
- Produces: `verify_dsh_reporting_token(token: str, secret: str, *, now: int) -> DshReportingClaims`。
- Produces: `CapabilityTokenVerifier.verify_token(token: str) -> AccessToken | None`，按精确 header 分派 Odoo 与 DSH。
- Preserves: `require_mcp_identity(thread_id: str) -> McpRequestIdentity`，允许 Odoo 整数身份和 DSH 字符串身份，但输出仍统一为字符串。

- [ ] **Step 1: Write failing identity tests**

在 `test_identity.py` 增加独立 `_dsh_token()` 测试构造器和参数化测试，手工签名固定 header/claims。覆盖有效映射，以及错误签名、过期、未来签发、TTL 大于 300 秒、错误 header/issuer/audience/version/database/company、空 `sub`、空 `thread`、`sub != thread`；另加一例把带 `DSH-REPORTING` header 但 Odoo claims 的 token 断言为 `None`，证明无验证器降级。在 `test_http_e2e.py` 复用现有 server setup 增加 DSH token 的工具发现和 `reporting_get` 调用，断言 controller scope 为 `("session-dsh", "session-dsh", "dsh", "default")`。

```python
@pytest.mark.anyio
async def test_dsh_verifier_returns_session_identity() -> None:
    verifier = CapabilityTokenVerifier("s" * 32, clock=lambda: 1_800_000_000)
    access_token = await verifier.verify_token(_dsh_token("s" * 32))
    assert access_token is not None
    assert access_token.claims == {
        "sub": "session-1", "database": "dsh", "user": "session-1",
        "company": "default", "thread": "session-1",
    }

@pytest.mark.parametrize("override", [
    {"iss": "other"}, {"aud": "other"}, {"ver": 2},
    {"database": "odoo"}, {"company": "other"},
    {"sub": "session-2"}, {"exp": 1_800_000_301},
])
@pytest.mark.anyio
async def test_dsh_verifier_rejects_invalid_protocol_claims(override: dict[str, object]) -> None:
    verifier = CapabilityTokenVerifier("s" * 32, clock=lambda: 1_800_000_000)
    assert await verifier.verify_token(_dsh_token("s" * 32, override=override)) is None
```

- [ ] **Step 2: Run identity tests and verify RED**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting_mcp/tests/test_identity.py smart_reporting/reporting_mcp/tests/test_http_e2e.py -k 'dsh or identity'`

Expected: 新 DSH identity 和 HTTP 用例都因现有 verifier 只接受 `WORKSPACE-CAP` 而 FAIL。

- [ ] **Step 3: Implement strict dispatch and DSH verification**

在 `identity.py` 增加不可变 `DshReportingClaims`、严格 base64url/JSON 解码、HS256 constant-time 签名校验和固定 claims 校验。`CapabilityTokenVerifier.verify_token()` 先读取完整 header：仅 `{alg: HS256, typ: WORKSPACE-CAP}` 调原 `verify_capability()`，仅 `{alg: HS256, typ: DSH-REPORTING}` 调 `verify_dsh_reporting_token()`，其他值立即返回 `None`；任一分支失败均不得尝试另一分支。把两类结果都投影为 `database/user/company/thread` claims，调整 `require_mcp_identity()` 接受非空 `int | str` 的 user/company。

- [ ] **Step 4: Run identity and unchanged Odoo security tests**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting_mcp/tests/test_identity.py smart_reporting/reporting_mcp/tests/test_http_e2e.py smart_reporting/tests/test_security.py smart_reporting/tests/test_reporting_request_identity.py`

Expected: PASS；原 Odoo capability 行为保持通过。

- [ ] **Step 5: Commit Reporting identity change**

```bash
git add smart_reporting/reporting_mcp/identity.py smart_reporting/reporting_mcp/tests/test_identity.py smart_reporting/reporting_mcp/tests/test_http_e2e.py
git commit -m "feat: authenticate DSH reporting sessions"
```

### Task 2: DSH Plugin Host MCP Bridge

**Files:**
- Create: `/home/junge/pros/dsh-smart-reporting/host-core.js`
- Create: `/home/junge/pros/dsh-smart-reporting/tests/host-core.test.js`
- Modify: `/home/junge/pros/dsh-smart-reporting/index.js`
- Modify: `/home/junge/pros/dsh-smart-reporting/package.json`

**Interfaces:**
- Produces: `signDshToken(secret: string, sessionId: string, nowSeconds?: number) -> Promise<string>`。
- Produces: `publicTool(tool: McpTool) -> { name, description, inputSchema }`，只删除顶层 `threadId` 和 `required` 中对应项。
- Produces: `discoverTools(clientFactory, config) -> Promise<McpTool[]>`，要求四个目标工具恰好各出现一次且有 object input schema。
- Produces: `callReportingTool(clientFactory, config, rawName, args, exec) -> Promise<ReportingValue>`，拒绝参数 `threadId`、绑定 `exec.agent.session.id`、120 秒超时并始终 close。

- [ ] **Step 1: Write failing pure Host contract tests**

用 Node `node:test` 和小型 fake client factory 覆盖：JWT header/claims/签名；四工具缺失、重复、坏 schema；schema 深拷贝后只删除顶层 `threadId`；模型覆盖 thread 被拒；四个 raw tool 都收到当前 Session；`isError`、无 `structuredContent`、abort/timeout 均失败；connect/list/call 成功或失败后 `close()` 都恰好执行一次。期望值使用手工 JSON 字面量和独立 `crypto.createHmac()` 校验。

```js
test('injects the current session and closes one client per call', async () => {
  const seen = []
  const factory = fakeFactory({ callTool(request) { seen.push(request); return completedResult } })
  const value = await callReportingTool(factory, config, 'reporting_get',
    { operationId: 'op-1' }, execFor('session-1'))
  assert.equal(value.status, 'completed')
  assert.deepEqual(seen[0].arguments, { operationId: 'op-1', threadId: 'session-1' })
  assert.equal(factory.closed, 1)
})
```

- [ ] **Step 2: Run Host tests and verify RED**

Run: `node --test tests/host-core.test.js`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `host-core.js`.

- [ ] **Step 3: Implement minimal Host protocol core**

在 `host-core.js` 仅使用 Node `crypto` 和 JSON-compatible values 实现上述接口。结果保留 `status`、`operationId`、`review`、`report`、`error` 中卡片所需的服务端字段；模型渲染只返回状态、operation/report id 或审核提示。所有 error message 不拼入 token、密钥、完整参数或 URL。

- [ ] **Step 4: Implement async plugin activation and per-call MCP clients**

`index.js` 的 Config 只暴露 `baseUrl`，默认取 `SMART_REPORTING_BASE_URL`；共享密钥只从 `AGENT_WORKSPACE_HMAC_SECRET` 环境变量读取，不进入普通配置 UI。`apply` 启动时创建发现 client 并关闭，再用 `ctx.tools.register()` 注册四个 raw JSON Schema 工具。Client 使用 `@modelcontextprotocol/sdk/client/index.js` 与 `client/streamableHttp.js`，transport header 为 `Authorization: Bearer <fresh token>`；`callTool(..., { signal: exec.signal, timeout: 120000, maxTotalTimeout: 120000 })`。公开 schema 来自发现结果，公开名固定添加 `mcp__smart_reporting__` 前缀，`timeoutMs` 固定 120000。

- [ ] **Step 5: Run Host tests and syntax checks**

Run: `node --test tests/host-core.test.js`

Run: `node --check index.js && node --check host-core.js`

Expected: 全部 PASS。

### Task 3: DSH Reporting Cards and Delivery Metadata

**Files:**
- Create: `/home/junge/pros/dsh-smart-reporting/client-model.js`
- Create: `/home/junge/pros/dsh-smart-reporting/tests/client-model.test.js`
- Modify: `/home/junge/pros/dsh-smart-reporting/client.js`
- Modify: `/home/junge/pros/dsh-smart-reporting/package.json`
- Modify: `/home/junge/pros/dsh-smart-reporting/cordis.patch.yml`
- Modify: `/home/junge/pros/dsh-smart-reporting/README.zh.md`

**Interfaces:**
- Produces: `reportingCardModel(block, baseUrl) -> null | { status, operationId, review, report }`，只接受五种状态。
- Produces: `reportingCommand(action, operationId, feedback?) -> string`，生成要求模型调用固定 MCP 工具的明确指令，不含 thread。
- Produces: `safeDeliveryUrl(value, baseUrl) -> string | null`，只允许同源且 pathname 前缀 `/reports/v1/download/`。
- Consumes: Host `presentationMeta` 中的最小 Reporting 投影；Client 不访问 Reporting 网络。

- [ ] **Step 1: Write failing Client model tests**

覆盖 running/paused/completed/cancelled/failed 和 malformed metadata；刷新、批准、拒绝（含反馈）、取消指令必须包含 operationId 和对应公开工具名且不包含 `threadId`；同源下载路径通过，跨源、用户名密码 URL、非 HTTP(S)、相似路径 `/reports/v1/download-evil/` 均拒绝。

```js
test('accepts only same-origin report delivery URLs', () => {
  assert.equal(safeDeliveryUrl('http://127.0.0.1:33046/reports/v1/download/r/preview', BASE),
    'http://127.0.0.1:33046/reports/v1/download/r/preview')
  assert.equal(safeDeliveryUrl('https://evil.example/reports/v1/download/r', BASE), null)
  assert.equal(safeDeliveryUrl('http://127.0.0.1:33046/reports/v1/download-evil/r', BASE), null)
})
```

- [ ] **Step 2: Run Client model tests and verify RED**

Run: `node --test tests/client-model.test.js`

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `client-model.js`.

- [ ] **Step 3: Implement pure card projection and commands**

在 `client-model.js` 对 `ToolResultNode.meta` 做逐字段白名单读取。completed 仅输出通过 `safeDeliveryUrl()` 的 HTML/PDF/Word URL；paused 仅输出标题、说明、阶段和受限 preview scalar fields；指令使用固定中文模板，例如 `请调用 mcp__smart_reporting__reporting_get，operationId 为 "op-1"，不要创建新报表。`。

- [ ] **Step 4: Implement the shared React card and scoped actions**

`client.js` 为四个公开工具 key 用一个 generator 注册并由 Cordis disposer 管理。组件从 toolview props 读取 `block`，通过注册项的 session-scope `inject` 获得当前 scope 的 `conversation.send` 回调；按钮点击只调用该回调。使用 DSH `Button` 与 Refresh/Check/Close/Stop/Download icons；iframe 设置 `sandbox=""`，下载链接设置 `target="_blank" rel="noreferrer"`，CSS 仅由 `styles.insert()` 注入插件 class，操作区在窄屏换行。

- [ ] **Step 5: Add lifecycle/UI smoke tests and verify them**

在 `tests/client-model.test.js` 加 fake `slots`/`conversation` 验证四个 key 注册且 disposer 全部返回；用 `React.createElement` 返回树验证五态操作集合、iframe sandbox 和链接 rel。点击 handler 后断言 fake `conversation.send()` 收到 Task 3 Step 3 的确切指令。

Run: `node --test tests/client-model.test.js`

Run: `node --check client.js && node --check client-model.js`

Expected: 全部 PASS。

- [ ] **Step 6: Finalize package metadata and operator docs**

`package.json` 增加运行依赖 `@modelcontextprotocol/sdk:^1.29.0`，Client peer/inject 增加 `@deepseek-ai/dsh-client-ui-conversation` 与 `@deepseek-ai/dsh-client-ui-primitives`，`files` 包含两个 core module。README 只记录两个环境变量、四个公开工具、Session 自动绑定、120 秒调用超时不限制后台报表，以及 Reporting 同源下载要求；删除 agent id/bearer token 文档。`cordis.patch.yml` 继续只插入 Host 与 Client 两个插件条目。

- [ ] **Step 7: Run final focused verification**

Reporting worktree：

```bash
.venv/bin/python -m pytest -q \
  smart_reporting/reporting_mcp/tests/test_identity.py \
  smart_reporting/reporting_mcp/tests/test_http_e2e.py \
  smart_reporting/reporting_mcp/tests/test_contracts.py \
  smart_reporting/tests/test_security.py \
  smart_reporting/tests/test_reporting_request_identity.py
git diff --check
git status --short
```

插件目录：

```bash
node --test tests/host-core.test.js tests/client-model.test.js
node --check index.js
node --check host-core.js
node --check client.js
node --check client-model.js
```

Expected: 所有定点检查 PASS；Reporting 主工作区和 `/home/junge/pros/dsh` 的 status 不因本实现变化。
