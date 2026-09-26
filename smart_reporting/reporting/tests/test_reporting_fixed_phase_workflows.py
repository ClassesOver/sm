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
        message for message in messages
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
        message for message in messages
        if "report_visualization_binding_mismatch" in str(message)
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
    state = _analysis_state_with_requirement(
        dataset_id="dataset_other", fields=("income",)
    )
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
    assert projection["metrics"][0]["periodValueFields"] == ["period", "value"]
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
                    "findings": [{
                        "name": "科室同比",
                        "columns": ["科室", "同比增速(%)"],
                        "rows": [["普通外科", 23.84], ["高血压研究所", None]],
                    }],
                    "reconciliations": [{"name": "同比口径核对", "passed": True}],
                }, ensure_ascii=False
            ).encode()
        ),
    )
    fact_file = FileIdentity(path="facts/a.json", size=2, sha256="a" * 64)
    supplement_file = FileIdentity(path="analysis/a/supplement.json", size=2, sha256="b" * 64)

    projection = await RuntimeAnalysisMixin._visualization_section_fact_projection(
        runtime, "analysis_001", fact_file,
        {"datasetIds": ["dataset_001"], "evidenceFiles": [supplement_file.model_dump(mode="json", by_alias=True)]},
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
    receipt = _execution_receipt(
        "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
    )
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
    submit.assert_awaited_once_with(
        _visualization_plan(), (_inspection(),), _context()
    )


@pytest.mark.anyio
async def test_visualization_workflow_passes_benchmark_projection_to_coding() -> None:
    script_file = FileIdentity(path="charts/charts.py", size=1, sha256="b" * 64)
    receipt = _execution_receipt(
        "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
    )
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
    receipt = _execution_receipt(
        "charts/charts.py", 1, "b" * 64, ("charts/chart.png",)
    )
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

    assert [
        call.kwargs["benchmark_projection"] for call in run_code.await_args_list
    ] == [projection, projection]
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
        submit=AsyncMock(side_effect=[
            ReportingError("report_chart_file_missing", "missing"),
            {"status": "accepted"},
        ]),
        benchmark_projection=projection,
    ).run(_visualization_payload(), _context())

    assert [
        call.kwargs["benchmark_projection"] for call in run_code.await_args_list
    ] == [projection, projection]
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
async def test_section_recovery_uses_one_bounded_thinking_upgrade(
    monkeypatch: pytest.MonkeyPatch,
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
        thinking_request=ThinkingRequest(
            operation="section_generation",
            complexity="standard",
        ),
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
        visual_inspection_receipts=(_inspection().model_copy(
            update={"requires_revision": True}
        ),),
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
