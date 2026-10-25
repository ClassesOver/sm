"""动态发现图谱与章节提纲的 checkpoint 身份契约。"""

import pytest

from smart_reporting.reporting.workflow.checkpoint import (
    FileIdentity,
    ProfileCoverageDataset,
    ProfileCoverageManifest,
    ReportingCheckpoint,
)


def _coverage() -> ProfileCoverageManifest:
    dataset = ProfileCoverageDataset(
        datasetId="dataset-url-abc0001",
        datasetPath="报表/数据集/run1/dataset-url-abc0001.csv",
        datasetSize=100,
        datasetSnapshotHash="b" * 64,
        profileFile=FileIdentity(path="profiles/x.json", size=1, sha256="c" * 64),
        rowCount=4,
        fieldCount=1,
        fields=("amount",),
    )
    return ProfileCoverageManifest(
        authorizedDatasetCount=1,
        coveredDatasetCount=1,
        datasets=(dataset,),
    )


def test_checkpoint_preserves_finding_graph_and_narrative_identity():
    graph_file = FileIdentity(path="facts/finding-graph.json", size=10, sha256="d" * 64)
    outline_file = FileIdentity(path="outline/narrative.json", size=11, sha256="e" * 64)
    checkpoint = ReportingCheckpoint(
        revision=1,
        phase="analysis",
        outlineHash="a" * 64,
        profileCoverage=_coverage(),
        findingGraphFile=graph_file,
        findingGraphHash="f" * 64,
        narrativeOutlineFile=outline_file,
        narrativeOutlineHash="1" * 64,
    )

    assert checkpoint.finding_graph_file == graph_file
    assert checkpoint.finding_graph_hash == "f" * 64
    assert checkpoint.narrative_outline_file == outline_file
    assert checkpoint.narrative_outline_hash == "1" * 64


def test_checkpoint_rejects_invalid_finding_graph_hash():
    try:
        ReportingCheckpoint(
            revision=1,
            phase="analysis",
            outlineHash="a" * 64,
            profileCoverage=_coverage(),
            findingGraphHash="not-a-sha256",
        )
    except ValueError as error:
        assert "findingGraphHash" in str(error)
    else:
        raise AssertionError("invalid finding graph hash was accepted")


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_restore_rejects_graph_from_another_fact_snapshot(anyio_backend):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.hospital_operation.finding_projection import build_finding_graph
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    graph = build_finding_graph(
        [{"analysisId": "analysis_001"}], None, (), snapshot_hash="f" * 64,
        citation_ids_by_analysis={"analysis_001": ("citation_001",)},
    )
    checkpoint = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64,
        profileCoverage=_coverage(),
        findingGraphFile=FileIdentity(path="findings/graph.json", size=10, sha256="d" * 64),
        findingGraphHash=graph.snapshot_hash,
    )
    runtime = SimpleNamespace(_read_identity_model=AsyncMock(return_value=graph),
                              _profile=lambda _: SimpleNamespace(metrics=()), _state=lambda _: {})
    with pytest.raises(ReportingError, match="快照"):
        await RuntimeAnalysisMixin._restore_or_create_finding_graph(
            runtime, run_context=None, checkpoint=checkpoint, thread_id="thread-1",
            report_run_id="run-1", revision=1,
            fact_files={"analysis_001": FileIdentity(path="facts/001.json", size=10, sha256="e" * 64)},
        )


def test_checkpoint_accepts_first_frozen_narrative_outline():
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    current = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64,
        profileCoverage=_coverage(),
        pendingSections=("section_001", "section_002"),
    )
    incoming = ReportingCheckpoint.model_validate({
        **current.model_dump(mode="json", by_alias=True),
        "outlineHash": "b" * 64,
        "narrativeOutlineFile": {"path": "narrative/outline.json", "size": 10, "sha256": "c" * 64},
        "narrativeOutlineHash": "c" * 64,
        "pendingSections": ["section_001"],
    })
    merged = RuntimeAnalysisMixin._merge_reporting_checkpoints(current, incoming)
    assert merged.outline_hash == "b" * 64
    assert merged.narrative_outline_file.path == "narrative/outline.json"
    assert merged.pending_sections == ("section_001",)


def test_checkpoint_rejects_outline_change_after_narrative_freeze():
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    current = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64,
        profileCoverage=_coverage(),
        narrativeOutlineFile=FileIdentity(path="narrative/outline.json", size=10, sha256="c" * 64),
        narrativeOutlineHash="c" * 64,
    )
    incoming = current.model_copy(update={"outline_hash": "b" * 64})
    with pytest.raises(ReportingError):
        RuntimeAnalysisMixin._merge_reporting_checkpoints(current, incoming)


def test_stale_started_trace_does_not_overwrite_a_recorded_result():
    from smart_reporting.reporting.workflow.checkpoint import ContextTrace
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    def trace(task_id, analysis_id, status):
        return ContextTrace(phase="analysis", taskId=task_id, workKind="analysis_item",
                            analysisId=analysis_id, attempt=0, status=status)

    # 并发补证：analysis_002 携带启动时看到的 analysis_001 started 副本写回，
    # 不能把 analysis_001 已写回的完成结果改回 started。
    base = dict(revision=1, phase="analysis", outlineHash="a" * 64, profileCoverage=_coverage())
    current = ReportingCheckpoint(**base, trace=(
        trace("task-1", "analysis_001", "completed"), trace("task-2", "analysis_002", "started"),
    ))
    incoming = ReportingCheckpoint(**base, trace=(
        trace("task-1", "analysis_001", "started"), trace("task-2", "analysis_002", "completed"),
    ))
    merged = RuntimeAnalysisMixin._merge_reporting_checkpoints(current, incoming)
    assert {item.task_id: item.status for item in merged.trace} == {
        "task-1": "completed", "task-2": "completed",
    }
    # 结果之间仍以后写回者为准（如 failed 之后同一 Task 恢复完成）。
    failed = ReportingCheckpoint(**base, trace=(trace("task-1", "analysis_001", "failed"),))
    recovered = ReportingCheckpoint(**base, trace=(trace("task-1", "analysis_001", "completed"),))
    assert RuntimeAnalysisMixin._merge_reporting_checkpoints(failed, recovered).trace[0].status == "completed"


@pytest.mark.parametrize("changed", [None, "work_item_hash", "artifact_file"])
@pytest.mark.parametrize("retry_counts", [(2, 0), (0, 2)])
def test_completed_section_restore_preserves_retry_history_and_checks_identity(changed, retry_counts):
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.checkpoint import CompletedSection
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    section = CompletedSection(
        sectionCode="section_001", workItemHash="b" * 64,
        artifactFile=FileIdentity(path="section.json", size=10, sha256="c" * 64),
        retryCount=retry_counts[0],
    )
    current = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64,
        profileCoverage=_coverage(), completedSections=(section,),
    )
    updates = {"retry_count": retry_counts[1]}
    if changed == "work_item_hash":
        updates[changed] = "d" * 64
    elif changed == "artifact_file":
        updates[changed] = section.artifact_file.model_copy(update={"sha256": "d" * 64})
    incoming = current.model_copy(update={"completed_sections": (section.model_copy(update=updates),)})

    if changed is not None:
        with pytest.raises(ReportingError, match="其他完成产物"):
            RuntimeAnalysisMixin._merge_reporting_checkpoints(current, incoming)
    else:
        merged = RuntimeAnalysisMixin._merge_reporting_checkpoints(current, incoming)
        assert merged.completed_sections[0].retry_count == 2
        assert merged.completed_sections[0].artifact_file == section.artifact_file


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("source_count", [1, 2])
@pytest.mark.parametrize("purpose_scope", [False, True])
async def test_finding_graph_freezes_supplement_identity_and_registered_citations(anyio_backend, source_count, purpose_scope):
    import hashlib
    import json
    from types import SimpleNamespace

    from smart_reporting.reporting.delivery.artifacts_v1 import Citation
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.hospital_operation.findings import FindingGraph
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    fact_file = FileIdentity(path="facts/001.json", size=10, sha256="a" * 64)
    supplement_file = FileIdentity(path="evidence/001.json", size=10, sha256="b" * 64)
    item = {
        "analysisId": "analysis_001", "datasetIds": ["dataset-url-abc0001"],
        "citationIds": ["citation_007"],
        "evidenceFiles": [fact_file.model_dump(by_alias=True), supplement_file.model_dump(by_alias=True)],
    }
    if source_count == 2:
        item["evidenceFiles"].append({"path": "evidence/002.json", "size": 10, "sha256": "f" * 64})
    binding = Citation(citationId="citation_007", datasetId="dataset-url-abc0001",
                       requirementId="requirement_001", snapshotHash="c" * 64)
    saved = {}

    async def read(thread_id, identity, model):
        if model is FindingGraph:
            return saved["graph"]
        return DeterministicAnalysisBundle(analysisId="analysis_001")

    async def read_bytes(thread_id, identity):
        findings = [{"name": "院区差额", "metricCodes": ["income"], "columns": ["院区", "差额"], "rows": [["东", 10]]}]
        if purpose_scope:
            findings.insert(0, {"name": "其他用途", "metricCodes": ["budget"], "value": 999})
        return json.dumps({
            "findings": findings,
            "reconciliations": [{"name": "总额", "passed": True}], "warnings": [],
        }).encode()

    async def write(thread_id, path, content):
        saved["graph"] = FindingGraph.model_validate_json(content)
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    async def persist(context, checkpoint):
        return checkpoint

    runtime = SimpleNamespace(
        _read_identity_model=read, _read_identity_bytes=read_bytes, _write_immutable_artifact=write,
        _profile=lambda context: SimpleNamespace(metrics=()), _persist_reporting_checkpoint=persist,
        _state=lambda context: {},
        _update_reporting_checkpoint=RuntimeAnalysisMixin._update_reporting_checkpoint,
        _merge_checkpoint_files=RuntimeAnalysisMixin._merge_checkpoint_files,
    )
    if purpose_scope:
        from smart_reporting.reporting.hospital_operation.detailed_analysis import (
            DetailedAnalysisPlan,
        )
        from smart_reporting.reporting.profile.models import EffectiveMetric
        from smart_reporting.reporting.tests.test_deterministic_analysis import analysis
        from smart_reporting.reporting.workflow.runtime.base import (
            REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
        )

        metrics = tuple(EffectiveMetric(
            code=code, kind="currency", description="同名金额", aggregation="sum",
            fieldRef=f"source.db.table.{code}", purpose=purpose,
        ) for code, purpose in (("income", "收入多维分析"), ("budget", "预算或预实对比")))
        # Even stale allowedMetricCodes cannot overrule the current frozen purpose.
        plan = DetailedAnalysisPlan(analyses=(analysis().model_copy(update={
            "dataset_ids": (binding.dataset_id,), "metric_purposes": ("收入多维分析",),
            "allowed_metric_codes": ("income", "budget"),
        }),), datasetIds=(binding.dataset_id,))
        runtime._profile = lambda _: SimpleNamespace(metrics=metrics)
        runtime._state = lambda _: {REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: plan.model_dump(by_alias=True)}
    checkpoint = ReportingCheckpoint(revision=1, phase="analysis", outlineHash="d" * 64, profileCoverage=_coverage())
    kwargs = dict(
        run_context=None, thread_id="thread-1", report_run_id="run-1", revision=1,
        fact_files={"analysis_001": fact_file}, analysis_items={"analysis_001": item},
        citation_bindings=(binding,),
    )
    frozen = await RuntimeAnalysisMixin._restore_or_create_finding_graph(runtime, checkpoint=checkpoint, **kwargs)
    assert saved["graph"].findings[0].source_refs[0].path == supplement_file.path
    assert saved["graph"].findings[0].citation_ids == (binding.citation_id,)
    assert {ref.path for card in saved["graph"].findings for ref in card.source_refs if ref.path != fact_file.path} == {
        value["path"] for value in item["evidenceFiles"][1:]
    }
    if purpose_scope:
        assert saved["graph"].findings[0].source_refs[0].pointer == "/findings/1"
        assert all("budget" not in card.metric_codes for card in saved["graph"].findings)
        assert any("未用于正文" in issue for card in saved["graph"].findings for issue in card.limitations)
    item["evidenceFiles"][1]["sha256"] = "e" * 64
    with pytest.raises(ReportingError, match="快照"):
        await RuntimeAnalysisMixin._restore_or_create_finding_graph(runtime, checkpoint=frozen, **kwargs)
