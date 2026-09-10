import hashlib
import inspect
import json
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
)
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisChart,
    AnalysisEvidence,
    ChartVisualInspectionIssue,
    ChartVisualInspectionReceipt,
    FileIdentity,
    MetricDefinition,
    SectionCitation,
    SectionManagementQuestion,
    SectionWorkItem,
)
from smart_reporting.reporting.workflow.runtime import sections as reporting_sections
from smart_reporting.reporting.workflow.runtime.analysis import (
    RuntimeAnalysisMixin,
    _visualization_section_completion_conditions,
)
from smart_reporting.reporting.workflow.runtime.base import (
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
)
from smart_reporting.reporting.workflow.runtime.code_generation import (
    CodeGenerationResult,
    ReportingCodeGenerationRunner,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    AnalysisReworkDecision,
    ChartDraft,
    RenderSectionDecision,
    SectionBlockContent,
    SectionEvidenceBundle,
    SectionEvidenceFile,
    SectionPlanOutput,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.section_workflow import SectionWorkflow
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)
from smart_reporting.reporting.workflow.state import ReportingPhase
from smart_reporting.task_execution import TaskExecutionScope


def _context() -> RunContext:
    return RunContext(run_id="run-1", session_id="session-1")


def _chart() -> ChartDraft:
    return ChartDraft(
        chartId="chart_001",
        sourcePath="charts/chart.png",
        title="收入趋势",
        altText="收入按月趋势",
        citationIds=("citation_001",),
        metricCodes=("revenue",),
        currentPeriod="2026-08",
        sourceDatasetId="dataset_001",
        aggregationGrain="month",
    )


def _visualization_plan(*, charts: tuple[ChartDraft, ...] | None = None) -> VisualizationPlanDraft:
    return VisualizationPlanDraft(charts=(_chart(),) if charts is None else charts)


def _visualization_payload() -> dict[str, object]:
    return {"visualizationWorkspace": {"scriptPath": "charts/charts.py"}}


def test_analysis_executor_does_not_assemble_report() -> None:
    source = inspect.getsource(RuntimeAnalysisMixin.run_reporting_analysis)

    assert "_finalize_reporting_sections" not in source


@pytest.mark.anyio
async def test_analysis_executor_does_not_rerun_after_finalize_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = SimpleNamespace(revision=2, phase="finalize")
    durable = SimpleNamespace(
        phase=ReportingPhase.FINALIZE,
        payload={"workflowCheckpoint": {"phase": "finalize", "revision": 2}},
    )

    class Runtime:
        state_repository = SimpleNamespace(get_or_create=AsyncMock(return_value=durable))
        report_tools = SimpleNamespace(
            bind_document_context=AsyncMock(
                side_effect=AssertionError("FINALIZE 重入不得重新执行分析准备")
            )
        )

        @staticmethod
        def _feedback(_step_input: object) -> None:
            return None

        @staticmethod
        def _state(run_context: RunContext) -> dict[str, object]:
            return run_context.session_state

        @staticmethod
        def _scope(_run_context: RunContext) -> dict[str, str]:
            return {
                "externalRunId": "external-run",
                "threadId": "thread",
                "userId": "user",
            }

        @staticmethod
        def _workflow_result(state: dict[str, object]) -> dict[str, object]:
            return dict(state[REPORT_WORKFLOW_RESULT_STATE_KEY])  # type: ignore[arg-type]

    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.ReportingCheckpoint.model_validate",
        lambda _value: checkpoint,
    )
    context = RunContext(
        run_id="run-1",
        session_id="thread",
        user_id="user",
        session_state={REPORT_WORKFLOW_RESULT_STATE_KEY: {"jobId": "job-1"}},
    )

    output = await RuntimeAnalysisMixin.run_reporting_analysis(
        Runtime(), SimpleNamespace(), context
    )

    assert output.content == {"status": "ready", "jobId": "job-1"}
    Runtime.report_tools.bind_document_context.assert_not_awaited()


@pytest.mark.anyio
async def test_assemble_report_retries_only_finalization_and_preserves_frozen_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint = SimpleNamespace(revision=2, phase="finalize")
    manifest = SimpleNamespace(model_dump=lambda **_kwargs: {"version": "1", "artifacts": []})
    durable = SimpleNamespace(
        phase=ReportingPhase.FINALIZE,
        payload={"workflowCheckpoint": {"phase": "finalize", "revision": 2}},
    )
    finalization_calls = 0

    class Runtime:
        state_repository = SimpleNamespace(get=AsyncMock(return_value=durable))

        @staticmethod
        def _state(run_context: RunContext) -> dict[str, object]:
            return run_context.session_state

        @staticmethod
        def _scope(_run_context: RunContext) -> dict[str, str]:
            return {"externalRunId": "external-run", "threadId": "thread"}

        @staticmethod
        def _workflow_result(state: dict[str, object]) -> dict[str, object]:
            return dict(state[REPORT_WORKFLOW_RESULT_STATE_KEY])  # type: ignore[arg-type]

        async def _finalize_reporting_sections(self, *_args, **_kwargs):
            nonlocal finalization_calls
            finalization_calls += 1
            if finalization_calls == 1:
                raise ReportingError("report_assembly_failed", "汇编失败")
            return checkpoint, manifest

    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.ReportingCheckpoint.model_validate",
        lambda _value: checkpoint,
    )
    context = RunContext(
        run_id="run-1",
        session_id="thread",
        session_state={
            REPORT_WORKFLOW_RESULT_STATE_KEY: {"jobId": "job-1"},
            REPORT_DATASET_LINEAGE_STATE_KEY: [],
        },
    )
    runtime = Runtime()
    frozen_state = dict(context.session_state)

    with pytest.raises(ReportingError, match="汇编失败"):
        await RuntimeAnalysisMixin.assemble_report(runtime, SimpleNamespace(), context)

    assert context.session_state == frozen_state
    assert durable.phase is ReportingPhase.FINALIZE

    output = await RuntimeAnalysisMixin.assemble_report(runtime, SimpleNamespace(), context)

    assert finalization_calls == 2
    assert output.content["markdownPath"].endswith("report-revision-2.md")
    assert context.session_state[REPORT_ARTIFACTS_STATE_KEY]["draft"] == {
        "version": "1",
        "artifacts": [],
    }


@pytest.mark.anyio
async def test_assemble_report_restores_completed_manifest_without_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_file = FileIdentity(
        path="报表/智能分析/run-1/report-revision-2.manifest.json",
        size=1,
        sha256="a" * 64,
    )
    checkpoint = SimpleNamespace(
        revision=2,
        phase="completed",
        files=(manifest_file,),
    )
    manifest = SimpleNamespace(
        model_dump=lambda **_kwargs: {"version": "1", "artifacts": ["existing"]}
    )
    durable = SimpleNamespace(
        phase=ReportingPhase.COMPLETED,
        payload={"workflowCheckpoint": {"phase": "completed", "revision": 2}},
    )

    class Runtime:
        state_repository = SimpleNamespace(get=AsyncMock(return_value=durable))

        @staticmethod
        def _state(run_context: RunContext) -> dict[str, object]:
            return run_context.session_state

        @staticmethod
        def _scope(_run_context: RunContext) -> dict[str, str]:
            return {"externalRunId": "external-run", "threadId": "thread"}

        @staticmethod
        def _workflow_result(state: dict[str, object]) -> dict[str, object]:
            return dict(state[REPORT_WORKFLOW_RESULT_STATE_KEY])  # type: ignore[arg-type]

        _read_identity_model = AsyncMock(return_value=manifest)
        _finalize_reporting_sections = AsyncMock(
            side_effect=AssertionError("completed checkpoint 不得重复汇编")
        )

    monkeypatch.setattr(
        "smart_reporting.reporting.workflow.runtime.analysis.ReportingCheckpoint.model_validate",
        lambda _value: checkpoint,
    )
    context = RunContext(
        run_id="run-1",
        session_id="thread",
        session_state={
            REPORT_WORKFLOW_RESULT_STATE_KEY: {"jobId": "job-1"},
            REPORT_DATASET_LINEAGE_STATE_KEY: [],
        },
    )

    output = await RuntimeAnalysisMixin.assemble_report(Runtime(), SimpleNamespace(), context)

    assert output.content["markdownPath"].endswith("report-revision-2.md")
    Runtime._read_identity_model.assert_awaited_once()
    Runtime._finalize_reporting_sections.assert_not_awaited()
    assert context.session_state[REPORT_ARTIFACTS_STATE_KEY]["draft"]["artifacts"] == ["existing"]


@pytest.mark.anyio
async def test_visualization_fact_projection_declares_period_value_fields() -> None:
    fact_model = SimpleNamespace(
        model_dump=lambda **_kwargs: {
            "metrics": [
                {
                    "datasetId": "dataset_001",
                    "field": "outpatient_visits",
                    "metricCodes": ["outpatient_visits"],
                    "periodValues": [{"period": "2025-01", "value": 100}],
                    "topGroups": [],
                    "bottomGroups": [],
                }
            ]
        }
    )
    runtime = SimpleNamespace(
        _visualization_context={"thread_id": "thread-1"},
        _read_identity_model=AsyncMock(return_value=fact_model),
    )
    fact_file = FileIdentity(path="analysis/facts/analysis_001.json", size=2, sha256="a" * 64)

    projection = await RuntimeAnalysisMixin._visualization_section_fact_projection(
        runtime,
        "analysis_001",
        fact_file,
        {},
    )

    assert projection["metrics"][0]["periodValueFields"] == ["period", "value"]


def test_visualization_generator_completion_does_not_delegate_tool_calls() -> None:
    conditions = _visualization_section_completion_conditions(None)

    assert not any("submit_visualization_charts" in item for item in conditions)
    assert any("固定 Workflow" in item for item in conditions)


def test_executive_summary_bounds_all_analysis_summaries_without_dropping_coverage() -> None:
    summaries = [f"analysis_{index:03d}：" + "经营结论。" * 400 for index in range(1, 16)]

    result = reporting_sections._bounded_executive_summary(summaries)

    assert len(result) <= 8_000
    assert [result.index(f"analysis_{index:03d}") for index in range(1, 16)] == sorted(
        result.index(f"analysis_{index:03d}") for index in range(1, 16)
    )


def test_executive_summary_keeps_short_summaries_unchanged() -> None:
    assert reporting_sections._bounded_executive_summary(["收入增长。", "成本下降。"]) == (
        "收入增长。；成本下降。"
    )


def _inspection() -> ChartVisualInspectionReceipt:
    return ChartVisualInspectionReceipt(
        sourcePath="charts/chart.png",
        sha256="a" * 64,
        inspectionMode="vision",
        visualReviewStatus="passed",
        modelId="vision-test",
        reviewed=True,
        requiresRevision=False,
    )


@pytest.mark.anyio
async def test_visualization_workflow_orders_fixed_steps() -> None:
    events: list[str] = []
    plan = _visualization_plan()
    file_identity = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)

    async def generate_plan(_payload, _context):
        events.append("generate_plan")
        return plan

    async def generate_script(received_plan, _context, *, diagnostic):
        assert received_plan is plan
        assert diagnostic is None
        events.append("generate_script")
        return CodeGenerationResult(file_identity)

    async def execute(script_path, _context):
        events.append(f"execute:{script_path}")
        return {"exitCode": 0}

    async def inspect(chart, _context):
        assert chart is plan.charts[0]
        events.append(f"inspect:{chart.source_path}")
        return _inspection()

    async def submit(received_plan, _inspections, _context):
        assert received_plan is plan
        events.append("submit")
        return {"status": "accepted"}

    result = await VisualizationSectionWorkflow(
        generate_plan=generate_plan,
        generate_script=generate_script,
        repair_script=None,
        execute_script=execute,
        inspect_chart=inspect,
        submit=submit,
    ).run(_visualization_payload(), _context())

    assert result.status == "accepted"
    assert result.plan is plan
    assert events == [
        "generate_plan",
        "generate_script",
        "execute:charts/charts.py",
        "inspect:charts/chart.png",
        "submit",
    ]


@pytest.mark.anyio
async def test_visualization_workflow_submits_zero_charts_without_code_or_checks() -> None:
    plan = _visualization_plan(charts=())
    generate_script = AsyncMock()
    execute = AsyncMock()
    inspect = AsyncMock()
    submit = AsyncMock(return_value={"status": "committed"})

    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        generate_script=generate_script,
        repair_script=AsyncMock(),
        execute_script=execute,
        inspect_chart=inspect,
        submit=submit,
    ).run(_visualization_payload(), _context())

    assert result.plan is plan
    assert result.script_file is None
    assert result.inspections == ()
    generate_script.assert_not_awaited()
    execute.assert_not_awaited()
    inspect.assert_not_awaited()
    submit.assert_awaited_once_with(plan, (), ANY)


@pytest.mark.anyio
async def test_visualization_workflow_repairs_script_failure_once_with_frozen_plan() -> None:
    plan = _visualization_plan()
    execute = AsyncMock(
        side_effect=[
            {
                "ok": True,
                "status": "completed",
                "exitCode": 0,
                "output": "[FAIL] chart.png: image is blank",
            },
            {"ok": True, "status": "completed", "exitCode": 0, "output": "ok"},
        ]
    )
    initial_file = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    repaired_file = FileIdentity(path="charts/charts.py", size=2, sha256="b" * 64)
    repair = AsyncMock(return_value=CodeGenerationResult(repaired_file))
    submitted_plans: list[VisualizationPlanDraft] = []

    async def submit(received_plan, _inspections, _context):
        submitted_plans.append(received_plan)
        return {"status": "accepted"}

    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        generate_script=AsyncMock(return_value=CodeGenerationResult(initial_file)),
        repair_script=repair,
        execute_script=execute,
        inspect_chart=AsyncMock(return_value=_inspection()),
        submit=submit,
    ).run(_visualization_payload(), _context())

    assert result.recovery_used is True
    assert result.plan is plan
    assert result.script_file is repaired_file
    assert submitted_plans == [plan]
    repair.assert_awaited_once()
    repaired_from, diagnostic, task_facts, _ = repair.await_args.args
    assert repaired_from is initial_file
    assert diagnostic == {
        "code": "report_visualization_script_failed",
        "message": "可视化脚本执行失败。",
        "details": {
            "path": "charts/charts.py",
            "exitCode": 0,
            "output": "[FAIL] chart.png: image is blank",
        },
    }
    assert task_facts == {}
    assert execute.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure_code",
    ["report_code_generation_no_source", "report_python_source_shape_invalid"],
)
async def test_visualization_workflow_retries_initial_generation_with_frozen_plan(
    failure_code: str,
) -> None:
    plan = _visualization_plan()
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    generate_plan = AsyncMock(return_value=plan)
    generate_script = AsyncMock(
        side_effect=[
            ReportingError(
                failure_code,
                "生成失败",
                details={"size": 65537, "lineCount": 1, "maxLineLength": 65536},
            ),
            ReportingError(
                failure_code,
                "生成失败",
                details={"size": 65537, "lineCount": 1, "maxLineLength": 65536},
            ),
            CodeGenerationResult(script_file),
        ]
    )

    result = await VisualizationSectionWorkflow(
        generate_plan=generate_plan,
        generate_script=generate_script,
        repair_script=AsyncMock(),
        execute_script=AsyncMock(return_value={"exitCode": 0}),
        inspect_chart=None,
        submit=AsyncMock(return_value={"status": "accepted"}),
    ).run(_visualization_payload(), _context())

    assert result.plan is plan
    generate_plan.assert_awaited_once()
    assert generate_script.await_count == 3
    assert [call.args[0] for call in generate_script.await_args_list] == [plan, plan, plan]
    assert generate_script.await_args_list[0].kwargs["diagnostic"] is None
    assert [call.kwargs["diagnostic"]["code"] for call in generate_script.await_args_list[1:]] == [
        failure_code,
        failure_code,
    ]
    assert generate_script.await_args_list[1].kwargs["diagnostic"]["details"] == {
        "path": "charts/charts.py",
        "size": 65537,
        "lineCount": 1,
        "maxLineLength": 65536,
    }


@pytest.mark.anyio
async def test_visualization_workflow_hydrates_committed_script_without_regeneration() -> None:
    plan = _visualization_plan()
    script_file = FileIdentity(path="charts/charts.py", size=20, sha256="a" * 64)
    load_script = AsyncMock(return_value=script_file)
    generate_script = AsyncMock()

    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        generate_script=generate_script,
        repair_script=None,
        execute_script=AsyncMock(return_value={"exitCode": 0}),
        inspect_chart=AsyncMock(return_value=_inspection()),
        submit=AsyncMock(return_value={"status": "accepted"}),
        load_script=load_script,
    ).run(_visualization_payload(), _context())

    assert result.script_file is script_file
    load_script.assert_awaited_once_with("charts/charts.py", ANY)
    generate_script.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_workflow_repairs_visual_review_failure_once() -> None:
    initial_file = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    repaired_file = FileIdentity(path="charts/charts.py", size=2, sha256="b" * 64)
    failed_inspection = _inspection().model_copy(
        update={
            "visual_review_status": "failed",
            "requires_revision": True,
            "issues": (
                ChartVisualInspectionIssue(
                    category="text_overlap",
                    severity="critical",
                    description="图例遮挡横轴标签。",
                ),
            ),
        }
    )
    repair = AsyncMock(return_value=CodeGenerationResult(repaired_file))

    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        generate_script=AsyncMock(return_value=CodeGenerationResult(initial_file)),
        repair_script=repair,
        execute_script=AsyncMock(return_value={"exitCode": 0}),
        inspect_chart=AsyncMock(side_effect=[failed_inspection, _inspection()]),
        submit=AsyncMock(return_value={"status": "accepted"}),
    ).run(_visualization_payload(), _context())

    assert result.recovery_used is True
    repair.assert_awaited_once()
    _, diagnostic, task_facts, _ = repair.await_args.args
    assert diagnostic == {
        "code": "report_visualization_review_failed",
        "message": "图表正式审查未通过。",
        "details": {"path": "charts/charts.py"},
    }
    assert task_facts == {
        "inspections": [
            {
                "sourcePath": "charts/chart.png",
                "visualReviewStatus": "failed",
                "requiresRevision": True,
                "issues": [
                    {
                        "category": "text_overlap",
                        "severity": "critical",
                        "description": "图例遮挡横轴标签。",
                    }
                ],
                "summary": None,
                "warnings": [],
                "suggestions": [],
            }
        ]
    }


@pytest.mark.anyio
async def test_visualization_workflow_recovers_missing_chart_file_with_compact_payload() -> None:
    plan = _visualization_plan()
    initial_file = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    repaired_file = FileIdentity(path="charts/charts.py", size=2, sha256="b" * 64)
    repair_payloads: list[dict[str, object]] = []
    events: list[str] = []

    async def repair(script_file, diagnostic, task_facts, _context):
        assert script_file is initial_file
        repair_payloads.append({"diagnostic": dict(diagnostic), "taskFacts": dict(task_facts)})
        events.append("repair")
        return CodeGenerationResult(repaired_file)

    async def execute(_path, _context):
        events.append("execute")
        return {"exitCode": 0}

    async def inspect(_chart, _context):
        events.append("inspect")
        return _inspection()

    async def submit(received_plan, _inspections, _context):
        assert received_plan is plan
        events.append("submit")
        if events.count("submit") == 1:
            return {
                "ok": False,
                "status": "rejected",
                "code": "report_chart_file_missing",
                "message": "图表源文件不存在;未生成的图表不得提交登记。",
                "details": {"sourcePath": "charts/chart.png"},
            }
        return {"ok": True, "status": "accepted"}

    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        generate_script=AsyncMock(return_value=CodeGenerationResult(initial_file)),
        repair_script=repair,
        execute_script=execute,
        inspect_chart=inspect,
        submit=submit,
    ).run(_visualization_payload(), _context())

    assert result.status == "accepted"
    assert result.recovery_used is True
    assert events == [
        "execute",
        "inspect",
        "submit",
        "repair",
        "execute",
        "inspect",
        "submit",
    ]
    assert repair_payloads == [
        {
            "diagnostic": {
                "code": "report_chart_file_missing",
                "message": "图表源文件不存在;未生成的图表不得提交登记。",
                "details": {"path": "charts/chart.png"},
            },
            "taskFacts": {
                "missingCharts": [
                    {
                        "chartId": "chart_001",
                        "sourcePath": "charts/chart.png",
                        "title": "收入趋势",
                    }
                ]
            },
        }
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("failure_kind", ["missing_chart", "visual_review"])
async def test_visualization_repair_adapter_preserves_restricted_task_facts_in_runner_prompt(
    failure_kind: str,
) -> None:
    source = "value = 1\nprint(value)\n"
    script_file = FileIdentity(
        path="charts/charts.py",
        size=len(source.encode()),
        sha256=hashlib.sha256(source.encode()).hexdigest(),
    )
    prompts: list[dict[str, object]] = []

    class FakeAgent:
        def __init__(self) -> None:
            self.tools: list[object] = []
            self.tool_choice: object | None = None

        async def arun(self, prompt: str, **_kwargs: object) -> object:
            tool = self.tools[0]
            if tool.name == "read_file":
                return await tool.entrypoint(path=script_file.path)
            prompts.append(json.loads(prompt))
            return await tool.entrypoint(source=source)

    async def read_file(**_kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "path": script_file.path,
            "content": source,
            "sha256": script_file.sha256,
            "offset": 0,
            "nextOffset": script_file.size,
            "totalBytes": script_file.size,
        }

    async def apply_patch(**_kwargs: object) -> dict[str, object]:
        return {
            "ok": True,
            "artifacts": [
                {
                    "path": script_file.path,
                    "size": len(source.encode()),
                    "sha256": script_file.sha256,
                }
            ],
        }

    runner = ReportingCodeGenerationRunner(agent_factory=FakeAgent)

    async def repair(script, diagnostic, task_facts, context):
        return await runner.repair(
            script,
            diagnostic,
            read_file,
            apply_patch,
            context,
            task_facts=task_facts,
        )

    failed_inspection = _inspection().model_copy(
        update={
            "visual_review_status": "failed",
            "requires_revision": True,
            "issues": (
                ChartVisualInspectionIssue(
                    category="text_overlap",
                    severity="critical",
                    description="图例遮挡横轴标签。",
                ),
            ),
        }
    )
    missing_receipt = {
        "status": "rejected",
        "code": "report_chart_file_missing",
        "message": "图表源文件不存在。",
        "details": {"sourcePath": "charts/chart.png"},
    }
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        generate_script=AsyncMock(return_value=CodeGenerationResult(script_file)),
        repair_script=repair,
        execute_script=AsyncMock(return_value={"exitCode": 0}),
        inspect_chart=(
            None
            if failure_kind == "missing_chart"
            else AsyncMock(side_effect=[failed_inspection, _inspection()])
        ),
        submit=AsyncMock(
            side_effect=([missing_receipt, {"status": "accepted"}])
            if failure_kind == "missing_chart"
            else [{"status": "accepted"}]
        ),
    )

    await workflow.run(_visualization_payload(), _context())

    assert len(prompts) == 1
    task_facts = prompts[0]["facts"]["taskFacts"]
    if failure_kind == "missing_chart":
        assert task_facts == {
            "missingCharts": [
                {
                    "chartId": "chart_001",
                    "sourcePath": "charts/chart.png",
                    "title": "收入趋势",
                }
            ]
        }
    else:
        assert task_facts == {
            "inspections": [
                {
                    "sourcePath": "charts/chart.png",
                    "visualReviewStatus": "failed",
                    "requiresRevision": True,
                    "issues": [
                        {
                            "category": "text_overlap",
                            "severity": "critical",
                            "description": "图例遮挡横轴标签。",
                        }
                    ],
                    "warnings": [],
                    "suggestions": [],
                }
            ]
        }
        assert "modelId" not in json.dumps(task_facts)
        assert "sha256" not in json.dumps(task_facts)


@pytest.mark.anyio
async def test_visualization_workflow_propagates_second_missing_chart_file_without_retrying() -> (
    None
):
    missing_chart = {
        "ok": False,
        "status": "rejected",
        "code": "report_chart_file_missing",
        "message": "图表源文件不存在;未生成的图表不得提交登记。",
        "details": {"sourcePath": "charts/chart.png"},
    }
    initial_file = FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
    repair = AsyncMock(return_value=CodeGenerationResult(initial_file))
    execute = AsyncMock(return_value={"exitCode": 0})
    submit = AsyncMock(side_effect=[missing_chart, missing_chart])

    with pytest.raises(ReportingError) as caught:
        await VisualizationSectionWorkflow(
            generate_plan=AsyncMock(return_value=_visualization_plan()),
            generate_script=AsyncMock(return_value=CodeGenerationResult(initial_file)),
            repair_script=repair,
            execute_script=execute,
            inspect_chart=None,
            submit=submit,
        ).run(_visualization_payload(), _context())

    assert caught.value.code == "report_chart_file_missing"
    repair.assert_awaited_once()
    assert execute.await_count == 2
    assert submit.await_count == 2


@pytest.mark.anyio
async def test_visualization_workflow_does_not_recover_artifact_change() -> None:
    repair = AsyncMock()
    with pytest.raises(ReportingError) as caught:
        await VisualizationSectionWorkflow(
            generate_plan=AsyncMock(return_value=_visualization_plan()),
            generate_script=AsyncMock(
                side_effect=ReportingError("report_phase_artifact_changed", "SHA changed")
            ),
            repair_script=repair,
            execute_script=AsyncMock(),
            inspect_chart=AsyncMock(),
            submit=AsyncMock(),
        ).run(_visualization_payload(), _context())
    assert caught.value.code == "report_phase_artifact_changed"
    repair.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_workflow_does_not_repair_nonretryable_error() -> None:
    repair = AsyncMock()

    with pytest.raises(ReportingError) as caught:
        await VisualizationSectionWorkflow(
            generate_plan=AsyncMock(return_value=_visualization_plan()),
            generate_script=AsyncMock(
                return_value=CodeGenerationResult(
                    FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
                )
            ),
            repair_script=repair,
            execute_script=AsyncMock(return_value={"exitCode": 0}),
            inspect_chart=None,
            submit=AsyncMock(
                return_value={
                    "status": "rejected",
                    "code": "report_visualization_submit_rejected",
                    "message": "提交不可重试。",
                    "retryable": False,
                }
            ),
        ).run(_visualization_payload(), _context())

    assert caught.value.code == "report_visualization_submit_rejected"
    repair.assert_not_awaited()


@pytest.mark.anyio
async def test_visualization_workflow_allows_deterministic_submission_without_vision() -> None:
    submit = AsyncMock(return_value={"status": "committed"})
    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        generate_script=AsyncMock(
            return_value=CodeGenerationResult(
                FileIdentity(path="charts/charts.py", size=1, sha256="a" * 64)
            )
        ),
        repair_script=None,
        execute_script=AsyncMock(return_value={"exitCode": 0}),
        inspect_chart=None,
        submit=submit,
    ).run(_visualization_payload(), _context())

    assert result.status == "accepted"
    assert result.inspections == ()
    submit.assert_awaited_once()


_SECTION_EVIDENCE_CONTENT = "证据正文"
_SECTION_EVIDENCE_BYTES = _SECTION_EVIDENCE_CONTENT.encode("utf-8")
_SECTION_EVIDENCE_SHA256 = hashlib.sha256(_SECTION_EVIDENCE_BYTES).hexdigest()


def _section_evidence_receipt(*, next_offset: int | None = None) -> dict[str, object]:
    return {
        "path": "evidence/a.json",
        "offset": 0,
        "nextOffset": len(_SECTION_EVIDENCE_BYTES) if next_offset is None else next_offset,
        "totalBytes": len(_SECTION_EVIDENCE_BYTES),
        "content": _SECTION_EVIDENCE_CONTENT,
        "hasMore": False if next_offset is None else True,
        "sha256": _SECTION_EVIDENCE_SHA256,
    }


def _section_work_item() -> SectionWorkItem:
    identity = FileIdentity(
        path="evidence/a.json",
        size=len(_SECTION_EVIDENCE_BYTES),
        sha256=_SECTION_EVIDENCE_SHA256,
    )
    evidence = AnalysisEvidence(
        analysisId="analysis_001",
        summary="summary",
        datasetIds=("dataset_001",),
        evidenceFiles=(identity,),
        citationIds=("citation_001",),
    )
    return SectionWorkItem(
        sectionCode="section_001",
        sectionNumber="1",
        title="收入",
        objective="目标",
        completionConditions=("完成",),
        analysisIds=("analysis_001",),
        evidence=(evidence,),
        citations=(
            SectionCitation(
                citationId="citation_001",
                datasetId="dataset_001",
                requirementId="requirement_001",
                snapshotHash="a" * 64,
            ),
        ),
        factSummaries=("事实摘要",),
        markdownRequirements=("markdown",),
    )


def test_section_block_input_budget_uses_final_routed_model() -> None:
    context = _context()
    context.dependencies = {
        REPORTING_TASK_DEPENDENCY: {
            REPORTING_MODEL_TIER_DEPENDENCY_KEY: "fast",
            REPORTING_MODEL_ID_DEPENDENCY_KEY: "qwen3.8-35b-a3b",
        }
    }
    agent = SimpleNamespace(
        model=SimpleNamespace(
            id="unknown-initial-model",
            _task_execution_input_token_budget=300 * 1024,
        )
    )

    assert reporting_sections._section_block_input_token_budget(agent, context) == 224 * 1024


@pytest.mark.anyio
async def test_section_generation_plans_then_renders_each_block_serially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_item = _section_work_item().model_copy(
        update={
            "metric_definitions": (
                MetricDefinition(
                    code="revenue",
                    name="收入",
                    definition="收入合计",
                    unit="元",
                    periodBasis="2025年",
                ),
            ),
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
            ),
        }
    )
    evidence = SectionEvidenceBundle(
        sectionCode="section_001",
        files=(
            SectionEvidenceFile(
                identity=work_item.evidence[0].evidence_files[0],
                content='{"收入":100}',
            ),
        ),
        factSummaries=("收入为100元",),
    )
    stages: list[str] = []

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        stages.append(stage)
        if stage == "plan":
            assert "evidence" not in payload
            return SectionPlanOutput.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {
                            "blockId": "block_001",
                            "objective": "说明收入规模",
                            "claimIds": ["claim_001"],
                        },
                        {
                            "blockId": "block_002",
                            "objective": "解释管理影响",
                            "claimIds": ["claim_001"],
                        },
                    ],
                    "claims": [
                        {
                            "claimId": "claim_001",
                            "metricCode": "revenue",
                            "value": 100,
                            "managementQuestionRef": "analysis_001",
                            "currentPeriod": "2025年",
                            "citationIds": ["citation_001"],
                        }
                    ],
                }
            )
        assert payload["evidence"]["files"][0]["content"] == '{"收入":100}'
        return SectionBlockContent(
            markdown=f"### {payload['blockPlan']['objective']}\n\n收入为100元。"
        )

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)

    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {
            "reportGoal": "分析2025年收入",
            "sectionGoal": {"sectionCode": "section_001"},
            "sectionWorkItem": work_item.model_dump(mode="json", by_alias=True),
        },
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
    )

    assert stages == ["plan", "block-1", "block-2"]
    assert isinstance(result, RenderSectionDecision)
    assert tuple(block.block_id for block in result.blocks) == ("block_001", "block_002")
    assert all(block.claim_ids == ("claim_001",) for block in result.blocks)


@pytest.mark.anyio
async def test_section_generation_locally_regenerates_block_with_missing_heading_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_item = _section_work_item().model_copy(
        update={
            "metric_definitions": (
                MetricDefinition(
                    code="revenue",
                    name="收入",
                    definition="收入合计",
                    unit="元",
                    periodBasis="2025年",
                ),
            ),
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
            ),
        }
    )
    evidence = SectionEvidenceBundle(
        sectionCode="section_001",
        files=(
            SectionEvidenceFile(
                identity=work_item.evidence[0].evidence_files[0],
                content='{"收入":100}',
            ),
        ),
        factSummaries=("收入为100元",),
    )
    stages: list[str] = []
    block_payloads: list[dict[str, object]] = []

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        stages.append(stage)
        if stage == "plan":
            return SectionPlanOutput.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {
                            "blockId": "block_001",
                            "objective": "说明收入规模",
                            "claimIds": ["claim_001"],
                        },
                        {
                            "blockId": "block_002",
                            "objective": "解释管理影响",
                            "claimIds": ["claim_001"],
                        },
                    ],
                    "claims": [
                        {
                            "claimId": "claim_001",
                            "metricCode": "revenue",
                            "value": 100,
                            "managementQuestionRef": "analysis_001",
                            "currentPeriod": "2025年",
                            "citationIds": ["citation_001"],
                        }
                    ],
                }
            )
        block_payloads.append(dict(payload))
        if len(block_payloads) == 1:
            return SectionBlockContent(markdown="#### 收入规模\n\n收入为100元。")
        if len(block_payloads) == 2:
            correction = payload["correction"]
            assert correction == {
                "attempt": 1,
                "code": "report_draft_heading_parent_missing",
                "issues": [
                    {
                        "path": "$.blocks[0].markdown",
                        "type": "heading_parent_missing",
                        "message": "H4 标题必须位于当前章节的 H3 标题之后。",
                    }
                ],
                "previousOutput": {"markdown": "#### 收入规模\n\n收入为100元。"},
                "requiredAction": (
                    "仅修正 issues 指向的当前 block；在 output_schema.markdown 字段中返回完整正文，"
                    "保留其余有效内容，不得返回解释、代码围栏或 schema 外字段。"
                ),
            }
            return SectionBlockContent(markdown="### 收入规模\n\n收入为100元。")
        assert "correction" not in payload
        return SectionBlockContent(markdown="#### 管理影响\n\n收入表现稳定。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)

    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {
            "reportGoal": "分析2025年收入",
            "sectionGoal": {"sectionCode": "section_001"},
            "sectionWorkItem": work_item.model_dump(mode="json", by_alias=True),
        },
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
    )

    assert stages == ["plan", "block-1", "block-1", "block-2"]
    assert result.blocks[0].markdown.startswith("### ")
    assert result.blocks[1].markdown.startswith("#### ")


@pytest.mark.anyio
async def test_section_generation_corrects_plan_references_before_rendering_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work_item = _section_work_item().model_copy(
        update={
            "metric_definitions": (
                MetricDefinition(
                    code="revenue",
                    name="收入",
                    definition="收入合计",
                    unit="元",
                    periodBasis="2025年",
                ),
            ),
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
            ),
        }
    )
    evidence = SectionEvidenceBundle(
        sectionCode="section_001",
        files=(
            SectionEvidenceFile(
                identity=work_item.evidence[0].evidence_files[0],
                content='{"收入":100}',
            ),
        ),
        factSummaries=("收入为100元",),
    )
    stages: list[str] = []

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        stages.append(stage)
        if stage == "plan":
            metric_code = "invented_revenue" if stages.count("plan") == 1 else "revenue"
            if stages.count("plan") == 2:
                correction = payload["correction"]
                assert correction["code"] == "report_section_plan_reference_invalid"
                assert correction["issues"] == [
                    {
                        "path": "$.claims[0].metricCode",
                        "type": "unknown_metric_code",
                        "message": "metricCode 必须来自当前 SectionWorkItem。",
                        "allowedValues": ["revenue"],
                    }
                ]
            return SectionPlanOutput.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {
                            "blockId": "block_001",
                            "objective": "说明收入规模",
                            "claimIds": ["claim_001"],
                        }
                    ],
                    "claims": [
                        {
                            "claimId": "claim_001",
                            "metricCode": metric_code,
                            "value": 100,
                            "managementQuestionRef": "analysis_001",
                            "currentPeriod": "2025年",
                            "citationIds": ["citation_001"],
                        }
                    ],
                }
            )
        return SectionBlockContent(markdown="### 收入规模\n\n收入为100元。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)

    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {
            "reportGoal": "分析2025年收入",
            "sectionGoal": {"sectionCode": "section_001"},
            "sectionWorkItem": work_item.model_dump(mode="json", by_alias=True),
        },
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
    )

    assert stages == ["plan", "plan", "block-1"]
    assert result.claims[0].metric_code == "revenue"


@pytest.mark.anyio
async def test_section_generation_projects_relevant_json_and_text_evidence_per_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_content = json.dumps(
        {
            "rows": [
                *(
                    {
                        "metric": "成本",
                        "period": "2025年",
                        "value": 80 + index,
                        "record": index,
                    }
                    for index in range(400)
                ),
                {"metric": "收入", "period": "2025年", "value": 100, "unit": "元"},
                {"metric": "门诊量", "period": "2025年", "value": 9000},
            ],
            "unrelated_blob": "x" * 40_000,
        },
        ensure_ascii=False,
    )
    text_content = "\n".join(
        [
            *(f"完全无关的历史记录 {index}" for index in range(30)),
            "2025年收入事实如下。",
            "收入为100元。",
            "同比口径与当前管理问题一致。",
            *(f"完全无关的附录记录 {index}" for index in range(30)),
        ]
    )
    json_identity = FileIdentity(
        path="evidence/revenue.json", size=len(json_content.encode()), sha256="a" * 64
    )
    text_identity = FileIdentity(
        path="evidence/revenue.txt", size=len(text_content.encode()), sha256="b" * 64
    )
    evidence_item = AnalysisEvidence(
        analysisId="analysis_001",
        summary="2025年收入为100元",
        datasetIds=("dataset_001",),
        evidenceFiles=(json_identity, text_identity),
        citationIds=("citation_001",),
        metrics=("revenue",),
        chartIds=("chart_001",),
    )
    chart = AnalysisChart(
        chartId="chart_001",
        sourceFile=FileIdentity(path="charts/revenue.png", size=1024, sha256="c" * 64),
        title="2025年收入趋势",
        altText="2025年收入趋势图",
        citationIds=("citation_001",),
        metricCodes=("revenue",),
        currentPeriod="2025年",
        sourceDatasetId="dataset_001",
        aggregationGrain="month",
    )
    work_item = _section_work_item().model_copy(
        update={
            "evidence": (evidence_item,),
            "charts": (chart,),
            "metric_definitions": (
                MetricDefinition(
                    code="revenue",
                    name="收入",
                    definition="收入合计",
                    unit="元",
                    periodBasis="2025年",
                ),
            ),
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
            ),
        }
    )
    evidence = SectionEvidenceBundle(
        sectionCode="section_001",
        files=(
            SectionEvidenceFile(identity=json_identity, content=json_content),
            SectionEvidenceFile(identity=text_identity, content=text_content),
        ),
        factSummaries=("2025年收入为100元",),
    )
    block_payloads: list[dict[str, object]] = []

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        if stage == "plan":
            return SectionPlanOutput.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {
                            "blockId": "block_001",
                            "objective": "解释2025年收入表现",
                            "claimIds": ["claim_001"],
                        }
                    ],
                    "claims": [
                        {
                            "claimId": "claim_001",
                            "metricCode": "revenue",
                            "value": 100,
                            "managementQuestionRef": "analysis_001",
                            "currentPeriod": "2025年",
                            "citationIds": ["citation_001"],
                            "chartIds": ["chart_001"],
                        }
                    ],
                }
            )
        block_payloads.append(payload)
        return SectionBlockContent(markdown="### 收入表现\n\n2025年收入为100元。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)
    agent = SimpleNamespace(model=SimpleNamespace(_task_execution_input_token_budget=16 * 1024))

    for _ in range(2):
        await reporting_sections._generate_section_in_blocks(
            agent,
            {
                "reportGoal": "分析2025年收入",
                "sectionGoal": {"sectionCode": "section_001"},
                "sectionWorkItem": work_item.model_dump(mode="json", by_alias=True),
            },
            evidence,
            work_item,
            scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
            run_context=_context(),
        )

    assert len(block_payloads) == 2
    assert block_payloads[0]["evidence"] == block_payloads[1]["evidence"]
    payload = block_payloads[0]
    evidence_view = payload["evidence"]
    files = evidence_view["files"]
    assert [item["identity"]["path"] for item in files] == [
        "evidence/revenue.json",
        "evidence/revenue.txt",
    ]
    assert all(item["identity"]["sha256"] in {"a" * 64, "b" * 64} for item in files)
    assert '"metric":"收入"' in files[0]["content"]
    assert "unrelated_blob" not in files[0]["content"]
    assert "收入为100元" in files[1]["content"]
    assert "同比口径" in files[1]["content"]
    assert "完全无关的历史记录 0" not in files[1]["content"]
    assert evidence_view["factSummaries"] == ["2025年收入为100元"]
    assert payload["facts"][0]["summary"] == "2025年收入为100元"
    assert payload["citations"][0]["citationId"] == "citation_001"
    assert payload["charts"][0]["chartId"] == "chart_001"
    assert len(json.dumps(payload, ensure_ascii=False)) < len(json_content) + len(text_content)


def test_section_evidence_projection_accounts_for_outer_json_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_content = json.dumps(
        {"rows": [{"metric": "收入", "period": "2025年", "value": index} for index in range(120)]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    second_content = json.dumps(
        {
            "rows": [
                {
                    "metric": "收入",
                    "period": "2024年",
                    "value": index,
                    "note": 'C:\\income\\"quoted"',
                }
                for index in range(80)
            ]
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    first_identity = FileIdentity(
        path="evidence/revenue.json",
        size=len(first_content.encode()),
        sha256=hashlib.sha256(first_content.encode()).hexdigest(),
    )
    second_identity = FileIdentity(
        path="evidence/revenue-baseline.json",
        size=len(second_content.encode()),
        sha256=hashlib.sha256(second_content.encode()).hexdigest(),
    )
    evidence_files = (
        SectionEvidenceFile(identity=first_identity, content=first_content),
        SectionEvidenceFile(identity=second_identity, content=second_content),
    )
    evidence_token_budget = 512
    monkeypatch.setattr(
        reporting_sections,
        "_section_block_evidence_token_budget",
        lambda *_args, **_kwargs: evidence_token_budget,
    )

    projected = reporting_sections._project_section_evidence_files(
        SimpleNamespace(),
        evidence_files,
        fact_summaries=("收入事实",),
        relevance_values=("收入",),
        base_payload={"phase": "section"},
        run_context=_context(),
    )

    projected_files = projected["files"]
    assert [item["identity"] for item in projected_files] == [
        identity.model_dump(mode="json", by_alias=True)
        for identity in (first_identity, second_identity)
    ]
    assert all("收入" in item["content"] for item in projected_files)
    assert (
        sum(
            reporting_sections._estimated_section_tokens(reporting_sections._json_text(item))
            for item in projected_files
        )
        <= evidence_token_budget
    )


def test_section_evidence_projection_bounds_plateau_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = FileIdentity(path="evidence/a.json", size=1, sha256="a" * 64)
    evidence_file = SectionEvidenceFile(identity=identity, content='{"metric":"收入"}')
    evidence_token_budget = 256
    attempted_budgets: list[int] = []

    def project_with_plateau(_content, _matcher, *, token_budget):
        attempted_budgets.append(token_budget)
        if token_budget > 196:
            return "x" * 840, {"format": "json_paths", "truncated": True}
        return "收入", {"format": "json_paths", "truncated": True}

    monkeypatch.setattr(
        reporting_sections,
        "_section_block_evidence_token_budget",
        lambda *_args, **_kwargs: evidence_token_budget,
    )
    monkeypatch.setattr(reporting_sections, "_project_json_evidence", project_with_plateau)

    projected = reporting_sections._project_section_evidence_files(
        SimpleNamespace(),
        (evidence_file,),
        fact_summaries=("收入事实",),
        relevance_values=("收入",),
        base_payload={"phase": "section"},
        run_context=_context(),
    )

    assert projected["files"][0]["content"] == "收入"
    assert len(attempted_budgets) <= 16


@pytest.mark.anyio
async def test_section_workflow_reads_evidence_before_generation() -> None:
    events: list[str] = []

    async def read(path, offset, _context):
        events.append(f"read:{path}:{offset}")
        return _section_evidence_receipt()

    async def generate(bundle, _context):
        events.append("generate")
        assert bundle.files[0].content == "证据正文"
        return RenderSectionDecision.model_construct(
            section_code="section_001", blocks=(), claims=()
        )

    async def render(_decision, _context):
        events.append("render")
        return {"status": "accepted"}

    result = await SectionWorkflow(
        read_evidence=read,
        generate=generate,
        recover=None,
        render=render,
        rework=AsyncMock(),
    ).run(_section_work_item(), _context())
    assert result.status == "accepted"
    assert events == ["read:evidence/a.json:0", "generate", "render"]


@pytest.mark.anyio
async def test_section_workflow_reads_duplicate_frozen_identity_once() -> None:
    work_item = _section_work_item()
    duplicate = AnalysisEvidence(
        analysisId="analysis_002",
        summary="同一冻结证据的另一个管理问题",
        datasetIds=("dataset_001",),
        evidenceFiles=(work_item.evidence[0].evidence_files[0],),
        citationIds=("citation_001",),
    )
    work_item = work_item.model_copy(
        update={
            "analysis_ids": ("analysis_001", "analysis_002"),
            "evidence": (*work_item.evidence, duplicate),
        }
    )
    read = AsyncMock(return_value=_section_evidence_receipt())

    await SectionWorkflow(
        read_evidence=read,
        generate=AsyncMock(
            return_value=RenderSectionDecision.model_construct(
                section_code="section_001", blocks=(), claims=()
            )
        ),
        recover=None,
        render=AsyncMock(return_value={"status": "accepted"}),
        rework=AsyncMock(),
    ).run(work_item, _context())

    assert read.await_count == 1
    assert read.await_args.args[:2] == ("evidence/a.json", 0)


@pytest.mark.anyio
async def test_section_workflow_rejects_conflicting_frozen_identity_before_read() -> None:
    work_item = _section_work_item()
    conflicting = AnalysisEvidence(
        analysisId="analysis_002",
        summary="冲突身份",
        datasetIds=("dataset_001",),
        evidenceFiles=(FileIdentity(path="evidence/a.json", size=9, sha256="b" * 64),),
        citationIds=("citation_001",),
    )
    work_item = work_item.model_copy(
        update={
            "analysis_ids": ("analysis_001", "analysis_002"),
            "evidence": (*work_item.evidence, conflicting),
        }
    )
    read = AsyncMock(return_value={"content": "证据正文", "nextOffset": None})

    with pytest.raises(ReportingError) as caught:
        await SectionWorkflow(
            read_evidence=read,
            generate=AsyncMock(),
            recover=None,
            render=AsyncMock(),
            rework=AsyncMock(),
        ).run(work_item, _context())

    assert caught.value.code == "report_section_evidence_invalid"
    read.assert_not_awaited()


@pytest.mark.anyio
async def test_section_workflow_preserves_rejection_details_for_recovery() -> None:
    rejected = {
        "status": "rejected",
        "code": "report_analysis_rework_unresolvable",
        "message": "零行数据无法通过返工补算。",
        "requiredActions": ["提交受限 claim。"],
    }

    async def recover(repair, _context):
        assert set(repair) == {"diagnostic"}
        assert repair["diagnostic"]["code"] == "report_analysis_rework_unresolvable"
        assert repair["diagnostic"]["details"] == rejected
        return RenderSectionDecision.model_construct(
            section_code="section_001", blocks=(), claims=()
        )

    result = await SectionWorkflow(
        read_evidence=AsyncMock(return_value=_section_evidence_receipt()),
        generate=AsyncMock(
            return_value=AnalysisReworkDecision(
                sectionCode="section_001",
                analysisIds=("analysis_001",),
                reason="缺少月度收入事实",
                missingEvidence=("月度收入事实",),
            )
        ),
        recover=recover,
        render=AsyncMock(return_value={"status": "accepted"}),
        rework=AsyncMock(return_value=rejected),
    ).run(_section_work_item(), _context())

    assert result.status == "accepted"
    assert result.recovery_used is True


@pytest.mark.anyio
async def test_section_workflow_does_not_recover_nonretryable_submission() -> None:
    recover = AsyncMock()
    rejected = {
        "ok": False,
        "status": "rejected",
        "code": "report_draft_protocol_injection",
        "message": "正文不得自行包含协议标记。",
        "details": {"path": "$.blocks[0].markdown"},
        "retryable": False,
    }

    with pytest.raises(ReportingError) as caught:
        await SectionWorkflow(
            read_evidence=AsyncMock(return_value=_section_evidence_receipt()),
            generate=AsyncMock(
                return_value=RenderSectionDecision.model_construct(
                    section_code="section_001", blocks=(), claims=()
                )
            ),
            recover=recover,
            render=AsyncMock(return_value=rejected),
            rework=AsyncMock(),
        ).run(_section_work_item(), _context())

    assert caught.value.code == "report_draft_protocol_injection"
    assert caught.value.details == rejected
    recover.assert_not_awaited()


@pytest.mark.anyio
async def test_section_workflow_recovers_when_initial_generation_is_invalid() -> None:
    recover = AsyncMock(
        return_value=RenderSectionDecision.model_construct(
            section_code="section_001", blocks=(), claims=()
        )
    )
    generate = AsyncMock(side_effect=ReportingError("report_phase_output_invalid", "invalid"))

    result = await SectionWorkflow(
        read_evidence=AsyncMock(return_value=_section_evidence_receipt()),
        generate=generate,
        recover=recover,
        render=AsyncMock(return_value={"status": "accepted"}),
        rework=AsyncMock(),
    ).run(_section_work_item(), _context())

    assert result.status == "accepted"
    assert result.recovery_used is True
    recover.assert_awaited_once()
    assert set(recover.await_args.args[0]) == {"diagnostic"}
    assert recover.await_args.args[0]["diagnostic"]["code"] == "report_phase_output_invalid"


@pytest.mark.anyio
async def test_section_workflow_rejects_non_progressing_evidence_offset() -> None:
    with pytest.raises(ReportingError, match="续读 offset"):
        await SectionWorkflow(
            read_evidence=AsyncMock(return_value=_section_evidence_receipt(next_offset=0)),
            generate=AsyncMock(),
            recover=None,
            render=AsyncMock(),
            rework=AsyncMock(),
        ).run(_section_work_item(), _context())


@pytest.mark.anyio
async def test_section_workflow_rejects_evidence_receipt_without_frozen_hash() -> None:
    receipt = _section_evidence_receipt()
    receipt.pop("sha256")

    with pytest.raises(ReportingError) as caught:
        await SectionWorkflow(
            read_evidence=AsyncMock(return_value=receipt),
            generate=AsyncMock(),
            recover=None,
            render=AsyncMock(),
            rework=AsyncMock(),
        ).run(_section_work_item(), _context())

    assert caught.value.code == "report_phase_artifact_changed"
