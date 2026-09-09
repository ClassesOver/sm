# Reporting DSH MCP UI 与独立认证设计

## 目标

在不改变现有 Odoo Workspace capability 语义的前提下，为 DeepSeek Harness（DSH）增加独立的 Reporting MCP 认证方式，并在 `dsh-smart-reporting` 插件中提供安装即用的 MCP 工具及报告任务卡片。

一次 DSH Session 对应一个 Reporting 用户和 thread。同一 DSH 实例可以同时运行多个 Session，各 Session 的 Reporting 操作、审核和产物访问互相隔离。认证 token 的有效期只约束一次 MCP 请求，不约束后台报表运行时长。

## 范围

本次改动包含两个交付面：

- Reporting 服务：在 `/home/junge/pros/chat` 的专用 worktree 中增加 DSH token 验证，并保留现有 Odoo capability 验证。
- DSH 插件：在 `/home/junge/pros/dsh-smart-reporting` 中替换当前直连 AgentOS Run API 的实现，注册四个 Reporting MCP 工具和对应 Web 工具卡片。

本次不修改 `/home/junge/pros/chat` 主工作区，不修改 `/home/junge/pros/dsh`，不接入 Odoo，不增加通用 MCP Client 的动态 header 能力，也不增加独立的 DSH 密钥配置。

## 配置

部署只需要两个配置值：

- `SMART_REPORTING_BASE_URL`：Reporting 服务地址，默认 `http://127.0.0.1:33046`。插件固定使用其 `/mcp` 路径。
- `AGENT_WORKSPACE_HMAC_SECRET`：Reporting 与 DSH 插件共用的现有 HMAC 信任根，至少 32 字节。

以下值属于协议常量，不开放配置：

- token 类型：`DSH-REPORTING`
- 签名算法：`HS256`
- issuer：`dsh`
- audience：`smart-reporting-mcp`
- token TTL：5 分钟
- MCP 工具 namespace：`smart_reporting`
- 单次 MCP 调用超时：120 秒
- DSH 租户标识：`database=dsh`、`company=default`

缺少有效密钥时，DSH 工具调用失败关闭。Reporting 原有认证仍遵循现有配置行为。

## 身份与认证

### DSH token

插件从工具执行上下文读取 `exec.agent.session.id`，并用共享密钥签发短期 token。模型参数、工具结果和浏览器均不接触 Session 身份或密钥。

token header 固定为：

```json
{"alg":"HS256","typ":"DSH-REPORTING"}
```

token claims 固定包含：

```json
{
  "iss": "dsh",
  "aud": "smart-reporting-mcp",
  "sub": "<DSH Session ID>",
  "thread": "<DSH Session ID>",
  "database": "dsh",
  "company": "default",
  "iat": 0,
  "exp": 0,
  "ver": 1
}
```

服务端验证签名、精确 header、issuer、audience、版本、签发时间、过期时间、最大 TTL、固定租户字段以及 `sub == thread`。验证成功后映射为：

- `database = dsh`
- `company_id = default`
- `user_id = sub`
- `thread_id = thread`

`threadId` 仍由每个 MCP 工具参数携带，但插件会从公开输入 schema 中移除该字段，并在 Host 执行时根据当前 Session 自动补入。调用方不能覆盖它。

### 与 Odoo capability 共存

现有 `verify_capability()`、`WORKSPACE-CAP` header、audience、Odoo identity 字段和错误语义保持不变。MCP TokenVerifier 只增加按精确 token header 分派：

- `WORKSPACE-CAP` 进入原验证流程。
- `DSH-REPORTING` 进入新增验证流程。
- 其他 header 或解析失败直接拒绝。

两种 token 虽然共用 HMAC 信任根，但不能跨验证器使用。服务端不得根据缺失字段猜测 token 类型，也不得在一个验证器失败后降级尝试另一个验证器。

## Host 插件

### 启动发现

插件启动时签发一个发现用短期 token，连接 `${SMART_REPORTING_BASE_URL}/mcp` 并读取真实工具定义。必须恰好发现以下四个工具：

- `reporting_start`
- `reporting_get`
- `reporting_review`
- `reporting_cancel`

插件只接管这四个工具。工具缺失、重复或 schema 不可用时加载失败，避免运行时静默漂移。DSH 中注册的公开名称为：

- `mcp__smart_reporting__reporting_start`
- `mcp__smart_reporting__reporting_get`
- `mcp__smart_reporting__reporting_review`
- `mcp__smart_reporting__reporting_cancel`

注册参数基于服务端真实 input schema，仅删除顶层 `threadId` 及对应 `required` 项。插件不手工维护其余业务字段 schema。

### 工具执行

每次工具调用执行以下步骤：

1. 要求 `exec.agent.session.id` 存在。
2. 对模型参数做 JSON 快照，并拒绝调用方提供 `threadId`。
3. 签发绑定当前 Session 的新 token。
4. 创建 MCP Client 和 Streamable HTTP transport。
5. 使用原始 MCP 工具名调用服务端，并自动补入 `threadId`。
6. 验证 `isError`、`structuredContent` 和 Reporting 状态字段。
7. 在成功、失败、取消和超时路径中关闭 Client/transport。

连接不跨 Session 缓存，避免静态 header 或连接状态造成身份串用。`reporting_start` 保留真实 schema 中的 `clientRequestId`、`reportRequest` 和 `attachments`；其余工具同样只隐藏 `threadId`。

规范工具结果保存 Reporting 的结构化结果。模型可见文本只给出状态、报告 id 或待审核提示，不输出 token、密钥、完整请求、下载 bearer URL 或敏感业务预览。

## Web 工具卡片

Client 在 `tool.call.toolview` 中为四个公开工具名分别注册同一组报告卡片。卡片只读取持久化的工具参数和结果 metadata，不重新请求 Reporting，也不重建工具调用历史。

状态行为如下：

- `running`：显示运行中、`operationId` 和刷新操作。
- `paused`：显示审核标题、说明、阶段及受限 preview。支持批准、拒绝和拒绝反馈。
- `completed`：显示报告 id、revision、自包含 HTML 预览以及 PDF、Word 下载。
- `cancelled`：显示已取消终态，不提供操作。
- `failed`：显示失败终态，不提供操作。

刷新、审核和取消按钮不直接调用 MCP。它们通过当前 Session 的 `conversation.send()` 排队一条明确指令，由模型调用对应 MCP 工具。指令包含当前卡片已经持久化的 `operationId`、动作和用户反馈，不包含密钥或 thread。

HTML、PDF 和 Word URL 必须与 `SMART_REPORTING_BASE_URL` 同源，且 pathname 以 `/reports/v1/download/` 开头。HTML 使用无权限的 `iframe sandbox` 预览；下载链接使用新页面和 `noreferrer`。不满足约束的 URL 不渲染为可访问资源。

卡片使用 DSH 现有主题变量，保持紧凑、可扫描布局；按钮使用已有图标库，移动端允许操作区换行，不使用全局 DOM 选择器或覆盖全局主题。

## 错误处理与日志

- 缺少 Session、密钥无效、发现失败、未知 schema、MCP 错误、超时和取消均作为明确工具失败返回。
- 服务端 DSH token 的 header、签名、时间、issuer、audience、版本、租户或 thread 任一校验失败均拒绝认证。
- `operationId` 继续由 Reporting 绑定 database、company、user、thread 和 clientRequestId；插件不解析或重建它。
- 插件日志不记录 token、密钥、完整请求、审核 preview 或下载 URL。
- Reporting 新增日志使用 Loguru、稳定英文事件名和非敏感结构化字段。
- 报表后台执行、持久化、清理和原有 Workflow 状态机均不改变。

## 验证

### Reporting 定点测试

- 有效 DSH token 可通过验证并形成正确 `McpRequestIdentity`。
- 拒绝错误签名、过期、未来签发、超长 TTL、错误 header、issuer、audience、版本、租户字段及 `sub/thread` 不一致。
- 原 Odoo capability 验证测试原样通过。
- HTTP MCP 分别使用原 capability 和 DSH token完成工具发现及一次工具调用。

### 插件 Host 测试

- token 编码与 Reporting 验证约定一致。
- 发现只接受完整且唯一的四工具集合。
- 注册 schema 删除 `threadId` 且保留其他服务端字段。
- 四个工具均自动注入当前 Session id，拒绝调用方覆盖。
- 正常、MCP error、超时和取消路径均关闭资源。
- 输出 metadata 只包含卡片所需字段。

### 插件 Client 测试

- running、paused、completed、cancelled、failed 五种状态正确投影。
- 刷新、批准、拒绝和取消生成正确的当前 Session 指令。
- 不同源或错误路径的预览、下载 URL 被拒绝。
- 插件卸载后四个 keyed Slot 注册全部移除。

只运行上述定点测试、相关静态检查和 `git diff --check`，不重复执行 Reporting 全量测试。

## 交付位置

- Reporting 分支：`codex/reporting-mcp-dsh-auth`
- Reporting worktree：`/home/junge/pros/chat/.worktrees/reporting-mcp-dsh-auth`
- DSH 插件目录：`/home/junge/pros/dsh-smart-reporting`

Reporting 主工作区 `/home/junge/pros/chat` 和 DSH 源码仓库 `/home/junge/pros/dsh` 均保持不变。
