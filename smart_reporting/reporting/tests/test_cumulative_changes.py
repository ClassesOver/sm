"""Cumulative snapshots prove signed level differences, never monthly flows."""

import hashlib
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicMetricFact,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.profile.models import EffectiveMetric, MetricPatch
from smart_reporting.reporting.trace.cumulative_changes import (
    cumulative_change_template,
    registered_cumulative_changes,
)
from smart_reporting.reporting.trace.fact_index import metric_fact_identity

from .test_deterministic_analysis import analysis, context, semantic

CUMULATIVE_POLICY = {
    "version": "1",
    "reset": "calendar_year_zero",
    "observation": "closed_month_end",
    "changes": "signed_snapshot_delta",
}


@pytest.mark.parametrize("aggregation", ["count", "count_distinct", "average", "ratio"])
def test_profile_cumulative_policy_cannot_be_attached_to_non_sum_metric(aggregation):
    with pytest.raises(ValidationError):
        EffectiveMetric.model_validate({
            "code": "cumulative", "kind": "amount", "aggregation": aggregation,
            "fieldRef": semantic("amount")["fieldRef"], "cumulativePolicy": CUMULATIVE_POLICY,
        })


def test_absent_profile_policy_preserves_wire_and_frozen_identity():
    declaration = {"code": "amount", "kind": "amount", "aggregation": "sum",
                   "fieldRef": semantic("amount")["fieldRef"]}
    metric = EffectiveMetric.model_validate(declaration)
    assert "cumulativePolicy" not in metric.model_dump(mode="json", by_alias=True)
    assert "cumulativePolicy" not in MetricPatch(code="amount").model_dump(mode="json", by_alias=True)
    frozen = DeterministicMetricFact.model_validate(cumulative_entry())
    ordinary = frozen.model_copy(update={"cumulative_policy": None})
    assert metric_fact_identity(frozen) != metric_fact_identity(ordinary)
    assert "cumulativePolicy" not in ordinary.model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize("fault", ["additive", "profile", "ambiguous", "policy"])
def test_invalid_cumulative_configuration_preserves_unrelated_metrics(fault):
    raw = b"month,department,amount,visits\n2025-01,A,10,2\n2025-02,A,25,3\n"
    declaration = {**semantic("amount", scope={"department": "A"}, unit="元"),
                   "additiveAcross": ["month", "department"] if fault == "additive" else ["department"]}
    other = semantic("visits", scope={"department": "A"}, unit="人次")
    definitions = [{"code": "cumulative", "kind": "amount", "aggregation": "sum",
                    "fieldRef": declaration["fieldRef"],
                    "cumulativePolicy": {**CUMULATIVE_POLICY, **({"reset": "never"} if fault == "policy" else {})}},
                   {"code": "visits", "kind": "count", "aggregation": "sum", "fieldRef": other["fieldRef"]}]
    if fault == "ambiguous":
        definitions.append({"code": "amount_alias", "aggregation": "sum", "fieldRef": declaration["fieldRef"]})
    ctx = context("current", fields=("month", "department", "amount", "visits"),
                  semantics=(declaration, other), sha256=hashlib.sha256(raw).hexdigest()).model_copy(
                      update={"period_granularities": {"month": "month"}})
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")), (("current", raw, ctx, ("current",)),),
        profile_metrics=tuple(definitions), profile_hash=None if fault == "profile" else "a" * 64,
    )
    assert [item.field for item in bundle.metrics] == ["visits"]
    assert bundle.metrics[0].total == 5
    assert any("累计快照策略" in warning for warning in bundle.warnings)


def cumulative_document(
    values=(1000, 10, 25), *, months=("2024-12", "2025-01", "2025-02"), unit="元"
):
    raw = (
        "month,department,amount\n"
        + "".join(f"{month},A,{value}\n" for month, value in zip(months, values, strict=True))
    ).encode()
    declaration = {
        **semantic("amount", scope={"department": "A"}, unit=unit),
        "additiveAcross": ["department"],
    }
    ctx = context(
        "current", semantics=(declaration,), sha256=hashlib.sha256(raw).hexdigest()
    ).model_copy(update={"period_granularities": {"month": "month"}})
    definitions = (
        {
            "code": "cumulative_amount",
            "kind": "amount",
            "aggregation": "sum",
            "fieldRef": declaration["fieldRef"],
            "cumulativePolicy": CUMULATIVE_POLICY,
        },
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(), (("current", raw, ctx, ("current",)),),
        profile_metrics=definitions, profile_hash="a" * 64,
    )
    assert len(bundle.metrics) == 1, bundle.warnings
    return json.loads(bundle.model_dump_json(by_alias=True))


def cumulative_entry(*args, **kwargs):
    return cumulative_document(*args, **kwargs)["metrics"][0]


def test_calendar_reset_does_not_subtract_december_snapshot():
    entry = cumulative_entry()
    assert entry["cumulativePolicy"] == CUMULATIVE_POLICY
    assert entry["total"] == 25 and entry["periodAggregation"] == "last"
    proofs, reasons = registered_cumulative_changes(entry, profile_hash="a" * 64)
    assert not reasons
    assert set(proofs) == {"cumulativeChanges.1", "cumulativeChanges.2"}
    january, february = proofs.values()
    assert january == {
        "value": Decimal(10), "current_period": "2025-01", "baseline_period": None,
        "baseline_value": Decimal(0), "current_value": Decimal(10), "reset": True, "unit": "元",
    }
    assert february["value"] == Decimal(15)
    assert february["baseline_period"] == "2025-01" and not february["reset"]


def test_january_only_has_explicit_zero_baseline():
    proofs, reasons = registered_cumulative_changes(cumulative_entry((10,), months=("2025-01",)))
    assert not reasons and proofs["cumulativeChanges.0"]["value"] == 10
    assert proofs["cumulativeChanges.0"]["reset"]


def test_window_starting_after_january_never_fills_missing_baseline_with_zero():
    entry = cumulative_entry((50, 70), months=("2025-04", "2025-05"))
    proofs, reasons = registered_cumulative_changes(entry)
    assert not reasons and set(proofs) == {"cumulativeChanges.1"}
    assert proofs["cumulativeChanges.1"]["value"] == 20
    assert proofs["cumulativeChanges.1"]["baseline_period"] == "2025-04"
    single = cumulative_entry((50,), months=("2025-04",))
    assert registered_cumulative_changes(single) == ({}, ())


def test_signed_snapshot_corrections_are_not_clamped_or_called_flow():
    entry = cumulative_entry((30, 20), months=("2025-01", "2025-02"))
    proofs, reasons = registered_cumulative_changes(entry)
    assert not reasons
    proof = proofs["cumulativeChanges.1"]
    assert proof["value"] == -10
    text = cumulative_change_template(proof, "范围（department=A），指标累计收入", "-10.00元")
    assert "2025-02月末" in text and "以2025-01月末累计快照为基线" in text
    assert "累计快照变化为-10.00元" in text
    assert text.endswith("（累计快照变化，可能包含追溯调整，不等同当期业务流量）")
    january = cumulative_change_template(proofs["cumulativeChanges.0"], "累计收入", "30.00元")
    assert "按自然年重置零基线" in january and "上年末" not in january


@pytest.mark.parametrize("unit", ["元", "万元", "亿元", "人次", "万人次", "人", "次", "床日", "床"])
def test_confirmed_scalar_units_are_preserved_without_guessing_a_flow_unit(unit):
    entry = cumulative_entry(unit=unit)
    proofs, reasons = registered_cumulative_changes(entry)
    assert not reasons and all(proof["unit"] == unit for proof in proofs.values())


@pytest.mark.parametrize("key,value,reason", [
    ("factId", None, "cumulative_registration_identity_unproven"),
    ("profileHash", None, "cumulative_registration_identity_unproven"),
    ("cumulativePolicy", None, "cumulative_policy_unproven"),
    ("scope", {}, "cumulative_context_unproven"),
    ("unit", None, "cumulative_context_unproven"),
    ("unit", "%", "cumulative_context_unproven"),
    ("unit", "元/人次", "cumulative_context_unproven"),
    ("unit", "吨", "cumulative_context_unproven"),
    ("aggregation", "average", "cumulative_measure_semantics_unproven"),
    ("periodAggregation", "sum", "cumulative_measure_semantics_unproven"),
    ("periodGranularity", "day", "cumulative_measure_semantics_unproven"),
    ("periodField", None, "cumulative_measure_semantics_unproven"),
    ("missingCount", 1, "cumulative_completeness_unproven"),
    ("seriesMissingCount", 1, "cumulative_completeness_unproven"),
    ("seriesMissingCount", None, "cumulative_completeness_unproven"),
    ("periodMissingCount", 1, "cumulative_completeness_unproven"),
    ("periodMissingCount", None, "cumulative_completeness_unproven"),
    ("warnings", ["unconfirmed snapshot"], "cumulative_completeness_unproven"),
    ("periodValues", [], "cumulative_monthly_window_required"),
    ("periodStart", "2024-11", "cumulative_window_identity_mismatch"),
    ("periodEnd", "2025-03", "cumulative_window_identity_mismatch"),
    ("total", 20, "cumulative_window_identity_mismatch"),
])
def test_unknown_or_inconsistent_input_never_proves_snapshot_change(key, value, reason):
    entry = cumulative_entry()
    entry[key] = value
    assert registered_cumulative_changes(entry) == ({}, (reason,))


def test_expected_profile_and_merged_warnings_are_checked():
    entry = cumulative_entry()
    assert registered_cumulative_changes(entry, profile_hash="b" * 64) == (
        {}, ("cumulative_registration_identity_unproven",)
    )
    assert registered_cumulative_changes(entry, warnings=("incomplete source",)) == (
        {}, ("cumulative_completeness_unproven",)
    )


@pytest.mark.parametrize("months", [
    ("2025-01", "2025-03", "2025-04"),
    ("2025-01", "2025-01", "2025-02"),
    ("2025-01", "2025-03", "2025-02"),
])
def test_gap_duplicate_and_reordered_periods_are_not_complete_premises(months):
    entry = cumulative_entry()
    entry["periodValues"] = [
        {"period": month, "value": value} for month, value in zip(months, (10, 20, 30), strict=True)
    ]
    entry.update(periodStart=months[0], periodEnd=months[-1], total=30)
    assert registered_cumulative_changes(entry) == ({}, ("cumulative_window_incomplete",))


@pytest.mark.parametrize("period", ["2025-02-15", "2025", "invalid"])
def test_nonmonthly_observation_labels_do_not_inherit_closed_month_end_policy(period):
    entry = cumulative_entry()
    entry["periodValues"][1]["period"] = period
    assert registered_cumulative_changes(entry) == ({}, ("cumulative_monthly_window_required",))


@pytest.mark.parametrize("periods", [
    ("2024年12月", "2025年1月", "2025年2月"),
    ("2024-12-01", "2025-01-01", "2025-02-01"),
])
def test_registered_month_aliases_canonicalize_without_changing_the_observation_policy(periods):
    entry = cumulative_entry()
    for item, label in zip(entry["periodValues"], periods, strict=True):
        item["period"] = label
    entry.update(periodStart=periods[0], periodEnd=periods[-1])
    proofs, reasons = registered_cumulative_changes(entry)
    assert not reasons and proofs["cumulativeChanges.1"]["current_period"] == "2025-01"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_observations_are_unknown(bad):
    entry = cumulative_entry()
    entry["periodValues"][1]["value"] = bad
    proofs, reasons = registered_cumulative_changes(entry)
    assert not proofs and reasons


def test_snapshot_delta_overflow_is_unknown():
    entry = cumulative_entry()
    entry["periodValues"] = [
        {"period": "2025-01", "value": -1.7e308},
        {"period": "2025-02", "value": 1.7e308},
    ]
    entry.update(periodStart="2025-01", periodEnd="2025-02", total=1.7e308)
    assert registered_cumulative_changes(entry) == ({}, ("cumulative_difference_out_of_range",))


def test_decimal_difference_does_not_round_before_subtraction():
    entry = cumulative_entry((0.1, 0.3), months=("2025-01", "2025-02"))
    proofs, reasons = registered_cumulative_changes(entry)
    assert not reasons and proofs["cumulativeChanges.1"]["value"] == Decimal("0.2")


@pytest.mark.parametrize("patch", [
    {"reset": "fiscal_year_zero"},
    {"reset": "never"},
    {"observation": "latest_open_month"},
    {"changes": "monthly_flow"},
    {"version": "2"},
    {"unknownPremise": True},
])
def test_unsupported_policy_is_not_treated_as_calendar_year_reset(patch):
    entry = cumulative_entry()
    entry["cumulativePolicy"].update(patch)
    assert registered_cumulative_changes(entry) == ({}, ("cumulative_input_invalid",))
