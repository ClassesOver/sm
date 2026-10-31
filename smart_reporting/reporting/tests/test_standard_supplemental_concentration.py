"""集中度使用全量授权分组，异常口径以空值和软告警呈现。"""
from __future__ import annotations

import json

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisItemWorkflow,
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    run_standard_supplemental,
    standard_computation_candidates,
)


def _compute(body: str, total: float, *, periods=("2025-01",)):
    return run_standard_supplemental(
        analysis_id="analysis_001", dataset_ids=("current",),
        authorized_fields=("period", "department", "amount"),
        csv_content=("period,department,amount\n" + body).encode(),
        request=StandardSupplementalRequest(
            operation="group_concentration", datasetId="current", outputName="concentration",
            measureField="amount", measureUnit="元", dimensionField="department",
            periodField="period", currentPeriods=periods, parentTotal=total,
        ),
    )


@pytest.mark.parametrize("body,total,cr5,hhi,top5,count", [
    ("2025-01,A,60\n2025-01,B,40\n", 100, 1, .52, 100, 2),
    ("2025-01,A,100\n", 100, 1, 1, 100, 1),
    ("".join(f"2025-01,{name},100\n" for name in "FEDCBA"), 600, 5/6, 1/6, 500, 6),
    ("2025-01,A,80\n2025-01,A,-20\n2025-01,B,40\n2024-01,A,999\n", 100, 1, .52, 100, 2),
])
def test_concentration_uses_complete_net_groups_and_fraction_scale(body, total, cr5, hhi, top5, count):
    payload = _compute(body, total)
    finding = payload["findings"][0]
    assert finding["columns"] == [
        "period", "cr5", "hhi", "top5_amount", "total_amount", "group_count", "missing_amount",
    ]
    assert finding["rows"][0][0] == "2025-01"
    assert finding["rows"][0][1:] == pytest.approx([cr5, hhi, top5, total, count, 0])
    assert finding["columnMeta"]["cr5"] == {"unit": "%", "isPercent": False}
    assert finding["columnMeta"]["hhi"]["unit"] == "0—1"
    assert payload["warnings"] == []
    assert all(check["passed"] for check in payload["reconciliations"])
    validate_supplemental_evidence(
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(),
        {"analysisId": "analysis_001", "datasetIds": ["current"]},
    )
    if count == 6:
        assert finding["top5Units"] == ["A", "B", "C", "D", "E"]


def test_negative_net_group_keeps_cr5_but_never_reports_classical_hhi():
    payload = _compute("2025-01,A,110\n2025-01,B,-10\n", 100)
    assert payload["findings"][0]["rows"][0][1:3] == [1, None]
    assert any("负" in warning and "HHI" in warning for warning in payload["warnings"])


@pytest.mark.parametrize("body,total,reason", [
    ("2025-01,A,0\n", 0, "总额"),
    ("2025-01,A,-10\n", -10, "总额"),
    ("2025-01,A,60\n2025-01,,40\n", 100, "归属"),
    ("2025-01,A,60\n2025-01,  ,40\n", 100, "归属"),
    ("2025-01,A,60\n", 100, "对账"),
    ("2025-01,A,100\n2025-01,B,invalid\n", 100, "无效"),
    ("", 0, "数据"),
])
def test_incomplete_or_invalid_population_returns_null_with_soft_warning(body, total, reason):
    payload = _compute(body, total)
    assert payload["findings"][0]["rows"][0][1:3] == [None, None]
    assert any(reason in warning for warning in payload["warnings"])
    json.dumps(payload, allow_nan=False)
    if reason == "归属":
        assert payload["findings"][0]["rows"][0][-2:] == [1, 40]


def test_missing_month_is_not_treated_as_zero():
    payload = _compute("2025-01,A,100\n", 100, periods=("2025-01", "2025-02"))
    assert payload["findings"][0]["rows"][0][1:3] == [None, None]
    assert any("期间" in warning for warning in payload["warnings"])


def test_multi_month_concentration_aggregates_groups_before_squaring_shares():
    payload = _compute(
        "2025-01,A,100\n2025-02,B,100\n", 200, periods=("2025-01", "2025-02"),
    )
    assert payload["findings"][0]["rows"] == [["2025-01、2025-02", 1, .5, 200, 200, 2, 0]]
    assert payload["warnings"] == []


def test_concentration_candidate_routes_with_explicit_output_contract_and_authorization():
    state = _standard_analysis_state()
    candidate = next(item for item in standard_computation_candidates(state.facts, state.instruction["datasets"])
                     if item["standardComputation"]["operation"] == "group_concentration")
    requirement = state.decision.coding_requirements[0].model_copy(update={
        "standard_computation": None, "standard_candidate_id": candidate["candidateId"],
        "required_columns": ("cr5", "hhi", "top5_amount", "total_amount"),
    })
    state.decision = state.decision.model_copy(update={"coding_requirements": (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.operation == "group_concentration"
    assert AnalysisItemWorkflow._standard_output_issues(state.decision, [candidate]) == []
    requirement = requirement.model_copy(update={"fields": ("income", "period")})
    state.decision = state.decision.model_copy(update={"coding_requirements": (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize("fault", [None, "hash", "nonadditive", "fields"])
def test_explicit_concentration_routes_without_candidate_but_requires_frozen_authorized_inputs(fault):
    state = _standard_analysis_state()
    spec = StandardSupplementalSpec(
        operation="group_concentration", measureField="income", dimensionField="department",
        periodField="period", currentPeriods=("2026-01",), parentFactId=state.facts.metrics[0].fact_id,
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={
        "standard_computation": spec, "required_columns": ("cr5", "hhi"),
    })
    if fault == "hash":
        state.facts.metrics[0].dataset_sha256 = "b" * 64
    elif fault == "nonadditive":
        state.facts.metrics[0].period_aggregation = "last"
    elif fault == "fields":
        requirement = requirement.model_copy(update={"fields": ("income", "period")})
    state.decision = state.decision.model_copy(update={"coding_requirements": (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == ((spec,) if fault is None else ())
