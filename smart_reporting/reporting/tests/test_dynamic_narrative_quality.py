from smart_reporting.reporting.hospital_operation.findings import FindingGraph
from smart_reporting.reporting.hospital_operation.narrative_outline import (
    NarrativeOutline,
    evaluate_narrative_quality,
)


def _graph():
    return FindingGraph.model_validate({
        "snapshotHash": "a" * 64,
        "findings": [
            {"findingId": "finding_0000000000000001", "analysisIds": ["analysis_001"],
             "kind": "trend", "title": "收入", "summary": "收入变化", "metricCodes": ["revenue"],
             "periodRoles": ["current"], "priority": "high", "evidenceLevel": "verified_fact",
             "actionability": "high", "citationIds": ["citation_001"],
             "sourceRefs": [{"analysisId": "analysis_001", "fileSha256": "b" * 64,
                             "path": "facts.json", "pointer": "/metrics/0"}]},
            {"findingId": "finding_0000000000000002", "analysisIds": ["analysis_001"],
             "kind": "data_quality", "title": "质量", "summary": "质量限制", "metricCodes": ["revenue"],
             "periodRoles": ["current"], "priority": "low", "evidenceLevel": "evidence_missing",
             "actionability": "low", "citationIds": ["citation_001"],
             "sourceRefs": [{"analysisId": "analysis_001", "fileSha256": "b" * 64,
                             "path": "facts.json", "pointer": "/warnings"}]},
        ],
    })


def _outline():
    return NarrativeOutline.model_validate({
        "title": "报告", "snapshotHash": "a" * 64,
        "sections": [{"code": "section_001", "sectionNumber": "1", "title": "收入",
                      "findingIds": ["finding_0000000000000001"], "analysisIds": ["analysis_001"],
                      "objective": "解释", "groupingReason": "同主题", "narrativeRole": "management_finding",
                      "priority": "high", "maxCharts": 1, "maxBlocks": 2}],
        "appendixFindingIds": ["finding_0000000000000002"],
    })


def test_quality_reports_coverage_and_rendering_gaps_as_soft_issues():
    result = evaluate_narrative_quality(_graph(), _outline(), rendered_section_codes=())
    assert result.coverage_rate == 1.0
    assert result.unassigned_finding_ids == ()
    assert any(issue["code"] == "report_narrative_section_unrendered" for issue in result.issues)


def test_quality_reports_duplicate_and_empty_sections():
    outline = _outline().model_copy(update={
        "sections": (_outline().sections[0].model_copy(update={"finding_ids": ()}),
                     _outline().sections[0].model_copy(update={"code": "section_002", "section_number": "2"}),
                     _outline().sections[0].model_copy(update={"code": "section_003", "section_number": "3"})),
    })
    result = evaluate_narrative_quality(_graph(), outline, rendered_section_codes=("section_001",))
    codes = {issue["code"] for issue in result.issues}
    assert "report_narrative_empty_section" in codes
    assert "report_narrative_duplicate_finding" in codes


def test_publication_quality_warnings_are_soft_and_include_coverage():
    from smart_reporting.reporting.workflow.runtime.publication import narrative_quality_warnings

    warnings = narrative_quality_warnings(_graph(), _outline(), rendered_section_codes=())
    assert any(item["code"] == "report_narrative_section_unrendered" for item in warnings)
    assert all("coverageRate" in item["details"] for item in warnings)
