from smart_reporting.reporting.hospital_operation.narrative_planner import (
    NarrativeContentBudget,
    build_compatible_report_outline,
    build_narrative_planning_context,
    cluster_findings,
    score_finding_relation,
)
from smart_reporting.reporting.tests.narrative_helpers import finding, graph


def test_related_income_and_workload_findings_share_group():
    left = finding(1, metricCodes=("income",), relatedFindingIds=("finding_0000000000000002",))
    right = finding(2, metricCodes=("workload",), relatedFindingIds=("finding_0000000000000001",))
    groups = cluster_findings(graph(left, right))
    assert {left.finding_id, right.finding_id} in [set(group) for group in groups]


def test_same_topic_can_include_hospital_trend_and_department_contribution():
    left = finding(1, grain=("院区",))
    right = finding(2, kind="attribution", grain=("科室",), periodEnd="2025-10-31")
    groups = cluster_findings(graph(left, right))
    assert groups == ((left.finding_id, right.finding_id),)


def test_cluster_has_content_budget():
    cards = [finding(i, priority="low") for i in range(1, 5)]
    groups = cluster_findings(graph(*cards), NarrativeContentBudget(max_findings_per_section=2))
    assert all(len(group) <= 2 for group in groups)


def test_unrelated_domains_are_not_forced_into_same_section():
    left = finding(1, metricCodes=("income",))
    right = finding(2, metricCodes=("funds",))
    assert score_finding_relation(left, right) == 0


def test_planning_context_does_not_hide_themes_as_section_overflow():
    cards = [finding(i, metricCodes=(f"metric_{i}",)) for i in range(1, 15)]
    context = build_narrative_planning_context(graph(*cards), "识别经营问题")
    assert {item for group in context["candidateGroups"] for item in group} == {
        card.finding_id for card in cards
    }
    assert "maxSections" not in context.get("contentBudget", {})


def test_default_grouping_does_not_split_theme_by_finding_count():
    cards = [finding(i, title="收入变化", priority="medium") for i in range(1, 241)]
    source = graph(*cards)
    assert cluster_findings(source) == (tuple(card.finding_id for card in cards),)
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_fallback_narrative_candidate,
    )

    candidate = build_fallback_narrative_candidate(source, "经营报告")
    assert len(candidate.sections) == 1
    assert candidate.sections[0].finding_ids == tuple(card.finding_id for card in cards)


def test_compatible_outline_uses_finding_groups_instead_of_analysis_count():
    cards = [
        finding(1, metricCodes=("income",), relatedFindingIds=("finding_0000000000000002",)),
        finding(2, metricCodes=("workload",), relatedFindingIds=("finding_0000000000000001",)),
    ]
    outline = build_compatible_report_outline(
        graph(*cards), report_type="comprehensive", title="医院运营分析"
    )
    assert len(outline.sections) == 1
    assert outline.sections[0].analysis_ids == ("analysis_001", "analysis_002")


def test_compatible_outline_preserves_frozen_narrative_sections():
    from smart_reporting.reporting.hospital_operation.narrative_outline import (
        NarrativeOutlineCandidate,
        freeze_narrative_outline,
    )
    cards = [finding(1), finding(2)]
    source_graph = graph(*cards)
    candidate = NarrativeOutlineCandidate(
        title="经营变化与结构风险", snapshotHash=source_graph.snapshot_hash,
        sections=[
            {"title": "收入变化", "findingIds": [cards[0].finding_id],
             "objective": "解释收入变化", "groupingReason": "收入管理问题"},
            {"title": "结构风险", "findingIds": [cards[1].finding_id],
             "objective": "识别结构风险", "groupingReason": "风险管理问题"},
        ],
    )
    narrative = freeze_narrative_outline(
        candidate, graph=source_graph,
        analyses=[{"analysisId": "analysis_001"}, {"analysisId": "analysis_002"}],
    )
    result = build_compatible_report_outline(
        source_graph, report_type="comprehensive", title=narrative.title,
        narrative_outline=narrative,
    )
    assert [section.title for section in result.sections] == ["收入变化", "结构风险"]
    assert [section.analysis_ids for section in result.sections] == [
        ("analysis_001",), ("analysis_002",),
    ]
    assert result.sections[0].focus == ("解释收入变化",)


def test_fallback_merges_duplicate_trends_without_filling_section_cap():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_fallback_narrative_candidate,
    )
    cards = [finding(i, title='收入趋势', kind='trend', priority='medium') for i in range(1, 19)]
    candidate = build_fallback_narrative_candidate(graph(*cards), '运营报告')
    assert len(candidate.sections) == 1
    assert candidate.sections[0].title == '收入趋势'
    assert set(candidate.sections[0].finding_ids) == {card.finding_id for card in cards}


def test_fallback_keeps_operating_topics_ahead_of_statistical_appendix():
    from smart_reporting.reporting.hospital_operation.narrative_planner import (
        build_fallback_narrative_candidate,
    )
    cards = [finding(i, title='收入统计关系', metricCodes=(f'field_{i}',),
                     evidenceLevel='statistical_relation', priority='medium') for i in range(1, 80)]
    cost = finding(80, title='成本异常', kind='anomaly', metricCodes=('cost',), priority='medium')
    candidate = build_fallback_narrative_candidate(graph(*cards, cost), '运营报告')
    assert any(cost.finding_id in section.finding_ids for section in candidate.sections)
    assert all(card.finding_id in candidate.appendix_finding_ids for card in cards)
