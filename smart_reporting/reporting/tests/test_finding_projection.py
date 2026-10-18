import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)
from smart_reporting.reporting.hospital_operation.finding_projection import (
    project_analysis_findings,
)


def facts(**changes):
    return DeterministicAnalysisBundle.model_validate({
        "analysisId": "analysis_001", "metrics": [], "comparisons": [],
        "derivedMetrics": [], "reconciliations": [], "correlations": {},
        "correlationDetails": [], **changes,
    })


def test_projection_creates_trend_finding_from_period_values():
    result = project_analysis_findings("analysis_001", facts(metrics=[{
        "datasetId": "dataset-abc123", "datasetSha256": "a" * 64, "periodRoles": ["current"],
        "field": "income", "fieldRef": "income", "aggregation": "sum", "formula": "sum(income)",
        "total": 20, "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
        "periodValues": [{"period": "2025-01", "value": 10}, {"period": "2025-02", "value": 20}],
    }]), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert any(item.kind == "trend" for item in result)


@pytest.mark.parametrize('values', [(0, 0), (10, 10)])
def test_constant_metric_is_low_priority_and_uses_display_name(values):
    result = project_analysis_findings('analysis_001', facts(metrics=[{
        'datasetId': 'dataset-abc123', 'datasetSha256': 'a' * 64,
        'periodRoles': ['current'],
        'field': 'income', 'fieldRef': 'income', 'displayName': '医疗收入',
        'aggregation': 'sum', 'formula': 'sum(income)', 'total': sum(values),
        'missingCount': 0, 'zeroCount': 2 if values[0] == 0 else 0, 'negativeCount': 0,
        'periodValues': [{'period': '2025-01', 'value': values[0]},
                         {'period': '2025-02', 'value': values[1]}],
    }]), None, snapshot_hash='b' * 64, citation_ids=('citation_001',))
    assert result[0].kind == 'data_quality'
    assert result[0].priority == 'low'
    assert result[0].title == '医疗收入期间值一致'


def test_reconciliation_name_does_not_establish_direct_attribution():
    result = project_analysis_findings("analysis_001", facts(reconciliations=[{
        "code": "contribution", "periodRole": "current", "leftMetric": "income",
        "rightMetric": "groups", "grain": ["院区"], "leftTotal": 10, "rightTotal": 10,
        "difference": 0, "absoluteTolerance": 0, "relativeTolerance": 0,
        "checkedGroupCount": 1, "failedGroupCount": 0, "passed": True,
        "formula": "sum(groups)=income", "datasetIds": ["dataset-abc123"],
        "datasetSha256s": ["a" * 64],
    }]), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert all(item.evidence_level != "direct_decomposition" for item in result)
    assert result[0].title == "指标对账通过"
    assert not result[0].limitations


def test_projection_marks_correlation_as_statistical_relation():
    result = project_analysis_findings("analysis_001", facts(correlationDetails=[{
        "datasetId": "dataset-abc123", "datasetSha256": "a" * 64,
        "leftField": "income", "rightField": "workload", "method": "pearson",
        "sampleCount": 12, "value": 0.8,
    }]), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert next(item for item in result if item.kind == "impact").evidence_level == "statistical_relation"


def test_projection_keeps_only_the_strongest_moderate_correlations():
    # 回放：每对相关系数都成为发现（含 r=0.005），规划出整章重复的“统计关系说明”。
    values = (0.0048, -0.31, 0.95, -0.88, 0.81, 0.77, 0.66, 0.52)
    details = [{"datasetId": "dataset-abc123", "datasetSha256": "a" * 64, "leftField": f"left{index}",
                "rightField": "workload", "method": "pearson", "sampleCount": 12, "value": value}
               for index, value in enumerate(values)]
    result = project_analysis_findings("analysis_001", facts(correlationDetails=details), None,
                                       snapshot_hash="b" * 64, citation_ids=("citation_001",))
    relations = [item for item in result if item.evidence_level == "statistical_relation"]
    pointers = [item.source_refs[0].pointer for item in relations]
    assert pointers == [f"/correlationDetails/{index}" for index in (2, 3, 4, 5, 6)]
    assert "相关系数0.95" in relations[0].summary


def test_projection_has_missing_evidence_when_bundle_is_empty():
    result = project_analysis_findings("analysis_001", facts(), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert result[0].impact_value is None
    assert result[0].evidence_level == "evidence_missing"


def test_projection_ids_are_stable():
    first = project_analysis_findings("analysis_001", facts(), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    second = project_analysis_findings("analysis_001", facts(), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert [item.finding_id for item in first] == [item.finding_id for item in second]


def test_trend_finding_preserves_fact_scope_period_and_pointer():
    result = project_analysis_findings("analysis_001", facts(metrics=[{
        "datasetId": "dataset-abc123", "datasetSha256": "a" * 64,
        "periodRoles": ["current"], "metricCodes": ["income_total"],
        "field": "income", "fieldRef": "income", "aggregation": "sum",
        "formula": "sum(income)", "total": 30,
        "scope": {"income_nature": "开单收入"},
        "periodStart": "2025-01-01", "periodEnd": "2025-02-28",
        "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
        "periodValues": [{"period": "2025-01", "value": 10}, {"period": "2025-02", "value": 20}],
    }]), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    trend = next(item for item in result if item.kind == "trend")
    assert trend.metric_codes == ("income_total",)
    assert trend.scope == {"income_nature": "开单收入"}
    assert trend.period_start == "2025-01-01"
    assert trend.period_end == "2025-02-28"
    assert trend.source_refs[0].pointer == "/metrics/0/periodValues"


def test_projection_uses_registered_citations_instead_of_inventing_ids():
    result = project_analysis_findings(
        "analysis_001", facts(), None, snapshot_hash="b" * 64,
        citation_ids=("citation_007",),
    )
    assert result[0].citation_ids == ("citation_007",)


def test_supplemental_finding_retains_its_file_identity_and_pointer():
    evidence = {
        "analysisId": "analysis_001", "datasetIds": ["dataset-abc123"],
        "findings": [{"name": "院区收入变化", "kind": "comparison",
                      "columns": ["院区", "差额"], "rows": [["东院区", 10]]}],
        "reconciliations": [{"name": "收入对账", "passed": True}], "warnings": [],
    }
    result = project_analysis_findings(
        "analysis_001", facts(), evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_007",),
        supplemental_file_path="evidence/001.json", supplemental_file_sha256="c" * 64,
    )
    selected = next(item for item in result if item.title == "院区收入变化")
    assert selected.source_refs[0].path == "evidence/001.json"
    assert selected.source_refs[0].file_sha256 == "c" * 64
    assert selected.source_refs[0].pointer == "/findings/0"
    assert selected.citation_ids == ("citation_007",)
    assert selected.impact_value is None


def test_supplemental_projection_requires_frozen_file_identity():
    with pytest.raises(ValueError, match="身份"):
        project_analysis_findings(
            "analysis_001", facts(), {"findings": [{"name": "收入变化"}]},
            snapshot_hash="b" * 64, citation_ids=("citation_007",),
        )


def test_supplemental_attribution_requires_closed_reconciliation_and_preserves_scope():
    authoritative = facts(metrics=[{
        "factId": "fact-1111111111111111", "datasetId": "dataset-abc123", "datasetSha256": "a" * 64,
        "periodRoles": ["current"], "metricCodes": ["income"], "field": "income",
        "fieldRef": "income", "aggregation": "sum", "formula": "sum(income)", "total": 100,
        "topGroups": [{"group": "A", "value": 60}, {"group": "B", "value": 40}],
        "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
    }])
    evidence = {
        "analysisId": "analysis_001", "datasetIds": ["dataset-abc123"],
        "findings": [{
            "name": "科室收入分解", "kind": "attribution", "directDecomposition": True,
            "reconciliationCode": "income_by_department", "metricCodes": ["income"],
            "sourceFactIds": ["fact-1111111111111111"],
            "periodRoles": ["current"], "grain": ["科室"], "scope": {"性质": "开单收入"},
            "total": 100, "components": [{"name": "A", "value": 60}, {"name": "B", "value": 40}],
        }],
        "reconciliations": [{
            "name": "科室收入合计对账", "code": "income_by_department", "passed": True,
            "leftTotal": 100, "rightTotal": 100, "difference": 0,
            "grain": ["科室"], "scope": {"性质": "开单收入"},
        }],
        "warnings": [],
    }
    result = project_analysis_findings(
        "analysis_001", authoritative, evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_007",), supplemental_file_path="evidence/001.json",
        supplemental_file_sha256="c" * 64,
    )
    attribution = next(item for item in result if item.title == "科室收入分解")
    assert attribution.kind == "attribution"
    assert attribution.evidence_level == "direct_decomposition"
    assert attribution.grain == ("科室",)
    assert attribution.scope == {"性质": "开单收入"}


def test_supplemental_attribution_with_failed_or_nonclosing_reconciliation_is_not_direct():
    evidence = {
        "analysisId": "analysis_001", "datasetIds": ["dataset-abc123"],
        "findings": [{"name": "疑似收入分解", "kind": "attribution", "directDecomposition": True,
                      "reconciliationCode": "bad", "total": 100,
                      "components": [{"name": "A", "value": 90}]}],
        "reconciliations": [{"name": "对账失败", "code": "bad", "passed": False,
                             "leftTotal": 100, "rightTotal": 90, "difference": 10}],
        "warnings": [],
    }
    result = project_analysis_findings(
        "analysis_001", facts(), evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_007",), supplemental_file_path="evidence/001.json",
        supplemental_file_sha256="c" * 64,
    )
    attribution = next(item for item in result if item.title == "疑似收入分解")
    assert attribution.evidence_level != "direct_decomposition"


def test_supplemental_attribution_without_authoritative_source_fact_is_not_direct():
    evidence = {
        "analysisId": "analysis_001", "datasetIds": ["dataset-abc123"],
        "findings": [{"name": "伪造分解", "kind": "attribution", "directDecomposition": True,
                      "reconciliationCode": "ok", "total": 100,
                      "components": [{"name": "A", "value": 100}]}],
        "reconciliations": [{"name": "自报对账", "code": "ok", "passed": True,
                             "leftTotal": 100, "rightTotal": 100, "difference": 0}],
        "warnings": [],
    }
    result = project_analysis_findings(
        "analysis_001", facts(), evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_007",), supplemental_file_path="evidence/001.json",
        supplemental_file_sha256="c" * 64,
    )
    attribution = next(item for item in result if item.title == "伪造分解")
    assert attribution.evidence_level != "direct_decomposition"
