"""大报告输入规模不能使章节验收契约或提纲请求失控。"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.narrative_helpers import finding, graph
from smart_reporting.reporting.tools.base import ReportingToolkitBase
from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin as SectionTools
from smart_reporting.reporting.workflow.checkpoint import FileIdentity, SectionWorkItem
from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin
from smart_reporting.task_execution.acceptance import normalize_acceptance_contract


@pytest.mark.anyio
async def test_large_section_starts_with_small_contract_and_complete_frozen_constraints():
    class TaskStarted(BaseException):
        pass

    analysis_ids = tuple(f"analysis_{i:03d}" for i in range(1, 15))
    constraints = {
        aid: {"datasetIds": [f"dataset_{i}" for i in range(8)],
              "periods": ["2025"], "metrics": [f"metric_{i}" for i in range(30)],
              "profileDatasets": [{"datasetId": f"dataset_{i}", "rowCount": 12,
                                   "profileSnapshotHash": "a" * 64} for i in range(8)],
              "planHash": "b" * 64}
        for aid in analysis_ids
    }
    item = SectionWorkItem(sectionCode="section_003", sectionNumber="3", title="运营变化",
                           objective="解释变化", analysisIds=analysis_ids,
                           completionConditions=("保留证据",), markdownRequirements=("使用事实",),
                           findingIds=(finding().finding_id,),
                           findingSummaries=({"findingId": finding().finding_id, "summary": "已核验经营发现"},))
    from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
        _revenue_work_item,
    )
    evidence = _revenue_work_item().evidence[0]
    item = item.model_copy(update={"evidence": tuple(
        evidence.model_copy(update={"analysis_id": aid, "summary": "重复分析摘要" * 1100}) for aid in analysis_ids
    )})
    assert item.serialized_bytes() > 256 * 1024
    checkpoint = SimpleNamespace(files=(), trace=(), last_error=None)
    files = {}
    captured = {}

    async def write(thread, path, payload):
        content = json.dumps(payload, ensure_ascii=False).encode()
        files[path] = content
        return {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}

    async def start(scope, instruction, *, acceptance_contract):
        captured.update(normalize_acceptance_contract(acceptance_contract))
        raise TaskStarted()

    runtime = object.__new__(RuntimeSectionsMixin)
    runtime._scope = lambda ctx: {"threadId": "t", "userId": "u", "externalRunId": "r"}
    runtime._state = lambda ctx: {}
    runtime._envelope = lambda ctx: SimpleNamespace(report_goal="分析经营变化")
    runtime._durable_completed_section = AsyncMock(return_value=None)
    runtime._apply_durable_command = AsyncMock()
    runtime._write_artifact_validation_context = write
    runtime._merge_checkpoint_files = lambda *args: ()
    runtime._update_reporting_checkpoint = lambda cp, **kwargs: cp
    runtime._persist_reporting_checkpoint = AsyncMock()
    runtime._replace_trace = lambda cp, *args, **kwargs: cp
    runtime.task_runner = SimpleNamespace(
        repository=SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None)), start=start)
    with pytest.raises(TaskStarted):
        await runtime._run_section_phase(
            RunContext(run_id="run-1", session_id="s"), checkpoint=checkpoint, revision=1,
            sandbox_id="sandbox", validation_context_file=FileIdentity(path="context.json", size=2, sha256="a" * 64),
            work_item=item, analysis_rework_constraints=constraints,
            analysis_rework_allowed=True, degraded_rework=None,
        )
    contract = captured["requirements"][0]["parameters"]["phaseContract"]
    assert "analysisReworkConstraints" not in contract
    identity = contract["analysisReworkConstraintsFile"]
    content = files[identity["path"]]
    assert len(content) == identity["size"]
    assert hashlib.sha256(content).hexdigest() == identity["sha256"]
    assert json.loads(content) == constraints


@pytest.mark.anyio
@pytest.mark.parametrize("tampered", [False, True])
async def test_rework_constraints_file_requires_exact_identity(tampered):
    content = b'{"analysis_001":{"planHash":"original"}}'
    identity = {"path": "constraints.json", "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest()}
    tools = object.__new__(SectionTools)
    tools.runtime = SimpleNamespace(workspace=SimpleNamespace(
        afile_bytes=AsyncMock(return_value=(content.replace(b"original", b"tampered") if tampered else content,
                                            "application/json"))))
    tools._read_trusted_json = ReportingToolkitBase._read_trusted_json.__get__(tools)
    # 文件身份优先，不能用内联数据覆盖冻结文件。
    contract = {"analysisReworkConstraintsFile": identity, "analysisReworkConstraints": {"fake": {}}}
    if tampered:
        with pytest.raises(ReportingError, match="身份"):
            await tools._analysis_rework_contract(scope=SimpleNamespace(thread_id="t"), contract=contract)
    else:
        resolved = await tools._analysis_rework_contract(scope=SimpleNamespace(thread_id="t"), contract=contract)
        assert resolved["analysisReworkConstraints"] == json.loads(content)
    assert contract["analysisReworkConstraints"] == {"fake": {}}


def test_outline_planning_batches_fit_budget_and_keep_all_findings():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_narrative_planning_batches,
    )

    cards = [finding(i, summary="经营变化" * 100) for i in range(1, 35)]
    source = graph(*cards)
    original = source.model_dump(mode="json", by_alias=True)
    batches = build_narrative_planning_batches(source, "经营分析", max_bytes=10000)
    assert len(batches) > 1
    assigned = []
    for context in batches:
        assert len(json.dumps(context, ensure_ascii=False, separators=(",", ":")).encode()) <= 10000
        assert context["snapshotHash"] == source.snapshot_hash
        ids = {card["findingId"] for card in context["findings"]}
        assert all(set(group) <= ids for group in context["candidateGroups"])
        assigned.extend(ids)
        for card in context["findings"]:
            assert card["scope"] == {} and card["periodStart"] == "2025-01-01"
            assert "sourceRefs" not in card and "citationIds" not in card
    assert len(assigned) == len(set(assigned)) == len(cards)
    assert set(assigned) == {card.finding_id for card in cards}
    assert source.model_dump(mode="json", by_alias=True) == original


def test_comparison_title_uses_matching_frozen_metric_label():
    from smart_reporting.reporting.hospital_operation.finding_projection import (
        project_analysis_findings,
    )

    payload = {"metrics": [{"fieldRef": "db.t.income", "field": "income", "displayName": "医疗收入"}],
               "comparisons": [{"field": "income", "fieldRef": "db.t.income", "change": 10,
                                "unit": "元", "comparisonType": "yoy"}]}
    result = project_analysis_findings("analysis_001", payload, None,
                                       snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert result[0].title == "医疗收入比较变化"
    assert result[0].source_refs[0].pointer == "/comparisons/0"


@pytest.mark.anyio
async def test_runtime_merges_planning_batches_against_complete_graph():
    from smart_reporting.reporting.hospital_operation.narrative_outline import (
        NarrativeOutlineCandidate,
    )
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    source = graph(*(finding(i, summary="经营变化" * 350) for i in range(1, 37)))
    calls = []

    async def planner(agent, payload, context, **kwargs):
        calls.append(payload)
        cards = payload["planningContext"]["findings"]
        groups = [cards] if payload.get("planningStage") == "consolidate" else [[card] for card in cards]
        return NarrativeOutlineCandidate(
            title="综合运营分析", snapshotHash=source.snapshot_hash,
            sections=[{"title": "经营变化", "findingIds": [card["findingId"] for card in group],
                       "objective": "解释变化", "groupingReason": "相同范围与期间"} for group in groups],
        )

    runtime = SimpleNamespace(
        _narrative_outline_agent=SimpleNamespace(model=SimpleNamespace(_task_execution_input_token_budget=32000)),
        _run_planner=planner,
    )
    outline, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=source, title="综合运营分析", report_goal="分析经营变化",
        analyses=[{"analysisId": aid} for card in source.findings for aid in card.analysis_ids],
        run_context=None,
    )
    assigned = [item for section in outline.sections for item in section.finding_ids]
    assert len(calls) > 1
    assert calls[-1].get("planningStage") == "consolidate"
    assert len(calls[-1]["planningContext"]["proposedSections"]) > 30
    assert not issues
    assert len(outline.sections) == 1
    assert len(assigned) == len(set(assigned)) == len(source.findings)


@pytest.mark.anyio
async def test_outline_hard_cap_does_not_repeat_same_payload():
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    planner = AsyncMock(side_effect=ReportingError("report_planner_context_budget_exceeded", "输入超限"))
    runtime = SimpleNamespace(_narrative_outline_agent=object(), _run_planner=planner)
    outline, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=graph(finding()), title="报告", report_goal="经营分析",
        analyses=[{"analysisId": "analysis_001"}], run_context=None,
    )
    assert planner.await_count == 1
    assert outline.sections[0].finding_ids == (finding().finding_id,)
    assert issues[0]["code"] == "report_narrative_planning_degraded"


def test_fallback_uses_frozen_analysis_name_for_technical_evidence_title():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_fallback_narrative_candidate,
    )

    source = graph(finding(title="monthly_income_share_by_area"))
    result = build_fallback_narrative_candidate(
        source, "报告", analyses=[{"analysisId": "analysis_001", "analysisName": "院区收入结构变化"}],
    )
    assert result.sections[0].title == "院区收入结构变化"
    assert result.sections[0].finding_ids == (source.findings[0].finding_id,)


def test_section_request_count_includes_system_schema_and_routed_model():
    from agno.models.message import Message

    from smart_reporting.reporting.workflow.runtime.phase_models import SectionContent
    from smart_reporting.reporting.workflow.runtime.sections import _section_request_tokens

    class Model:
        id = "original"

        def count_tokens(self, messages, *, output_schema):
            assert self.id == "routed-model"
            assert [message.role for message in messages] == ["system", "user"]
            assert messages[0].content == "章节写作约束"
            assert output_schema is SectionContent
            return 321

    agent = SimpleNamespace(model=Model(), get_system_message=lambda **kwargs: Message(role="system", content="章节写作约束"))
    context = RunContext(run_id="r", session_id="s")
    # 路由状态由现有协议函数读取，避免在测试中猜测状态字段。
    from unittest.mock import patch
    with patch("smart_reporting.reporting.workflow.runtime.sections.reporting_model_route_from_run_context",
               return_value=("standard", "routed-model")):
        assert _section_request_tokens(agent, {"generationStage": "content"}, context) == 321
    assert agent.model.id == "original"


@pytest.mark.parametrize("bound", [True, False])
def test_claim_number_context_retains_exact_budget_dependency(bound):
    from smart_reporting.reporting.tests.test_content_review import _metric
    from smart_reporting.reporting.workflow.runtime.sections import _section_number_context

    actual = {**_metric("actual_income"), "metricCodes": ["income"]}
    budget = {**_metric("budget_income"), "factId": "fact-" + "c" * 16}
    unrelated = {**_metric("budget_income"), "factId": "fact-" + "d" * 16, "datasetSha256": "e" * 64}
    content = json.dumps({"analysisId": "analysis_001", "metrics": [actual, budget, unrelated]})
    catalog, guide = _section_number_context(
        (content,), {}, claims=(SimpleNamespace(fact_ids=(actual["factId"],) if bound else (), metric_code="income"),),
    )
    assert {item["factId"] for item in guide} == {actual["factId"], budget["factId"]}
    assert any(budget["factId"] in token for token in catalog)
    assert all(unrelated["factId"] not in token for token in catalog)


def test_finding_evidence_keeps_budget_dependency_with_original_pointer():
    from smart_reporting.reporting.tests.test_content_review import _metric
    from smart_reporting.reporting.workflow.runtime.finding_evidence import finding_evidence_view
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionEvidenceFile

    actual = _metric("actual_income")
    budget = {**_metric("budget_income"), "factId": "fact-" + "c" * 16}
    foreign = {**budget, "factId": "fact-" + "d" * 16, "datasetSha256": "e" * 64}
    content = json.dumps({"analysisId": "analysis_001", "metrics": [actual, budget, foreign]})
    identity = FileIdentity(path="facts.json", size=len(content.encode()), sha256=hashlib.sha256(content.encode()).hexdigest())
    item = SectionWorkItem(
        sectionCode="section_001", sectionNumber="1", title="预算执行", objective="分析预算",
        analysisIds=("analysis_001",), completionConditions=("保留证据",), markdownRequirements=("使用事实",),
        findingIds=(finding().finding_id,), findingSummaries=({
            "findingId": finding().finding_id,
            "sourceRefs": [{"analysisId": "analysis_001", "path": "facts.json",
                            "fileSha256": identity.sha256, "pointer": "/metrics/0/total"}],
        },),
    )
    views, ids, warnings = finding_evidence_view((SectionEvidenceFile(identity=identity, content=content),), item)
    assert not warnings
    assert ids == {actual["factId"], budget["factId"]}
    assert views[0].identity == identity
    assert json.loads(views[0].content)["selected"] == [
        {"pointer": "/metrics/0", "value": actual}, {"pointer": "/metrics/1", "value": budget},
    ]
