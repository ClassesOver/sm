# AgentOS Coding 与 Reporting 服务

本包提供 Coding Agent、Reporting Workflow、PostgreSQL 持久化和按 thread 隔离的 Daytona 工作区。应用不安装浏览器聊天 interface。

## 启动

```bash
docker compose up -d agent-db
uv venv --python 3.12 .venv-agent
uv pip install --python .venv-agent/bin/python -r smart_reporting/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m smart_reporting.app
```

主应用保留：

- AgentOS 原生 Agent API，公开 `report-agent`，同时支持普通对话和智能报表。
- `report-agent` 的报表请求支持与 CLI 相同的自然语言或 `ReportRequestEnvelope` JSON 输入。
- `GET /ready` 服务就绪检查。
- `/workspace/*` 工作区文件接口。
- `/reports/v1/download/*` 报告公开 bearer 下载接口，链接默认 30 天有效。

通用 AgentOS Console 的 run 请求可不携带 Workspace 请求头，此时沿用原生
`user_id/session_id`，且不会生成默认 Odoo 身份。Odoo 集成请求必须同时使用
`X-Workspace-Thread` 和 `X-Workspace-Capability`；Workspace 请求始终要求这两个请求头，
公开报告下载仅校验 URL 中的 bearer grant。Capability 必须携带并绑定 Odoo `database`、`user`、`company`、
`odoo_session` 和 `thread`；服务端会用验签后的 `user/thread` 覆盖 AgentOS run 请求中的
`user_id/session_id`。签名密钥由 `AGENT_WORKSPACE_HMAC_SECRET` 配置。

AgentOS 中的 Reporting 正常发布时会将 PDF/Word 持久化到 PostgreSQL、签发默认 30 天有效的
公开 bearer 下载授权，并返回基于 `AGENT_REPORT_PUBLIC_BASE_URL` 的完整下载 URL；持久化成功后
删除对应 Daytona sandbox。Reporting CLI 不启动 HTTP 下载服务，仍返回 Workspace 相对路径。

## CLI

Coding CLI：

```bash
AGENT_ENV_FILE=.env .venv-agent/bin/python -m smart_reporting.coding.cli
```

Reporting CLI：

```bash
AGENT_ENV_FILE=.env .venv-agent/bin/python -m smart_reporting.reporting.cli
```

Coding 与 Reporting 使用独立 Agent、指令、工具、状态和验收链路。Coding 通过 `CodingTaskSupervisor` 管理 Task、Attempt、Execution、租约、验证和完成门禁；Reporting 通过顶层 Workflow 编排数据准备、分析、章节生成、双格式验收和发布。

## 配置

主要环境变量：

| 变量 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 模型 API 密钥 |
| `OPENAI_BASE_URL` | OpenAI-compatible API 地址 |
| `MODEL` | 默认模型 |
| `AGENT_DB_URL` | AgentOS PostgreSQL 连接 |
| `AGENT_WORKSPACE_HMAC_SECRET` | Workspace capability 签名密钥 |
| `AGENT_DAYTONA_API_URL` | Daytona API 地址 |
| `DAYTONA_API_KEY` | Daytona API Key |
| `AGENT_CODING_ENABLE_THINKING` | Coding Agent thinking 开关 |
| `AGENT_REPORT_CODING_ENABLE_THINKING` | Reporting worker thinking 开关 |
| `AGENT_REPORT_ENABLE_THINKING` | Reporting planner thinking 开关 |
| `AGENT_REPORT_ENABLE_VISION` | 图表视觉审查开关 |
| `AGENT_REPORT_DATA_SOURCES_DIR` | Reporting 数据源配置目录 |

## 验证

```bash
uv pip install --python .venv-agent/bin/python -r smart_reporting/requirements-test.txt
bash scripts/check_agentos.sh
```

PostgreSQL 和 Daytona 集成用例按测试标记单独运行。
