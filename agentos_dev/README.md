# 最小 AgentOS 开发应用

该应用提供两个 HRP 集成端点：

- `POST /agui`：标准 AG-UI SSE 运行端点。
- `POST /agui/cancel`：显式取消当前 capability/thread 绑定的 Coding 或 Report 任务。
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

Coding 与 Report 的内部入口在包和资源生命周期上相互独立，仍可使用同一套模型、数据库和 Daytona
工作区配置。独立 CLI 不启动 FastAPI、Team 或 AG-UI 路由：

```bash
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.coding.cli
```

报表模式使用同一个 `ReportWorkflowController` 和终端审核 adapter；输入严格的
`ReportRequestEnvelope` JSON 后，以单独一行 `/run` 提交。连接信息只能来自服务端数据源注册表，
DDL 仅用于 metadata 明确返回零个 Agent 时的 schema fallback：

```bash
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.coding.reporting.cli
```

仅运行内部 facade AgentOS 时使用：

```bash
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.coding
AGENT_ENV_FILE=.env .venv-agent/bin/python -m agentos_dev.coding.reporting
```

两者都只注册由 Supervisor 或 Workflow 控制的 facade，不公开底层 worker。生产浏览器仍只访问
综合 `agentos_dev.app`。Reporting AgentOS 的 `/agui` 同时接受严格 Envelope JSON 和自然语言：
自然语言原文不在路由层改写，由 `report-agent` 模型生成 ISO 起止日期并调用强类型 Workflow 工具；
`reportGoal` 必须逐字保留用户输入，期间不明确时由模型询问用户，不允许程序猜测。

报表 CLI 在服务和 tracing 初始化前校验 `ReportRequestEnvelope`，随后依次处理来源、提纲、批量 SQL
和发布审核；批准、带反馈拒绝和取消都恢复同一持久化 Workflow run。数据库连接只从服务端注册表加载。

Coding 模式使用 Agno 2.8.2 原生异步 `Agent.acli_app` 提供多轮输入、终端渲染和退出控制。原生 CLI
面向保留 Agno Agent 接口的确定性转交实体；其 `arun` 不调用模型，而是把完整目标直接交给
`CodingTaskSupervisor`。只有底层 `coding-agent-cli` 使用 `MODEL`，并按
`AGENT_CODING_ENABLE_THINKING` 传递 `enable_thinking`、使用 `reasoning_effort=medium` 执行受控工具闭环。
Reporting Coding worker 和结构化 planner 默认由独立的
`AGENT_REPORT_ENABLE_THINKING=true` 开启 thinking；普通 Assistant/Team 由
`AGENT_ASSISTANT_ENABLE_THINKING=false` 独立控制，公开 facade 始终关闭 thinking。
因此 CLI 不导入
`agentos_dev.app`，同时与生产 `/agui` 共用 Task/Attempt/Execution、租约、续跑和完成门禁。
PostgreSQL 中 Coding Repository 使用独立的 `agentos_coding` schema 和版本表，不写入 Agno
的 session、run 或 schema-version 表；SQLite 单实例开发仍使用默认 schema。

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

主 Assistant 通过 Agno callable tools factory 注册 `AgentControlToolkit` 和 `BaseToolkit`；
Coding Agent 固定注册生产 `WorkspaceCodingToolkit`。公开 `report-agent` 只注册
`ReportWorkflowToolkit` 的启动、批准、拒绝和取消四个 facade 工具；未注册到 AgentOS 的
`report-worker` 才持有 `WorkspaceCodingToolkit` 和 `WorkspaceReportToolkit`；它只能读取 Workflow
提交的不可变数据集。生产 Coding Toolkit 继承 Agno
`DaytonaTools` 类型，但跳过其创建 sandbox 的初始化逻辑，通过共享 `CodingExecutionKernel` 和
`WorkspaceService` 使用当前 thread 唯一 Daytona sandbox。旧 `CodingToolkit` 仅保留兼容与回归测试，
不会与生产 Toolkit 同时提供给模型。
Base 层提供受限终端及
后台会话、基于 ripgrep 的文件/文本搜索、分段读取、文件统计、递归目录树、SHA-256、只读 Git、
定位 hunk、单文件补丁、完整变更集、目录创建、文件复制、图片查看和 PDF 检查；报表 worker 的内部
工具提供数据登记、多轮分析和 Markdown 转 PDF。BaseToolkit 的读取、检查和后台轮询无需确认，新建、覆盖、
补丁、移动、删除、通用 `sandbox_exec`、后台输入及终止需要确认；生产 Coding Toolkit 的受控终端、
进程、补丁、显式验证、只读检索、输出重读、图片、计划和验收工具均不要求确认。
所有能力仍绑定当前 thread 的 Daytona
sandbox；实际安全边界包括 `network_block_all`、路径和符号链接校验、文件/结果大小限制以及
前台命令最长 60 秒、后台命令最长 86400 秒；后台命令仍须设置明确时限。

Base 层采用少量强工具，并提供分段读取、分页搜索、精确替换及陈旧文件检测，
不直接挂载 Agno 的 `Workspace`、`FileTools` 或 `CodingTools`，因为这些工具操作 AgentOS 宿主目录，
无法继承本项目的 Daytona/thread 隔离；`BaseToolkit` 是面向该边界的 coding agent 实现，覆盖 read、
edit、write、shell 以及 grep/find/ls。文件和文本搜索在 Daytona sandbox 内通过服务端生成的
`rg` 参数执行，支持多 include/exclude glob、正则、智能大小写、整词、上下文、文件列表和计数输出，
不接收模型提供的任意 flags。分段读取、统计、目录树和哈希在 sandbox 内复用 `sed`、`wc`、
`stat`、`find` 与 `sha256sum`，因此可检查超过 1 MiB 的文件且不会先下载到 AgentOS。Git status、
diff、log 和 show 同样使用固定只读参数，不开放任意 Git flags；失败时仅返回仓库、修订、路径或通用
错误分类，不回传原始 stderr。定位 hunk 绑定原文件 SHA-256 和 1-based 行坐标，并与批量补丁一样在
全部目标预检通过后才写入。完整变更集可在一次预检和确认中
执行 create/update/delete/move，每个既有文件都绑定预期 SHA-256；任一预检失败时零写入，执行失败
按逆序回滚。短命令采用一次性受监督执行；异步命令使用 Daytona 原生 session，最多同时四个、
单个最长 86400 秒，并通过 UTF-8 字节日志游标分页轮询、输入、中断或终止；交互式命令可通过
`script` 获取指定行列且默认关闭输入回显的 PTY，禁止
`nohup`、`disown` 和 shell 后台符号绕过受管生命周期。后台启动可用 `yield_time_ms` 等待最多
30 秒并返回耗时、原始字节数和日志游标；后台输入也可在写入后按同一游标直接等待新输出。
每轮报表分析调用必须提供完整非空命令，
失败输出会返回模型继续修正。单次完整文本读取限制为 64 KiB，更大文件必须分段读取。
Coding Agent 与 `report-worker` 在每个工具批次后持久化 checkpoint；模型请求遇到临时失败时最多重试两次并指数退避。
Coding `terminal.command` 以 UTF-8 字节计最多 32 KiB；大段文件内容必须通过文件修改工具传输。

## Coding Agent 配置

这里的“对齐”是让内部 `report-worker` 成为受 Daytona 隔离的 coding agent 扩展，同时让公开
`report-agent` 保持轻量 Workflow facade。当前采用以下配置：

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
| `AGENT_TRACING_ENABLED` | `false` | 将 Agent、模型和工具 OpenTelemetry trace 写入 AgentOS 数据库 |
| `compress_tool_results` | `True` | 仅压缩历史分析工具的大结果 |
| `enable_session_summaries` | `True` | 成功 run 后滚动更新非权威摘要 |
| `AGENT_ASSISTANT_ENABLE_THINKING` | `false` | 控制普通 Assistant/Team thinking |
| `AGENT_CODING_ENABLE_THINKING` | `true` | 控制纯 Coding worker thinking |
| `AGENT_REPORT_ENABLE_THINKING` | `true` | 控制 Report Coding worker 和 Reporting planner thinking |
| `AGENT_REPORT_ENABLE_VISION` | `false` | 控制 Report Worker 是否暴露图片检查工具并向模型发送媒体 |

Coding Agent 和原生 CLI 额外使用同一个 `ContextBudgetController`：有效上下文上限取
`AGENT_CONTEXT_TOKEN_BUDGET` 与 96K token 的较小值，并至少保留 32K token 输出空间。未超预算时只在
尾部追加消息，不按消息年龄改写已发送的模型前缀；超预算后再批量把旧 Coding 工具结果转换为包含工具、
参数摘要、状态、SHA-256 和重读参数的确定性 receipt，必要时生成 `CODING_CHECKPOINT`。Skill 结果仍按
最近 10 条窗口和 `SKILL_PRUNED` 规则选择，但在 Coding Agent 中与预算压缩批次一起生效。所有压缩只
写入 `compressed_content`，不修改持久化消息的原始 `content`，也不调用压缩模型。

内部 Coding Agent 与 `report-worker` 继续共享模型、存储、检查点和历史预算配置，但身份、指令和工具能力相互独立：

```python
coding_agent = Agent(
    tool_choice="auto",
    tool_call_limit=None,
    checkpoint="tool-batch",
    retries=0,
    add_history_to_context=False,
    compress_tool_results=True,
    enable_session_summaries=True,
)
coding_agent.model.retries = 2
coding_agent.model.exponential_backoff = True

# Agno 2.8.2 会在构造时把 None 归一化为 3；这里恢复的是检索语义。
coding_agent.num_history_runs = None
```

生产 `/agui` 只创建 ID 为 `hrp-assistant-team` 的一个 Agno `TeamMode.coordinate` Team，配置为
`tool_choice="auto"`、`checkpoint="runs"`，静态成员只有 `general-assistant`。Team 领导者可直接
回答普通问题；需要普通助手的技能或工作区服务端工具时才委派。Coding 与 Report 仍是独立的内部能力，
暂不注册到综合 AgentOS，也不属于该 Team。

请求中合法的固定宿主 command 和 `odoo.business.<namespace>.<command>` 由 Agno AG-UI 路由写入
Team 顶层 `RunContext.client_tools`，不会复制到成员。Team 领导者只在用户明确要求页面或业务操作时
调用这些工具；工具目录本身只表示能力可用。`external_execution=True` 工具由 Agno 原生暂停 Team
run，浏览器回传结果后通过官方 continue 流程续跑同一个 `run_id`。自动生成的 `/agents/*/runs` 和
`/teams/*/runs` 运行入口统一禁用，浏览器只能经过带 capability 和输入清洗的 `/agui`。

当前版本只支持 `hrp-assistant-team` 的 TeamSession 和 run。旧 `odoo-assistant-team`、旧 standalone
AgentSession 以及旧 command member 的暂停 run 不做迁移或续跑兼容；升级后必须创建新 thread/run，
不能向新入口提交旧工具暂停结果。branch 仅接受能在当前 TeamSession 中确认的源 run。

PostgreSQL 仍永久保存完整 runs 和原始 `Message.content`。完整模型上下文上限为 256K tokens，
预算装配器为输出预留 32K，并根据最新 HRP 宿主快照、当前用户输入和客户端工具 schema 的估算
动态缩小历史预算；默认历史最多 192K。待确认操作和当前 run 结果属于强制上下文，不会为了保留
旧历史而裁剪。旧 `odoo.*` 工具调用和结果不进入后续模型上下文，避免旧快照、token 和
modifiers 与最新 `BasicModel` 状态竞争；`sandbox_exec`、`sandbox_process_poll`、`exec_command`、
`poll_process`、`write_stdin`、`stop_process` 以及历史 `report_analyze_dataset` 结果保留，
大结果优先使用独立的 `compressed_content`，原文不被覆盖。

滚动摘要只包含用户目标、已确认决策、工作区产物、完成事项和待办事项，并标记为非权威历史。
摘要和压缩都不能作为 Odoo 业务事实；需要记录值、筛选、权限或页面状态时，必须使用本轮最新
宿主快照。压缩和摘要辅助模型始终关闭 thinking。普通 Assistant/Team 由
`AGENT_ASSISTANT_ENABLE_THINKING` 控制，内部 Coding Agent 由
`AGENT_CODING_ENABLE_THINKING` 控制，`report-worker` 和 Reporting planner 由
`AGENT_REPORT_ENABLE_THINKING` 独立控制。Coding facade 的 Agno 官方 `arun(..., stream=True, stream_events=True)` 实时返回
`ReasoningStarted`、原始 `ReasoningContentDelta` 和 `ReasoningCompleted`；只投影 reasoning 文本，
不返回 provider 原始字段。终态持久化前仍清除 reasoning 字段，原始 reasoning 不进入 session 或
数据库。AG-UI、自定义 SSE 和 React 不转发或展示原始 reasoning，前端只展示“正在分析当前请求”
或“正在整理工具结果”等确定性状态。

相关环境变量可独立回退：`AGENT_ENABLE_TOOL_RESULT_COMPRESSION=false` 停止生成新压缩结果，
`AGENT_ENABLE_SESSION_SUMMARIES=false` 停止更新和注入摘要，
`AGENT_ASSISTANT_ENABLE_THINKING=false`、`AGENT_CODING_ENABLE_THINKING=false` 和
`AGENT_REPORT_ENABLE_THINKING=false` 分别关闭普通 Assistant/Team、纯 Coding worker 和
Report Coding worker/Reporting planner thinking；`AGENT_CONTEXT_TOKEN_BUDGET`、
`AGENT_HISTORY_TOKEN_BUDGET` 和
`AGENT_OUTPUT_TOKEN_RESERVE` 分别调整完整窗口、历史上限和输出余量。关闭任一能力都不会删除 PostgreSQL
中的完整历史，也不会改变 `agui.odoo.v2`、命令确认、授权或 stale snapshot 校验。
新建 Daytona 工作区使用 `DAYTONA_DEFAULT_SNAPSHOT` 指定的 snapshot，默认值为 `sandbox-tools`。
默认继续设置 `network_block_all=true`；运维可通过 `DAYTONA_NETWORK_ALLOW_LIST` 为新建 sandbox
配置最多 10 个逗号分隔的 IPv4 CIDR，此时只发送 `network_allow_list`。白名单不支持端口约束，
已有 sandbox 也不会自动变更网络策略；端口限制仍由出口防火墙或目标服务 ACL 承担。
`AGENT_DEBUG` 与三套 thinking 开关独立生效；同时开启 debug 和任一 thinking 时，Agno 调试日志可能包含
provider reasoning。不得在生产环境记录包含业务数据的请求、响应正文或 reasoning。

上述配置不改变能力边界。Odoo `BasicModel` 仍是业务页面状态的唯一事实来源；命令仍经过
注册、策略、准备/确认和一次性授权链路；分析命令仍受 thread 隔离、Daytona、网络、路径、
文件大小、输出大小和超时限制。

### 计划、工具发现与上下文状态

Agno 2.8.2 支持 `session_state`、AG-UI `STATE_DELTA`、callable tools factory 和固定步骤
Workflow，但没有内置的专用 `update_plan`。本项目因此提供受约束的计划工具：主 Assistant
继续使用 `agent_update_plan`，Coding/Report Agent 使用 `update_plan`；两者最多 20 步、最多一个
`in_progress`，且只写保留键 `agentos_plan`。计划是任务进度，不是 Odoo 业务事实，也不得保存快照、
授权或 modifiers。

`agent_tool_search` 搜索服务端 Toolkit 类别，`agent_load_toolkit` 只修改保留的加载状态。Agno
在每个 run 开始时解析一次 callable tools，因此新 Toolkit 从下一 run 生效；这不需要用户确认，
也不会绕过具体工具原有的确认策略。`cache_callables=False` 防止不同 thread 或不同加载状态复用
错误的工具列表。搜索结果带 `routeSkill` 时只用于发现，不能通过 `agent_load_toolkit` 加载；当前综合
入口不会因此把 Coding 或 Report 动态加入 Team。续跑和 regenerate 始终使用当前 Team；branch 的
源 run 无法在当前 TeamSession 中确认时失败关闭。

### 泛化数据源与 ReportAgent

`coding-agent` 不属于生产 Team，也不注册到综合 AgentOS 的公开 agents 列表；Supervisor 仅在
Attempt 内调用原始 Agent 的
`WorkspaceCodingToolkit` 固定工具集。
`terminal` 将前台/后台语义映射到受管命令，并在远端 session 创建前写入持久 execution 预留记录；
`process` 支持
`list/poll/wait/kill/write/submit`，未暴露底层不能可靠保证的完整历史日志、关闭 stdin 和异步通知；
`create_files` 在一次原子补丁中创建一个或多个不存在的目标；`overwrite_file` 要求调用方提供当前 SHA-256；`replace_text`
使用服务端读取的 SHA-256 做唯一或全部精确替换；`apply_patch` 复用原生补丁。
`apply_patch` 支持 Add/Update/Delete/Move、多文件与多 hunk，并在工作区服务层原子提交；仅对完整
Markdown/heredoc 外壳和 Add File 纯空行提供有限格式兼容。对于不能稳定生成补丁函数参数的兼容模型，
`terminal` 还接受完整、独立的 `apply_patch <<'PATCH'` heredoc：服务端在进入远端 Shell 前拦截
它并复用同一 Patch 解析与原子提交层，因此不依赖 Daytona 镜像安装同名命令；格式错误或夹带其他
Shell 命令时拒绝且不写文件。供应商 API 已拒绝的畸形函数参数无法到达该 fallback，仍须由模型或
供应商重试为有效工具调用。`report-worker` 从该基座派生，固定暴露生产 Coding Toolkit 和
`WorkspaceReportToolkit`，但不注册为 AgentOS 公共 Agent 或 Team
member。生产路由仍由公开 `report-agent` 接收，它只通过四个 `report_workflow_*` 工具调用
`ReportWorkflowController`；`AgentOS` 不额外注册 Workflow，也不增加第二条传输链路。
`agentos_dev.coding.reporting` 的 Agno Workflow 依次处理来源解析、受限画像、提纲审核、分析计划、取数需求、
SQL 候选与按需审核、不可变数据集物化、Coding 分析、PDF 验收和发布审核。AG-UI 和 CLI adapter
只负责暂停、反馈、继续和取消。Report 层保留数据源物化、输入绑定、Markdown/PDF 渲染及验收。
来源和 Schema 唯一确定时直接继续，仅在多个报表 Agent 需要用户选择时暂停。
完整文件内容不会注入 facade 模型；内部 worker 只从 AnalysisPlan、DataRequirement 和
DatasetHandle 取得分析输入，不持有数据库凭据。
复杂分析优先通过受控只读工具检查文件、搜索内容和查看 Git 状态或差异；新文件使用
一次创建一个或多个新文件使用 `create_files`，完整覆盖使用带最新 SHA-256 的 `overwrite_file`，已有文件的小范围修改优先使用
`replace_text`，删除、移动或多文件修改使用 `apply_patch`。
命令使用 `terminal` 和 `process` 执行与
持续管理，不再经过 `report_analyze_dataset` 的二次命令封装。生产 Coding Toolkit 不设置 Agno
HITL 确认，分析执行仍受 Daytona 网络隔离、路径、进程、超时和输出大小限制；
不新增 AgentOS 宿主机 Python 或绕过现有工作区边界的执行入口。

普通 `terminal` 保守计为潜在 mutation，但不再充当验证。`verify` 在当前工作区前台执行命令，
把命令摘要、退出码、执行后的 mutation 和指定产物摘要写入验证回执；`finish_task` 未显式收到
`verification_ids` 时，自动选择当前 mutation 最近一次成功的 `verify`。文本结果超过 48 KiB 时
返回确定性的首尾预览和 `outputHandle`，完整结果在容量限制内保存在工作区根目录之外，并可用
`read_tool_output` 按 UTF-8 字节偏移重读。

Coding 任务统一由 `agentos_dev.coding.CodingTaskSupervisor` 编排：一个 `CodingTask` 表示完整目标，
每次 Agno internal run 是一个 `Attempt`，terminal/process/文件修改/verify 副作用保存为 `Execution`。AG-UI、
Team member 和 CLI 只通过薄 adapter 调用 Supervisor；AG-UI adapter 位于 `agentos_dev.coding`，
其余 Coding 核心模块不导入 FastAPI、Team、Report 或 `agentos_dev.app`，也不通过工具名或 AG-UI
事件推进任务状态。

客户端始终只看到原始 external `run_id`。断线恢复复用当前 Attempt 的同一 internal `run_id`，只增加
`resume_count`；只有 continuation 才创建下一 Attempt。Attempt 0 不消耗预算，最多创建 Attempt 20，
因此一个任务最多 21 个 Attempt；24 小时 deadline 从任务创建时计算，新指令和恢复均不重置。
连续相同规范化错误三次后失败关闭。`TaskSession` 每 15 秒独立续租，租约 TTL 为 45 秒；断线取消
本地 Agno coroutine，清理未保留 Execution，并把可恢复任务置为 `suspended`，不会在无连接时后台继续。
配额不足、认证失败、无效模型请求和 provider 限流分别返回 `model_insufficient_quota`、
`model_authentication_failed`、`model_invalid_request` 和 `model_rate_limited`，暂停 Task 并释放租约，
不自动增加 `resume_count` 或创建 continuation；外部条件恢复后由原 external run 显式恢复。

`finish_task` 使用单次 sandbox 上下文的批量哈希做两阶段产物校验，并验证计划、最后 mutation 后的
成功显式 verification、活动进程、健康服务和 pending
instruction 后先保存不可变 `finish_receipt`，把 Task 置为 `finishing`、Attempt 置为
`finish_requested`；Agno run 到达终态后才原子完成 Task。最终消息 ID 固定为
`<external_run_id>:final`，终态事件 ID 固定为 `<external_run_id>:terminal`，未验收的候选总结不会发布。

Task 可选的 `acceptance_contract` 只从服务端可信 dependency 进入 Supervisor，不属于
`run_coding_task` 的模型工具参数；客户端同名 context 会在请求准备阶段被清除。契约创建后不可修改，
最多 64 KiB、32 个 requirement，每项引用 `<skill>:<validator>` 并声明固定参数和相对产物 glob。
Skill 通过 `metadata.agentos.acceptance.validators` 注册 `scripts/*.py`、固定 timeout 和允许的
`artifactPatterns`；服务启动时固定脚本内容与 SHA-256。`verify(validator_id=...)` 使用 `python3 -I`
在 Daytona 中运行该固定脚本，请求和结果均为严格有界 JSON，回执绑定当前 mutation、validator 摘要及
产物摘要。validator 未通过时额外返回有界的 `failedRequirements`、`passedRequirements` 和定向
`requiredActions`，供 Coding Agent 只修失败能力并保护已通过行为。`finish_task` 缺少、失败或过期的语义证据时分别返回 `finish_acceptance_missing`、
`finish_acceptance_failed` 或 `finish_acceptance_stale`；相同状态重复提交仍由 `finish_no_progress`
短路。没有契约的既有 Coding/Report/CLI 任务保持原完成门禁，不会额外运行 validator。
Report 保持独立的既有交付回执门禁，不写入 Coding v2 的状态推进逻辑。

Report v1 只接受服务端注册的 StarRocks 数据源。`AGENT_REPORT_DATA_SOURCES_DIR` 指向配置边界目录；
加载器从边界到当前目录逐层查找 `report-data-sources.json`，同 ID 数据源由子层整项覆盖。
配置只保存 source ID、可选 `reportingProfile` 引用、`dsnEnv`、数据库和查询限额，DSN 只从同名服务端环境变量读取。表范围来自 metadata DDL；期间字段和粒度由模型的数据理解计划声明。
请求、模型上下文和 Workflow state 均不接受连接字段。示例：

```json
{
  "version": "1",
  "defaultSourceIds": ["operations"],
  "sources": [
    {
      "id": "operations",
      "name": "运营数据",
      "type": "starrocks",
      "dsnEnv": "REPORT_STARROCKS_DSN",
      "database": "reporting",
      "statementTimeoutSeconds": 30,
      "maxRows": 1000000,
      "maxBytes": 268435456,
      "profileConcurrency": 4,
      "queryConcurrency": 2
    }
  ]
}
```

同一配置边界下的 `reporting_profiles/**/*.json` 使用显式 `profileId`/`extends` 组织平台、行业、集团、
医院和模板层。目录名不产生隐式继承；有效 Profile 按稳定 code 合并并计算 hash。Profile 只能通过
结构化字段引用、受限聚合和对账规则缩小 Snapshot，不能包含 SQL、表达式或连接信息。未绑定 Profile
的数据源使用内置领域无关章节。

StarRocks 使用官方 `starrocks==1.3.3` SQLAlchemy dialect。数据源账号权限不作为启动门禁；
API/DDL 模型仍必须与实时 catalog 一致。

SQL 只允许单条 `SELECT` 或只读 CTE，并强制只读事务、超时、Snapshot 表字段白名单和结果
分片限制。Compose 默认只读挂载仓库中的 `rj` 配置，固定允许 6 张经营视图，并从
`REPORT_STARROCKS_DSN` 注入连接；生产环境也可通过 `AGENT_REPORT_DATA_SOURCES_DIR` 指向宿主机
配置目录。metadata 只能缩小该白名单，不能动态扩大。
`AGENT_REPORT_METADATA_URL` 配置外部 metadata 服务基址，`AGENT_REPORT_METADATA_TOKEN` 配置其
Bearer token；未配置 URL 表示明确禁用 metadata 服务，而网络、鉴权、5xx 或响应契约错误均失败关闭，
不会降级为零 Agent。

综合 AgentOS 在启动时创建 `report_download_grants_v1`；正式部署应以等价数据库迁移预建该表。
最终发布审核批准前不签发下载 grant。批准后返回的同源
`GET /reports/v1/download/{opaqueGrant}` 必须携带现有 `X-AGUI-Thread` 和
`X-AGUI-Capability`，并继续校验数据库、用户、公司、Odoo session、thread、Workflow run、
report revision 与 PDF hash。应用会脱敏 Uvicorn access log 中的 grant 路径；反向代理、网关和
APM 也必须将 `/reports/v1/download/*` 记录为固定占位路径，禁止采集原始 URL。

独立 Report AgentOS 没有 Odoo capability 提供的数据库、公司和 session scope，因此默认不装配 HTTP
发布 issuer；最终发布审核会以 `report_publication_unavailable` 失败关闭。只有上游认证中间件能提供
同等完整且已验证的身份时才能启用 HTTP 下载，不能使用空值或固定占位身份。

`agent_context_status` 使用 Agno 模型的 `count_tokens(messages, tools, output_schema)` 估算本轮完整
上下文，返回 256K 上限、估算已用、扣除输出预留后的余量、预算历史和计数可靠性；计数器不可用时
明确标记为不可靠，不回退注入全历史。它不返回旧 Odoo 工具结果或业务字段。余量不足时可调用
`agent_prepare_continuation` 保存摘要、待办和工作区相对产物路径；该工具只建立下一 run 可见的受控
交接，不会递归启动 run，也不会绕过工具确认。计划全部完成时交接状态会被清除。

智能报表 Workflow 先将数据源物化为当前 thread 绑定的 DatasetHandle，再以 SHA-256、大小和 thread
绑定创建服务端 job。内部 `report-worker` 随后使用 Coding Toolkit
执行当前 Daytona 工作区允许的 Python、Shell 或其他分析命令；公开 facade 不接收 DatasetHandle、
SQL 或数据库凭据。Report 层不再提供能力探测、固定剖析、
独立命令执行器、60 秒分析超时或成功轮次门槛。模型生成完整 Markdown 和本地图表后，将其渲染为
不覆盖已有文件的新 PDF；渲染和 PDF 验收各自最多运行 600 秒。PDF 限制为 200 MiB 和 200 页，运行时使用
Poppler 将 PDF 逐页栅格化，检查空白页、页眉页脚、页码、文本、图片数量和像素占比，并把 Markdown、图片、PDF 的
路径、大小、SHA-256 和验收结果写入 Workflow 持久化状态。只有 PDF 验收通过且最终发布审核获批，
SSE 交付门禁才返回正式产物。系统不再使用固定模板、`compile` 或 `blocks`。
Markdown 必须包含与 manifest 一致的 `[[citation:<citationId>]]` 引用标记和
`[[section:<sectionCode>]]` 关键章节标记；图表路径、Markdown、PDF、数据集 snapshot、CodingTask key
和 report revision 通过 `ReportArtifactManifest`/`PdfArtifactManifest` 的大小与 SHA-256 绑定。
sandbox 的 `/tmp/workspace-report-*` 仅用于一次渲染或验收的临时文件；超时和失败都会由 AgentOS 清理，
不能作为 job 状态或验收依据。Markdown、图片和 PDF 输出到 `报表/生成结果/<job_id>/`。生产环境必须使用仓库现有
`docker/sandbox-tools` 镜像，以提供 ripgrep、WeasyPrint 69、pypdf、数据分析库和 Noto CJK。镜像
同时安装 `matplotlibrc`，将 Matplotlib/Seaborn 默认字体固定为 Noto CJK，避免中文图表在生成 PNG
时已经丢失字形；不要在分析命令中改回仅含 DejaVu 的字体配置。
部署时从该镜像创建并激活自定义 Snapshot `sandbox-tools-20260723`；不要复用不可删除的
System Snapshot。工具镜像更新后必须重新创建并激活该自定义 Snapshot；仅推送同名 Registry tag
不会刷新既有 Snapshot 的固定镜像引用。

应用默认读取当前工作目录下的 `.env`，复用其中的 `MODEL`、
`OPENAI_BASE_URL` 和 `OPENAI_API_KEY`。可通过 `AGENT_ENV_FILE` 指向其他
环境文件；已存在的进程环境变量优先于文件内容。

Agent、Team、Coding 任务和 workspace 注册表共享同一 Agno 数据库。连接配置优先读取
`AGENT_DB_URL`，其次读取 `DATABASE_URL`；未提供完整 URL 时，根据
`AGENT_POSTGRES_HOST`、`AGENT_POSTGRES_PORT`、`AGENT_POSTGRES_DB`、
`AGENT_POSTGRES_USER` 和 `AGENT_POSTGRES_PASSWORD` 生成连接串。统一 Compose 将专用
PostgreSQL 绑定到 `127.0.0.1:55432`，容器内 AgentOS 则通过 `agent-db:5432` 连接。
外部 PostgreSQL 首次使用时仍可运行 `bash scripts/init_agent_db.sh` 安全创建数据库；
认证沿用环境变量或 `.pgpass`。

OpenTelemetry tracing 默认关闭。设置 `AGENT_TRACING_ENABLED=true` 后，生产 AgentOS 和原生
CLI 会通过 Agno OpenInference instrumentation 完整采集 Agent run、模型调用和工具执行，包括
Prompt、模型输出、工具参数与工具结果，并写入同一数据库的 `agno_traces` 和 `agno_spans` 表。
生产 AgentOS 保持即时数据库导出；原生 CLI 使用批量导出降低工具闭环中的写库开销，并在关闭
模型、工作区和数据库连接前同步 flush，确保正常退出时已排队的 span 落库。
AgentOS API/UI 可从该数据库查询 trace；数据不写入 `agentos_coding` schema，也没有单独的清理
任务。由于 trace 可能包含用户输入、业务数据和完整工具载荷，生产环境必须依赖现有数据库访问
控制和备份策略保护这些内容。缺少 tracing 依赖或初始化失败时，启用状态下服务会拒绝启动。

配置 `AGENT_TRACING_PHOENIX_ENDPOINT` 后，trace 会继续即时写入 Agno 数据库，同时通过 OTLP
HTTP 批量发送到 Phoenix。地址可填写 collector 基址（例如 `http://127.0.0.1:6006`）或完整的
`/v1/traces` 地址；Phoenix Cloud 使用 `AGENT_TRACING_PHOENIX_API_KEY`，项目名称通过
`AGENT_TRACING_PHOENIX_PROJECT` 设置，默认 `agentos`。外发使用同一个全局 tracer provider，
运行期间不支持动态切换；修改配置后必须重启所有 AgentOS/CLI 进程。外部 Phoenix 与数据库会
各自保存完整载荷，必须分别配置访问控制、TLS、保留和删除策略。根 Compose 不启动 Phoenix；
Phoenix 在宿主机运行时，AgentOS 容器应使用 `http://host.docker.internal:6006`，不能使用容器自身的
`127.0.0.1`。

PostgreSQL 是多实例生产默认。文件型 SQLite 仅用于单实例开发兼容，支持
`sqlite[+aiosqlite]:///`，启用 WAL、foreign keys 和 busy timeout，并拒绝内存数据库。任务、内部 run
映射和 execution 回执使用可移植 SQLAlchemy 表与 Agno schema version；活动记录不清理，终态及有界
模型可见输出保留 7 天后由数据库租约协调的惰性清理删除。

Coding v2 采用协调停机迁移，不支持新旧实例并行双读双写。部署时先停止旧实例并备份数据库，再由
新版本在 schema advisory lock 下完成加列、Instruction 表、唯一索引和回填，成功后只启动新版本。
旧活动 Execution 以 epoch 0 导入；发现重复 Attempt 编号或无法判定的数据时迁移失败关闭，不静默修正。

普通 `/agui` 请求只接收当前用户消息，页面工具续跑只接收末尾连续工具结果；fresh request
由服务端从 AgentOS PostgreSQL 装配预算历史，续跑沿用原暂停 run，不重复注入。历史回答重生成使用受控 branch 元数据和源、
目标 thread 双 capability，在新 thread 中复制截至目标 run 的历史并调用 Agno 原生
`regenerate=True, replace_original=True`。分支工作区复制源会话当前文件，限制为 2000 个
普通文件、总计 256 MiB、单文件 200 MiB，符号链接或任一超限会整体拒绝。

`AGENT_SKILLS_DIR` 使用 Agno 官方 `Skills(loaders=[LocalSkills(...)])` 方式加载。
Skills 保持渐进披露：模型先看到名称和描述，再按需读取指令、reference 或 script，
不额外实现 Hermes `skill_manage` 或宿主侧动态工具协议。服务端 Toolkit 的按需加载使用 Agno
原生 callable tools factory。BaseToolkit 的工具和公开参数均提供
面向模型的 schema 说明、长度/范围/格式约束和 `additionalProperties: false`，并通过 Agno 原生
`Function.parameters` 注入参数边界。BaseToolkit 和 WorkspaceReportToolkit 均通过 Agno 原生
Toolkit instructions 注入各自的工具选择、迭代、失败恢复和完成校验规则；
指令明确所有基础工具共享当前 thread 的同一 Daytona
sandbox，独立只读探查可并行，存在依赖时串行，并在修改前后校验真实文件状态。
这些工具对齐只改善能力发现和执行纪律，不会把工具执行移到 AgentOS 宿主机，
也不会放宽确认、网络、路径、文件或超时边界。

`coding-agent` 还固定加载随 AgentOS 镜像打包的 `agentos_dev/builtin_skills/sandbox-tooling` 系统
Skill，内部 `report-worker` 从 coding 基座继承该 Skill，公开 `report-agent` 不加载 Coding Skill。
该系统 Skill 按需披露当前 Daytona sandbox-tools
镜像已预装和明确未预装的开发、文档、数据及数据库客户端能力。生产 Coding Agent 不受
`AGENT_SKILLS_DIR` 配置影响，也不进入前端可选业务 Skill 列表；原生 CLI Coding Agent 会在该
内置 Skill 之后追加加载 `AGENT_SKILLS_DIR`，并以 Agno `LocalSkills(validate=False)` 兼容
Hermes 扩展 frontmatter；内置 Skill 仍保持严格校验。CLI 执行期间把内部 Coding 工具转换为
Agno 原生 tool-call 事件并显示在 `Tool Calls` 面板，参数有界且脱敏，不显示工具结果正文。调整
`docker/sandbox-tools/Dockerfile` 或其 `requirements-*.in` 时必须同步更新该系统 Skill。
