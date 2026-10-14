from smart_reporting.reporting.hospital_operation.narrative_planner import (
    NarrativeContentBudget,
    cluster_findings,
    score_finding_relation,
)
from smart_reporting.reporting.tests.test_dynamic_narrative_contracts import finding, graph


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
