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
    }]), None, snapshot_hash="b" * 64)
    assert any(item.kind == "trend" for item in result)


def test_projection_marks_closed_reconciliation_as_direct_attribution():
    result = project_analysis_findings("analysis_001", facts(reconciliations=[{
        "code": "contribution", "periodRole": "current", "leftMetric": "income",
        "rightMetric": "groups", "grain": ["院区"], "leftTotal": 10, "rightTotal": 10,
        "difference": 0, "absoluteTolerance": 0, "relativeTolerance": 0,
        "checkedGroupCount": 1, "failedGroupCount": 0, "passed": True,
        "formula": "sum(groups)=income", "datasetIds": ["dataset-abc123"],
        "datasetSha256s": ["a" * 64],
    }]), None, snapshot_hash="b" * 64)
    assert next(item for item in result if item.kind == "attribution").evidence_level == "direct_decomposition"


def test_projection_marks_correlation_as_statistical_relation():
    result = project_analysis_findings("analysis_001", facts(correlationDetails=[{
        "datasetId": "dataset-abc123", "datasetSha256": "a" * 64,
        "leftField": "income", "rightField": "workload", "method": "pearson",
        "sampleCount": 12, "value": 0.8,
    }]), None, snapshot_hash="b" * 64)
    assert next(item for item in result if item.kind == "impact").evidence_level == "statistical_relation"


def test_projection_has_missing_evidence_when_bundle_is_empty():
    result = project_analysis_findings("analysis_001", facts(), None, snapshot_hash="b" * 64)
    assert result[0].impact_value is None
    assert result[0].evidence_level == "evidence_missing"


def test_projection_ids_are_stable():
    first = project_analysis_findings("analysis_001", facts(), None, snapshot_hash="b" * 64)
    second = project_analysis_findings("analysis_001", facts(), None, snapshot_hash="b" * 64)
    assert [item.finding_id for item in first] == [item.finding_id for item in second]
