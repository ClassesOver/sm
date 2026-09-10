# Reporting Coding Agent Script Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将分析项补证和可视化的 Python 生成从结构化 JSON 字段迁移到受控 Coding Agent patch 流程，同时保留固定 Workflow、内部 CAS、有界修复和 durable 恢复。

**Architecture:** 结构化 Agent 只生成 `AnalysisEvidenceDecision` 或 `VisualizationPlanDraft`；无 `output_schema` 的代码 Agent 通过受控工具阶段创建或修复唯一签发脚本；Reporting Toolkit 在真实 Workspace mutation 前验证临时候选，固定 Workflow 随后执行、验收和提交。模型可见的 `apply_analysis_patch` 只有 `patch` 参数，服务端从实际基线自动派生并在写锁内复核 SHA。

**Tech Stack:** Python 3.12、Agno 3.0.1、Pydantic v2、Loguru、pytest、unified diff、临时 Git tree、Daytona `WorkspaceService`

**Spec:** `docs/superpowers/specs/2026-09-09-reporting-coding-agent-script-generation-design.md`

## Global Constraints

- 业务语义校验只产生软告警；不得把补证业务差异升级为硬失败。
- 应用日志只使用 loguru，且不得记录或回显完整 Python 源码。
- 不运行或重复完整测试套件；每个任务只运行列出的定点测试，集成阶段统一运行一次相关集合。
- 分析脚本最大 128 KiB；可视化脚本最大 64 KiB；任一 UTF-8 物理行最大 8 KiB。
- 初次代码生成只暴露 `apply_analysis_patch`；修复严格按只读 `read_file`、只写 `apply_analysis_patch` 两阶段执行。
- 代码 Agent 不设置 `output_schema`，不接受普通文本、Markdown code fence 或直接 Python 输出作为成功。
- `run_python_script`、`inspect_chart`、`submit_visualization_charts`、`complete_analysis_item` 只由固定 Workflow 调用。
- 不保留 `AnalysisScriptDraft.script`、`VisualizationScriptDraft.pythonSource` 或其他长源码 JSON fallback。
- 模型工具协议不包含 `expected_sha256`；内部 before/after SHA、workspace lock 和 durable write intent 必须保留。

## Parallel Execution Layout

- Wave 1 并行：Task 1（patch/CAS/源码门禁）和 Task 2（Coding Agent 执行器）。两者文件不重叠。
- Wave 2 并行：Task 3（分析项 Workflow）和 Task 4（可视化 Workflow），都基于合并后的 Wave 1。
- Task 3 与 Task 4 都可能修改 `runtime/analysis.py`；各自在独立 worktree 提交，主 Agent 合并时只在该文件做契约级冲突解决。
- Wave 3：Task 5 由主 Agent 完成装配清理、probe 更新和一次相关测试集合验证。
- 每个 worktree 从当时主分支 HEAD 新建，不复用仓库中已有的历史 worktree。

---

### Task 1: Patch-Only Tool Contract, Internal CAS, and Pre-Mutation Source Gate

**Files:**
- Modify: `smart_reporting/reporting/tools/validation.py`
- Modify: `smart_reporting/task_execution/tools.py`
- Modify: `smart_reporting/reporting/tools/analysis_item.py`
- Modify: `smart_reporting/reporting/tools/toolkit.py`
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`
- Test: `smart_reporting/reporting/tests/test_reporting_workspace_port.py`
- Test: `smart_reporting/task_execution/tests/test_git_patch_kernel.py`

**Interfaces:**
- Consumes: 现有 `parse_unified_diff()`、临时 Git tree、`WorkspaceService.aapply_changes()`、Reporting task acceptance contract。
- Produces: `analysis_patch_parameters()` 仅接受 `{"patch": string}`；`abuild_workspace_changes(service, thread, patch)` 自动派生 update/delete 的内部 `expected_sha256`；`RuntimeAnalysisMixin.apply_analysis_patch(patch, run_context=None)`；统一源码门禁错误 `report_python_source_shape_invalid`。

- [ ] **Step 1: 写模型可见 schema 和函数签名的失败测试**

在 `test_reporting_tool_contracts.py` 断言 `analysis_patch_parameters()` 的 properties 只有
`patch`，`expected_sha256` 触发 additionalProperties 拒绝；用 `inspect.signature()` 断言
`ReportingToolkit.apply_analysis_patch` 不再暴露 `expected_sha256`。

- [ ] **Step 2: 写内部 CAS 的失败测试**

在 `test_git_patch_kernel.py` 改写旧 hash 参数测试：不向 `abuild_workspace_changes()` 传 hash，断言
返回的 update operation 包含从当前文件派生的 `expected_sha256`。在 build 和
`aapply_changes()` 之间改变文件，断言提交阶段仍抛 `WorkspacePathConflict` 且不会覆盖并发内容。

- [ ] **Step 3: 写源码门禁的边界失败测试**

在 `test_reporting_workspace_port.py` 覆盖：分析 128 KiB 边界、可视化 64 KiB 边界、8 KiB 物理行
边界、单行 262140 列、非法语法、非 LF/缺少末尾换行、非签发路径和大块 literal 数据。失败断言：

```python
assert error.code == "report_python_source_shape_invalid"
assert error.details == {
    "path": expected_path,
    "size": expected_size,
    "lineCount": expected_lines,
    "maxLineLength": expected_max_line,
}
```

并断言 `workspace.aapply_changes` 与 durable `record_write_intent` 均未调用。

- [ ] **Step 4: 运行新增测试确认失败**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/task_execution/tests/test_git_patch_kernel.py smart_reporting/reporting/tests/test_reporting_workspace_port.py -q`

Expected: 只因 `expected_sha256` 仍公开、缺少统一门禁或旧签名而失败。

- [ ] **Step 5: 实现 patch-only schema 和自动基线 SHA**

删除 `analysis_patch_parameters()` 的 `expected_sha256`；把
`build_workspace_changes/abuild_workspace_changes` 的公开签名收窄为 `(service, thread, patch)`；保留
`_build_changes_from_originals()` 为 update/delete operation 写入内部 `expected_sha256`，供
`WorkspaceService.aapply_changes()` 在锁内复核。删除只验证模型 hash 的
`_validate_original_hash()` 分支，不删除 Workspace change schema 内部 hash 字段。

- [ ] **Step 6: 实现统一候选源码门禁**

在 `analysis_item.py` 把 `_preflight_analysis_python_write()` 收敛为签发脚本专用验证：统一规范并验证
UTF-8 文本、LF 与末尾换行、唯一精确路径、多行结构、文件/行长限制、`ast.parse`、`compile`，并
复用现有可视化 AST 策略。对 bytes、大型字符串或大型纯 literal collection 拒绝直接嵌入的数据；
正常列名、标签、格式字符串等小型常量继续允许。所有形状失败只返回短 details，不附源码。

- [ ] **Step 7: 保持 durable CAS 顺序**

先在临时 tree 构造并校验候选，再生成包含内部 before/after identity 的 write intent，最后调用
`aapply_changes()`。已提交和 pending intent 的恢复逻辑保持不变；冲突回执改为要求重新读取后 fresh
retry，不再要求模型回传 SHA。

- [ ] **Step 8: 运行 Task 1 定点测试**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/task_execution/tests/test_git_patch_kernel.py smart_reporting/reporting/tests/test_reporting_workspace_port.py -q`

Expected: PASS。

- [ ] **Step 9: 提交 Task 1**

```bash
git add smart_reporting/reporting/tools/validation.py smart_reporting/task_execution/tools.py smart_reporting/reporting/tools/analysis_item.py smart_reporting/reporting/tools/toolkit.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py smart_reporting/reporting/tests/test_reporting_workspace_port.py smart_reporting/task_execution/tests/test_git_patch_kernel.py
git commit -m "refactor: internalize reporting patch concurrency"
```

---

### Task 2: Dedicated Coding Agent and Two-Stage Repair Runner

**Files:**
- Create: `smart_reporting/reporting/workflow/runtime/code_generation.py`
- Modify: `smart_reporting/reporting/agent.py`
- Test: `smart_reporting/reporting/tests/test_reporting_generator_agent.py`
- Test: `smart_reporting/reporting/tests/test_reporting_patch_termination.py`
- Create: `smart_reporting/reporting/tests/test_reporting_code_generation.py`

**Interfaces:**
- Consumes: Agno `Agent`/`Function`, `RunContext`, task-scoped `read_file` and `apply_analysis_patch` callables。
- Produces: `create_reporting_code_agent(*, model, name, role, instructions) -> Agent`；`CodeGenerationResult(script_file: FileIdentity)`；`ReportingCodeGenerationRunner.generate(...)` 和 `.repair(...)`。

- [ ] **Step 1: 写代码 Agent 构造失败测试**

断言 `create_reporting_code_agent` 返回的 Agent 满足：`output_schema is None`、
`parse_response is False`、`structured_outputs is False`、`tools == []`、`retries == 0`、无会话历史；其
基础提示明确普通文本不算成功、只允许签发脚本和 unified diff。

- [ ] **Step 2: 写初次生成 runner 失败测试**

使用 fake Agent/工具回调覆盖：只有 `apply_analysis_patch` 可见且使用 named tool choice；成功 patch
立即停止并返回唯一 `FileIdentity`；纯文本、零调用、两次 patch、失败回执、两个 artifacts、错误路径
都抛稳定 `ReportingError`，且每轮写入次数不超过一。

- [ ] **Step 3: 写修复 runner 两阶段失败测试**

断言 `repair()` 第一次模型调用只装配 `read_file`，参数路径必须严格等于签发脚本；第二次使用 fresh
Agent 上下文，只装配并强制 `apply_analysis_patch`，请求包含受限 read receipt 和短诊断。第一阶段
普通文本/错路径/重复读取、第二阶段无 patch/直接输出源码均失败。

- [ ] **Step 4: 写 malformed tool JSON 和 fresh retry 测试**

让 fake Agent 返回工具参数截断与无工具调用，断言 runner 不触发 mutation，并返回可供上层启动
fresh Coding Agent 的稳定错误；错误 details 不包含原始完整参数或源码。

- [ ] **Step 5: 运行新增测试确认失败**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_patch_termination.py smart_reporting/reporting/tests/test_reporting_code_generation.py -q`

Expected: FAIL，因为 factory/runner 尚不存在。

- [ ] **Step 6: 实现 `create_reporting_code_agent`**

从 Reporting 模型复制配置，但不安装结构化 parser；关闭 output schema、JSON mode、Markdown、历史和
Agent 内部盲重试。Runner 每阶段在 Agent 副本上绑定唯一工具和 named tool choice，工具 wrapper
记录调用次数/回执并设置成功后停止，不解析 `RunOutput.content` 为源码。

- [ ] **Step 7: 实现 generate/repair 协议**

`generate()` 接收签发路径、任务事实和 patch callable，只运行一次写阶段；`repair()` 先运行只读阶段，
校验 read receipt 的 path/sha/分页完整性，再把内容和短诊断交给 fresh 写阶段。两个入口只以唯一成功
patch 回执结束；`run_python_script` 不进入任何工具列表。

- [ ] **Step 8: 运行 Task 2 定点测试**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_patch_termination.py smart_reporting/reporting/tests/test_reporting_code_generation.py -q`

Expected: PASS。

- [ ] **Step 9: 提交 Task 2**

```bash
git add smart_reporting/reporting/agent.py smart_reporting/reporting/workflow/runtime/code_generation.py smart_reporting/reporting/tests/test_reporting_generator_agent.py smart_reporting/reporting/tests/test_reporting_patch_termination.py smart_reporting/reporting/tests/test_reporting_code_generation.py
git commit -m "feat: add reporting coding-agent runner"
```

---

### Task 3: Analysis Item Code Generation Workflow

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/base.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Test: `smart_reporting/reporting/tests/test_analysis_item_workflow.py`
- Test: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`

**Interfaces:**
- Consumes: Task 2 `ReportingCodeGenerationRunner`、`create_reporting_code_agent`，Task 1 patch-only toolkit。
- Produces: `AnalysisItemWorkflow` 依赖 `decide_evidence`、`generate_script`、`repair_script`、`run_script`、`complete`；结构化 schema 只保留 `AnalysisEvidenceDecision` 和 `AnalysisSummaryDraft`。

- [ ] **Step 1: 改写分析项测试为无源码决策**

删除测试中的 `AnalysisEvidencePlan.script` 和 `AnalysisScriptDraft`。facts 足够时断言不调用
generate/repair/run；facts 不足时断言顺序为
`decision -> generate patch -> run -> evidence validate -> summary -> complete`。

- [ ] **Step 2: 写修复和降级失败测试**

用 mock runner 断言运行失败或 evidence 结构失败后调用 `repair_script`，最多两次；修复输入保留原始
`missingFacts` 和当前签发路径。三次执行仍失败时继续使用 deterministic facts、记录
`report_analysis_supplement_abandoned` 软告警并完成分析项。

- [ ] **Step 3: 写工具所有权测试**

断言分析代码 Agent 永远不接收 `run_python_script` 或 `complete_analysis_item`；固定 Workflow 只用
签发的 `supplement.py` 调用 runner，并拒绝非唯一/非签发 `FileIdentity`。

- [ ] **Step 4: 运行分析项测试确认失败**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py -q`

Expected: FAIL，因为 Workflow 仍依赖脚本型计划。

- [ ] **Step 5: 简化 `analysis_item_workflow.py` 状态和回调**

删除 `_script_patch()`、`AnalysisEvidencePlan`、`AnalysisScriptDraft` 和 `plan.script` 状态。初始阶段只
保存 `AnalysisEvidenceDecision`；需要补证时调用 `generate_script`，失败或验收错误调用
`repair_script`。Workflow 仍负责 evidence 分页读取、Pydantic 校验、summary 和终态提交。

- [ ] **Step 6: 改造 runtime Agent 装配**

`base.py` 保留 `_analysis_evidence_agent` 的结构化决策，删除结构化 `_analysis_script_agent`，改为
Task 2 factory 创建无 schema 的分析代码 Agent。`analysis.py` 删除 `AnalysisEvidencePlan` 拼装和
`previousScript` JSON 路径，分别把初次与修复请求交给 code runner；运行仍由
`toolkit.run_python_script` 回调执行。

- [ ] **Step 7: 保持 retry/thinking/durable 语义**

初次或 mutation 前失败使用 fresh generate retry；已有脚本后的运行/evidence 失败使用两阶段修复。
保留 `MAX_ANALYSIS_SCRIPT_REPAIRS = 2`、原有 thinking 升级、阶段 loguru 日志、完成 payload 和
durable completion recovery。

- [ ] **Step 8: 运行 Task 3 定点测试**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py -q`

Expected: PASS。

- [ ] **Step 9: 提交 Task 3**

```bash
git add smart_reporting/reporting/workflow/runtime/analysis_item_workflow.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/test_analysis_item_workflow.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py
git commit -m "refactor: generate analysis scripts through patches"
```

---

### Task 4: Visualization Plan and Coding Agent Workflow

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/phase_models.py`
- Modify: `smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py`
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`
- Modify: `smart_reporting/reporting/bootstrap.py`
- Test: `smart_reporting/reporting/tests/test_reporting_phase_models.py`
- Test: `smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py`
- Test: `smart_reporting/reporting/tests/test_reporting_generator_agent.py`

**Interfaces:**
- Consumes: Task 2 `ReportingCodeGenerationRunner`、Task 1 patch-only toolkit、现有 `ChartDraft`/图表检查与提交回调。
- Produces: `VisualizationPlanDraft(charts, warnings)`；`VisualizationSectionWorkflow(generate_plan, generate_script, repair_script, execute_script, inspect_chart, submit)`。

- [ ] **Step 1: 写无源码可视化 schema 失败测试**

断言 `VisualizationPlanDraft` 接受 `charts/warnings`，拒绝 `scriptPath`、`pythonSource` 和空字段外
extras；保留全部 `ChartDraft` 路径、引用、期间和中文元数据验证。

- [ ] **Step 2: 改写固定 Workflow 顺序测试**

有图时断言顺序：`generate_plan -> generate_script -> execute fixed charts.py -> inspect/deterministic -> submit`；
`charts=()` 时直接 submit 零图，generate_script、execute、inspect 均不调用。

- [ ] **Step 3: 写一次修复和冻结计划测试**

脚本失败、缺图、确定性/视觉检查失败时只调用一次 `repair_script`，随后重走 execute/inspect/submit；
修复前后使用同一个 `VisualizationPlanDraft`，不得增删 charts 或改变引用元数据。不可恢复错误仍直接
抛出。

- [ ] **Step 4: 运行可视化测试确认失败**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_reporting_phase_models.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_generator_agent.py -q`

Expected: FAIL，因为 schema/Workflow 仍承载源码。

- [ ] **Step 5: 用 `VisualizationPlanDraft` 替换脚本草案**

从 `phase_models.py` 删除 `VisualizationScriptDraft.script_path/python_source` 及字段级 AST 校验；保留并
迁移可视化 Python AST 策略给 Task 1 候选文件门禁。更新 exports 和所有结构化执行器测试，使业务
生成器只返回 charts/warnings。

- [ ] **Step 6: 改造可视化固定 Workflow**

Workflow 先获取并冻结 plan；空 charts 调用 `submit(plan, ...)` 后结束。有图时通过 code runner 写入
Workflow 签发的 `charts.py`，固定执行，验证计划图片，检查并提交。失败诊断只携带 code/details 和
缺失 chart identity；已有脚本时走两阶段 repair，一次后仍失败则章节失败。

- [ ] **Step 7: 更新 runtime/bootstrap 装配**

`bootstrap.py` 的 visualization generator/recovery 不再使用 `VisualizationScriptDraft`；结构化生成器
只创建 plan，另装配无 schema visualization code Agent。`analysis.py` 删除 source-to-diff 的
`write_script()` 和 `expected_sha256`，把签发路径、facts、plan、toolkit callbacks 传给 code runner。

- [ ] **Step 8: 运行 Task 4 定点测试**

Run:
`./.venv/bin/pytest smart_reporting/reporting/tests/test_reporting_phase_models.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_generator_agent.py -q`

Expected: PASS。

- [ ] **Step 9: 提交 Task 4**

```bash
git add smart_reporting/reporting/workflow/runtime/phase_models.py smart_reporting/reporting/workflow/runtime/visualization_section_workflow.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests/test_reporting_phase_models.py smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py smart_reporting/reporting/tests/test_reporting_generator_agent.py
git commit -m "refactor: generate visualization scripts through patches"
```

---

### Task 5: Integration Cleanup, Probes, and Focused Verification

**Files:**
- Modify: `smart_reporting/reporting/instructions.py`
- Modify: `smart_reporting/reporting/agent.py`
- Modify: `smart_reporting/reporting/phase.py`
- Modify: `smart_reporting/reporting/tools/capabilities.py`
- Modify: `scripts/probe_reporting_patch_agent.py`
- Modify: `scripts/probe_reporting_tools_agent.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_structured_executor.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py`
- Modify: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`

**Interfaces:**
- Consumes: Tasks 1-4 merged contracts。
- Produces: 无旧源码 schema、无模型 hash 参数、无自由执行/提交工具投影消费者的完整 Reporting runtime。

- [ ] **Step 1: 合并并核对 Wave 2 的 `analysis.py` 冲突**

保留两个流程共同需要的 imports/constructor fields；不得恢复任何 `pythonSource`、`script` 或
source-to-diff 逻辑。运行 `python -m compileall` 前先用 `rg` 检查不存在半合并符号。

- [ ] **Step 2: 写旧协议清理失败测试**

更新 agent projection、planner contracts、structured executor 和 CLI mock alignment 测试，断言：
结构化 Agent 无源码字段；code Agent 各阶段只见允许工具；所有模型可见 patch schema/说明无
`expected_sha256`；Workflow 而非模型调用执行、检查和提交工具。

- [ ] **Step 3: 删除旧提示和动态工具编排**

从 `instructions.py`、`agent.py`、`phase.py`、`capabilities.py` 删除只服务于旧 visualization
`patch -> run -> inspect -> submit` Agent 的状态投影、nextTool/requiredFields hash 提示和自由编排
文本。先用 `rg` 确认真实消费者；仍被其他 Reporting task 使用的通用能力只收窄说明，不删除。

- [ ] **Step 4: 更新 probes**

`probe_reporting_patch_agent.py` 只发送 `patch`，不模拟 hash。`probe_reporting_tools_agent.py` 分别覆盖
分析初次/修复和可视化初次/修复：初次只 patch，修复 read 后 patch，成功后模型调用结束；普通文本
和直接 Python 输出计为失败。

- [ ] **Step 5: 静态残留检查**

Run:

```bash
rg -n "AnalysisScriptDraft|AnalysisEvidencePlan|VisualizationScriptDraft|pythonSource|previousScript" smart_reporting scripts
rg -n "expected_sha256" smart_reporting/reporting scripts/probe_reporting_patch_agent.py scripts/probe_reporting_tools_agent.py
```

Expected: 第一组无运行时消费者；第二组只允许内部 Workspace/CAS、非模型协议或无关发布代码引用。

- [ ] **Step 6: 运行一次相关测试集合**

Run:

```bash
./.venv/bin/pytest \
  smart_reporting/task_execution/tests/test_git_patch_kernel.py \
  smart_reporting/reporting/tests/test_reporting_workspace_port.py \
  smart_reporting/reporting/tests/test_reporting_tool_contracts.py \
  smart_reporting/reporting/tests/test_reporting_code_generation.py \
  smart_reporting/reporting/tests/test_analysis_item_workflow.py \
  smart_reporting/reporting/tests/test_reporting_phase_models.py \
  smart_reporting/reporting/tests/test_reporting_fixed_phase_workflows.py \
  smart_reporting/reporting/tests/test_reporting_generator_agent.py \
  smart_reporting/reporting/tests/test_reporting_agent_projection.py \
  smart_reporting/reporting/tests/test_reporting_planner_contracts.py \
  smart_reporting/reporting/tests/test_reporting_patch_termination.py \
  smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py -q
```

Expected: PASS；不要再次运行该完整相关集合。

- [ ] **Step 7: 运行静态验证**

Run:

```bash
./.venv/bin/ruff check smart_reporting/reporting smart_reporting/task_execution scripts/probe_reporting_patch_agent.py scripts/probe_reporting_tools_agent.py
./.venv/bin/python -m compileall -q smart_reporting/reporting smart_reporting/task_execution scripts
git diff --check
```

Expected: 全部 exit 0。

- [ ] **Step 8: 运行真实模型 probe 一次**

按脚本现有 CLI 参数分别执行分析和可视化代表场景；记录 tool call 顺序、patch 物理行数、文件大小、
是否出现普通文本成功误判。外部模型不可用时明确报告，不能用 mock 结果冒充。

- [ ] **Step 9: 提交集成清理**

```bash
git add smart_reporting scripts
git commit -m "refactor: complete reporting coding-agent migration"
```
