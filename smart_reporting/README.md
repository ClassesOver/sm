# Office 文档服务

本包提供 Office 四格式（DOCX、XLSX、PPTX、PDF）原生在线编辑、文件内 AI、管理后台、PostgreSQL 持久化
和按身份隔离的本地工作区。报告工作流、Reporting MCP、Coding Agent 与旧报告编辑器已退役。

## 启动

```bash
docker compose up -d reporting-db
UV_PROJECT_ENVIRONMENT=.venv uv sync --python 3.12 --no-install-project
AGENT_ENV_FILE=.env .venv/bin/python -m smart_reporting.app
```

`reporting-db` 向宿主机发布 `127.0.0.1:55432`，与默认 `AGENT_DB_URL` 一致。容器内的
AgentOS 仍通过服务名 `reporting-db:5432` 连接。

主应用提供：

- `GET /ready` 服务就绪检查（含已开启 Office 能力所需的引擎检查）。
- `/office`、`/office/api/*` GenOffice 网页工作区：独立登录、个人/团队工作区文件、搜索、知识库问答与工作区数据源。
- `/reports/v1/native/*` Office 原生编辑页、读取模型、预览、保存/导出、文件内 AI 与下载。
- `/reports/v1/native/import` 四格式上传导入（需 Workspace capability）。
- `/reports/v1/download/*` 已签发报告与 Office 产物的 bearer 下载。
- `/management/*` 管理后台（数据源、目录、表授权、指标、统计口径、业务知识、系统配置）。
- 旧编辑入口 `/reports/v1/editor|slides|workbooks/*` 统一返回 `410`。

Odoo 集成请求使用 `X-Workspace-Thread` 和 `X-Workspace-Capability`；Capability 绑定 Odoo
`database`、`user`、`company`、`odoo_session` 和 `thread`，签名密钥由
`AGENT_WORKSPACE_HMAC_SECRET` 配置。公开下载只校验 URL 中的 bearer grant。

## 模块

- `office/`：Office 中立能力——编辑授权与会话、产物身份、结构化候选 Agent、Office 模型
  （`create_office_model`，配置 `AGENT_OFFICE_MODEL*` 时由 `office_model` 切换独立模型）与复杂场景编码任务
  （`office/codex.py`，Agno `CodexAgent`）；以及 GenOffice 工作区服务（`api`、`repository`、`documents`、
  `search`、`knowledge`、`source_*`）。
- `report_editor/`：Office 原生编辑器后端与前端，见 [report_editor/README.md](report_editor/README.md)。
- `management/`：管理后台与 Alembic 迁移。
- `reporting/`：保留的共用实现——四格式引擎桥接（`delivery/`、`*_engine/`）、数据源查询
  （`data_source/`）、结构化输出执行器、业务知识检索与语义基础模型。
- `.importlinter` 约束 Office 不得（含间接）依赖已退役模块；GenOffice 数据源与知识库集成可复用管理端数据源，
  但同样不得依赖报告工作流。测试 `test_office_import_boundaries` 执行该检查。

系统渲染依赖与根目录 `Dockerfile` 保持一致（LibreOffice、Pandoc、Poppler、qpdf、Noto CJK 字体等）。
宿主绘图可设置 `MATPLOTLIBRC="$PWD/docker/matplotlibrc"`；图表只使用 Matplotlib 静态 PNG/JPEG。

## 配置

主要环境变量：

| 变量 | 用途 |
| --- | --- |
| `OPENAI_API_KEY` | 模型 API 密钥 |
| `OPENAI_BASE_URL` | OpenAI-compatible API 地址 |
| `AGENT_MODEL_FAST` / `AGENT_MODEL_STANDARD` / `AGENT_MODEL_STRONG` | 模型档位，Office AI 默认使用标准档 |
| `AGENT_MODEL_*_STRUCTURED_MODE` | 各档结构化协议：`json_schema`（默认）或 `json_object` |
| `AGENT_MODEL_STRUCTURED_STRICT` | 是否对 JSON Schema 启用 strict；兼容端点不支持时可设为 `false` |
| `AGENT_MODEL_VLLM_REASONING` / `AGENT_MODEL_VLLM_THINKING_BUDGET` / `AGENT_MODEL_LITELLM_PROXY` | vLLM 与 LiteLLM 兼容参数 |
| `AGENT_DB_URL` | AgentOS PostgreSQL 连接 |
| `AGENT_WORKSPACE_HMAC_SECRET` | Workspace capability 与授权签名密钥 |
| `AGENT_REPORT_PUBLIC_BASE_URL` | 下载与编辑链接的公开同源基地址；生产环境使用 HTTPS |
| `AGENT_NATIVE_DOCX_ENABLED` / `_PDF_ENABLED` / `_PDF_TEXT_ENABLED` / `_UPLOAD_ENABLED` / `_AI_ENABLED` | Office 能力灰度开关 |
| `AGENT_OFFICE_MODEL` / `AGENT_OFFICE_MODEL_BASE_URL` / `AGENT_OFFICE_MODEL_API_KEY` | GenOffice 文档助手、主页问答与搜索重排的独立 OpenAI 兼容模型；留空沿用标准档 |
| `AGENT_OFFICE_CODEX_ENABLED` | 复杂场景编码任务开关（默认关闭） |
| `AGENT_OFFICE_CODEX_BASE_URL` / `AGENT_OFFICE_CODEX_MODEL` | 编码任务的 Responses 端点与模型；留空沿用 `OPENAI_BASE_URL` 与标准档 |
| `AGENT_MANAGEMENT_CREDENTIAL_KEYS` | 数据源凭据加密密钥（`key-id:Fernet-key`） |

已退役的报告配置项若仍保存在管理端系统配置中，读取时忽略并记录告警，不阻断启动。

## 验证

```bash
UV_PROJECT_ENVIRONMENT=.venv uv sync --python 3.12 --no-install-project
bash scripts/check_agentos.sh
```

PostgreSQL 集成用例按测试标记单独运行。
