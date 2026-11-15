# Dual-render Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support per-chart Matplotlib or Plotly rendering with report-level `auto`, `static`, and `interactive` preferences while preserving static PDF/Word output.

**Architecture:** Keep the existing raster chart as the stable Markdown and export artifact. Add a hash-bound Plotly JSON companion to Plotly charts and progressively enhance only the report editor page with locally bundled Plotly.js.

**Tech Stack:** Python 3.12, Pydantic, Agno tools, FastAPI, TypeScript, Milkdown, Plotly.py, Plotly.js, pytest, Vitest

**Spec:** `docs/superpowers/specs/2026-09-20-dual-render-visualization-design.md`

## Global Constraints

- Default report preference is `auto`; supported values are exactly `auto`, `static`, and `interactive`.
- Renderer selection is per chart and is exactly `matplotlib` or `plotly`.
- Every chart retains a PNG/JPEG fallback; PDF and Word never consume Plotly JSON.
- Plotly companions are JSON only. Never accept generated HTML or JavaScript.
- Plotly.js must be bundled locally and loaded lazily; no CDN and no CSP relaxation.
- Semantic business validation produces soft warnings; path, identity, and executable-content validation fail closed.
- Do not install or rely on Kaleido in this implementation.（**已取代（2026-09-24）：** 用户拍板安装 `kaleido>=1.4.0`，根 Dockerfile 构建期 provision 专用 Chrome 并冒烟验证 `fig.write_image()`；详见 `docs/superpowers/plans/2026-09-20-reporting-coding-performance-optimization.md` 的 2026-09-24 Kaleido 登记。本条与第 141 行"without claiming Kaleido support"仅保留为历史决策记录。）
- Run focused tests after each task; do not repeat the full test suite.

---

### Task 1: Request And Chart Contracts

**Files:**
- Modify: `smart_reporting/reporting/contract.py`
- Modify: `smart_reporting/reporting/workflow/runtime/phase_models.py`
- Modify: `smart_reporting/reporting/delivery/draft_v1.py`
- Modify: `smart_reporting/reporting/workflow/checkpoint.py`
- Test: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`
- Test: `smart_reporting/reporting/tests/test_reporting_v1_workflows.py`

**Interfaces:**
- Produces: `ReportRequestEnvelope.visualization_mode: Literal["auto", "static", "interactive"]`
- Produces: chart fields `renderer` and optional `interactivePath`/`interactiveFile`

- [ ] Add failing tests asserting the request defaults to `auto`, serializes an explicit override, old chart payloads default to Matplotlib, and Plotly requires a `.plotly.json` companion.
- [ ] Run the named tests and confirm failures are caused by missing fields.
- [ ] Add the minimal Pydantic fields and validators while keeping existing payloads compatible.
- [ ] Run the named tests and confirm they pass.
- [ ] Commit request and chart contract support.

### Task 2: Plotly JSON Inspection And Durable Submission

**Files:**
- Modify: `smart_reporting/reporting/workspace.py`
- Modify: `smart_reporting/reporting/host_workspace.py`
- Modify: `smart_reporting/reporting/tools/visualization.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Test: `smart_reporting/reporting/tests/test_reporting_host_workspace.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

**Interfaces:**
- Produces: `inspect_report_plotly_file(service, thread_id, path) -> dict[str, Any]`
- Produces: durable `interactiveFiles` identities paired to Plotly chart registrations

> **2026-09-24 实施补记：** `ReportingWorkspaceAdapter` 已补齐 `inspect_plotly_file`，并把缺失能力收敛为结构化失败码 `report_workspace_capability_missing`（fatal-fast）；可视化章节 fresh-attempt 循环遇到该错误码记账后立即上抛，不再触发 4 次整段重跑。

- [ ] Add failing tests for a valid bounded Plotly figure, malformed JSON, forbidden URL/script content, unsupported traces, excessive complexity, missing companion, and cross-root paths.
- [ ] Run those tests and verify each failure is feature-related.
- [ ] Implement structured JSON inspection with explicit limits and allowlists.
- [ ] Extend submission to inspect and persist companion identities without applying visual review to JSON.
- [ ] Run the focused workspace and tool tests.
- [ ] Commit Plotly artifact validation and submission.

### Task 3: Analysis And Delivery Manifests

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/sections.py`
- Modify: `smart_reporting/reporting/delivery/artifacts_v1.py`
- Modify: `smart_reporting/reporting/workflow/runtime/publication.py`
- Test: `smart_reporting/reporting/tests/test_reporting_semantic_contract.py`
- Test: `smart_reporting/reporting/tests/test_reporting_artifacts_v1.py`

**Interfaces:**
- Consumes: chart renderer and hash-bound interactive file identity
- Produces: `ChartArtifact.interactive_spec` while preserving `ChartArtifact.path` as raster fallback

- [ ] Add failing tests proving Plotly metadata survives analysis finalization and artifact publication while Markdown still references only images.
- [ ] Verify the tests fail because interactive metadata is dropped or rejected.
- [ ] Propagate renderer and companion identity through manifests; accept only registered companion JSON as a non-image artifact.
- [ ] Run focused semantic and artifact tests.
- [ ] Commit manifest propagation.

### Task 4: Editor API

**Files:**
- Modify: `smart_reporting/report_editor/service.py`
- Modify: `smart_reporting/report_editor/api.py`
- Test: `smart_reporting/reporting/tests/test_report_editor.py`

**Interfaces:**
- Produces: document `interactiveCharts` mapping keyed by static image path
- Produces: authenticated JSON asset response with stored size/SHA-256 verification

- [ ] Add failing tests for document mapping, valid JSON retrieval, unregistered paths, changed content, and response security headers.
- [ ] Verify the focused tests fail for missing API behavior.
- [ ] Implement registered Plotly asset reads separately from raster reads and return the mapping from the document endpoint.
- [ ] Run the editor API tests.
- [ ] Commit editor interactive artifact API.

### Task 5: Frontend Progressive Enhancement

**Files:**
- Create: `smart_reporting/report_editor/frontend/src/interactive-charts.ts`
- Create: `smart_reporting/report_editor/frontend/src/interactive-charts.test.ts`
- Modify: `smart_reporting/report_editor/frontend/src/protocol.ts`
- Modify: `smart_reporting/report_editor/frontend/src/main.ts`
- Modify: `smart_reporting/report_editor/frontend/package.json`
- Modify: `smart_reporting/report_editor/frontend/package-lock.json`
- Modify: `smart_reporting/report_editor/frontend/scripts/check-build-budget.mjs`

**Interfaces:**
- Consumes: `interactiveCharts` document mapping and same-origin Plotly JSON
- Produces: `enhanceInteractiveCharts(root, charts)` with image fallback on every failure

- [ ] Add failing Vitest cases for successful enhancement, failed fetch/import/render fallback, accessibility labeling, resize, and stale chart cleanup.
- [ ] Run only `interactive-charts.test.ts` and verify expected failures.
- [ ] Add a lazy Plotly.js import and replace images only after a successful render.
- [ ] Add an explicit vendor chunk budget appropriate to the measured minified artifact.
- [ ] Run the focused frontend tests, build, and budget check.
- [ ] Commit frontend interactive rendering.

### Task 6: Model Guidance And End-to-End Regression

**Files:**
- Modify: `smart_reporting/reporting/bootstrap.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/reporting/tools/analysis_item.py`
- Modify: `smart_reporting/README.md`
- Test: `smart_reporting/reporting/tests/test_reporting_workspace_port.py`
- Test: `smart_reporting/reporting/tests/test_reporting_integration.py`

**Interfaces:**
- Consumes: report visualization preference and dual-render chart contract
- Produces: model freedom to select a supported renderer without a Matplotlib-only AST gate

- [ ] Add failing tests showing valid Matplotlib and Plotly-producing scripts pass source preflight while forbidden paths and tool impersonation still fail.
- [ ] Verify failures come from the current Matplotlib-only gate.
- [ ] Replace library-specific source enforcement with output-contract enforcement and update task instructions without claiming Kaleido support.
- [ ] Add a focused integration case containing one Matplotlib and one Plotly chart and assert static export remains image-only.
- [ ] Run the focused Python tests once, then run frontend tests/build once if Task 5 changed after its verification.
- [ ] Update documentation and commit the completed feature.

