# Reporting 思考预算分层设计

## 背景

当前 Reporting 将模型能力档位、Durable 任务类型和单次模型调用的 thinking 配置部分耦合。
`analysis_item`、`visualization_section` 等外层任务内部包含多种性质不同的调用，但它们容易继承同一套
高思考配置。例如可视化章节同时包含图表规划、Python 源码生成、脚本执行和视觉修复，其中源码生成
本质上是把已冻结计划转换为确定性脚本，不应与开放式规划共享高预算。

现有日志显示，一个章节的分析项约耗时 8.5 秒，图表代码模型生成约耗时 125.4 秒，Python 语法校验
和 patch 应用不足 0.5 秒，章节总耗时约 177 秒。主要瓶颈是模型生成源码时的 reasoning，而不是本地
校验、patch 或持久化。

## 目标

- 数据理解和 SQL 规划首次调用固定使用 2K thinking 预算。
- 模型能力档位与 thinking 预算解耦，允许 strong 模型执行低预算或关闭 thinking 的任务。
- 按单次模型操作、复杂度和失败类型决定预算，不按外层 Durable 任务统一预算。
- 确定性 Python 脚本首次生成关闭 thinking，失败修复按原因有界升级。
- 正常路径不使用 6K 或 8K；同一调用链最多升级一次。
- 保持冻结事实、引用、图表、Durable 状态和验收协议不变。
- 业务语义校验继续只产生软告警，不触发预算升级或硬失败。

## 非目标

- 不更换现有模型，不改变 `fast`、`standard`、`strong` 的模型选择结果。
- 不调整分析和章节并发度。
- 不裁剪冻结事实来换取速度。
- 不引入基于线上历史数据自动调参的动态控制器。
- 不新增按阶段配置的环境变量。
- 不改变脚本编译、Sandbox 执行、视觉审查或产物提交门禁。

## 设计原则

一次模型调用由两个互相独立的决策组成：模型路由决定使用哪个模型，thinking 策略决定本次请求是否
思考以及最多使用多少 token。模型强弱表示能力，不隐含推理预算；任务复杂度只影响需要推理的开放式
任务，不能使确定性转换自动开启 thinking。

预算升级必须由机器可识别的失败分类触发。网络、限流和超时等瞬时错误保持原预算重试，避免形成
“响应越慢，下一次思考越多”的正反馈。业务语义差异继续进入软告警，不被伪装成需要更多推理的失败。

## 策略模型

### 模型能力选择

现有 `ModelRouter` 继续根据任务类型、复杂度和已分类失败选择：

- `fast`
- `standard`
- `strong`

路由结果继续包含 `tier` 和 `model_id`，但不再通过模型档位强制绑定 `off`、`high` 或 `max`。

### Thinking 选择

新增单次调用级策略输入 `ThinkingRequest`：

```text
operation
complexity
attempt
failure_kind
configured_budget_cap
thinking_enabled
```

其中 `operation` 描述真实模型操作，而不是复用外层 `task_kind`：

```text
request_normalization
domain_resolution
data_understanding
measure_semantics
outline_planning
sql_planning
analysis_planning
analysis_evidence
analysis_summary
analysis_script
visualization_plan
visualization_script
section_generation
```

策略输出不可变的 `ThinkingDecision`：

```text
enabled
reasoning_effort
thinking_budget
reason
```

最终预算为策略预算与环境硬上限的较小值。策略函数是纯函数，不读取或修改 Agent、模型和
`RunContext`。

## 预算档位

| 档位 | Thinking | Effort | Token |
| --- | --- | --- | ---: |
| Off | 关闭 | 无 | 0 |
| Light | 开启 | high | 1K |
| Standard | 开启 | high | 2K |
| Deep | 开启 | high | 4K |
| Recovery | 开启 | max | 6K |

1K、2K 和 4K 使用 `high`；只有证据恢复的 6K 使用 `max`。8K 不再是任何常规或自动恢复路径的策略
预算，只允许作为向后兼容的环境硬上限存在。关闭 thinking 时必须同时清除 `enable_thinking`、
`reasoning_effort`、`thinking_budget` 和 provider 特有的 reasoning 字段，不能继承共享模型状态。

## 阶段预算矩阵

### 规划阶段

| 操作 | 首次预算 | 合法升级 |
| --- | ---: | ---: |
| 请求归一化 | Off | Schema 失败时 1K |
| 领域识别 | Off | 不升级；无法唯一判断时请求澄清 |
| 数据理解 | 2K | Schema 或能力映射失败时 4K |
| 指标语义 | 2K | Schema 或能力映射失败时 4K |
| 提纲规划 | Off | Schema 失败时 2K |
| SQL 规划 | 2K | Schema 或 SQL 校验失败时 4K |
| 分析计划 | 2K | Schema 失败时 4K |

数据理解和 SQL 规划首次预算固定为 2K，不再随外层模型档位自动升到 4K 或 8K。

### 分析阶段

| 操作 | 简单 | 标准 | 复杂 | 合法升级 |
| --- | ---: | ---: | ---: | ---: |
| 证据规划 | 1K | 2K | 4K | 事实或证据缺失时 6K |
| 分析总结 | 1K | 2K | 4K | Schema 失败时最高 4K |
| 分析脚本生成 | Off | Off | Off | 编译或执行失败时 2K |

分析复杂度继续只根据已校验计划中的数据集数、指标数、比较维度、组织粒度和动作数量计算，不从自然
语言猜测。只有真实的 `evidence_incomplete` 或 `fact_incomplete` 可将证据规划升级到 6K。

### 可视化阶段

| 操作 | 简单 | 标准 | 复杂 | 合法升级 |
| --- | ---: | ---: | ---: | ---: |
| 可视化计划 | 1K | 2K | 4K | Schema 失败时最高 4K |
| 图表脚本生成 | Off | Off | Off | 编译或执行失败时 2K |
| 图表视觉修复 | - | - | - | 视觉审查失败时 4K |

`VisualizationPlanDraft` 已冻结图表数量、指标、期间、输出路径和引用关系，因此首次源码生成只做确定性
转换，不启用独立 reasoning。脚本仍需经过源码形状校验、Python 编译、Sandbox 执行、图表文件校验
和可选视觉审查。

### 章节阶段

| 操作 | 首次预算 | 合法升级 |
| --- | ---: | ---: |
| 章节成稿 | Off | 结构化输出失败时 2K |
| 章节重写 | 2K | 不再升级 |
| 发布和格式转换 | 无模型调用 | 无 |

## 失败分类与升级

允许升级的失败类型：

- `schema_failure`
- `capability_mapping_failure`
- `evidence_incomplete`
- `fact_incomplete`
- `sql_validation_failure`
- `python_compile_failure`
- `python_execution_failure`
- `visual_review_failure`

禁止升级的情况：

- 网络错误、限流和模型服务超时；
- Workspace 暂时不可用、Task lease 冲突和用户取消；
- 业务语义软告警；
- 当前调用链已经升级过一次；
- 无法由更多推理修复的文件身份、权限或契约错误。

瞬时错误可以按现有重试策略使用相同预算重试，但不得提高预算。一次失败只进入一条恢复路径，禁止
从 Off 自动连续增长到 2K、4K 和 6K。

代码生成恢复链固定为：

```text
首次生成：Off
  -> Python 编译或执行失败：2K 修复
  -> 视觉审查失败：4K 视觉修复
  -> 再次失败：结束当前 attempt，不继续提高预算
```

## 请求执行与并发隔离

每次真实模型调用按以下顺序执行：

1. 模型路由器选择 `tier` 和 `model_id`。
2. Thinking 策略按 `operation`、复杂度、attempt 和失败类型生成 `ThinkingDecision`。
3. 两个结果绑定到当前请求的 `RunContext`。
4. 从共享模型创建请求级副本。
5. 清除副本中所有遗留 thinking 字段。
6. 应用本次 `ThinkingDecision` 后调用模型。
7. 调用结束后丢弃请求级副本。

禁止临时修改共享 Agent 或共享模型。并发运行的分析证据规划、图表脚本生成和章节成稿必须各自读取
请求级决策，不能互相继承预算。

调用侧使用统一的上下文管理器或等价 helper 绑定决策：

```python
async with bind_reporting_thinking(
    run_context,
    operation="visualization_script",
    complexity="standard",
    failure_kind=None,
):
    await code_runner.generate(...)
```

该 helper 只负责绑定和恢复请求级字段，取代当前散落的 `try/finally` 字典修改；策略计算仍由独立纯
函数完成。

## 配置兼容

保留现有配置：

```text
AGENT_REPORT_CODING_ENABLE_THINKING
AGENT_REPORT_CODING_THINKING_BUDGET
AGENT_REPORT_ENABLE_THINKING
AGENT_REPORT_PLANNER_THINKING_BUDGET
```

配置语义调整为：

- 对应的 `ENABLE_THINKING=false` 时，受其控制的所有阶段统一关闭 thinking；
- `*_THINKING_BUDGET` 是硬上限，不再是每次调用的默认预算；
- 实际预算为 `min(policy_budget, configured_budget_cap)`；
- 硬上限低于策略预算时直接取硬上限，不通过其他配置补足；
- 暂不增加按 operation 配置的环境变量，避免形成不可审计的配置矩阵。

## 可观测性

模型选择和 thinking 选择分别记录，应用代码日志统一使用 loguru。

现有模型路由日志保持不变：

```text
report_model_selected task_kind=visualization_section tier=standard
model_id=deepseek-v4-flash-0731
```

新增不含业务内容的 thinking 决策日志：

```text
report_thinking_selected operation=visualization_script complexity=standard
enabled=false effort=off budget=0 attempt=0 reason=initial_deterministic_generation
```

恢复调用示例：

```text
report_thinking_selected operation=visualization_script complexity=standard
enabled=true effort=high budget=2048 attempt=1 reason=python_execution_failure
```

每次请求还应关联记录模型 ID、reasoning 耗时、输出模型耗时、输入 token、reasoning token、输出
token、是否升级和最终状态。日志不得包含完整 prompt、源码、冻结事实或凭据。

## 组件边界与迁移范围

- `model_routing/models.py`：模型档位不再校验固定的 reasoning effort；模型能力路由保持纯粹。
- `model_routing/policy.py`：只保留任务到模型能力档位的映射。
- `reporting/model_policy.py`：定义 operation、请求、决策、预算表和纯策略函数。
- `reporting/workflow/runtime/base.py`：规划阶段按具体 operation 绑定请求级预算。
- `reporting/workflow/runtime/analysis.py`：分离证据规划、分析总结、分析脚本和可视化调用的预算。
- `reporting/workflow/runtime/sections.py`：绑定章节首次生成与重写预算。
- `reporting/workflow/runtime/code_generation.py`：首次生成关闭 thinking，修复按已分类失败开启预算。
- `reporting/agent.py`：请求模型只消费已选定的 `ThinkingDecision`，不从模型档位反推预算。
- `model_routing/observability.py` 或相邻 Reporting 可观测模块：记录 thinking 决策事件。

现有“修复阶段由服务端直接读取受信脚本”的工作区改动保持独立。它减少一次修复模型调用，但不能
替代本设计的预算分层。

## 测试策略

遵循项目要求，只运行与本改造相关的定点测试，不重复完整测试套件。

### 纯策略测试

使用表驱动覆盖 `operation × complexity × failure_kind × attempt`，至少验证：

- 数据理解首次严格为 2K；
- SQL 规划首次严格为 2K；
- 分析和图表脚本首次为 Off；
- 正常路径不产生 6K 或 8K；
- 瞬时错误保持原预算；
- 业务语义软告警不升级；
- 同一调用链最多升级一次；
- 环境配置只限制上限。

### 请求模型测试

- 请求级副本正确应用 `ThinkingDecision`，共享模型保持不变；
- Off 清除所有遗留 thinking 和 reasoning 字段；
- Qwen 的内部 `max` 在传输层正确转换为 `xhigh`；
- DeepSeek 使用预期的 `high` 或 `max`；
- 关闭全局 thinking 时任务契约不能将其重新开启。

### 并发与 Workflow 测试

- 并行运行 4K 分析证据规划和 Off 图表脚本生成，两者互不污染；
- Python 编译或执行失败后脚本修复使用 2K；
- 视觉失败后图表修复使用 4K；
- 网络和超时错误保持原预算；
- 第二次失败后终止，不继续升级；
- Durable 已完成任务恢复时不重新调用模型。

## 验收标准

功能验收：

- 报表内容、引用、图表、文件身份和 Durable 状态协议保持兼容；
- 数据理解和 SQL 规划首次模型调用严格使用 2K；
- 所有 Python 脚本首次生成均关闭 thinking；
- 正常路径没有 6K 或 8K 请求；
- 只有事实或证据恢复允许使用 6K；
- 业务语义问题仍只形成软告警。

性能与可观测验收：

- 示例中的 `model_generate_source` 不再包含独立 reasoning 阶段；
- 约 7.5 KiB 的成功图表脚本只发生一次非 thinking 输出调用；
- 日志可以按 operation 独立统计 reasoning 与输出耗时和 token；
- 同等输入下章节 P50 延迟应明显低于当前基线；CI 不设置依赖外部模型波动的耗时阈值。

风险控制：

- Off 模式产生的语法错误由源码形状校验和 Python 编译捕获；
- 运行错误由 Sandbox 执行回执捕获；
- 图表质量由文件门禁和视觉审查捕获；
- 修复失败不会无限重试或继续增加预算。
