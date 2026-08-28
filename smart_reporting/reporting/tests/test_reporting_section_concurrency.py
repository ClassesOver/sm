from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.delivery.artifacts_v1 import Citation
from smart_reporting.reporting.delivery.draft_v1 import ReportDraftBlock
from smart_reporting.reporting.hospital_operation.detailed_analysis import (
    DetailedAnalysisItem,
    DetailedAnalysisPlan,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisChart,
    AnalysisDatasetSemantics,
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    AnalysisReworkRequest,
    ChartVisualInspectionReceipt,
    CheckpointError,
    CheckpointRetryUsage,
    CompletedSection,
    ContextTrace,
    FileIdentity,
    MetricDefinition,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
    ReportBrief,
    ReportingCheckpoint,
    SectionArtifact,
    SectionClaim,
    SectionWorkItem,
)
from smart_reporting.reporting.workflow.runtime import (
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    ReportWorkflowRuntime,
)
from smart_reporting.reporting.workflow.runtime import analysis as runtime_analysis
from smart_reporting.reporting.workflow.runtime import sections as runtime_sections
from smart_reporting.reporting.workflow.runtime.analysis import (
    _analysis_fact_retry_usage,
    _checkpoint_retry_error,
    _run_pending_analysis_items,
    _visualization_retry_usage,
)
from smart_reporting.reporting.workflow.runtime.sections import _run_bounded, _section_retry_context


@pytest.mark.anyio
async def test_dataset_publication_gate_classifies_disclosed_data_limits_as_warnings() -> None:
    stored = checkpoint(completed=(), pending=())
    assert stored.evidence_manifest is not None
    stored = stored.model_copy(
        update={
            "evidence_manifest": stored.evidence_manifest.model_copy(
                update={
                    "metric_definitions": (
                        MetricDefinition(
                            code="income_yoy",
                            name="医疗收入同比",
                            definition="2025年1-11月相对2024年全年，仅作参考性对比",
                            unit="%",
                            periodBasis="2025年1-11月 vs 2024年全年（期间跨度不一致）",
                        ),
                    ),
                    "warnings": (
                        "2025年11月数据缺失，累计口径不完整。",
                        "期间索引存在重复，需先按月及组织粒度聚合。",
                    ),
                }
            )
        }
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                payload={"workflowCheckpoint": stored.model_dump(mode="json", by_alias=True)}
            )
        )
    )
    runtime.workspace_service = SimpleNamespace(ahash_file=AsyncMock(return_value={}))
    context = SimpleNamespace(
        run_id="run-1",
        session_id="thread-1",
        user_id="user-1",
        dependencies=None,
        session_state={REPORT_WORKFLOW_RESULT_STATE_KEY: {"datasets": []}},
    )

    gate = await runtime._dataset_publication_gate(
        context,
        {
            "status": "validated",
            "markdownPath": "report.md",
            "pdfPath": "report.pdf",
            "wordPath": "report.docx",
        },
    )

    warning_codes = {item["code"] for item in gate["warnings"]}
    issue_codes = {item["code"] for item in gate["issues"]}
    assert {
        "analysis_period_incomparable",
        "analysis_data_incomplete",
        "analysis_data_quality",
    }.isdisjoint(issue_codes)
    assert {
        "analysis_period_incomparable",
        "analysis_data_incomplete",
        "analysis_data_quality",
    } <= warning_codes


@pytest.mark.anyio
async def test_run_bounded_limits_concurrency_and_preserves_input_order() -> None:
    active = 0
    maximum = 0
    lock = asyncio.Lock()

    async def worker(value: int) -> int:
        nonlocal active, maximum
        async with lock:
            active += 1
            maximum = max(maximum, active)
        await asyncio.sleep((5 - value) * 0.005)
        async with lock:
            active -= 1
        return value * 10

    result = await _run_bounded((1, 2, 3, 4), concurrency=2, worker=worker)

    assert maximum == 2
    assert result == [10, 20, 30, 40]


@pytest.mark.anyio
async def test_run_bounded_finishes_siblings_and_raises_original_failure() -> None:
    failure = ReportingError(
        "report_worker_failed",
        "章节 section_001 未调用终态工具。",
        details={"sectionCode": "section_001"},
    )
    observed: list[str] = []

    async def worker(section_code: str) -> str:
        await asyncio.sleep(0)
        observed.append(section_code)
        if section_code == "section_001":
            raise failure
        return section_code

    with pytest.raises(ReportingError) as raised:
        await _run_bounded(
            ("section_001", "section_002"),
            concurrency=2,
            worker=worker,
        )

    assert raised.value is failure
    assert set(observed) == {"section_001", "section_002"}


def test_analysis_rework_constraints_bind_frozen_plan_and_profile_receipts() -> None:
    plan = DetailedAnalysisPlan(
        datasetIds=("dataset-1",),
        analyses=(
            DetailedAnalysisItem(
                analysisId="analysis_001",
                domain="income",
                managementQuestion="收入表现如何？",
                primaryMetricFamily="收入",
                datasetIds=("dataset-1",),
                fields=("month", "revenue"),
                metrics=("revenue",),
                periods=("2026-01",),
                actions=("趋势",),
                evidenceSummary="收入趋势事实。",
                suggestedSection="收入分析",
                completionConditions=("说明收入趋势",),
            ),
        ),
    )
    profile_coverage = checkpoint(completed=(), pending=()).profile_coverage

    constraints = ReportWorkflowRuntime._analysis_rework_constraints(
        detailed_plan=plan,
        profile_coverage=profile_coverage,
        analysis_ids=("analysis_001",),
    )

    assert constraints["analysis_001"]["datasetIds"] == ["dataset-1"]
    assert constraints["analysis_001"]["periods"] == ["2026-01"]
    assert constraints["analysis_001"]["metrics"] == ["revenue"]
    assert constraints["analysis_001"]["profileDatasets"] == [
        {
            "datasetId": "dataset-1",
            "rowCount": 1,
            "profileSnapshotHash": "b" * 64,
        }
    ]
    assert len(constraints["analysis_001"]["planHash"]) == 64


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("concurrency", "expected_started"),
    [
        (1, ["section_001"]),
        (2, ["section_001", "section_002"]),
    ],
)
async def test_section_batches_stop_scheduling_after_completed_batch_requests_rework(
    concurrency: int,
    expected_started: list[str],
) -> None:
    started: list[str] = []
    rework = AnalysisReworkRequest(
        sectionCode="section_001",
        analysisIds=("analysis_001",),
        reason="当前冻结事实不足。",
        missingEvidence=("重算当前冻结期间。",),
    )

    async def worker(section_code: str) -> tuple[None, None, AnalysisReworkRequest | None]:
        started.append(section_code)
        await asyncio.sleep(0)
        return None, None, rework if section_code == "section_001" else None

    results = await runtime_sections._run_section_batches_until_rework(
        ("section_001", "section_002", "section_003"),
        concurrency=concurrency,
        worker=worker,
    )

    assert started == expected_started
    assert len(results) == concurrency
    assert results[0][2] == rework


@pytest.mark.anyio
async def test_section_worker_defers_rework_transition_until_batch_finishes() -> None:
    stored = checkpoint(completed=(), pending=("section_001",))
    work_item = section_work_item("section_001")
    request = AnalysisReworkRequest(
        sectionCode="section_001",
        analysisIds=("analysis_001",),
        reason="当前冻结事实不足。",
        missingEvidence=("重算当前冻结期间。",),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_worker = SimpleNamespace(id="worker-1")
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }
    runtime._state = lambda _run_context: {
        "report_outline": {
            "reportType": "comprehensive",
            "title": "经营分析",
            "sections": [
                {
                    "code": "section_001",
                    "sectionNumber": "1",
                    "title": "收入分析",
                    "analysisIds": ["analysis_001"],
                }
            ],
        }
    }
    runtime._durable_completed_section = AsyncMock(return_value=None)
    runtime._write_artifact_validation_context = AsyncMock(
        return_value={"path": "sections/work-item.json", "size": 1, "sha256": "a" * 64}
    )
    runtime._persist_reporting_checkpoint = AsyncMock(side_effect=lambda _context, value: value)
    runtime._apply_durable_command = AsyncMock()
    runtime._trace_metrics_from_receipt = lambda _receipt: {}
    runtime.task_runner = SimpleNamespace(
        repository=SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None)),
        start=AsyncMock(),
        run=AsyncMock(return_value={}),
    )

    async def rework_identity(
        _thread_id: str, _receipt: Any, expected_paths: tuple[str, ...]
    ) -> FileIdentity:
        return FileIdentity(path=expected_paths[1], size=1, sha256="b" * 64)

    runtime._phase_artifact_from_receipt = rework_identity
    runtime._read_identity_model = AsyncMock(return_value=request)

    candidate, artifact, returned_request = await runtime._run_section_phase(
        SimpleNamespace(run_id="run-1"),
        checkpoint=stored,
        revision=1,
        sandbox_id="sandbox-1",
        validation_context_file=FileIdentity(
            path="validation/context.json", size=1, sha256="c" * 64
        ),
        work_item=work_item,
        analysis_rework_constraints={},
    )

    assert artifact is None
    assert returned_request == request
    assert candidate.phase == "sections"
    assert candidate.report_brief == stored.report_brief
    assert candidate.evidence_manifest == stored.evidence_manifest
    assert candidate.analysis_manifest_file == stored.analysis_manifest_file
    assert [call.args[1].name for call in runtime._apply_durable_command.await_args_list] == [
        "start_section"
    ]


def test_pending_analysis_rework_survives_fresh_retry_without_analysis_manifest() -> None:
    rework_file = FileIdentity(path="sections/income.rework.json", size=1, sha256="a" * 64)
    stored = checkpoint(completed=(), pending=("section_001",)).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
            "trace": (
                ContextTrace(
                    phase="section",
                    taskId="section-income",
                    workKind="section",
                    sectionCode="section_001",
                    status="rework",
                    artifactFile=rework_file,
                ),
                ContextTrace(
                    phase="analysis",
                    taskId="analysis-income",
                    workKind="analysis_item",
                    analysisId="analysis_001",
                    status="completed",
                    retryReason="analysis_rework:targeted",
                ),
            ),
        }
    )

    assert runtime_sections._pending_analysis_rework_file(stored) == rework_file


def test_pending_analysis_rework_is_covered_by_later_visualization_freeze() -> None:
    rework_file = FileIdentity(path="sections/income.rework.json", size=1, sha256="a" * 64)
    stored = checkpoint(completed=(), pending=("section_001",)).model_copy(
        update={
            "phase": "analysis",
            "trace": (
                ContextTrace(
                    phase="section",
                    taskId="section-income",
                    workKind="section",
                    sectionCode="section_001",
                    status="rework",
                    artifactFile=rework_file,
                ),
                ContextTrace(
                    phase="analysis",
                    taskId="analysis-visualization",
                    workKind="visualization",
                    status="completed",
                ),
            ),
        }
    )

    assert runtime_sections._pending_analysis_rework_file(stored) is None


def test_section_retry_context_preserves_structured_failure_details() -> None:
    error = ReportingError(
        "report_section_completion_conflict",
        "章节图表绑定冲突。",
        details={
            "chartId": "chart-income",
            "claimId": "claim-income",
            "conflictType": "metric_mismatch",
            "expected": "income_yoy",
            "actual": "income_total",
        },
    )

    assert _section_retry_context(error) == {
        "code": "report_section_completion_conflict",
        "message": "章节图表绑定冲突。",
        "details": {
            "chartId": "chart-income",
            "claimId": "claim-income",
            "conflictType": "metric_mismatch",
            "expected": "income_yoy",
            "actual": "income_total",
        },
    }
    checkpoint_error = CheckpointError(
        phase="section",
        code=error.code,
        message=error.message,
        sectionCode="section_001",
        details=error.details,
    )
    assert _section_retry_context(checkpoint_error) == _section_retry_context(error)


@pytest.mark.anyio
async def test_run_pending_analysis_items_skips_completed_and_limits_concurrency() -> None:
    active = 0
    maximum = 0
    observed: list[str] = []
    lock = asyncio.Lock()

    async def worker(analysis_id: str) -> None:
        nonlocal active, maximum
        async with lock:
            active += 1
            maximum = max(maximum, active)
        await asyncio.sleep(0.005)
        observed.append(analysis_id)
        async with lock:
            active -= 1

    scheduled = await _run_pending_analysis_items(
        ("analysis_001", "analysis_002", "analysis_003", "analysis_004"),
        completed_analysis_ids={"analysis_002"},
        concurrency=2,
        worker=worker,
    )

    assert scheduled == ("analysis_001", "analysis_003", "analysis_004")
    assert set(observed) == set(scheduled)
    assert maximum == 2


@pytest.mark.anyio
async def test_run_pending_analysis_items_finishes_siblings_before_raising_failure() -> None:
    observed: list[str] = []

    async def worker(analysis_id: str) -> None:
        await asyncio.sleep(0)
        observed.append(analysis_id)
        if analysis_id == "analysis_002":
            raise RuntimeError("analysis failed")

    with pytest.raises(RuntimeError, match="analysis failed"):
        await _run_pending_analysis_items(
            ("analysis_001", "analysis_002", "analysis_003"),
            completed_analysis_ids=set(),
            concurrency=3,
            worker=worker,
        )

    assert set(observed) == {"analysis_001", "analysis_002", "analysis_003"}


def test_reporting_checkpoint_serializes_deterministic_fact_file_mapping() -> None:
    fact_file = FileIdentity(
        path="报表/智能分析/run-1/facts/revision-1/analysis_001.json",
        size=12,
        sha256="f" * 64,
    )

    stored = analysis_checkpoint(deterministic_fact_files={"analysis_001": fact_file})

    assert stored.model_dump(mode="json", by_alias=True)["deterministicFactFiles"] == {
        "analysis_001": fact_file.model_dump(mode="json", by_alias=True)
    }


@pytest.mark.anyio
async def test_deterministic_fact_mapping_is_revalidated_without_recalculation() -> None:
    fact_file = FileIdentity(
        path="报表/智能分析/run-1/facts/revision-1/analysis_001.json",
        size=12,
        sha256="f" * 64,
    )
    stored = analysis_checkpoint(deterministic_fact_files={"analysis_001": fact_file})
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(
        ahash_file=AsyncMock(return_value=fact_file.model_dump(mode="json", by_alias=True))
    )
    runtime._prepare_deterministic_analysis_facts = AsyncMock()
    runtime._persist_reporting_checkpoint = AsyncMock()

    restored, fact_files = await runtime._restore_or_create_deterministic_analysis_facts(
        run_context=SimpleNamespace(run_id="run-1"),
        checkpoint=stored,
        thread_id="thread-1",
        report_run_id="run-1",
        revision=1,
        detailed_plan=analysis_plan("analysis_001"),
        dataset_handles=(),
    )

    assert restored is stored
    assert fact_files == {"analysis_001": fact_file}
    runtime.workspace_service.ahash_file.assert_awaited_once_with("thread-1", fact_file.path)
    runtime._prepare_deterministic_analysis_facts.assert_not_awaited()
    runtime._persist_reporting_checkpoint.assert_not_awaited()


@pytest.mark.anyio
async def test_legacy_v2_checkpoint_recovers_fact_mapping_only_from_canonical_files() -> None:
    fact_files = {
        analysis_id: FileIdentity(
            path=f"报表/智能分析/run-1/facts/revision-1/{analysis_id}.json",
            size=index,
            sha256=str(index) * 64,
        )
        for index, analysis_id in enumerate(("analysis_001", "analysis_002"), start=1)
    }
    stored = analysis_checkpoint(
        files=tuple(fact_files.values()),
        trace=(
            ContextTrace(
                phase="analysis",
                taskId="legacy-analysis-task",
                workKind="analysis_item",
                analysisId="analysis_001",
            ),
        ),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(
        ahash_file=AsyncMock(
            side_effect=[
                identity.model_dump(mode="json", by_alias=True) for identity in fact_files.values()
            ]
        )
    )
    runtime._prepare_deterministic_analysis_facts = AsyncMock()
    runtime._persist_reporting_checkpoint = AsyncMock(side_effect=lambda _context, value: value)

    restored, recovered = await runtime._restore_or_create_deterministic_analysis_facts(
        run_context=SimpleNamespace(run_id="run-1"),
        checkpoint=stored,
        thread_id="thread-1",
        report_run_id="run-1",
        revision=1,
        detailed_plan=analysis_plan("analysis_001", "analysis_002"),
        dataset_handles=(),
    )

    assert recovered == fact_files
    assert restored.deterministic_fact_files == fact_files
    runtime._prepare_deterministic_analysis_facts.assert_not_awaited()
    runtime._persist_reporting_checkpoint.assert_awaited_once()


@pytest.mark.anyio
async def test_legacy_checkpoint_rejects_noncanonical_deterministic_fact_file() -> None:
    stored = analysis_checkpoint(
        files=(
            FileIdentity(
                path="报表/智能分析/run-1/facts/revision-2/analysis_001.json",
                size=1,
                sha256="a" * 64,
            ),
        )
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(ahash_file=AsyncMock())
    runtime._prepare_deterministic_analysis_facts = AsyncMock()
    runtime._persist_reporting_checkpoint = AsyncMock()

    with pytest.raises(ReportingError) as raised:
        await runtime._restore_or_create_deterministic_analysis_facts(
            run_context=SimpleNamespace(run_id="run-1"),
            checkpoint=stored,
            thread_id="thread-1",
            report_run_id="run-1",
            revision=1,
            detailed_plan=analysis_plan("analysis_001"),
            dataset_handles=(),
        )

    assert raised.value.code == "report_semantic_contract_upgrade_required"
    runtime.workspace_service.ahash_file.assert_not_awaited()
    runtime._prepare_deterministic_analysis_facts.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fact_files",
    [
        {
            "analysis_999": FileIdentity(
                path="报表/智能分析/run-1/facts/revision-1/analysis_001.json",
                size=1,
                sha256="a" * 64,
            )
        },
        {
            "analysis_001": FileIdentity(
                path="报表/智能分析/run-1/facts/revision-1/analysis_002.json",
                size=1,
                sha256="a" * 64,
            )
        },
    ],
)
async def test_checkpoint_rejects_wrong_analysis_fact_mapping(
    fact_files: dict[str, FileIdentity],
) -> None:
    stored = analysis_checkpoint(deterministic_fact_files=fact_files)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(ahash_file=AsyncMock())
    runtime._prepare_deterministic_analysis_facts = AsyncMock()
    runtime._persist_reporting_checkpoint = AsyncMock()

    with pytest.raises(ReportingError) as raised:
        await runtime._restore_or_create_deterministic_analysis_facts(
            run_context=SimpleNamespace(run_id="run-1"),
            checkpoint=stored,
            thread_id="thread-1",
            report_run_id="run-1",
            revision=1,
            detailed_plan=analysis_plan("analysis_001"),
            dataset_handles=(),
        )

    assert raised.value.code == "report_semantic_contract_upgrade_required"
    runtime.workspace_service.ahash_file.assert_not_awaited()
    runtime._prepare_deterministic_analysis_facts.assert_not_awaited()


@pytest.mark.anyio
async def test_checkpoint_rejects_changed_deterministic_fact_file() -> None:
    fact_file = FileIdentity(
        path="报表/智能分析/run-1/facts/revision-1/analysis_001.json",
        size=12,
        sha256="f" * 64,
    )
    stored = analysis_checkpoint(deterministic_fact_files={"analysis_001": fact_file})
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(
        ahash_file=AsyncMock(return_value={"path": fact_file.path, "size": 13, "sha256": "e" * 64})
    )
    runtime._prepare_deterministic_analysis_facts = AsyncMock()
    runtime._persist_reporting_checkpoint = AsyncMock()

    with pytest.raises(ReportingError) as raised:
        await runtime._restore_or_create_deterministic_analysis_facts(
            run_context=SimpleNamespace(run_id="run-1"),
            checkpoint=stored,
            thread_id="thread-1",
            report_run_id="run-1",
            revision=1,
            detailed_plan=analysis_plan("analysis_001"),
            dataset_handles=(),
        )

    assert raised.value.code == "report_analysis_facts_changed"
    runtime._prepare_deterministic_analysis_facts.assert_not_awaited()


@pytest.mark.anyio
async def test_new_deterministic_facts_are_checkpointed_before_analysis_workers() -> None:
    fact_file = FileIdentity(
        path="报表/智能分析/run-1/facts/revision-1/analysis_001.json",
        size=12,
        sha256="f" * 64,
    )
    stored = analysis_checkpoint()
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(ahash_file=AsyncMock())
    runtime._prepare_deterministic_analysis_facts = AsyncMock(
        return_value={"analysis_001": fact_file}
    )
    runtime._persist_reporting_checkpoint = AsyncMock(side_effect=lambda _context, value: value)

    restored, fact_files = await runtime._restore_or_create_deterministic_analysis_facts(
        run_context=SimpleNamespace(run_id="run-1"),
        checkpoint=stored,
        thread_id="thread-1",
        report_run_id="run-1",
        revision=1,
        detailed_plan=analysis_plan("analysis_001"),
        dataset_handles=(),
    )

    assert fact_files == {"analysis_001": fact_file}
    assert restored.deterministic_fact_files == fact_files
    assert fact_file in restored.files
    runtime._persist_reporting_checkpoint.assert_awaited_once()


def test_fresh_retry_restores_stable_error_for_matching_failed_work() -> None:
    stored = checkpoint(completed=(), pending=()).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
            "last_error": CheckpointError(
                phase="analysis",
                code="report_analysis_fact_query_budget_exhausted",
                message="事实查询预算耗尽。",
                retryReason="report_analysis_fact_query_budget_exhausted",
                taskId="analysis-task-1",
                workKind="analysis_item",
                analysisId="analysis_001",
                attempt=0,
                retryUsage=CheckpointRetryUsage(analysisFactQueriesUsed=2),
            ),
            "trace": (
                ContextTrace(
                    phase="analysis",
                    taskId="analysis-task-1",
                    workKind="analysis_item",
                    analysisId="analysis_001",
                    status="failed",
                    retryReason=None,
                ),
            ),
        }
    )

    restored = _checkpoint_retry_error(
        stored,
        work_kind="analysis_item",
        analysis_id="analysis_001",
        retry_reason=None,
    )

    assert isinstance(restored, ReportingError)
    assert restored.code == "report_analysis_fact_query_budget_exhausted"
    assert restored.message == "事实查询预算耗尽。"
    assert _analysis_fact_retry_usage(restored) == 2
    assert (
        _checkpoint_retry_error(
            stored,
            work_kind="visualization",
            analysis_id=None,
            retry_reason=None,
        )
        is None
    )


def test_fresh_retry_does_not_bind_another_work_items_error() -> None:
    stored = checkpoint(completed=(), pending=()).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
            "last_error": CheckpointError(
                phase="analysis",
                code="report_visualization_tool_budget_exhausted",
                message="A 的预算耗尽。",
                taskId="visualization-task-a",
                workKind="visualization",
                attempt=0,
                retryUsage=CheckpointRetryUsage(
                    visualizationReadUnitsUsed=11,
                    visualizationFactQueriesUsed=3,
                    visualizationToolCalls=47,
                    visualizationScriptFailures=2,
                    visualizationAttemptSuccessfulToolCalls=40,
                    visualizationAttemptRejectedToolCalls=7,
                ),
            ),
            "trace": (
                ContextTrace(
                    phase="analysis",
                    taskId="visualization-task-a",
                    workKind="visualization",
                    attempt=0,
                    status="failed",
                ),
                ContextTrace(
                    phase="analysis",
                    taskId="visualization-task-b",
                    workKind="visualization",
                    attempt=1,
                    status="failed",
                ),
            ),
        }
    )

    with pytest.raises(ReportingError) as mismatch:
        _checkpoint_retry_error(
            stored,
            work_kind="visualization",
            analysis_id=None,
            retry_reason=None,
        )
    assert mismatch.value.code == "report_semantic_contract_upgrade_required"

    only_a = stored.model_copy(update={"trace": stored.trace[:1]})
    restored = _checkpoint_retry_error(
        only_a,
        work_kind="visualization",
        analysis_id=None,
        retry_reason=None,
    )
    assert _visualization_retry_usage(restored) == {
        "visualizationReadUnitsUsed": 11,
        "visualizationFactQueriesUsed": 3,
        "visualizationToolCalls": 47,
        "visualizationScriptFailures": 2,
    }
    restored_usage = getattr(restored, REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR)
    assert restored_usage["visualizationAttemptSuccessfulToolCalls"] == 40
    assert restored_usage["visualizationAttemptRejectedToolCalls"] == 7


def test_fresh_retry_rejects_incomplete_checkpoint_instead_of_resetting_budget() -> None:
    stored = checkpoint(completed=(), pending=()).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
            "last_error": CheckpointError(
                phase="analysis",
                code="report_analysis_fact_query_budget_exhausted",
                message="旧 checkpoint 未保存恢复身份和预算。",
            ),
            "trace": (
                ContextTrace(
                    phase="analysis",
                    taskId="analysis-task-legacy",
                    workKind="analysis_item",
                    analysisId="analysis_001",
                    attempt=0,
                    status="failed",
                ),
            ),
        }
    )

    with pytest.raises(ReportingError) as raised:
        _checkpoint_retry_error(
            stored,
            work_kind="analysis_item",
            analysis_id="analysis_001",
            retry_reason=None,
        )

    assert raised.value.code == "report_semantic_contract_upgrade_required"


@pytest.mark.parametrize(
    ("previous_mode", "current_mode"),
    [("vision", "deterministic"), ("deterministic", "vision")],
)
def test_visualization_capability_drift_fails_closed(
    previous_mode: str,
    current_mode: str,
) -> None:
    trace = ContextTrace.model_construct(
        phase="analysis",
        task_id="visualization-task-1",
        work_kind="visualization",
        attempt=0,
        status="failed",
        visual_inspection_mode=previous_mode,
    )
    stored = checkpoint(completed=(), pending=()).model_copy(update={"trace": (trace,)})

    with pytest.raises(ReportingError) as raised:
        runtime_analysis._ensure_visual_inspection_capability(stored, current_mode)

    assert raised.value.code == "report_visualization_capability_changed"


def test_visualization_capability_is_stable_across_fresh_retry() -> None:
    trace = ContextTrace.model_construct(
        phase="analysis",
        task_id="visualization-task-1",
        work_kind="visualization",
        attempt=0,
        status="failed",
        visual_inspection_mode="deterministic",
    )
    stored = checkpoint(completed=(), pending=()).model_copy(update={"trace": (trace,)})

    runtime_analysis._ensure_visual_inspection_capability(stored, "deterministic")


@pytest.mark.anyio
async def test_visualization_retry_projects_citation_ids_into_each_worker_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = DetailedAnalysisPlan(
        datasetIds=("dataset-income",),
        analyses=(
            DetailedAnalysisItem(
                analysisId="analysis_001",
                domain="income",
                managementQuestion="收入趋势",
                primaryMetricFamily="收入",
                datasetIds=("dataset-income",),
                fields=(),
                metrics=(),
                periods=(),
                actions=("趋势",),
                evidenceSummary="固定事实",
                suggestedSection="收入",
                completionConditions=("完成",),
            ),
        ),
    )
    checkpoint_before_visualization = checkpoint(completed=(), pending=()).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
        }
    )
    fact_file = FileIdentity(path="facts/analysis_001.json", size=1, sha256="f" * 64)
    durable = SimpleNamespace(
        payload={
            "completedAnalysisIds": ["analysis_001"],
            "analysisItems": {
                "analysis_001": {
                    "summary": "收入同比增长。",
                    "evidenceFiles": [
                        {"path": "evidence/income.json", "size": 2, "sha256": "e" * 64}
                    ],
                    "citationIds": ["citation-000"],
                }
            },
            "charts": [],
        }
    )
    task_runner = SimpleNamespace(
        repository=SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None)),
        start=AsyncMock(),
        run=AsyncMock(
            side_effect=(
                ReportingError(
                    "report_visualization_evidence_path_forbidden",
                    "visualization 只能读取签发的最新已提交脚本。",
                    details={"terminalReason": "tool_no_progress"},
                ),
                RuntimeError("stop after visualization retry"),
            )
        ),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.analysis_concurrency = 1
    runtime.report_worker = SimpleNamespace(
        id="report-worker",
        model=SimpleNamespace(_report_vision_enabled=False),
    )
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=durable))
    runtime.task_runner = task_runner
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }
    runtime._envelope = lambda _run_context: SimpleNamespace(report_goal="经营分析")
    runtime._state = lambda _run_context: {"report_outline": {"title": "经营分析"}}
    runtime._worker_thinking_effort = lambda *, retry: "off"
    fact_metrics = [
        {
            "field": f"income_{metric_index:03}",
            "metricCodes": [f"income_total_{metric_index:03}"],
            "unit": "元",
            "periodRoles": ["current"],
            "periodStart": "2025-01-01",
            "periodEnd": "2025-12-31",
            "periodValues": [
                {"period": f"period-{period_index:04}", "value": float(period_index)}
                for period_index in range(1200)
            ],
        }
        for metric_index in range(12)
    ]
    full_fact_payload = {
        "version": "1",
        "analysisId": "analysis_001",
        "metrics": fact_metrics,
        "derivedMetrics": [],
        "comparisons": [],
        "reconciliations": [],
        "correlations": {},
        "warnings": [],
    }
    assert len(json.dumps(full_fact_payload, ensure_ascii=False).encode("utf-8")) > (
        runtime_analysis.MAX_REPORT_INSTRUCTION_BYTES
    )

    async def read_fact_model(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            analysis_id="analysis_001",
            model_dump=lambda **_options: full_fact_payload,
        )

    runtime._read_identity_model = read_fact_model

    async def restore_facts(
        **kwargs: Any,
    ) -> tuple[ReportingCheckpoint, dict[str, FileIdentity]]:
        return kwargs["checkpoint"], {"analysis_001": fact_file}

    async def run_analysis_item(*_args: Any, **_kwargs: Any) -> ReportingCheckpoint:
        return checkpoint_before_visualization

    async def current_checkpoint(*_args: Any, **_kwargs: Any) -> ReportingCheckpoint:
        return checkpoint_before_visualization

    async def persist_checkpoint(
        _run_context: Any, stored: ReportingCheckpoint
    ) -> ReportingCheckpoint:
        return stored

    runtime._restore_or_create_deterministic_analysis_facts = restore_facts
    runtime._run_analysis_item_task = run_analysis_item
    runtime._current_reporting_checkpoint = current_checkpoint
    runtime._persist_reporting_checkpoint = persist_checkpoint
    monkeypatch.setattr(runtime_analysis, "MAX_REPORT_SECTION_PHASE_ATTEMPTS", 2)

    with pytest.raises(RuntimeError, match="stop after visualization retry"):
        await runtime._run_analysis_phase(
            SimpleNamespace(run_id="run-1"),
            checkpoint=checkpoint_before_visualization,
            revision=1,
            sandbox_id="sandbox-1",
            validation_context_file=FileIdentity(
                path="validation/context.json", size=1, sha256="b" * 64
            ),
            detailed_plan=plan,
            dataset_handles=(),
            lineage=(),
            citation_bindings=tuple(
                Citation(
                    citationId=f"citation-{index:03}",
                    datasetId="dataset-income",
                    requirementId=f"requirement-{index:03}",
                    snapshotHash=f"{index:064x}",
                )
                for index in range(100)
            ),
            analysis_context_file=FileIdentity(
                path="analysis/context.json", size=1, sha256="a" * 64
            ),
            feedback=None,
            rework_request=None,
        )

    assert task_runner.start.await_count == 2
    instructions = [json.loads(call.args[1]) for call in task_runner.start.await_args_list]
    citation_ids = [f"citation-{index:03}" for index in range(100)]
    expected_mapping = {"analysis_001": citation_ids}
    assert [item["analysisCitationIds"] for item in instructions] == [
        expected_mapping,
        expected_mapping,
    ]
    expected_dataset_mapping = {citation_id: "dataset-income" for citation_id in citation_ids}
    assert [item["citationDatasetIds"] for item in instructions] == [
        expected_dataset_mapping,
        expected_dataset_mapping,
    ]
    assert [item["visualInspectionMode"] for item in instructions] == [
        "deterministic",
        "deterministic",
    ]
    assert any("上一轮因工具调用" in item for item in instructions[1]["completionConditions"])
    assert [item["visualizationWorkspace"]["allowedTerminalCommand"] for item in instructions] == [
        "python3 报表/智能分析/run-1/analysis/charts.py",
        "python3 报表/智能分析/run-1/analysis/charts.py",
    ]
    expected_fact_files = {
        "analysis_001": {"path": "facts/analysis_001.json", "size": 1, "sha256": "f" * 64}
    }
    assert [item["deterministicFactFiles"] for item in instructions] == [
        expected_fact_files,
        expected_fact_files,
    ]
    expected_visualization_facts = [
        {
            "analysisId": "analysis_001",
            "plan": {
                "analysisId": "analysis_001",
                "domain": "income",
                "step": "收入趋势",
                "primaryMetricFamily": "收入",
                "datasetIds": ["dataset-income"],
            },
            "summary": "收入同比增长。",
            "factFile": expected_fact_files["analysis_001"],
            "metrics": [
                {
                    "field": f"income_{metric_index:03}",
                    "metricCodes": [f"income_total_{metric_index:03}"],
                    "unit": "元",
                    "periodRoles": ["current"],
                    "periodStart": "2025-01-01",
                    "periodEnd": "2025-12-31",
                }
                for metric_index in range(12)
            ],
            "derivedMetrics": [],
            "comparisons": [],
            "fields": [f"income_{metric_index:03}" for metric_index in range(12)],
            "allowedMetricCodes": [f"income_total_{metric_index:03}" for metric_index in range(12)],
            "evidenceFiles": [{"path": "evidence/income.json", "size": 2, "sha256": "e" * 64}],
            "citationIds": ["citation-000"],
        }
    ]
    assert [item["visualizationFacts"] for item in instructions] == [
        expected_visualization_facts,
        expected_visualization_facts,
    ]
    assert all("facts" not in item["visualizationFacts"][0] for item in instructions)
    assert all(
        len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
        < runtime_analysis.MAX_REPORT_INSTRUCTION_BYTES
        for item in instructions
    )
    assert all("citationRegistry" not in item for item in instructions)
    assert all("snapshotHash" not in item for item in instructions)
    assert all(
        len(call.args[1].encode("utf-8")) < 512 * 1024 for call in task_runner.start.await_args_list
    )
    contracts = [call.kwargs["acceptance_contract"] for call in task_runner.start.await_args_list]
    phase_contracts = [item["requirements"][0]["parameters"]["phaseContract"] for item in contracts]
    assert [item["visualizationRecovery"] for item in phase_contracts] == [False, True]
    assert [item["visualInspectionMode"] for item in phase_contracts] == [
        "deterministic",
        "deterministic",
    ]


@pytest.mark.anyio
async def test_targeted_rework_schedules_only_requested_analysis_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = analysis_plan("analysis_001", "analysis_002", "analysis_003")
    fact_files = {
        analysis_id: FileIdentity(
            path=f"报表/智能分析/run-1/facts/revision-1/{analysis_id}.json",
            size=1,
            sha256=str(index) * 64,
        )
        for index, analysis_id in enumerate(
            ("analysis_001", "analysis_002", "analysis_003"), start=1
        )
    }
    stored = analysis_checkpoint(deterministic_fact_files=fact_files)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.analysis_concurrency = 2
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }
    runtime._restore_or_create_deterministic_analysis_facts = AsyncMock(
        return_value=(stored, fact_files)
    )
    runtime._apply_durable_command = AsyncMock()
    runtime._persist_reporting_checkpoint = AsyncMock(side_effect=lambda _context, value: value)
    scheduled = AsyncMock(side_effect=RuntimeError("stop after scheduling"))
    monkeypatch.setattr(runtime_analysis, "_run_pending_analysis_items", scheduled)

    with pytest.raises(RuntimeError, match="stop after scheduling"):
        await runtime._run_analysis_phase(
            SimpleNamespace(run_id="run-1"),
            checkpoint=stored,
            revision=1,
            sandbox_id="sandbox-1",
            validation_context_file=FileIdentity(
                path="validation/context.json", size=1, sha256="b" * 64
            ),
            detailed_plan=plan,
            dataset_handles=(),
            lineage=(),
            citation_bindings=(),
            analysis_context_file=FileIdentity(
                path="analysis/context.json", size=1, sha256="a" * 64
            ),
            feedback=None,
            rework_request=runtime_analysis.AnalysisReworkRequest(
                sectionCode="income",
                analysisIds=("analysis_002",),
                reason="补充证据",
                missingEvidence=("同比",),
            ),
        )

    assert scheduled.await_args.args[0] == ("analysis_002",)


def test_merge_reporting_checkpoints_keeps_out_of_order_section_results() -> None:
    base = checkpoint(
        completed=(completed("section_002", "b"),),
        pending=("section_001", "section_003"),
    )
    incoming = checkpoint(
        completed=(completed("section_001", "a"),),
        pending=("section_002", "section_003"),
    )

    merged = ReportWorkflowRuntime._merge_reporting_checkpoints(base, incoming)

    assert {item.section_code for item in merged.completed_sections} == {
        "section_001",
        "section_002",
    }
    assert merged.pending_sections == ("section_003",)


def test_merge_reporting_checkpoints_keeps_concurrent_analysis_traces_and_files() -> None:
    first_file = FileIdentity(path="analysis/analysis_001/evidence.json", size=1, sha256="a" * 64)
    second_file = FileIdentity(path="analysis/analysis_002/evidence.json", size=1, sha256="b" * 64)
    base = checkpoint(completed=(), pending=()).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
            "files": (first_file,),
            "trace": (
                ContextTrace(
                    phase="analysis",
                    taskId="task-analysis-001",
                    workKind="analysis_item",
                    analysisId="analysis_001",
                    status="completed",
                ),
            ),
        }
    )
    incoming = checkpoint(completed=(), pending=()).model_copy(
        update={
            "phase": "analysis",
            "report_brief": None,
            "evidence_manifest": None,
            "analysis_manifest_file": None,
            "files": (second_file,),
            "trace": (
                ContextTrace(
                    phase="analysis",
                    taskId="task-analysis-002",
                    workKind="analysis_item",
                    analysisId="analysis_002",
                    status="completed",
                ),
            ),
        }
    )

    merged = ReportWorkflowRuntime._merge_reporting_checkpoints(base, incoming)

    assert {item.path for item in merged.files} == {first_file.path, second_file.path}
    assert {item.analysis_id for item in merged.trace} == {"analysis_001", "analysis_002"}


def test_merge_reporting_checkpoints_preserves_deterministic_fact_mapping() -> None:
    fact_file = FileIdentity(
        path="报表/智能分析/run-1/facts/revision-1/analysis_001.json",
        size=1,
        sha256="a" * 64,
    )
    current = analysis_checkpoint(deterministic_fact_files={"analysis_001": fact_file})
    incoming = analysis_checkpoint()

    merged = ReportWorkflowRuntime._merge_reporting_checkpoints(current, incoming)

    assert merged.deterministic_fact_files == {"analysis_001": fact_file}


def test_merge_reporting_checkpoints_rejects_deterministic_fact_identity_conflict() -> None:
    path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    current = analysis_checkpoint(
        deterministic_fact_files={"analysis_001": FileIdentity(path=path, size=1, sha256="a" * 64)}
    )
    incoming = analysis_checkpoint(
        deterministic_fact_files={"analysis_001": FileIdentity(path=path, size=2, sha256="b" * 64)}
    )

    with pytest.raises(ReportingError) as raised:
        ReportWorkflowRuntime._merge_reporting_checkpoints(current, incoming)

    assert raised.value.code == "report_checkpoint_conflict"


def test_merge_reporting_checkpoints_rejects_mapped_fact_overwrite_from_files() -> None:
    path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    current = analysis_checkpoint(
        deterministic_fact_files={"analysis_001": FileIdentity(path=path, size=1, sha256="a" * 64)}
    )
    incoming = analysis_checkpoint(files=(FileIdentity(path=path, size=2, sha256="b" * 64),))

    with pytest.raises(ReportingError) as raised:
        ReportWorkflowRuntime._merge_reporting_checkpoints(current, incoming)

    assert raised.value.code == "report_checkpoint_conflict"


@pytest.mark.anyio
async def test_persist_reporting_checkpoint_serializes_concurrent_merges() -> None:
    base = checkpoint(completed=(), pending=("section_001", "section_002"))

    class StateRepository:
        def __init__(self) -> None:
            self.payload: dict[str, Any] = {
                "workflowCheckpoint": base.model_dump(mode="json", by_alias=True)
            }

        async def get(self, _report_run_id: str) -> Any:
            return SimpleNamespace(payload=copy.deepcopy(self.payload))

    repository = StateRepository()
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository = repository
    runtime._checkpoint_persist_lock = asyncio.Lock()
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }
    write_count = 0

    async def write_identity(_thread_id: str, _path: str, _serialized: bytes) -> FileIdentity:
        nonlocal write_count
        write_count += 1
        if write_count == 1:
            await asyncio.sleep(0.01)
        return FileIdentity(
            path=f"audit/checkpoint-{write_count}.json",
            size=1,
            sha256=str(write_count) * 64,
        )

    async def apply_command(_run_context: Any, command: Any) -> None:
        repository.payload["workflowCheckpoint"] = copy.deepcopy(command.payload["checkpoint"])

    runtime._write_immutable_artifact = write_identity
    runtime._apply_durable_command = apply_command
    run_context = SimpleNamespace(run_id="run-1")

    await asyncio.gather(
        runtime._persist_reporting_checkpoint(
            run_context,
            checkpoint(
                completed=(completed("section_001", "a"),),
                pending=("section_002",),
            ),
        ),
        runtime._persist_reporting_checkpoint(
            run_context,
            checkpoint(
                completed=(completed("section_002", "b"),),
                pending=("section_001",),
            ),
        ),
    )

    stored = ReportingCheckpoint.model_validate(repository.payload["workflowCheckpoint"])
    assert {item.section_code for item in stored.completed_sections} == {
        "section_001",
        "section_002",
    }
    assert stored.pending_sections == ()


@pytest.mark.anyio
async def test_batch_rework_commit_prevents_late_section_checkpoint_backflow() -> None:
    base = checkpoint(completed=(), pending=("section_001", "section_002"))
    rework_file = FileIdentity(path="sections/section_001.rework.json", size=1, sha256="a" * 64)
    section_file = FileIdentity(path="sections/section_002.json", size=1, sha256="b" * 64)
    rework_request = AnalysisReworkRequest(
        sectionCode="section_001",
        analysisIds=("analysis_001",),
        reason="当前冻结事实不足。",
        missingEvidence=("重算当前冻结期间。",),
    )
    rework_candidate = base.model_copy(
        update={
            "trace": (
                ContextTrace(
                    phase="section",
                    taskId="section-001",
                    workKind="section",
                    sectionCode="section_001",
                    status="rework",
                    artifactFile=rework_file,
                ),
            ),
            "files": (*base.files, rework_file),
        }
    )
    late_completion = base.model_copy(
        update={
            "completed_sections": (
                CompletedSection(
                    sectionCode="section_002",
                    workItemHash="c" * 64,
                    artifactFile=section_file,
                ),
            ),
            "pending_sections": ("section_001",),
            "trace": (
                ContextTrace(
                    phase="section",
                    taskId="section-002",
                    workKind="section",
                    sectionCode="section_002",
                    status="completed",
                    artifactFile=section_file,
                ),
            ),
            "files": (*base.files, section_file),
        }
    )

    class StateRepository:
        def __init__(self) -> None:
            self.payload = {"workflowCheckpoint": base.model_dump(mode="json", by_alias=True)}

        async def get(self, _report_run_id: str) -> Any:
            return SimpleNamespace(payload=copy.deepcopy(self.payload))

    repository = StateRepository()
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository = repository
    runtime._checkpoint_persist_lock = asyncio.Lock()
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }
    runtime._state = lambda _run_context: {
        "report_outline": {
            "reportType": "comprehensive",
            "title": "经营分析",
            "sections": [
                {
                    "code": "section_001",
                    "sectionNumber": "1",
                    "title": "收入分析",
                    "analysisIds": ["analysis_001"],
                },
                {
                    "code": "section_002",
                    "sectionNumber": "2",
                    "title": "收入补充",
                    "analysisIds": ["analysis_001"],
                },
            ],
        }
    }
    commands: list[str] = []

    async def write_identity(_thread_id: str, path: str, serialized: bytes) -> FileIdentity:
        return FileIdentity(
            path=path,
            size=len(serialized),
            sha256=hashlib.sha256(serialized).hexdigest(),
        )

    async def apply_command(_run_context: Any, command: Any) -> None:
        commands.append(command.name)
        if command.name == "request_analysis_rework":
            stored = repository.payload["workflowCheckpoint"]
            repository.payload["workflowCheckpoint"] = {
                **stored,
                "phase": "analysis",
                "reportBrief": None,
                "evidenceManifest": None,
                "analysisManifestFile": None,
            }
        elif command.name == "set_workflow_checkpoint":
            repository.payload["workflowCheckpoint"] = copy.deepcopy(command.payload["checkpoint"])

    runtime._write_immutable_artifact = write_identity
    runtime._apply_durable_command = apply_command
    run_context = SimpleNamespace(run_id="run-1")

    await runtime._persist_reporting_checkpoint(run_context, rework_candidate)
    await runtime._persist_reporting_checkpoint(run_context, late_completion)
    checkpoint_before_commit = ReportingCheckpoint.model_validate(
        repository.payload["workflowCheckpoint"]
    )
    assert checkpoint_before_commit.phase == "sections"
    assert {item.section_code for item in checkpoint_before_commit.completed_sections} == {
        "section_002"
    }

    committed, aggregated = await runtime._commit_section_rework_batch(
        run_context,
        checkpoint=checkpoint_before_commit,
        revision=1,
        rework_results=((rework_candidate, rework_request),),
    )

    durable = ReportingCheckpoint.model_validate(repository.payload["workflowCheckpoint"])
    assert aggregated == rework_request
    assert committed == durable
    assert durable.phase == "analysis"
    assert durable.report_brief is None
    assert durable.evidence_manifest is None
    assert durable.analysis_manifest_file is None
    assert durable.completed_sections == ()
    assert durable.pending_sections == ("section_001", "section_002")
    assert commands[-2:] == ["request_analysis_rework", "set_workflow_checkpoint"]


@pytest.mark.anyio
async def test_durable_completed_section_reuses_bound_artifact() -> None:
    identity = FileIdentity(path="sections/section_001.json", size=1, sha256="a" * 64)
    artifact = SectionArtifact(
        sectionCode="section_001",
        blocks=(
            ReportDraftBlock(
                blockId="summary",
                markdown="### 经营结论\n\n收入保持增长。",
                citationIds=("citation_001",),
                claimIds=("claim_001",),
            ),
        ),
        claims=(
            SectionClaim(
                claimId="claim_001",
                metricCode="revenue",
                value=1,
                periodBasis="2026-01",
                managementQuestion="问题",
                currentPeriod="2026-01",
                citationIds=("citation_001",),
            ),
        ),
    )
    durable = SimpleNamespace(
        payload={
            "sectionArtifacts": {
                "section_001": {
                    "sectionCode": "section_001",
                    "analysisIds": ["analysis_001"],
                    "workItemHash": "b" * 64,
                    "revision": 1,
                    "artifactFile": identity.model_dump(mode="json", by_alias=True),
                }
            }
        }
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository = SimpleNamespace(
        get_by_external_run_id=lambda _external_run_id: asyncio.sleep(0, result=durable)
    )
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }

    async def read_identity_model(
        _thread_id: str, actual_identity: FileIdentity, _model: Any
    ) -> Any:
        assert actual_identity == identity
        return artifact

    runtime._read_identity_model = read_identity_model

    restored = await runtime._durable_completed_section(
        SimpleNamespace(),
        revision=1,
        section_code="section_001",
        analysis_ids=("analysis_001",),
        work_item_hash="b" * 64,
    )

    assert restored is not None
    completed_section, restored_artifact = restored
    assert completed_section.artifact_file == identity
    assert completed_section.work_item_hash == "b" * 64
    assert restored_artifact is artifact


@pytest.mark.anyio
async def test_durable_completed_section_rejects_legacy_protocol_injection() -> None:
    identity = FileIdentity(path="sections/section_003.json", size=1, sha256="c" * 64)
    artifact = SectionArtifact(
        sectionCode="section_003",
        blocks=(
            ReportDraftBlock(
                blockId="workload_trend",
                markdown="![工作量趋势](workload_monthly_trend)",
                citationIds=("citation_011",),
                chartIds=("workload_monthly_trend",),
                claimIds=("claim_003",),
            ),
        ),
        claims=(
            SectionClaim(
                claimId="claim_003",
                metricCode="workload",
                value=1,
                periodBasis="2026-01",
                managementQuestion="问题",
                currentPeriod="2026-01",
                citationIds=("citation_011",),
                chartIds=("workload_monthly_trend",),
            ),
        ),
    )
    durable = SimpleNamespace(
        payload={
            "sectionArtifacts": {
                "section_003": {
                    "analysisIds": ["analysis_003"],
                    "workItemHash": "d" * 64,
                    "revision": 1,
                    "artifactFile": identity.model_dump(mode="json", by_alias=True),
                }
            }
        }
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.state_repository = SimpleNamespace(
        get_by_external_run_id=lambda _external_run_id: asyncio.sleep(0, result=durable)
    )
    runtime._scope = lambda _run_context: {
        "externalRunId": "run-1",
        "threadId": "thread-1",
        "userId": "user-1",
    }
    runtime._read_identity_model = AsyncMock(return_value=artifact)

    with pytest.raises(ReportingError) as raised:
        await runtime._durable_completed_section(
            SimpleNamespace(),
            revision=1,
            section_code="section_003",
            analysis_ids=("analysis_003",),
            work_item_hash="d" * 64,
        )

    assert raised.value.code == "report_draft_protocol_injection"


def checkpoint(
    *, completed: tuple[CompletedSection, ...], pending: tuple[str, ...]
) -> ReportingCheckpoint:
    profile = ProfileCoverageManifest(
        authorizedDatasetCount=1,
        coveredDatasetCount=1,
        datasets=(
            ProfileCoverageDataset(
                datasetId="dataset-1",
                datasetPath="datasets/a.csv",
                datasetSize=1,
                datasetSnapshotHash="a" * 64,
                profileFile=FileIdentity(path="profiles/a.json", size=1, sha256="b" * 64),
                rowCount=1,
                fieldCount=1,
                fields=("amount",),
            ),
        ),
    )
    return ReportingCheckpoint(
        revision=1,
        phase="sections",
        outlineHash="c" * 64,
        profileCoverage=profile,
        reportBrief=ReportBrief(
            objective="目标",
            executiveSummary="摘要",
            managementQuestions=("问题",),
        ),
        evidenceManifest=AnalysisEvidenceManifest(
            evidence=(
                AnalysisEvidence(
                    analysisId="analysis_001",
                    summary="摘要",
                    datasetIds=("dataset-1",),
                    evidenceFiles=(
                        FileIdentity(path="analysis/evidence.json", size=1, sha256="e" * 64),
                    ),
                    citationIds=("citation_001",),
                ),
            ),
            datasetSemantics=(
                AnalysisDatasetSemantics(
                    datasetId="dataset-1",
                    rowGrain="record",
                    duplicateResolution="not_applicable",
                ),
            ),
        ),
        analysisManifestFile=FileIdentity(path="analysis/final.json", size=1, sha256="d" * 64),
        completedSections=completed,
        pendingSections=pending,
    )


def analysis_checkpoint(
    *,
    deterministic_fact_files: dict[str, FileIdentity] | None = None,
    files: tuple[FileIdentity, ...] = (),
    trace: tuple[ContextTrace, ...] = (),
) -> ReportingCheckpoint:
    payload = checkpoint(completed=(), pending=()).model_dump(mode="json", by_alias=True)
    payload.update(
        {
            "phase": "analysis",
            "reportBrief": None,
            "evidenceManifest": None,
            "analysisManifestFile": None,
            "files": [item.model_dump(mode="json", by_alias=True) for item in files],
            "trace": [item.model_dump(mode="json", by_alias=True) for item in trace],
        }
    )
    if deterministic_fact_files is not None:
        payload["deterministicFactFiles"] = {
            analysis_id: identity.model_dump(mode="json", by_alias=True)
            for analysis_id, identity in deterministic_fact_files.items()
        }
    return ReportingCheckpoint.model_validate(payload)


def analysis_plan(*analysis_ids: str) -> DetailedAnalysisPlan:
    return DetailedAnalysisPlan(
        datasetIds=("dataset-1",),
        analyses=tuple(
            DetailedAnalysisItem(
                analysisId=analysis_id,
                domain="income",
                managementQuestion=f"{analysis_id} 管理问题",
                primaryMetricFamily="收入",
                datasetIds=("dataset-1",),
                fields=(),
                metrics=(),
                periods=(),
                actions=("趋势",),
                evidenceSummary="固定事实",
                suggestedSection="收入",
                completionConditions=("完成",),
            )
            for analysis_id in analysis_ids
        ),
    )


def section_work_item(section_code: str) -> SectionWorkItem:
    evidence_file = FileIdentity(path="analysis/evidence.json", size=1, sha256="e" * 64)
    return SectionWorkItem(
        sectionCode=section_code,
        sectionNumber="1",
        title="收入分析",
        objective="说明收入表现。",
        reportBrief={
            "objective": "经营分析",
            "executiveSummary": "收入表现摘要。",
            "managementQuestions": ["问题"],
        },
        completionConditions=("说明收入表现",),
        analysisIds=("analysis_001",),
        evidence=(
            AnalysisEvidence(
                analysisId="analysis_001",
                summary="当前冻结事实。",
                datasetIds=("dataset-1",),
                evidenceFiles=(evidence_file,),
                citationIds=("citation_001",),
            ),
        ),
        citations=(
            {
                "citationId": "citation_001",
                "datasetId": "dataset-1",
                "requirementId": "requirement-1",
                "snapshotHash": "f" * 64,
            },
        ),
        factFiles=(evidence_file,),
        factSummaries=("当前冻结事实。",),
        markdownRequirements=("只使用冻结事实",),
    )


def test_build_section_work_item_projects_selected_metrics_and_chart_semantics() -> None:
    runtime = object.__new__(ReportWorkflowRuntime)
    evidence_file = FileIdentity(path="analysis/evidence.json", size=1, sha256="e" * 64)
    evidence = AnalysisEvidence(
        analysisId="analysis_001",
        summary="当前冻结事实。",
        datasetIds=("dataset-1",),
        evidenceFiles=(evidence_file,),
        citationIds=("citation_001",),
        chartIds=("revenue_trend",),
    )
    chart = AnalysisChart(
        chartId="revenue_trend",
        sourceFile={"path": "analysis/charts/revenue.png", "size": 1, "sha256": "a" * 64},
        title="收入趋势",
        altText="收入趋势图",
        citationIds=("citation_001",),
        metricCodes=("revenue",),
        currentPeriod="2026-01",
        comparisonPeriod="2025-01",
        comparisonType="yoy",
        sourceDatasetId="dataset-1",
        aggregationGrain="month",
        visualInspectionReceipt=ChartVisualInspectionReceipt(
            sourcePath="analysis/charts/revenue.png",
            sha256="a" * 64,
            inspectionMode="deterministic",
            visualReviewStatus="not_run",
            inspectorId="deterministic-raster-inspector-v1",
            reviewed=True,
            requiresRevision=False,
        ),
    )
    analysis_artifact = SimpleNamespace(
        report_brief=ReportBrief(
            objective="经营分析",
            executiveSummary="收入表现摘要。",
            managementQuestions=("收入表现如何？",),
        ),
        evidence_manifest=SimpleNamespace(
            evidence=(evidence,),
            metric_definitions=(
                MetricDefinition(
                    code="revenue",
                    name="收入",
                    definition="收入金额",
                    unit="元",
                    periodBasis="2026-01",
                ),
                MetricDefinition(
                    code="margin",
                    name="毛利率",
                    definition="毛利率",
                    unit="%",
                    periodBasis="2026-01",
                ),
            ),
            charts=(chart,),
        ),
        profile_read_receipts=(),
    )
    section = SimpleNamespace(
        code="section_001",
        section_number="1",
        title="收入分析",
        analysis_ids=("analysis_001",),
        focus=("收入表现如何？",),
    )
    citation = Citation(
        citationId="citation_001",
        datasetId="dataset-1",
        requirementId="requirement-1",
        snapshotHash="f" * 64,
    )

    work_item = runtime._build_section_work_item(
        section,
        detailed_plan=DetailedAnalysisPlan(
            datasetIds=("dataset-1",),
            analyses=(
                DetailedAnalysisItem(
                    analysisId="analysis_001",
                    domain="income",
                    managementQuestion="收入表现如何？",
                    primaryMetricFamily="收入",
                    datasetIds=("dataset-1",),
                    fields=("month", "revenue"),
                    metrics=("revenue",),
                    periods=("2026-01",),
                    actions=("趋势",),
                    evidenceSummary="固定事实",
                    suggestedSection="收入分析",
                    completionConditions=("完成",),
                ),
            ),
        ),
        analysis_artifact=analysis_artifact,
        citation_bindings=(citation,),
    )

    assert tuple(item.code for item in work_item.metric_definitions) == ("revenue",)
    assert len(work_item.markdown_requirements) <= 50
    chart_rule = next(item for item in work_item.markdown_requirements if "revenue_trend" in item)
    assert "currentPeriod=2026-01" in chart_rule
    assert "comparisonPeriod=2025-01" in chart_rule
    assert "comparisonType=yoy" in chart_rule
    assert "citationIds 至少包含 ['citation_001']" in chart_rule


def completed(section_code: str, digest: str) -> CompletedSection:
    return CompletedSection(
        sectionCode=section_code,
        workItemHash=digest * 64,
        artifactFile=FileIdentity(path=f"sections/{section_code}.json", size=1, sha256=digest * 64),
    )
