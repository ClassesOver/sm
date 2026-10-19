"""动态提纲模型候选、服务端纠错与降级。"""

from types import SimpleNamespace

import pytest
from agno.exceptions import ModelProviderError

from smart_reporting.reporting.hospital_operation.narrative_outline import NarrativeOutlineCandidate
from smart_reporting.reporting.tests.narrative_helpers import finding, graph
from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin


def candidate(snapshot, finding_ids, title="收入增长与结构风险"):
    return NarrativeOutlineCandidate(
        title="医院运营分析", snapshotHash=snapshot,
        sections=[{"title": title, "findingIds": finding_ids,
                   "objective": "解释已核验变化", "groupingReason": "共同管理问题"}],
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_runtime_corrects_unknown_finding_and_preserves_model_title(anyio_backend):
    source = graph(finding())
    requests = []

    async def planner(agent, payload, context, **kwargs):
        requests.append(payload)
        if len(requests) == 1:
            return candidate(source.snapshot_hash, ["finding_ffffffffffffffff"])
        return candidate(source.snapshot_hash, [source.findings[0].finding_id])

    runtime = SimpleNamespace(_narrative_outline_agent=object(), _run_planner=planner)
    result, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=source, title="医院运营分析", report_goal="识别经营风险",
        analyses=[{"analysisId": "analysis_001"}], run_context=None,
    )
    assert result.sections[0].title == "收入增长与结构风险"
    assert len(requests) == 2
    assert "correction" in requests[1]
    assert not issues


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_runtime_preserves_findings_and_warns_after_invalid_candidates(anyio_backend):
    source = graph(finding())

    async def planner(agent, payload, context, **kwargs):
        return candidate(source.snapshot_hash, ["finding_ffffffffffffffff"])

    runtime = SimpleNamespace(_narrative_outline_agent=object(), _run_planner=planner)
    result, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=source, title="医院运营分析", report_goal="识别经营风险",
        analyses=[{"analysisId": "analysis_001"}], run_context=None,
    )
    assert result.sections[0].finding_ids == (source.findings[0].finding_id,)
    assert issues[0]["code"] == "report_narrative_planning_degraded"
    assert "未知" in issues[0]["message"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_fallback_preserves_independent_topics_and_one_appendix(anyio_backend):
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_compatible_report_outline,
    )

    cards = [finding(i, metricCodes=(f"metric_{i}",),
                     priority="high" if i <= 14 else "medium",
                     evidenceLevel="verified_fact" if i <= 14 else "statistical_relation")
             for i in range(1, 583)]
    source = graph(*cards)

    async def planner(agent, payload, context, **kwargs):
        return candidate(source.snapshot_hash, ["finding_ffffffffffffffff"])

    runtime = SimpleNamespace(_narrative_outline_agent=object(), _run_planner=planner)
    result, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=source, title="医院运营分析", report_goal="识别经营风险",
        analyses=[{"analysisId": f"analysis_{i:03d}"} for i in range(1, 583)],
        run_context=None,
    )
    assigned = [item for section in result.sections for item in section.finding_ids]
    assert len(assigned) == len(set(assigned)) == len(cards)
    assert set(assigned) == {card.finding_id for card in cards}
    assert all(card.finding_id not in result.appendix_finding_ids
               for card in cards if card.priority == "high")
    assert len(result.sections) == 15
    assert all(len(section.finding_ids) == 1 for section in result.sections[:-1])
    assert result.sections[-1].narrative_role == "appendix"
    assert len(result.sections[-1].finding_ids) == 568
    compatible = build_compatible_report_outline(
        source, report_type="comprehensive", title=result.title, narrative_outline=result,
    )
    assert len(compatible.sections) == len(result.sections)
    assert issues[0]["code"] == "report_narrative_planning_degraded"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_provider_failure_degrades_to_deterministic_outline(anyio_backend):
    source = graph(finding())

    async def planner(agent, payload, context, **kwargs):
        raise ModelProviderError("Invalid request parameters", status_code=400)

    runtime = SimpleNamespace(_narrative_outline_agent=object(), _run_planner=planner)
    result, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=source, title="医院运营分析", report_goal="识别经营风险",
        analyses=[{"analysisId": "analysis_001"}], run_context=None,
    )

    assert result.sections[0].finding_ids == (source.findings[0].finding_id,)
    assert issues[0]["code"] == "report_narrative_planning_degraded"
    assert "Invalid request parameters" in issues[0]["message"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("phase,corruption", [
    ("narrative_planning", None), ("sections", None), ("finalize", None),
    ("sections", "finding_graph_hash"), ("sections", "narrative_outline_hash"),
    ("sections", "outline_hash"), ("sections", "snapshot"),
])
async def test_runtime_restores_frozen_outline_without_replanning(anyio_backend, phase, corruption):
    from smart_reporting.reporting.hospital_operation.narrative_outline import (
        freeze_narrative_outline,
    )
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_compatible_report_outline,
    )
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.checkpoint import ReportingCheckpoint
    from smart_reporting.reporting.workflow.runtime.base import (
        REPORT_OUTLINE_HASH_STATE_KEY,
        REPORT_OUTLINE_STATE_KEY,
        payload_sha256,
    )
    from smart_reporting.reporting.workflow.state import ReportingPhase, ReportingRunState, apply

    source = graph(finding())
    narrative = freeze_narrative_outline(
        candidate(source.snapshot_hash, [source.findings[0].finding_id]),
        graph=source, analyses=[{"analysisId": "analysis_001"}],
    )
    compatible = build_compatible_report_outline(
        source, report_type="comprehensive", title=narrative.title, narrative_outline=narrative,
    ).model_dump(mode="json", by_alias=True)
    checkpoint = ReportingCheckpoint.model_validate({
        "revision": 1, "phase": "analysis", "outlineHash": payload_sha256(compatible),
        "profileCoverage": {
            "authorizedDatasetCount": 1, "coveredDatasetCount": 1,
            "datasets": [{
                "datasetId": "dataset-url-abc0001", "datasetPath": "data.csv",
                "datasetSize": 10, "datasetSnapshotHash": "c" * 64,
                "profileFile": {"path": "profile.json", "size": 1, "sha256": "d" * 64},
                "rowCount": 1, "fieldCount": 1, "fields": ["amount"],
            }],
        },
        "findingGraphFile": {"path": "graph.json", "size": 1, "sha256": "e" * 64},
        "findingGraphHash": source.snapshot_hash,
        "narrativeOutlineFile": {"path": "outline.json", "size": 1, "sha256": "f" * 64},
        "narrativeOutlineHash": "f" * 64,
        "warnings": [{"code": "existing_warning"}],
    })
    if corruption == "snapshot":
        narrative = narrative.model_copy(update={"snapshot_hash": "a" * 64})
    elif corruption is not None:
        checkpoint = checkpoint.model_copy(update={corruption: "a" * 64})
    durable = ReportingRunState.initial(
        report_run_id="run-1", external_run_id="run-1", thread_id="thread-1", owner_user_id="user-1",
    ).model_copy(update={"phase": ReportingPhase(phase), "payload": {
        "workflowCheckpoint": checkpoint.model_dump(mode="json", by_alias=True),
    }})
    state = {REPORT_OUTLINE_STATE_KEY: compatible, REPORT_OUTLINE_HASH_STATE_KEY: payload_sha256(compatible)}

    async def get(run_id):
        return durable

    async def read(thread_id, identity, model):
        return source if identity.path == "graph.json" else narrative

    async def command(context, value):
        nonlocal durable
        durable = apply(durable, value).state

    runtime = SimpleNamespace(
        _scope=lambda context: {"threadId": "thread-1", "externalRunId": "run-1"},
        state_repository=SimpleNamespace(get=get), _read_identity_model=read,
        _state=lambda context: state, _apply_durable_command=command,
    )
    if corruption is not None:
        with pytest.raises(ReportingError, match="不一致"):
            await RuntimeAnalysisMixin.generate_narrative_outline(
                runtime, None, SimpleNamespace(run_id="run-1"),
            )
        assert durable.phase is ReportingPhase.SECTIONS
        return
    result = await RuntimeAnalysisMixin.generate_narrative_outline(
        runtime, None, SimpleNamespace(run_id="run-1"),
    )
    assert result.content["sectionCount"] == 1
    assert state[REPORT_OUTLINE_STATE_KEY] == compatible
    assert durable.phase is (ReportingPhase.FINALIZE if phase == "finalize" else ReportingPhase.SECTIONS)
    assert durable.payload["workflowCheckpoint"] == checkpoint.model_dump(mode="json", by_alias=True)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_runtime_repairs_mistyped_finding_ids_and_keeps_planned_sections(anyio_backend):
    # 回放：190个发现的全局统筹因抄错编号被拒，整份报告退回确定性分组，章节名成了发现标题拼接。
    cards = [finding(i) for i in range(1, 5)]
    source = graph(*cards)
    ids = [card.finding_id for card in cards]

    async def planner(agent, payload, context, **kwargs):
        return candidate(source.snapshot_hash, [ids[0], "finding_ffffffffffffffff", ids[0], ids[1]],
                         title="收入规模与结构")

    runtime = SimpleNamespace(_narrative_outline_agent=object(), _run_planner=planner)
    result, issues = await RuntimeAnalysisMixin._plan_narrative_outline(
        runtime, graph=source, title="医院运营分析", report_goal="识别经营风险",
        analyses=[{"analysisId": f"analysis_{i:03d}"} for i in range(1, 5)], run_context=None,
    )
    assert result.sections[0].title == "收入规模与结构"
    assigned = [item for section in result.sections for item in section.finding_ids] + list(result.appendix_finding_ids)
    assert sorted(assigned) == sorted(ids)
    assert [issue["code"] for issue in issues] == ["report_narrative_outline_repaired"]
    assert "1 个未知、1 个重复" in issues[0]["message"]


def test_fallback_section_titles_use_analysis_names_not_joined_finding_titles():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_fallback_narrative_candidate,
    )

    cards = [finding(i, title=f"指标{i}比较变化") for i in range(1, 4)]
    names = [{"analysisId": f"analysis_{i:03d}", "analysisName": f"分析{i}"} for i in range(1, 4)]
    outline = build_fallback_narrative_candidate(graph(*cards), "医院运营分析", analyses=names)
    for section in outline.sections:
        assert "；" not in section.title and len(section.title) <= 30
        assert section.title.startswith("分析")


@pytest.mark.parametrize(("goal", "start", "end", "report_type", "expected"), [
    ("请使用默认真实数据源和现有Reporting流程生成2025年瑞金医院综合运营分析正式报告，覆盖收入规模。",
     "2025-01-01", "2025-12-31", "comprehensive", "2025年瑞金医院综合运营分析报告"),
    ("分析收入和成本变化。", "2025-01-01", "2025-12-31", "comprehensive", "2025年综合运营分析报告"),
    ("分析收入和成本变化。", "2025-01-01", "2025-09-30", "topic", "2025年1—9月专题运营分析报告"),
    ("生成报告。", "2024-07-01", "2025-06-30", None, "2024—2025年运营分析报告"),
])
def test_default_report_title_uses_requested_title_or_period(goal, start, end, report_type, expected):
    from datetime import date

    from smart_reporting.reporting.hospital_operation.narrative_planner import default_report_title

    assert default_report_title(goal, date.fromisoformat(start), date.fromisoformat(end), report_type) == expected
