"""统计范围从已登记组织维度及完整CSV取值冻结，不从名称猜全院。"""

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import build_deterministic_analysis_bundle
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic


@pytest.mark.parametrize("organization", ["entity", "hospital", "company"])
def test_freezes_complete_singleton_registered_organization_without_changing_total(organization):
    ref = "dynamic_source.dynamic_db.dynamic_table."
    frame = f"month,department,{organization},amount\n2025-01,A,甲医院,10\n2025-02,B,甲医院,20\n".encode()
    bundle = build_deterministic_analysis_bundle(analysis(), ((
        "current", frame, context("current", fields=("month", "department", organization, "amount")), ("current",),
    ),), profile_dimensions=({"code": "entity", "kind": "organization", "fieldRefs": [ref + organization]},))
    assert bundle.metrics[0].scope == {organization: "甲医院"}
    assert bundle.metrics[0].total == 30
    assert bundle.metrics[0].period_values[0].value == 10


@pytest.mark.parametrize("values", ["甲医院\n乙医院", "甲医院\n", "甲医院\n "])
def test_incomplete_or_multiple_organizations_are_never_frozen_as_single_scope(values):
    first, second = values.split("\n")
    frame = f"month,department,entity,amount\n2025-01,A,{first},10\n2025-02,B,{second},20\n".encode()
    bundle = build_deterministic_analysis_bundle(analysis(), ((
        "current", frame, context("current", fields=("month", "department", "entity", "amount")), ("current",),
    ),), profile_dimensions=({"code": "entity", "kind": "organization",
                              "fieldRefs": ["dynamic_source.dynamic_db.dynamic_table.entity"]},))
    assert bundle.metrics[0].scope == {}
    assert bundle.metrics[0].total == 30


@pytest.mark.parametrize("dimension", [
    {"code": "entity", "kind": "category", "fieldRefs": ["dynamic_source.dynamic_db.dynamic_table.entity"]},
    {"code": "entity", "kind": "organization", "fieldRefs": ["other_source.db.table.entity"]},
])
def test_unregistered_or_other_table_organization_is_not_used(dimension):
    bundle = build_deterministic_analysis_bundle(analysis(), ((
        "current", "month,department,entity,amount\n2025-01,A,甲医院,10\n".encode(),
        context("current", fields=("month", "department", "entity", "amount")), ("current",),
    ),), profile_dimensions=(dimension,))
    assert bundle.metrics[0].scope == {}


def test_organization_scope_preserves_metric_exclusive_filter():
    bundle = build_deterministic_analysis_bundle(analysis(), ((
        "current", "month,department,entity,amount\n2025-01,A,甲医院,10\n2025-02,B,乙医院,20\n".encode(),
        context("current", fields=("month", "department", "entity", "amount"),
                semantics=(semantic("amount", scope={"department": "A"}),)), ("current",),
    ),), profile_dimensions=({"code": "entity", "kind": "organization",
                              "fieldRefs": ["dynamic_source.dynamic_db.dynamic_table.entity"]},))
    assert bundle.metrics[0].scope == {"department": "A", "entity": "甲医院"}
    assert bundle.metrics[0].total == 10


def test_observed_conflicting_organizations_do_not_become_a_scopeless_ratio():
    metrics = (
        {"code": "actual", "aggregation": "sum", "fieldRef": semantic("actual")["fieldRef"]},
        {"code": "budget", "aggregation": "sum", "fieldRef": semantic("budget")["fieldRef"]},
        {"code": "execution", "aggregation": "ratio", "numeratorMetric": "actual", "denominatorMetric": "budget"},
    )
    bundle = build_deterministic_analysis_bundle(analysis(fields=("actual", "budget")), tuple(
        (field, f"month,department,entity,{field}\n2025-01,A,{entity},{value}\n".encode(),
         context(field, fields=("month", "department", "entity", field), semantics=(semantic(field),)),
         ("current",))
        for field, entity, value in (("actual", "甲医院", 80), ("budget", "乙医院", 100))
    ), profile_metrics=metrics, profile_dimensions=({
        "code": "entity", "kind": "organization", "fieldRefs": ["dynamic_source.dynamic_db.dynamic_table.entity"],
    },))
    assert len(bundle.metrics) == 2
    assert bundle.derived_metrics == ()
    assert any("范围" in warning and "execution" in warning for warning in bundle.warnings)


def test_equal_amounts_in_different_organizations_never_pass_reconciliation():
    bundle = build_deterministic_analysis_bundle(analysis(fields=("actual", "ledger")), tuple(
        (field, f"month,department,entity,{field}\n2025-01,A,{entity},80\n".encode(),
         context(field, fields=("month", "department", "entity", field), semantics=(semantic(field, unit="元"),)),
         ("current",))
        for field, entity in (("actual", "甲医院"), ("ledger", "乙医院"))
    ), profile_metrics=tuple({"code": field, "aggregation": "sum", "fieldRef": semantic(field)["fieldRef"]}
                             for field in ("actual", "ledger")),
        profile_reconciliations=({"code": "ledger_check", "leftMetric": "actual", "rightMetric": "ledger",
                                 "grain": ["department"], "absoluteTolerance": 0, "relativeTolerance": 0},),
        profile_dimensions=({"code": "entity", "kind": "organization",
                             "fieldRefs": ["dynamic_source.dynamic_db.dynamic_table.entity"]},))
    assert len(bundle.metrics) == 2
    assert bundle.reconciliations == ()
    assert any("范围" in warning and "ledger_check" in warning for warning in bundle.warnings)
