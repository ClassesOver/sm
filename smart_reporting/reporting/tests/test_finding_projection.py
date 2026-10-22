import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
)
from smart_reporting.reporting.hospital_operation.finding_projection import (
    build_finding_graph,
    project_analysis_findings,
)
from smart_reporting.reporting.hospital_operation.narrative_planner import (
    build_fallback_narrative_candidate,
    build_narrative_planning_context,
)


def facts(**changes):
    return DeterministicAnalysisBundle.model_validate({
        "analysisId": "analysis_001", "metrics": [], "comparisons": [],
        "derivedMetrics": [], "reconciliations": [], "correlations": {},
        "correlationDetails": [], **changes,
    })


@pytest.mark.parametrize("kind", ["attribution", "comparison", "impact"])
@pytest.mark.parametrize("name", [
    "已证实人员浪费导致亏损999万元，必须裁员",
    "项目付款率120%，已确认超预算风险",
])
@pytest.mark.parametrize("registered_label", [None, "医疗收入", "医疗收入" * 100])
def test_unproven_supplemental_title_cannot_become_a_planned_conclusion(kind, name, registered_label):
    import json

    cards = project_analysis_findings(
        "analysis_001", facts(), {"analysisId": "analysis_001", "findings": [
            {"name": name, "kind": kind, "metricCodes": ["income"]},
        ]}, ({"code": "income", "description": registered_label},) if registered_label else (),
        snapshot_hash="b" * 64, citation_ids=("citation_001",),
        supplemental_file_path="evidence.json", supplemental_file_sha256="c" * 64,
    )
    from smart_reporting.reporting.hospital_operation.findings import FindingGraph

    graph = FindingGraph(snapshotHash="b" * 64, findings=cards)
    planning = build_narrative_planning_context(graph, "分析经营情况")
    fallback = build_fallback_narrative_candidate(graph, "报告")
    assert cards[0].evidence_level == "evidence_missing"
    assert name not in json.dumps(planning, ensure_ascii=False)
    assert name not in fallback.model_dump_json()
    if registered_label:
        assert "医疗收入" in cards[0].title
    assert cards[0].title.endswith("证据待核对")
    assert cards[0].source_refs[0].pointer == "/findings/0"


def test_supplemental_usage_filter_preserves_original_source_identity_and_indices():
    result = project_analysis_findings(
        "analysis_001", facts(), {
            "analysisId": "analysis_001", "findings": [
                {"name": "已删指标", "metricCodes": ["discharges_non"], "value": 999},
                {"name": "其他用途", "metricCodes": ["budget_income"], "value": 888},
                {"name": "收入补证", "metricCodes": ["income"], "value": 100},
            ],
        }, snapshot_hash="b" * 64, citation_ids=("citation_001",),
        supplemental_file_path="evidence.json", supplemental_file_sha256="c" * 64,
        metric_scope={"allowedMetricCodes": ["income"], "allowedFieldRefs": ["source.db.table.income"]},
    )
    supplemental = [card for card in result if card.source_refs[0].path == "evidence.json"]
    assert len(supplemental) == 1
    assert supplemental[0].source_refs[0].pointer == "/findings/2"
    assert supplemental[0].source_refs[0].file_sha256 == "c" * 64
    assert supplemental[0].evidence_level == "evidence_missing"
    assert supplemental[0].limitations
    assert any("findings/0" in issue for card in result for issue in card.limitations)
    assert all("discharges_non" not in card.metric_codes for card in result)


def test_file_registration_does_not_verify_arbitrary_supplemental_values():
    result = project_analysis_findings(
        "analysis_001", facts(), {"analysisId": "analysis_001", "findings": [
            {"name": "任意补证", "metricCodes": ["income"], "value": 999},
        ]}, snapshot_hash="b" * 64, citation_ids=("citation_001",),
        supplemental_file_path="evidence.json", supplemental_file_sha256="c" * 64,
    )
    assert result[0].evidence_level == "evidence_missing"


def test_many_rejected_supplements_and_full_warning_budget_remain_soft_gaps():
    for findings, scope in [
        ([{"metricCodes": ["deleted"]}] * 500, {"allowedMetricCodes": []}),
        ([{"metricCodes": ["income"]}], {"allowedMetricCodes": ["income"]}),
    ]:
        cards = project_analysis_findings(
            "analysis_001", facts(), {"analysisId": "analysis_001", "findings": findings,
                                      "warnings": [f"业务限制{i}" for i in range(100)]},
            snapshot_hash="b" * 64, citation_ids=("citation_001",),
            supplemental_file_path="evidence.json", supplemental_file_sha256="c" * 64,
            metric_scope=scope,
        )
        assert cards and all(card.evidence_level == "evidence_missing" for card in cards)
        assert all(len(card.limitations) <= 100 for card in cards)


def test_projection_creates_trend_finding_from_period_values():
    result = project_analysis_findings("analysis_001", facts(metrics=[{
        "datasetId": "dataset-abc123", "datasetSha256": "a" * 64, "periodRoles": ["current"],
        "field": "income", "fieldRef": "income", "aggregation": "sum", "formula": "sum(income)",
        "total": 20, "missingCount": 0, "zeroCount": 0, "negativeCount": 0,
        "periodValues": [{"period": "2025-01", "value": 10}, {"period": "2025-02", "value": 20}],
    }]), None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    assert any(item.kind == "trend" for item in result)


def test_projection_treats_scalar_grain_as_one_dimension():
    result = project_analysis_findings("analysis_001", {
        "analysisId": "analysis_001", "metrics": [{
        "datasetId": "dataset-abc123", "datasetSha256": "a" * 64,
        "periodRoles": ["current"], "field": "income", "fieldRef": "income",
        "aggregation": "sum", "formula": "sum(income)", "total": 10,
        "periodValues": [{"period": "2025-01", "value": 10}, {"period": "2025-02", "value": 20}],
        "grain": "stlevel_analytic_unit",
        }], "comparisons": [], "derivedMetrics": [], "reconciliations": [],
        "correlations": {}, "correlationDetails": [],
    }, None, snapshot_hash="b" * 64, citation_ids=("citation_001",))
    trend = next(item for item in result if item.kind == "trend")
    assert trend.grain == ("stlevel_analytic_unit",)


@pytest.fixture(params=["fact", "supplemental", "attribution"])
def grain_graph(request):
    def build(grain):
        metric = {
            "factId": "fact-1111111111111111", "total": 100, "field": "income",
            "topGroups": [{"group": "A", "value": 60}, {"group": "B", "value": 40}],
        }
        evidence = None
        if request.param == "fact":
            metric.update(grain=grain, periodValues=[
                {"period": "2025-01", "value": 40}, {"period": "2025-02", "value": 60},
            ])
        else:
            evidence = {
                "analysisId": "analysis_001",
                "findings": [{
                    "name": "科室收入分解",
                    "kind": "attribution" if request.param == "attribution" else "impact",
                    "directDecomposition": True, "reconciliationCode": "income_by_department",
                    "sourceFactIds": [metric["factId"]], "grain": grain, "scope": {},
                    "total": 100,
                    "components": [{"name": "A", "value": 60}, {"name": "B", "value": 40}],
                }],
                "reconciliations": [{
                    "code": "income_by_department", "passed": True,
                    "grain": grain, "scope": {}, "leftTotal": 100, "rightTotal": 100,
                }],
            }
        return build_finding_graph(
            [{"analysisId": "analysis_001", "metrics": [metric]}],
            {"analysis_001": evidence} if evidence else None, (),
            snapshot_hash="b" * 64, citation_ids_by_analysis={"analysis_001": ("citation_001",)},
            fact_file_sha256s={"analysis_001": "a" * 64},
            supplemental_file_paths={"analysis_001": "evidence/001.json"},
            supplemental_file_sha256s={"analysis_001": "c" * 64},
        )

    return build


@pytest.mark.parametrize("grain", [
    [None], [1], [{}], [True], [b"department"], ["科室", None], ("科室", {}),
], ids=["null", "number", "object", "boolean", "bytes", "mixed-list", "mixed-tuple"])
def test_projection_rejects_non_string_grain_before_freezing(grain_graph, grain):
    with pytest.raises(ValueError, match="grain"):
        grain_graph(grain)


@pytest.mark.parametrize(("grain", "expected"), [
    ("stlevel_analytic_unit", ("stlevel_analytic_unit",)),
    (["院区", "科室"], ("院区", "科室")),
    (("院区", "科室"), ("院区", "科室")),
    ([], ()),
    (None, ()),
], ids=["scalar-string", "string-list", "string-tuple", "empty", "missing"])
def test_projection_preserves_valid_grain_in_graph_and_planning(grain_graph, grain, expected):
    graph = grain_graph(grain)
    assert len(graph.findings) == 1
    assert graph.findings[0].grain == expected
    context = build_narrative_planning_context(graph, "经营报告")
    assert context["findings"][0]["grain"] == list(expected)


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
    selected = next(item for item in result if any(
        ref.path == "evidence/001.json" and ref.pointer == "/findings/0" for ref in item.source_refs
    ))
    assert selected.source_refs[0].path == "evidence/001.json"
    assert selected.source_refs[0].file_sha256 == "c" * 64
    assert selected.source_refs[0].pointer == "/findings/0"
    assert selected.citation_ids == ("citation_007",)
    assert selected.impact_value is None


@pytest.mark.parametrize("scope", ["开单收入", ["开单收入"], 1])
def test_supplemental_finding_with_non_mapping_scope_is_kept_without_crashing(scope):
    evidence = {
        "analysisId": "analysis_001", "datasetIds": ["dataset-abc123"],
        "findings": [{"name": "异常收入", "kind": "anomaly", "scope": scope}],
        "reconciliations": [], "warnings": [],
    }
    result = project_analysis_findings(
        "analysis_001", facts(), evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_007",),
        supplemental_file_path="evidence/001.json", supplemental_file_sha256="c" * 64,
    )
    selected = next(item for item in result if any(
        ref.path == "evidence/001.json" and ref.pointer == "/findings/0" for ref in item.source_refs
    ))
    assert selected.scope == {}
    assert any("scope" in warning for warning in selected.limitations)
    assert selected.source_refs[0].pointer == "/findings/0"


def test_supplemental_projection_requires_frozen_file_identity():
    with pytest.raises(ValueError, match="身份"):
        project_analysis_findings(
            "analysis_001", facts(), {"findings": [{"name": "收入变化"}]},
            snapshot_hash="b" * 64, citation_ids=("citation_007",),
        )


@pytest.mark.parametrize("scope", [{"性质": "开单收入"}, "开单收入"])
def test_legacy_closed_totals_do_not_prove_complete_same_basis_attribution(scope):
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
            "periodRoles": ["current"], "grain": ["科室"], "scope": scope,
            "total": 100, "components": [{"name": "A", "value": 60}, {"name": "B", "value": 40}],
        }],
        "reconciliations": [{
            "name": "科室收入合计对账", "code": "income_by_department", "passed": True,
            "leftTotal": 100, "rightTotal": 100, "difference": 0,
            "grain": ["科室"], "scope": scope,
        }],
        "warnings": [],
    }
    result = project_analysis_findings(
        "analysis_001", authoritative, evidence, snapshot_hash="b" * 64,
        citation_ids=("citation_007",), supplemental_file_path="evidence/001.json",
        supplemental_file_sha256="c" * 64,
    )
    attribution = next(item for item in result if any(
        ref.path == "evidence/001.json" and ref.pointer == "/findings/0" for ref in item.source_refs
    ))
    assert attribution.grain == ("科室",)
    assert attribution.evidence_level == "evidence_missing"
    if isinstance(scope, dict):
        assert attribution.scope == scope
    else:
        assert attribution.evidence_level != "direct_decomposition"
        assert attribution.scope == {}
        assert any("scope" in warning for warning in attribution.limitations)


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
    attribution = next(item for item in result if any(
        ref.path == "evidence/001.json" and ref.pointer == "/findings/0" for ref in item.source_refs
    ))
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
    attribution = next(item for item in result if any(
        ref.path == "evidence/001.json" and ref.pointer == "/findings/0" for ref in item.source_refs
    ))
    assert attribution.evidence_level != "direct_decomposition"


def test_finding_titles_use_the_main_display_name_without_aliases():
    # 回放：“收入金额，也称医疗收入金额趋势”进入章节名与核心结论。
    result = project_analysis_findings('analysis_001', facts(metrics=[{
        'datasetId': 'dataset-abc123', 'datasetSha256': 'a' * 64, 'periodRoles': ['current'],
        'field': 'income', 'fieldRef': 'income', 'displayName': '收入金额，也称医疗收入金额',
        'aggregation': 'sum', 'formula': 'sum(income)', 'total': 30,
        'missingCount': 0, 'zeroCount': 0, 'negativeCount': 0,
        'periodValues': [{'period': '2025-01', 'value': 10}, {'period': '2025-02', 'value': 20}],
    }]), None, snapshot_hash='b' * 64, citation_ids=('citation_001',))
    assert result[0].title == '收入金额趋势'
