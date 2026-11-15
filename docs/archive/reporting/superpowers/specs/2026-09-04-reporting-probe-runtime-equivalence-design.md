# Reporting 真实模型探针运行时等价性设计

## 目标

让 `scripts/probe_reporting_tools_agent.py` 对真实模型发起的每一个场景调用，使用与
Reporting 生产任务一致的 `RunContext`、依赖、运行身份和工具投影规则。探针结果应只反映
模型对当前受限工具面的调用质量，不把探针缺少运行时上下文造成的错误暴露计入生产问题。

本设计是提高 Reporting 工具调用成功率和稳定输出的测量前置工作。完成后，才能依据真实的
失败码、完成率和严格协议合规率，决定是否需要修改阶段指令或恢复策略。

## 背景与问题

生产任务由 `ReportTaskRunner` 创建 Agno `RunContext`，在完整执行范围内以
`bind_reporting_run_context()` 绑定它，并把同一对象传给子工作流。`ReportingPhaseOpenAIChat`
据此解析 phase、task kind、模型路由和可视化生命周期状态，投影本轮允许发送给模型的工具。

当前探针直接执行 `Agent(...).arun(prompt)`。虽然它使用 `ReportingPhaseOpenAIChat` 和当前
Toolkit schema，但没有生产形状的 `RunContext`，所以模型投影无法辨别 phase、task kind 或
可视化生命周期。探针因而向模型暴露静态能力矩阵中的完整工具集，可能把本应隐藏的工具调用
误归因于模型或生产指令。

`tools_for_task()` 的静态集合仍是服务器能力集合，不能为修复探针而收窄。动态可见集合必须
由受信的运行时上下文和现有 `ReportingPhaseOpenAIChat` 逻辑产生。

## 范围

- 为每个探针场景构造生产形状的 `RunContext`，包含稳定但隔离的 run、session 和 user identity，
  以及以 `REPORTING_TASK_DEPENDENCY` 为根的 phase、task kind、模型档位和本场景所需预算依赖。
- 在整个 `Agent.arun()` 生命周期外层使用 `bind_reporting_run_context()`，并像生产任务一样把
  同一组 run、session、user、dependencies 与 `RunContext` 显式传给 Agno 调用，确保模型投影、
  工具批次和 probe 记录读取的是同一状态。
- 在每次模型请求时记录实际投影给模型的工具名；探针的 `unexpected_tools` 和协议合规判定以
  本场景的动态可见集合为准，而不是只以静态 `scenario.tool_names` 为准。
- 将十个场景保持为十个，并用一个重复的可视化前台场景替换为可视化 recovery 场景，以覆盖
  已签发脚本后的读取与修复路径。
- 为初始可视化、后台 session 已建立、recovery 三种生命周期状态增加定点契约测试，确保
  每一状态的模型工具面与生产过滤结果一致。
- 完成等价性实现后，分别使用 fast 与 standard 配置的真实模型运行十个场景；探针日志和
  结果仅写入系统临时目录。

## 非目标

- 不修改 `ReportingPhaseOpenAIChat`、`ReportingToolkit`、`tools_for_task()`、生产任务执行器
  或 `task_execution` 的业务行为。
- 不放宽 mock workspace、路径、文件、命令、哈希、脚本签发、超时或身份校验规则。
- 不修改工具名、参数 schema、错误码、成功/失败回执、Workflow ID、数据库表或持久化协议。
- 本阶段不直接重写模型指令、工具描述或恢复策略；这些改动只在重新测量后的失败分布支持时
  单独设计和实现。

## 运行时等价性

### 上下文构造

每个 `ProbeScenario` 派生唯一的 probe run id、session id 和固定测试 user id，不读取共享
会话或真实用户状态。其 `RunContext.dependencies` 采用生产同一层级：

`{"AgentOS 任务执行": {"reportingPhase": ..., "reportingTaskKind": ..., ...}}`

其中 phase 和 task kind 直接来自场景；模型档位与 thinking 配置来自探针参数；可视化场景带入
当前生产过滤所需的注册、脚本写入、失败待恢复、预算与后台 session 状态。分析项场景带入事实
查询预算与 recovery 状态。所有状态都只存在当前 probe 的 `RunContext.session_state` 中。

### 调用边界

探针在创建 Agent 后，以如下语义执行一次场景：

1. 创建 `RunContext` 和 mock workspace/runtime。
2. 进入 `bind_reporting_run_context(run_context)`。
3. 调用 `agent.arun()`，传入 prompt、`stream=True`、`stream_events=True`、run id、session id、
   user id、dependencies 和 `run_context`，并消费完整结果。
4. 退出绑定范围后收集 recorder、workspace 与动态工具投影日志。

绑定范围必须覆盖异步请求和工具调用的完整消费过程。不能只在 Agent 构造时绑定，因为 Agno 的
模型请求和工具批次可能在异步迭代期间才发生。

### 动态工具面

可视化初始轮只能看到探索与生成阶段当前允许的工具；`read_file`、`read_tool_output` 以及没有
后台 session 时的 `process` 不得投影。脚本已签发且进入 recovery 后，模型才可以看到恢复所需
的读取工具。后台 session 存在时，`process` 按生产规则进入工具面。

记录器保留静态 `scenario.tool_names` 作为该场景应完成的工作契约，但以下判定以实际投影为准：

- 模型调用未投影工具：协议失败，记录 `report_phase_tool_forbidden` 或对应既有拒绝码。
- 模型调用已投影但不属于场景必需工具：记录为额外调用，不能误标为“阶段不可见”。
- 场景期望的工具在该生命周期下不可能投影：这是探针设计缺陷，定点测试必须失败，不能通过
  放宽工具面掩盖。

每轮结果包含 `visible_tools` 或等价的逐请求投影日志，供真实模型结果按动态权限面复核。

## Mock 与生命周期

探针继续从当前 `ReportingToolkit` 复制工具 schema，并用 `ProbeRecorder` 调度到
`MockReportingToolRuntime`，以隔离 Daytona、PostgreSQL 和真实用户工作区。它保留现有文件根、
路径穿越、签发脚本、受限 terminal、输出句柄、终态回执和 workspace 调用记录的拒绝语义。

探针需要补足的是生产 Toolkit 依赖的生命周期状态，而不是模拟更宽权限。成功的 patch、后台
process、截断输出和终态回执必须同步到同一 `RunContext.session_state` 中，使下一批模型工具
投影能观察到与生产一致的变化。

## 测试与验证

定点单元测试使用 mock 模型或直接调用现有投影入口，不访问网络：

- 初始 visualization context 的模型可见工具不含 `read_file`、`read_tool_output` 和无 session
  的 `process`。
- 已建立后台 session 的 visualization context 按生产规则出现 `process`，其他未满足的
  生命周期工具仍保持隐藏。
- recovery context 在脚本签发和失败待恢复后，出现恢复所需读取工具，且不会出现无关能力。
- `Agent.arun()` 收到与绑定的上下文为同一对象；探针记录的动态工具面等于
  `ReportingPhaseOpenAIChat` 的实际投影结果。
- 十个场景仍覆盖 analysis item、visualization section 和普通 section 的所有当前工具 schema；
  recovery 场景覆盖先失败、再读取已签发脚本、修复并提交的顺序。

实现完成后，使用以下模型配置分别运行一轮十场景探针：

- `AGENT_MODEL_FAST=qwen3.6-flash`
- `AGENT_MODEL_STANDARD=deepseek-v4-flash-0731`

每轮报告完成率、严格协议合规率、动态工具面违规、既有拒绝码分布、每场景耗时和逐调用日志。
真实模型结果是外部依赖验证，不替代无网络的定点契约测试。

## 不变量与验收标准

- 探针发给模型的工具集合与相同 `RunContext` 下生产 `ReportingPhaseOpenAIChat` 的动态过滤结果
  完全一致。
- 任何未通过生产生命周期前置条件的工具，在探针中同样不可见或被既有错误码拒绝。
- mock workspace 从不执行任意 shell、读取未签发路径或写入仓库；所有探针产物写入 `/tmp`。
- 十个场景全部可被运行，且每个工具调用的可见性、拒绝和终态顺序可以从 JSON 记录复核。
- 该变更的定点测试、相关 Reporting 非集成回归、Ruff、必要 Mypy 与 `git diff --check` 通过后，
  才使用新的结果进入指令和恢复策略优化阶段。
