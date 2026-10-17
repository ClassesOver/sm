"""大附录与多章节报告必须走得完真实的 checkpoint 写入/合并/恢复链路。"""

import asyncio
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.delivery.artifacts_v1 import Citation
from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
from smart_reporting.reporting.hospital_operation.narrative_outline import (
    NarrativeOutlineCandidate,
    freeze_narrative_outline,
)
from smart_reporting.reporting.hospital_operation.narrative_planner import (
    build_compatible_report_outline,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.narrative_helpers import finding, graph
from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
from smart_reporting.reporting.workflow.checkpoint import (
    AnalysisArtifact,
    CheckpointError,
    ContextTrace,
    FileIdentity,
    ReportingCheckpoint,
    SectionArtifact,
    SectionWorkItem,
)
from smart_reporting.reporting.workflow.runtime import sections as section_runtime
from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin
from smart_reporting.reporting.workflow.runtime.base import (
    MAX_SECTION_WORK_ITEM_BYTES,
    REPORT_DATASET_LINEAGE_STATE_KEY,
    REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY,
    REPORT_OUTLINE_HASH_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    payload_sha256,
)
from smart_reporting.reporting.workflow.runtime.sections import (
    RuntimeSectionsMixin,
    _json_text,
    _section_model_work_item_payload,
)
from smart_reporting.reporting.workflow.state import (
    ReportingPhase,
    ReportingRunState,
    apply,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _identity(path, content=b"{}"):
    return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())


def _appendix_inputs(count=568, *, summary="收入发生变化", analysis_count=12, files_per_analysis=1):
    source = graph(finding(), *(
        finding(i, analysisIds=[f"analysis_{(i - 2) % analysis_count + 1:03d}"],
                priority="low", evidenceLevel="statistical_relation", summary=summary)
        for i in range(2, count + 2)
    ))
    plan = DetailedAnalysisPlan.model_validate({
        "datasetIds": ["dataset_001"],
        "analyses": [{
            "analysisId": f"analysis_{i:03d}", "domain": "income",
            "managementQuestion": "解释经营变化", "primaryMetricFamily": "income",
            "datasetIds": ["dataset_001"], "fields": ["amount"],
            "metrics": ["income"], "periods": [], "actions": ["sum"],
            "evidenceSummary": "总额与趋势", "suggestedSection": "收入分析",
            "completionConditions": ["冻结事实"],
        } for i in range(1, analysis_count + 1)],
    })
    outline = freeze_narrative_outline(
        NarrativeOutlineCandidate(
            title="运营分析", snapshotHash=source.snapshot_hash,
            sections=[{"title": "经营变化", "findingIds": [source.findings[0].finding_id],
                       "objective": "解释变化", "groupingReason": "经营主题"}],
            appendixFindingIds=[card.finding_id for card in source.findings[1:]],
        ),
        graph=source, analyses=[{"analysisId": item.analysis_id} for item in plan.analyses],
    )
    artifact = AnalysisArtifact.model_validate({
        "reportBrief": {"objective": "经营分析", "executiveSummary": "收入变化",
                        "managementQuestions": ["经营变化"]},
        "evidenceManifest": {
            "evidence": [{
                "analysisId": item.analysis_id, "datasetIds": ["dataset_001"],
                "summary": "冻结分析摘要" * 1000, "citationIds": ["citation_001"],
                "evidenceFiles": [_identity(f"facts/{item.analysis_id}-{n}.json")
                                  for n in range(files_per_analysis)],
                "warnings": ["统计关系不能解释为因果"],
            } for item in plan.analyses],
            "metricDefinitions": [{"code": "income", "name": "收入", "definition": "收入合计",
                                   "unit": "元", "periodBasis": "2025年"}],
            "datasetSemantics": [{"datasetId": "dataset_001", "rowGrain": "month",
                                  "duplicateResolution": "not_applicable"}],
        },
    })
    citations = (Citation(citationId="citation_001", datasetId="dataset_001",
                          requirementId="requirement_001", snapshotHash="a" * 64),)
    return source, plan, outline, artifact, citations


def _work_item(runtime, section, inputs):
    source, plan, _, artifact, citations = inputs
    return runtime._build_narrative_section_work_item(
        section, graph=source, detailed_plan=plan,
        analysis_artifact=artifact, citation_bindings=citations,
    )


def _fit(runtime, inputs):
    source, plan, outline, artifact, citations = inputs
    return runtime._fit_narrative_outline_context(
        outline, graph=source, detailed_plan=plan,
        analysis_artifact=artifact, citation_bindings=citations,
    )


@pytest.mark.parametrize("summary", ["收入发生变化", "收入变化与统计限制。" * 350], ids=["short", "long"])
def test_568_appendix_findings_fit_complete_section_projection_without_loss(summary):
    inputs = _appendix_inputs(summary=summary)
    source, _, original, artifact, _ = inputs
    runtime = RuntimeSectionsMixin()
    before = original.model_dump(mode="json", by_alias=True)
    frozen = artifact.model_dump(mode="json", by_alias=True)
    unsplit = _work_item(runtime, original.sections[-1], inputs)
    assert len(_json_text(_section_model_work_item_payload(unsplit)).encode()) > MAX_SECTION_WORK_ITEM_BYTES

    fitted = _fit(runtime, inputs)

    assert len(fitted.sections) > len(original.sections)
    assert fitted.sections[0] == original.sections[0]
    assert fitted.appendix_finding_ids == original.appendix_finding_ids
    assigned = [fid for section in fitted.sections for fid in section.finding_ids]
    assert assigned == [card.finding_id for card in source.findings]
    assert len(set(assigned)) == len(assigned)
    for index, section in enumerate(fitted.sections, 1):
        assert section.code == f"section_{index:03d}"
        assert section.section_number == str(index)
        item = _work_item(runtime, section, inputs)
        assert len(_json_text(_section_model_work_item_payload(item)).encode()) <= MAX_SECTION_WORK_ITEM_BYTES
        assert tuple(card["findingId"] for card in item.finding_summaries) == section.finding_ids
        assert all(card["sourceRefs"] for card in item.finding_summaries)
        assert item.evidence and item.citations and item.metric_definitions
    assert original.model_dump(mode="json", by_alias=True) == before
    assert artifact.model_dump(mode="json", by_alias=True) == frozen
    assert _fit(runtime, (*inputs[:2], fitted, *inputs[3:])) == fitted


@pytest.mark.parametrize("over_budget", [False, True])
def test_appendix_split_uses_full_utf8_projection_and_exact_boundary(monkeypatch, over_budget):
    inputs = _appendix_inputs(count=8)
    runtime = RuntimeSectionsMixin()
    item = _work_item(runtime, inputs[2].sections[-1], inputs)
    size = len(_json_text(_section_model_work_item_payload(item)).encode())
    # 摘要本身低于预算仍须计入 evidence、citation、目录及中文 UTF-8 字节。
    assert len(_json_text(item.finding_summaries).encode()) < size - 1
    monkeypatch.setattr(section_runtime, "MAX_SECTION_WORK_ITEM_BYTES", size - int(over_budget))
    fitted = _fit(runtime, inputs)
    assert (len(fitted.sections) > 2) == over_budget


def test_appendix_split_also_respects_evidence_file_capacity():
    inputs = _appendix_inputs(count=101, analysis_count=101, files_per_analysis=2)
    fitted = _fit(RuntimeSectionsMixin(), inputs)
    assert len(fitted.sections) > 2
    for section in fitted.sections:
        assert len(_work_item(RuntimeSectionsMixin(), section, inputs).fact_files) <= 200


def test_single_oversized_finding_fails_without_truncating_frozen_evidence(monkeypatch):
    inputs = _appendix_inputs(count=1)
    monkeypatch.setattr(section_runtime, "MAX_SECTION_WORK_ITEM_BYTES", 100)
    with pytest.raises(ReportingError) as error:
        _fit(RuntimeSectionsMixin(), inputs)
    assert error.value.code == "report_section_context_too_large"
    assert error.value.details["findingId"] == inputs[0].findings[-1].finding_id


class _CheckpointRuntime(RuntimeAnalysisMixin, RuntimeSectionsMixin):
    """仅替换外部文件/任务端口；checkpoint 校验、合并、持久化命令用生产实现。"""

    def __init__(self, root, checkpoint):
        self.root = root
        self._checkpoint_persist_lock = asyncio.Lock()
        self.state_repository = SimpleNamespace(get=self._get, get_by_external_run_id=self._get)
        self.durable = ReportingRunState.initial(
            report_run_id="run-1", external_run_id="run-1", thread_id="thread-1", owner_user_id="user-1",
        ).model_copy(update={"phase": ReportingPhase.SECTIONS, "payload": {
            "workflowCheckpoint": checkpoint.model_dump(mode="json", by_alias=True),
        }})
        self.state = {}

    def _scope(self, context):
        return {"threadId": "thread-1", "externalRunId": "run-1", "userId": "user-1"}

    def _state(self, context):
        return self.state

    def _envelope(self, context):
        return SimpleNamespace(report_goal="经营分析")

    async def _get(self, run_id):
        return self.durable

    async def _apply_durable_command(self, context, command):
        self.durable = apply(self.durable, command).state

    async def _write_immutable_artifact(self, thread, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == content
        else:
            target.write_bytes(content)
        return _identity(path, content)

    async def _write_artifact_validation_context(self, thread, path, payload):
        identity = await self._write_immutable_artifact(thread, path, _json_text(payload).encode())
        return identity.model_dump(mode="json", by_alias=True)

    async def _read_identity_model(self, thread, identity, model):
        content = (self.root / identity.path).read_bytes()
        assert _identity(identity.path, content) == identity
        return model.model_validate_json(content)


@pytest.mark.anyio
async def test_568_appendix_is_split_before_outline_and_pending_checkpoint_are_frozen(tmp_path):
    inputs = _appendix_inputs()
    source, plan, original, artifact, _ = inputs
    compatible = build_compatible_report_outline(
        source, report_type="comprehensive", title=original.title, narrative_outline=original,
    ).model_dump(mode="json", by_alias=True)
    checkpoint = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash=payload_sha256(compatible), profileCoverage=_coverage(),
    )
    runtime = _CheckpointRuntime(tmp_path, checkpoint)
    runtime.durable = runtime.durable.model_copy(update={"phase": ReportingPhase.NARRATIVE_PLANNING})
    graph_file = await runtime._write_immutable_artifact("thread-1", "graph.json", source.model_dump_json(by_alias=True).encode())
    checkpoint = runtime._update_reporting_checkpoint(
        checkpoint, finding_graph_file=graph_file, finding_graph_hash=source.snapshot_hash,
    )
    context = RunContext(run_id="run-1", session_id="session-1")
    await runtime._persist_reporting_checkpoint(context, checkpoint)
    runtime.state.update({
        REPORT_OUTLINE_STATE_KEY: compatible, REPORT_OUTLINE_HASH_STATE_KEY: payload_sha256(compatible),
        REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: plan.model_dump(mode="json", by_alias=True),
        REPORT_DATASET_LINEAGE_STATE_KEY: [{
            "datasetId": "dataset_001", "sourceId": "source_001",
            "requirementId": "requirement_001", "sqlHash": "a" * 64,
            "rowCount": 1, "size": 2, "sha256": "a" * 64,
        }],
    })
    runtime._plan_narrative_outline = AsyncMock(return_value=(original, ()))
    runtime._build_reporting_artifact = AsyncMock(return_value=artifact)

    output = await runtime.generate_narrative_outline(None, context)

    restored = ReportingCheckpoint.model_validate(runtime.durable.payload["workflowCheckpoint"])
    narrative = await runtime._read_identity_model("thread-1", restored.narrative_outline_file, type(original))
    assert output.content["sectionCount"] == len(narrative.sections) > 2
    assert restored.pending_sections == tuple(section.code for section in narrative.sections)
    assert restored.outline_hash == payload_sha256(runtime.state[REPORT_OUTLINE_STATE_KEY])
    assert restored.narrative_outline_hash == restored.narrative_outline_file.sha256
    assert restored.narrative_outline_file in restored.files
    assert runtime.durable.phase is ReportingPhase.SECTIONS
    assert await runtime.generate_narrative_outline(None, context) == output
    runtime._plan_narrative_outline.assert_awaited_once()
    runtime._build_reporting_artifact.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("section_count,analysis_file_count", [(167, 0), (167, 80), (201, 80)])
async def test_all_sections_complete_with_existing_analysis_files_and_checkpoint_restore(
    tmp_path, section_count, analysis_file_count,
):
    codes = tuple(f"section_{i:03d}" for i in range(1, section_count + 1))
    existing = tuple(_identity(f"analysis/{i}.json") for i in range(analysis_file_count))
    checkpoint = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64, profileCoverage=_coverage(),
        pendingSections=codes, files=existing,
    )
    runtime = _CheckpointRuntime(tmp_path, checkpoint)
    runtime.section_generator = object()
    # 独立阶段任务在端口签发合法产物；_run_section_phase 照常读取、校验和登记。
    tasks = {}

    async def start(scope, instruction, **kwargs):
        tasks[scope.external_run_id] = json.loads(instruction)

    async def run(scope, **kwargs):
        payload = tasks[scope.external_run_id]
        artifact = SectionArtifact(sectionCode=payload["sectionGoal"]["sectionCode"], blocks=[{
            "blockId": "block_001", "markdown": "经营变化已有冻结证据，统计关系存在限制。",
            "claimIds": ["claim_001"],
        }], claims=[{
            "claimId": "claim_001", "metricCode": "income", "value": 1,
            "periodBasis": "2025年", "managementQuestion": "经营变化",
            "currentPeriod": "2025年", "citationIds": ["citation_001"],
        }])
        identity = await runtime._write_immutable_artifact(
            "thread-1", payload["sectionOutputPath"], artifact.model_dump_json(by_alias=True).encode(),
        )
        return {"artifacts": [identity.model_dump(mode="json", by_alias=True)]}

    async def hash_file(thread, path):
        return _identity(path, (tmp_path / path).read_bytes()).model_dump(mode="json", by_alias=True)

    runtime.task_runner = SimpleNamespace(
        repository=SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None)), start=start, run=run,
    )
    runtime.workspace_service = SimpleNamespace(ahash_file=hash_file)
    context = RunContext(run_id="run-1", session_id="session-1")
    validation = _identity("validation.json")
    first_stale = checkpoint
    for index, code in enumerate(codes, 1):
        work_item = SectionWorkItem(
            sectionCode=code, sectionNumber=str(index), title="经营变化", objective="解释变化",
            analysisIds=("analysis_001",), completionConditions=("保留证据",),
            markdownRequirements=("使用冻结事实",),
        )
        checkpoint, artifact, rework = await runtime._run_section_phase(
            context, checkpoint=checkpoint, revision=1, sandbox_id="sandbox",
            validation_context_file=validation,
            work_item=work_item,
            analysis_rework_constraints={}, analysis_rework_allowed=False, degraded_rework=None,
        )
        assert artifact.section_code == code and rework is None
        # 重新读取 durable 与磁盘镜像，不能绕过模型校验或仅使用内存副本。
        checkpoint = ReportingCheckpoint.model_validate(runtime.durable.payload["workflowCheckpoint"])
        mirror = FileIdentity.model_validate(runtime.durable.payload["checkpointMirrorFile"])
        assert await runtime._read_identity_model("thread-1", mirror, ReportingCheckpoint) == checkpoint

    assert len(checkpoint.completed_sections) == section_count
    assert not checkpoint.pending_sections
    assert len(checkpoint.files) == analysis_file_count + 3 * section_count
    assert len({item.path for item in checkpoint.files}) == len(checkpoint.files)
    assert set(existing) <= set(checkpoint.files)
    assert all(trace.status == "completed" for trace in checkpoint.trace)
    # 并发旧快照回放不能删掉分析文件、已完成章节或把 pending 重新引入。
    assert await runtime._persist_reporting_checkpoint(context, first_stale) == checkpoint
    # 恢复已完成章节必须读取 durable 身份，不再签发新任务或重复计入文件。
    replayed, restored_artifact, rework = await runtime._run_section_phase(
        context, checkpoint=checkpoint, revision=1, sandbox_id="sandbox",
        validation_context_file=validation, work_item=work_item,
        analysis_rework_constraints={}, analysis_rework_allowed=False, degraded_rework=None,
    )
    assert replayed == checkpoint
    assert restored_artifact == artifact and rework is None
    assert len(tasks) == section_count


def test_checkpoint_runtime_ledgers_scale_with_sections_and_dedupe_paths():
    files = tuple(_identity(f"facts/{i}.json") for i in range(601))
    checkpoint = ReportingCheckpoint(
        revision=1, phase="analysis", outlineHash="a" * 64, profileCoverage=_coverage(),
        files=RuntimeAnalysisMixin._merge_checkpoint_files(files, files[0]),
        trace=tuple(ContextTrace(phase="section", taskId=f"task-{i}") for i in range(2101)),
        visualizationSectionErrors={f"section_{i:03d}": CheckpointError(
            phase="analysis", code="failed", message="图表生成失败", sectionCode=f"section_{i:03d}",
        ) for i in range(1, 202)},
    )
    restored = ReportingCheckpoint.model_validate_json(checkpoint.model_dump_json(by_alias=True))
    assert restored == checkpoint
    assert len(restored.files) == 601
    assert len(restored.trace) == 2101
    assert len(restored.visualization_section_errors) == 201
