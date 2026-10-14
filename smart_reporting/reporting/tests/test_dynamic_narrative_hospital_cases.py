import json
from pathlib import Path

from smart_reporting.reporting.hospital_operation.findings import FindingGraph
from smart_reporting.reporting.hospital_operation.narrative_planner import (
    build_compatible_report_outline,
    cluster_findings,
)

FIXTURE = Path(__file__).parent / "fixtures" / "dynamic_narrative_hospital_cases.json"


def _cases() -> list[dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


def _graph(case: dict) -> FindingGraph:
    return FindingGraph.model_validate(case["graph"])


def test_hospital_cases_use_finding_relationships_to_shape_sections():
    cases = {case["name"]: case for case in _cases()}
    merged = _graph(cases["income_and_workload"])
    separate = _graph(cases["income_and_cost"])

    merged_groups = cluster_findings(merged)
    separate_groups = cluster_findings(separate)

    assert len(merged_groups) == 1
    assert len(separate_groups) == 2


def test_hospital_cases_cover_funds_quality_and_statistical_limits():
    cases = {case["name"]: case for case in _cases()}
    funds = _graph(cases["funds_risk"])
    relation = _graph(cases["statistical_relation"])
    quality = _graph(cases["data_quality_limit"])

    assert len(cluster_findings(funds)) == 1
    assert relation.findings[0].evidence_level == "statistical_relation"
    assert quality.findings[0].evidence_level == "evidence_missing"


def test_hospital_cases_do_not_create_budget_section_without_budget_facts():
    case = next(item for item in _cases() if item["name"] == "without_budget")
    graph = _graph(case)
    outline = build_compatible_report_outline(
        graph, report_type="comprehensive", title="医院运营分析"
    )

    assert all("预算" not in section.title for section in outline.sections)
