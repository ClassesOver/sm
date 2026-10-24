"""发现身份、范围及章节覆盖契约。"""

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.hospital_operation.narrative_outline import (
    NarrativeOutlineCandidate,
    freeze_narrative_outline,
    merge_repeated_sections,
)
from smart_reporting.reporting.tests.narrative_helpers import finding, graph


def candidate(*groups, **changes):
    return NarrativeOutlineCandidate(title="医院运营分析", snapshotHash="b" * 64,
        sections=[{"title": f"经营变化{index}", "findingIds": ids,
                   "objective": "解释经营变化", "groupingReason": "共同管理问题"}
                  for index, ids in enumerate(groups)], **changes)


def freeze(value, cards):
    return freeze_narrative_outline(value, graph=graph(*cards),
        analyses=[{"analysisId": aid} for card in cards for aid in card.analysis_ids])


def test_frozen_narrative_titles_use_report_body_wording():
    # 生产提纲走叙事冻结路径：标题与章节名同样按正文规范（“1-9月”→“1—9月”，括号全角）。
    cards = [finding(1)]
    value = NarrativeOutlineCandidate(
        title="2025年1-9月全院经济运行分析报告", snapshotHash="b" * 64,
        sections=[{"title": "收入分析(含体检)", "findingIds": [cards[0].finding_id],
                   "objective": "解释经营变化", "groupingReason": "共同管理问题"}])
    result = freeze(value, cards)
    assert result.title == "2025年1—9月全院经济运行分析报告"
    assert result.sections[0].title == "收入分析（含体检）"


def test_sections_derive_analysis_identity_and_number_from_findings():
    cards = [finding(1), finding(2)]
    result = freeze(candidate([card.finding_id for card in cards]), cards)
    assert result.sections[0].code == "section_001"
    assert result.sections[0].section_number == "1"
    assert result.sections[0].analysis_ids == ("analysis_001", "analysis_002")


@pytest.mark.parametrize("groups", [(["finding_0000000000000001"], ["finding_0000000000000001"]),
                                     (["finding_ffffffffffffffff"],)])
def test_unknown_or_repeated_finding_is_rejected(groups):
    with pytest.raises(ValueError):
        freeze(candidate(*groups), [finding()])


def test_high_priority_finding_cannot_be_silently_omitted():
    with pytest.raises(ValueError, match="遗漏"):
        freeze(candidate([finding().finding_id]), [finding(), finding(2)])


def test_low_priority_appendix_has_explicit_destination():
    cards = [finding(), finding(2, priority="low")]
    result = freeze(candidate([cards[0].finding_id], appendixFindingIds=[cards[1].finding_id]), cards)
    assert result.appendix_finding_ids == (cards[1].finding_id,)


def test_low_priority_appendix_is_materialized_as_visible_appendix_section():
    cards = [finding(), finding(2, priority="low")]
    result = freeze(candidate([cards[0].finding_id], appendixFindingIds=[cards[1].finding_id]), cards)
    appendix = result.sections[-1]
    assert appendix.narrative_role == "appendix"
    assert appendix.finding_ids == (cards[1].finding_id,)
    assert appendix.title.startswith("附录")


@pytest.mark.parametrize("changes", [
    {"periodEnd": "2025-10-31"}, {"grain": ["科室"]}, {"scope": {"income_nature": "开单"}},
])
def test_topic_can_include_different_scopes_without_changing_facts(changes):
    cards = [finding(), finding(2, **changes)]
    source = graph(*cards)
    before = source.model_dump()
    result = freeze_narrative_outline(
        candidate([card.finding_id for card in cards]), graph=source,
        analyses=[{"analysisId": aid} for card in cards for aid in card.analysis_ids],
    )
    assert result.sections[0].finding_ids == tuple(card.finding_id for card in cards)
    assert result.sections[0].analysis_ids == ("analysis_001", "analysis_002")
    assert source.model_dump() == before


def test_graph_rejects_unregistered_relationship():
    with pytest.raises(ValueError):
        graph(finding(relatedFindingIds=["finding_ffffffffffffffff"]))


def test_identity_requires_source_and_rejects_nonfinite_value():
    with pytest.raises(ValidationError):
        finding(sourceRefs=[])
    with pytest.raises(ValidationError):
        finding(impactValue=float("nan"))


def test_outline_cannot_change_snapshot():
    value = candidate([finding().finding_id]).model_copy(update={"snapshot_hash": "c" * 64})
    with pytest.raises(ValueError, match="快照"):
        freeze(value, [finding()])


@pytest.mark.parametrize("omitted", [
    [{"findingId": "finding_ffffffffffffffff", "reason": "影响较小"}],
    [{"findingId": "finding_0000000000000001", "reason": "影响较小"}],
    [{"findingId": "finding_0000000000000002"}],
    [{"findingId": "finding_0000000000000002", "reason": "   "}],
    [{"reason": "影响较小"}],
    [{"findingId": "finding_0000000000000002", "reason": "影响较小"}] * 2,
])
def test_omissions_require_unique_known_findings_and_explicit_reason(omitted):
    cards = [finding(), finding(2, priority="low")]
    with pytest.raises(ValueError, match="忽略"):
        freeze(candidate([cards[0].finding_id], omittedFindings=omitted), cards)


def test_low_priority_finding_can_be_omitted_with_reason():
    cards = [finding(), finding(2, priority="low")]
    omitted = [{"findingId": cards[1].finding_id, "reason": "对经营影响较小，正文已覆盖主要发现"}]
    result = freeze(candidate([cards[0].finding_id], omittedFindings=omitted), cards)
    assert result.omitted_findings == tuple(omitted)


def test_high_priority_finding_cannot_be_hidden_in_appendix_section():
    value = candidate([finding().finding_id])
    value = value.model_copy(update={"sections": (
        value.sections[0].model_copy(update={"narrative_role": "appendix"}),
    )})
    with pytest.raises(ValueError, match="高优先级"):
        freeze(value, [finding()])


def test_distinct_management_findings_are_not_forced_into_ten_chapters():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_compatible_report_outline,
    )

    cards = [finding(index, metricCodes=(f"metric_{index}",)) for index in range(1, 32)]
    result = freeze(candidate(*[[card.finding_id] for card in cards]), cards)
    compatible = build_compatible_report_outline(
        graph(*cards), report_type="comprehensive", title=result.title, narrative_outline=result,
    )
    assert len(result.sections) == len(compatible.sections) == len(cards)
    assert {fid for section in result.sections for fid in section.finding_ids} == {card.finding_id for card in cards}
    assert sum(len(section.finding_ids) for section in result.sections) == len(cards)
    assert {aid for section in result.sections for aid in section.analysis_ids} == {aid for card in cards for aid in card.analysis_ids}


def test_materialized_appendix_does_not_force_merging_other_chapters():
    cards = [finding(i) for i in range(1, 11)] + [finding(11, priority="low")]
    result = freeze(candidate(*[[card.finding_id] for card in cards[:-1]],
                              appendixFindingIds=[cards[-1].finding_id]), cards)
    assert len(result.sections) == 11
    assert result.sections[-1].narrative_role == "appendix"
    assert {fid for section in result.sections for fid in section.finding_ids} == {card.finding_id for card in cards}


def test_appendix_keeps_all_findings_in_one_logical_chapter():
    cards = [finding(), *(finding(i, priority="low") for i in range(2, 430))]
    appendix_ids = [card.finding_id for card in cards[1:]]
    result = freeze(candidate([cards[0].finding_id], appendixFindingIds=appendix_ids), cards)
    assert len(result.sections) == 2
    assert result.sections[-1].narrative_role == "appendix"
    assert result.sections[-1].finding_ids == tuple(appendix_ids)
    assert len(result.sections[-1].analysis_ids) == 428


def test_fallback_clustering_keeps_more_than_ten_unrelated_topics():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_narrative_planning_context,
        cluster_findings,
    )

    cards = [finding(index, metricCodes=(f"metric_{index}",)) for index in range(1, 22)]
    source = graph(*cards)
    groups = cluster_findings(source)
    assert len(groups) == len(cards)
    assert {item for group in groups for item in group} == {card.finding_id for card in cards}
    context = build_narrative_planning_context(source, "按主题完整呈现")
    assert "maxChaptersIncludingAppendix" not in context["contentBudget"]


def test_cluster_findings_scales_to_large_finding_graphs() -> None:
    import time

    from smart_reporting.reporting.hospital_operation.findings import FindingGraph
    from smart_reporting.reporting.hospital_operation.narrative_planner import cluster_findings
    from smart_reporting.reporting.tests.narrative_helpers import finding

    # 原实现逐成员线性查找卡片，1200 条发现约 16 秒；按成员卡片直接打分后应在秒级以内。
    cards = tuple(
        finding(index, metricCodes=(f"m{index % 300}",), analysisIds=(f"analysis_{index % 150:03d}",))
        for index in range(1, 1201)
    )
    started = time.perf_counter()
    groups = cluster_findings(FindingGraph(snapshotHash="a" * 64, findings=cards))
    assert time.perf_counter() - started < 5
    assert sorted(item for group in groups for item in group) == sorted(card.finding_id for card in cards)


def test_final_outline_merges_chapters_with_same_title_or_same_analysis_sources():
    # 回放：跨批次统筹后仍有两个“收入预算执行情况分析”和两个来源相同的支出预算章节。
    cards = [finding(1), finding(2), finding(3), finding(4, analysisIds=["analysis_003"]), finding(5)]
    ids = [card.finding_id for card in cards]
    sections = [
        {"title": "收入预算执行情况分析", "findingIds": [ids[0]], "maxCharts": 2},
        {"title": "支出预算执行情况分析", "findingIds": [ids[2]], "priority": "low"},
        {"title": "收入预算执行情况分析", "findingIds": [ids[1]], "maxCharts": 3},
        {"title": "支出预算执行与实际支出分析", "findingIds": [ids[3]], "priority": "high"},
        {"title": "成本运行情况分析", "findingIds": [ids[4]]},
    ]
    value = NarrativeOutlineCandidate(title="医院运营分析", snapshotHash="b" * 64, sections=[
        {"objective": "解释经营变化", "groupingReason": "共同管理问题", **item} for item in sections
    ])

    repaired, merged = merge_repeated_sections(value, graph=graph(*cards))

    assert merged == 2
    assert [section.title for section in repaired.sections] == [
        "收入预算执行情况分析", "支出预算执行情况分析", "成本运行情况分析",
    ]
    assert repaired.sections[0].finding_ids == (ids[0], ids[1])
    assert repaired.sections[0].max_charts == 5
    assert repaired.sections[1].finding_ids == (ids[2], ids[3])
    assert repaired.sections[1].priority == "high"
    frozen = freeze(repaired, cards)
    assert {fid for section in frozen.sections for fid in section.finding_ids} == set(ids)
