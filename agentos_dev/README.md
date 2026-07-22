# 最小 AgentOS 开发应用

该应用提供两个 HRP 集成端点：

- `POST /agui`：标准 AG-UI SSE 运行端点。
- `GET /config`：`agui.odoo.v2` 协议握手声明。

启动：

```bash
HOST_UID=$(id -u) HOST_GID=$(id -g) \
  docker compose --env-file .env.example --profile setup run --build --rm env-init
# 脚本自动生成服务密码；只需将 .env 中的 OPENAI_API_KEY 改为真实值
docker compose up -d agent-db
uv venv --python 3.12 .venv-agent
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements.txt
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.app
```

开发检查与测试：

```bash
uv pip install --python .venv-agent/bin/python -r agentos_dev/requirements-test.txt
bash scripts/check_agentos.sh

# 启动 PostgreSQL 后单独运行集成测试
.venv-agent/bin/python -m pytest -m integration
```

初始化命令中的 `HOST_UID`/`HOST_GID` 用于保持 `.env` 的宿主文件所有权，`--rm` 只在
脚本结束后删除临时初始化容器。Compose 会在启动数据库时自动创建项目默认网络。
Daytona 使用独立的 `docker/docker-compose.yaml` 部署；宿主机运行本应用时默认通过
`http://127.0.0.1:33043/api` 访问 Daytona。

默认监听 `127.0.0.1:7777`。HRP 只需配置
`http://127.0.0.1:7777/agui` 并开启“允许跨域开发服务”。

Agent 通过 Agno callable tools factory 注册 `AgentControlToolkit`、`BaseToolkit` 和按需加载的
`WorkspaceReportToolkit`。Base 层提供受限终端及
后台会话、基于 ripgrep 的文件/文本搜索、分段读取、文件统计、递归目录树、SHA-256、只读 Git、
定位 hunk、单文件补丁、完整变更集、目录创建、文件复制、图片查看和 PDF 检查；报表层只提供能力发现、
数据登记、多轮分析和 Markdown 转 PDF。读取、检查和后台轮询无需确认，新建、覆盖、补丁、移动、
删除、通用 `sandbox_exec`、后台输入及终止需要确认。所有能力仍绑定当前 thread 的 Daytona
sandbox；实际安全边界包括 `network_block_all`、路径和符号链接校验、文件/结果大小限制以及
前台命令最长 60 秒、后台命令最长 900 秒。

Base 层借鉴 Codex 的少量强工具和 Hermes 的分段读取、分页搜索、精确替换及陈旧文件检测，
但不直接挂载 Agno 的 `Workspace`、`FileTools` 或 `CodingTools`，因为这些工具操作 AgentOS 宿主目录，
无法继承本项目的 Daytona/thread 隔离。文件和文本搜索在 Daytona sandbox 内通过服务端生成的
`rg` 参数执行，支持多 include/exclude glob、正则、智能大小写、整词、上下文、文件列表和计数输出，
不接收模型提供的任意 flags。分段读取、统计、目录树和哈希在 sandbox 内复用 `sed`、`wc`、
`stat`、`find` 与 `sha256sum`，因此可检查超过 1 MiB 的文件且不会先下载到 AgentOS。Git status、
diff、log 和 show 同样使用固定只读参数，不开放任意 Git flags；失败时仅返回仓库、修订、路径或通用
错误分类，不回传原始 stderr。定位 hunk 绑定原文件 SHA-256 和 1-based 行坐标，并与批量补丁一样在
全部目标预检通过后才写入。完整变更集可在一次预检和确认中
执行 create/update/delete/move，每个既有文件都绑定预期 SHA-256；任一预检失败时零写入，执行失败
按逆序回滚。短命令采用一次性受监督执行；异步命令使用 Daytona 原生 session，最多同时四个、
单个最长 900 秒，并通过 UTF-8 字节日志游标分页轮询、输入、中断或终止；交互式命令可通过
`script` 获取指定行列且默认关闭输入回显的 PTY，禁止
`nohup`、`disown` 和 shell 后台符号绕过受管生命周期。后台启动可用 `yield_time_ms` 等待最多
30 秒并返回耗时、原始字节数和日志游标；后台输入也可在写入后按同一游标直接等待新输出。
每轮报表分析调用必须提供完整非空命令，
失败输出会返回模型继续修正。单次完整文本读取限制为 64 KiB，更大文件必须分段读取。
Agent 在每个工具批次后持久化 checkpoint；模型请求遇到临时失败时最多重试两次并指数退避。

## Codex 对齐配置

这里的“对齐”是增强长任务的自主工具循环、持久化和失败恢复能力，不是把 HRP Agent
改造成通用代码代理。当前采用以下配置：

| 配置 | 当前值 | 作用 |
| --- | --- | --- |
| `tool_choice` | `"auto"` | 由模型决定继续调用工具还是返回结果 |
| `tool_call_limit` | `None` | 不限制单次运行的工具调用轮次，由模型根据任务自行结束 |
| `checkpoint` | `"tool-batch"` | 每个模型工具批次后持久化运行状态，支持长任务恢复 |
| `Agent.retries` | `0` | 不重试整个 run，避免重复执行工具 |
| `model.retries` | `2` | 只重试失败的模型请求 |
| `model.exponential_backoff` | `True` | 模型请求重试之间使用指数退避 |
| `add_history_to_context` | `False` | 关闭 Agno 默认的全历史直接注入 |
| `num_history_runs` | `None` | 保持全部 run 可存储和检索，不代表全部发送给模型 |
| `AGENT_CONTEXT_TOKEN_BUDGET` | `262144` | 模型完整上下文窗口上限 |
| `AGENT_HISTORY_TOKEN_BUDGET` | `196608` | 历史装配上限，会按本轮强制上下文动态缩小 |
| `AGENT_OUTPUT_TOKEN_RESERVE` | `32768` | 为模型输出和工具续跑保留的 token |
| `compress_tool_results` | `True` | 仅压缩历史分析工具的大结果 |
| `enable_session_summaries` | `True` | 成功 run 后滚动更新非权威摘要 |
| `enable_thinking` | `True` | 主模型启用；辅助模型关闭，客户端不接收原始 reasoning |

等价的核心配置如下；三个 Assistant 均使用同一组配置，仅强制工具选择不同：

```python
assistant = Agent(
    tool_choice="auto",
    tool_call_limit=None,
    checkpoint="tool-batch",
    retries=0,
    add_history_to_context=False,
    compress_tool_results=True,
    enable_session_summaries=True,
)
assistant.model.retries = 2
assistant.model.exponential_backoff = True

# Agno 2.7.3 会在构造时把 None 归一化为 3；这里恢复的是检索语义。
assistant.num_history_runs = None
```

PostgreSQL 仍永久保存完整 runs 和原始 `Message.content`。完整模型上下文上限为 256K tokens，
预算装配器为输出预留 32K，并根据最新 HRP 宿主快照、当前用户输入和客户端工具 schema 的估算
动态缩小历史预算；默认历史最多 192K。待确认操作和当前 run 结果属于强制上下文，不会为了保留
旧历史而裁剪。旧 `odoo.*` 工具调用和结果不进入后续模型上下文，避免旧快照、token 和
modifiers 与最新 `BasicModel` 状态竞争；`sandbox_exec`、`sandbox_process_poll` 和
`report_analyze_dataset` 结果保留，
大结果优先使用独立的 `compressed_content`，原文不被覆盖。

滚动摘要只包含用户目标、已确认决策、工作区产物、完成事项和待办事项，并标记为非权威历史。
摘要和压缩都不能作为 Odoo 业务事实；需要记录值、筛选、权限或页面状态时，必须使用本轮最新
宿主快照。主模型通过 `enable_thinking=true` 启用 Qwen Thinking，压缩和摘要辅助模型始终关闭
thinking。服务端不转发原始 reasoning delta，终态持久化前清除 reasoning 字段；前端只展示
“正在分析当前请求”或“正在整理工具结果”等确定性状态。

相关环境变量可独立回退：`AGENT_ENABLE_TOOL_RESULT_COMPRESSION=false` 停止生成新压缩结果，
`AGENT_ENABLE_SESSION_SUMMARIES=false` 停止更新和注入摘要，`AGENT_ENABLE_THINKING=false` 关闭
主模型 thinking；`AGENT_CONTEXT_TOKEN_BUDGET`、`AGENT_HISTORY_TOKEN_BUDGET` 和
`AGENT_OUTPUT_TOKEN_RESERVE` 分别调整完整窗口、历史上限和输出余量。关闭任一能力都不会删除 PostgreSQL
中的完整历史，也不会改变 `agui.odoo.v2`、命令确认、授权或 stale snapshot 校验。
为避免 provider reasoning 进入 Agno 调试日志，thinking 开启时 `AGENT_DEBUG` 不生效；需要模型级
调试时必须先关闭 thinking，且不得在生产环境记录包含业务数据的请求或响应正文。

上述配置不改变能力边界。Odoo `BasicModel` 仍是业务页面状态的唯一事实来源；命令仍经过
注册、策略、准备/确认和一次性授权链路；分析命令仍受 thread 隔离、Daytona、网络、路径、
文件大小、输出大小和超时限制。

### 计划、工具发现与上下文状态

Agno 2.7.3 支持 `session_state`、AG-UI `STATE_DELTA`、callable tools factory 和固定步骤
Workflow，但没有 Codex 风格的专用 `update_plan`。本项目因此在 Agno Toolkit 内提供受约束的
`agent_update_plan`：最多 20 步、最多一个 `in_progress`，且只写保留键 `agentos_plan`；它是任务
进度，不是 Odoo 业务事实，也不得保存快照、授权或 modifiers。

`agent_tool_search` 搜索服务端 Toolkit 类别，`agent_load_toolkit` 只修改保留的加载状态。Agno
在每个 run 开始时解析一次 callable tools，因此新 Toolkit 从下一 run 生效；这不需要用户确认，
也不会绕过具体工具原有的确认策略。`cache_callables=False` 防止不同 thread 或不同加载状态复用
错误的工具列表。搜索结果带 `routeSkill` 时只用于发现，不能通过 `agent_load_toolkit` 加载；选择
智能报表 skill 时，服务端将新 run 路由到独立 `report-agent`，主助手不会动态加载报表 Toolkit。
续跑、branch 和 regenerate 按源 run 的 Agent ID 保持同一 Agent；无法确认原 Agent 时失败关闭。

### 泛化数据源与 ReportAgent

`report-agent` 固定暴露 `AgentControlToolkit`、`BaseToolkit`、`ReportDataSourceToolkit` 和
`WorkspaceReportToolkit`。它不使用固定 Workflow 或 Team，模型自行决定分析命令和轮次，但必须
完成“发现数据源 → 物化数据集 → 确定性剖析 → 至少一轮成功分析 → Markdown → PDF → 验收”的
受控链路。完整文件内容不会注入模型上下文；模型只接收数据源句柄、schema、剖析结果和分析输出。

工作区文件、目录、SQLite、DuckDB、Odoo 受控导出和服务端注册的只读 PostgreSQL 均通过
`DatasetHandle` 进入报表工具。目录只列直接子项，文件变化会返回稳定的 `stale_dataset`，单个
任务最多 20 个输入；单文件不超过 25 MiB，数据库物化总量不超过 256 MiB。Odoo 导出仍必须
经过现有导出、确认和一次性授权链路，ReportAgent 不访问 Odoo ORM 或数据库。

外部 PostgreSQL 数据源由 `AGENT_REPORT_DATA_SOURCES_FILE` 指向的 JSON 配置注册。配置只保存
数据源 ID、`dsnEnv`、允许的 schema/table 和限额，DSN 从同名环境变量读取，不能由模型提供；
AgentOS 自身 PostgreSQL 会被拒绝。示例：

```json
{
  "sources": [
    {
      "id": "finance",
      "name": "财务只读库",
      "type": "postgresql",
      "dsnEnv": "REPORT_FINANCE_DSN",
      "schemas": ["reporting"],
      "tables": ["reporting.revenue"],
      "statementTimeoutMs": 30000,
      "maxRows": 1000000,
      "maxBytes": 268435456
    }
  ]
}
```

SQL 只允许单条 `SELECT` 或只读 CTE，并强制只读事务、超时、schema/table 白名单和结果
分片限制。Compose 默认只读挂载仓库中的空配置 `deploy/agentos/report-data-sources.json`；
生产环境通过 `AGENT_REPORT_DATA_SOURCES_FILE` 指向宿主机配置，并确保 `dsnEnv` 对应变量已
注入 AgentOS 容器。工作区 SQLite 使用只读 URI，DuckDB 使用只读连接，sandbox-tools 镜像
包含 DuckDB 运行时依赖。

`agent_context_status` 使用 Agno 模型的 `count_tokens(messages, tools, output_schema)` 估算本轮完整
上下文，返回 256K 上限、估算已用、扣除输出预留后的余量、预算历史和计数可靠性；计数器不可用时
明确标记为不可靠，不回退注入全历史。它不返回旧 Odoo 工具结果或业务字段。余量不足时可调用
`agent_prepare_continuation` 保存摘要、待办和工作区相对产物路径；该工具只建立下一 run 可见的受控
交接，不会递归启动 run，也不会绕过工具确认。计划全部完成时交接状态会被清除。

智能报表先登记当前 thread 工作区内的输入文件，并对 CSV、TSV、Excel、JSON、JSONL 或 Parquet
生成确定性的受限数据剖析，再由模型使用同一 `job_id` 自主执行多轮 Python、Shell 或 SQL 分析。
CSV、JSONL、Excel 和 Parquet 剖析只在内存中保留前 100,000 行；普通 JSON 因格式无法流式读取，
超过 25 MiB 时应转换为 JSONL/Parquet 或直接使用分析命令。
输入内容以 SHA-256 绑定，每轮命令必须输出分析结果；失败轮次把退出码和输出返回给模型继续修正。
至少一轮成功后由模型生成完整 Markdown 和本地图表，再渲染为不覆盖已有文件的新 PDF。运行时使用
Poppler 将 PDF 逐页栅格化，检查空白页、文本、图片数量和像素占比，并把 Markdown、图片、PDF 的
路径、大小、SHA-256 和验收结果写入同一 job manifest。只有 `report_job_status` 返回 `validated`
且产物未变化才算完成。系统不再使用固定模板、`compile` 或 `blocks`。
任务状态保存在 sandbox 的 `/tmp/workspace-report`，Markdown、图片和 PDF 输出到
`报表/生成结果/<job_id>/`。生产环境必须使用仓库现有
`docker/sandbox-tools` 镜像，以提供 ripgrep、WeasyPrint 69、pypdf、数据分析库和 Noto CJK。镜像
同时安装 `matplotlibrc`，将 Matplotlib/Seaborn 默认字体固定为 Noto CJK，避免中文图表在生成 PNG
时已经丢失字形；不要在分析命令中改回仅含 DejaVu 的字体配置。
部署时从该镜像创建并激活自定义 Snapshot `sandbox-tools-20260722`；不要复用不可删除的
System Snapshot。工具镜像更新后必须重新创建并激活该自定义 Snapshot；仅推送同名 Registry tag
不会刷新既有 Snapshot 的固定镜像引用。

应用默认读取 `/home/junge/pros/agents_app/.env`，复用其中的 `MODEL`、
`OPENAI_BASE_URL` 和 `OPENAI_API_KEY`。可通过 `AGENT_ENV_FILE` 指向其他
环境文件；已存在的进程环境变量优先于文件内容。

开发会话和 workspace 注册表统一保存在 PostgreSQL。连接配置优先读取
`AGENT_DB_URL`，其次读取 `DATABASE_URL`；未提供完整 URL 时，根据
`AGENT_POSTGRES_HOST`、`AGENT_POSTGRES_PORT`、`AGENT_POSTGRES_DB`、
`AGENT_POSTGRES_USER` 和 `AGENT_POSTGRES_PASSWORD` 生成连接串。统一 Compose 将专用
PostgreSQL 绑定到 `127.0.0.1:55432`，容器内 AgentOS 则通过 `agent-db:5432` 连接。
外部 PostgreSQL 首次使用时仍可运行 `bash scripts/init_agent_db.sh` 安全创建数据库；
认证沿用环境变量或 `.pgpass`。

普通 `/agui` 请求只接收当前用户消息，页面工具续跑只接收末尾连续工具结果；fresh request
由服务端从 AgentOS PostgreSQL 装配预算历史，续跑沿用原暂停 run，不重复注入。历史回答重生成使用受控 branch 元数据和源、
目标 thread 双 capability，在新 thread 中复制截至目标 run 的历史并调用 Agno 原生
`regenerate=True, replace_original=True`。分支工作区复制源会话当前文件，限制为 2000 个
普通文件、总计 256 MiB、单文件 25 MiB，符号链接或任一超限会整体拒绝。

`AGENT_SKILLS_DIR` 使用 Agno 官方 `Skills(loaders=[LocalSkills(...)])` 方式加载。
Skills 保持渐进披露：模型先看到名称和描述，再按需读取指令、reference 或 script，
不额外实现 Hermes `skill_manage` 或宿主侧动态工具协议。服务端 Toolkit 的按需加载使用 Agno
原生 callable tools factory。BaseToolkit 的工具和公开参数均提供
面向模型的 schema 说明、长度/范围/格式约束和 `additionalProperties: false`，并通过 Agno 原生
`Function.parameters` 注入参数边界。BaseToolkit 和 WorkspaceReportToolkit 均通过 Agno 原生
Toolkit instructions 注入各自的工具选择、迭代、失败恢复和完成校验规则；
指令明确所有基础工具共享当前 thread 的同一 Daytona
sandbox，独立只读探查可并行，存在依赖时串行，并在修改前后校验真实文件状态。
这些 Hermes/Codex 对齐只改善能力发现和执行纪律，不会把工具执行移到 AgentOS 宿主机，
也不会放宽确认、网络、路径、文件或超时边界。
