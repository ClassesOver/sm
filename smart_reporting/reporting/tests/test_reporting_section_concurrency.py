from __future__ import annotations

import asyncio
import copy
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
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisEvidence,
    AnalysisEvidenceManifest,
    CompletedSection,
    ContextTrace,
    FileIdentity,
    MetricDefinition,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
    ReportBrief,
    ReportingCheckpoint,
    SectionArtifact,
)
from smart_reporting.reporting.workflow.runtime import (
    REPORT_WORKFLOW_RESULT_STATE_KEY,
    ReportWorkflowRuntime,
)
from smart_reporting.reporting.workflow.runtime import analysis as runtime_analysis
from smart_reporting.reporting.workflow.runtime.analysis import _run_pending_analysis_items
from smart_reporting.reporting.workflow.runtime.sections import _run_bounded


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
            "analysisItems": {},
            "charts": [],
        }
    )
    task_runner = SimpleNamespace(
        repository=SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None)),
        start=AsyncMock(),
        run=AsyncMock(
            side_effect=(
                ReportingError(
                    "report_visualization_tool_budget_exhausted",
                    "当前可视化 Task 已达到工具调用上限。",
                ),
                RuntimeError("stop after visualization retry"),
            )
        ),
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.analysis_concurrency = 1
    runtime.report_worker = SimpleNamespace(id="report-worker")
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

    async def prepare_facts(**_kwargs: Any) -> dict[str, FileIdentity]:
        return {"analysis_001": fact_file}

    async def run_analysis_item(*_args: Any, **_kwargs: Any) -> ReportingCheckpoint:
        return checkpoint_before_visualization

    async def current_checkpoint(*_args: Any, **_kwargs: Any) -> ReportingCheckpoint:
        return checkpoint_before_visualization

    async def persist_checkpoint(
        _run_context: Any, stored: ReportingCheckpoint
    ) -> ReportingCheckpoint:
        return stored

    runtime._prepare_deterministic_analysis_facts = prepare_facts
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
            citation_bindings=(
                Citation(
                    citationId="citation-income",
                    datasetId="dataset-income",
                    requirementId="requirement-income",
                    snapshotHash="c" * 64,
                ),
            ),
            analysis_context_file=FileIdentity(
                path="analysis/context.json", size=1, sha256="a" * 64
            ),
            feedback=None,
            rework_request=None,
        )

    assert task_runner.start.await_count == 2
    instructions = [json.loads(call.args[1]) for call in task_runner.start.await_args_list]
    expected_mapping = {"analysis_001": ["citation-income"]}
    assert [item["analysisCitationIds"] for item in instructions] == [
        expected_mapping,
        expected_mapping,
    ]
    assert [item["visualizationWorkspace"]["allowedTerminalCommand"] for item in instructions] == [
        "python3 报表/智能分析/run-1/analysis/charts.py",
        "python3 报表/智能分析/run-1/analysis/charts.py",
    ]
    assert all("citationRegistry" not in item for item in instructions)
    assert all("snapshotHash" not in item for item in instructions)
    contracts = [call.kwargs["acceptance_contract"] for call in task_runner.start.await_args_list]
    phase_contracts = [item["requirements"][0]["parameters"]["phaseContract"] for item in contracts]
    assert [item["visualizationRecovery"] for item in phase_contracts] == [False, True]


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
async def test_durable_completed_section_reuses_bound_artifact() -> None:
    identity = FileIdentity(path="sections/section_001.json", size=1, sha256="a" * 64)
    artifact = SectionArtifact(
        sectionCode="section_001",
        blocks=(
            ReportDraftBlock(
                blockId="summary",
                markdown="### 经营结论\n\n收入保持增长。",
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
            )
        ),
        analysisManifestFile=FileIdentity(path="analysis/final.json", size=1, sha256="d" * 64),
        completedSections=completed,
        pendingSections=pending,
    )


def completed(section_code: str, digest: str) -> CompletedSection:
    return CompletedSection(
        sectionCode=section_code,
        workItemHash=digest * 64,
        artifactFile=FileIdentity(path=f"sections/{section_code}.json", size=1, sha256=digest * 64),
    )
