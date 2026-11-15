# Reporting CLI Mock 链路对齐设计

## 目标

让 Reporting mock 测试覆盖真实 CLI 从请求解析到阶段工具执行的生产主链路，使测试结论能够区分：

- CLI、Workflow、任务协调器或工具生命周期的实现缺陷；
- 模型没有按当前可见工具和回执完成任务的行为偏差。

本轮不追求完整报表交付 E2E，不连接 PostgreSQL、Daytona 或真实文件系统。

## 当前问题

现有 `scripts/probe_reporting_tools_agent.py` 已使用生产工具 schema、动态工具投影和生产形状
`RunContext`，但仍直接创建阶段 Agent，并手工构造阶段 JSON。它没有经过 CLI 请求解析、顶层
Workflow、Controller、阶段任务协调器和生产阶段投影，因此只能测模型选工具能力，不能证明真实
CLI 链路等价。

实测还暴露出一项生产契约矛盾：Section 指令要求模型按 `factFiles` 读取事实文件，而
`ReportingSectionsToolsMixin._section_evidence_read_rejection()` 只授权当前 WorkItem 的
`evidenceFiles`。模型按指令读取 `factFiles` 时必然被生产工具拒绝。

## 方案

采用双层测试，不把两类目标混在同一个 test agent 中。

### 1. CLI 闭环契约测试

测试从 `parse_report_input()` 和 `drive_workflow()` 进入，保留以下生产实现：

- CLI 请求解析和租户 scope 构造；
- 顶层 Workflow/Controller 的调用协议；
- `ReportTaskRunner` 的任务上下文、路由、生命周期和 executor 调用边界；
- `AnalysisItemWorkflow` 以及 Section/Visualization Agent executor 的生产选择；
- Reporting Toolkit 的真实 schema、hooks、阶段权限和动态工具投影。

只替换明确的外部端口：

- PostgreSQL repository 使用每个测试独立的显式 fake repository；
- Daytona 使用 `MockReportingToolRuntime` 和内存 workspace；
- 模型响应使用确定性 fake model/executor；
- PDF、DOCX 和发布步骤不进入本轮测试。

测试不得使用 SQLite，不得复制生产状态机，也不得在 fake 中重新定义工具权限。

### 2. 真实模型工具探针

保留现有十场景探针，用于测量模型工具选择、调用顺序、参数质量和终态提交成功率。探针继续记录：

- 每次模型请求实际可见的工具集合；
- 每次工具调用时的可见工具集合；
- 不可见工具调用、拒绝码、缺失工具和终态结果；
- 两种模型各十个场景的完成率与严格协议合规率。

探针结果不得用于证明租约、持久化、Workflow continuation 或完整 CLI 交付正确。

## 契约修正

Section 生产指令改为：

- 数值事实优先使用 WorkItem 已内联的 `factSummaries`；
- 只有需要证据正文时才读取 `evidenceFiles`；
- `factFiles` 是服务端事实身份和追溯元数据，不属于 Section 文件读取授权；
- 不得读取 Dataset 输入、其他章节文件或未列入 `evidenceFiles` 的路径。

工具授权实现保持不变，避免通过扩大读取范围掩盖指令矛盾。

## 数据流

1. 测试输入自然语言或 `ReportRequestEnvelope` JSON。
2. `parse_report_input()` 生成生产请求结构。
3. `drive_workflow()` 构造 database、company、user、run 和 thread scope。
4. 生产 Controller/Workflow 生成阶段任务和 acceptance contract。
5. `ReportTaskRunner` 构造生产 `RunContext` 并选择显式 executor。
6. executor 通过生产 Toolkit 调用 mock workspace。
7. 测试同时断言 CLI 结果、任务状态、工具调用日志和 workspace 调用日志。

每个测试创建独立 runtime、repository、workspace 和 `RunContext`，禁止跨测试共享状态。

## 失败处理

- fake repository 必须保留租约冲突、状态版本冲突和终态校验，不得无条件返回成功。
- mock workspace 继续校验路径、输出根、覆盖 SHA、签发命令和 session 所属关系。
- 非法工具调用必须经过生产 admission/hook 返回稳定错误码。
- 模型或 executor 普通文本结束但没有终态工具时，沿用生产 continuation/失败语义。
- 测试失败时保存调用日志到 pytest 输出；不得把运行产物写入仓库。

## 测试范围

新增定点测试覆盖：

- 自然语言和 envelope JSON 经 CLI 解析后进入同一 Workflow scope；
- `analysis_item` 由 `AnalysisItemWorkflow` executor 执行，不调用 Worker Agent；
- `visualization_section` 和 `section` 分别使用生产专属 Agent executor；
- 三类任务收到同形生产 `RunContext` 和中立 `task_execution` 依赖；
- Section 只读 `evidenceFiles`，使用内联 `factSummaries`，不会尝试读取 `factFiles`；
- 后台 terminal 只有在返回 session 后才开放对应 `process`；
- recovery 只能读取和覆盖签发脚本，文件 SHA 变化时失败关闭；
- 十次 mock 重复运行的结果和调用日志一致且无状态泄漏。

## 验收条件

- CLI 闭环测试不直接构造阶段 Agent，也不手写替代生产权限的工具表。
- 测试至少经过 `parse_report_input()`、`drive_workflow()`、Controller/Workflow、
  `ReportTaskRunner` 和生产 Toolkit 边界。
- Section 指令与工具授权一致，相关失败测试先红后绿。
- Reporting 定点及非集成回归、task_execution 非集成回归、Ruff、必要 Mypy 和
  `git diff --check` 通过。
- 不修改公开工具 schema、错误码、Workflow ID、数据库结构或 Daytona 隔离策略。

## 非目标

- 不运行完整需求澄清、提纲审批、全部章节和 PDF/DOCX 交付链路。
- 不新增 SQLite 路径，不以 mock 替代 PostgreSQL 集成测试的事务结论。
- 不在本轮修改模型路由、temperature、thinking 或重试次数。
- 不废弃 `task_execution`；它继续作为 Reporting 内部任务生命周期基础设施。
