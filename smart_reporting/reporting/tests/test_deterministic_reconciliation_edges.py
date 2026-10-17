"""对账共同期末、空分组身份和同日历期间别名的数值回归。"""

from __future__ import annotations

import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.fact_index import assign_fact_ids

from .test_deterministic_analysis import analysis, context, semantic
from .test_deterministic_stock import stock_context


def metrics(*fields):
    return tuple({"code": field, "aggregation": "sum", "fieldRef": semantic(field)["fieldRef"]}
                 for field in fields)


def dataset(name, content, ctx):
    return name, content, ctx.model_copy(update={"sha256": hashlib.sha256(content).hexdigest()}), ("current",)


def reconcile(datasets, grain=("department",)):
    return build_deterministic_analysis_bundle(
        analysis(fields=("actual", "ledger")), datasets,
        profile_metrics=metrics("actual", "ledger"),
        profile_reconciliations=({"code": "check", "leftMetric": "actual", "rightMetric": "ledger",
                                  "grain": list(grain), "absoluteTolerance": 0, "relativeTolerance": 0},),
        profile_dimensions=tuple({"code": field, "fieldRefs": [semantic(field)["fieldRef"]]} for field in grain),
    )


@pytest.mark.parametrize("actual_latest,ledger_latest", [("2025-02", "2025-01"), ("2025-01", "2025-02")])
def test_stock_reconciliation_uses_latest_common_period(actual_latest, ledger_latest):
    bundle = reconcile((
        dataset("actual", ("month,department,actual\n2024-12,A,999\n2025-01,A,100\n"
                           + ("2025-02,A,200\n" if actual_latest == "2025-02" else "")).encode(),
                stock_context("actual", ("actual",))),
        dataset("ledger", ("month,department,ledger\n2024-12,A,777\n2025-01,A,200\n"
                           + ("2025-02,A,100\n" if ledger_latest == "2025-02" else "")).encode(),
                stock_context("ledger", ("ledger",))),
    ))
    check = bundle.reconciliations[0]
    assert (check.left_total, check.right_total, check.difference) == (100, 200, -100)
    assert check.period_start == check.period_end == "2025-01"
    assert check.checked_group_count == check.failed_group_count == 1
    assert check.passed is False
    assert any("时点对账" in warning for warning in check.warnings)
    # The selected period participates in identity, so another endpoint cannot reuse the reference.
    changed = check.model_copy(update={"period_start": "2024-12", "period_end": "2024-12"})
    revised = assign_fact_ids(bundle.model_copy(update={"reconciliations": (changed,)}))
    assert revised.reconciliations[0].fact_id != check.fact_id


@pytest.mark.parametrize("right_is_stock", [True, False])
def test_stock_reconciliation_without_comparable_period_is_softly_omitted(right_is_stock):
    right_ctx = stock_context("ledger", ("ledger",)) if right_is_stock else context(
        "ledger", fields=("month", "department", "ledger"), semantics=(semantic("ledger"),),
    )
    right_period = "2025-02" if right_is_stock else "2025-01"
    bundle = reconcile((
        dataset("actual", b"month,department,actual\n2025-01,A,100\n", stock_context("actual", ("actual",))),
        dataset("ledger", f"month,department,ledger\n{right_period},A,100\n".encode(), right_ctx),
    ))
    assert bundle.reconciliations == ()
    assert any("未生成对账" in warning for warning in bundle.warnings)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("grain", [("department",), ("department", "ward")])
def test_null_and_literal_none_remain_distinct_groups(reverse, grain):
    rows = [",A,100,200", "None,A,200,100"]
    if reverse:
        rows.reverse()
    content = ("month,department,ward,actual,ledger\n"
               + "".join(f"2025-01,{row}\n" for row in rows)).encode()
    ctx = context("current", fields=("month", "department", "ward", "actual", "ledger"),
                  semantics=(semantic("actual"), semantic("ledger")))
    bundle = reconcile((dataset("current", content, ctx),), grain)
    check = bundle.reconciliations[0]
    assert (check.left_total, check.right_total, check.difference) == (300, 300, 0)
    assert check.checked_group_count == check.failed_group_count == 2
    assert check.passed is False


@pytest.mark.parametrize("side", ["numerator", "denominator", "both"])
@pytest.mark.parametrize("labels,grain", [
    (("2025-1", "2025-01"), None),
    (("2025-1-1", "2025-01-01"), None),
    (("2025-01", "2025-01-01"), "month"),
])
def test_ratio_combines_calendar_aliases_on_either_side(side, labels, grain):
    amount_rows = f"{labels[0]},A,100\n{labels[1]},A,200\n" if side != "denominator" else f"{labels[1]},A,300\n"
    visits_rows = f"{labels[0]},A,4\n{labels[1]},A,6\n" if side != "numerator" else f"{labels[1]},A,10\n"
    entries = []
    for field, rows in (("amount", amount_rows), ("visits", visits_rows)):
        ctx = context(field, fields=("month", "department", field), semantics=(semantic(field),))
        if grain:
            ctx = ctx.model_copy(update={"period_granularities": {"month": grain}})
        entries.append(dataset(field, (f"month,department,{field}\n" + rows).encode(), ctx))
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")), tuple(entries),
        profile_metrics=metrics("amount", "visits") + ({"code": "ratio", "aggregation": "ratio",
            "numeratorMetric": "amount", "denominatorMetric": "visits"},),
    )
    ratio = bundle.derived_metrics[0]
    assert (ratio.numerator, ratio.denominator, ratio.value) == (300, 10, 30)
    assert all(len(fact.period_values) == 1 for fact in bundle.metrics)


@pytest.mark.parametrize("aggregation,expected", [
    ("sum", 40), ("average", 40 / 3), ("count", 3), ("count_distinct", 2), ("min", 10), ("max", 20),
])
def test_period_aliases_aggregate_original_rows(aggregation, expected):
    content = b"month,department,amount\n2025-1,A,10\n2025-1,A,20\n2025-01,A,10\n2025-02,A,100\n"
    ctx = context("current", semantics=(semantic("amount", aggregation),))
    bundle = build_deterministic_analysis_bundle(analysis(), (dataset("current", content, ctx),))
    periods = bundle.metrics[0].period_values
    assert [period.period for period in periods] == ["2025-01", "2025-02"]
    assert periods[0].value == pytest.approx(expected)
