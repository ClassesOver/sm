from __future__ import annotations

import hashlib
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

pytestmark = pytest.mark.skip(reason="历史 tools probe 依赖已删除的 V0 runner 协议")


def _settings() -> object:
    return object()


_ANALYSIS_SOURCE = (
    "# 中文补证脚本\n"
    "from pathlib import Path\n"
    'output_path = Path("analysis/output/supplement.json")\n'
    'output_path.write_text("{}", encoding="utf-8")\n'
)
_REPAIRED_ANALYSIS_SOURCE = _ANALYSIS_SOURCE + "repair_complete = True\n"
_VISUALIZATION_SOURCE = (
    "import matplotlib\n"
    'matplotlib.use("Agg")\n'
    "import matplotlib.pyplot as plt\n"
    'output_path = "analysis/charts/outpatient_operation/chart.png"\n'
    "plt.savefig(output_path)\n"
)
_REPAIRED_VISUALIZATION_SOURCE = _VISUALIZATION_SOURCE + "repair_complete = True\n"


def _create_patch(path: str, source: str) -> dict[str, str]:
    lines = source.splitlines(keepends=True)
    return {
        "patch": (
            f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{len(lines)} @@\n"
            + "".join(f"+{line}" for line in lines)
        )
    }


def _update_patch(path: str, before: str, after: str) -> str:
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    return (
        f"--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,{len(before_lines)} +1,{len(after_lines)} @@\n"
        + "".join(f"-{line}" for line in before_lines)
        + "".join(f"+{line}" for line in after_lines)
    )


def _chart_patch() -> dict[str, str]:
    return _create_patch("analysis/output/outpatient_chart.py", _VISUALIZATION_SOURCE)


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
        source = _VISUALIZATION_SOURCE if "chart" in path else _ANALYSIS_SOURCE
        repaired = _REPAIRED_VISUALIZATION_SOURCE if "chart" in path else _REPAIRED_ANALYSIS_SOURCE
        return await tool.entrypoint(source=repaired if repair else source)


class _InvalidCodeAgent:
    def __init__(self, output: object) -> None:
        self.output = output
        self.tools: list[object] = []

    async def arun(self, _prompt: str, **_kwargs: object) -> object:
        return self.output


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


@pytest.mark.anyio
async def test_probe_reads_utf8_script_with_byte_aligned_pagination_receipt() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "analysis-script-foreground")
    recorder = ProbeRecorder(_runtime(), scenario)
    patch_result = await recorder.invoke(
        "apply_analysis_patch",
        _create_patch("analysis/output/supplement.py", _ANALYSIS_SOURCE),
    )
    raw = _ANALYSIS_SOURCE.encode("utf-8")
    expected_sha256 = hashlib.sha256(raw).hexdigest()

    complete = await recorder.invoke(
        "read_file", {"path": "analysis/output/supplement.py", "offset": 0}
    )
    first = await recorder.invoke(
        "read_file",
        {"path": "analysis/output/supplement.py", "offset": 0, "max_bytes": 4},
    )
    second = await recorder.invoke(
        "read_file",
        {
            "path": "analysis/output/supplement.py",
            "offset": first["nextOffset"],
            "max_bytes": 4,
        },
    )

    assert patch_result["ok"] is True
    assert complete["content"] == _ANALYSIS_SOURCE
    assert complete["offset"] == 0
    assert complete["nextOffset"] == complete["totalBytes"] == len(raw)
    assert complete["sha256"] == expected_sha256
    assert complete["hasMore"] is False
    assert first["content"] == "# "
    assert first["nextOffset"] == len(b"# ")
    assert first["hasMore"] is True
    assert second["content"] == "中"
    assert second["offset"] == first["nextOffset"]
    assert second["nextOffset"] == first["nextOffset"] + len("中".encode())
    assert second["sha256"] == expected_sha256


@pytest.mark.anyio
async def test_probe_repair_runner_accepts_complete_utf8_read_receipt() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "analysis-script-context")
    recorder = ProbeRecorder(_runtime(), scenario)
    committed = await recorder.invoke(
        "apply_analysis_patch",
        _create_patch("analysis/output/supplement.py", _ANALYSIS_SOURCE),
    )
    script = probe_module.FileIdentity.model_validate(committed["artifacts"][0])

    result = await probe_module.ReportingCodeGenerationRunner(
        agent_factory=_OfflineCodeAgent
    ).repair(
        script,
        {"code": "probe_script_failed", "message": "需要修复"},
        lambda **arguments: recorder.invoke("read_file", arguments),
        lambda **arguments: recorder.invoke("apply_analysis_patch", arguments),
    )

    assert result.script_file.path == script.path
    assert result.script_file.size == len(_REPAIRED_ANALYSIS_SOURCE.encode("utf-8"))
    assert (
        result.script_file.sha256
        == hashlib.sha256(_REPAIRED_ANALYSIS_SOURCE.encode("utf-8")).hexdigest()
    )
    assert [call["name"] for call in recorder.calls] == [
        "apply_analysis_patch",
        "read_file",
        "apply_analysis_patch",
    ]
    assert await recorder.runtime.workspace.read_text(script.path) == _REPAIRED_ANALYSIS_SOURCE


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


@pytest.mark.parametrize(
    "actual",
    [
        ("read_file", "run_python_script", "run_python_script", "complete_analysis_item"),
        ("run_python_script", "read_file", "complete_analysis_item"),
    ],
)
def test_probe_protocol_rejects_duplicate_or_reordered_tool_calls(
    actual: tuple[str, ...],
) -> None:
    expected = ("read_file", "run_python_script", "complete_analysis_item")

    failure = probe_module._tool_sequence_failure(expected, actual)

    assert failure == {
        "code": "probe_tool_sequence_mismatch",
        "message": "场景工具调用顺序或次数不匹配。",
        "details": {"expected": list(expected), "actual": list(actual)},
    }


@pytest.mark.anyio
@pytest.mark.parametrize("scenario_name", ["analysis-script-context", "visualization-recovery"])
async def test_probe_recovery_requires_script_repair(scenario_name: str) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    recorder = ProbeRecorder(_runtime(), scenario)
    path = (
        "analysis/output/supplement.py"
        if scenario.task_kind == "analysis_item"
        else "analysis/output/outpatient_chart.py"
    )
    source = _ANALYSIS_SOURCE if scenario.task_kind == "analysis_item" else _VISUALIZATION_SOURCE
    await recorder.invoke("apply_analysis_patch", _create_patch(path, source))

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
    monkeypatch.setattr(
        probe_module, "ReportingStructuredOutputExecutor", _OfflineStructuredExecutor
    )
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

    content = await recorder.runtime.workspace.read_text(recorder.committed_script_path)
    expected_source = (
        _REPAIRED_ANALYSIS_SOURCE
        if scenario.task_kind == "analysis_item"
        else _REPAIRED_VISUALIZATION_SOURCE
    )
    assert content == expected_source
    assert len(recorder.script_patch_metrics) == 2
    assert [item["attempt"] for item in recorder.script_patch_metrics] == [1, 2]
    assert recorder.final_script_metrics == {
        "path": recorder.committed_script_path,
        "sourceLineCount": len(expected_source.splitlines()),
        "sizeBytes": len(expected_source.encode()),
        "sha256": hashlib.sha256(expected_source.encode()).hexdigest(),
    }


@pytest.mark.anyio
@pytest.mark.parametrize("model_output", ["处理完成。", "print('direct python')", None])
async def test_probe_rejects_non_patch_coding_output_after_workflow_soft_fallback(
    monkeypatch: pytest.MonkeyPatch, model_output: object
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "analysis-script-foreground")
    monkeypatch.setattr(
        probe_module,
        "_build_model",
        lambda *_args, **_kwargs: SimpleNamespace(id="test"),
    )
    monkeypatch.setattr(
        probe_module, "ReportingStructuredOutputExecutor", _OfflineStructuredExecutor
    )
    monkeypatch.setattr(
        probe_module,
        "create_reporting_generator_agent",
        lambda **kwargs: SimpleNamespace(output_schema=kwargs["output_schema"]),
    )
    monkeypatch.setattr(
        probe_module,
        "create_reporting_code_agent",
        lambda **_kwargs: _InvalidCodeAgent(model_output),
    )

    result = await _run_scenario(
        _settings(),
        scenario,
        model_tier="fast",
        thinking=False,
        timeout_seconds=5,
    )

    assert result["task_completed"] is True
    assert result["protocol_compliant"] is False
    assert result["valid"] is False
    assert {"apply_analysis_patch", "run_python_script"}.issubset(result["missing_tools"])
    assert any(
        failure["code"] == "probe_required_tools_missing" for failure in result["protocol_failures"]
    )


@pytest.mark.anyio
async def test_probe_run_reports_final_script_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "analysis-script-foreground")
    monkeypatch.setattr(
        probe_module,
        "_build_model",
        lambda *_args, **_kwargs: SimpleNamespace(id="test"),
    )
    monkeypatch.setattr(
        probe_module, "ReportingStructuredOutputExecutor", _OfflineStructuredExecutor
    )
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

    result = await _run_scenario(
        _settings(), scenario, model_tier="fast", thinking=False, timeout_seconds=5
    )

    assert result["finalScriptMetrics"] == {
        "path": "analysis/output/supplement.py",
        "sourceLineCount": len(_ANALYSIS_SOURCE.splitlines()),
        "sizeBytes": len(_ANALYSIS_SOURCE.encode()),
        "sha256": hashlib.sha256(_ANALYSIS_SOURCE.encode()).hexdigest(),
    }
    assert result["scriptPatchMetrics"] == [
        {
            "attempt": 1,
            "path": "analysis/output/supplement.py",
            "patchPhysicalLineCount": len(
                _create_patch("analysis/output/supplement.py", _ANALYSIS_SOURCE)[
                    "patch"
                ].splitlines()
            ),
            "sourceLineCount": len(_ANALYSIS_SOURCE.splitlines()),
            "sizeBytes": len(_ANALYSIS_SOURCE.encode()),
            "sha256": hashlib.sha256(_ANALYSIS_SOURCE.encode()).hexdigest(),
        }
    ]


@pytest.mark.anyio
async def test_probe_run_returns_nonzero_for_completed_noncompliant_result(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = probe_scenarios()[0]

    async def noncompliant_result(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "valid": True,
            "protocol_compliant": False,
            "task_completed": True,
            "expected_tools": [],
            "calls": [],
        }

    monkeypatch.setattr(probe_module, "probe_scenarios", lambda: (scenario,))
    monkeypatch.setattr(
        probe_module.AgentSettings,
        "from_environment",
        lambda: SimpleNamespace(model_fast_id="test", model_standard_id="test"),
    )
    monkeypatch.setattr(
        probe_module,
        "_run_scenario",
        noncompliant_result,
    )

    exit_code = await probe_module._run(
        SimpleNamespace(
            env_file=".env",
            runs=1,
            model_tier="fast",
            thinking=False,
            task_timeout=5,
            progress_file=None,
        )
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["protocol_compliant_count"] == 0


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
async def test_probe_runner_uses_contract_simulation_without_executor() -> None:
    scenario = next(item for item in probe_scenarios() if item.name == "visualization-inspection")
    runtime = _runtime()
    tools, recorder = build_mock_probe_tools(scenario.phase, scenario.task_kind, runtime, scenario)
    by_name = {tool.name: tool for tool in tools}

    await by_name["apply_analysis_patch"].entrypoint(**_chart_patch())
    command_result = await by_name["run_python_script"].entrypoint(
        script_path="analysis/output/outpatient_chart.py", timeout=30
    )

    assert command_result["ok"] is True
    assert command_result["simulationMode"] == "mock_contract_simulation"
    assert "execute_script" not in [call["operation"] for call in runtime.calls]
    assert [call["name"] for call in recorder.calls] == [
        "apply_analysis_patch",
        "run_python_script",
    ]


@pytest.mark.anyio
async def test_probe_applies_valid_unified_diff_content() -> None:
    runtime = _runtime()
    recorder = ProbeRecorder(runtime)

    result = await recorder.invoke("apply_analysis_patch", _chart_patch())

    assert result["ok"] is True
    assert await runtime.workspace.read_text("analysis/output/outpatient_chart.py") == (
        _VISUALIZATION_SOURCE
    )
    expected = {
        "attempt": 1,
        "path": "analysis/output/outpatient_chart.py",
        "patchPhysicalLineCount": len(_chart_patch()["patch"].splitlines()),
        "sourceLineCount": len(_VISUALIZATION_SOURCE.splitlines()),
        "sizeBytes": len(_VISUALIZATION_SOURCE.encode()),
        "sha256": hashlib.sha256(_VISUALIZATION_SOURCE.encode()).hexdigest(),
    }
    assert result["scriptMetrics"] == expected
    assert recorder.script_patch_metrics == [expected]
    assert result["artifacts"][0] == {
        "path": expected["path"],
        "size": expected["sizeBytes"],
        "sha256": expected["sha256"],
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario_name", "path", "source"),
    [
        ("analysis-script-foreground", "analysis/output/supplement.py", "pass\n"),
        ("analysis-script-foreground", "analysis/output/supplement.py", "value = (\n"),
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            "value = 1\r\nprint(value)\r\n",
        ),
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            "#" + "a" * (8 * 1024) + "\npass\n",
        ),
        (
            "visualization-inspection",
            "analysis/output/outpatient_chart.py",
            "import matplotlib\nmatplotlib.use('Agg')\nimport matplotlib.pyplot as plt\n",
        ),
    ],
)
async def test_probe_rejects_invalid_python_source_before_workspace_mutation(
    scenario_name: str, path: str, source: str
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    runtime = _runtime()
    recorder = ProbeRecorder(runtime, scenario)

    result = await recorder.invoke("apply_analysis_patch", _create_patch(path, source))

    assert result["ok"] is False
    assert result["code"] == "report_python_source_shape_invalid"
    assert runtime.calls == []
    assert recorder.committed_script_path is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario_name", "path", "source", "artifact_path"),
    [
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            _ANALYSIS_SOURCE.replace("supplement.json", "wrong.json"),
            "analysis/output/wrong.json",
        ),
        (
            "visualization-inspection",
            "analysis/output/outpatient_chart.py",
            _VISUALIZATION_SOURCE.replace("chart.png", "wrong.png"),
            "analysis/charts/outpatient_operation/wrong.png",
        ),
    ],
)
async def test_probe_simulation_rejects_wrong_artifact_output_path(
    scenario_name: str, path: str, source: str, artifact_path: str
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    runtime = _runtime()
    recorder = ProbeRecorder(runtime, scenario)
    patch_result = await recorder.invoke("apply_analysis_patch", _create_patch(path, source))

    result = await recorder.invoke("run_python_script", {"script_path": path, "timeout": 30})

    assert patch_result["ok"] is True
    assert result["ok"] is False
    assert result["code"] == "probe_artifact_contract_invalid"
    assert "execute_script" not in [call["operation"] for call in runtime.calls]
    with pytest.raises(Exception):
        await runtime.workspace.read_bytes(artifact_path)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario_name", "script_path", "source"),
    [
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            "from pathlib import Path\n"
            "raise RuntimeError('stop')\n"
            'output_path = Path("analysis/output/supplement.json")\n'
            'output_path.write_text("{}", encoding="utf-8")\n',
        ),
        (
            "visualization-inspection",
            "analysis/output/outpatient_chart.py",
            "import matplotlib\n"
            'matplotlib.use("Agg")\n'
            "import matplotlib.pyplot as plt\n"
            "if False:\n"
            '    plt.savefig("analysis/charts/outpatient_operation/chart.png")\n',
        ),
    ],
)
async def test_probe_simulation_rejects_statically_unreachable_artifact_write(
    scenario_name: str, script_path: str, source: str
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    recorder = ProbeRecorder(_runtime(), scenario)
    patch_result = await recorder.invoke("apply_analysis_patch", _create_patch(script_path, source))

    result = await recorder.invoke("run_python_script", {"script_path": script_path, "timeout": 30})

    assert patch_result["ok"] is True
    assert result["ok"] is False
    assert result["code"] == "probe_artifact_contract_invalid"
    assert result["simulationMode"] == "mock_contract_simulation"
    assert recorder.accepted_artifact_paths == set()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario_name", "script_path", "source"),
    [
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            "from pathlib import Path\n"
            "def never_called():\n"
            '    Path("analysis/output/supplement.json").write_text("{}")\n'
            "print('done')\n",
        ),
        (
            "visualization-inspection",
            "analysis/output/outpatient_chart.py",
            "import matplotlib\n"
            'matplotlib.use("Agg")\n'
            "import matplotlib.pyplot as plt\n"
            "class Renderer:\n"
            "    def render(self):\n"
            '        plt.savefig("analysis/charts/outpatient_operation/chart.png")\n'
            "print('done')\n",
        ),
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            "from pathlib import Path\n"
            "def write_output():\n"
            '    Path("analysis/output/supplement.json").write_text("{}")\n'
            "if False:\n"
            "    write_output()\n",
        ),
    ],
)
async def test_probe_simulation_rejects_artifact_write_outside_finite_entry_call_graph(
    scenario_name: str, script_path: str, source: str
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    recorder = ProbeRecorder(_runtime(), scenario)
    await recorder.invoke("apply_analysis_patch", _create_patch(script_path, source))

    result = await recorder.invoke("run_python_script", {"script_path": script_path, "timeout": 30})

    assert result["ok"] is False
    assert result["code"] == "probe_artifact_contract_invalid"
    assert recorder.accepted_artifact_paths == set()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("scenario_name", "script_path", "source"),
    [
        (
            "analysis-script-foreground",
            "analysis/output/supplement.py",
            "from pathlib import Path\n"
            "def main():\n"
            '    Path("analysis/output/supplement.json").write_text("{}")\n'
            'if __name__ == "__main__":\n'
            "    main()\n",
        ),
        (
            "visualization-inspection",
            "analysis/output/outpatient_chart.py",
            "import matplotlib\n"
            'matplotlib.use("Agg")\n'
            "import matplotlib.pyplot as plt\n"
            "def render():\n"
            '    plt.savefig("analysis/charts/outpatient_operation/chart.png")\n'
            'if __name__ == "__main__":\n'
            "    render()\n",
        ),
    ],
)
async def test_probe_simulation_accepts_artifact_write_from_explicit_main_call_graph(
    scenario_name: str, script_path: str, source: str
) -> None:
    scenario = next(item for item in probe_scenarios() if item.name == scenario_name)
    recorder = ProbeRecorder(_runtime(), scenario)
    await recorder.invoke("apply_analysis_patch", _create_patch(script_path, source))

    result = await recorder.invoke("run_python_script", {"script_path": script_path, "timeout": 30})

    assert result["ok"] is True


@pytest.mark.anyio
async def test_probe_artifacts_are_unavailable_until_simulated_script_acceptance() -> None:
    analysis = next(item for item in probe_scenarios() if item.name == "analysis-script-foreground")
    analysis_recorder = ProbeRecorder(_runtime(), analysis)
    before_evidence = await analysis_recorder.invoke(
        "read_file", {"path": "analysis/output/supplement.json"}
    )
    await analysis_recorder.invoke(
        "apply_analysis_patch", _create_patch("analysis/output/supplement.py", _ANALYSIS_SOURCE)
    )
    run_evidence = await analysis_recorder.invoke(
        "run_python_script", {"script_path": "analysis/output/supplement.py", "timeout": 30}
    )
    after_evidence = await analysis_recorder.invoke(
        "read_file", {"path": "analysis/output/supplement.json"}
    )

    visualization = next(
        item for item in probe_scenarios() if item.name == "visualization-inspection"
    )
    visualization_recorder = ProbeRecorder(_runtime(), visualization)
    before_chart = await visualization_recorder.invoke(
        "inspect_chart", {"path": "analysis/charts/outpatient_operation/chart.png"}
    )
    await visualization_recorder.invoke("apply_analysis_patch", _chart_patch())
    run_chart = await visualization_recorder.invoke(
        "run_python_script",
        {"script_path": "analysis/output/outpatient_chart.py", "timeout": 30},
    )
    after_chart = await visualization_recorder.invoke(
        "inspect_chart", {"path": "analysis/charts/outpatient_operation/chart.png"}
    )

    assert before_evidence["code"] == "probe_stage_read_path_forbidden"
    assert run_evidence["simulationMode"] == "mock_contract_simulation"
    assert after_evidence["ok"] is True
    assert before_chart["code"] == "probe_chart_not_accepted"
    assert run_chart["simulationMode"] == "mock_contract_simulation"
    assert after_chart["ok"] is True
    assert after_chart["sha256"] != "a" * 64


@pytest.mark.anyio
async def test_probe_rejects_invalid_unified_diff_without_writing() -> None:
    runtime = _runtime()
    recorder = ProbeRecorder(runtime)

    result = await recorder.invoke("apply_analysis_patch", {"patch": "print('direct python')"})

    assert result["ok"] is False
    assert result["code"] == "probe_patch_invalid"
    assert runtime.calls == []


@pytest.mark.anyio
async def test_probe_rejects_update_with_wrong_original_content() -> None:
    runtime = _runtime()
    recorder = ProbeRecorder(runtime)
    await recorder.invoke("apply_analysis_patch", _chart_patch())

    result = await recorder.invoke(
        "apply_analysis_patch",
        {
            "patch": (
                "--- a/analysis/output/outpatient_chart.py\n"
                "+++ b/analysis/output/outpatient_chart.py\n"
                "@@ -1 +1 @@\n"
                "-print('wrong')\n"
                "+repair_complete = True\n"
            )
        },
    )

    assert result["ok"] is False
    assert result["code"] == "probe_patch_invalid"
    assert await runtime.workspace.read_text("analysis/output/outpatient_chart.py") == (
        _VISUALIZATION_SOURCE
    )


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
    await recorder.invoke("apply_analysis_patch", _chart_patch())

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
        _create_patch("analysis/output/other.py", _ANALYSIS_SOURCE),
    )

    result = await recorder.invoke(
        "run_python_script", {"script_path": "analysis/output/other.py", "timeout": 30}
    )

    assert result["ok"] is False
    assert result["code"] == "probe_script_path_forbidden"
    assert result["details"] == {"scriptPath": "analysis/output/supplement.py"}
    assert runtime.calls == []


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
    assert visualization["allowedDatasetIds"] == ["dataset-001"]
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
