# Reporting 固定阶段执行与受控 Agent 恢复设计

## 背景

真实模型探针表明，Reporting 工具调用失败已经集中在两类行为：可视化 Agent 需要把完整
Python 脚本包装进大型 unified diff 工具参数，较弱模型容易产生损坏参数或越序执行；章节
Agent 在读取证据后可能重复读取或以普通文本结束，没有提交终态。把单场景超时从 90 秒
提高到 180 秒没有改善成功率，只延长了重复调用的失败确认时间。

`analysis_item` 已由 `AnalysisItemWorkflow` 固定编排，不需要再次改造。本设计只覆盖
`visualization_section` 和 `section`，目标是把无推理价值的工具顺序交给 Workflow，把模型
职责收敛为结构化内容生成，并仅在可恢复的内容问题上启用专用恢复 Agent。

## 目标

- 可视化采用“模型生成完整 Python 脚本，Workflow 固定写入、执行、审查、提交”的主路径。
- 章节证据由 Workflow 自动完整读取，模型只生成结构化正文或返工决定。
- 正常主路径不依赖模型自主选择工具，也不调用 `Agent.acontinue_run`。
- 内容失败最多触发一次独立恢复 Agent；身份、授权和基础设施失败继续失败关闭。
- 保留现有任务租约、幂等、durable replay、取消、超时和 workspace 隔离语义。
- 不改变公开工具名称、参数 schema、稳定错误码、Workflow ID、数据库结构或 Daytona 策略。

## 非目标

- 不修改 `analysis_item` 的现有固定子工作流。
- 不把图表收敛为纯模板选择或声明式 `ChartSpec`；模型仍可生成完整 Python 脚本。
- 不迁移 PostgreSQL 兼容表名或 `artifacts_v1.codingTaskKey`。
- 不废弃 `task_execution`。它继续作为 Reporting Workflow 的中立内部执行基础设施。
- 不增加任意 Shell、任意 Python、任意文件访问或新的外部产品接口。

## 总体架构

```text
ReportingTaskCoordinator
        |
        +-- analysis_item
        |     `-- AnalysisItemWorkflow（保持现状）
        |
        +-- visualization_section
        |     `-- VisualizationSectionWorkflow
        |           1. 准备冻结事实和签发约束
        |           2. Visualization Generator Agent -> VisualizationScriptDraft
        |           3. 固定写入 Python 脚本
        |           4. 固定执行签发命令
        |           5. 固定审查图表
        |           6. 固定提交终态
        |           7. 内容失败时调用一次 Recovery Agent
        |
        `-- section
              `-- SectionWorkflow
                    1. 自动读取授权 evidenceFiles
                    2. 自动恢复截断内容
                    3. Section Generator Agent -> SectionDecision
                    4. 固定提交正文或返工终态
                    5. 内容失败时调用一次 Recovery Agent
```

两个新增 Workflow 都属于 Reporting 领域层。它们只依赖中立的任务生命周期接口、
`ReportingToolRuntime`/workspace port、现有 Reporting 领域校验能力，以及显式传入的生成
Agent 和恢复 Agent。低层 `task_execution` 不导入 Reporting 模型或阶段实现。

## 可视化主路径

### 生成契约

Visualization Generator Agent 不挂载工具，只返回内部 Pydantic 模型：

```python
class VisualizationScriptDraft(BaseModel):
    script_path: str
    python_source: str
    charts: tuple[ChartDraft, ...]
    warnings: tuple[str, ...] = ()
```

`ChartDraft` 声明图表 ID、输出路径、标题、指标绑定和引用来源。`script_path`、图表输出路径、
指标绑定和引用必须属于服务端签发集合。模型不能自行扩展输出目录、执行命令、dataset、
citation 或 chart ID。

### 固定执行

1. Workflow 校验 `VisualizationScriptDraft` 的结构、大小和签发绑定。
2. 服务端把 `python_source` 转换成现有受控写入意图，并复用现有补丁解析、路径与 SHA 校验。
3. workspace port 写入脚本并返回不可变文件身份。
4. Workflow 只执行 acceptance contract 签发的 Python 命令，不接受模型提供命令。
5. Workflow 对声明的每个图表调用现有正式审查能力，冻结审查回执和文件 SHA。
6. 全部必要图表通过后，服务端构造现有 `submit_visualization_charts` 参数并提交一次终态。

模型不接触 `apply_analysis_patch`、`terminal`、`process`、`inspect_chart` 或
`submit_visualization_charts` 的调用顺序。工具规则仍由现有 Reporting runtime 执行，Workflow
不复制路径、命令、审查或验收规则。

## 章节主路径

### 证据准备

Workflow 只读取 `SectionWorkItem.evidence[].evidenceFiles`：

- 在读取前校验路径、大小、SHA 和当前 Task 授权。
- 自动跟随 `handle` 和 `nextOffset` 读取完整内容，并执行既有输出大小限制。
- 把证据规范化为有界的 `SectionEvidenceBundle`。
- `factFiles` 只保留在 durable work item 和身份 hash 中，不读取也不进入模型输入。
- 数值事实继续来自签发的 `factSummaries`，不能由 evidence 文本覆盖。

### 生成与提交

Section Generator Agent 不挂载工具，只返回判别联合：

```python
SectionDecision = RenderSectionDecision | AnalysisReworkDecision
```

`RenderSectionDecision` 包含 `section_code`、正文 blocks 和 claims；
`AnalysisReworkDecision` 包含 analysis IDs、原因和缺失证据。Workflow 完成现有 schema、事实、
citation、chart、claim 和 section code 校验后，根据联合类型调用一次 `render_report_section`
或 `request_analysis_rework`。模型不能以普通文本结束，也不能遗漏终态调用。

## 内容恢复

仅下列失败允许进入一次 Recovery Agent：

- 可视化结构化输出或 Python 源码校验失败。
- 脚本执行非零退出。
- 声明的图表文件缺失或身份不符。
- 图表正式审查未通过。
- 章节 blocks/claims 不符合既有内容契约。
- 正文决定与证据充分性冲突。
- 返工决定缺少明确 analysis ID 或缺失证据。

可视化恢复输入只包含签发约束、当前脚本及 SHA、脱敏 stderr、失败图表和结构化审查诊断。
恢复 Agent 只能返回修订后的 `VisualizationScriptDraft`，不能执行、读取任意文件或提交。

章节恢复输入复用已冻结的 `SectionEvidenceBundle` 和结构化校验错误。恢复 Agent 只能返回新的
`SectionDecision`，不重新读取文件。

每个内容阶段最多恢复一次，恢复使用独立最小上下文，不使用 `Agent.acontinue_run`。恢复结果
仍走完整固定执行与校验链路。第二次内容失败保留现有稳定错误码，并附加最后一次结构化诊断。

## 失败关闭边界

下列错误不得交给 Recovery Agent：

- 租约冲突、任务取消或 deadline 到期。
- capability、用户、公司、thread 或数据库绑定失败。
- 文件 SHA 在读取或执行期间变化。
- 未授权路径、命令或输出目录。
- workspace、数据库或模型服务不可用。

这些错误直接返回 `ReportingTaskCoordinator`，沿用现有失败关闭和 fresh attempt 语义。每个
成功副作用继续写入 durable state；重放只能返回已存结果，不再次写文件、执行脚本或提交终态。

## Agent 边界

- `analysis_item`：继续使用现有 Agno 固定子工作流及专用规划/摘要 Agent。
- `visualization_section`：主路径使用无工具 Generator Agent；一次内容恢复使用无执行权限的
  Recovery Agent。
- `section`：主路径使用无工具 Generator Agent；一次内容恢复使用无文件权限的 Recovery Agent。
- 三类阶段共享 Reporting 的任务生命周期与 workspace port，但不共享通用 Code Worker 抽象。

## 测试与验收

### 结构化契约测试

- 覆盖正常输出、缺字段、非法路径、重复 chart ID、错误 section code 和超限源码。
- 证明模型输出只能作为候选数据，不能绕过服务端验收。

### Workflow 定点测试

- 可视化验证“生成、写入、执行、审查、提交”的严格顺序。
- 章节验证自动读取、截断续读、正文提交和返工提交。
- 正常路径断言 Recovery Agent 和 `Agent.acontinue_run` 从未调用。
- 覆盖脚本修复上限、SHA 变化、超时、取消、重复提交和 durable replay。
- 覆盖所有允许恢复和必须失败关闭的分类。

### CLI mock 对齐

- 保持 `parse_report_input -> drive_workflow -> Reporting Workflow -> coordinator -> runtime`
  的生产单链路。
- mock workspace 只替换外部执行环境，不定义另一套工具回执。
- 正常路径隔离重复 100 次，结果和调用日志必须一致且无状态泄漏。
- 所有公开 Reporting 工具至少在固定主路径、契约测试或恢复路径中执行一次。

### 真实模型探针

- `qwen3.6-flash` 和 `deepseek-v4-flash-0731` 各执行现有 10 个复杂场景。
- 单场景使用 90 秒上限；180 秒实验已证明不能改善协议失败。
- 第一阶段门槛：每个模型至少 `9/10` 完成、`8/10` 严格合规、
  `not_visible_calls=0`。
- 固定 Workflow 稳定后，目标提升为两个模型均 `10/10` 完成；严格合规保持 `>=8/10`，
  避免把合理内容差异误判为系统失败。

### 回归检查

- Reporting 定点与全部非集成回归。
- `task_execution` 非集成回归。
- 改动文件 Ruff format、Ruff lint 和必要 Mypy。
- `git diff --check`。
- 全仓检索运行时 `Code Worker`、`Coding*` 旧抽象，只允许明确的数据库和已发布协议兼容标识。

## 兼容性与迁移顺序

1. 先增加两个内部结构化输出模型和固定 Workflow，不切换生产装配。
2. 使用现有 mock workspace 验证主路径与恢复路径。
3. 将 `visualization_section` 装配切换到固定 Workflow，保持外部 Task 和验收契约不变。
4. 将 `section` 装配切换到固定 Workflow。
5. 清理仅被旧自主工具循环使用的内部装配代码；公开工具和稳定错误码继续保留。
6. 完成真实模型门槛后再删除旧 Agent 主路径，禁止长期并存两套权威实现。

迁移期间每个阶段只有一个生产入口，旧实现仅在测试对照期存在，不通过运行时开关长期双写或
双跑。数据库、artifact v1、Workflow ID 和 Daytona 隔离策略不参与此次迁移。
