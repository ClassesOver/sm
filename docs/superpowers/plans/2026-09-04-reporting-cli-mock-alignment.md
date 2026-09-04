# Reporting CLI Mock 链路对齐实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让定点 mock 测试真实经过 Reporting CLI、Workflow、任务协调器、阶段 executor 和生产 Toolkit，同时修正 Section 指令与文件读取授权之间的契约矛盾。

**Architecture:** 测试入口使用生产 `parse_report_input()` 与 `drive_workflow()`。为避免完整报表交付的需求澄清、审批和发布依赖，测试提供一个只桥接生产 `ReportingDraftWorkflow` 的最小 Workflow adapter；阶段执行仍调用生产 runtime 的分析、可视化和章节方法，并由 `ReportingTaskCoordinator` 管理租约、attempt、RunContext 与终态。PostgreSQL、Daytona、模型响应和最终发布端口使用独立 fake/mock，权限和状态转换继续由生产实现负责。

**Tech Stack:** Python 3.12、pytest/anyio、Agno 3.0.1、Pydantic、Loguru、现有 `task_execution` 与 `MockReportingToolRuntime`。

---

### Task 1: 修正 Section Agent 指令契约

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_planner_contracts.py`
- Modify: `smart_reporting/reporting/instructions.py:297-314`

- [ ] **Step 1: 写失败测试，锁定事实摘要与证据文件边界**

在现有 planner contract 测试文件中导入 `REPORT_SECTION_AGENT_INSTRUCTIONS`，加入：

```python
def test_section_instructions_match_evidence_file_authorization() -> None:
    instructions = "\n".join(REPORT_SECTION_AGENT_INSTRUCTIONS)

    assert "factSummaries" in instructions
    assert "evidenceFiles" in instructions
    assert "factFiles 仅用于事实身份和追溯元数据" in instructions
    assert "只按 factFiles 定点读取" not in instructions
    assert "补读原始 facts/evidence" not in instructions
```

- [ ] **Step 2: 运行测试确认按预期失败**

运行：

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_planner_contracts.py::test_section_instructions_match_evidence_file_authorization -q
```

预期：FAIL，现有指令仍要求按 `factFiles` 读取并补读原始 facts/evidence。

- [ ] **Step 3: 进行最小指令修改**

把 Section 指令改为：数值事实优先使用内联 `factSummaries`；只有需要证据正文时才使用 `read_file` 读取当前 WorkItem 授权的 `evidenceFiles`；`factFiles` 仅用于事实身份和追溯元数据，不属于 Section 文件读取授权；禁止读取 Dataset 输入、其他章节文件及未列入 `evidenceFiles` 的路径。删除“只按 factFiles 定点读取”和“补读原始 facts/evidence”的原文，不改变工具名、schema 或错误码。

- [ ] **Step 4: 运行定点测试并检查格式**

运行：

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_planner_contracts.py -q
.venv-agent/bin/python -m ruff format --check smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py
.venv-agent/bin/python -m ruff check smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py
```

预期：全部通过。

- [ ] **Step 5: 提交任务 1**

```bash
git add smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py
git commit -m "fix(reporting): align section evidence instructions"
```

### Task 2: 建立 CLI 主链路 mock harness

**Files:**
- Create: `smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py`
- Modify: `smart_reporting/reporting/cli.py` only if the harness exposes a real CLI contract defect

- [ ] **Step 1: 写失败测试，要求输入经过 parse 与 drive**

在新测试文件中创建测试专属 fake repository、workspace、model executor 和 Workflow adapter。adapter 必须是 Agno `Workflow` 形状，`arun()` 接收 CLI 传入的 `report_input`、`run_id`、`session_id`、`user_id`、`session_state`、`dependencies`，构造生产形状 `RunContext`，调用生产 `ReportingDraftWorkflow` 的阶段回调，并返回带 `status/content` 的结果。测试调用：

```python
raw = "生成 2025 年运营报告，重点分析收入同比和区域贡献"
parsed = parse_report_input(raw)
result = await drive_workflow(
    workflow_adapter,
    runtime,
    parsed,
    run_id="cli-run-1",
    session_id="cli-session-1",
    user_id="cli-user-1",
    database="odoo",
    company_id="company-1",
)

assert adapter.received_input == parsed
assert adapter.received_scope == {"externalRunId": "cli-run-1", "threadId": "cli-session-1", "userId": "cli-user-1", "database": "odoo", "companyId": "company-1"}
assert result["status"] == "completed"
assert adapter.production_draft_workflow_called is True
```

adapter 的阶段回调必须进入生产 Reporting runtime 阶段方法及 `ReportingTaskCoordinator` 路径，不能直接把输入改写成成功结果；外部端口仅使用本测试独立 fake。

- [ ] **Step 2: 运行测试确认 harness 尚未存在**

运行：

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py::test_cli_input_reaches_production_draft_workflow -q
```

预期：FAIL，测试文件或 adapter 尚未实现。

- [ ] **Step 3: 实现最小测试 adapter 与独立 fake**

在测试文件内部实现仅供该文件使用的 fake，避免为单一消费者新增共享 support 模块：

1. fake repository 实现 Coordinator 所需的 `create_task_with_initial_attempt`、`get_task_snapshot`、`open_initial`、`resume_current`、`attempt_instruction`、`finalize_finish`、`claim_lease`、`release_lease`，保留 state version、lease epoch 和重复终态检查。
2. 使用 `MockReportingToolRuntime`，输入、数据和输出根目录均为测试内存对象；不接触 SQLite、真实 Daytona 或用户目录。
3. adapter 内构造最小 `ReportingDraftWorkflow`，其 `run_analysis` 调用生产 AnalysisItem executor，`submit_visualization` 和 `draft_section` 调用生产 `ReportingAgentExecutor`；阶段工具通过 `build_reporting_tools()` 生成，测试只记录生产 schema/hooks，不重写权限表。
4. adapter 的 `arun()` 返回 `SimpleNamespace(status="completed", content={"sectionCode": "section-1"})`；提供 `acontinue_run()` 以满足 CLI 协议，但正常闭环不得调用它。
5. 记录 `RunContext.run_id/session_id/user_id/dependencies[TASK_EXECUTION_DEPENDENCY]`，断言三类阶段共用同形 binding。

- [ ] **Step 4: 运行测试并验证真实边界**

运行：

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py -q
```

预期：通过，并且断言 `parse_report_input()`、`drive_workflow()`、Workflow adapter、`ReportingDraftWorkflow`、Coordinator、生产 Toolkit 均被调用。

- [ ] **Step 5: 提交任务 2**

```bash
git add smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py
git commit -m "test(reporting): align mock harness with cli workflow"
```

### Task 3: 覆盖三类 executor、生命周期与重复稳定性

**Files:**
- Modify: `smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py`
- Reuse production code: `smart_reporting/reporting/workflow/execution.py`, `smart_reporting/reporting/workflow/runtime/analysis.py`, `smart_reporting/reporting/workflow/runtime/sections.py`, `smart_reporting/reporting/tools/mock_workspace.py`

- [ ] **Step 1: 先加入失败契约测试**

加入以下独立测试（参数使用本文件的 fixture，测试体必须实现真实调用和断言，不得以 `...` 占位）：

```python
@pytest.mark.anyio
async def test_analysis_executor_never_calls_worker_agent(harness):
    await harness.run_phase("analysis_item")
    harness.worker_agent.arun.assert_not_awaited()
    harness.worker_agent.acontinue_run.assert_not_awaited()

@pytest.mark.anyio
async def test_visualization_and_section_select_reporting_agents(harness):
    await harness.run_phase("visualization_section")
    await harness.run_phase("section")
    assert harness.selected_agent_kinds == ["visualization_section", "section"]

@pytest.mark.anyio
async def test_all_phase_contexts_share_task_execution_binding(harness):
    await harness.run_all_phases()
    assert {item["runId"] for item in harness.context_bindings} == {"cli-run-1"}
    assert {item["sessionId"] for item in harness.context_bindings} == {"cli-session-1"}
    assert all("task_execution" in item["dependencies"] for item in harness.context_bindings)

@pytest.mark.anyio
async def test_background_process_requires_returned_session(harness):
    result = await harness.start_background_process()
    assert result["status"] == "running"
    await harness.send_process_input(result["session_id"], "", submit=True)

@pytest.mark.anyio
async def test_recovery_rejects_changed_signed_script_sha(harness):
    await harness.sign_script()
    await harness.mutate_signed_script()
    with pytest.raises(ReportingError, match="哈希"):
        await harness.recover_script()

@pytest.mark.anyio
async def test_cli_mock_repeated_ten_times_is_deterministic(harness_factory):
    observations = [await harness_factory().run_once() for _ in range(10)]
    assert all(item == observations[0] for item in observations)
```

其中 analysis 测试使用 `AsyncMock` Worker Agent 并断言 `arun` 与 `acontinue_run` 均未调用；visualization/section 断言 `ReportingAgentExecutor` 选择对应 key；重复测试精确执行 10 次，比较每次结果和调用日志且确认 runtime/repository/workspace 不跨次共享。

- [ ] **Step 2: 运行失败测试确认契约能抓到缺口**

运行：

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py -q
```

预期：新增断言至少有一项失败；失败必须来自缺失的生产边界或 Section 指令契约，而不是测试拼写错误。

- [ ] **Step 3: 以最小改动修复生产缺口**

仅在失败明确指向生产实现时修改生产文件；优先修正 adapter 接线或测试 fake。禁止扩大 Section 文件权限、复制状态机、增加 Worker Agent、改变公开工具 schema、错误码、Workflow ID、数据库表或 Daytona 策略。若只需测试调整即可通过，不修改生产代码。

- [ ] **Step 4: 运行 Task 3 定点测试**

运行：

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py -q
.venv-agent/bin/python -m ruff format --check smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py
.venv-agent/bin/python -m ruff check smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py
```

预期：全部通过，重复测试报告 10 次且调用日志无泄漏。

- [ ] **Step 5: 提交任务 3**

```bash
git add smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py smart_reporting/reporting/workflow smart_reporting/reporting/tools
git commit -m "test(reporting): cover phase executors and lifecycle"
```

### Task 4: 全量相关验证与交付检查

**Files:**
- Verify only; no broad cleanup or unrelated formatting

- [ ] **Step 1: 运行 Reporting 非集成回归**

```bash
.venv-agent/bin/python -m pytest smart_reporting/reporting/tests -m 'not integration' -q
```

预期：通过；若有失败，只修复本轮引入的回归。

- [ ] **Step 2: 运行 task_execution 非集成回归**

```bash
.venv-agent/bin/python -m pytest smart_reporting/task_execution/tests -m 'not integration' -q
```

预期：通过，确认 `task_execution` 仍是 Reporting 内部生命周期基础设施。

- [ ] **Step 3: 运行静态检查**

```bash
.venv-agent/bin/python -m ruff format --check smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py
.venv-agent/bin/python -m ruff check smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/test_reporting_planner_contracts.py smart_reporting/reporting/tests/test_reporting_cli_mock_alignment.py
.venv-agent/bin/python -m mypy smart_reporting/reporting/cli.py smart_reporting/reporting/workflow/execution.py smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/sections.py
git diff --check
```

- [ ] **Step 4: 检查旧命名与产物边界**

运行：

```bash
rg -n "Code Worker|CodingExecution|CodingRepository|CodingScope|CodingTask|CodingAnalysisAndDraftWorkflow" smart_reporting scripts docs
git status --short
```

只允许既有数据库兼容标识和 `artifacts_v1.codingTaskKey` 出现在明确 allowlist；不得提交 `/tmp` 之外的测试产物、日志、密钥或缓存。

- [ ] **Step 5: 交付报告**

说明实际修改文件、实际执行命令及结果、未执行项目与原因；明确 `task_execution` 未废弃，仍是中立内部执行基础设施。真实模型十场景探针作为后续优化轮次，不冒充本轮 CLI mock 闭环验收结果。
