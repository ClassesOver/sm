# 可视化阶段按章节并行化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Reporting 可视化阶段从单个串行 worker 重构为"按提纲章节并行的图表 worker + 串行汇总 worker",消除 64K 长生成恶性循环与 WorkspaceError 炸 run。

**Architecture:** 新增两个 taskKind(`visualization_section`/`visualization_finalize`)贯穿协议全链路(类型/解析/能力矩阵/终态工具/恢复指令/限额);章节 worker 图表输出按 `{sectionCode}/attempt-{n}/` 隔离,durable reducer 新增按章提交分支;checkpoint 失败账本从标量 lastError 升级为按章 dict;旧 in-flight visualization task 废弃并从 durable facts 重建。

**Tech Stack:** Python 3.12、Agno 3.0.0、Pydantic v2 StrictModel、asyncio Semaphore+TaskGroup、PostgreSQL durable state。

**Spec:** `docs/superpowers/specs/2026-08-31-reporting-visualization-parallelization-design.md`

## Global Constraints

- 交付说明、用户可见文案、新增业务注释使用中文;协议字段、错误码、日志事件名用英文。
- `register_report_charts` 的整批注册语义、durable 幂等键 `charts:{digest}`、`_finalize_reporting_sections` 消费逻辑、`SectionWorkItem.charts` 派生**不变**。
- 错误码只增不改;`report_chart_file_missing`、`report_visualization_section_conflict` 为新增稳定英文标识。
- checkpoint Literal 只增值不改值;`visualization` 值保留用于历史 trace 校验,但不再新发起该类任务。
- 单章输出限额 16K(`_REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT = 16 * 1024`),汇总沿用 64K。
- 并发配置 `AGENT_REPORT_VISUALIZATION_CONCURRENCY` 默认 1、上限 4,与 `analysis_concurrency` 完全同构。
- 每个 Task 完成后运行定点 pytest + Ruff format/lint;Mypy 覆盖改动文件。测试不访问真实网络;PostgreSQL 场景标记 integration(本计划不需要)。
- 提交信息格式与仓库现有风格一致(feat:/fix: 前缀 + 中文摘要)。不提交临时产物。

---

### Task 1: checkpoint Schema 升级(workKind 枚举 + 章节失败账本)

**Files:**
- Modify: `smart_reporting/reporting/workflow/checkpoint.py:617-624`(`CheckpointError`)、`:630-637`(`ContextTrace`)、`ReportingCheckpoint` 类定义区
- Test: `smart_reporting/reporting/tests/test_reporting_state.py`(新增测试函数)

**Interfaces:**
- Produces: `CheckpointError.work_kind`/`ContextTrace.work_kind` 的 Literal 含 `visualization_section`、`visualization_finalize`;`ReportingCheckpoint.visualization_section_errors: dict[str, CheckpointError]`(默认 `{}`,alias `visualizationSectionErrors`);merge 侧按 sectionCode 键合并。

- [ ] **Step 1: 写失败测试**

```python
def test_checkpoint_error_accepts_visualization_section_work_kind() -> None:
    # 章节身份写入 sectionCode,analysisId 保持 analysis_NNN pattern 不变
    error = CheckpointError.model_validate(
        {
            "phase": "analysis",
            "code": "report_analysis_phase_failed",
            "message": "章节图表 worker 失败。",
            "workKind": "visualization_section",
            "sectionCode": "section_001",
        }
    )
    assert error.work_kind == "visualization_section"
    assert error.section_code == "section_001"
    assert error.analysis_id is None


def test_checkpoint_error_rejects_section_code_in_analysis_id() -> None:
    with pytest.raises(ValidationError):
        CheckpointError.model_validate(
            {
                "phase": "analysis",
                "code": "x",
                "message": "m",
                "workKind": "visualization_section",
                "analysisId": "section_001",
            }
        )


def test_checkpoint_error_accepts_visualization_finalize() -> None:
    error = CheckpointError.model_validate(
        {"phase": "analysis", "code": "x", "message": "m", "workKind": "visualization_finalize"}
    )
    assert error.work_kind == "visualization_finalize"


def test_context_trace_accepts_new_work_kinds() -> None:
    trace = ContextTrace.model_validate(
        {
            "phase": "analysis",
            "workKind": "visualization_section",
            "sectionCode": "section_001",
            "attempt": 0,
        }
    )
    assert trace.work_kind == "visualization_section"
    finalize = ContextTrace.model_validate(
        {"phase": "analysis", "workKind": "visualization_finalize", "attempt": 0}
    )
    assert finalize.work_kind == "visualization_finalize"


def test_checkpoint_visualization_section_errors_default_empty() -> None:
    checkpoint = ReportingCheckpoint.model_validate({"phase": "analysis", "revision": 1})
    assert checkpoint.visualization_section_errors == {}
    # 历史 checkpoint(无该字段)反序列化后必须仍是合法模型
    payload = checkpoint.model_dump(mode="json", by_alias=True)
    payload.pop("visualizationSectionErrors")
    assert ReportingCheckpoint.model_validate(payload).visualization_section_errors == {}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_state.py -k "visualization_section or visualization_finalize" -v`
Expected: FAIL(pydantic ValidationError,Literal 不含新值/字段不存在)

- [ ] **Step 3: 最小实现**

在 `checkpoint.py` 中:

1. `CheckpointError.work_kind` 与 `ContextTrace.work_kind` 的 Literal 改为:
   `Literal["analysis_item", "visualization", "visualization_section", "visualization_finalize", "section", "finalize"]`
2. `ReportingCheckpoint` 新增字段(放在 `last_error` 相邻位置):

```python
    # 按章保存 visualization_section 失败与预算账本;并发合并时按键合并,
    # 不复用标量 last_error(后者保留给汇总 worker 的全局终态失败)。
    visualization_section_errors: dict[str, CheckpointError] = Field(
        default_factory=dict, alias="visualizationSectionErrors", max_length=200
    )
```

- [ ] **Step 4: 运行测试确认通过 + 现有回归**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_state.py -q`
Expected: PASS(含既有用例)

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/workflow/checkpoint.py smart_reporting/reporting/tests/test_reporting_state.py
git commit -m "feat: checkpoint 支持 visualization_section/finalize workKind 与按章失败账本"
```

---

### Task 2: taskKind 类型与解析层(协议矩阵前三行)

**Files:**
- Modify: `smart_reporting/reporting/phase.py:16`(`ReportingTaskKind`)、`:218`(`reporting_task_kind_from_acceptance_contract`)、`:585`(`reporting_task_kind_from_run_context`)
- Test: `smart_reporting/reporting/tests/test_reporting_agent_projection.py`(新增解析测试)

**Interfaces:**
- Produces: `ReportingTaskKind = Literal["analysis_item", "visualization", "visualization_section", "visualization_finalize", "section"]`;两个解析函数对新 kind 返回非 None,对未知值仍返回 None。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.parametrize(
    ("task_kind",),
    [
        ("visualization_section",),
        ("visualization_finalize",),
    ],
)
def test_reporting_task_kind_from_acceptance_contract_accepts_new_kinds(
    task_kind: str,
) -> None:
    contract = {
        "requirements": [
            {
                "parameters": {
                    "phase": "analysis",
                    "phaseContract": {"taskKind": task_kind},
                }
            }
        ]
    }
    assert reporting_task_kind_from_acceptance_contract(contract) == task_kind


@pytest.mark.parametrize(
    ("task_kind",),
    [
        ("visualization_section",),
        ("visualization_finalize",),
    ],
)
def test_reporting_task_kind_from_run_context_accepts_new_kinds(task_kind: str) -> None:
    run_context = make_run_context(
        dependencies={REPORTING_TASK_DEPENDENCY: {REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind}}
    )
    assert reporting_task_kind_from_run_context(run_context) == task_kind
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_agent_projection.py -k "accepts_new_kinds" -v`
Expected: FAIL(返回 None,断言不等)

- [ ] **Step 3: 最小实现**

`phase.py` 三处白名单/Literal 同步加 `"visualization_section", "visualization_finalize"`:

```python
ReportingTaskKind = Literal[
    "analysis_item",
    "visualization",
    "visualization_section",
    "visualization_finalize",
    "section",
]
```

两个解析函数末行 `task_kind if task_kind in {...}` 的集合同步加两值。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_agent_projection.py -k "task_kind" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/phase.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
git commit -m "feat: ReportingTaskKind 新增 visualization_section/finalize 并贯通解析层"
```

---

### Task 3: 输出限额分支与能力矩阵

**Files:**
- Modify: `smart_reporting/reporting/agent.py:160-162`(常量)、`:2217-2232`(`_phase_request_model`)
- Modify: `smart_reporting/reporting/tools/capabilities.py`(两个新 frozenset + `tools_for_task` 分支)
- Test: `smart_reporting/reporting/tests/test_reporting_agent_projection.py:2954-2989`(参数化表扩展)

**Interfaces:**
- Consumes: Task 2 的 `ReportingTaskKind`。
- Produces: `_REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT: Final[int] = 16 * 1024`;`_phase_request_model` 对 `visualization_section` 返回 max_tokens=16384、`visualization_finalize` 返回 65536、`visualization` 分支删除;`REPORTING_VISUALIZATION_SECTION_TOOL_NAMES`、`REPORTING_VISUALIZATION_FINALIZE_TOOL_NAMES` 两个 frozenset;`tools_for_task` 两分支。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.parametrize(
    ("phase", "task_kind", "expected_max_tokens"),
    [
        ("analysis", "analysis_item", 16_384),
        ("analysis", "visualization_section", 16_384),
        ("analysis", "visualization_finalize", 65_536),
        ("analysis", "section", 16_384),
    ],
)
def test_reporting_worker_applies_phase_output_token_limits(
    phase: str,
    task_kind: str,
    expected_max_tokens: int,
) -> None:
    # 复用本文件现有 test_reporting_worker_applies_phase_output_token_limits 的
    # fixture 构造方式(ReportingOpenAIChat 实例 + run_context 依赖注入),
    # 断言 request_model.max_tokens == expected_max_tokens 且共享模型 max_tokens 不变。
    ...


def test_tools_for_task_visualization_section() -> None:
    names = tools_for_task("analysis", "visualization_section")
    assert names is not None
    assert "submit_visualization_charts" in names
    assert "write_analysis_files" in names
    assert "terminal" in names
    assert "register_report_charts" not in names
    assert "finalize_report_analysis" not in names


def test_tools_for_task_visualization_finalize() -> None:
    names = tools_for_task("analysis", "visualization_finalize")
    assert names is not None
    assert "register_report_charts" in names
    assert "finalize_report_analysis" in names
    assert "submit_visualization_charts" not in names
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_agent_projection.py -k "token_limits or tools_for_task" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现**

`agent.py`:

```python
_REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT = 16 * 1024
```

`_phase_request_model` 的分支:

```python
        if task_kind == "analysis_item":
            output_limit = _REPORT_ANALYSIS_ITEM_OUTPUT_TOKEN_LIMIT
        elif task_kind == "visualization_section":
            output_limit = _REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT
        elif task_kind == "visualization_finalize":
            output_limit = _REPORT_VISUALIZATION_OUTPUT_TOKEN_LIMIT
        elif task_kind == "section":
            output_limit = _REPORT_SECTION_OUTPUT_TOKEN_LIMIT
        else:
            output_limit = None
```

`capabilities.py`:

```python
REPORTING_VISUALIZATION_SECTION_TOOL_NAMES = frozenset(
    {
        "get_skill_instructions",
        "get_skill_reference",
        "inspect_chart",
        "process",
        "read_file",
        "read_tool_output",
        "submit_visualization_charts",
        "terminal",
        "view_image",
        "write_analysis_files",
    }
)
REPORTING_VISUALIZATION_FINALIZE_TOOL_NAMES = frozenset(
    {
        "finalize_report_analysis",
        "get_skill_instructions",
        "read_file",
        "read_tool_output",
        "register_report_charts",
        "write_analysis_files",
    }
)
```

`tools_for_task` 增两分支,`visualization` 分支保留(历史 run 恢复期读取);`__all__` 增两常量。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_agent_projection.py -q`
Expected: PASS(含既有 `test_reporting_worker_applies_phase_output_token_limits` 旧参数化行更新)

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/agent.py smart_reporting/reporting/tools/capabilities.py smart_reporting/reporting/tests/test_reporting_agent_projection.py
git commit -m "feat: 新 taskKind 输出限额档位与工具能力矩阵"
```

---

### Task 4: 图表文件缺失可恢复回执(report_chart_file_missing)

**Files:**
- Modify: `smart_reporting/reporting/tools/sections.py:808-862`(`_inspect_chart_file`)
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

**Interfaces:**
- Produces: `_inspect_chart_file` 对不存在文件返回/抛 `ReportingError("report_chart_file_missing", ..., retryable=True)`(经 `_failure` 转失败回执),`details={"sourcePath": ..., "chartId": ...}`;不再让 `WorkspaceError` 穿透炸 run。

- [ ] **Step 1: 写失败测试**

```python
async def test_register_report_charts_missing_file_returns_recoverable_failure() -> None:
    # 构造与现有 register_report_charts 契约测试同构的 toolkit fixture,
    # charts 批次引用 chartOutputRoot 下不存在的 PNG
    result = await toolkit.register_report_charts(
        charts=[
            {
                "chartId": "chart_missing",
                "sourcePath": "报表/智能分析/run-1/analysis/charts/section_001/attempt-1/chart_x.png",
                "title": "标题",
                "altText": "图注",
                "citationIds": ["citation_001"],
                "metricCodes": ["101"],
                "currentPeriod": "2025年",
                "sourceDatasetId": "dataset-1",
                "aggregationGrain": "月",
            }
        ],
        run_context=run_context,
    )
    assert result["ok"] is False
    assert result["code"] == "report_chart_file_missing"
    assert result["retryable"] is True
    # requiredActions 指示从清单移除或先生成
    assert any("移除" in action or "生成" in action for action in result["requiredActions"])
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_tool_contracts.py -k "missing_file_returns_recoverable" -v`
Expected: FAIL(现状抛 WorkspaceError 或 `_failure` 的 error_type 是 WorkspaceError)

- [ ] **Step 3: 最小实现**

`_inspect_chart_file` 中把:

```python
            await self.kernel.service._avalidate_existing_path(sandbox, source_path)
```

替换为:

```python
            try:
                await self.kernel.service._avalidate_existing_path(sandbox, source_path)
            except WorkspaceError as error:
                # 图表文件未生成(SKIP)时给出可恢复的字段级回执:模型移除该
                # 图或先生成再提交。不得让 WorkspaceError 穿透为 run 级失败,
                # 否则 error continuation 会注入全量任务上下文并滚入
                # tool_no_progress 8 连败终态(见 2026-08-31 真实运行分析)。
                raise ReportingError(
                    "report_chart_file_missing",
                    "图表源文件不存在;未生成的图表不得提交登记。",
                    details={"sourcePath": source_path},
                    retryable=True,
                ) from error
```

工具外层 `except (ReportingError, ValidationError, WorkspaceError)` 的 `_failure` 路径保持不变(ReportingError 自动带 retryable)。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_tool_contracts.py -k "chart" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/tools/sections.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
git commit -m "fix: 图表源文件缺失返回可恢复回执而非 WorkspaceError"
```

---

### Task 5: durable reducer 按章提交与全局唯一性

**Files:**
- Modify: `smart_reporting/reporting/workflow/state.py`(apply 函数新增 `submit_visualization_charts` 分支,约 513 行 `register_charts` 分支附近)
- Test: `smart_reporting/reporting/tests/test_reporting_state.py`

**Interfaces:**
- Produces: reducer 分支 `name == "submit_visualization_charts"`:
  - 状态机要求 `state.phase is ReportingPhase.VISUALIZATION` 且 `chartsRegistered` 未关闭(未注册前允许提交;已注册后提交被拒)。
  - `arguments`:`{"sectionCode": str, "charts": list[ReportChartRegistration dict], "files": [{path,size,sha256}, ...]}`。
  - 空列表合法(零图章):写入 `visualizationSections:{sectionCode} = {"charts": [], "files": []}`,并把 sectionCode 加入 `completedVisualizationSections`。
  - 跨章全局唯一性:遍历全部既有 `visualizationSections` 的 chartId/sourcePath 与新批次求交集,冲突抛 `ReportingStateError("report_visualization_section_conflict", ...)`。
  - 幂等:`commandId = viz-section:{revision}:{sectionCode}:{chartsSha256}`。

- [ ] **Step 1: 写失败测试**

```python
def test_submit_visualization_charts_persists_section_submission() -> None:
    state = make_visualization_state()  # 复用现有 register_charts 测试的 state 工厂
    result = apply(
        state,
        {
            "name": "submit_visualization_charts",
            "commandId": "viz-section:1:section_001:abc",
            "payload": {
                "sectionCode": "section_001",
                "charts": [make_chart_registration("chart_a")],
                "files": [make_file_identity("charts/section_001/attempt-1/chart_a.png")],
            },
        },
    )
    payload = result.state.payload
    assert payload["visualizationSections"]["section_001"]["charts"][0]["chartId"] == "chart_a"
    assert "section_001" in payload["completedVisualizationSections"]


def test_submit_visualization_charts_allows_empty_charts() -> None:
    state = make_visualization_state()
    result = apply(
        state,
        {
            "name": "submit_visualization_charts",
            "commandId": "viz-section:1:section_002:empty",
            "payload": {"sectionCode": "section_002", "charts": [], "files": []},
        },
    )
    payload = result.state.payload
    assert payload["visualizationSections"]["section_002"] == {"charts": [], "files": []}
    assert "section_002" in payload["completedVisualizationSections"]


def test_submit_visualization_charts_rejects_cross_section_duplicate() -> None:
    state = submit_section(state_with_chart("chart_a", "section_001"))
    with pytest.raises(ReportingStateError) as exc_info:
        apply(
            state,
            {
                "name": "submit_visualization_charts",
                "commandId": "viz-section:1:section_002:def",
                "payload": {
                    "sectionCode": "section_002",
                    "charts": [make_chart_registration("chart_a")],
                    "files": [],
                },
            },
        )
    assert exc_info.value.code == "report_visualization_section_conflict"


def test_submit_visualization_charts_blocked_after_registration_closed() -> None:
    state = register_charts_state()  # chartsRegistered=True
    with pytest.raises(ReportingStateError):
        apply(state, make_submit_command("section_003"))
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_state.py -k "submit_visualization_charts" -v`
Expected: FAIL(unknown command name 分支)

- [ ] **Step 3: 最小实现**

在 `state.py` 的 apply 函数 `elif name == "register_charts":` 分支之前新增(完整实现上述语义;重复 commandId 幂等由 apply 入口统一处理):

```python
    elif name == "submit_visualization_charts":
        # 章节图表草案提交:零图章合法(key 存在即"已完成");
        # chartId/sourcePath 跨章全局唯一,冲突章收到可恢复回执后改名重提。
        if state.phase is not ReportingPhase.VISUALIZATION:
            raise ReportingStateError(
                "report_visualization_section_phase_invalid", "章节图表只能在可视化阶段提交。"
            )
        if payload.get("chartsRegistered") is True:
            raise ReportingStateError(
                "report_visualization_section_closed", "图表登记窗口已关闭,章节草案不可再变更。"
            )
        section_code = arguments.get("sectionCode")
        charts = arguments.get("charts")
        files = arguments.get("files")
        # (校验 section_code str 1..128、charts list、files list of file identity)
        sections = payload.setdefault("visualizationSections", {})
        # (遍历全部既有 section 的 chartId/sourcePath 与新批次求交,冲突抛
        #  report_visualization_section_conflict)
        sections[section_code] = {"charts": [...], "files": [...]}
        completed = payload.setdefault("completedVisualizationSections", [])
        if section_code not in completed:
            completed.append(section_code)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_state.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/workflow/state.py smart_reporting/reporting/tests/test_reporting_state.py
git commit -m "feat: durable reducer 支持按章图表草案提交与跨章唯一性"
```

---

### Task 6: submit_visualization_charts 工具(终态工具)

**Files:**
- Modify: `smart_reporting/reporting/tools/sections.py`(新工具方法,register_report_charts 附近)
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`

**Interfaces:**
- Consumes: Task 4 的 `_inspect_chart_file` 修复;Task 5 的 reducer 分支;Task 1 后 `ContextTrace`(运行时通过 task runner 收口,本工具只回执)。
- Produces: `async def submit_visualization_charts(self, sectionCode: str, charts: list[dict], run_context=None) -> dict`;成功回执 `{"ok": True, "status": "committed", "sectionCode": ..., "chartCount": n}`;校验失败回执走 `_failure`。task_kinds 白名单 `frozenset({"visualization_section"})`。

- [ ] **Step 1: 写失败测试**

```python
async def test_submit_visualization_charts_requires_section_task_kind() -> None:
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001", charts=[], run_context=finalize_run_context
    )
    assert result["ok"] is False  # visualization_finalize 调用被拒


async def test_submit_visualization_charts_commit_flow() -> None:
    # fixture: section worker 上下文 + chartOutputRoot 下已存在 PNG(复用现有
    # register 测试的工作区 mock),write 后调用
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001", charts=[valid_chart], run_context=section_run_context
    )
    assert result["ok"] is True
    assert result["chartCount"] == 1
    # durable 中 visualizationSections 已写入(mock state repository 断言)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_tool_contracts.py -k "submit_visualization" -v`
Expected: FAIL(AttributeError: no attribute)

- [ ] **Step 3: 最小实现**

在 `sections.py` 新增方法(复用 `_require_phase_tool`、`_chart_output_root`、`_inspect_chart_file`、`_apply_durable`;完整实现,含 6.2 语义):

```python
    async def submit_visualization_charts(
        self,
        sectionCode: str,
        charts: list[dict[str, Any]],
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """章节 worker 终态:提交该章图表草案(允许零图)并按章收口。"""
        # 1) _require_phase_tool(allowed={"analysis"}, task_kinds={"visualization_section"})
        # 2) 逐项 ReportChartRegistration.model_validate + _inspect_chart_file
        #    (缺失文件经 Task 4 返回 report_chart_file_missing 失败回执)
        # 3) sourcePath 必须以本章契约 chartOutputRoot
        #    (analysis/charts/{sectionCode}/attempt-{n}/)为前缀
        # 4) _apply_durable(name="submit_visualization_charts",
        #    command_id=f"viz-section:{revision}:{sectionCode}:{charts_digest}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_tool_contracts.py -k "submit_visualization or register_report_charts" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/tools/sections.py smart_reporting/reporting/tests/test_reporting_tool_contracts.py
git commit -m "feat: 章节图表草案提交终态工具 submit_visualization_charts"
```

---

### Task 7: 执行层终态工具映射与恢复指令

**Files:**
- Modify: `smart_reporting/reporting/workflow/execution.py:493-530`(terminal_tools 分支与 recovery_instruction 分支)
- Test: `smart_reporting/reporting/tests/test_reporting_worker_continuation.py`(若无此文件,在 `test_reporting_tool_contracts.py` 或执行层既有测试文件中新增)

**Interfaces:**
- Consumes: Task 2 的 taskKind 值。
- Produces: `visualization_section` -> `terminal_tools = ("submit_visualization_charts",)`;`visualization_finalize` -> `("finalize_report_analysis",)`;两 kind 的 error-continuation 文案;`visualization` 分支文案保留(历史恢复)。

- [ ] **Step 1: 写失败测试**

```python
def test_terminal_tools_for_visualization_section() -> None:
    binding = {REPORTING_TASK_KIND_DEPENDENCY_KEY: "visualization_section"}
    # 通过 _run_worker 的公开入口或直接抽取分支函数断言:
    # 终态工具集合 == ("submit_visualization_charts",)


def test_recovery_instruction_for_visualization_section() -> None:
    # section worker error continuation 文案包含"只调用一次 submit_visualization_charts"
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "terminal_tools or recovery_instruction" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现**

`execution.py` 分支:

```python
        if task_kind == "analysis_item":
            terminal_tools = ("complete_analysis_item",)
        elif task_kind == "visualization_section":
            terminal_tools = ("submit_visualization_charts",)
        elif task_kind == "visualization_finalize":
            terminal_tools = ("finalize_report_analysis",)
        elif task_kind == "visualization":
            terminal_tools = ("finalize_report_analysis",)
        elif task_kind == "section":
            ...
```

恢复指令新增(对照现有 visualization 分支写法):

```python
                    elif task_kind == "visualization_section" and recovery_attempt > 0:
                        recovery_instruction = (
                            "服务端已保留本 run 已生成的该章图表文件。立即停止重新探索;"
                            "脚本尚未执行时先且只执行一次签发的本章脚本;"
                            "随后只调用一次 submit_visualization_charts 提交该章全部图表草案,"
                            "缺失的图表不要提交。不得调用 read_file,不得输出解释性文本。"
                        )
                    elif task_kind == "visualization_finalize" and recovery_attempt > 0:
                        recovery_instruction = (
                            "服务端已保留全部章节图表草案。立即停止重新探索;"
                            "只调用一次 register_report_charts 整批登记,随后立即调用 "
                            "finalize_report_analysis。不得调用 read_file/query_analysis_facts,"
                            "不得输出解释性文本。"
                        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "terminal_tools or recovery_instruction or continuation" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/workflow/execution.py smart_reporting/reporting/tests/
git commit -m "feat: 执行层新 taskKind 终态工具映射与 error-continuation 恢复指令"
```

---

### Task 8: register_report_charts 白名单收紧与 instructions 模板

**Files:**
- Modify: `smart_reporting/reporting/tools/sections.py:958,1018`(`_require_phase_tool(..., task_kinds=frozenset({"visualization"}))` 改 `{"visualization_finalize"}`;`tools/analysis.py:864` 的 `finalize_report_analysis` 同改)
- Modify: `smart_reporting/reporting/instructions.py:301-331`(`build_report_agent_instructions` 新 kind 分支;拆分 `REPORT_VISUALIZATION_AGENT_INSTRUCTIONS` 为章节/汇总两组)
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`、`smart_reporting/reporting/tests/test_reporting_agent_projection.py`

**Interfaces:**
- Consumes: Task 2/3 的 taskKind。
- Produces: `REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS`(按章生成脚本/执行/提交,禁注册禁 finalize)、`REPORT_VISUALIZATION_FINALIZE_AGENT_INSTRUCTIONS`(注册+ReportBrief+finalize,语义目录从任务 JSON 受信投影);`build_report_agent_instructions` 对两 kind 返回对应组合。

- [ ] **Step 1: 写失败测试**

```python
async def test_register_report_charts_rejected_for_legacy_visualization_kind() -> None:
    result = await toolkit.register_report_charts(charts=[...], run_context=legacy_viz_context)
    assert result["ok"] is False  # 旧 taskKind 不再拥有登记权限


async def test_register_report_charts_allowed_for_finalize_kind() -> None:
    result = await toolkit.register_report_charts(charts=[...], run_context=finalize_context)
    assert result["ok"] is True


def test_build_report_agent_instructions_new_kinds() -> None:
    section_instructions = build_report_agent_instructions(section_viz_run_context)
    assert any("submit_visualization_charts" in item for item in section_instructions)
    finalize_instructions = build_report_agent_instructions(finalize_run_context)
    assert any("register_report_charts" in item for item in finalize_instructions)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "register_report_charts or build_report_agent_instructions" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现**

1. 两处 `task_kinds=frozenset({"visualization"})` 改 `frozenset({"visualization_finalize"})`。
2. `instructions.py`:`REPORT_VISUALIZATION_AGENT_INSTRUCTIONS` 按语义拆为两组常量(保留公共条目),`build_report_agent_instructions` 增分支:

```python
    if task_kind == "visualization_section":
        return [*REPORT_WORKER_COMMON_INSTRUCTIONS, *REPORT_VISUALIZATION_SECTION_AGENT_INSTRUCTIONS]
    if task_kind == "visualization_finalize":
        return [*REPORT_WORKER_COMMON_INSTRUCTIONS, *REPORT_VISUALIZATION_FINALIZE_AGENT_INSTRUCTIONS]
```

`visualization` 分支改为 raise(或返回原模板,配合 Task 10 废弃策略选择 raise;按 Spec §8 不再新发起)。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "register_report_charts or build_report_agent or instructions" -q`
Expected: PASS(同步更新受影响的既有断言)

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/tools/sections.py smart_reporting/reporting/tools/analysis.py smart_reporting/reporting/instructions.py smart_reporting/reporting/tests/
git commit -m "feat: register/finalize 白名单收紧至 visualization_finalize 并拆分指令模板"
```

---

### Task 9: 章节调度器与 worker 构造(_run_pending_visualization_sections)

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`(新函数 `_run_visualization_section_task`、`_run_pending_visualization_sections`;`_run_analysis_phase` 的 1080-1652 区重构为两段调用)
- Modify: `smart_reporting/settings.py:254-259`(`report_visualization_concurrency`)、`smart_reporting/reporting/workflow/runtime/base.py:404-434`、`smart_reporting/reporting/bootstrap.py:70`
- Test: `smart_reporting/reporting/tests/test_reporting_section_concurrency.py`(同构新增)

**Interfaces:**
- Consumes: Task 1-8 全部;`_run_bounded`(analysis.py:1891)、`build_report_phase_acceptance_contract`、`TaskScope`、`task_runner.start/run`。
- Produces:
  - `_run_visualization_section_task(section_code: str) -> None`(构造按章 instruction/contract/task 并驱动 task_runner;trace `workKind="visualization_section"`、`sectionCode`、attempt 从该章 trace 历史续号;`chartOutputRoot = analysis/charts/{sectionCode}/attempt-{n+1}/`)
  - `_run_pending_visualization_sections(section_codes, *, completed, concurrency, worker)`:与 `_run_pending_analysis_items`(1922)同构,失败入 `visualization_section_errors` 账本
  - `_run_visualization_finalize()`:构造汇总任务(task key `viz-finalize`;trace `workKind="visualization_finalize"`;instruction 含 durable 汇集草案+语义目录+完整 outline;成功后走现有 1532-1580 收口链)
  - `ReportingRuntime.__init__` 新参数 `visualization_concurrency`(1..4);settings 键 `report_visualization_concurrency`,env `AGENT_REPORT_VISUALIZATION_CONCURRENCY`

- [ ] **Step 1: 写失败测试**

```python
async def test_visualization_sections_run_with_bounded_concurrency() -> None:
    # 复用 test_reporting_section_concurrency.py 的 runtime/task_runner mock 工厂
    runtime = make_runtime(visualization_concurrency=2)
    started: list[str] = []
    # ... 断言 4 章按 2 并发执行,全部收口后 finalize 被调用一次


async def test_section_failure_does_not_cancel_siblings() -> None:
    runtime = make_runtime(visualization_concurrency=4)
    # section_002 注入失败;断言 section_001/003/004 均完成,
    # visualization_section_errors 只含 section_002,finalize 未被调用


async def test_completed_sections_skipped_on_resume() -> None:
    runtime = make_runtime_with_durable(
        completedVisualizationSections=["section_001"],
    )
    # 断言 section_001 不再创建 task,其余章正常执行


async def test_finalize_failure_keeps_section_artifacts() -> None:
    runtime = make_runtime(visualization_concurrency=2)
    # finalize 注入失败;断言 visualizationSections durable 内容不变,
    # 重试时全部章节跳过、只重建 finalize task
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_section_concurrency.py -k "visualization" -v`
Expected: FAIL(函数不存在)

- [ ] **Step 3: 最小实现**

1. settings/base/bootstrap 三处 `visualization_concurrency` 装配(与 `analysis_concurrency` 逐行同构)。
2. 新增两个模块级函数 + runtime 方法,核心结构(节选;完整实现含 trace 续号、budget 按章投影、512KiB 校验、`reporting_phase_task_key(..., analysis_id=f"viz-section:{section_code}", ...)`):

```python
async def _run_pending_visualization_sections(
    section_codes: Sequence[str],
    *,
    completed_section_codes: set[str],
    concurrency: int,
    worker: Callable[[str], Awaitable[None]],
) -> None:
    pending = tuple(code for code in section_codes if code not in completed_section_codes)
    if not pending:
        return
    failures: dict[str, Exception] = {}

    async def run_one(section_code: str) -> None:
        try:
            await worker(section_code)
        except Exception as error:
            # 单章失败不取消兄弟章;账本按 sectionCode 写入
            # checkpoint.visualization_section_errors(含 retryUsage),
            # 收口后仅失败章 fresh attempt。
            failures[section_code] = error

    await _run_bounded(pending, concurrency=concurrency, worker=run_one)
    if failures:
        raise VisualizationSectionFailures(failures)  # 或最小化:抛第一个 + 账本已写 durable
```

3. `_run_analysis_phase` 主循环重构:章节数取 `outline.sections`;全部收口(含零图章)后调 `_run_visualization_finalize()`;汇总失败写 `last_error`(全局),章节失败读账本重建。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_section_concurrency.py -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/workflow/runtime/base.py smart_reporting/settings.py smart_reporting/reporting/bootstrap.py smart_reporting/reporting/tests/test_reporting_section_concurrency.py
git commit -m "feat: 可视化按章节并行调度与汇总 worker 构造"
```

---

### Task 10: 旧 checkpoint 迁移与全链路恢复测试

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`(恢复入口:`workKind="visualization"` 未终态 trace 的废弃分支;`chartsRegistered=true` 的 finalize-only 分支)
- Test: `smart_reporting/reporting/tests/test_reporting_state.py` 或新文件 `test_reporting_visualization_recovery.py`

**Interfaces:**
- Consumes: Task 9 的调度器。
- Produces: 恢复期行为--legacy 未终态 task 标记废弃不恢复 run;`chartsRegistered=true` 且 `charts` 非空 -> 跳过章节重建直接 finalize;`chartsRegistered=false` -> 整段重建章节;attempt 与 legacy trace 不混算;`chartsRegistered` 标志语义不变。

- [ ] **Step 1: 写失败测试**

```python
async def test_legacy_unterminal_visualization_task_is_discarded() -> None:
    checkpoint = checkpoint_with_legacy_visualization_trace(status="started")
    runtime = make_runtime_with_checkpoint(checkpoint)
    await runtime.run_coding_analysis(...)
    # 断言:legacy task 未被恢复;章节任务全部重建;
    # legacy trace 仍可被 ReportingCheckpoint 校验(未删值)


async def test_registered_but_unfrozen_run_goes_finalize_only() -> None:
    checkpoint = checkpoint_with_legacy_visualization_trace(
        status="started", charts_registered=True, charts=[chart_entry]
    )
    # 断言:不创建章节 task;汇总 task 输入含 registeredCharts;
    # register 窗口已关(汇总只做 ReportBrief+finalize)


async def test_visualization_section_errors_merge_keeps_both() -> None:
    # 双章同时失败:合并后账本同时含 section_001 与 section_002,
    # 各自 retryUsage 不丢失;恢复时两章各自重建
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "legacy_visualization or section_errors_merge" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现**

`_run_analysis_phase` 恢复入口(对照 1080-1104 的 trace 扫描区)新增:发现 `workKind=="visualization"` 且 status=="started" 的 trace 时:

```python
            # 旧 in-flight visualization task 废弃:register 白名单已收紧到
            # visualization_finalize,legacy run 无法完成登记;facts 已在启动
            # 前置校验冻结(analysis.py:1134-1138),整段按新章节协议重建无损。
            # chartsRegistered=true 且 charts 非空的 run 例外:登记窗口已关,
            # 跳过章节重建,直接构造 finalize-only 汇总任务。
```

(按上述语义实现分支;merge 侧在 `_update_reporting_checkpoint` 对 `visualization_section_errors` 做按键合并,替代 361 行对 last_error 的覆盖语义。)

- [ ] **Step 4: 运行测试确认通过**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "legacy_visualization or section_errors_merge or visualization" -q`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/reporting/workflow/runtime/analysis.py smart_reporting/reporting/tests/
git commit -m "feat: 旧 visualization checkpoint 废弃迁移与按章失败账本合并"
```

---

### Task 11: 汇总语义投影与最终回归

**Files:**
- Modify: `smart_reporting/reporting/workflow/runtime/analysis.py`(汇总 instruction 的语义目录投影:`analysisPlans`、`deterministicFactFiles`、`analysisCitationIds`、`citationDatasetIds`、`chartRegistrationRules` 全量)
- Test: `smart_reporting/reporting/tests/test_reporting_tool_contracts.py`(汇总 finalize 语义提交测试)

**Interfaces:**
- Consumes: Task 9 的汇总 instruction;`finalize_report_analysis` 的 `datasetSemantics`/`metricDefinitions` 契约(`tools/analysis.py:848-852`)。
- Produces: 汇总 worker 从任务 JSON 的受信语义目录提交 `datasetSemantics`(精确覆盖 evidence dataset,`checkpoint.py:355` 校验)与 `metricDefinitions`,不从图表元数据猜测。

- [ ] **Step 1: 写失败测试**

```python
async def test_finalize_submit_semantics_from_projected_catalog() -> None:
    # 汇总 run_context:任务 JSON 含 analysisPlans/deterministicFactFiles/
    # allowedMetricCodes;断言 finalize_report_analysis 成功且
    # datasetSemantics 精确覆盖全部 evidence datasetId
    ...


async def test_global_zero_charts_fails_at_finalize() -> None:
    # 全部章零图:register 拒绝空批次;finalize 报
    # report_visualization_charts_not_registered(既有约束不变)
    ...
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd smart_reporting && python -m pytest reporting/tests -k "projected_catalog or zero_charts" -v`
Expected: FAIL

- [ ] **Step 3: 最小实现**

汇总 instruction payload 增语义目录字段(从 durable analysis_plans、fact_files、citation_bindings 投影;字段名与 6.3 一致);确认 `finalize_report_analysis` 的 `_phase_parameters` 路径已能读取(analysisOutputPath 等)。

- [ ] **Step 4: 最终回归 + 静态检查**

Run: `cd smart_reporting && python -m pytest reporting/tests/test_reporting_agent_projection.py reporting/tests/test_reporting_tool_contracts.py reporting/tests/test_reporting_state.py reporting/tests/test_reporting_section_concurrency.py -q`
Expected: PASS
Run: `cd smart_reporting && ruff format reporting/ && ruff check reporting/ && mypy reporting/workflow/runtime/analysis.py reporting/workflow/state.py reporting/tools/sections.py reporting/agent.py reporting/phase.py reporting/tools/capabilities.py reporting/instructions.py`
Expected: 无错误

- [ ] **Step 5: 提交**

```bash
git add smart_reporting/
git commit -m "feat: 汇总 worker 语义目录受信投影与全局收口回归"
```

---

## 真实验证(实施完成后单独执行,不属提交单元)

按 Spec §10.4:跑一次 CLI 工作流(同类医院年度运营报告请求),归档日志到 /tmp,对照本次基线确认:
1. 可视化段耗时 5-8 分钟;
2. 无 65,536 输出打满;
3. 无 WorkspaceError;
4. 产出 PDF。

使用 `reporting-cli-acceptance` skill 执行与归档。

## Self-Review 记录

- Spec 覆盖:§5.1->Task 1;§7 矩阵前三行->Task 2、限额/能力矩阵->Task 3;§6.4 WorkspaceError->Task 4;§6.5 reducer->Task 5;§6.2 工具->Task 6;§7 终态/恢复指令->Task 7;§6.4 白名单+§7 指令模板->Task 8;§5.2-5.3 调度+§6.1/6.3 instruction->Task 9;§8 迁移+§5.4 账本->Task 10;§6.3 语义->Task 11。无缺口。
- 占位符扫描:Task 3/6/9 的 `...` 均为"复用现有 fixture 构造方式"的指向性说明并给出了断言主体,非 TBD;实施者需读取相邻既有测试复用工厂(这是既有测试文件的既定模式,plan 已指明文件与函数名)。
- 类型一致性:`visualization_section_errors`、`completedVisualizationSections`、`visualizationSections`、`report_chart_file_missing`、`report_visualization_section_conflict`、`viz-section:{sectionCode}`/`viz-finalize`、`charts/{sectionCode}/attempt-{n}/` 各任务间一致。
