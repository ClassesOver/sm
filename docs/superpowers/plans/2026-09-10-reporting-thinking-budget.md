# Reporting Thinking Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Reporting 的模型能力路由与单次调用 thinking 预算解耦，使数据理解和 SQL 规划首次固定使用 2K、确定性脚本首次关闭 thinking，并仅在明确可恢复失败时有界升级。

**Architecture:** `model_routing` 只选择模型能力，`reporting.model_policy` 以纯函数选择不可变 `ThinkingDecision`。每次模型调用通过 `ContextVar` 绑定决策，结构化执行器负责 Schema 纠错轮次的预算切换，各 Workflow 显式提供 operation、复杂度和失败分类；共享 Agent、模型和 `RunContext.dependencies` 均不被临时改写。

**Tech Stack:** Python 3.12、Agno、Pydantic、ContextVar、Loguru、pytest/AnyIO

**Spec:** `docs/superpowers/specs/2026-09-10-reporting-thinking-budget-design.md`

## Global Constraints

- 数据理解和 SQL 规划首次模型调用严格使用 2048 token thinking 预算。
- 正常路径不得产生 6144 或 8192 token thinking 请求。
- 分析脚本和图表脚本首次生成必须关闭 thinking。
- 只有事实或证据恢复允许使用 6144 token；业务语义校验只产生软告警。
- 网络、限流、超时、Workspace 暂不可用、lease 冲突和取消不得提高 thinking 预算。
- `AGENT_REPORT_*_THINKING_BUDGET` 只作为硬上限；不得新增按 operation 配置的环境变量。
- 不改变模型 ID、并发度、冻结事实、引用、图表、脚本门禁或 Durable 状态协议。
- 应用日志使用 Loguru，且不得记录完整 prompt、源码、冻结事实或凭据。
- 只运行计划列出的定点测试，不运行或重复完整测试套件。
- 执行前保留并理解工作区已有改动；不得覆盖与本计划重叠的用户修改。

---

### Task 1: Thinking 策略领域模型与模型路由解耦

**Files:**
- Modify: `smart_reporting/model_routing/models.py`
- Modify: `smart_reporting/model_routing/policy.py`
- Modify: `smart_reporting/model_routing/observability.py`
- Modify: `smart_reporting/model_routing/__init__.py`
- Modify: `smart_reporting/reporting/model_policy.py`
- Create: `smart_reporting/reporting/tests/test_reporting_thinking_policy.py`
- Test: `smart_reporting/tests/test_model_routing.py`

**Interfaces:**
- Consumes: 现有 `TaskComplexity = Literal["simple", "standard", "complex"]`。
- Produces: `ThinkingOperation`、`ThinkingFailureKind`、`ThinkingRequest`、`ThinkingDecision`、`select_reporting_thinking(request)` 和 `log_thinking_selection(fields)`。

- [ ] **Step 1: 写失败的预算矩阵测试**

在新测试文件中加入表驱动用例，明确固定预算、复杂度预算、升级边界和环境上限：

```python
@pytest.mark.parametrize(
    ("operation", "complexity", "budget"),
    [
        ("data_understanding", "simple", 2048),
        ("data_understanding", "complex", 2048),
        ("measure_semantics", "standard", 2048),
        ("sql_planning", "simple", 2048),
        ("sql_planning", "complex", 2048),
        ("analysis_evidence", "simple", 1024),
        ("analysis_evidence", "standard", 2048),
        ("analysis_evidence", "complex", 4096),
        ("analysis_script", "complex", 0),
        ("visualization_script", "complex", 0),
        ("section_generation", "complex", 0),
    ],
)
def test_initial_thinking_budget_matrix(operation, complexity, budget):
    decision = select_reporting_thinking(
        ThinkingRequest(operation=operation, complexity=complexity)
    )
    assert decision.thinking_budget == budget
    assert decision.enabled is (budget > 0)
```

补充独立断言：`evidence_incomplete` 将 `analysis_evidence` 升到 6144/`max`；SQL 校验失败升到 4096；脚本执行失败升到 2048；视觉失败升到 4096；`transient`、`semantic_warning` 和 `attempt=2` 不升级；`configured_budget_cap=1536` 将 2K/4K/6K 截到 1536；`thinking_enabled=False` 返回 Off。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_thinking_policy.py smart_reporting/tests/test_model_routing.py`

Expected: FAIL，原因是新的策略类型尚不存在，且 `ModelProfile` 仍要求 `reasoning_effort`。

- [ ] **Step 3: 实现不可变策略类型和纯选择函数**

在 `reporting/model_policy.py` 增加精确类型：

```python
ThinkingOperation = Literal[
    "request_normalization",
    "domain_resolution",
    "data_understanding",
    "measure_semantics",
    "outline_planning",
    "sql_planning",
    "analysis_planning",
    "analysis_evidence",
    "analysis_summary",
    "analysis_script",
    "visualization_plan",
    "visualization_script",
    "section_generation",
]
ThinkingFailureKind = Literal[
    "schema_failure",
    "capability_mapping_failure",
    "evidence_incomplete",
    "fact_incomplete",
    "sql_validation_failure",
    "python_compile_failure",
    "python_execution_failure",
    "visual_review_failure",
    "transient",
    "semantic_warning",
]

@dataclass(frozen=True, slots=True)
class ThinkingRequest:
    operation: ThinkingOperation
    complexity: TaskComplexity = "standard"
    attempt: int = 0
    failure_kind: ThinkingFailureKind | None = None
    configured_budget_cap: int = 8192
    thinking_enabled: bool = True

@dataclass(frozen=True, slots=True)
class ThinkingDecision:
    operation: ThinkingOperation
    complexity: TaskComplexity
    enabled: bool
    reasoning_effort: ReportingReasoningEffort | None
    thinking_budget: int
    attempt: int
    reason: str
```

实现 `_INITIAL_BUDGETS` 和 `_RECOVERY_BUDGETS` 常量表。`select_reporting_thinking()` 必须验证 cap 和 attempt，先处理全局关闭，再选择初始预算；仅 `attempt == 1` 且 failure 在 operation 的白名单中时选择恢复预算。预算为零返回 Off，非零预算取 `min(policy_budget, configured_budget_cap)`；只有 `analysis_evidence + evidence_incomplete/fact_incomplete` 的 6144 使用 `max`，其余启用档均使用 `high`。

- [ ] **Step 4: 删除模型档位到 reasoning 的强绑定**

将 `ModelProfile` 收窄为：

```python
@dataclass(frozen=True, slots=True)
class ModelProfile:
    tier: ModelTier
    model_id: str
```

同步修改 `DEFAULT_MODEL_PROFILES`、`build_model_profiles()` 和路由测试。`ModelSelection`、`ModelRouter`、三档模型 ID 及 task policy 均保持不变。

- [ ] **Step 5: 增加 thinking 选择日志边界**

在 `model_routing/observability.py` 添加 `log_thinking_selection()`，固定输出：

```text
report_thinking_selected operation={} complexity={} enabled={} effort={} budget={} attempt={} reason={} policy_version=v1
```

为 `ThinkingDecision.event_fields()` 添加不含业务数据的稳定字段，并在测试中用 Loguru sink 断言事件不包含 prompt、facts 或 source。

- [ ] **Step 6: 运行定点测试并提交**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_thinking_policy.py smart_reporting/tests/test_model_routing.py`

Expected: PASS。

```bash
git add smart_reporting/model_routing smart_reporting/reporting/model_policy.py smart_reporting/reporting/tests/test_reporting_thinking_policy.py smart_reporting/tests/test_model_routing.py
git commit -m "refactor: separate reporting thinking policy"
```

### Task 2: 请求级 ContextVar 绑定与模型请求消费

**Files:**
- Modify: `smart_reporting/reporting/model_policy.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_generator_agent.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_code_generation.py`

**Interfaces:**
- Consumes: Task 1 的 `ThinkingDecision`。
- Produces: `bind_reporting_thinking(decision)`、`current_reporting_thinking_decision()`；`ReportingOpenAIChat` 和 Coding Agent 对当前协程决策的隔离消费。

- [ ] **Step 1: 写请求隔离和 Off 清理的失败测试**

增加以下行为测试：

```python
def test_phase_request_uses_bound_decision_without_mutating_shared_model():
    model = ReportingPhaseOpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test",
        reasoning_effort="max",
        extra_body={"enable_thinking": True, "thinking_budget": 8192},
    )
    decision = ThinkingDecision(
        operation="data_understanding",
        complexity="standard",
        enabled=True,
        reasoning_effort="high",
        thinking_budget=2048,
        attempt=0,
        reason="initial_policy",
    )
    with bind_reporting_thinking(decision):
        request_model = model._phase_request_model([Message(role="user", content="test")])
    assert request_model.extra_body["thinking_budget"] == 2048
    assert model.extra_body["thinking_budget"] == 8192
```

另加并发 AnyIO 测试：一个协程绑定 4096，另一个绑定 Off；两者得到各自请求副本，共享模型仍为原配置。补充 Off 测试，断言 request 副本不含 `thinking_budget`、顶层 `reasoning_effort` 或 Responses `reasoning`。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_agent_projection.py smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_code_generation.py`

Expected: FAIL，模型请求尚未读取 ContextVar，Coding Agent 仍会无条件保留 reasoning Agent。

- [ ] **Step 3: 实现 ContextVar 绑定**

在 `reporting/model_policy.py` 增加：

```python
_CURRENT_REPORTING_THINKING: ContextVar[ThinkingDecision | None] = ContextVar(
    "current_reporting_thinking",
    default=None,
)

@contextmanager
def bind_reporting_thinking(decision: ThinkingDecision):
    token = _CURRENT_REPORTING_THINKING.set(decision)
    log_thinking_selection(decision.event_fields())
    try:
        yield
    finally:
        _CURRENT_REPORTING_THINKING.reset(token)
```

`current_reporting_thinking_decision()` 只返回当前协程值。嵌套绑定必须在退出后恢复外层值；测试覆盖异常退出和嵌套恢复。

- [ ] **Step 4: 让 Chat 请求副本消费精确决策**

在 `ReportingOpenAIChat._phase_request_model()` 中先复制模型和选择 routed `model_id`，再读取当前
`ThinkingDecision`。存在决策时从 request 副本清除历史字段并调用
`apply_reporting_thinking_profile()` 应用精确预算；不存在决策时保留现有 profile 行为作为非 Reporting
调用兼容路径。删除从 `ModelProfile.reasoning_effort` 或外层 tier 推断预算的逻辑。

- [ ] **Step 5: 让 Coding Agent 首次 Off 时跳过 reasoning 调用**

`ReportingCodeOpenAIResponses` 继续始终关闭输出模型自身 thinking。`ReportingCodeGenerationRunner._fresh_agent()`
读取当前决策：若为 Off，则在浅复制 Agent 上将 `reasoning_model` 和 `reasoning_agent` 设为 `None`；若启用则
保留 reasoning Agent，并由其 `OpenAIChat` 请求副本消费 2K/4K 决策。不得修改模板 Agent。

增加测试断言首次生成只发生一次 Responses 输出调用；绑定 2048 的修复会发生一次 reasoning 调用和一次
非 thinking Responses 输出调用；两个路径均只提交一次 `submit_python_source`。

- [ ] **Step 6: 运行定点测试并提交**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_agent_projection.py smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_code_generation.py`

Expected: PASS。

```bash
git add smart_reporting/reporting/model_policy.py smart_reporting/reporting/agent.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tests/test_reporting_agent_projection.py smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_code_generation.py
git commit -m "refactor: bind reporting thinking per request"
```

### Task 3: 结构化输出纠错轮次的预算切换

**Files:**
- Modify: `smart_reporting/reporting/structured_output/execution.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_structured_executor.py`

**Interfaces:**
- Consumes: Task 1 的 `ThinkingRequest`、`select_reporting_thinking()`；Task 2 的 `bind_reporting_thinking()`。
- Produces: `ReportingStructuredOutputExecutor.execute(..., thinking_request: ThinkingRequest | None)`，保证同一次结构化执行内首次与 Schema 纠错分别绑定预算。

- [ ] **Step 1: 写结构化纠错预算的失败测试**

用 Fake Agent 记录每次模型调用看到的决策，覆盖：

```python
request = ThinkingRequest(
    operation="data_understanding",
    complexity="standard",
    configured_budget_cap=8192,
)
result = await executor.execute(
    instruction,
    routing_context=context,
    session_id="thinking-test",
    user_id="user-1",
    thinking_request=request,
)
assert observed_budgets == [2048, 4096]
```

第一轮返回领域 Schema 无效内容，第二轮返回有效内容。另测 JSON Schema 传输降级不算业务失败，预算保持
2048；`StructuredOutputCallBudget` 耗尽时不创建额外 thinking 决策。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_structured_executor.py`

Expected: FAIL，`execute()` 尚无 `thinking_request` 参数且内部调用未绑定决策。

- [ ] **Step 3: 在每次真实模型调用边界选择并绑定预算**

为 `execute()` 增加可选 `thinking_request`。进入 `_execute_mode()` 前，以 `dataclasses.replace()` 构造本轮请求：

```python
call_request = replace(
    thinking_request,
    attempt=min(business_call_number, 1),
    failure_kind=next_failure_kind,
)
decision = select_reporting_thinking(call_request)
with bind_reporting_thinking(decision):
    execution_agent, output = await self._execute_mode(...)
```

初始 `next_failure_kind` 使用调用方传入值。结构或领域 Pydantic 校验失败后设为 `schema_failure`；Schema
transport fallback 不改变 failure、attempt 或预算。成功、异常和预算耗尽路径都依赖 ContextVar token
自动恢复。

- [ ] **Step 4: 保持无策略调用向后兼容**

当 `thinking_request is None` 时使用 `nullcontext()`，现有测试和非 Reporting 调用不改变行为。不得从
schema 名、Agent ID 或提示词猜测 operation。

- [ ] **Step 5: 运行定点测试并提交**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_structured_executor.py`

Expected: PASS。

```bash
git add smart_reporting/reporting/structured_output/execution.py smart_reporting/reporting/tests/test_reporting_structured_executor.py
git commit -m "feat: budget reporting structured retries"
```

### Task 4: 规划阶段接入 2K 数据理解和 SQL 策略

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/workflow/runtime/planning.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`

**Interfaces:**
- Consumes: Task 1 的 operation 策略；Task 3 的 `thinking_request` 执行参数。
- Produces: `_run_planner(..., thinking_complexity="standard", failure_kind=None, attempt=0)` 和每个 Planner 的固定 `ThinkingPolicyConfig`。

- [ ] **Step 1: 写各 Planner 初始预算和纠错预算的失败测试**

更新原 `test_runtime_planners_use_stage_specific_thinking_profiles`，不再读取模型上的固定 profile，改为断言
Agent 的 operation 配置。增加 Fake executor 记录请求：

```python
assert runtime._data_understanding_agent._reporting_thinking.operation == "data_understanding"
assert runtime._sql_agent._reporting_thinking.operation == "sql_planning"
assert observed["data_understanding"][0].configured_budget_cap == 8192
assert selected_budgets["data_understanding"] == [2048, 4096]
assert selected_budgets["sql_planning"] == [2048, 4096]
```

同时断言 request normalizer、领域识别和 outline 首次 Off，analysis planner 首次 2K；
`planner_enable_thinking=False` 时全部 operation 决策为 Off。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_planner_contracts.py -k 'thinking or data_understanding or sql'`

Expected: FAIL，当前数据理解和 SQL 首次均为 Off，且 Planner 仍持有 initial/escalation profile。

- [ ] **Step 3: 用 operation 配置替换 Planner 固定 profile**

在 `model_policy.py` 定义：

```python
@dataclass(frozen=True, slots=True)
class ThinkingPolicyConfig:
    operation: ThinkingOperation
    thinking_enabled: bool
    configured_budget_cap: int
```

`ReportWorkflowRuntime._planning_agent()` 改为接收该配置并保存到 Agent 的
`_reporting_thinking` 属性。Planner 模型模板只保留全局开关和硬上限，不再通过
`_report_escalation_thinking_profile` 表达业务预算。

- [ ] **Step 4: 扩展 `_run_planner` 传递调用级请求**

签名增加：

```python
async def _run_planner(
    self,
    agent: Agent,
    payload: dict[str, Any],
    run_context: RunContext,
    *,
    call_budget: StructuredOutputCallBudget | None = None,
    thinking_complexity: TaskComplexity = "standard",
    failure_kind: ThinkingFailureKind | None = None,
    attempt: int = 0,
) -> BaseModel:
```

从 Agent 读取 `ThinkingPolicyConfig`，构造 `ThinkingRequest` 后传给 executor。配置缺失时抛
`report_thinking_policy_missing`，不静默退回 8K。

- [ ] **Step 5: 给规划循环传入精确失败类型**

逐个绑定：请求归一化=`request_normalization`；数据理解=`data_understanding`，服务端能力映射反馈为
`capability_mapping_failure`；指标语义=`measure_semantics`，首次 2K、Schema 或候选字段能力映射失败时
4K；提纲=`outline_planning`；SQL=`sql_planning`，只读/字段/期间审核反馈为
`sql_validation_failure`；分析计划=`analysis_planning`。Schema 失败由 Task 3 的执行器内部升级。

外层循环使用 `attempt=0` 或 `1`，第二次及以后保持 1；超过一次升级不会增加预算。

- [ ] **Step 6: 运行定点测试并提交**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_planner_contracts.py -k 'thinking or data_understanding or sql or analysis_plan or outline'`

Expected: PASS。

```bash
git add smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/workflow/runtime/planning.py smart_reporting/reporting/model_policy.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py
git commit -m "feat: apply layered planner thinking budgets"
```

### Task 5: 分析、可视化和代码恢复接入分层预算

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_code_generation.py`

**Interfaces:**
- Consumes: Tasks 1–4 的策略、绑定、结构化执行器和 `_run_planner()`。
- Produces: `_analysis_item_complexity()` 驱动证据/总结预算；`_visualization_thinking_complexity()`；`_code_failure_kind()`；首次 Off 和 2K/4K 修复路径。

- [ ] **Step 1: 写分析阶段预算失败测试**

以现有 `test_analysis_script_repair_temporarily_escalates_to_max` 为基础改写预期：

```python
assert observed == [
    ("analysis_001:evidence:decision", "high", 2048),
    ("analysis_001:evidence:script:initial", None, 0),
    ("analysis_001:evidence:script:repair", "high", 2048),
    ("analysis_001:summary", "high", 2048),
]
```

另以简单、复杂计划验证 evidence/summary 分别为 1K/4K；`fact_incomplete` 的一次恢复为 6K/`max`；
业务 warning 不升级。

- [ ] **Step 2: 写可视化生成和修复预算失败测试**

在固定 Workflow 测试中记录三类调用：首次脚本生成看到 Off；Python 执行失败后的 repair 看到 2K；
`report_visualization_review_failed` 后的 repair 看到 4K。第二次失败终止，不能产生第三个更高决策。

定义可视化复杂度：一个 `analysisId` 为 simple，2–3 个为 standard，4 个及以上为 complex。测试分别断言
可视化计划为 1K、2K、4K；图表数量不参与首次复杂度判断，因为计划生成前尚无受信 charts。

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_planner_contracts.py -k 'analysis_script or analysis_item_thinking'
.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py -k visualization
.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_code_generation.py
```

Expected: FAIL，当前分析脚本预算沿用分析预算，可视化规划没有独立 ThinkingRequest。

- [ ] **Step 4: 替换分析阶段的共享 dependencies 临时写入**

删除 `analysis.py` 中手工保存/恢复 `REPORTING_THINKING_*_DEPENDENCY_KEY` 的两个 `try/finally` 块。
证据决策、总结、脚本生成和修复分别构造 request 并用 `bind_reporting_thinking()` 包裹真实调用：

```python
decision = select_reporting_thinking(
    ThinkingRequest(
        operation="analysis_script",
        complexity=complexity,
        attempt=1 if diagnostic is not None else 0,
        failure_kind=_code_failure_kind(diagnostic),
        configured_budget_cap=code_budget_cap,
        thinking_enabled=code_thinking_enabled,
    )
)
with bind_reporting_thinking(decision):
    return await code_runner.generate(...)
```

`_code_failure_kind()` 只把稳定的源码形状/语法错误映射为 `python_compile_failure`，脚本非零退出映射为
`python_execution_failure`，视觉审查拒绝映射为 `visual_review_failure`；未知、超时、取消、lease 和
Workspace 错误不得映射到升级类型。

- [ ] **Step 5: 接入可视化计划和恢复预算**

`generate_plan()` 调用 `ReportingStructuredOutputExecutor.run()` 时传入 `visualization_plan` 请求和由
analysisIds 数量得到的复杂度。`generate_script()` 首次绑定 Off；携带编译诊断的 fresh generate 绑定
2K。`repair_script()` 根据 `_repair_diagnostic()` 的稳定 code 绑定 2K 或 4K。

保持 `VisualizationSectionWorkflow` 的计划只生成一次、脚本生成最多三次、执行/视觉修复一次等现有次数
边界；thinking 策略只改变每次调用预算，不增加重试。

- [ ] **Step 6: 运行定点测试并提交**

Run:

```bash
.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_planner_contracts.py -k 'analysis_script or analysis_item_thinking'
.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py -k visualization
.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_code_generation.py
```

Expected: PASS。

```bash
git add smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_code_generation.py
git commit -m "perf: layer analysis and visualization thinking"
```

### Task 6: 章节生成预算、兼容契约和最终定点验证

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/sections.py`
- Modify: `smart_reporting/reporting/workflow/runtime/section_workflow.py`
- Modify: `smart_reporting/reporting/workflow/execution.py`
- Modify: `smart_reporting/reporting/phase.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_draft_workflow.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_task_coordinator.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

**Interfaces:**
- Consumes: Tasks 1–5 的请求级策略。
- Produces: 章节首次 Off、章节恢复 2K；acceptance contract 仅作外层默认值和兼容输入，不再控制内部子调用预算。

- [ ] **Step 1: 写章节预算与外层契约兼容测试**

增加测试记录 `_generate_section_in_blocks()` 中每次请求看到的决策：正常生成 Off；结构化或 render 恢复
调用为 2K；恢复再失败时不升到 4K。保留现有断言：业务语义差异只记录 warning，不能触发 recover。

在 coordinator 测试中断言模型路由仍选择相同 `tier/model_id`；acceptance contract 中已有
`thinkingEffort/thinkingBudget` 可继续被解析，但内部显式 decision 优先。

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest -q smart_reporting/reporting/tests/test_reporting_draft_workflow.py smart_reporting/reporting/tests/test_reporting_task_coordinator.py smart_reporting/reporting/tests/test_reporting_agent_projection.py -k 'thinking or section or model_route'`

Expected: FAIL，章节当前只通过外层 `thinkingEffort=off` 控制，恢复调用没有独立 2K 决策。

- [ ] **Step 3: 接入章节首次和恢复请求**

为 `_generate_section_in_blocks()` 增加 `thinking_request` 参数并传给结构化执行器。`generate()` 使用：

```python
ThinkingRequest(
    operation="section_generation",
    complexity="standard",
    attempt=0,
    configured_budget_cap=section_budget_cap,
    thinking_enabled=section_thinking_enabled,
)
```

`recover()` 使用相同 operation、`attempt=1` 和 `failure_kind="schema_failure"`，得到 2K。业务语义 warning
不构造 failure；现有 SectionWorkflow 两次尝试上限保持不变。

- [ ] **Step 4: 收窄外层 acceptance thinking 字段的职责**

`workflow/execution.py` 继续解析历史 contract 的 `thinkingEffort/thinkingBudget`，供尚未迁移的外层 Agent
兼容；已迁移的规划、分析、可视化和章节子调用必须优先消费 ContextVar decision。删除任何依据 routed
tier 自动设置 high/max 的路径。不要改变 contract 版本和 durable payload 结构。

- [ ] **Step 5: 运行一次最终定点测试集合**

Run:

```bash
.venv/bin/python -m pytest -q \
  smart_reporting/tests/test_model_routing.py \
  smart_reporting/reporting/tests/test_reporting_thinking_policy.py \
  smart_reporting/reporting/tests/test_reporting_structured_executor.py \
  smart_reporting/reporting/tests/test_reporting_planner_contracts.py \
  smart_reporting/reporting/tests/test_reporting_agent_projection.py \
  smart_reporting/reporting/tests/test_reporting_generator_agent.py \
  smart_reporting/reporting/tests/test_reporting_code_generation.py \
  smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py \
  smart_reporting/reporting/tests/test_reporting_draft_workflow.py \
  smart_reporting/reporting/tests/test_reporting_task_coordinator.py
```

Expected: PASS。不要再次运行这些文件或完整测试套件。

- [ ] **Step 6: 检查 diff 并提交**

Run: `git diff --check`

Expected: 无输出。

确认 `rg -n 'thinking_budget.*8192|reasoning_effort="max"' smart_reporting/reporting` 的剩余命中仅属于环境
硬上限、传输兼容测试或明确的 6K Recovery 实现，不存在正常路径 8K 默认请求。

```bash
git add smart_reporting/reporting/workflow/runtime/sections.py smart_reporting/reporting/workflow/runtime/section_workflow.py smart_reporting/reporting/workflow/execution.py smart_reporting/reporting/phase.py smart_reporting/reporting/tests/test_reporting_draft_workflow.py smart_reporting/reporting/tests/test_reporting_task_coordinator.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
git commit -m "perf: complete reporting thinking budget migration"
```
