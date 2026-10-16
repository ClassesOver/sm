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


def test_dynamic_analysis_reuse_requires_exact_finding_and_section_bindings():
    from smart_reporting.reporting.workflow.runtime.publication import (
        _matches_narrative_analysis_bindings,
    )

    graph = _graph()
    first = _outline().sections[0]
    second = first.model_copy(update={'code': 'section_002', 'section_number': '2',
        'finding_ids': (graph.findings[1].finding_id,)})
    narrative = _outline().model_copy(update={'sections': (first, second), 'appendix_finding_ids': ()})
    assert _matches_narrative_analysis_bindings(graph, narrative, narrative, 'a' * 64)
    assert not _matches_narrative_analysis_bindings(graph, narrative, narrative, 'c' * 64)
    foreign = second.model_copy(update={'analysis_ids': ('analysis_999',)})
    assert not _matches_narrative_analysis_bindings(graph, narrative, narrative.model_copy(update={'sections': (first, foreign)}), 'a' * 64)
    unknown = second.model_copy(update={'finding_ids': ('finding_9999999999999999',)})
    altered = narrative.model_copy(update={'sections': (first, unknown)})
    assert not _matches_narrative_analysis_bindings(graph, altered, altered, 'a' * 64)


def test_analysis_reuse_exemption_uses_finding_graph_hash():
    from smart_reporting.reporting.workflow.runtime.publication import (
        _narrative_reuse_snapshot_hash,
        _without_verified_analysis_reuse,
    )

    graph = _graph()
    first = _outline().sections[0]
    second = first.model_copy(update={
        'code': 'section_002', 'section_number': '2',
        'finding_ids': (graph.findings[1].finding_id,),
    })
    narrative = _outline().model_copy(update={'sections': (first, second), 'appendix_finding_ids': ()})
    issues = [
        {'code': 'outline_analysis_duplicate', 'message': '批准提纲重复引用 analysisId。'},
        {'code': 'other', 'message': '保留'},
    ]
    dataset_hash = 'd' * 64
    assert dataset_hash != graph.snapshot_hash
    assert _narrative_reuse_snapshot_hash(graph, graph.snapshot_hash) == graph.snapshot_hash
    assert _narrative_reuse_snapshot_hash(graph, dataset_hash) is None
    assert _narrative_reuse_snapshot_hash(graph, None) is None
    cleared = _without_verified_analysis_reuse(
        issues, graph=graph, narrative=narrative, outline=narrative,
        finding_graph_hash=graph.snapshot_hash,
    )
    assert [item['code'] for item in cleared] == ['other']
    kept = _without_verified_analysis_reuse(
        issues, graph=graph, narrative=narrative, outline=narrative,
        finding_graph_hash=dataset_hash,
    )
    assert kept == issues
    assert _without_verified_analysis_reuse(
        issues, graph=graph, narrative=narrative, outline=None,
        finding_graph_hash=graph.snapshot_hash,
    ) == issues
