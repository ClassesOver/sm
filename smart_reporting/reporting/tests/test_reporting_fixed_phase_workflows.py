import hashlib
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.agent import Agent
from agno.run import RunContext
from loguru import logger
from pydantic import ValidationError

from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.code_agent.context import ExecutionReceipt
from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)
from smart_reporting.reporting.model_policy import (
    ThinkingRequest,
    select_reporting_thinking,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
)
from smart_reporting.reporting.workflow.benchmark_variants import (
    BenchmarkProjection,
    BenchmarkVariant,
    LegacyAnalysisEvidenceDecision,
)
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisChart,
    AnalysisEvidence,
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
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisItemWorkflow,
    _AnalysisItemState,
)
from smart_reporting.reporting.workflow.runtime.base import (
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_WORKFLOW_RESULT_STATE_KEY,
)
from smart_reporting.reporting.workflow.runtime.code_generation import (
    CodeGenerationResult,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    AnalysisReworkDecision,
    ChartDraft,
    RenderSectionDecision,
    RenderSectionPlan,
    SectionBlockContent,
    SectionContent,
    SectionEvidenceBundle,
    SectionEvidenceFile,
    SectionPlanOutput,
    VisualizationPlanDraft,
)
from smart_reporting.reporting.workflow.runtime.section_workflow import SectionWorkflow
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
    _code_failure_kind,
    _validated_visual_receipts,
    _visualization_thinking_complexity,
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
        visualForm="按月折线图",
        dataBindings=(
            {
                "analysisId": "analysis_001",
                "factPath": "facts/analysis_001.json",
                "dataPath": "metrics[0].periodValues",
                "fields": ["period", "value"],
                "role": "月度趋势",
            },
        ),
    )


def _visualization_plan(*, charts: tuple[ChartDraft, ...] | None = None) -> VisualizationPlanDraft:
    return VisualizationPlanDraft(charts=(_chart(),) if charts is None else charts)


def _visualization_payload() -> dict[str, object]:
    return {
        "visualizationWorkspace": {"scriptPath": "charts/charts.py"},
        "visualizationFacts": [
            {
                "analysisId": "analysis_001",
                "factFile": {"path": "facts/analysis_001.json"},
                "dataDescriptors": [
                    {
                        "dataPath": "metrics[0].periodValues",
                        "fields": ["period", "value"],
                    }
                ],
            }
        ],
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("factPath", "facts/other.json"),
        ("dataPath", "metrics[9].periodValues"),
    ],
    ids=("fact-path", "data-path"),
)
async def test_visualization_workflow_autocorrects_retargetable_binding_mismatch(
    field: str, value: object
) -> None:
    """字段集合与签发描述唯一匹配时，planner 签错 factPath/dataPath 自动改指并继续。"""
    chart_payload = _chart().model_dump(mode="json", by_alias=True)
    chart_payload["dataBindings"][0][field] = value
    plan = VisualizationPlanDraft(charts=(ChartDraft.model_validate(chart_payload),))
    code_result = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection(),),
    )
    submit = AsyncMock(return_value={"status": "accepted"})
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        run_code=AsyncMock(return_value=code_result),
        submit=submit,
    )

    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        result = await workflow.run(_visualization_payload(), _context())
    finally:
        logger.remove(sink_id)

    assert result.status == "accepted"
    assert result.inspections == (_inspection(),)
    corrected_binding = result.plan.charts[0].data_bindings[0]
    assert corrected_binding.fact_path == "facts/analysis_001.json"
    assert corrected_binding.data_path == "metrics[0].periodValues"
    warnings = [
        message
        for message in messages
        if "report_visualization_binding_autocorrected" in str(message)
    ]
    assert len(warnings) == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("analysisId", "analysis_unknown"),
        ("fields", ["period", "unknown"]),
    ],
    ids=("analysis", "field"),
)
async def test_visualization_workflow_warns_on_uncorrectable_binding_mismatch(
    field: str, value: object
) -> None:
    """无法按字段唯一改指的错配保持软告警继续（生产三跑实证：硬拒会耗尽
    fresh attempt；执行层 AST/指令/修复回执兜底）。"""
    chart_payload = _chart().model_dump(mode="json", by_alias=True)
    chart_payload["dataBindings"][0][field] = value
    plan = VisualizationPlanDraft(charts=(ChartDraft.model_validate(chart_payload),))
    code_result = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection(),),
    )
    submit = AsyncMock(return_value={"status": "accepted"})
    workflow = VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=plan),
        run_code=AsyncMock(return_value=code_result),
        submit=submit,
    )

    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        result = await workflow.run(_visualization_payload(), _context())
    finally:
        logger.remove(sink_id)

    assert result.status == "accepted"
    warnings = [
        message for message in messages if "report_visualization_binding_mismatch" in str(message)
    ]
    assert len(warnings) == 1
    extra = warnings[0].record["extra"]
    expected_descriptors = (
        []
        if field == "analysisId"
        else [
            {
                "factPath": "facts/analysis_001.json",
                "dataPath": "metrics[0].periodValues",
                "fields": ["period", "value"],
            }
        ]
    )
    assert extra["details"]["availableDescriptors"] == expected_descriptors


def test_analysis_executor_does_not_assemble_report() -> None:
    source = inspect.getsource(RuntimeAnalysisMixin.run_reporting_analysis)

    assert "_finalize_reporting_sections" not in source


def _analysis_workflow(
    *, benchmark_projection: BenchmarkProjection | None = None
) -> AnalysisItemWorkflow:
    return AnalysisItemWorkflow(
        decide_evidence=AsyncMock(),
        run_code=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(),
        complete=AsyncMock(),
        benchmark_projection=benchmark_projection,
    )


def _analysis_state_with_requirement(
    *, dataset_id: str = "dataset_001", fields: tuple[str, ...] = ("department", "income")
) -> _AnalysisItemState:
    return _AnalysisItemState(
        instruction={
            "currentAnalysis": {
                "analysisId": "analysis_001",
                "datasetIds": ["dataset_001"],
            },
            "datasets": [
                {
                    "datasetId": "dataset_001",
                    "path": "data/income.csv",
                    "columns": ["department", "income", "period"],
                }
            ],
            "analysisOutputRoot": "analysis/analysis_001",
        },
        decision=AnalysisEvidenceDecision.model_validate(
            {
                "requiresSupplementalEvidence": True,
                "reason": "需要科室收入构成",
                "missingFacts": ["科室收入构成"],
                "codingRequirements": [
                    {
                        "datasetId": dataset_id,
                        "fields": list(fields),
                        "calculation": "按科室汇总收入并与收入总量对账",
                        "outputName": "department_income",
                    }
                ],
            }
        ),
    )


def test_analysis_candidate_projection_includes_validated_coding_requirements() -> None:
    facts = _analysis_workflow(
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.CANDIDATE)
    )._script_task_facts(_analysis_state_with_requirement())

    assert facts["codingRequirements"] == [
        {
            "datasetId": "dataset_001",
            "fields": ["department", "income"],
            "calculation": "按科室汇总收入并与收入总量对账",
            "outputName": "department_income",
        }
    ]
    assert "evidenceDecision" not in facts


def test_analysis_production_projection_defaults_to_dynamic_requirements() -> None:
    facts = _analysis_workflow()._script_task_facts(_analysis_state_with_requirement())

    assert facts["codingRequirements"] == [
        {
            "datasetId": "dataset_001",
            "fields": ["department", "income"],
            "calculation": "按科室汇总收入并与收入总量对账",
            "outputName": "department_income",
        }
    ]
    assert "evidenceDecision" not in facts


def test_analysis_legacy_projection_omits_r7_requirements_but_keeps_existing_facts() -> None:
    state = _analysis_state_with_requirement()
    state.instruction["deterministicFacts"] = {
        "analysisId": "analysis_001",
        "metrics": [{"metricId": "income", "value": 100}],
    }

    facts = _analysis_workflow()._script_task_facts(
        state,
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY),
    )

    assert "codingRequirements" not in facts
    assert facts["existingFacts"] == {
        "analysisId": "analysis_001",
        "metrics": [{"metricId": "income", "value": 100}],
    }


def test_script_receives_registered_monthly_baselines_without_large_group_details():
    state = _analysis_state_with_requirement()
    periods = [{'period': '2025-01-01', 'value': 60}, {'period': '2025-02-01', 'value': 40}]
    state.instruction['deterministicFacts'] = {
        'analysisId': 'analysis_001', 'metrics': [{
            'field': 'income', 'total': 100, 'unit': '元', 'periodGranularity': 'month',
            'periodValues': periods, 'topGroups': [{'group': '科室', 'value': 50}],
        }],
    }
    facts = _analysis_workflow()._script_task_facts(state)
    metric = facts['existingFacts']['metrics'][0]
    assert metric['periodValues'] == periods
    assert metric['unit'] == '元'
    assert 'topGroups' not in metric


def test_script_does_not_expand_registered_daily_baselines():
    state = _analysis_state_with_requirement()
    state.instruction['deterministicFacts'] = {
        'analysisId': 'analysis_001', 'metrics': [{
            'field': 'income', 'total': 100, 'periodGranularity': 'day',
            'periodValues': [{'period': '2025-01-01', 'value': 100}],
        }],
    }
    facts = _analysis_workflow()._script_task_facts(state)
    assert 'periodValues' not in facts['existingFacts']['metrics'][0]


def test_analysis_workflow_uses_constructor_projection_for_coding_facts() -> None:
    workflow = _analysis_workflow(
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)
    )

    facts = workflow._script_task_facts(_analysis_state_with_requirement())

    assert "codingRequirements" not in facts
    assert facts["evidenceDecision"]["missingFacts"] == ["科室收入构成"]


def test_analysis_workflow_preserves_legacy_decision_without_fabricating_requirements() -> None:
    state = _analysis_state_with_requirement()
    state.decision = LegacyAnalysisEvidenceDecision.model_validate(
        {
            "requiresSupplementalEvidence": True,
            "reason": "缺少部门明细",
            "missingFacts": ["部门明细"],
        }
    )

    facts = _analysis_workflow(
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)
    )._script_task_facts(state)

    assert "codingRequirements" not in facts
    assert facts["evidenceDecision"]["missingFacts"] == ["部门明细"]


@pytest.mark.anyio
async def test_analysis_evidence_planner_receives_authorized_dataset_fields() -> None:
    requests: list[dict[str, object]] = []

    async def decide(payload: dict[str, object]) -> AnalysisEvidenceDecision:
        requests.append(payload)
        return _analysis_state_with_requirement().decision  # type: ignore[return-value]

    workflow = AnalysisItemWorkflow(
        decide_evidence=decide,
        run_code=AsyncMock(),
        summarize=AsyncMock(),
        read_file=AsyncMock(),
        complete=AsyncMock(),
    )
    state = _analysis_state_with_requirement()
    state.facts = DeterministicAnalysisBundle(analysisId="analysis_001")
    state.instruction["deterministicFacts"] = {
        "analysisId": "analysis_001",
        "metrics": [],
    }

    await workflow._decide_evidence(state)

    assert requests[0]["datasets"] == state.instruction["datasets"]


@pytest.mark.parametrize(
    "requires_supplement,requirements",
    [
        (
            True,
            [
                {
                    "datasetId": "dataset_001",
                    "fields": [],
                    "calculation": "汇总收入",
                    "outputName": "income_total",
                }
            ],
        ),
        (
            True,
            [
                {
                    "datasetId": "dataset_001",
                    "fields": ["income"],
                    "calculation": "汇总收入",
                    "outputName": "income_total",
                },
                {
                    "datasetId": "dataset_001",
                    "fields": ["department"],
                    "calculation": "统计科室",
                    "outputName": "income_total",
                },
            ],
        ),
        (
            False,
            [
                {
                    "datasetId": "dataset_001",
                    "fields": ["income"],
                    "calculation": "汇总收入",
                    "outputName": "income_total",
                }
            ],
        ),
    ],
    ids=("empty-fields", "duplicate-output", "requirements-without-supplement"),
)
def test_analysis_evidence_decision_rejects_inconsistent_coding_requirements(
    requires_supplement: bool, requirements: list[dict[str, object]]
) -> None:
    with pytest.raises(ValidationError):
        AnalysisEvidenceDecision.model_validate(
            {
                "requiresSupplementalEvidence": requires_supplement,
                "reason": "补证决策",
                "missingFacts": ["收入"] if requires_supplement else [],
                "codingRequirements": requirements,
            }
        )


@pytest.mark.parametrize(
    ("dataset_id", "fields"),
    [
        ("dataset_unknown", ("income",)),
        ("dataset_001", ("income", "baseline_income")),
    ],
    ids=("unknown-dataset", "cross-dataset-field"),
)
def test_analysis_script_facts_reject_untrusted_coding_requirements(
    dataset_id: str, fields: tuple[str, ...]
) -> None:
    with pytest.raises(ReportingError) as caught:
        _analysis_workflow()._script_task_facts(
            _analysis_state_with_requirement(dataset_id=dataset_id, fields=fields)
        )

    assert caught.value.code == "report_analysis_evidence_decision_invalid"


def test_analysis_script_facts_reject_dataset_outside_current_analysis() -> None:
    state = _analysis_state_with_requirement(dataset_id="dataset_other", fields=("income",))
    state.instruction["datasets"].append(
        {
            "datasetId": "dataset_other",
            "path": "data/other.csv",
            "columns": ["income"],
        }
    )

    with pytest.raises(ReportingError) as caught:
        _analysis_workflow()._script_task_facts(state)

    assert caught.value.code == "report_analysis_evidence_decision_invalid"


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
                "callerThreadId": "thread",
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
    # 汇编完成后会从 checkpoint 中取回已登记的 manifest 文件身份。
    checkpoint = SimpleNamespace(revision=2, phase="finalize", files=[SimpleNamespace(
        path="报表/智能分析/run-1/report-revision-2.manifest.json", size=2, sha256="a" * 64,
    )])
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
                    "total": 100,
                    "warnings": ["数据质量提示"],
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
        _read_identity_bytes=AsyncMock(
            return_value=json.dumps(
                {
                    "findings": [
                        {
                            "name": "月度成本收入比",
                            "columns": ["period", "income", "cost", "costIncomeRatio"],
                            "rows": [["2025-01", 100, 90, 0.9]],
                        }
                    ],
                    "reconciliations": [{"name": "收入成本期间对账", "passed": True}],
                    "warnings": [],
                },
                ensure_ascii=False,
            ).encode()
        ),
    )
    fact_file = FileIdentity(path="analysis/facts/analysis_001.json", size=2, sha256="a" * 64)
    supplement_file = FileIdentity(
        path="analysis/evidence/analysis_001/supplement.json",
        size=2,
        sha256="b" * 64,
    )

    projection = await RuntimeAnalysisMixin._visualization_section_fact_projection(
        runtime,
        "analysis_001",
        fact_file,
        {
            "datasetIds": ["dataset_001"],
            "evidenceFiles": [
                supplement_file.model_dump(mode="json", by_alias=True),
                fact_file.model_dump(mode="json", by_alias=True),
            ],
        },
    )

    assert projection["dataPathBase"] == "fileRoot"
    metric_descriptor = next(item for item in projection["dataDescriptors"] if item["dataPath"] == "metrics[0]")
    assert "warnings" not in metric_descriptor["fields"]
    assert "periodValues" not in metric_descriptor["fields"]
    assert "total" in metric_descriptor["fields"]
    assert projection["metrics"][0]["periodValueFields"] == ["period", "value"]
    for collection in ("topGroups", "bottomGroups"):
        descriptor = next(item for item in projection["dataDescriptors"] if item["dataPath"] == f"metrics[0].{collection}")
        assert descriptor["dataScope"]["coverage"] == "ranked_subset"
        assert descriptor["dataScope"]["canRepresentFullDistribution"] is False
    assert {
        "dataPath": "metrics[0].periodValues",
        "fields": ["period", "value"],
    } in projection["dataDescriptors"]
    assert projection["supplementalEvidenceSources"] == [
        {
            "sourceFile": supplement_file.model_dump(mode="json", by_alias=True),
            "dataPathBase": "fileRoot",
            "findings": [
                {
                    "findingIndex": 0,
                    "name": "月度成本收入比",
                    "dataPath": "findings[0]",
                    "fields": ["columns", "name", "rows"],
                    "columns": ["period", "income", "cost", "costIncomeRatio"],
                    "rowsDataPath": "findings[0].rows",
                    "rowEncoding": "columns_rows",
                    "rowCount": 1,
                }
            ],
            "dataDescriptors": [
                {
                    "dataPath": "findings[0]",
                    "fields": ["columns", "name", "rows"],
                },
                {
                    "dataPath": "findings[0].rows",
                    "fields": ["period", "income", "cost", "costIncomeRatio"],
                },
            ],
        }
    ]


def test_visualization_generator_completion_does_not_delegate_tool_calls() -> None:
    conditions = _visualization_section_completion_conditions(None)

    assert not any("submit_visualization_charts" in item for item in conditions)
    assert any("固定 Workflow" in item for item in conditions)


@pytest.mark.anyio
async def test_visualization_fact_projection_declares_nullable_columns() -> None:
    runtime = SimpleNamespace(
        _visualization_context={"thread_id": "thread-1"},
        _read_identity_model=AsyncMock(
            return_value=SimpleNamespace(model_dump=lambda **_: {"metrics": []})
        ),
        _read_identity_bytes=AsyncMock(
            return_value=json.dumps(
                {
                    "findings": [
                        {
                            "name": "科室同比",
                            "columns": ["科室", "同比增速(%)"],
                            "rows": [["普通外科", 23.84], ["高血压研究所", None]],
                        }
                    ],
                    "reconciliations": [{"name": "同比口径核对", "passed": True}],
                },
                ensure_ascii=False,
            ).encode()
        ),
    )
    fact_file = FileIdentity(path="facts/a.json", size=2, sha256="a" * 64)
    supplement_file = FileIdentity(path="analysis/a/supplement.json", size=2, sha256="b" * 64)

    projection = await RuntimeAnalysisMixin._visualization_section_fact_projection(
        runtime,
        "analysis_001",
        fact_file,
        {
            "datasetIds": ["dataset_001"],
            "evidenceFiles": [supplement_file.model_dump(mode="json", by_alias=True)],
        },
    )

    descriptor = projection["supplementalEvidenceSources"][0]["findings"][0]
    assert descriptor["nullableFields"] == ["同比增速(%)"]


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


def _execution_receipt(
    script_path: str,
    script_size: int,
    script_sha256: str,
    output_paths: tuple[str, ...],
) -> ExecutionReceipt:
    return ExecutionReceipt(
        runId="run-1",
        sourceFile=FileIdentity(
            path=script_path,
            size=script_size,
            sha256=script_sha256,
        ),
        outputFiles=tuple(
            FileIdentity(path=path, size=1, sha256="a" * 64)
            for index, path in enumerate(output_paths, start=1)
        ),
    )


@pytest.mark.anyio
async def test_visualization_workflow_consumes_code_agent_visual_receipts() -> None:
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64)
    receipt = _execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",))
    result = CodeGenerationResult(
        script_file=script_file,
        execution_receipt=receipt,
        visual_inspection_receipts=(_inspection(),),
    )
    submit = AsyncMock(return_value={"status": "accepted"})

    workflow_result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(return_value=result),
        submit=submit,
    ).run(_visualization_payload(), _context())

    assert workflow_result.status == "accepted"
    assert workflow_result.inspections == (_inspection(),)
    submit.assert_awaited_once_with(_visualization_plan(), (_inspection(),), _context())


@pytest.mark.anyio
async def test_visualization_workflow_passes_benchmark_projection_to_coding() -> None:
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64)
    receipt = _execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",))
    result = CodeGenerationResult(
        script_file=script_file,
        execution_receipt=receipt,
        visual_inspection_receipts=(_inspection(),),
    )
    run_code = AsyncMock(return_value=result)

    await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=run_code,
        submit=AsyncMock(return_value={"status": "accepted"}),
        benchmark_projection=BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY),
    ).run(_visualization_payload(), _context())

    assert run_code.await_args.kwargs["benchmark_projection"].variant is BenchmarkVariant.LEGACY
    assert run_code.await_args.kwargs["task_facts"] is None


@pytest.mark.anyio
async def test_visualization_workflow_preserves_benchmark_projection_for_repair() -> None:
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64)
    receipt = _execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",))
    result = CodeGenerationResult(
        script_file=script_file,
        execution_receipt=receipt,
        visual_inspection_receipts=(_inspection(),),
    )
    run_code = AsyncMock(
        side_effect=[ReportingError("report_chart_file_missing", "missing"), result]
    )
    projection = BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)

    await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=run_code,
        submit=AsyncMock(return_value={"status": "accepted"}),
        benchmark_projection=projection,
    ).run(_visualization_payload(), _context())

    assert [call.kwargs["benchmark_projection"] for call in run_code.await_args_list] == [
        projection,
        projection,
    ]
    assert all(
        "benchmarkProjection" not in (call.kwargs["task_facts"] or {})
        for call in run_code.await_args_list
    )


@pytest.mark.anyio
async def test_visualization_execution_repair_preserves_benchmark_projection() -> None:
    first_script = FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64)
    repaired_script = FileIdentity(path="charts/charts.py", size=1, sha256="c" * 64)
    first = CodeGenerationResult(
        script_file=first_script,
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection(),),
    )
    repaired = CodeGenerationResult(
        script_file=repaired_script,
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "c" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection(),),
    )
    run_code = AsyncMock(side_effect=[first, repaired])
    projection = BenchmarkProjection.for_variant(BenchmarkVariant.LEGACY)

    await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=run_code,
        submit=AsyncMock(
            side_effect=[
                ReportingError("report_chart_file_missing", "missing"),
                {"status": "accepted"},
            ]
        ),
        benchmark_projection=projection,
    ).run(_visualization_payload(), _context())

    assert [call.kwargs["benchmark_projection"] for call in run_code.await_args_list] == [
        projection,
        projection,
    ]
    assert run_code.await_args.kwargs["task_facts"]["repairAttempt"] == 1
    assert "benchmarkProjection" not in run_code.await_args.kwargs["task_facts"]


@pytest.mark.parametrize(
    ("analysis_ids", "expected_complexity", "expected_budget"),
    [
        (("analysis_001",), "simple", 1024),
        (("analysis_001", "analysis_002"), "standard", 2048),
        (("analysis_001", "analysis_002", "analysis_003", "analysis_004"), "complex", 4096),
    ],
)
def test_visualization_plan_thinking_follows_analysis_count(
    analysis_ids: tuple[str, ...], expected_complexity: str, expected_budget: int
) -> None:
    complexity = _visualization_thinking_complexity({"analysisIds": analysis_ids})
    decision = select_reporting_thinking(
        ThinkingRequest(operation="visualization_plan", complexity=complexity)
    )

    assert complexity == expected_complexity
    assert decision.thinking_budget == expected_budget


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("report_python_source_shape_invalid", "python_compile_failure"),
        ("report_python_source_path_invalid", "python_compile_failure"),
        ("report_analysis_script_failed", "python_execution_failure"),
        ("report_visualization_script_failed", "python_execution_failure"),
        ("report_visualization_review_failed", "visual_review_failure"),
        ("report_task_timeout", None),
        ("report_workspace_unavailable", None),
        ("unknown", None),
    ],
)
def test_code_failure_kind_only_classifies_recoverable_failures(
    code: str, expected: str | None
) -> None:
    assert _code_failure_kind({"code": code}) == expected


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


def _plan_stage_validator(work_item: SectionWorkItem) -> object:
    stage = reporting_sections._section_stage_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")),
        SectionPlanOutput,
        "plan",
        response_validator=reporting_sections._section_plan_response_validator(work_item),
    )
    return getattr(stage.model, "_report_response_validator")


def test_degraded_plan_stage_instructions_forbid_further_rework() -> None:
    stage = reporting_sections._section_stage_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")),
        RenderSectionPlan,
        "plan",
    )

    instructions = "\n".join(stage.instructions)
    assert "不得再请求补证" in instructions
    assert "不足时返回 rework" not in instructions


def _render_plan_payload(metric_code: str = "revenue") -> dict:
    return {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": [{"blockId": "block_001", "objective": "说明收入", "claimIds": ["claim_001"]}],
        "claims": [
            {
                "claimId": "claim_001",
                "metricCode": metric_code,
                "value": 100,
                "citationIds": ["citation_001"],
            }
        ],
    }


def _dual_analysis_work_item(*, shared_metric: bool) -> SectionWorkItem:
    identity = FileIdentity(
        path="evidence/a.json",
        size=len(_SECTION_EVIDENCE_BYTES),
        sha256=_SECTION_EVIDENCE_SHA256,
    )
    second_metric = "revenue" if shared_metric else "margin"
    return _section_work_item().model_copy(
        update={
            "analysisIds": ("analysis_001", "analysis_002"),
            "evidence": (
                AnalysisEvidence(
                    analysisId="analysis_001",
                    summary="summary",
                    datasetIds=("dataset_001",),
                    evidenceFiles=(identity,),
                    citationIds=("citation_001",),
                    metrics=("revenue",),
                ),
                AnalysisEvidence(
                    analysisId="analysis_002",
                    summary="summary",
                    datasetIds=("dataset_001",),
                    evidenceFiles=(identity,),
                    citationIds=("citation_001",),
                    metrics=(second_metric,),
                ),
            ),
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
                SectionManagementQuestion(ref="analysis_002", question="利润表现如何？"),
            ),
        }
    )


def test_section_plan_validator_backfills_single_catalog_ref() -> None:
    work_item = _section_work_item().model_copy(
        update={
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
            ),
        }
    )
    validator = _plan_stage_validator(work_item)

    result = validator(json.dumps(_render_plan_payload(), ensure_ascii=False))

    assert result.root.claims[0].management_question_ref == "analysis_001"


def test_section_plan_validator_backfills_unique_metric_mapping() -> None:
    work_item = _dual_analysis_work_item(shared_metric=False)
    validator = _plan_stage_validator(work_item)

    result = validator(json.dumps(_render_plan_payload("margin"), ensure_ascii=False))

    assert result.root.claims[0].management_question_ref == "analysis_002"


def test_section_plan_validator_keeps_ambiguous_missing_ref_failing() -> None:
    work_item = _dual_analysis_work_item(shared_metric=True)
    validator = _plan_stage_validator(work_item)

    with pytest.raises(ValidationError) as raised:
        validator(json.dumps(_render_plan_payload(), ensure_ascii=False))

    assert raised.value._report_candidate["claims"][0]["claimId"] == "claim_001"


def test_section_plan_validator_never_overrides_present_ref() -> None:
    work_item = _dual_analysis_work_item(shared_metric=False)
    validator = _plan_stage_validator(work_item)
    payload = _render_plan_payload("margin")
    payload["claims"][0]["managementQuestionRef"] = "analysis_999"

    result = validator(json.dumps(payload, ensure_ascii=False))

    assert result.root.claims[0].management_question_ref == "analysis_999"


def test_section_plan_validator_never_overrides_explicit_null_ref() -> None:
    work_item = _dual_analysis_work_item(shared_metric=False)
    validator = _plan_stage_validator(work_item)
    payload = _render_plan_payload("margin")
    payload["claims"][0]["managementQuestionRef"] = None

    with pytest.raises(ValidationError) as raised:
        validator(json.dumps(payload, ensure_ascii=False))

    assert raised.value._report_candidate["claims"][0]["managementQuestionRef"] is None


def _previous_two_claim_plan() -> dict:
    payload = _render_plan_payload()
    payload["blocks"][0]["claimIds"] = ["claim_001", "claim_002"]
    payload["claims"] = [
        {**payload["claims"][0], "managementQuestionRef": "analysis_001"},
        {
            "claimId": "claim_002",
            "metricCode": "revenue",
            "value": 90,
            "managementQuestionRef": "analysis_999",
            "citationIds": ["citation_001"],
        },
    ]
    return payload


@pytest.mark.parametrize(
    "patch_shape",
    ["single_claim", "claims_wrapper", "claim_list"],
)
def test_section_plan_validator_merges_correction_claim_patch(patch_shape: str) -> None:
    previous = _previous_two_claim_plan()
    fixed = {**previous["claims"][1], "managementQuestionRef": "analysis_001"}
    content = {
        "single_claim": fixed,
        "claims_wrapper": {"claims": [fixed]},
        "claim_list": [fixed],
    }[patch_shape]
    validator = reporting_sections._section_plan_response_validator(
        _section_work_item(), RenderSectionPlan, previous
    )

    result = validator(json.dumps(content, ensure_ascii=False))

    assert result.section_code == "section_001"
    assert [claim.claim_id for claim in result.claims] == ["claim_001", "claim_002"]
    assert result.claims[1].management_question_ref == "analysis_001"
    assert result.blocks[0].claim_ids == ("claim_001", "claim_002")


def _revenue_work_item() -> SectionWorkItem:
    return _section_work_item().model_copy(
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


def _plan_claim(claim_id: str, **overrides: object) -> dict:
    return {
        "claimId": claim_id,
        "metricCode": "revenue",
        "value": 100,
        "managementQuestionRef": "analysis_001",
        "currentPeriod": "2025年",
        "citationIds": ["citation_001"],
        **overrides,
    }


def test_section_plan_patch_with_non_string_claim_id_stays_validation_error() -> None:
    previous = _previous_two_claim_plan()
    validator = reporting_sections._section_plan_response_validator(
        _section_work_item(), RenderSectionPlan, previous
    )

    with pytest.raises(ValidationError):
        validator(json.dumps({**previous["claims"][1], "claimId": ["claim_002"]}))


@pytest.mark.anyio
@pytest.mark.parametrize("whole_section", [False, True, "oversized"])
@pytest.mark.parametrize("recovery", [None, {"code": "report_phase_output_invalid"}])
async def test_section_generation_switch_preserves_blocks_and_references(
    monkeypatch, whole_section, recovery
):
    stages = []
    plan = {
        "sectionCode": "section_001",
        "blocks": [
            {"blockId": f"block_{index}", "objective": "收入", "claimIds": [f"claim_{index}"]}
            for index in (1, 2)
        ],
        "claims": [_plan_claim(f"claim_{index}") for index in (1, 2)],
    }

    async def fake_stage(agent, schema, stage, payload, **kwargs):
        stages.append(stage)
        assert payload["numberGuide"][0]["total"]["reference"] == (
            "100元" if stage == "plan" else "{{value:fact-aaaaaaaaaaaaaaaa:total:元}}"
        )
        assert payload["numberGuide"][0]["datasetId"] == "current"
        decision = select_reporting_thinking(kwargs["thinking_request"])
        assert decision.thinking_budget == (4096 if stage == "content" else 2048)
        if stage == "plan":
            return SectionPlanOutput.model_validate({"kind": "render", **plan})
        token = "{{value:fact-aaaaaaaaaaaaaaaa:total:元}}"
        assert payload["frozenNumbers"][token] == "100元"
        if stage == "content":
            assert stage == "content"
            assert payload["sectionPlan"]["blocks"] == plan["blocks"]
            assert len(payload["evidence"]["files"]) == 1
            return schema.model_validate(
                {
                    "blocks": [
                        {"blockId": f"block_{index}", "markdown": f"收入为{token}。"}
                        for index in (2, 1)
                    ]
                }
            )
        return SectionBlockContent(markdown=f"收入为{token}。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    if whole_section == "oversized":
        async def oversized_content(*_args, **_kwargs):
            raise ReportingError("report_section_context_too_large", "整章输入过大")

        monkeypatch.setattr(reporting_sections, "_generate_whole_section_content", oversized_content)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(
        sectionCode="section_001",
        files=(
            SectionEvidenceFile(
                identity=work_item.evidence[0].evidence_files[0], content=json.dumps({
                    "analysisId": "analysis_001", "metrics": [{
                        "factId": "fact-aaaaaaaaaaaaaaaa", "datasetId": "current", "datasetSha256": "a" * 64,
                        "periodRoles": ["current"], "field": "amount", "fieldRef": "hospital.revenue.amount",
                        "aggregation": "sum", "unit": "元", "formula": "sum(amount)", "total": 100,
                        "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
                    }],
                })
            ),
        ),
        factSummaries=("收入为100元",),
    )
    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {"reportGoal": "分析收入", "sectionGoal": {}},
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
        whole_section=whole_section,
        recovery=recovery,
    )
    assert stages == (
        ["plan", "content"] if whole_section is True else ["plan", "block-1", "block-2"]
    )
    assert [block.block_id for block in result.blocks] == ["block_1", "block_2"]
    assert [block.claim_ids for block in result.blocks] == [("claim_1",), ("claim_2",)]
    assert all(block.citation_ids == ("citation_001",) for block in result.blocks)
    assert all(block.markdown == "收入为100元。" for block in result.blocks)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "block_ids",
    [
        ["block_1"],
        ["block_1", "block_1"],
        ["block_1", "block_2", "block_3"],
    ],
)
async def test_whole_section_rejects_missing_duplicate_or_extra_blocks(monkeypatch, block_ids):
    async def fake_stage(*args, **kwargs):
        return SectionContent.model_validate(
            {
                "blocks": [
                    {"blockId": block_id, "markdown": "收入为100元。"} for block_id in block_ids
                ]
            }
        )

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    plan = RenderSectionPlan.model_validate(
        {
            "sectionCode": "section_001",
            "blocks": [
                {"blockId": f"block_{index}", "objective": "收入", "claimIds": ["claim_1"]}
                for index in (1, 2)
            ],
            "claims": [_plan_claim("claim_1")],
        }
    )
    with pytest.raises(ReportingError) as captured:
        await reporting_sections._generate_whole_section_content(
            object(),
            {},
            SectionEvidenceBundle(
                sectionCode="section_001",
                files=(
                    SectionEvidenceFile(
                        identity=work_item.evidence[0].evidence_files[0], content='{"收入":100}'
                    ),
                ),
                factSummaries=("收入为100元",),
            ),
            work_item,
            plan,
            scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
            run_context=_context(),
            thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
        )
    assert captured.value.code == "report_section_content_blocks_invalid"


def test_whole_section_stage_requests_all_blocks():
    stage = reporting_sections._section_stage_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")),
        SectionContent,
        "content",
    )
    instructions = "\n".join(stage.instructions)
    assert "一次生成 sectionPlan 中全部 block" in instructions
    assert "不得生成其他 block" not in instructions


@pytest.mark.anyio
async def test_first_block_sibling_orphan_h4_headings_are_promoted_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages: list[str] = []
    plan = {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": [{"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001"]}],
        "claims": [_plan_claim("claim_001")],
    }

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        stages.append(stage)
        if stage == "plan":
            return SectionPlanOutput.model_validate(plan)
        assert "correction" not in payload
        return SectionBlockContent(
            markdown="#### 门诊收入\n\n收入为100元。\n\n#### 住院收入\n\n稳定。"
        )

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)
    work_item = _revenue_work_item()
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

    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {"reportGoal": "分析2025年收入", "sectionGoal": {"sectionCode": "section_001"}},
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
    )

    assert stages == ["plan", "block-1"]
    assert result.blocks[0].markdown == ("### 门诊收入\n\n收入为100元。\n\n### 住院收入\n\n稳定。")


def test_section_plan_references_repaired_when_unambiguous() -> None:
    work_item = _revenue_work_item()
    decision = RenderSectionPlan.model_validate(
        {
            "sectionCode": "section_001",
            "blocks": [{"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001"]}],
            "claims": [
                _plan_claim(
                    "claim_001",
                    metricCode="收入",
                    managementQuestionRef="analysis_404",
                    citationIds=["citation_999"],
                    chartIds=["chart_999"],
                )
            ],
        }
    )

    repaired = reporting_sections._repair_section_plan_references(decision, work_item)

    claim = repaired.claims[0]
    assert claim.metric_code == "revenue"
    assert claim.management_question_ref == "analysis_001"
    assert claim.citation_ids == ("citation_001",)
    assert claim.chart_ids == ()
    assert reporting_sections._section_plan_reference_issues(repaired, work_item) == []


def test_section_plan_citations_fall_back_to_bound_chart_anchor() -> None:
    base = _revenue_work_item()
    work_item = base.model_copy(
        update={
            "citations": (
                *base.citations,
                SectionCitation(
                    citationId="citation_002",
                    datasetId="dataset_001",
                    requirementId="requirement_002",
                    snapshotHash="b" * 64,
                ),
            ),
            "evidence": (
                base.evidence[0].model_copy(
                    update={"citation_ids": ("citation_001", "citation_002")}
                ),
            ),
            "charts": (
                AnalysisChart(
                    chartId="chart_001",
                    sourceFile=FileIdentity(path="charts/revenue.png", size=1024, sha256="c" * 64),
                    title="2025年收入趋势",
                    altText="2025年收入趋势图",
                    citationIds=("citation_002",),
                    metricCodes=("revenue",),
                    currentPeriod="2025年",
                    sourceDatasetId="dataset_001",
                    aggregationGrain="month",
                ),
            ),
        }
    )
    decision = RenderSectionPlan.model_validate(
        {
            "sectionCode": "section_001",
            "blocks": [{"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001"]}],
            "claims": [
                _plan_claim("claim_001", citationIds=["citation_999"], chartIds=["chart_001"])
            ],
        }
    )

    repaired = reporting_sections._repair_section_plan_references(decision, work_item)

    assert repaired.claims[0].citation_ids == ("citation_002",)
    assert reporting_sections._section_plan_reference_issues(repaired, work_item) == []


def test_section_plan_references_keep_ambiguous_metric_for_model_correction() -> None:
    work_item = _revenue_work_item()
    decision = RenderSectionPlan.model_validate(
        {
            "sectionCode": "section_001",
            "blocks": [{"blockId": "block_001", "objective": "利润", "claimIds": ["claim_001"]}],
            "claims": [_plan_claim("claim_001", metricCode="profit")],
        }
    )

    repaired = reporting_sections._repair_section_plan_references(decision, work_item)

    assert repaired is decision
    assert [
        item["type"]
        for item in reporting_sections._section_plan_reference_issues(repaired, work_item)
    ] == ["unknown_metric_code"]


async def _generate_with_plan(
    monkeypatch, plan: dict, stages: list[str], work_item: SectionWorkItem | None = None
):
    work_item = work_item or _revenue_work_item()
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

    async def fake_run_stage(_agent, _schema, stage, _payload, **_kwargs):
        stages.append(stage)
        if stage == "plan":
            return SectionPlanOutput.model_validate(plan)
        return SectionBlockContent(markdown="### 收入规模\n\n收入为100元。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)
    return await reporting_sections._generate_section_in_blocks(
        object(),
        {"reportGoal": "分析2025年收入", "sectionGoal": {"sectionCode": "section_001"}},
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
    )


@pytest.mark.anyio
async def test_section_plan_rejects_invented_fact_ids_before_body_generation(monkeypatch):
    stages: list[str] = []
    plan = {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": [{"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001"]}],
        "claims": [_plan_claim("claim_001", factIds=["fact_001"])],
    }
    with pytest.raises(ReportingError) as raised:
        await _generate_with_plan(monkeypatch, plan, stages)
    assert raised.value.code == "report_claim_fact_unknown"
    assert stages == ["plan", "plan", "plan"]


@pytest.mark.anyio
async def test_section_plan_supplies_frozen_fact_catalog_and_corrects_alias(monkeypatch):
    work_item = _revenue_work_item()
    fact_id = "fact-2762d4b6dbc7dd82"
    document = {
        "analysisId": "analysis_001",
        "metrics": [
            {
                "factId": fact_id,
                "total": 100,
                "unit": "元",
                "periodStart": "2025-01-01",
            }
        ],
    }
    evidence = SectionEvidenceBundle(
        sectionCode="section_001",
        factSummaries=("收入为100元",),
        files=(
            SectionEvidenceFile(
                identity=work_item.evidence[0].evidence_files[0], content=json.dumps(document)
            ),
        ),
    )
    stages: list[str] = []

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        stages.append(stage)
        if stage == "plan":
            assert payload["factCatalog"] == [
                {
                    "analysisId": "analysis_001",
                    "kind": "metrics",
                    "factId": fact_id,
                    "total": 100,
                    "unit": "元",
                    "periodStart": "2025-01-01",
                }
            ]
            if stages.count("plan") == 2:
                issue = payload["correction"]["issues"][0]
                assert issue["type"] == "unknown_fact_id"
                assert issue["allowedValues"] == [fact_id]
            return SectionPlanOutput.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001"]}
                    ],
                    "claims": [
                        _plan_claim(
                            "claim_001",
                            factIds=["fact_001" if stages.count("plan") == 1 else fact_id],
                        )
                    ],
                }
            )
        return SectionBlockContent(markdown="### 收入规模\n\n收入为100元。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)
    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {},
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
    )
    assert result.claims[0].fact_ids == (fact_id,)
    assert stages == ["plan", "plan", "block-1"]


@pytest.mark.anyio
async def test_section_plan_passes_unresolved_references_to_render_after_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages: list[str] = []
    plan = {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": [
            {"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001", "claim_002"]},
            {"blockId": "block_002", "objective": "利润", "claimIds": ["claim_002"]},
        ],
        "claims": [_plan_claim("claim_001"), _plan_claim("claim_002", metricCode="profit")],
    }

    result = await _generate_with_plan(monkeypatch, plan, stages)

    # 未知指标交给渲染工具保留并写入产物告警，而不是静默剔除结论。
    assert stages == ["plan", "plan", "plan", "block-1", "block-2"]
    assert [claim.claim_id for claim in result.claims] == ["claim_001", "claim_002"]


@pytest.mark.anyio
async def test_section_plan_fails_closed_when_no_claim_keeps_an_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stages: list[str] = []
    plan = {
        "kind": "render",
        "sectionCode": "section_001",
        "blocks": [{"blockId": "block_001", "objective": "利润", "claimIds": ["claim_001"]}],
        "claims": [_plan_claim("claim_001", citationIds=["citation_999"])],
    }

    base = _revenue_work_item()
    # 所属 analysis 拥有两个 citation，锚点无法唯一回填。
    work_item = base.model_copy(
        update={
            "citations": (
                *base.citations,
                SectionCitation(
                    citationId="citation_002",
                    datasetId="dataset_001",
                    requirementId="requirement_002",
                    snapshotHash="b" * 64,
                ),
            ),
            "evidence": (
                base.evidence[0].model_copy(
                    update={"citation_ids": ("citation_001", "citation_002")}
                ),
            ),
        }
    )

    with pytest.raises(ReportingError) as raised:
        await _generate_with_plan(monkeypatch, plan, stages, work_item)

    assert raised.value.code == "report_section_plan_reference_invalid"
    assert stages == ["plan", "plan", "plan"]


@pytest.mark.anyio
async def test_section_plan_validation_error_reaches_agno_without_candidate_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agno.agent import _run as agno_run
    from agno.models.response import ModelResponse

    from smart_reporting.context_management import ProjectedOpenAIChat

    secret = "一般医用设备-SPECT执行完毕"
    responses = iter(
        [
            {"claimId": "claim_001", "metricCode": "revenue", "value": secret},
            _render_plan_payload(),
        ]
    )
    agno_errors: list[str] = []

    async def fake_aresponse(_model, *_args, **_kwargs):
        return ModelResponse(content=json.dumps(next(responses), ensure_ascii=False))

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", fake_aresponse)
    monkeypatch.setattr(agno_run, "log_error", lambda message, *a, **k: agno_errors.append(message))
    work_item = _section_work_item().model_copy(
        update={
            "management_question_catalog": (
                SectionManagementQuestion(ref="analysis_001", question="收入表现如何？"),
            ),
        }
    )

    result = await reporting_sections._run_section_stage(
        Agent(model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test")),
        RenderSectionPlan,
        "plan",
        {"sectionCode": "section_001"},
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_planning", complexity="standard"),
        section_code="section_001",
        response_validator=reporting_sections._section_plan_response_validator(
            work_item, RenderSectionPlan
        ),
    )

    assert isinstance(result, RenderSectionPlan)
    assert len(agno_errors) == 1
    assert "sectionCode:missing" in agno_errors[0]
    assert secret not in agno_errors[0]


def test_section_plan_validator_keeps_unknown_claim_patch_failing() -> None:
    previous = _previous_two_claim_plan()
    unknown = {**previous["claims"][1], "claimId": "claim_404"}
    validator = reporting_sections._section_plan_response_validator(
        _section_work_item(), RenderSectionPlan, previous
    )

    with pytest.raises(ValidationError) as raised:
        validator(json.dumps(unknown, ensure_ascii=False))

    assert raised.value._report_candidate["claimId"] == "claim_404"


@pytest.mark.anyio
async def test_section_generation_attaches_response_validator_to_plan_stage(
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
    captured: dict[str, object] = {}

    async def fake_run_stage(_agent, _schema, stage, payload, **kwargs):
        captured[stage] = kwargs.get("response_validator")
        if stage == "plan":
            return SectionPlanOutput.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {"blockId": "block_001", "objective": "说明收入", "claimIds": ["claim_001"]}
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
        return SectionBlockContent(
            markdown=f"### {payload['blockPlan']['objective']}\n\n收入为100元。"
        )

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)

    await reporting_sections._generate_section_in_blocks(
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
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
            attempt=0,
            configured_budget_cap=8192,
            thinking_enabled=True,
        ),
    )

    assert callable(captured["plan"])
    assert captured["block-1"] is None


@pytest.mark.anyio
@pytest.mark.parametrize("effort", ["low", "high", "max"])
async def test_section_generation_plans_then_renders_each_block_serially(
    monkeypatch: pytest.MonkeyPatch,
    effort: str,
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
    decisions = []

    async def fake_run_stage(_agent, _schema, stage, payload, **kwargs):
        stages.append(stage)
        decisions.append(select_reporting_thinking(kwargs["thinking_request"]))
        if stage == "plan":
            assert "evidence" not in payload
            assert payload["requiredOutputShape"] == {
                "kind": "render",
                "sectionCode": "section_001",
                "blocks": [
                    {
                        "blockId": "block_001",
                        "objective": "当前 block 的写作目标",
                        "claimIds": ["claim_001"],
                    }
                ],
                "claims": [
                    {
                        "claimId": "claim_001",
                        "metricCode": "必须来自 allowedMetricCodes",
                        "value": "必须来自证据",
                        "managementQuestionRef": "必须来自 managementQuestionRefs",
                        "citationIds": ["必须来自当前 citations"],
                        "chartIds": [],
                    }
                ],
            }
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
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
            attempt=0,
            configured_budget_cap=8192,
            thinking_enabled=True,
            reasoning_effort=effort,
        ),
    )

    assert stages == ["plan", "block-1", "block-2"]
    assert [item.reasoning_effort for item in decisions] == [effort, None, None]
    assert [
        (item.operation, item.enabled, item.thinking_budget, item.attempt) for item in decisions
    ] == [
        ("section_planning", True, 2048, 0),
        ("section_generation", False, 0, 0),
        ("section_generation", False, 0, 0),
    ]
    assert isinstance(result, RenderSectionDecision)
    assert tuple(block.block_id for block in result.blocks) == ("block_001", "block_002")
    assert all(block.claim_ids == ("claim_001",) for block in result.blocks)


@pytest.mark.anyio
async def test_degraded_section_generation_only_accepts_render_plan(
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

    async def fake_run_stage(_agent, schema, stage, payload, **_kwargs):
        if stage == "plan":
            assert schema is RenderSectionPlan
            assert payload["analysisReworkAllowed"] is False
            assert "不得再次请求补证" in payload["requiredAction"]
            return RenderSectionPlan.model_validate(
                {
                    "kind": "render",
                    "sectionCode": "section_001",
                    "blocks": [
                        {"blockId": "block_001", "objective": "说明收入", "claimIds": ["claim_001"]}
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
        return SectionBlockContent(markdown="### 收入\n\n收入为100元。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)

    result = await reporting_sections._generate_section_in_blocks(
        object(),
        {
            "reportGoal": "分析2025年收入",
            "sectionGoal": {"sectionCode": "section_001"},
            "sectionWorkItem": work_item.model_dump(mode="json", by_alias=True),
            "analysisReworkAllowed": False,
        },
        evidence,
        work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
            attempt=0,
            configured_budget_cap=8192,
            thinking_enabled=True,
        ),
    )

    assert isinstance(result, RenderSectionDecision)


@pytest.mark.anyio
@pytest.mark.parametrize("whole_section", [False, True])
async def test_section_recovery_uses_one_bounded_thinking_upgrade(
    monkeypatch: pytest.MonkeyPatch,
    whole_section: bool,
) -> None:
    work_item = _section_work_item()
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
    decisions = []

    async def fake_run_stage(_agent, _schema, _stage, _payload, **kwargs):
        request = kwargs["thinking_request"]
        decisions.append(select_reporting_thinking(request))
        return SectionPlanOutput.model_validate(
            {
                "kind": "rework",
                "sectionCode": "section_001",
                "analysisIds": ["analysis_001"],
                "reason": "缺少月度收入事实",
                "missingEvidence": ["月度收入事实"],
            }
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
        recovery={"code": "report_phase_output_invalid"},
        whole_section=whole_section,
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
            attempt=1,
            failure_kind="schema_failure",
            configured_budget_cap=8192,
            thinking_enabled=True,
        ),
    )

    assert isinstance(result, AnalysisReworkDecision)
    assert [(item.operation, item.thinking_budget, item.attempt) for item in decisions] == [
        ("section_planning", 2048, 1)
    ]


def test_section_block_does_not_inherit_outer_plan_recovery() -> None:
    recovery_request = ThinkingRequest(
        operation="section_generation",
        complexity="standard",
        attempt=1,
        failure_kind="schema_failure",
    )

    plan_request = reporting_sections._section_stage_thinking_request(recovery_request, "plan")
    block_request = reporting_sections._section_stage_thinking_request(recovery_request, "block-1")

    assert select_reporting_thinking(plan_request).thinking_budget == 2048
    assert select_reporting_thinking(block_request).thinking_budget == 0
    assert block_request.operation == "section_generation"
    assert block_request.attempt == 0
    assert block_request.failure_kind is None


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ({"code": "report_phase_output_invalid"}, "schema_failure"),
        ({"code": "report_draft_heading_parent_missing"}, None),
        ({"code": "report_section_submit_rejected"}, None),
        ({"message": "章节重试"}, None),
    ],
)
def test_section_recovery_only_classifies_structured_output_as_schema_failure(
    diagnostic: dict[str, str], expected: str | None
) -> None:
    assert reporting_sections._section_recovery_failure_kind(diagnostic) == expected


@pytest.mark.anyio
async def test_section_generation_promotes_orphan_h4_without_model_correction(
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
        assert "correction" not in payload
        if len(block_payloads) == 1:
            return SectionBlockContent(markdown="#### 收入规模\n\n收入为100元。")
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
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
        ),
    )

    assert stages == ["plan", "block-1", "block-2"]
    assert result.blocks[0].markdown == "### 收入规模\n\n收入为100元。"
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

    async def fake_run_stage(_agent, _schema, stage, payload, **kwargs):
        stages.append(stage)
        if stage == "plan":
            metric_code = "invented_revenue" if stages.count("plan") == 1 else "revenue"
            if stages.count("plan") == 2:
                # 修正轮校验器持有上一版规划：只回传被修正 claim 也能合并成完整规划。
                merged = kwargs["response_validator"](
                    json.dumps(
                        {
                            "claimId": "claim_001",
                            "metricCode": "revenue",
                            "value": 100,
                            "citationIds": ["citation_001"],
                        }
                    )
                )
                assert merged.root.blocks[0].claim_ids == ("claim_001",)
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
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
        ),
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
            thinking_request=ThinkingRequest(
                operation="section_generation",
                complexity="standard",
            ),
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


@pytest.mark.parametrize("bind_fact_id", [False, True])
def test_section_number_context_excludes_unrelated_facts_and_keeps_exact_values(bind_fact_id):
    contents = (json.dumps({
        "analysisId": "analysis_001",
        "metrics": [
            {
                "factId": fact_id, "datasetId": "current", "datasetSha256": "a" * 64,
                "periodRoles": ["current"], "field": code,
                "fieldRef": f"hospital.revenue.{code}", "metricCodes": [code],
                "aggregation": "sum", "unit": "元", "formula": f"sum({code})",
                "total": total, "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
            }
            for fact_id, code, total in (
                ("fact-aaaaaaaaaaaaaaaa", "revenue", 11123541503),
                ("fact-bbbbbbbbbbbbbbbb", "cost", 200),
            )
        ],
    }),)
    claim = SimpleNamespace(
        fact_ids=("fact-aaaaaaaaaaaaaaaa",) if bind_fact_id else (), metric_code="revenue",
    )
    catalog, guide = reporting_sections._section_number_context(contents, {}, claims=(claim,))
    assert [item["factId"] for item in guide] == ["fact-aaaaaaaaaaaaaaaa"]
    token = "{{value:fact-aaaaaaaaaaaaaaaa:total:元}}"
    assert catalog[token] == "11,123,541,503元"
    assert not any("fact-bbbbbbbbbbbbbbbb" in key for key in catalog)
    assert json.loads(contents[0])["metrics"][1]["total"] == 200
    _, planning = reporting_sections._section_number_context(contents, {})
    assert planning[0]["total"]["reference"] == catalog[token]
    assert [item["factId"] for item in planning] == [
        "fact-aaaaaaaaaaaaaaaa", "fact-bbbbbbbbbbbbbbbb",
    ]


@pytest.mark.anyio
async def test_section_stage_attempts_use_independent_sessions(monkeypatch):
    sessions = []

    async def execute(_self, _input, **kwargs):
        sessions.append(kwargs["session_id"])
        return SimpleNamespace(content=SectionBlockContent(markdown="收入情况待核实。"))

    monkeypatch.setattr(reporting_sections.ReportingStructuredOutputExecutor, "execute", execute)
    agent = Agent(model=ReportingPhaseOpenAIChat(id="deepseek-v4-flash-0731", api_key="test"))
    for attempt in ("block-1-1", "block-1-2"):
        await reporting_sections._run_section_stage(
            agent, SectionBlockContent, "block-1", {},
            scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
            run_context=_context(),
            thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
            section_code="section_001", attempt_key=attempt,
        )
    assert len(set(sessions)) == 2
    assert all("task-1:section_001:block-1:" in session for session in sessions)


def test_section_number_context_keeps_bound_comparison_without_metric_guide():
    contents = (json.dumps({
        "analysisId": "analysis_001",
        "comparisons": [
            {
                "factId": fact_id, "comparisonType": "yoy", "field": "revenue",
                "fieldRef": "hospital.revenue.amount", "currentDatasetId": "current",
                "baselineDatasetId": "baseline", "currentDatasetSha256": "a" * 64,
                "baselineDatasetSha256": "b" * 64, "currentTotal": 100,
                "baselineTotal": 80, "change": 20, "changeRate": 25,
                "formula": "current - baseline", "unit": "元",
            }
            for fact_id in ("fact-aaaaaaaaaaaaaaaa", "fact-bbbbbbbbbbbbbbbb")
        ],
    }),)
    catalog, guide = reporting_sections._section_number_context(
        contents, {}, claims=(SimpleNamespace(
            fact_ids=("fact-aaaaaaaaaaaaaaaa",), metric_code="revenue",
        ),),
    )
    assert not guide
    assert catalog["{{value:fact-aaaaaaaaaaaaaaaa:change:元}}"] == "20元"
    assert not any("fact-bbbbbbbbbbbbbbbb" in key for key in catalog)


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

    messages: list[str] = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")
    try:
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
    finally:
        logger.remove(sink_id)

    assert result.status == "accepted"
    assert result.recovery_used is True
    assert any(
        "report_section_submission_rejected"
        " section_code=section_001"
        " rejection_code=report_analysis_rework_unresolvable"
        " recovery_scope=section" in message
        for message in messages
    )


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


def test_validated_visual_receipts_soft_accepts_gate_degraded_revision():
    """收敛闸门降级提交的 requires_revision 回执按软告警接受（cli-report-48220a46
    实证：硬拒会把 section 打入 fresh attempt 死循环）。结构/身份校验保持硬性。"""
    result = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection().model_copy(update={"requires_revision": True}),),
    )
    plan = _visualization_plan()

    inspections = _validated_visual_receipts(result, plan)

    assert inspections[0].requires_revision is True

    unreviewed = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection().model_copy(update={"reviewed": False}),),
    )
    with pytest.raises(ReportingError) as caught:
        _validated_visual_receipts(unreviewed, plan)
    assert caught.value.code == "report_phase_artifact_changed"

    sha_mismatch = CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection().model_copy(update={"sha256": "c" * 64}),),
    )
    with pytest.raises(ReportingError) as caught:
        _validated_visual_receipts(sha_mismatch, plan)
    assert caught.value.code == "report_phase_artifact_changed"


@pytest.mark.anyio
async def test_visualization_deadline_passed_degrades_without_planner_call() -> None:
    generate_plan = AsyncMock(return_value=_visualization_plan())
    degrade = AsyncMock(return_value={"status": "accepted"})

    # 章节墙钟截止已过：新 attempt 不再调用 planner，直接零图收口。
    result = await VisualizationSectionWorkflow(
        generate_plan=generate_plan,
        run_code=AsyncMock(),
        submit=AsyncMock(),
        degrade=degrade,
        deadline=100.0,
        clock=lambda: 100.0,
    ).run(_visualization_payload(), _context())

    assert result.status == "degraded"
    assert result.plan.charts == ()
    generate_plan.assert_not_awaited()
    assert degrade.await_args.args[0].code == "report_visualization_section_deadline_exceeded"


@pytest.mark.anyio
async def test_visualization_deadline_stops_new_repairs_even_before_final_attempt() -> None:
    now = [0.0]

    async def failing_run_code(*_args, **_kwargs):
        # 第一次执行耗尽截止；即使失败可修复，也不得再开启新一轮修复。
        now[0] = 200.0
        raise ReportingError("report_visualization_script_failed", "脚本失败。")

    run_code = AsyncMock(side_effect=failing_run_code)
    degrade = AsyncMock(return_value={"status": "accepted"})

    result = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=run_code,
        submit=AsyncMock(),
        degrade=degrade,
        final_attempt=False,
        deadline=100.0,
        clock=lambda: now[0],
    ).run(_visualization_payload(), _context())

    assert result.status == "degraded"
    assert run_code.await_count == 1
    error = degrade.await_args.args[0]
    assert error.code == "report_visualization_section_deadline_exceeded"
    assert error.details["lastFailureCode"] == "report_visualization_script_failed"


@pytest.mark.anyio
async def test_visualization_without_deadline_keeps_repairing() -> None:
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64)
    result = CodeGenerationResult(
        script_file=script_file,
        execution_receipt=_execution_receipt(
            "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
        ),
        visual_inspection_receipts=(_inspection(),),
    )
    run_code = AsyncMock(
        side_effect=[ReportingError("report_visualization_script_failed", "失败"), result]
    )

    outcome = await VisualizationSectionWorkflow(
        generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=run_code,
        submit=AsyncMock(return_value={"status": "accepted"}),
        degrade=AsyncMock(),
        deadline=100.0,
        clock=lambda: 0.0,
    ).run(_visualization_payload(), _context())

    assert outcome.status == "accepted"
    assert run_code.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("code", "recovered"),
    [
        ("report_capability_state_invalid", False),
        ("report_workspace_capability_missing", False),
        ("report_section_citation_missing", True),
    ],
)
async def test_section_workflow_skips_model_recovery_for_infrastructure_failures(
    code: str, recovered: bool
) -> None:
    async def read(_path, _offset, _context):
        return _section_evidence_receipt()

    async def generate(_bundle, _context):
        return RenderSectionDecision.model_construct(
            section_code="section_001", blocks=(), claims=()
        )

    render_calls = 0

    async def render(_decision, _context):
        nonlocal render_calls
        render_calls += 1
        if render_calls == 1:
            raise ReportingError(code, "失败")
        return {"status": "accepted"}

    recover = AsyncMock(
        return_value=RenderSectionDecision.model_construct(
            section_code="section_001", blocks=(), claims=()
        )
    )
    workflow = SectionWorkflow(
        read_evidence=read,
        generate=generate,
        recover=recover,
        render=render,
        rework=AsyncMock(),
    )

    if recovered:
        result = await workflow.run(_section_work_item(), _context())
        assert result.recovery_used is True
    else:
        # 基础设施失败交由统一策略直接上抛，不白耗一次模型 recovery 调用。
        with pytest.raises(ReportingError, match=code):
            await workflow.run(_section_work_item(), _context())
        recover.assert_not_awaited()


@pytest.mark.parametrize(("goal", "count", "expected"), [
    ("一个分析项，包含一张图表", 1, 1),
    ("每项分析包含一张图表", 2, 2),
    ("使用1张图表展示趋势", 1, 1),
    ("分析成本，生成图表", 1, None),
    ("生成两张图表", 1, None),
])
def test_explicit_chart_count_follows_user_request(goal, count, expected):
    from smart_reporting.reporting.workflow.runtime.analysis import _limit_requested_charts, _requested_chart_limit

    assert _requested_chart_limit(goal, count) == expected
    charts = tuple(_chart().model_copy(update={"chart_id": f"chart_{index:03d}", "source_path": f"charts/{index}.png"}) for index in range(3))
    plan = _visualization_plan(charts=charts)
    result = _limit_requested_charts(plan, goal, count)
    assert len(result.charts) == (3 if expected is None else expected)
    assert result.charts[0].data_bindings == charts[0].data_bindings
    assert len(plan.charts) == 3


@pytest.mark.anyio
async def test_section_semantic_review_corrects_once_and_stays_soft(monkeypatch):
    from .test_content_review import _metric

    calls = []
    async def fake_stage(*args, **kwargs):
        payload = args[3]
        calls.append(dict(payload))
        text = "预算累计6,062,600人次。" if len(calls) == 1 else "预算累计{{value:fact-aaaaaaaaaaaaaaaa:periodTotals.0-9:人次}}。"
        return SectionContent.model_validate({"blocks": [{"blockId": "block_1", "markdown": text}]})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0],
        content=json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(606259,) * 12)]})),), factSummaries=())
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "预算执行", "claimIds": ["claim_1"]}],
        "claims": [_plan_claim("claim_1")]})
    result = await reporting_sections._generate_whole_section_content(object(), {}, evidence, work_item, plan,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"), run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    assert len(calls) == 2
    assert "6,062,600人次" in str(calls[1]["correction"]["issues"])
    assert result.blocks[0].markdown == "预算累计6,062,590人次。"
    assert result.blocks[0].citation_ids == ("citation_001",)


@pytest.mark.anyio
async def test_section_correction_covers_repetition_and_internal_ids(monkeypatch):
    from .test_content_review import _metric

    calls = []
    first = "本期门诊收入运行总体平稳，结构保持稳定。"
    second_clean = "住院收入结构有所变化，需结合科室明细复核。"
    outputs = iter([
        # 默认整章生成：第二个 block 重复第一个 block 的句子并泄漏内部 ID。
        {"block_1": first, "block_2": first + "另见 analysis_001 的明细。"},
        {"block_1": first, "block_2": second_clean},
    ])

    async def fake_stage(*args, **kwargs):
        calls.append(dict(args[3]))
        texts = next(outputs)
        return SectionContent.model_validate({"blocks": [
            {"blockId": block_id, "markdown": text} for block_id, text in texts.items()
        ]})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0],
        content=json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(606259,) * 12)]})),), factSummaries=())
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "门诊", "claimIds": ["claim_1"]},
                   {"blockId": "block_2", "objective": "住院", "claimIds": ["claim_2"]}],
        "claims": [_plan_claim("claim_1"), _plan_claim("claim_2")]})
    result = await reporting_sections._generate_whole_section_content(object(), {}, evidence, work_item, plan,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"), run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    assert len(calls) == 2
    correction = calls[1]["correction"]
    assert set(correction["issues"]) == {"block_2"}
    issues = "\n".join(correction["issues"]["block_2"])
    assert "与本章前文重复" in issues and "analysis_001" in issues
    # 纠错指令须覆盖可读性类问题，而不只是数字与口径。
    for keyword in ("业务名称", "重复", "拆分"):
        assert keyword in correction["requiredAction"]
    assert result.blocks[1].markdown == second_clean


@pytest.mark.anyio
async def test_whole_section_correction_only_replaces_blocks_with_issues(monkeypatch):
    from .test_content_review import _metric

    clean = "本期门诊收入运行总体平稳，结构保持稳定。"
    outputs = iter([
        {"block_1": clean, "block_2": "另见 analysis_001 的明细。"},
        # 纠错轮次把无问题的 block_1 改坏（引入无依据数字），只应采纳有问题的 block_2。
        {"block_1": "本期门诊收入为999元。", "block_2": "住院收入结构有所变化，需结合科室明细复核。"},
    ])

    async def fake_stage(*args, **kwargs):
        texts = next(outputs)
        return SectionContent.model_validate({"blocks": [
            {"blockId": block_id, "markdown": text} for block_id, text in texts.items()
        ]})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0],
        content=json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(606259,) * 12)]})),), factSummaries=())
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "门诊", "claimIds": ["claim_1"]},
                   {"blockId": "block_2", "objective": "住院", "claimIds": ["claim_2"]}],
        "claims": [_plan_claim("claim_1"), _plan_claim("claim_2")]})
    result = await reporting_sections._generate_whole_section_content(object(), {}, evidence, work_item, plan,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"), run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    assert [block.markdown for block in result.blocks] == [clean, "住院收入结构有所变化，需结合科室明细复核。"]


_FIRST_WITH_ISSUE = "另见 analysis_001 的明细。"
_WORSE_CORRECTION = "另见 analysis_001 与 fact-" + "a" * 16 + " 及 claim_001 的明细。"


@pytest.mark.anyio
async def test_whole_section_correction_that_adds_issues_is_reverted(monkeypatch):
    from .test_content_review import _metric

    outputs = iter([{"block_1": _FIRST_WITH_ISSUE}, {"block_1": _WORSE_CORRECTION}])

    async def fake_stage(*args, **kwargs):
        return SectionContent.model_validate({"blocks": [
            {"blockId": block_id, "markdown": text} for block_id, text in next(outputs).items()
        ]})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0],
        content=json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(606259,) * 12)]})),), factSummaries=())
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "门诊", "claimIds": ["claim_1"]}],
        "claims": [_plan_claim("claim_1")]})
    result = await reporting_sections._generate_whole_section_content(object(), {}, evidence, work_item, plan,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"), run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    # 纠错结果问题更多时保留首轮版本，不让纠错把正文改得更差。
    assert result.blocks[0].markdown == _FIRST_WITH_ISSUE


@pytest.mark.anyio
async def test_correction_that_fixes_accuracy_is_kept_despite_new_readability_issues(monkeypatch):
    from .test_content_review import _metric

    long_sentence = "门诊收入结构保持稳定并且持续优化" * 10
    fixed = f"{long_sentence}。{long_sentence}，后续继续观察。"
    # 首轮 1 个准确性问题（无依据数字）；纠错修正了数字但新增 2 个可读性问题，仍应采纳纠错。
    outputs = iter([{"block_1": "门诊收入为999元。"}, {"block_1": fixed}])

    async def fake_stage(*args, **kwargs):
        return SectionContent.model_validate({"blocks": [
            {"blockId": block_id, "markdown": text} for block_id, text in next(outputs).items()
        ]})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0],
        content=json.dumps({"analysisId": "analysis_001", "metrics": [_metric(values=(606259,) * 12)]})),), factSummaries=())
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "门诊", "claimIds": ["claim_1"]}],
        "claims": [_plan_claim("claim_1")]})
    result = await reporting_sections._generate_whole_section_content(object(), {}, evidence, work_item, plan,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"), run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    assert result.blocks[0].markdown == fixed


@pytest.mark.anyio
async def test_block_correction_that_adds_issues_is_reverted(monkeypatch):
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", factSummaries=(), files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0],
        content=json.dumps({"analysisId": "analysis_001", "metrics": []})),))
    block_outputs = iter([_FIRST_WITH_ISSUE, _WORSE_CORRECTION])

    async def fake_run_stage(_agent, _schema, stage, payload, **_kwargs):
        if stage == "plan":
            return SectionPlanOutput.model_validate({"kind": "render", "sectionCode": "section_001",
                "blocks": [{"blockId": "block_001", "objective": "收入", "claimIds": ["claim_001"]}],
                "claims": [_plan_claim("claim_001")]})
        return SectionBlockContent(markdown=next(block_outputs))

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_run_stage)
    result = await reporting_sections._generate_section_in_blocks(
        object(), {}, evidence, work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"),
    )
    assert result.blocks[0].markdown == _FIRST_WITH_ISSUE


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["timeout", "provider_unreachable", "context_hard_limit"])
async def test_section_semantic_correction_provider_failure_keeps_previous_content(monkeypatch, failure):
    calls = []
    async def fake_stage(*args, **kwargs):
        calls.append(args[3])
        if len(calls) > 1:
            if failure == "context_hard_limit":
                from smart_reporting.context_management import TaskExecutionContextHardLimitError
                raise TaskExecutionContextHardLimitError("纠错上下文超限", metrics={})
            if failure == "provider_unreachable":
                from agno.exceptions import ModelProviderError
                raise ModelProviderError("model provider unreachable")
            raise ReportingError("report_structured_output_timeout", "纠错服务暂不可用")
        return SectionContent.model_validate({"blocks": [{"blockId": "block_1", "markdown": "字段未填充有效数值，原因待核实。"}]})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "预算执行", "claimIds": ["claim_1"]}],
        "claims": [_plan_claim("claim_1")]})
    result = await reporting_sections._generate_whole_section_content(object(), {},
        SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
            identity=work_item.evidence[0].evidence_files[0], content="{}"),), factSummaries=()), work_item, plan,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"), run_context=_context(),
        thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    assert len(calls) == 2
    assert "待核实" in result.blocks[0].markdown


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["timeout", "provider_unreachable", "context_hard_limit"])
async def test_block_semantic_correction_provider_failure_keeps_previous_content(monkeypatch, failure):
    stages = []
    plan = {"sectionCode": "section_001",
            "blocks": [{"blockId": "block_1", "objective": "收入", "claimIds": ["claim_1"]}],
            "claims": [_plan_claim("claim_1")]}

    async def fake_stage(agent, schema, stage, payload, **kwargs):
        stages.append(stage)
        if stage == "plan":
            return SectionPlanOutput.model_validate({"kind": "render", **plan})
        if "correction" in payload:
            if failure == "context_hard_limit":
                from smart_reporting.context_management import TaskExecutionContextHardLimitError
                raise TaskExecutionContextHardLimitError("纠错上下文超限", metrics={})
            if failure == "provider_unreachable":
                from agno.exceptions import ModelProviderError
                raise ModelProviderError("model provider unreachable")
            raise ReportingError("report_structured_output_timeout", "纠错服务暂不可用")
        return SectionBlockContent(markdown="字段未填充有效数值，原因待核实。")

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fake_stage)
    work_item = _revenue_work_item()
    evidence = SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
        identity=work_item.evidence[0].evidence_files[0], content='{}'),), factSummaries=())
    result = await reporting_sections._generate_section_in_blocks(object(),
        {"reportGoal": "分析收入", "sectionGoal": {}}, evidence, work_item,
        scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
        run_context=_context(), thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))
    assert stages == ["plan", "block-1", "block-1"]
    assert "待核实" in result.blocks[0].markdown
    assert result.blocks[0].citation_ids == ("citation_001",)


@pytest.mark.anyio
async def test_initial_section_context_failure_is_not_reported_as_generated_content(monkeypatch):
    from smart_reporting.context_management import TaskExecutionContextHardLimitError

    async def fail_stage(*_args, **_kwargs):
        raise TaskExecutionContextHardLimitError("首次正文上下文超限", metrics={})

    monkeypatch.setattr(reporting_sections, "_run_section_stage", fail_stage)
    work_item = _revenue_work_item()
    plan = RenderSectionPlan.model_validate({"sectionCode": "section_001",
        "blocks": [{"blockId": "block_1", "objective": "收入", "claimIds": ["claim_1"]}],
        "claims": [_plan_claim("claim_1")]})
    with pytest.raises(TaskExecutionContextHardLimitError):
        await reporting_sections._generate_whole_section_content(object(), {},
            SectionEvidenceBundle(sectionCode="section_001", files=(SectionEvidenceFile(
                identity=work_item.evidence[0].evidence_files[0], content="{}"),), factSummaries=()), work_item, plan,
            scope=TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "section"),
            run_context=_context(), thinking_request=ThinkingRequest(operation="section_generation", complexity="standard"))


@pytest.mark.anyio
@pytest.mark.parametrize("collection", ["topGroups", "bottomGroups"])
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_visualization_repairs_ranked_detail_used_as_complete_distribution(
    collection: str, repair_succeeds: bool
) -> None:
    bad_payload = _chart().model_dump(mode="json", by_alias=True)
    bad_payload.update(title="全院收入构成占比", altText="各院区收入贡献分布", aggregationGrain="院区汇总", visualForm="构成饼图")
    bad_payload["dataBindings"][0].update(dataPath=f"metrics[0].{collection}", fields=["group", "value"])
    bad = ChartDraft.model_validate(bad_payload)
    repaired_payload = bad.model_dump(mode="json", by_alias=True)
    repaired_payload["dataBindings"][0].update(factPath="evidence/supplement.json", dataPath="findings[0].rows", fields=["area", "income"])
    repaired = ChartDraft.model_validate(repaired_payload)
    payload = _visualization_payload()
    facts = payload["visualizationFacts"][0]
    facts["dataDescriptors"] = [{"dataPath": f"metrics[0].{collection}", "fields": ["group", "value"]}]
    facts["supplementalEvidenceSources"] = [{"sourceFile": {"path": "evidence/supplement.json"}, "dataDescriptors": [{"dataPath": "findings[0].rows", "fields": ["area", "income"]}]}]
    original = VisualizationPlanDraft(charts=(bad,))
    generate = AsyncMock(side_effect=[original, VisualizationPlanDraft(charts=(repaired if repair_succeeds else bad,))])
    run_code = AsyncMock(return_value=CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",)),
        visual_inspection_receipts=(_inspection(),),
    ))
    submit = AsyncMock(return_value={"status": "accepted"})
    result = await VisualizationSectionWorkflow(generate_plan=generate, run_code=run_code, submit=submit).run(payload, _context())

    assert generate.await_count == 2
    repair_payload = generate.await_args_list[1].args[0]
    assert repair_payload["scopeCorrections"][0]["dataPath"] == f"metrics[0].{collection}"
    assert "完整" in repair_payload["scopeCorrections"][0]["message"]
    assert result.status == "accepted"
    if repair_succeeds:
        assert result.plan.charts == (repaired,)
        run_code.assert_awaited_once()
    else:
        assert result.plan.charts == ()
        assert any("图表数据范围" in w for w in result.plan.warnings)
        run_code.assert_not_awaited()
    submit.assert_awaited_once()


@pytest.mark.anyio
async def test_visualization_explicit_ranked_detail_needs_no_scope_repair() -> None:
    payload = _visualization_payload()
    payload["visualizationFacts"][0]["dataDescriptors"] = [{"dataPath": "metrics[0].topGroups", "fields": ["group", "value"]}]
    raw = _chart().model_dump(mode="json", by_alias=True)
    raw.update(title="收入最高10条组合明细", altText="收入最高10条明细记录，范围为排序子集", aggregationGrain="组合明细记录")
    raw["dataBindings"][0].update(dataPath="metrics[0].topGroups", fields=["group", "value"])
    chart = ChartDraft.model_validate(raw)
    generate = AsyncMock(return_value=VisualizationPlanDraft(charts=(chart,)))
    run_code = AsyncMock(return_value=CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",)),
        visual_inspection_receipts=(_inspection(),),
    ))
    result = await VisualizationSectionWorkflow(generate_plan=generate, run_code=run_code, submit=AsyncMock(return_value={"status": "accepted"})).run(payload, _context())
    assert result.plan.charts == (chart,)
    generate.assert_awaited_once()


@pytest.mark.anyio
async def test_visualization_scope_repair_failure_keeps_unaffected_chart_and_delivery() -> None:
    raw = _chart().model_dump(mode="json", by_alias=True)
    raw.update(chartId="unsafe", sourcePath="charts/unsafe.png", title="全院成本构成", altText="全院成本比例", aggregationGrain="成本类别")
    raw["dataBindings"][0].update(dataPath="metrics[0].topGroups", fields=["group", "value"])
    bad = ChartDraft.model_validate(raw)
    payload = _visualization_payload()
    payload["visualizationFacts"][0]["dataDescriptors"].append({"dataPath": "metrics[0].topGroups", "fields": ["group", "value"]})
    generate = AsyncMock(side_effect=[VisualizationPlanDraft(charts=(_chart(), bad)), ReportingError("report_generator_failed", "纠正模型不可用")])
    run_code = AsyncMock(return_value=CodeGenerationResult(
        script_file=FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64),
        execution_receipt=_execution_receipt("charts/charts.py", 1, "b" * 64, ("charts/chart.png",)),
        visual_inspection_receipts=(_inspection(),),
    ))
    submit = AsyncMock(return_value={"status": "accepted"})
    result = await VisualizationSectionWorkflow(generate_plan=generate, run_code=run_code, submit=submit).run(payload, _context())
    assert result.status == "accepted"
    assert result.plan.charts == (_chart(),)
    assert any("unsafe" in w and "图表数据范围" in w for w in result.plan.warnings)
    assert generate.await_count == 2
    run_code.assert_awaited_once()
    submit.assert_awaited_once()


def test_chart_input_preserves_ranked_subset_scope_for_plotting() -> None:
    from smart_reporting.reporting.workflow.runtime.chart_inputs import materialize_chart_inputs

    raw = _chart().model_dump(mode="json", by_alias=True)
    raw["dataBindings"][0].update(dataPath="metrics[0].topGroups", fields=["group", "value"])
    chart = ChartDraft.model_validate(raw)
    facts = [{"analysisId": "analysis_001", "factFile": {"path": "facts/analysis_001.json", "sha256": "a" * 64}, "dataDescriptors": [{"dataPath": "metrics[0].topGroups", "fields": ["group", "value"]}]}]
    documents = {"facts/analysis_001.json": {"metrics": [{"topGroups": [{"group": "2025-07 / 总部 / 住院", "value": 23846533}, {"group": "2025-03 / 总部 / 住院", "value": 23657899}]}]}}
    result = materialize_chart_inputs(VisualizationPlanDraft(charts=(chart,)), facts, documents, output_root="charts/input")
    file = json.loads(result.files[0].content)
    assert file["rows"] == [["2025-07 / 总部 / 住院", 23846533], ["2025-03 / 总部 / 住院", 23657899]]
    assert file["dataScope"] == result.entries[0]["dataScope"]
    assert file["dataScope"]["coverage"] == "ranked_subset"
    assert file["dataScope"]["canRepresentFullDistribution"] is False
