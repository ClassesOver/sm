# Reporting Code Agent Visual Review Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move visualization review into the Code Agent tool loop through a server-enforced `view_image` tool backed by the independent vision model, and remove the old outer `inspect_chart` workflow.

**Architecture:** `ReportingCodeModeToolkit.view_image()` validates a declared output against the latest execution receipt, delegates to `ReportVisionReviewer`, and stores the resulting `ChartVisualInspectionReceipt` directly on the task binding. Visualization submission requires current passing receipts for every declared image. `VisualizationSectionWorkflow` only verifies signed receipts and submits them; it never invokes the vision model.

**Tech Stack:** Python 3.12, Agno Toolkit/Agent, OpenAI-compatible independent vision model, Pydantic, pytest/AnyIO, Loguru.

**Spec:** `docs/superpowers/specs/2026-09-16-coding-agent-view-image-design.md`

## Global Constraints

- Coding main model has no vision capability and receives structured review text only.
- `ReportVisionReviewer` remains the only image-understanding component.
- No compatibility aliases for `inspect_chart` or the old outer review callback.
- CodeMode continues to use the formal session Workspace directly.
- Visual receipts are task-local, server-owned, and bound to exact file SHA-256 values.
- Visualization fails closed when the independent vision reviewer is unavailable.
- Semantic business checks remain soft warnings; technical identity and review-gate failures are blocking.
- Application logging uses Loguru.
- Run only affected targeted tests; do not repeat the complete suite.

---

### Task 1: Add Server-Owned Visual Receipt State

**Files:**
- Modify: `smart_reporting/reporting/code_agent/context.py`
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`

**Interfaces:**
- Consumes: existing `ExecutionReceipt` and `ChartVisualInspectionReceipt`.
- Produces: `ReportingCodingTaskBinding.visual_inspection_receipts`, `clear_execution_state()`, and `CodeGenerationResult.visual_inspection_receipts`.

- [ ] **Step 1: Write failing binding-state tests**

Add tests that construct a visualization binding, store a receipt, call the new reset method, and assert both execution and visual state are empty. Also assert an analysis `CodeGenerationResult` defaults to an empty visual receipt tuple.

```python
receipt = ChartVisualInspectionReceipt.model_validate(passing_receipt)
binding.visual_inspection_receipts[receipt.source_path] = receipt
binding.execution_receipt = execution_receipt
binding.clear_execution_state()
assert binding.execution_receipt is None
assert binding.visual_inspection_receipts == {}

result = CodeGenerationResult(script_file=source, execution_receipt=execution_receipt)
assert result.visual_inspection_receipts == ()
```

- [ ] **Step 2: Run the new tests and verify failure**

Run:

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'visual_receipt_state or code_generation_result_visual'
```

Expected: failure because the binding field/reset method and result field do not exist.

- [ ] **Step 3: Implement task-local state**

Add these exact shapes:

```python
@dataclass(slots=True)
class ReportingCodingTaskBinding:
    ...
    execution_receipt: ExecutionReceipt | None = None
    visual_inspection_receipts: dict[str, ChartVisualInspectionReceipt] = field(
        default_factory=dict
    )

    def clear_execution_state(self) -> None:
        self.execution_receipt = None
        self.visual_inspection_receipts.clear()

@dataclass(frozen=True, slots=True)
class CodeGenerationResult:
    script_file: FileIdentity
    execution_receipt: ExecutionReceipt
    visual_inspection_receipts: tuple[ChartVisualInspectionReceipt, ...] = ()
```

Keep revision history out of this first implementation unless a later test demonstrates it is needed; the latest failed receipt already carries the bounded structured diagnostic.

- [ ] **Step 4: Run the focused tests**

Run the Step 2 command. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add smart_reporting/reporting/code_agent/context.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py
git commit -m "feat: track code agent visual receipts"
```

---

### Task 2: Implement Independent-Model `view_image` and Submission Gate

**Files:**
- Modify: `smart_reporting/reporting/code_agent/toolkit.py`
- Modify: `smart_reporting/reporting/vision.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`
- Test: `smart_reporting/reporting/tests/test_report_vision.py`

**Interfaces:**
- Consumes: `ReportVisionReviewer.review(workspace_key, path, detail)` and binding state from Task 1.
- Produces: `ReportingCodeModeToolkit.view_image(path, detail="high")` and visualization-specific `submit_script` visual gates.

- [ ] **Step 1: Write failing tool registration and authorization tests**

Cover these exact cases:

```python
assert "view_image" not in analysis_tool_names
assert "view_image" in visualization_tool_names

result = await visualization_toolkit.view_image("charts/not-declared.png")
assert result["ok"] is False
assert result["code"] == "report_code_visual_path_forbidden"

result = await visualization_toolkit.view_image("charts/chart.png")
assert result["code"] == "report_code_visual_review_required_execution"
```

- [ ] **Step 2: Write failing successful-review, cache, and identity-race tests**

Use an `AsyncMock` reviewer returning a `ChartVisualInspectionReceipt`. Assert:

- current output is reviewed and stored by path;
- structured receipt is returned to the Coding main model;
- a second call for the same SHA-256 reuses the receipt without another reviewer call;
- a changed post-review file returns `report_code_visual_output_changed` and stores nothing.

- [ ] **Step 3: Write failing submission-gate tests**

For visualization tasks assert:

```text
no receipt             -> report_code_visual_review_required
requiresRevision=true  -> report_code_visual_revision_required
stale receipt hash      -> report_code_visual_output_changed
all current receipts    -> submit succeeds
```

Also retain an analysis submission test proving analysis does not require visual receipts.

- [ ] **Step 4: Run the new Toolkit tests and verify failure**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'view_image or visual_review or submit'
```

Expected: new tests fail because `view_image` and visual gates do not exist.

- [ ] **Step 5: Implement `view_image`**

Inject `ReportVisionReviewer | None` into Toolkit. Register this function only for visualization tasks:

```python
Function(
    name="view_image",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "detail": {"type": "string", "enum": ["high", "original"]},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    strict=True,
    entrypoint=self.view_image,
)
```

Implementation sequence:

```python
async def view_image(self, path: str, detail: str = "high", ...) -> dict[str, Any]:
    receipt = self.binding.execution_receipt
    # Reject absent execution, unauthorized path, or output not in receipt.
    before = await self.workspace.ahash_file(self.context.task_id, path)
    # Reuse binding.visual_inspection_receipts[path] only when SHA matches.
    reviewed = ChartVisualInspectionReceipt.model_validate(
        await self.vision_reviewer.review(self.context.workspace_key, path, detail=detail)
    )
    after = await self.workspace.ahash_file(self.context.task_id, path)
    # Require before SHA == reviewed SHA == after SHA == execution output SHA.
    self.binding.visual_inspection_receipts[path] = reviewed
    return {"ok": True, "receipt": reviewed.model_dump(mode="json", by_alias=True)}
```

Return stable bounded failures rather than raw reviewer exceptions.

- [ ] **Step 6: Invalidate visual state and enforce submit gates**

Replace direct `binding.execution_receipt = None` assignments in `write_script`, `run_script`, and `restart_code_mode` with `binding.clear_execution_state()`. In `submit_script`, validate the complete current receipt set before assigning `submitted_receipt`.

- [ ] **Step 7: Run Toolkit and reviewer tests**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_report_vision.py
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add smart_reporting/reporting/code_agent/toolkit.py smart_reporting/reporting/vision.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_report_vision.py
git commit -m "feat: add independent visual review tool"
```

---

### Task 3: Inject the Reviewer and Return Signed Visual Receipts

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Test: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`
- Test: `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`

**Interfaces:**
- Consumes: Toolkit constructor and visual state from Tasks 1-2.
- Produces: Runner constructor with explicit `vision_reviewer`, dynamic `tool_call_limit`, and signed `CodeGenerationResult.visual_inspection_receipts`.

- [ ] **Step 1: Write failing runner tests**

Assert that:

- visualization Runner construction without a reviewer fails before Agent execution;
- analysis Runner can run without a reviewer;
- the exact reviewer instance is passed to the task-local Toolkit;
- returned visual receipts are sorted by `source_path`;
- `tool_call_limit == min(140, 29 + len(declared_output_paths))` for visualization and remains 20 for analysis.

- [ ] **Step 2: Run focused runner tests and verify failure**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py -k 'runner and (vision or tool_call_limit or visual_receipts)'
```

- [ ] **Step 3: Implement explicit reviewer injection**

Add `vision_reviewer: ReportVisionReviewer | None` to `ReportingCodeGenerationRunner`. Pass it into Toolkit. Fail with `report_code_visual_reviewer_missing` when `task_kind == "visualization"` and it is absent.

After Agent completion and `require_current_receipt`, construct:

```python
visual_receipts = tuple(
    binding.visual_inspection_receipts[path]
    for path in sorted(binding.visual_inspection_receipts)
)
return CodeGenerationResult(
    script_file=receipt.source_file,
    execution_receipt=receipt,
    visual_inspection_receipts=visual_receipts,
)
```

- [ ] **Step 4: Implement dynamic tool budget at Agent creation**

Set the task-local Agent limit after factory creation and before `arun`:

```python
agent.tool_call_limit = (
    min(140, 29 + len(task_context.declared_output_paths))
    if task_context.task_kind == "visualization"
    else 20
)
```

Reject a calculated value above the hard limit rather than silently dropping image reviews if future context limits exceed the current 100-output contract.

- [ ] **Step 5: Wire runtime ownership**

Pass the existing `ReportWorkflowRuntime.vision_reviewer` into visualization runners. Analysis runners pass `None`. Keep reviewer construction in `bootstrap.create_report_runtime`; Toolkit and Runner must not instantiate it.

- [ ] **Step 6: Run focused runner and V1 tests**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_reporting_v1_workflows.py
```

- [ ] **Step 7: Commit**

```bash
git add smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_reporting_v1_workflows.py
git commit -m "feat: sign visual receipts from code agent"
```

---

### Task 4: Remove Outer Visual Review from the Fixed Workflow

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_repair_knowledge.py`

**Interfaces:**
- Consumes: `CodeGenerationResult.visual_inspection_receipts` from Task 3.
- Produces: `VisualizationSectionWorkflow(generate_plan, run_code, submit, degrade, ...)` with no `inspect_chart` argument.

- [ ] **Step 1: Rewrite V1 Workflow tests first**

Replace external inspection mocks with signed Code Agent results. Add assertions that Workflow:

- submits the signed passing receipts without calling a reviewer;
- rejects path, hash, status, or `requiresRevision` mismatches as `report_phase_artifact_changed`;
- does not contain a visual repair loop;
- preserves execution-failure degradation;
- records successful repair knowledge only after domain submission accepts.

- [ ] **Step 2: Run V1 tests and verify failure**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_v1_workflows.py smart_reporting/reporting/tests/test_reporting_repair_knowledge.py
```

- [ ] **Step 3: Remove outer review code**

Delete `InspectChart`, the `inspect_chart` constructor field, `MAX_VISUALIZATION_REVIEW_REPAIRS`, `visual_review_repairs`, `_visual_review_issue_summary`, and the entire review-repair branch. Validate signed receipts immediately after validating execution outputs.

Change submit calls to pass `generated_result.visual_inspection_receipts`.

- [ ] **Step 4: Remove analysis runtime callback assembly**

Delete the local `inspect_chart()` function and remove `inspect_chart` from `workflow_kwargs`. Keep the existing domain `submit_visualization_charts` call and pass the signed receipts it receives from Workflow.

- [ ] **Step 5: Run affected Workflow tests**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_v1_workflows.py smart_reporting/reporting/tests/test_reporting_repair_knowledge.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py -k 'visualization'
```

- [ ] **Step 6: Commit**

```bash
git add smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_reporting_v1_workflows.py smart_reporting/reporting/tests/test_reporting_repair_knowledge.py
git commit -m "refactor: remove outer visualization review"
```

---

### Task 5: Delete the Legacy `inspect_chart` Tool Surface

**Files:**
- Modify: `smart_reporting/reporting/tools/visualization.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/tools/factory.py`
- Modify: `smart_reporting/reporting/tools/capabilities.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_execution.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`

**Interfaces:**
- Consumes: Code Agent `view_image` from Task 2.
- Produces: no Reporting phase `inspect_chart` function, capability, instruction, or compatibility fixture.

- [ ] **Step 1: Update contract tests to require absence**

Assert `inspect_chart` is absent from phase tool names, capability sets, model projections, and agent instructions. Keep `view_image` assertions scoped to the Code Agent Toolkit tests; do not expose it through the general Reporting phase Toolkit.

- [ ] **Step 2: Run the focused contract tests and verify failure**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_agent_projection.py -k 'inspect_chart or view_image or tool'
```

- [ ] **Step 3: Delete production legacy surface**

Remove `RuntimeVisualizationMixin.inspect_chart`, factory registration/removal branches, capability entries, agent filtering, and old dual-tool instructions. Do not leave deprecated aliases or wrappers.

- [ ] **Step 4: Delete obsolete V0 visualization tests**

Remove tests that instantiate `VisualizationSectionWorkflow` with `generate_script`, `repair_script`, `execute_script`, or `inspect_chart`. Remove their per-test skip markers. Preserve and run the non-visualization assemble/section tests already restored in that file.

- [ ] **Step 5: Run affected phase-tool and restored workflow tests**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_agent_projection.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py
```

- [ ] **Step 6: Commit**

```bash
git add smart_reporting/reporting/tools smart_reporting/reporting/agent.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_agent_execution.py smart_reporting/reporting/tests/test_reporting_agent_projection.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py
git commit -m "refactor: delete legacy chart inspection tool"
```

---

### Task 6: End-to-End Visual Repair and Resource Cleanup

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`
- Modify: `docs/superpowers/specs/2026-09-15-coding-agent-codemode-enhance-design.md`

**Interfaces:**
- Consumes: final Code Agent and Workflow contracts from Tasks 1-5.
- Produces: one real Agent E2E proving independent visual repair and updated source design documentation.

- [ ] **Step 1: Add the real Agent E2E**

Script the Responses sequence:

```text
write_script
run_script
view_image -> requiresRevision=true with structured overlap issue
write_script
run_script
view_image -> requiresRevision=false
submit_script
```

Assert:

- the independent reviewer is called twice with two different output hashes;
- the Coding main model request history contains structured text results only, never image bytes/data URLs;
- final `CodeGenerationResult` contains the passing receipt;
- Kernel and binding are released after success.

- [ ] **Step 2: Add failure and cancellation cleanup tests**

Cover reviewer exception and `asyncio.CancelledError` during `view_image`. Assert Kernel shutdown and `registry.active_count == 0`; no visual receipt survives binding release.

- [ ] **Step 3: Run the focused E2E and Workflow tests**

```bash
uv run pytest -q smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_reporting_v1_workflows.py
```

- [ ] **Step 4: Update the original Code Agent design**

Replace the old outer visual-review statements with a short reference to `2026-09-16-coding-agent-view-image-design.md`. Keep historical decisions accurate: independent reviewer, structured tool result, server-owned receipt, no outer review.

- [ ] **Step 5: Run final targeted verification once**

```bash
uv run pytest -q \
  smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py \
  smart_reporting/reporting/tests/test_report_vision.py \
  smart_reporting/reporting/tests/test_reporting_v1_workflows.py \
  smart_reporting/reporting/tests/test_reporting_repair_knowledge.py \
  smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
  smart_reporting/reporting/tests/test_reporting_agent_execution.py \
  smart_reporting/reporting/tests/test_reporting_agent_projection.py \
  smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py
uv run ruff check \
  smart_reporting/reporting/code_agent \
  smart_reporting/reporting/workflow/runtime/code_generation.py \
  smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py \
  smart_reporting/reporting/tools \
  smart_reporting/reporting/vision.py
git diff --check
```

Expected: all selected tests pass, Ruff passes, and no whitespace errors remain. Do not repeat this aggregate command after it passes.

- [ ] **Step 6: Commit**

```bash
git add smart_reporting/reporting/tests/test_reporting_interactive_code_agent.py smart_reporting/reporting/tests/test_reporting_v1_workflows.py docs/superpowers/specs/2026-09-15-coding-agent-codemode-enhance-design.md
git commit -m "test: verify code agent visual repair loop"
```
