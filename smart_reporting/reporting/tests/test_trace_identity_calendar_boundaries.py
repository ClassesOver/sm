"""事实语义身份、对账规则和同年闰日窗口的回归。"""

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicAnalysisBundle,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset, metrics
from smart_reporting.reporting.trace.fact_index import assign_fact_ids
from smart_reporting.reporting.trace.semantic_bindings import resolve_number_reference


def metric_bundle(unit="元", period_field="invoice_month"):
    raw = b"invoice_month,service_month,department,amount\n2025-01,2025-02,A,100\n2025-02,2025-01,A,200\n"
    measure = {
        **semantic("amount", unit=unit),
        "additiveAcross": ["invoice_month", "service_month", "department"],
    }
    ctx = context(
        "current",
        fields=("invoice_month", "service_month", "department", "amount"),
        semantics=(measure,),
    ).model_copy(
        update={
            "time_series_sort_field": period_field,
            "period_granularities": {"invoice_month": "month", "service_month": "month"},
        }
    )
    return build_deterministic_analysis_bundle(
        analysis(), (dataset("current", raw, ctx),), profile_metrics=metrics("amount")
    )


@pytest.mark.parametrize("options", [{"unit": "万元"}, {"period_field": "service_month"}])
def test_metric_semantics_change_identity_and_preserve_merged_references(options):
    left, right = metric_bundle(), metric_bundle(**options)
    assert left.metrics[0].total == right.metrics[0].total == 300
    assert left.metrics[0].fact_id != right.metrics[0].fact_id
    contents = [bundle.model_dump_json(by_alias=True) for bundle in (left, right)]
    for bundle, expected in ((left, 100), (right, 100 if "unit" in options else 200)):
        fact = bundle.metrics[0]
        token = "{{value:" + fact.fact_id + ":periodValues.0:" + fact.unit + "}}"
        selected = resolve_number_reference(token, contents)
        assert selected is not None and selected["value"] == expected


def reconciliation_bundle(*, absolute=0, relative=0, grain="ward"):
    raw = b"month,department,ward,actual,ledger\n2025-01,A,W1,100,101\n2025-01,A,W2,110,109\n"
    ctx = context(
        "current",
        fields=("month", "department", "ward", "actual", "ledger"),
        semantics=(semantic("actual", unit="元"), semantic("ledger", unit="元")),
    )
    return build_deterministic_analysis_bundle(
        analysis(fields=("actual", "ledger")),
        (dataset("current", raw, ctx),),
        profile_metrics=metrics("actual", "ledger"),
        profile_reconciliations=(
            {
                "code": "check",
                "leftMetric": "actual",
                "rightMetric": "ledger",
                "grain": [grain],
                "absoluteTolerance": absolute,
                "relativeTolerance": relative,
            },
        ),
        profile_dimensions=tuple(
            {"code": field, "fieldRefs": [semantic(field)["fieldRef"]]}
            for field in ("department", "ward")
        ),
    )


@pytest.mark.parametrize("options", [{"absolute": 1}, {"relative": 0.02}, {"grain": "department"}])
def test_reconciliation_rule_changes_identity_and_preserves_merged_references(options):
    left, right = reconciliation_bundle(), reconciliation_bundle(**options)
    assert not left.reconciliations[0].passed and right.reconciliations[0].passed
    assert tuple(f.fact_id for f in left.metrics) == tuple(f.fact_id for f in right.metrics)
    assert left.reconciliations[0].fact_id != right.reconciliations[0].fact_id
    contents = [b.model_dump_json(by_alias=True) for b in (left, right)]
    for bundle in (left, right):
        token = "{{value:" + bundle.reconciliations[0].fact_id + ":difference:元}}"
        selected = resolve_number_reference(token, contents)
        assert selected is not None and selected["value"] == 0


@pytest.mark.parametrize("builder", [metric_bundle, reconciliation_bundle])
def test_new_identity_is_stable_on_rebuild_and_roundtrip(builder):
    left, right = builder(), builder()
    assert left.model_dump() == right.model_dump()
    loaded = DeterministicAnalysisBundle.model_validate_json(left.model_dump_json(by_alias=True))
    assert assign_fact_ids(loaded).model_dump() == left.model_dump()


@pytest.mark.parametrize(
    "year,include_leap,expected,start",
    [
        (2025, False, 20, "2025-02-28"),
        (2024, False, 30, "2024-03-01"),
        (2024, True, 20, "2024-02-28"),
    ],
)
def test_same_year_ratio_and_reconciliation_require_calendar_continuity(
    year, include_leap, expected, start
):
    rows = f"{year}-02-28,A,100,10\n"
    if include_leap:
        rows += f"{year}-02-29,A,200,10\n"
    rows += f"{year}-03-01,A,300,10\n"
    raw = ("day,department,amount,visits\n" + rows).encode()
    ctx = context(
        "current",
        fields=("day", "department", "amount", "visits"),
        semantics=tuple(
            {**semantic(field, unit="元"), "additiveAcross": ["day", "department"]}
            for field in ("amount", "visits")
        ),
    ).model_copy(update={"time_series_sort_field": "day", "period_granularities": {"day": "date"}})
    definitions = metrics("amount", "visits") + (
        {
            "code": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": "amount",
            "denominatorMetric": "visits",
        },
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")).model_copy(update={"series_granularity": "day"}),
        (dataset("current", raw, ctx),),
        profile_metrics=definitions,
        profile_reconciliations=(
            {
                "code": "check",
                "leftMetric": "amount",
                "rightMetric": "visits",
                "grain": ["department"],
                "absoluteTolerance": 0,
                "relativeTolerance": 0,
            },
        ),
        profile_dimensions=(
            {"code": "department", "fieldRefs": [semantic("department")["fieldRef"]]},
        ),
    )
    fact = bundle.derived_metrics[0]
    assert (fact.value, fact.period_start) == (expected, start)
    check = bundle.reconciliations[0]
    assert check.period_start == start
    assert check.left_total / check.right_total == expected
    assert bool(fact.warnings) is (year == 2024 and not include_leap)
