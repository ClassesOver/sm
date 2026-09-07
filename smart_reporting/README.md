# AgentOS Coding 与 Reporting 服务

本包提供 Coding Agent、Reporting Workflow、PostgreSQL 持久化和按 thread 隔离的 Daytona 工作区。应用不安装浏览器聊天 interface。

## 启动

```bash
docker compose up -d reporting-db
UV_PROJECT_ENVIRONMENT=.venv uv sync --python 3.12 --no-install-project
AGENT_ENV_FILE=.env .venv/bin/python -m smart_reporting.app
```

主应用保留：

- AgentOS 原生 Agent API，公开 `smart-reporting`，同时支持普通对话和智能报表；旧
  `report-agent` ID 仅作为已有 session 和暂停 run 的兼容恢复入口保留。
- Reporting Workflow 不直接注册为 AgentOS 原生 Workflow；报表运行统一由
  `smart-reporting` facade 驱动，以共享 thread 独占与终态清理契约。
- `smart-reporting` 的报表请求支持与 CLI 相同的自然语言或 `ReportRequestEnvelope` JSON 输入。
- `GET /ready` 服务就绪检查。
- `/workspace/*` 工作区文件接口。
- `/reports/v1/download/*` 报告公开 bearer 下载接口，链接默认 30 天有效；HTML 使用
  `/reports/v1/download/{grant}/html` 在线预览。

通用 AgentOS Console 的 run 请求可不携带 Workspace 请求头，此时沿用原生
`user_id/session_id`，且不会生成默认 Odoo 身份。Odoo 集成请求必须同时使用
`X-Workspace-Thread` 和 `X-Workspace-Capability`；Workspace 请求始终要求这两个请求头，
公开报告下载仅校验 URL 中的 bearer grant。Capability 必须携带并绑定 Odoo `database`、`user`、`company`、
`odoo_session` 和 `thread`；服务端会用验签后的 `user/thread` 覆盖 AgentOS run 请求中的
`user_id/session_id`。签名密钥由 `AGENT_WORKSPACE_HMAC_SECRET` 配置。

## Reporting MCP

AgentOS 在同一服务内以 Streamable HTTP 暴露 `/mcp`，并关闭 Agno 内置通用工具，只提供
`reporting_start`、`reporting_get`、`reporting_review` 和 `reporting_cancel`。DSH 使用
`Authorization: Bearer <workspace capability>` 连接；capability 必须与每次工具参数中的
`threadId` 一致，用户、公司和数据库只取验签后的 claims，工具参数不能覆盖。

DSH 的 MCP 配置只需指向 `http(s)://<reporting-host>/mcp`，transport 选择
`streamable-http`。生产部署必须把客户端实际发送的 Host（含非默认端口）加入
`AGENT_REPORTING_MCP_ALLOWED_HOSTS`，多个值用逗号分隔。未配置有效
`AGENT_REPORTING_MCP_ALLOWED_HOSTS` 时仅允许 Agno 内置的 localhost Host；未配置有效
`AGENT_WORKSPACE_HMAC_SECRET` 时 Bearer 验证失败关闭。

`reporting_start` 在请求校验和可选附件物化后返回稳定 `operationId`，报表 Workflow 本身在
后台执行，DSH 通过 `reporting_get` 轮询；暂停后使用 `reporting_review` 审批或拒绝。附件不提供 MCP 上传工具，只接受 `attachments[].url` 的
HTTPS CSV：最多 4 个、单个最多 50 MiB、合计最多 200 MiB，不跟随重定向、不使用环境代理。
下载后的 CSV 会作为补充 Dataset 进入与 StarRocks 数据相同的不可变校验、Profile、分析和
发布血缘链路；`reportRequest.fileInputs` 不对 MCP 调用方开放。

`operationId` 是绑定 database、company、user、thread 和 clientRequestId 的不透明值，不应由
客户端解析。首次请求的 payload 指纹持久化在 `agentos_reporting.reporting_mcp_requests`，同一
clientRequestId 即使跨进程或重启也不能改写请求。当前后台 task 的主动取消仍是进程内操作，部署时
同一 AgentOS PostgreSQL 数据库只能运行一个 Reporting 服务实例，且 `AGENT_OS_WORKERS` 必须为 1。

AgentOS 中的 Reporting 正常发布时会将 PDF、Word 和自包含 HTML 持久化到 PostgreSQL、签发默认
30 天有效的公开 bearer 下载授权，并返回基于 `AGENT_REPORT_PUBLIC_BASE_URL` 的完整下载 URL；
HTML 回执字段为 `html.previewUrl`。持久化成功后删除对应 Daytona sandbox。过期授权会被删除，
无有效授权引用的产物在 24 小时安全窗口后分批回收。Reporting CLI 不启动 HTTP 下载服务，仍返回
Workspace 相对路径，并在 `html` 字段提供 HTML 路径、大小和 SHA-256。

HTML 是静态自包含文档：图片以内嵌 data URL 提供，禁止脚本、表单和外部资源；HTTP 预览响应通过
sandbox Content-Security-Policy 隔离页面。

## CLI

Reporting CLI：

```bash
AGENT_ENV_FILE=.env .venv/bin/python -m smart_reporting.reporting.cli
```

服务仅提供 Reporting 产品入口，通过顶层 Workflow 编排数据准备、分析、章节生成、三格式验收和发布。

## 配置

主要环境变量：

| 变量 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 模型 API 密钥 |
| `OPENAI_BASE_URL` | OpenAI-compatible API 地址 |
| `AGENT_MODEL_VLLM_REASONING` | 经 vLLM 提供 DeepSeek V4 时设为 `true`，使用官方 `chat_template_kwargs` reasoning 格式；默认 `false` 保持云端请求格式不变 |
| `AGENT_MODEL_FAST` | Reporting fast 档模型，默认 `qwen3.6-35b-a3b` |
| `AGENT_MODEL_STANDARD` | Reporting standard 档模型，默认 `deepseek-v4-flash-0731` |
| `AGENT_MODEL_STRONG` | Reporting strong 档模型，默认 `deepseek-v4-flash-0731` |
| `AGENT_MODEL_FAST_STRUCTURED_MODE` | fast 档结构化协议：`json_schema`（默认）或 `json_object` |
| `AGENT_MODEL_STANDARD_STRUCTURED_MODE` | standard 档结构化协议：`json_schema`（默认）或 `json_object` |
| `AGENT_MODEL_STRONG_STRUCTURED_MODE` | strong 档结构化协议：`json_schema`（默认）或 `json_object` |
| `AGENT_MODEL_STRUCTURED_STRICT` | 是否对 JSON Schema 启用 strict；默认 `true`，兼容端点不支持时可设为 `false` |
| `AGENT_DB_URL` | AgentOS PostgreSQL 连接 |
| `AGENT_WORKSPACE_HMAC_SECRET` | Workspace capability 签名密钥 |
| `SANDBOX_PROVIDER` | `daytona`（默认、企业 HA 优先）或 `local`（内网离线、当前仅 node-scoped） |
| `SANDBOX_LOCAL_PROFILE` | Local 固定发行版 profile：`ubuntu` 或 `openeuler` |
| `SANDBOX_LOCAL_ENDPOINT` | Local 绝对 UDS 地址或内网 HTTPS+mTLS 地址 |
| `SANDBOX_ROOTFS_DIGEST` | Local 管理员签名 catalog 中固定 rootfs 的 `sha256:` 摘要 |
| `SANDBOX_LOCAL_CA_CERT` | Local HTTPS 服务端 CA；HTTPS 模式必填 |
| `SANDBOX_LOCAL_CLIENT_CERT` | Local mTLS 客户端证书；HTTPS 模式必填 |
| `SANDBOX_LOCAL_CLIENT_KEY` | Local mTLS 客户端私钥；HTTPS 模式必填 |
| `AGENT_REPORTING_MCP_ALLOWED_HOSTS` | Reporting `/mcp` 接受的 Host 白名单，生产环境必须显式配置 |
| `AGENT_DAYTONA_API_URL` | Daytona API 地址 |
| `DAYTONA_API_KEY` | Daytona API Key |
| `AGENT_REPORT_CODING_ENABLE_THINKING` | Reporting 阶段 Agent thinking 开关（兼容配置名） |
| `AGENT_REPORT_ENABLE_THINKING` | Reporting planner thinking 开关 |
| `AGENT_REPORT_ENABLE_VISION` | 图表视觉审查开关 |
| `AGENT_REPORT_DATA_SOURCES_DIR` | Reporting 数据源配置目录 |

## Reporting 依赖诊断

诊断接口检查服务端配置的 `REPORT_STARROCKS_DSN`、`AGENT_REPORT_METADATA_URL` 和当前 Sandbox Provider，不接受调用方传入连接参数，也不返回连接信息、凭据或上游响应正文：

```bash
curl -X POST \
  http://127.0.0.1:33046/diagnostics/reporting-dependencies
```

三个依赖均正常时返回 HTTP 200；任一依赖未配置或检查失败时返回 HTTP 503，并在 `checks` 中返回稳定错误码和耗时。
元数据服务返回非成功响应时还会提供纯数字 `httpStatus`，但不会透传响应正文。
该接口不要求 Token；生产环境应通过防火墙或反向代理限制访问来源。

## 验证

```bash
UV_PROJECT_ENVIRONMENT=.venv uv sync --python 3.12 --no-install-project
bash scripts/check_agentos.sh
```

PostgreSQL 和 Daytona 集成用例按测试标记单独运行。
