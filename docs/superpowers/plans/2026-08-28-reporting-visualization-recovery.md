# Reporting Visualization Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Reporting 在未启用视觉模型时仍能以诚实的确定性检查完成图表登记，并修复真实 CLI 暴露的 citation 契约、no-progress 终止和无效探索问题。

**Architecture:** 保留现有 matplotlib 脚本和 `register_report_charts` 公共工具形状。服务端把图表检查分为始终执行的确定性检查和可选的模型视觉检查；citationIds 继续提供完整数据血缘，单数 `sourceDatasetId` 明确表示主 Dataset。Reporting no-progress 只把耐久状态变化和成功工具调用视为进展，不把失败回执写入通用 progress entries 当成恢复依据。

**Tech Stack:** Python 3.12、Agno 3.0.0、Pydantic、Pillow、pytest、Loguru。

---

## Scope

- 本轮不修改公共 HTTP API、数据库表、Workflow ID 或纯 Coding Agent。
- 本轮不引入新的图表 DSL，不替换 matplotlib；结构化 `ChartSpec` 服务端渲染另立后续计划。
- 不伪造视觉模型结果。无 vision 时回执必须明确 `inspectionMode=deterministic` 和 `visualReviewStatus=not_run`。
- 当前工作区已有 Section/facts/rework 修复，实施时只追加与本计划直接相关的测试和代码，不回退既有改动。
- 本任务按用户约束不创建 commit；每个任务以定点测试通过作为检查点。

## Capability Matrix

`AGENT_REPORT_ENABLE_VISION` 是本轮唯一 capability 事实源。Worker 创建时将其规范化为受信的
`visualInspectionMode=vision|deterministic`，同时签入 instruction payload、phase contract、
工具投影和最终检查回执。四处必须来自同一个值，禁止分别推断。

| 行为 | Vision enabled | Vision disabled |
|---|---|---|
| Pillow 文件签名、解码、尺寸、空白和宽高比检查 | 必须执行 | 必须执行 |
| `inspect_chart` 工具 | 暴露 | 不暴露 |
| 模型视觉审查 | 必须执行并通过 | 不执行 |
| `register_report_charts` 前置条件 | 当前 SHA-256 的 vision receipt | 当前 SHA-256 的 deterministic receipt |
| `inspectionMode` | `vision` | `deterministic` |
| `visualReviewStatus` | `passed` | `not_run` |
| 审查身份 | `modelId=<真实视觉模型>` | `inspectorId=deterministic-raster-inspector-v1`，`modelId=null` |
| 未执行视觉审查 Warning | 无 | 必须写入 manifest/delivery warnings |
| stale/失败检查回执 | 失败关闭 | 失败关闭 |
| Workflow 是否可完成 | 可以 | 可以，不伪装为 vision passed |

共同不变量：

- 两种模式使用相同的 citation、Dataset、期间、指标、文件路径和 SHA-256 校验。
- 两种模式都不能登记空白、无法解码、路径越界、身份变化或 citation 未注册的图片。
- Vision 模式不能在模型审查不可用时静默退化为 deterministic；本次 Task 以稳定错误码失败，由 fresh retry 恢复。
- Deterministic 模式的 `modelId` 必须为空，只记录稳定 `inspectorId`；不能在用户可见元数据中声称完成视觉审查。
- Capability 在同一个 Task 和 fresh retry 间不可变化；恢复时若签发模式与当前 Worker capability 不一致，以
  `report_visualization_capability_changed` 失败关闭，避免同一 revision 混用两类回执。

## File Map

- `smart_reporting/reporting/agent.py`: no-progress 计数、模型工具批次终止。
- `smart_reporting/reporting/instructions.py`: capability-aware visualization 指令。
- `smart_reporting/reporting/workflow/runtime/analysis.py`: visualization instruction/phase contract 投影。
- `smart_reporting/reporting/workflow/checkpoint.py`: 图表检查回执模式和兼容校验。
- `smart_reporting/reporting/delivery/draft_v1.py`: `sourceDatasetId` 的主 Dataset 语义说明。
- `smart_reporting/reporting/tools/sections.py`: citation 校验、确定性检查回执、视觉回执选择。
- `smart_reporting/reporting/tools/toolkit.py`: visualization 读取边界和工具说明。
- `smart_reporting/reporting/tests/test_reporting_agent_projection.py`: 真实 Agno 批次终止。
- `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`: 图表登记、vision fallback、完整 Toolkit no-progress。
- `smart_reporting/reporting/tests/test_reporting_section_concurrency.py`: visualization fresh retry/checkpoint 回归。

### Task 1: Fix Full-Stack No-Progress Termination

**Files:**
- Modify: `smart_reporting/reporting/agent.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Test: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`

- [ ] **Step 1: Add a failing Toolkit regression test**

  通过真实 `ReportWorkspaceTaskToolkit._invoke` 路径连续提交 8 个不同 `session_id` 的非法 visualization `process(action=submit)`。断言第 8 次抛出 `StopAgentRun`，原始 code 保持 `report_visualization_process_forbidden`，details 包含 `terminalReason=tool_no_progress` 和 `phaseFailureCount=8`。

- [ ] **Step 2: Run the failing test**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest -q \
    smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
    -k 'process and no_progress'
  ```

  Expected: FAIL because generic Coding progress entries change the Reporting progress fingerprint after every rejected call.

- [ ] **Step 3: Make the Reporting progress fingerprint depend only on real progress**

  In `_reporting_progress_fingerprint`, retain the durable mutation sequence and validated agent plan state. Remove failed tool result entries from the fingerprint. Successful Reporting tools already clear `_REPORT_TOOL_FAILURE_STATE_KEY`, so read-only success remains an explicit reset without treating rejected calls as progress.

- [ ] **Step 4: Verify same-error and phase-wide thresholds**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest -q \
    smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
    smart_reporting/reporting/tests/test_reporting_agent_projection.py \
    -k 'no_progress or remaining_batch'
  ```

  Expected: all selected tests pass; the eighth distinct failure prevents later calls in the same Agno batch.

### Task 2: Expose Authoritative Citation Lineage

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/instructions.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] **Step 1: Add a failing instruction projection test**

  Capture the visualization task instruction and assert it contains the compact trusted mapping:

  ```json
  {"citationDatasetIds":{"citation_006":"dataset-current","citation_007":"dataset-yoy"}}
  ```

  Assert the mapping comes from `Citation` bindings and contains no quote, source payload, hash, or business row data.

- [ ] **Step 2: Run the failing test**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest -q \
    smart_reporting/reporting/tests/test_reporting_section_concurrency.py \
    -k 'visualization and citation'
  ```

  Expected: FAIL because the acceptance contract contains the mapping but the model instruction does not.

- [ ] **Step 3: Add the compact mapping to the visualization instruction payload**

  Add `citationDatasetIds` beside `analysisCitationIds`. Update instructions to require exact reuse of this mapping and prohibit querying `datasets[].citationIds` or guessing Dataset ownership.

- [ ] **Step 4: Verify instruction size and secret boundary**

  Assert the task remains below `MAX_REPORT_INSTRUCTION_BYTES` for 100 citations and that only citationId/DatasetId pairs are projected.

### Task 3: Support Cross-Dataset Comparison Charts Without a Schema Migration

**Files:**
- Modify: `smart_reporting/reporting/delivery/draft_v1.py`
- Modify: `smart_reporting/reporting/tools/sections.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] **Step 1: Add failing chart registration tests**

  Cover:

  - current citation belongs to `dataset-current`;
  - comparison citation belongs to `dataset-yoy`;
  - chart declares `sourceDatasetId=dataset-current` as its primary Dataset;
  - registration proceeds to file inspection;
  - a primary Dataset absent from all chart citations is rejected.

- [ ] **Step 2: Run the failing tests**

  Run:

  ```bash
  .venv-agent/bin/python -m pytest -q \
    smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
    -k 'register_report_charts and dataset'
  ```

  Expected: the legitimate comparison chart fails with `report_chart_citation_dataset_mismatch`.

- [ ] **Step 3: Define `sourceDatasetId` as the primary Dataset**

  Keep the existing field for protocol compatibility. Validate that every citation is registered and that the declared primary Dataset appears among the cited Dataset set. Full lineage remains recoverable from `citationIds -> citationDatasetIds`.

- [ ] **Step 4: Return actionable mismatch details**

  Replace the aggregate `any(...)` check with an ordered per-chart check. On failure, include only bounded identifiers:

  ```json
  {
    "chartId":"income_yoy",
    "sourceDatasetId":"dataset-current",
    "citationDatasetIds":["dataset-yoy"]
  }
  ```

  Do not include file contents, facts, quotes, or source rows.

### Task 4: Add Honest Deterministic Inspection for Vision-Disabled Runs

**Files:**
- Modify: `smart_reporting/reporting/workflow/checkpoint.py`
- Modify: `smart_reporting/reporting/tools/sections.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/instructions.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] **Step 1: Add failing receipt compatibility tests**

  Add `inspectionMode: vision | deterministic`、`visualReviewStatus: passed | not_run`、
  `inspectorId`，并把 `modelId` 调整为可空；现有 v2 vision receipts 通过默认值保持兼容。
  Assert deterministic receipts cannot claim a vision model result.

  同时断言以下非法组合被 Pydantic 拒绝：

  - `inspectionMode=vision` 且 `visualReviewStatus=not_run`；
  - `inspectionMode=deterministic` 且 `visualReviewStatus=passed`；
  - deterministic receipt 携带视觉模型 issues/suggestions；
  - vision receipt 缺少非空 `modelId`。

- [ ] **Step 2: Add a failing vision-disabled registration test**

  With `visualInspectionMode=deterministic`, no `chartInspectionReceipts`, and a valid decoded PNG identity, assert registration succeeds with a deterministic receipt containing:

  ```json
  {
    "inspectionMode":"deterministic",
    "inspectorId":"deterministic-raster-inspector-v1",
    "modelId":null,
    "reviewed":true,
    "requiresRevision":false,
    "visualReviewStatus":"not_run"
  }
  ```

  The receipt warning must state that model visual review was not run.

- [ ] **Step 3: Preserve fail-closed vision mode**

  With `visualInspectionMode=vision`, keep requiring a hash-bound `inspect_chart` receipt. Missing, changed, rejected, or critical receipts continue returning the existing stable error codes.

  新增 vision-enabled 正常路径测试：工具工厂必须暴露 `inspect_chart`，通过的 vision receipt 被原样绑定；
  `requiresRevision=true`、critical issue、receipt SHA 不匹配和 reviewer 不可用均不得自动切换到 deterministic。

- [ ] **Step 4: Make instructions capability-aware**

  Project `visualInspectionMode` in both instruction payload and phase contract. In deterministic mode, explicitly forbid `inspect_chart` and say registration performs deterministic file checks. In vision mode, retain the existing inspect-before-register contract.

  增加工具 schema 投影断言，保证模型看到的说明和实际工具集合一致：vision 模式有 `inspect_chart`，
  deterministic 模式没有该工具，也没有“必须先调用 inspect_chart”的静态指令。

- [ ] **Step 5: Verify the manifest remains honest**

  Assert `AnalysisEvidenceManifest` accepts deterministic receipts but preserves `visualReviewStatus=not_run`; downstream delivery warnings must not describe them as model-reviewed.

- [ ] **Step 6: Reject capability drift on fresh retry**

  将 `visualInspectionMode` 持久化在 visualization phase contract/checkpoint 恢复依据中。首次 attempt 为 vision、
  fresh retry 变为 deterministic（以及反向变化）时，断言在任何图表读取或写入前返回
  `report_visualization_capability_changed`。

### Task 5: Close Visualization Exploration Drift

**Files:**
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

- [ ] **Step 1: Add failing direct-evidence-read tests**

  In visualization mode, assert `read_file` rejects durable evidence/facts and only permits the latest committed signed script. `query_analysis_facts` remains the only model-facing facts interface; the signed Python script may read its signed input paths during terminal execution.

- [ ] **Step 2: Align dynamic budgets with the enforced boundary**

  Keep the 512-unit total evidence-size admission gate for script safety, but stop scaling model `read_file` allowance with evidence bytes. Retain a small fixed read allowance for the committed script and bounded tool-output recovery.

- [ ] **Step 3: Verify fresh retry behavior**

  Assert a budget retry reuses the existing script and registered charts, does not reread evidence, and only performs the remaining terminal/register/finalize operations.

### Task 6: Regression and Static Verification

**Files:**
- Verify all modified Python files only.

- [ ] **Step 1: Run focused Reporting tests**

  ```bash
  .venv-agent/bin/python -m pytest -q \
    smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
    smart_reporting/reporting/tests/test_reporting_agent_projection.py \
    smart_reporting/reporting/tests/test_reporting_section_concurrency.py \
    smart_reporting/reporting/tests/test_reporting_state.py \
    smart_reporting/reporting/tests/test_reporting_worker_execution.py \
    smart_reporting/reporting/tests/test_reporting_semantic_contract.py
  ```

  定点集合必须显式包含以下双模式节点：

  - vision enabled：工具暴露、视觉回执通过、视觉回执失败关闭、fresh retry 复用；
  - vision disabled：工具隐藏、确定性登记成功、Warning 保留、fresh retry 复用；
  - capability drift：两个方向均在副作用前失败关闭；
  - 两种模式共同的跨 Dataset citation 和 no-progress 回归。

- [ ] **Step 2: Run formatting, lint, type, and diff checks**

  ```bash
  changed_files=$(git diff --name-only -- '*.py')
  .venv-agent/bin/python -m ruff format --check $changed_files
  .venv-agent/bin/python -m ruff check $changed_files
  .venv-agent/bin/python -m mypy --follow-imports=skip \
    smart_reporting/reporting/agent.py \
    smart_reporting/reporting/instructions.py \
    smart_reporting/reporting/tools/sections.py \
    smart_reporting/reporting/tools/toolkit.py \
    smart_reporting/reporting/workflow/checkpoint.py \
    smart_reporting/reporting/workflow/runtime/analysis.py
  git diff --check
  ```

- [ ] **Step 3: Review final scope**

  Confirm no HTTP schema, database migration, Workflow ID, dependency, pure Coding Agent, `.env`, generated artifact, or repository-local CLI output changed.

### Task 7: Real CLI Acceptance

**Files:**
- Output only under `/tmp/reporting_cli_<timestamp>/`.

- [ ] **Step 1: Run the same hospital report request in deterministic mode**

  使用当前 `AGENT_REPORT_ENABLE_VISION=false` 和 `reporting-cli-acceptance`；不要恢复已取消的 v2 run，
  因为它在 visualization attempt 中途结束。

- [ ] **Step 2: Verify visualization acceptance evidence**

  Confirm:

  - no `inspect_chart` calls when vision is disabled;
  - no direct evidence `read_file` exploration;
  - no repeated `report_chart_citation_dataset_mismatch`;
  - comparison charts retain current and baseline citations;
  - deterministic receipts say `visualReviewStatus=not_run`;
  - no 13-call illegal `process` batch;
  - facts identities remain unchanged;
  - section rework still short-circuits later sections.

- [ ] **Step 3: Archive metrics and terminal artifacts**

  Save `cli.log` and `performance.json`. Download the PDF only if the final trusted receipt is `status=completed` with complete path, size, and SHA-256.

- [ ] **Step 4: Run vision-enabled acceptance when the reviewer is configured**

  在存在可信视觉模型配置且不需要修改或输出密钥时，用相同请求运行第二轮 CLI。确认每张登记图表都有
  `inspectionMode=vision`、`visualReviewStatus=passed` 和匹配当前 SHA-256 的回执，且不存在 deterministic
  fallback Warning。若环境未配置视觉 reviewer，只运行 vision-enabled 契约测试并在交付中明确记录真实 CLI
  未执行原因；不得临时填入弱默认凭据或把 deterministic 结果记作 vision 验收通过。

## Deferred Follow-Up: Server-Rendered ChartSpec

Create a separate design and implementation plan after this recovery is stable. The follow-up should replace arbitrary model-authored matplotlib scripts with a strict `ChartSpec`, resolve series directly from frozen facts, render in a server-owned library, and model multi-Dataset lineage explicitly. It must be introduced as a new persisted protocol version with a defined migration and retirement condition; it is not part of this repair.
