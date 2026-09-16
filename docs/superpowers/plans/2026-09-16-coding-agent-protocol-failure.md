# Coding Agent Protocol Failure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 约束 Coding Agent 的 free-form custom tool wire format，并确保 DSML 正文与无签发结束只消费一次 generation，不再伪装成三轮脚本修复。

**Architecture:** 保留 Agno `Agent.arun` 工具循环，在 `ReportingCodeOpenAIResponses` provider 边界完成 grammar 声明、显式 `tool_choice` 保留和 DSML 正文拒绝。Runner 将 provider 记录的稳定协议错误透传，并给普通无签发错误附加 `retryable=false`；固定 Workflow 仅对已有签发脚本的真实技术失败启动诊断修复，无签发则立即进入原有 analysis 放弃补证或 visualization 零图降级终态。

**Tech Stack:** Python 3.12、Agno 3.0.9、OpenAI Responses API、Pydantic、Loguru、pytest。

**Spec:** `docs/superpowers/specs/2026-09-15-coding-agent-codemode-enhance-design.md`

## Global Constraints

- `write_script`、`execute_code` 使用 `start: SOURCE`、`SOURCE: /[\s\S]+/` 的 Lark grammar custom tool，不保留 `format: {type: "text"}` 兼容分支。
- 调用方显式 `tool_choice` 原样保留；仅 `None` 时默认 `auto`；`parallel_tool_calls` 始终为 `false`。
- DSML assistant 正文不解析、不执行，返回 `report_code_custom_tool_protocol_error` 和 `retryable=false`。
- 普通文本结束、工具上限耗尽或无签发返回 `report_code_generation_no_submission` 和 `retryable=false`。
- 单个 coding task 的协议失败或无签发只调用一次 Agent；已签发脚本的编译、执行、输出身份及领域技术失败继续使用现有诊断修复。
- analysis 无签发后立即放弃补证，visualization 无签发后立即零图降级；不改变最终 accepted/degraded 业务结果。
- 应用日志继续使用 Loguru；不增加兼容、恢复、临时 Workspace 或自定义模型循环。
- 每个任务只运行对应定点测试；最后统一运行一次受影响测试集合，禁止重复完整测试。

## File Map

- Modify `smart_reporting/reporting/code_agent/protocol.py`: 输出 grammar custom tool、保留显式工具选择并拒绝 DSML assistant 正文。
- Modify `smart_reporting/reporting/workflow/runtime/code_generation.py`: 透传 provider 稳定错误，给无签发结果附加不可重试标记。
- Modify `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`: 无签发时不重跑 generation，直接沿用放弃补证终态。
- Modify `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`: 无签发特判先于通用不可恢复判断，保持单次 generation 后零图降级。
- Modify `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`: 覆盖 wire format、工具选择、DSML 拒绝、provider 错误透传和无签发错误形状。
- Modify `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`: 覆盖 analysis/visualization 无签发只调用一次及已有脚本技术失败仍修复。

---

### Task 1: Provider Protocol Boundary

**Files:**
- Modify: `smart_reporting/reporting/code_agent/protocol.py:273-311,379-400`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py:358-505`

**Interfaces:**
- Consumes: Agno `OpenAIResponses` tool definitions and OpenAI `Response.output` items.
- Produces: grammar custom tool dictionaries and `ReportingError(code="report_code_custom_tool_protocol_error", details={"retryable": False})`.

- [ ] **Step 1: Write failing protocol tests**

Replace the text-format assertion and split the tool-choice behavior into explicit/default cases:

```python
assert tools[1]["format"] == {
    "type": "grammar",
    "syntax": "lark",
    "definition": "start: SOURCE\nSOURCE: /[\\s\\S]+/",
}
assert explicit["tool_choice"] == {"type": "custom", "name": "write_script"}
assert defaulted["tool_choice"] == "auto"
```

Add a provider response containing only assistant `output_text` with a DSML tool marker such as `<|recipient=write_script|>` and assert `_parse_provider_response()` raises `report_code_custom_tool_protocol_error` with `details == {"retryable": False}`。Add a plain assistant-text case and assert it remains ordinary model content.

- [ ] **Step 2: Run protocol tests and verify RED**

Run:

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'mixed_protocol_formats or code_requests or dsml'
```

Expected: grammar assertion sees `format.type == "text"`; explicit tool choice sees `"auto"`; DSML response does not raise.

- [ ] **Step 3: Implement the provider boundary**

Define immutable module constants for the grammar and bounded DSML marker detection. Emit:

```python
"format": {
    "type": "grammar",
    "syntax": "lark",
    "definition": _FREEFORM_TOOL_GRAMMAR,
}
```

In `get_request_params()`, keep `parallel_tool_calls=False` and set `tool_choice="auto"` only when tools exist and the superclass did not receive an explicit choice. Before delegating response parsing, inspect assistant message text only when there is no structured actionable call; if it contains a known DSML tool-call marker, raise the stable nonretryable protocol error. Never synthesize a tool call from text.

- [ ] **Step 4: Run protocol tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests pass.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/reporting/code_agent/protocol.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "fix: harden coding agent custom tool protocol"
```

### Task 2: Runner Failure Classification

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py:145-196`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py:1020-1066`

**Interfaces:**
- Consumes: `agent.model.report_run_error() -> Exception | None` when Agno returns a failed run instead of raising.
- Produces: unchanged stable provider `ReportingError`, or `report_code_generation_no_submission` with `details={"retryable": False}`.

- [ ] **Step 1: Write failing runner tests**

Extend the no-submission test:

```python
assert caught.value.code == "report_code_generation_no_submission"
assert caught.value.details == {"retryable": False}
```

Add an Agent double whose `arun()` returns normally while `model.report_run_error()` returns a nonretryable `report_code_custom_tool_protocol_error`; assert the runner raises that same error object and shuts down the CodeMode session.

- [ ] **Step 2: Run runner tests and verify RED**

Run:

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'no_submission or recorded_protocol_error'
```

Expected: no-submission details are absent and the recorded provider error is replaced by `report_code_generation_no_submission`.

- [ ] **Step 3: Implement stable failure propagation**

After `agent.arun()`, call `report_run_error` only when it is callable and re-raise a returned `Exception` before checking the receipt. Create no-submission as:

```python
ReportingError(
    "report_code_generation_no_submission",
    "Coding Agent 未签发成功执行的 Python 脚本。",
    details={"retryable": False},
)
```

Keep the existing rate-limit mapping and generic exception sanitization unchanged.

- [ ] **Step 4: Run runner tests and verify GREEN**

Run the Step 2 command. Expected: selected tests pass and both paths shut down exactly one task session.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "fix: classify coding agent terminal failures"
```

### Task 3: Workflow Retry Boundary

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py:700-764`
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py:411-442`
- Test: `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`

**Interfaces:**
- Consumes: nonretryable `report_code_generation_no_submission` and `report_code_custom_tool_protocol_error` from the runner.
- Produces: one-call analysis supplement abandonment, one-call visualization degradation, and fail-closed protocol errors.

- [ ] **Step 1: Write failing Workflow tests**

Add an analysis case whose `run_code` raises nonretryable no-submission and assert the Workflow completes through its existing supplement-abandoned path after exactly one call. Update the visualization no-submission fixture to include `details={"retryable": False}` and keep assertions `run_count == 1`, `status == "degraded"`, and `executionRepairCount == 0`. Add protocol-error cases for both Workflows and assert one `run_code` call with no repair or degrade callback.

Retain the existing visualization execution-failure test asserting four calls (initial plus three repairs); it is the regression guard that signed technical failures remain repairable.

- [ ] **Step 2: Run Workflow tests and verify RED**

Run:

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_v1_workflows.py -k 'no_submission or protocol_error or execution_repairs'
```

Expected: analysis raises instead of abandoning and visualization raises before its no-submission degradation branch.

- [ ] **Step 3: Implement terminal no-submission handling**

In analysis `_execute_script()`, handle `report_code_generation_no_submission` before the generic nonrecoverable branch: store the failure, clear evidence, and return `_abandon_supplement(state)` without scheduling another loop iteration. In visualization, move the existing no-submission degradation block before `_is_nonrecoverable(error)`. Do not add protocol errors to degradable sets; `retryable=false` must continue to fail closed.

- [ ] **Step 4: Run Workflow tests and verify GREEN**

Run the Step 2 command. Expected: no-submission calls once, protocol errors call once and escape, and execution failures retain their existing repair count.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/tests/test_reporting_v1_workflows.py
git commit -m "fix: stop retrying unsigned code generations"
```

### Task 4: Unified Verification

**Files:**
- Verify only; no production changes expected.

**Interfaces:**
- Consumes: Tasks 1-3 commits.
- Produces: one evidence-backed verification result for the affected protocol and Workflow surface.

- [ ] **Step 1: Run the affected test set once**

```bash
uv run pytest -q \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  smart_reporting/reporting/tests/test_reporting_v1_workflows.py \
  smart_reporting/reporting/tests/test_reporting_repair_knowledge.py \
  smart_reporting/reporting/tests/test_reporting_visual_repair_diagnostic.py
```

Expected: all tests pass with no warnings introduced by these changes.

- [ ] **Step 2: Run static patch checks**

```bash
git diff --check HEAD~3..HEAD
git status --short
```

Expected: diff check passes; unrelated pre-existing worktree modifications remain unstaged.

- [ ] **Step 3: Inspect commit scope**

```bash
git log --oneline -4
git show --stat --oneline HEAD~2..HEAD
```

Expected: the three implementation commits contain only the files listed in Tasks 1-3.
