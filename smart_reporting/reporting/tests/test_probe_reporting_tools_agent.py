from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.probe_reporting_tools_agent as probe_module
from scripts.probe_reporting_tools_agent import (
    ProbeRecorder,
    ProbeReportingPhaseOpenAIChat,
    ProbeToolProjection,
    _agent_instructions,
    _build_probe_run_context,
    _cli_stage_input,
    _probe_visible_tool_names,
    _run_scenario,
    _runtime,
    build_mock_probe_tools,
    complex_cli_prompt,
    probe_scenarios,
)
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    bind_reporting_run_context,
    current_reporting_run_context,
)
from smart_reporting.reporting.tools.capabilities import tools_for_task
from smart_reporting.reporting.tools.context import ReportingOutputPolicy
from smart_reporting.reporting.tools.mock_workspace import MockReportingToolRuntime
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    VisualizationPlanDraft,
)


def _settings() -> object:
    return object()


def _chart_patch() -> dict[str, str]:
    return {
        "patch": (
            "--- /dev/null\n+++ b/analysis/output/outpatient_chart.py\n"
            "@@ -0,0 +1 @@\n+print('chart')"
        )
    }


class _OfflineCodeAgent:
    def __init__(self) -> None:
        self.tools: list[object] = []

    async def arun(self, prompt: str, **_kwargs: object) -> object:
        payload = json.loads(prompt)
        tool = self.tools[0]
        if tool.name == "read_file":
            return await tool.entrypoint(path=payload["scriptPath"])
        path = payload["scriptPath"]
        repair = "readReceipt" in payload["facts"]
        patch = (
            f"--- {'a/' + path if repair else '/dev/null'}\n"
            f"+++ b/{path}\n"
            f"@@ {'-1 +1' if repair else '-0,0 +1'} @@\n"
            + ("-print('probe')\n+print('repaired')" if repair else "+print('probe')")
        )
        return await tool.entrypoint(patch=patch)


class _OfflineStructuredExecutor:
    def __init__(self, agent: object) -> None:
        self.output_schema = agent.output_schema

    async def run(self, _prompt: str, **_kwargs: object) -> object:
        if self.output_schema is AnalysisEvidenceDecision:
            return AnalysisEvidenceDecision(
                requiresSupplementalEvidence=True,
                reason="缺少 2025-04 成本事实。",
                missingFacts=("2025-04 outpatient cost",),
            )
        if self.output_schema is AnalysisSummaryDraft:
            return AnalysisSummaryDraft(summary="已完成补证。", warnings=())
        if self.output_schema is VisualizationPlanDraft:
            return VisualizationPlanDraft(
                charts=(
                    probe_module.ChartDraft(
                        chartId="chart_001",
                        sourcePath="analysis/charts/outpatient_operation/chart.png",
                        title="门诊趋势",
                        altText="门诊收入与成本率趋势",
                        citationIds=("citation-001",),
                        metricCodes=("outpatient_revenue",),
                        currentPeriod="2025-01 至 2025-06",
                        sourceDatasetId="dataset-001",
                        aggregationGrain="month",
                    ),
                )
            )
        raise AssertionError(f"unexpected schema: {self.output_schema}")


def test_probe_passes_cli_task_json_only_as_run_input() -> None:
    scenario = probe_scenarios()[0]
    instructions = "\n".join(_agent_instructions(scenario))

    assert '"taskKind":"analysis_item"' not in instructions
    assert complex_cli_prompt(scenario).count('"taskKind":"analysis_item"') == 1


@pytest.mark.anyio
async def test_probe_fact_query_receipt_matches_production_shape() -> None:
    scenario = next(item for item in probe_scenarios() if item.branch == "truncated")
    recorder = ProbeRecorder(_runtime(), scenario)

    result = await recorder.invoke(
        "query_analysis_facts",
        {"query": "metrics[]", "purpose": "补充成本事实", "maxItems": 10},
    )

    assert result["analysisIds"] == ["analysis_001"]
    assert result["query"] == "metrics[]"
    assert result["truncated"] is False
    assert result["itemLimit"] == 10
    assert result["value"][0]["missingCount"] == 1


@pytest.mark.anyio
async def test_probe_complete_section_evidence_is_valid_json() -> None:
    content = await _runtime().workspace.read_text("analysis/evidence/complete_analysis_001.json")

    assert json.loads(content)["validated"] is True


@pytest.mark.anyio
async def test_probe_section_read_receipts_match_frozen_evidence_identity() -> None:
    scenario = next(
        item for item in probe_scenarios() if item.name == "section-render-truncated-evidence"
    )
    identity = _cli_stage_input(scenario)["sectionWorkItem"]["evidence"][0]["evidenceFiles"][0]
    recorder = ProbeRecorder(_runtime(), scenario)

    first = await recorder.invoke("read_file", {"path": identity["path"], "offset": 0})
    second = await recorder.invoke(
        "read_file", {"path": identity["path"], "offset": first["nextOffset"]}
    )

    assert first["path"] == second["path"] == identity["path"]
    assert first["offset"] == 0
    assert second["offset"] == first["nextOffset"]
    assert first["totalBytes"] == second["totalBytes"] == identity["size"]
    assert first["sha256"] == second["sha256"] == identity["sha256"]
    assert first["hasMore"] is True
    assert second["hasMore"] is False
    assert len((first["content"] + second["content"]).encode()) == identity["size"]


def test_section_probe_directives_never_authorize_fact_file_reads() -> None:
    for scenario in probe_scenarios():
        if scenario.task_kind != "section":
            continue
        stage_input = _cli_stage_input(scenario)
        directive = stage_input["executionDirective"]
        assert "读取冻结事实" not in directive
        assert "不得读取 factFiles" in directive
        assert "factFiles" not in stage_input["sectionWorkItem"]


def test_probe_context_matches_production_task_binding() -> None:
    scenario = probe_scenarios()[0]

    context = _build_probe_run_context(
        scenario,
        model_tier="fast",
        model_id="qwen3.6-flash",
        thinking=False,
    )
    binding = context.dependencies[REPORTING_TASK_DEPENDENCY]

    assert context.user_id == "reporting-tool-probe"
    assert context.session_state == {}
    assert binding["externalRunId"] == f"probe-{scenario.name}"
    assert binding["threadId"] == f"probe-thread-{scenario.name}"
    assert binding["sandboxId"] == f"probe-sandbox-{scenario.name}"
    assert binding["leaseOwner"] == "reporting-tool-probe"
    assert binding["leaseEpoch"] == 1
    assert binding["attemptNo"] == 1
    assert binding[REPORTING_PHASE_DEPENDENCY_KEY] == scenario.phase
    assert binding[REPORTING_TASK_KIND_DEPENDENCY_KEY] == scenario.task_kind
    assert binding[REPORTING_MODEL_TIER_DEPENDENCY_KEY] == "fast"
    assert binding[REPORTING_MODEL_ID_DEPENDENCY_KEY] == "qwen3.6-flash"
    assert binding[REPORTING_THINKING_EFFORT_DEPENDENCY_KEY] == "off"
    assert len(
        {
            _build_probe_run_context(
                item, model_tier="fast", model_id="test", thinking=False
            ).run_id
            for item in probe_scenarios()
        }
    ) == len(probe_scenarios())


@pytest.mark.anyio
async def test_probe_passes_one_bound_production_context_to_fixed_analysis_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def run_fixed_analysis(
        scenario: object, model: object, recorder: object, run_context: object
    ) -> None:
        observed.update(
            scenario=scenario,
            model=model,
            recorder=recorder,
            run_context=run_context,
            bound=current_reporting_run_context(),
        )

    monkeypatch.setattr(probe_module, "_run_fixed_analysis_scenario", run_fixed_analysis)
    monkeypatch.setattr(
        probe_module,
        "_build_model",
        lambda *_args, **_kwargs: SimpleNamespace(id="qwen3.6-flash"),
    )

    result = await _run_scenario(
        _settings(),
        probe_scenarios()[0],
        model_tier="fast",
        thinking=False,
        timeout_seconds=1,
    )

    context = observed["run_context"]
    assert observed["bound"] is context
    assert observed["scenario"] == probe_scenarios()[0]
    assert observed["model"].id == "qwen3.6-flash"
    assert result["visible_tool_batches"] == []
    assert result["not_visible_calls"] == []


def test_probe_records_model_call_that_is_not_visible_in_current_projection() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-inspection")
    context = _build_probe_run_context(
        scenario,
        model_tier="fast",
        model_id="test",
        thinking=False,
    )
    projection = ProbeToolProjection(
        batches=[["apply_analysis_patch", "run_python_script", "submit_visualization_charts"]]
    )
    model = ProbeReportingPhaseOpenAIChat(id="test", api_key="test")
    model._probe_projection = projection
    assistant = probe_module.Message(
        role="assistant",
        tool_calls=[
            {
                "id": "call-hidden",
                "type": "function",
                "function": {"name": "process", "arguments": '{"action":"list"}'},
            }
        ],
    )
    messages = [probe_module.Message(role="user", content="probe")]

    with bind_reporting_run_context(context):
        calls = model.get_function_calls_to_run(assistant, messages, functions={})

    assert calls == []
    assert projection.not_visible_calls == [
        {"name": "process", "call_id": "call-hidden", "visible_tools": projection.batches[-1]}
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("scenario_name", ["analysis-script-context", "visualization-recovery"])
async def test_probe_recovery_requires_script_repair(scenario_name: str) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    recorder = ProbeRecorder(_runtime(), scenario)
    patch = (
        "--- /dev/null\n"
        f"+++ b/{'analysis/output/supplement.py' if scenario.task_kind == 'analysis_item' else 'analysis/output/outpatient_chart.py'}\n"
        "@@ -0,0 +1 @@\n+print('probe')"
    )
    await recorder.invoke("apply_analysis_patch", {"patch": patch})

    first = await recorder.invoke(
        "run_python_script",
        {"script_path": recorder.committed_script_path, "timeout": 30},
    )
    second = await recorder.invoke(
        "run_python_script",
        {"script_path": recorder.committed_script_path, "timeout": 30},
    )

    assert first["ok"] is False
    assert second["ok"] is True


@pytest.mark.anyio
@pytest.mark.parametrize("scenario_name", ["analysis-script-context", "visualization-recovery"])
async def test_probe_fixed_workflow_owns_recovery_after_coding_agent_stops(
    monkeypatch: pytest.MonkeyPatch, scenario_name: str
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    context = _build_probe_run_context(
        scenario,
        model_tier="fast",
        model_id="test",
        thinking=False,
    )
    tools, recorder = build_mock_probe_tools(
        scenario.phase,
        scenario.task_kind,
        _runtime(),
        scenario,
        context,
    )
    monkeypatch.setattr(probe_module, "ReportingStructuredOutputExecutor", _OfflineStructuredExecutor)
    monkeypatch.setattr(
        probe_module,
        "create_reporting_generator_agent",
        lambda **kwargs: SimpleNamespace(output_schema=kwargs["output_schema"]),
    )
    monkeypatch.setattr(
        probe_module,
        "create_reporting_code_agent",
        lambda **_kwargs: _OfflineCodeAgent(),
    )

    with bind_reporting_run_context(context):
        if scenario.task_kind == "analysis_item":
            await probe_module._run_fixed_analysis_scenario(
                scenario, SimpleNamespace(id="test"), recorder, context
            )
        else:
            await probe_module._run_fixed_visualization_scenario(
                scenario, SimpleNamespace(id="test"), recorder, context
            )

    names = [call["name"] for call in recorder.calls]
    first_patch = names.index("apply_analysis_patch")
    first_run = names.index("run_python_script", first_patch)
    repair_read = names.index("read_file", first_run)
    repair_patch = names.index("apply_analysis_patch", repair_read)
    second_run = names.index("run_python_script", repair_patch)
    assert first_patch < first_run < repair_read < repair_patch < second_run
    assert all(
        set(call["arguments"]) == {"patch"}
        for call in recorder.calls
        if call["name"] == "apply_analysis_patch"
    )
    assert names[-1] == scenario.completion_tool
    if scenario.task_kind == "visualization_section":
        assert names[-2:] == ["inspect_chart", "submit_visualization_charts"]


@pytest.mark.anyio
async def test_probe_controlled_runner_completes_without_process_session() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-inspection")
    context = _build_probe_run_context(
        scenario,
        model_tier="fast",
        model_id="test",
        thinking=False,
    )
    tools, recorder = build_mock_probe_tools(
        scenario.phase,
        scenario.task_kind,
        _runtime(),
        scenario,
        context,
    )
    await recorder.invoke("apply_analysis_patch", _chart_patch())
    receipt = await recorder.invoke(
        "run_python_script",
        {
            "script_path": "analysis/output/outpatient_chart.py",
            "timeout": 30,
        },
    )

    assert receipt["status"] == "completed"
    assert "session_id" not in receipt
    assert "process" not in _probe_visible_tool_names(context, tools)


@pytest.mark.anyio
async def test_probe_mock_runtime_is_isolated_across_ten_runs() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-inspection")
    previous_context = None
    previous_recorder = None
    previous_runtime = None
    for _ in range(10):
        context = _build_probe_run_context(
            scenario,
            model_tier="fast",
            model_id="test",
            thinking=False,
        )
        runtime = _runtime()
        _tools, recorder = build_mock_probe_tools(
            scenario.phase,
            scenario.task_kind,
            runtime,
            scenario,
            context,
        )
        assert context.session_state == {}
        assert recorder.calls == []
        assert runtime.calls == []
        await recorder.invoke("apply_analysis_patch", _chart_patch())
        await recorder.invoke(
            "run_python_script",
            {
                "script_path": "analysis/output/outpatient_chart.py",
                "timeout": 30,
            },
        )
        if previous_context is not None:
            assert context is not previous_context
            assert recorder.calls is not previous_recorder.calls
            assert runtime.calls is not previous_runtime.calls
        previous_context = context
        previous_recorder = recorder
        previous_runtime = runtime


@pytest.mark.parametrize(
    ("phase", "task_kind"),
    (
        ("analysis", "analysis_item"),
        ("analysis", "visualization_section"),
        ("section", "section"),
    ),
)
def test_probe_uses_current_reporting_toolkit_schema(phase: str, task_kind: str) -> None:
    runtime = MockReportingToolRuntime(
        input_snapshot={"datasets": [{"datasetId": "dataset-001"}]},
        inputs={"inputs/source.txt": b"source"},
        output_policy=ReportingOutputPolicy(roots=("analysis/output",)),
    )

    tools, _recorder = build_mock_probe_tools(phase, task_kind, runtime)

    expected = tools_for_task(phase, task_kind)
    assert expected is not None
    assert {tool.name for tool in tools} == expected
    assert all(isinstance(tool.parameters, dict) for tool in tools)


@pytest.mark.anyio
async def test_probe_tools_use_mock_workspace_for_file_and_command_calls() -> None:
    runtime = MockReportingToolRuntime(
        input_snapshot={},
        inputs={"inputs/source.txt": b"source"},
        output_policy=ReportingOutputPolicy(roots=("analysis/output",)),
    )
    tools, recorder = build_mock_probe_tools("analysis", "analysis_item", runtime)
    by_name = {tool.name: tool for tool in tools}

    read_result = await by_name["read_file"].entrypoint(path="inputs/source.txt")
    command_result = await by_name["run_python_script"].entrypoint(
        script_path="analysis/output/probe.py", timeout=30
    )

    assert read_result["ok"] is True
    assert read_result["content"] == "source"
    assert command_result["ok"] is True
    assert [call["operation"] for call in runtime.calls] == ["read_bytes", "execute_script"]
    assert [call["name"] for call in recorder.calls] == ["read_file", "run_python_script"]


@pytest.mark.anyio
async def test_probe_rejects_section_read_of_unissued_dataset_input() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "section-evidence-rework")
    runtime = MockReportingToolRuntime(
        input_snapshot={},
        inputs={"inputs/outpatient_monthly.csv": b"month,revenue,cost\n"},
        output_policy=ReportingOutputPolicy(roots=("analysis/output",)),
    )
    recorder = ProbeRecorder(runtime, scenario)

    result = await recorder.invoke("read_file", {"path": "inputs/outpatient_monthly.csv"})

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["code"] == "probe_stage_read_path_forbidden"
    assert result["requiredActions"]
    assert runtime.calls == []


@pytest.mark.anyio
async def test_probe_rejects_runner_before_visualization_script_is_committed() -> None:
    scenario = next(
        item for item in probe_scenarios() if item.name == "visualization-preview-truncated"
    )
    runtime = MockReportingToolRuntime(
        input_snapshot={},
        output_policy=ReportingOutputPolicy(roots=("analysis/output", "analysis/charts")),
    )
    recorder = ProbeRecorder(runtime, scenario)

    result = await recorder.invoke(
        "run_python_script",
        {"script_path": "analysis/output/outpatient_chart.py", "timeout": 30},
    )

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["code"] == "probe_script_not_committed"
    assert result["requiredActions"]
    assert runtime.calls == []


@pytest.mark.anyio
async def test_probe_rejects_runner_path_other_than_committed_script() -> None:
    scenario = next(
        item for item in probe_scenarios() if item.name == "visualization-preview-truncated"
    )
    runtime = MockReportingToolRuntime(
        input_snapshot={},
        output_policy=ReportingOutputPolicy(roots=("analysis/output", "analysis/charts")),
    )
    recorder = ProbeRecorder(runtime, scenario)
    await recorder.invoke(
        "apply_analysis_patch",
        {
            "patch": (
                "--- /dev/null\n+++ b/analysis/output/outpatient_chart.py\n"
                "@@ -0,0 +1 @@\n+print('chart')"
            )
        },
    )

    result = await recorder.invoke(
        "run_python_script", {"script_path": "analysis/output/other.py", "timeout": 30}
    )

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["code"] == "probe_script_path_forbidden"
    assert result["details"] == {"scriptPath": "analysis/output/outpatient_chart.py"}
    assert result["requiredActions"]
    assert [call["operation"] for call in runtime.calls] == ["write_text"]


@pytest.mark.anyio
async def test_probe_rejects_analysis_runner_path_outside_signed_supplement() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "analysis-script-foreground")
    runtime = MockReportingToolRuntime(
        input_snapshot={},
        output_policy=ReportingOutputPolicy(roots=("analysis/output", "analysis/charts")),
    )
    recorder = ProbeRecorder(runtime, scenario)
    await recorder.invoke(
        "apply_analysis_patch",
        {
            "patch": (
                "--- /dev/null\n+++ b/analysis/output/other.py\n@@ -0,0 +1 @@\n+print('analysis')"
            )
        },
    )

    result = await recorder.invoke(
        "run_python_script", {"script_path": "analysis/output/other.py", "timeout": 30}
    )

    assert result["ok"] is False
    assert result["code"] == "probe_script_path_forbidden"
    assert result["details"] == {"scriptPath": "analysis/output/supplement.py"}
    assert [call["operation"] for call in runtime.calls] == ["write_text"]


def test_probe_scenarios_only_require_tools_allowed_by_current_task_schema() -> None:
    scenarios = probe_scenarios()

    assert len(scenarios) == 10
    assert all(scenario.tool_names for scenario in scenarios)

    expected = {
        (phase, task_kind, tool_name)
        for phase, task_kind in (
            ("analysis", "analysis_item"),
            ("analysis", "visualization_section"),
            ("section", "section"),
        )
        for tool_name in tools_for_task(phase, task_kind) or ()
    }
    actual = {
        (scenario.phase, scenario.task_kind, tool_name)
        for scenario in scenarios
        for tool_name in scenario.tool_names
    }

    assert actual <= expected
    assert {scenario.task_kind for scenario in scenarios} == {
        "analysis_item",
        "visualization_section",
        "section",
    }
    assert {scenario.completion_tool for scenario in scenarios} == {
        "complete_analysis_item",
        "submit_visualization_charts",
        "render_report_section",
        "request_analysis_rework",
    }


def test_probe_scenarios_only_require_conditional_tools_after_their_preconditions() -> None:
    scenarios = {scenario.name: scenario for scenario in probe_scenarios()}

    assert "read_tool_output" not in scenarios["analysis-fixed-facts"].tool_names
    assert all("process" not in scenario.tool_names for scenario in scenarios.values())
    assert "read_file" in scenarios["analysis-fixed-facts"].tool_names
    assert "query_profile" not in scenarios["analysis-profile-bound-facts"].tool_names
    assert "query_analysis_facts" not in scenarios["analysis-truncated-output"].tool_names
    assert "query_analysis_context" not in scenarios["analysis-script-context"].tool_names
    assert scenarios["analysis-truncated-output"].branch == "truncated"
    assert scenarios["analysis-script-context"].branch == "recovery"
    assert scenarios["visualization-preview-truncated"].branch == "preview"
    assert scenarios["visualization-inspection"].branch == "inspection"
    assert "inspect_chart" not in scenarios["visualization-preview-truncated"].tool_names
    assert scenarios["visualization-recovery"].branch == "recovery"
    assert "view_image" not in scenarios["visualization-recovery"].tool_names


def test_probe_prompt_contains_cli_style_complex_stage_input() -> None:
    analysis = probe_scenarios()[0]
    visualization = probe_scenarios()[5]
    section = probe_scenarios()[8]

    analysis_prompt = complex_cli_prompt(analysis)
    visualization_prompt = complex_cli_prompt(visualization)
    section_prompt = complex_cli_prompt(section)

    assert '"reportGoal"' in analysis_prompt
    assert '"currentAnalysis"' in analysis_prompt
    assert '"deterministicFacts"' in analysis_prompt
    assert '"visualizationFacts"' in visualization_prompt
    assert '"sectionWorkItem"' in section_prompt
    assert "工具名称" not in analysis_prompt


def test_probe_analysis_branches_expose_only_their_real_completion_precondition() -> None:
    scenarios = {scenario.name: scenario for scenario in probe_scenarios()}

    fixed = _cli_stage_input(scenarios["analysis-fixed-facts"])
    profile = _cli_stage_input(scenarios["analysis-profile-bound-facts"])
    truncated = _cli_stage_input(scenarios["analysis-truncated-output"])

    assert fixed["deterministicFacts"]["analysisId"] == "analysis_001"
    assert profile["deterministicFacts"]["analysisId"] == "analysis_001"
    assert truncated["deterministicFacts"]["analysisId"] == "analysis_001"
    assert "按 offset 完整读取" in truncated["executionDirective"]
    assert "固定 Workflow" in complex_cli_prompt(scenarios["analysis-script-foreground"])
    assert "run_python_script" in complex_cli_prompt(scenarios["analysis-script-context"])


def test_probe_stage_inputs_match_production_phase_projections() -> None:
    scenarios = {scenario.name: scenario for scenario in probe_scenarios()}

    analysis = _cli_stage_input(scenarios["analysis-fixed-facts"])
    facts = analysis["deterministicFacts"]
    assert analysis["currentAnalysisId"] == "analysis_001"
    assert analysis["deterministicFactFile"]["path"] == "analysis/facts/analysis_001.json"
    assert analysis["deterministicFactFile"]["size"] > 100
    assert len(analysis["deterministicFactFile"]["sha256"]) == 64
    assert facts["analysisId"] == "analysis_001"
    assert facts["metrics"]
    assert facts["derivedMetrics"]
    assert facts["comparisons"]
    assert facts["warnings"]

    visualization = _cli_stage_input(scenarios["visualization-recovery"])
    visualization_fact = visualization["visualizationFacts"][0]
    assert visualization_fact["factFile"]["path"] == "analysis/facts/analysis_001.json"
    assert visualization_fact["metrics"][0]["metricIndex"] == 0
    assert visualization_fact["metrics"][0]["dataPaths"]["periodValues"] == (
        "metrics[0].periodValues"
    )
    assert visualization_fact["evidenceFiles"][0]["path"] == ("analysis/evidence/analysis_001.json")
    assert visualization_fact["citationIds"] == ["citation-001"]
    assert visualization["reportVisualTheme"]["primary"]
    assert visualization["visualizationWorkspace"] == {
        "scriptPath": "analysis/output/outpatient_chart.py",
        "chartOutputRoot": "analysis/charts/outpatient_operation",
    }

    section = _cli_stage_input(scenarios["section-render-truncated-evidence"])
    evidence = section["sectionWorkItem"]["evidence"][0]
    assert evidence["evidenceFiles"][0]["path"] == ("analysis/evidence/complete_analysis_001.json")
    assert "evidenceFiles" not in section["sectionWorkItem"]
