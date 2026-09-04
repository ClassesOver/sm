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


def _settings() -> object:
    return object()


def _chart_patch() -> dict[str, str]:
    return {
        "patch": (
            "--- /dev/null\n+++ b/analysis/output/outpatient_chart.py\n"
            "@@ -0,0 +1 @@\n+print('chart')"
        )
    }


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
async def test_probe_passes_one_bound_production_context_to_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeAgent:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def arun(self, _prompt: str, **kwargs: object) -> object:
            observed.update(kwargs)
            observed["bound"] = current_reporting_run_context()
            return object()

    monkeypatch.setattr(probe_module, "Agent", FakeAgent)
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
    assert observed["run_id"] == context.run_id
    assert observed["session_id"] == context.session_id
    assert observed["user_id"] == context.user_id
    assert observed["dependencies"] is context.dependencies
    assert observed["stream"] is True
    assert observed["stream_events"] is True
    assert result["visible_tool_batches"] == []
    assert result["not_visible_calls"] == []


def test_probe_records_model_call_that_is_not_visible_in_current_projection() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-background")
    context = _build_probe_run_context(
        scenario,
        model_tier="fast",
        model_id="test",
        thinking=False,
    )
    projection = ProbeToolProjection(
        batches=[["apply_analysis_patch", "terminal", "submit_visualization_charts"]]
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
async def test_probe_recovery_starts_with_production_visible_script_reads() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-recovery")
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
    await recorder.prepare()

    visible = _probe_visible_tool_names(context, tools)

    assert {"read_file", "read_tool_output"}.issubset(visible)
    assert "view_image" not in visible


@pytest.mark.anyio
async def test_probe_background_terminal_makes_only_its_context_process_visible() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-background")
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
        "terminal",
        {
            "command": "python3 analysis/output/outpatient_chart.py",
            "timeout": 30,
            "background": True,
        },
    )

    assert receipt["session_id"] in context.session_state["reportingVisualizationSessions"]
    assert "process" in _probe_visible_tool_names(context, tools)


@pytest.mark.anyio
async def test_probe_mock_runtime_is_isolated_across_ten_runs() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-background")
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
            "terminal",
            {
                "command": "python3 analysis/output/outpatient_chart.py",
                "timeout": 30,
                "background": True,
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
    command_result = await by_name["terminal"].entrypoint(
        command="python3 -c 'print(1)'", timeout=30
    )

    assert read_result["ok"] is True
    assert read_result["content"] == "source"
    assert command_result["ok"] is True
    assert [call["operation"] for call in runtime.calls] == ["read_bytes", "execute_script"]
    assert [call["name"] for call in recorder.calls] == ["read_file", "terminal"]


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
async def test_probe_rejects_terminal_before_visualization_script_is_committed() -> None:
    scenario = next(
        item for item in probe_scenarios() if item.name == "visualization-preview-truncated"
    )
    runtime = MockReportingToolRuntime(
        input_snapshot={},
        output_policy=ReportingOutputPolicy(roots=("analysis/output", "analysis/charts")),
    )
    recorder = ProbeRecorder(runtime, scenario)

    result = await recorder.invoke(
        "terminal", {"command": "python3 analysis/output/outpatient_chart.py", "timeout": 30}
    )

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["code"] == "probe_terminal_script_not_committed"
    assert result["requiredActions"]
    assert runtime.calls == []


@pytest.mark.anyio
async def test_probe_rejects_terminal_command_other_than_committed_script() -> None:
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

    result = await recorder.invoke("terminal", {"command": "pwd", "timeout": 30})

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["code"] == "probe_terminal_command_forbidden"
    assert result["details"] == {"allowedCommand": "python3 analysis/output/outpatient_chart.py"}
    assert result["requiredActions"]
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
    assert {scenario.terminal_tool for scenario in scenarios} == {
        "complete_analysis_item",
        "submit_visualization_charts",
        "render_report_section",
        "request_analysis_rework",
    }


def test_probe_scenarios_only_require_conditional_tools_after_their_preconditions() -> None:
    scenarios = {scenario.name: scenario for scenario in probe_scenarios()}

    assert "read_tool_output" not in scenarios["analysis-fixed-facts"].tool_names
    assert "process" not in scenarios["analysis-script-foreground"].tool_names
    assert scenarios["analysis-truncated-output"].branch == "truncated"
    assert scenarios["analysis-background-context"].branch == "background"
    assert scenarios["visualization-preview-truncated"].branch == "preview"
    assert scenarios["visualization-background"].branch == "background"
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
    profile = _cli_stage_input(scenarios["analysis-profile-supplement"])
    truncated = _cli_stage_input(scenarios["analysis-truncated-output"])

    assert fixed["deterministicFacts"]["analysisId"] == "analysis_001"
    assert profile["deterministicFacts"]["analysisId"] == "analysis_001"
    assert truncated["deterministicFacts"]["analysisId"] == "analysis_001"
    assert "明确事实缺口" in truncated["executionDirective"]
    assert "不得再次 patch、read 或 terminal" in complex_cli_prompt(
        scenarios["analysis-script-foreground"]
    )
    assert "只调用一次 process(action=wait)" in complex_cli_prompt(
        scenarios["analysis-background-context"]
    )


def test_probe_stage_inputs_match_production_phase_projections() -> None:
    scenarios = {scenario.name: scenario for scenario in probe_scenarios()}

    analysis = _cli_stage_input(scenarios["analysis-fixed-facts"])
    facts = analysis["deterministicFacts"]
    assert analysis["currentAnalysisId"] == "analysis_001"
    assert analysis["deterministicFactFile"]["path"] == "analysis/facts/analysis_001.json"
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
    assert visualization["visualizationWorkspace"]["allowedTerminalCommand"] == (
        "python3 analysis/output/outpatient_chart.py"
    )

    section = _cli_stage_input(scenarios["section-render-truncated-evidence"])
    evidence = section["sectionWorkItem"]["evidence"][0]
    assert evidence["evidenceFiles"][0]["path"] == ("analysis/evidence/complete_analysis_001.json")
    assert "evidenceFiles" not in section["sectionWorkItem"]
