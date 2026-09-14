# Reporting 会话 Workspace、宿主机 CodeMode 与 Matplotlib 设计

## 目标

从 `f5` 基线将整个 Reporting Workflow 的工作区与代码执行切换为完全宿主机方案：每个 Agno workflow session 拥有一个专属原生 `Workspace`，数据集、冻结事实、补充分析证据、脚本、图表和报告均在该 Workspace 内流转；分析项与可视化的 Coding 任务使用 Agno 原生 `CodeMode`，图表统一由 Matplotlib 生成。不调用 Daytona、local-sandboxd、bubblewrap、容器或其他隔离运行时，同时保持现有 Workflow 的阶段、重试、检查、提交和 durable state 语义不变。

## 已确认约束

- 使用 Agno 3.0.9 原生 `agno.tools.workspace.Workspace`，不重新实现一套 Agent 文件工具。
- 使用 Agno 3.0.9 原生 `agno.tools.code.CodeMode`，设置 `allow_shell=True` 和 `snapshot=False`。
- Python 与 Shell 直接继承 API 服务进程的宿主机权限，不提供安全隔离承诺。
- 一个 Reporting workflow session 对应一个宿主机目录和一个逻辑 Agno `Workspace`；同一进程内复用同一实例，进程重启后以同一目录恢复等价实例。
- 补充分析与可视化的 CodeMode Python Kernel 均按 Task 隔离；任务结束必须关闭对应 Kernel。
- `%%bash` 可用，但每个 Bash cell 是独立子进程。跨 cell 状态通过 Python Kernel 的 `os.chdir`、`os.environ` 和 Python 变量保持。
- 保留 `VisualizationSectionWorkflow` 及其计划、脚本生成、执行、修复、视觉审查、降级和提交顺序。
- 语义业务校验继续只产生软告警；路径越界、文件身份变化、执行失败和无效产物仍属于技术失败。
- 应用日志使用 Loguru。
- 不复用或修改 `feat/flint-chart-interactive-html` worktree 中的未提交 Flint 实现。

## 范围

本次包含：

- 从整个 Reporting Workflow 移除对 sandbox 工作区和执行器的运行时依赖；
- 为 Reporting 建立会话级宿主机目录映射；
- 让 Workflow 内所有文件工具和程序化文件访问复用同一个会话 `Workspace`；
- 将补充分析和可视化代码 Agent 改为 Workspace + CodeMode 工作方式；
- 使用 CodeMode 在宿主机执行补充分析脚本和签发的 Matplotlib 脚本；
- 保留现有文件身份、图表检查、提交和恢复契约；
- 增加定点单元测试与一个真实宿主机端到端测试。

本次不包含：

- 删除仓库中已有 Daytona 和 local sandbox 的历史实现；
- 修改非 Reporting 模块的执行策略；
- 改写 Reporting Workflow 状态机、数据库 schema 或公开 API；
- 引入 HTML/JavaScript 交互式图表；本分支的图表产物为 Matplotlib PNG；
- 为宿主机执行增加容器、权限降级、命令白名单或人工审批。

## 方案选择

采用“会话专属 Agno Workspace + Task 专属 CodeMode + 薄宿主机适配”方案。

Reporting workflow session 启动时，由会话 Workspace 注册表按可信 `workflow_session_id` 创建或取得唯一的 Agno `Workspace`。Workflow 内所有需要文件的 Agent、领域工具和程序化回调都解析这个实例，不再各自连接远端 workspace。Agent 直接使用 `Workspace` 提供的 `read_file`、`write_file`、`edit_file`、`list_files`、`search_content`、`move_file`、`delete_file` 和 `run_command`。补充分析和可视化 Coding 任务额外使用 CodeMode 的 `execute`/`restart` 完成数据探索、计算、Matplotlib 试绘和 Shell 操作。

固定 Workflow 仍通过现有回调完成文件身份校验、分析证据校验、正式执行、视觉审查和提交。PostgreSQL 中的 task lease、checkpoint、durable state 和操作记录不迁入 Workspace。

不采用“新增 HostSandboxProvider”方案，因为它会把无隔离的本机目录伪装成 sandbox，并复制不再需要的 provider、session、snapshot 和资源状态概念。不采用“全部手写 pathlib/subprocess 工具”方案，因为 Agno 已提供模型可用的本机 Workspace 与 CodeMode。

薄宿主机适配包装会话注册表解析出的同一个 Workspace 根目录，只覆盖 Agno `Workspace` 未提供而 Workflow 必需的程序化能力：二进制读写、SHA-256、普通文件检查、会话目录生命周期和图表产物读取。它不是第二个工作区，不拥有独立目录，不是 Agent Toolkit，也不实现 sandbox provider 协议。

## 目录与路径模型

新增绝对路径配置 `REPORTING_HOST_WORKSPACE_ROOT`。应用启动时解析并创建该根目录；空值、相对路径、普通文件和符号链接均拒绝启动。每个 Reporting 会话使用独立的不可逆 HMAC 摘要目录，摘要输入包含 tenant、user、company、thread 和 Agno session 身份，并复用现有 `workspace_hmac_secret`：

```text
<REPORTING_HOST_WORKSPACE_ROOT>/sessions/<session-hmac-sha256>/
  datasets/
  analysis/
  facts/
  evidence/
  charts/
  reports/
  tasks/<task-id>/
```

现有 durable state、冻结事实身份、图表计划和公开回执中的逻辑路径继续使用 `/home/daytona/workspace/<relative>`，避免修改持久化路径协议。宿主机适配只接受该前缀下的规范化路径，并映射到当前会话目录；绝对宿主机路径不进入模型业务载荷。

Agno 原生 `Workspace` 只接受相对路径。进入 Agent 指令和 Workspace 工具前，服务端把已签发逻辑路径投影为相对于会话根的 `workspacePath`；脚本也逐字使用这些签发的相对路径。Workspace 回执和文件身份在进入现有 Workflow 校验前映射回原逻辑路径。模型不负责删除前缀、拼接目录或推导映射，逻辑路径与相对路径的一一对应由服务端持有。

不同会话的 `Workspace` 均以各自的 `<session-hmac-sha256>` 目录为根，文件工具不能用相对路径访问其他会话。整个 Workflow 的数据集导入、上下文文件、冻结事实、补充证据、脚本、图表、章节草稿和最终报告都使用当前会话内的逻辑路径。CodeMode 创建 task session 后，Workflow 首个 bootstrap cell 将 cwd 切换到当前会话目录；可视化任务同时设置 Matplotlib `Agg` 后端。Workspace、薄适配和 CodeMode 访问同一批物理文件，不做上传、下载或跨运行时复制。

该隔离是运行状态与默认文件视图的逻辑隔离，不是安全隔离。由于 Workspace 的 `run_command` 和 CodeMode `%%bash` 都继承宿主机权限，主动构造绝对路径的代码仍可能访问其他会话或宿主机文件；在“不关闭 Shell、直接宿主机运行”的约束下不能同时承诺恶意代码级目录隔离。

## 会话 Workspace 装配

`ReportingWorkspaceRegistry` 按现有 `workflow_session_id` 管理 Agno `Workspace`。物理目录只由服务端根据 tenant、user、company、thread 和 workflow session 绑定解析，不接受模型提供路径。同一进程内，同一 session 的暂停、恢复和重放取得同一个实例；进程重启后重建指向同一目录的等价实例；不同 session 永不返回同一个实例或目录。

所有需要文件工具的 Reporting Agent 使用 Agno 原生 callable tools factory。工厂从可信 `RunContext.dependencies` 取得 `workflow_session_id`，再从注册表取得会话 Workspace；补充分析和可视化 Coding 任务额外获得共享的 CodeMode：

```python
def reporting_tools(run_context):
    workspace = workspace_registry.resolve_run_context(run_context)
    tools = [workspace, build_task_domain_tools(run_context, exclude_file_tools=True)]
    if is_coding_task(run_context):
        tools.append(code_mode)
    return tools
```

会话 Workspace 创建参数固定为 `root=session_root`、`allowed=Workspace.ALL_TOOLS`、`confirm=[]`。不启用人工确认，因为 Reporting 是现有固定 Workflow 内部执行者，暂停等待 HITL 会破坏现有同步任务契约。由于 Shell 已开放，Workspace root 是默认文件视图而不是安全边界。

领域 Toolkit 不再注册与原生 Workspace 重名的 `read_file`、`write_file`、`list_files`、`search_content`、`move_file` 和 `delete_file`；保留查询业务事实、提交、完成和其他 Workflow 领域命令。Agno 对重名工具采用先注册者生效并忽略后续工具，装配测试必须证明最终工具表不存在重复名称。

Agent 设置 `tools=reporting_tools` 和 `cache_callables=False`。不能使用 Agno 默认 callable cache：其默认 cache key 优先使用 `user_id`，会使同一用户的不同 Reporting 会话复用第一次解析出的任务工具。Workspace 实例的复用只由 `ReportingWorkspaceRegistry` 按 `workflow_session_id` 管理，Agent 本身保持复用，不在任务循环中重新创建。

`code_mode` 是 Reporting 运行时共享的单例，配置 `cwd=REPORTING_HOST_WORKSPACE_ROOT`、`allow_shell=True`、`allow_restart=True`、`snapshot=False`、明确的 timeout/输出/图片上限，以及覆盖补充分析与可视化 Coding 任务总并发上限的 `max_kernels`。它自身按 task-scoped `RunContext.session_id` 分配 Kernel。

补充分析 Agent 必须把最终完整 Python 源码写入分析项签发路径，并生成符合 `supplemental_evidence_output_contract` 的证据 JSON。可视化 Agent 必须把最终完整 Python 源码写入 `visualizationWorkspace.scriptPath`，并生成计划中的全部 Matplotlib PNG。Workflow 对脚本和产物重新计算身份；模型不能自行调用分析完成、图表提交或写 durable completion。

## 数据流

```text
Reporting workflow session 启动
  -> 解析或恢复唯一的会话 Agno Workspace
  -> 数据集、上下文、冻结事实写入该 Workspace
  -> analysis_item 固定五阶段
       -> 需要补证时由 Workspace + CodeMode 生成/修复并执行分析脚本
       -> 校验证据 JSON -> complete_analysis_item
  -> visualization_section 固定流程
       -> 结构化 VisualizationPlanDraft
       -> Workspace + CodeMode 生成/修复并正式执行 Matplotlib 脚本
       -> 校验 PNG -> 可选视觉审查 -> submit_visualization_charts
  -> 章节生成、报告组装、验证与发布继续读写同一 Workspace
  -> durable accepted/degraded/completed 状态仍写 PostgreSQL
```

正式执行不能直接信任生成阶段的试绘结果。每次进入 `execute_script` 都由 Workflow 运行当前签发脚本，并在运行后重新读取计划中每个 `sourcePath` 的普通文件属性、大小和 SHA-256。这样保留现有“脚本身份 + 产物身份”收口语义。

## Workflow 不变项

以下行为不得改变：

- `AnalysisItemWorkflow` 的 read-facts、plan-evidence、execute-script、validate-evidence、complete-analysis 五阶段及条件分支保持不变；
- 固定事实足够时仍跳过补充分析脚本；需要补证时仍执行现有生成、修复、证据校验和放弃补证逻辑；
- `supplemental_evidence_output_contract`、证据文件身份和 `complete_analysis_item` 收口保持不变；
- `VisualizationPlanDraft` 仍由结构化生成器产生且只生成一次；
- 首次生成和修复仍受现有 thinking 选择策略控制；
- 执行修复与视觉审查修复继续使用独立计数和上限；
- 修复后脚本 SHA-256 未变化仍按现有错误处理；
- 视觉审查失败仍回到脚本修复，不允许模型绕过检查；
- 修复耗尽后仍通过现有 `degrade` 回调按零图继续成稿；
- 只有固定 Workflow 可以调用 `submit_visualization_charts` 和写入完成状态；
- task lease、取消、幂等重放、checkpoint 和事件记录保持现状。

允许替换的只有现有回调背后的基础设施实现：脚本生成工具、文件访问和脚本执行。

## CodeMode 生命周期

Reporting 会话目录与 CodeMode Kernel 使用两级身份：同一 workflow session 的所有阶段复用一个宿主机目录和 Workspace 实例；每个补充分析或可视化 `task_id` 派生唯一 CodeMode session ID，并包含 work kind，避免并发任务共享 Python namespace。生成、正式执行和本任务内修复复用同一 task session；任务成功、降级、取消或异常退出时均在 `finally` 中调用异步 shutdown。关闭 Kernel 不关闭会话 Workspace。

`snapshot=False` 禁止跨进程恢复 pickle，也避免任务结束后残留可执行状态。`max_kernels` 与章节分析并发上限一致，单 cell 使用明确 timeout。Kernel 超时、死亡或输出无效转换为稳定的 Reporting 技术错误并进入现有执行修复路径；达到现有修复上限后按现有降级逻辑处理。

## 宿主机文件规则

- 所有模型输入文件只读，签发脚本和计划中的图表路径可写。
- 写入与哈希使用普通文件检查，不跟随最终路径上的符号链接。
- 路径规范化拒绝 `..`、NUL、控制字符和超出会话目录的解析结果。
- 正式脚本必须使用 `matplotlib.use("Agg")`，不打开 GUI。
- PNG 必须存在、非空、可被 Pillow 解码，并满足现有尺寸与文件大小限制。
- 会话目录和 Workspace 实例的创建、恢复与清理由 Reporting workflow session 生命周期触发；单个 task 结束只清理 Kernel 和任务临时文件，不删除同会话仍需复用的事实与产物。终态报告完成持久化后释放 Workspace 实例；目录按现有报告保留/清理语义处理。失败清理记录 Loguru warning，不覆盖原始任务结果。
- 完全宿主机模式不声称阻止恶意 Python 或 Shell 访问会话目录之外的文件。

## 错误与可观测性

新增稳定技术错误分类：宿主机根目录无效、路径映射失败、CodeMode bootstrap 失败、Kernel 执行失败、Kernel 超时和产物无效。错误详情只记录逻辑路径、任务 ID、异常类型和受限输出，不记录宿主机根绝对路径、环境变量值或完整数据内容。

关键日志使用 Loguru，并至少包含 `thread_id` 摘要、Reporting `session_id` 摘要、`task_id`、`section_code`、`code_mode_session_id`、阶段、耗时和错误码。正常路径记录 Workspace/CodeMode 初始化、脚本签发、正式执行、产物校验和 Kernel 关闭；失败路径记录进入修复或降级的原因。

语义问题继续通过 `report_visualization_semantic_warning` 等现有 warning 进入报告，不因切换执行环境升级为硬失败。

## 测试与验收

采用定点测试，不重复运行完整测试集。

单元测试覆盖：

- 设置只接受绝对、非符号链接的宿主机根目录；
- 相同会话身份稳定映射到同一目录，不同 tenant/user/thread/session 身份映射到不同目录，进程内实例可复用且模拟重启后目录可恢复；
- 逻辑路径稳定映射到正确会话目录并拒绝相对路径逃逸；
- Agent 只接收签发的相对 `workspacePath`，Workspace 回执可无损映射回 durable 逻辑路径；
- 整个 Workflow 的文件访问解析到同一个会话 Workspace，不同会话得到不同实例和 root；
- callable tools factory 关闭 Agno 默认 cache，并由注册表按 `workflow_session_id` 复用 Workspace；
- 原生 Workspace 与领域 Toolkit 的最终工具名称不重复；
- 补充分析和可视化 Agent 同时取得会话 Workspace 与 CodeMode，Workspace 无确认暂停，CodeMode 保持 `allow_shell=True`、`snapshot=False`；
- 同一会话的并发分析项和可视化章节使用不同 CodeMode task session，任务结束后 Kernel 被关闭；
- 固定事实足够的分析项不启动 Kernel，需要补证的分析项生成、执行、校验和修复语义不变；
- 最终脚本必须位于签发路径且身份变化可被发现；
- 正式执行失败进入现有修复路径，修复耗尽进入现有降级路径；
- PNG 缺失、空文件、损坏、符号链接或身份变化被拒绝；
- 语义业务问题只产生 warning；
- 运行链不调用 `create_sandbox_provider`、Daytona 或 local sandbox 客户端。

宿主机集成测试使用临时绝对目录，在两个 Reporting 会话中分别执行数据集导入、冻结事实、补充分析脚本、证据校验、Matplotlib 图表和报告产物流程。验证每个会话的全部文件来自其唯一 Workspace，两个会话不复用实例或目录；同一会话内分析与可视化使用不同 Kernel，并验证任务结束后无存活 Kernel。测试不使用网络、Daytona、local-sandboxd 或容器。

现有 `f5` 定向基线为 119 passed、1 failed。唯一失败是 `test_visualization_script_execution_repair_uses_off_then_4k` 仍期望首次预算为 `0`，而 `f5@89a5026` 已把实际策略改为 `1024`。该既有断言不在本功能中顺手修改；最终验证需分别报告该已知失败与本分支新增测试结果。

验收标准：

- Reporting 分析项、可视化、章节和报告组装的阶段与 durable 状态测试保持原语义；
- 真实补充分析与 Matplotlib 宿主机集成测试通过；
- 同一用户的不同 Reporting 会话不会复用 Workspace 目录或 CodeMode Kernel；
- 同一 Reporting 会话的整个 Workflow 只使用一个逻辑 Agno Workspace；进程内复用实例，重启后从同一目录恢复；
- 执行期间没有 Daytona/local sandbox API 调用；
- Shell 工具与 CodeMode `%%bash` 均保持可用；
- 任务完成或失败后没有遗留 CodeMode Kernel；
- 除已记录的 `f5` 基线失败外，相关定向测试全部通过。

## 部署方式

启动前设置唯一新增必需配置：

```bash
export REPORTING_HOST_WORKSPACE_ROOT=/absolute/path/to/reporting-workspaces
```

目录必须由运行 API 服务的系统用户独占写入。该模式直接执行模型生成的 Python 和 Shell，只适用于用户已经明确接受宿主机权限继承的受信环境。
