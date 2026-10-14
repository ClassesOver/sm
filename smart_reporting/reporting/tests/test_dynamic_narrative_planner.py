from smart_reporting.reporting.hospital_operation.narrative_planner import (
    NarrativeContentBudget,
    build_compatible_report_outline,
    cluster_findings,
    score_finding_relation,
)
from smart_reporting.reporting.tests.narrative_helpers import finding, graph


def test_related_income_and_workload_findings_share_group():
    left = finding(1, metricCodes=("income",), relatedFindingIds=("finding_0000000000000002",))
    right = finding(2, metricCodes=("workload",), relatedFindingIds=("finding_0000000000000001",))
    groups = cluster_findings(graph(left, right))
    assert {left.finding_id, right.finding_id} in [set(group) for group in groups]


def test_period_or_grain_conflict_does_not_merge():
    left = finding(1, grain=("院区",))
    right = finding(2, grain=("科室",))
    groups = cluster_findings(graph(left, right))
    assert all(set(group) != {left.finding_id, right.finding_id} for group in groups)


def test_cluster_has_content_budget():
    cards = [finding(i, priority="low") for i in range(1, 5)]
    groups = cluster_findings(graph(*cards), NarrativeContentBudget(max_findings_per_section=2))
    assert all(len(group) <= 2 for group in groups)


def test_unrelated_domains_are_not_forced_into_same_section():
    left = finding(1, metricCodes=("income",))
    right = finding(2, metricCodes=("funds",))
    assert score_finding_relation(left, right) == 0


def test_section_budget_does_not_drop_findings():
    cards = [finding(i, priority="low") for i in range(1, 4)]
    groups = cluster_findings(graph(*cards), NarrativeContentBudget(max_sections=1))
    assert {item for group in groups for item in group} == {
        card.finding_id for card in cards
    }


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
