from __future__ import annotations

import json

import pytest

from scripts.benchmark_standard_supplemental import summarize_timings
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisCodingRequirement,
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    run_standard_supplemental,
)

CSV = (
    "period,department,amount\n"
    "2025-01,内科,60\n"
    "2025-01,外科,40\n"
    "2025-02,内科,70\n"
    "2025-02,外科,30\n"
    "2024-01,内科,50\n"
    "2024-01,外科,50\n"
).encode()


def request(operation: str = "group_summary", *, parent_total: float = 200.0) -> StandardSupplementalRequest:
    return StandardSupplementalRequest(
        operation=operation,
        dataset_id="dataset-current",
        output_name="standard_result",
        measure_field="amount",
        dimension_field="department",
        period_field="period",
        current_periods=("2025-01", "2025-02"),
        baseline_periods=("2024-01",),
        parent_total=parent_total,
        baseline_parent_total=100.0,
    )


def test_group_summary_emits_complete_population_rank_share_and_reconciliation():
    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=CSV,
        request=request(),
    )

    finding = payload["findings"][0]
    assert finding["name"] == "standard_result"
    assert finding["columns"] == ["department", "value", "rank", "share"]
    assert finding["rows"] == [["内科", 130.0, 1, 0.65], ["外科", 70.0, 2, 0.35]]
    assert payload["reconciliations"] == [
        {"name": "standard_result_total", "passed": True, "left": 200.0, "right": 200.0}
    ]
    validated = validate_supplemental_evidence(
        json.dumps(payload, ensure_ascii=False).encode(),
        {"analysisId": "analysis_001", "datasetIds": ["dataset-current"]},
    )
    assert validated.findings[0]["rows"] == finding["rows"]


@pytest.mark.parametrize('fault', [None, 'dataset', 'fields', 'scope'])
def test_cross_dataset_comparison_keeps_inputs_separate_and_checks_authorization(fault):
    comparison = StandardSupplementalRequest(
        operation='period_comparison', datasetId='dataset-current', baselineDatasetId='dataset-prior',
        outputName='comparison', measureField='amount', dimensionField='department', periodField='period',
        currentPeriods=['2025-01'], baselinePeriods=['2024-01'], parentTotal=100, baselineParentTotal=50,
        scope={'income_nature': '开单收入'}, queryBoundScopeFields=['income_nature'],
        baselineQueryBoundScopeFields=['income_nature'],
    )
    kwargs = dict(
        analysis_id='analysis_001', dataset_ids=['dataset-current', 'dataset-prior'],
        authorized_fields=['period', 'department', 'amount'], request=comparison,
        csv_content=b'period,department,amount\n2025-01,A,100\n2024-01,A,invalid\n',
        baseline_csv_content=b'period,department,amount\n2024-01,A,50\n2025-01,A,invalid\n',
        baseline_authorized_fields=['period', 'department', 'amount'],
        authorized_query_scope={'income_nature': '开单收入'},
        baseline_authorized_query_scope={'income_nature': '开单收入'},
    )
    if fault == 'dataset':
        kwargs['dataset_ids'] = ['dataset-current']
    elif fault == 'fields':
        kwargs['baseline_authorized_fields'] = ['period', 'amount']
    elif fault == 'scope':
        kwargs['baseline_authorized_query_scope'] = {}
    if fault is not None:
        with pytest.raises(ValueError, match='未授权'):
            run_standard_supplemental(**kwargs)
        return
    result = run_standard_supplemental(**kwargs)
    assert result['findings'][0]['rows'] == [['A', 100.0, 50.0, 50.0, 1.0, 1.0]]
    assert all(item['passed'] for item in result['reconciliations'])
    assert result['warnings'] == []


def test_group_ratio_emits_operands_difference_ratio_and_dual_reconciliation():
    csv = (
        b"period,department,actual,budget\n"
        b"2025-01,A,80,10\n"
        b"2025-01,B,0,0\n"
    )
    ratio_request = StandardSupplementalRequest(
        operation="group_ratio",
        datasetId="dataset-current",
        outputName="department_completion",
        measureField="actual",
        denominatorField="budget",
        measureUnit="元",
        dimensionField="department",
        periodField="period",
        currentPeriods=("2025-01",),
        parentTotal=80,
        denominatorParentTotal=10,
        denominatorScale=10,
        ratioFactId="fact-ratio",
    )

    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "actual", "budget"),
        csv_content=csv,
        request=ratio_request,
    )

    finding = payload["findings"][0]
    assert finding["columns"] == [
        "department", "numerator", "denominator", "difference", "ratio",
    ]
    assert finding["rows"] == [
        ["A", 80.0, 100.0, -20.0, 0.8],
        ["B", 0.0, 0.0, 0.0, None],
    ]
    assert finding["columnMeta"] == {
        "ratio": {"unit": "%", "isPercent": False},
        "numerator": {"unit": "元"},
        "denominator": {"unit": "元"},
        "difference": {"unit": "元"},
    }
    assert payload["reconciliations"] == [
        {"name": "department_completion_numerator_total", "passed": True, "left": 80.0, "right": 80.0},
        {"name": "department_completion_denominator_total", "passed": True, "left": 10.0, "right": 10.0},
    ]
    assert any("分母为零" in warning for warning in payload["warnings"])


def test_group_ratio_keeps_one_sided_group_unknown_instead_of_zero():
    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "actual", "budget"),
        csv_content=b"period,department,actual,budget\n2025-01,A,,10\n",
        request=StandardSupplementalRequest(
            operation="group_ratio", datasetId="dataset-current", outputName="completion",
            measureField="actual", denominatorField="budget", dimensionField="department",
            periodField="period", currentPeriods=("2025-01",), parentTotal=0,
            denominatorParentTotal=10, denominatorScale=1, ratioFactId="fact-ratio",
        ),
    )

    assert payload["findings"][0]["rows"] == [["A", None, 10.0, None, None]]
    assert any("缺少分子" in warning for warning in payload["warnings"])


@pytest.mark.parametrize("operation", ["group_summary", "period_comparison"])
@pytest.mark.parametrize("values", [
    ("10000000000000000", "1", "-10000000000000000"),
    ("10000000000000000", "-10000000000000000", "1"),
])
def test_large_offsets_keep_same_exact_group_totals_as_frozen_facts(operation, values):
    csv = "period,department,amount\n" + "".join(
        f"2025-01,内科,{value}\n" for value in values
    ) + "2024-01,内科,2\n"
    payload = run_standard_supplemental(
        analysis_id="analysis_001", dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=csv.encode(),
        request=request(operation, parent_total=1.0).model_copy(
            update={"baseline_parent_total": 2.0}
        ),
    )

    row = payload["findings"][0]["rows"][0]
    if operation == "group_summary":
        assert row == ["内科", 1.0, 1, 1.0]
    else:
        assert row == ["内科", 1.0, 2.0, -1.0, -0.5, 1.0]
    assert all(item["passed"] for item in payload["reconciliations"])


def test_comparison_keeps_missing_baseline_group_as_warning_and_null_rate():
    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=CSV.replace("2024-01,外科,50\n".encode(), b""),
        request=request("period_comparison"),
    )

    finding = payload["findings"][0]
    assert finding["columns"] == ["department", "current", "baseline", "change", "changeRate", "contribution"]
    assert finding["rows"] == [["内科", 130.0, 50.0, 80.0, 1.6, pytest.approx(80 / 150)],
                               ["外科", 70.0, None, None, None, None]]
    assert any("外科" in warning for warning in payload["warnings"])
    assert payload["reconciliations"][0]["passed"] is True
    assert payload["reconciliations"][1]["passed"] is False
    assert any("父指标" in warning for warning in payload["warnings"])


def test_comparison_keeps_baseline_only_group_unknown_instead_of_zero():
    payload = run_standard_supplemental(
        analysis_id="analysis_001", dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content="period,department,amount\n2024-01,内科,50\n".encode(),
        request=request("period_comparison", parent_total=0.0),
    )
    assert payload["findings"][0]["rows"] == [["内科", None, 50.0, None, None, None]]
    assert any("缺少本期" in warning for warning in payload["warnings"])


def test_comparison_rejects_overlapping_period_aliases():
    with pytest.raises(ValueError, match="重叠"):
        StandardSupplementalRequest.model_validate({
            **request("period_comparison").model_dump(by_alias=True),
            "currentPeriods": ["2025-01"], "baselinePeriods": ["2025/1"],
        })


def test_zero_total_keeps_shares_null_and_emits_soft_warning():
    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content="period,department,amount\n2025-01,内科,0\n2025-01,外科,0\n".encode(),
        request=request(parent_total=0.0),
    )

    assert all(row[3] is None for row in payload["findings"][0]["rows"])
    assert any("分母" in warning for warning in payload["warnings"])
    assert payload["reconciliations"][0]["passed"] is True


@pytest.mark.parametrize("label", ["2025-1", "2025/01", "202501", "2025-01-01"])
def test_period_aliases_use_frozen_month_granularity(label):
    payload = run_standard_supplemental(
        analysis_id="analysis_001", dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=f"period,department,amount\n{label},内科,100\n".encode(),
        request=StandardSupplementalRequest.model_validate({
            **request(parent_total=100.0).model_dump(by_alias=True),
            "currentPeriods": ["2025-01"], "periodGranularity": "month",
        }),
    )
    assert payload["findings"][0]["rows"] == [["内科", 100.0, 1, 1.0]]
    assert payload["reconciliations"][0]["passed"] is True


def test_unauthorized_request_is_rejected_without_fallback_data_access():
    with pytest.raises(ValueError, match="未授权"):
        run_standard_supplemental(
            analysis_id="analysis_001",
            dataset_ids=("dataset-current",),
            authorized_fields=("period", "department"),
            csv_content=CSV,
            request=request(),
        )


def test_group_summary_requires_independent_parent_total():
    with pytest.raises(ValueError, match="parentTotal"):
        StandardSupplementalRequest(
            operation="group_summary",
            datasetId="dataset-current",
            outputName="standard_result",
            measureField="amount",
            dimensionField="department",
            periodField="period",
            currentPeriods=("2025-01",),
        )


def test_group_summary_keeps_missing_dimension_amount_in_null_group():
    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=b"period,department,amount\n2025-01,,10\n2025-01,\xe5\x86\x85\xe7\xa7\x91,90\n",
        request=request(parent_total=100.0),
    )

    assert payload["findings"][0]["rows"] == [
        ["内科", 90.0, 1, 0.9],
        [None, 10.0, 2, 0.1],
    ]
    assert payload["reconciliations"][0]["passed"] is True
    assert any("分组为空" in item for item in payload["warnings"])


def test_group_summary_applies_frozen_parent_scope():
    scoped_request = request(parent_total=60.0).model_copy(update={"scope": {"area": "north"}})
    csv = b"period,department,amount,area\n2025-01,A,60,north\n2025-01,B,40,south\n"

    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount", "area"),
        csv_content=csv,
        request=scoped_request,
    )

    assert payload["findings"][0]["rows"] == [["A", 60.0, 1, 1.0]]
    assert payload["reconciliations"][0]["passed"] is True


def test_group_summary_accepts_server_verified_query_bound_scope_without_csv_column():
    scoped_request = request(parent_total=100.0).model_copy(update={
        "scope": {"income_nature": "开单收入"},
        "query_bound_scope_fields": ("income_nature",),
        "current_periods": ("2025-01",),
    })
    csv = b"period,department,amount\n2025-01,A,60\n2025-01,B,40\n"

    payload = run_standard_supplemental(
        analysis_id="analysis_001",
        dataset_ids=("dataset-current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=csv,
        request=scoped_request,
        authorized_query_scope={"income_nature": "开单收入"},
    )

    assert payload["findings"][0]["scope"] == {"income_nature": "开单收入"}
    assert payload["findings"][0]["rows"] == [
        ["A", 60.0, 1, 0.6], ["B", 40.0, 2, 0.4],
    ]
    assert payload["reconciliations"][0]["passed"] is True


def test_query_bound_scope_cannot_be_self_authorized_by_request():
    scoped_request = request(parent_total=100.0).model_copy(update={
        "scope": {"income_nature": "开单收入"},
        "query_bound_scope_fields": ("income_nature",),
        "current_periods": ("2025-01",),
    })

    with pytest.raises(ValueError, match="查询固定范围"):
        run_standard_supplemental(
            analysis_id="analysis_001", dataset_ids=("dataset-current",),
            authorized_fields=("period", "department", "amount"),
            csv_content=b"period,department,amount\n2025-01,A,100\n",
            request=scoped_request,
        )


def test_summarize_timings_reports_percentiles_without_claiming_model_speedup():
    summary = summarize_timings([1.0, 2.0, 3.0, 4.0])

    assert summary == {"count": 4, "meanSeconds": 2.5, "p50Seconds": 2.5, "p95Seconds": 4.0}


def test_structured_spec_requires_all_computation_fields_in_requirement():
    spec = StandardSupplementalSpec.model_validate({
            "operation": "group_summary",
            "measureField": "amount",
            "dimensionField": "department",
            "periodField": "period",
            "currentPeriods": ["2025-01"],
            "parentFactId": "fact-parent",
        })
    with pytest.raises(ValueError, match="fields"):
        AnalysisCodingRequirement(
            datasetId="dataset-current", fields=("amount", "period"),
            calculation="部门汇总", outputName="department_summary",
            standardComputation=spec,
        )


def test_structured_spec_rejects_period_overlap():
    with pytest.raises(ValueError, match="期间不能重叠"):
        StandardSupplementalSpec.model_validate({
            "operation": "period_comparison",
            "measureField": "amount",
            "dimensionField": "department",
            "periodField": "period",
            "currentPeriods": ["2025-01"],
            "baselinePeriods": ["2025-01"],
            "parentFactId": "fact-current",
            "baselineParentFactId": "fact-baseline",
        })


def test_period_comparison_can_use_same_frozen_parent_fact():
    spec = StandardSupplementalSpec.model_validate({
        "operation": "period_comparison",
        "measureField": "amount",
        "dimensionField": "department",
        "periodField": "period",
        "currentPeriods": ["2025-01"],
        "baselinePeriods": ["2024-01"],
        "parentFactId": "fact-parent",
    })
    assert spec.baseline_parent_fact_id is None
