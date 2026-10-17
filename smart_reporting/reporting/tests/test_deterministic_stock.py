"""时点指标在事实、比较、派生计算和下钻中采用相同的全局期末。"""

from __future__ import annotations

import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    DeterministicMetricFact,
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService
from smart_reporting.reporting.trace.fact_index import assign_fact_ids

from .test_deterministic_analysis import analysis, context, semantic


def stock_semantic(field):
    return {**semantic(field), "additiveAcross": ["department"]}


def stock_context(dataset_id, fields=("balance",)):
    return context(dataset_id, fields=("month", "department", *fields),
                   semantics=tuple(stock_semantic(field) for field in fields))


@pytest.mark.parametrize("body,expected,groups,period_values", [
    ("2025-01,A,100\n2025-01,B,200\n2025-02,A,110\n2025-02,B,230\n", 340, {"A": 110, "B": 230}, [300, 340]),
    ("2025-10,A,110\n2025-2,A,100\n2025-2,B,200\n", 110, {"A": 110}, [300, 110]),
    ("2025-01,A,100\n2025-02,A,0\n2025-02,B,0\n", 0, {"A": 0, "B": 0}, [100, 0]),
    (",A,999\n2025-01,A,100\n2025-02,A,110\n", 110, {"A": 110}, [100, 110]),
])
def test_stock_total_and_groups_match_registered_drilldown(tmp_path, body, expected, groups, period_values):
    content = ("month,department,balance\n" + body).encode()
    digest = hashlib.sha256(content).hexdigest()
    ctx = stock_context("dataset-stock01").model_copy(update={"sha256": digest})
    metrics = ({"code": "balance", "aggregation": "sum", "fieldRef": semantic("balance")["fieldRef"]},)
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("balance",)), ((ctx.dataset_id, content, ctx, ("current",)),),
        profile_metrics=metrics,
    )
    fact = bundle.metrics[0]
    assert fact.total == expected
    assert fact.period_aggregation == "last"
    assert {group.group: group.value for group in fact.top_groups} == groups
    assert "最新登记期间" in fact.formula
    assert [value.value for value in fact.period_values] == period_values
    # Cross-period semantics must remain frozen when the fact file is reloaded.
    loaded = DeterministicMetricFact.model_validate_json(fact.model_dump_json(by_alias=True))
    assert loaded.period_aggregation == "last"

    path = tmp_path / "snapshot.csv"
    path.write_bytes(content)
    file = TraceDatasetFile(ctx.dataset_id, path, len(content), digest, len(body.splitlines()))
    (declaration,) = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode="json", by_alias=True),),
        dataset_columns={ctx.dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({"code": "department", "fieldRefs": [semantic("department")["fieldRef"]]},),
        measure_semantics=ctx.metric_semantics,
    )
    page = TraceDrilldownService(secret=b"test").drilldown(
        file, declaration, dimension_code="department", report_id="report", revision=1,
    )
    assert page.observed_value == expected
    assert dict(page.rows) == groups
    assert page.reconciled is True


@pytest.mark.parametrize("period", ["", "unknown-period"])
def test_stock_without_a_valid_period_is_softly_omitted(period):
    content = f"month,department,balance\n{period},A,100\n".encode()
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("balance",)), (("current", content, stock_context("current"), ("current",)),),
    )
    assert bundle.metrics == ()
    assert any("未生成时点事实" in warning for warning in bundle.warnings)


def test_stock_yoy_compares_endpoints_and_preserves_the_trend():
    bundle = build_deterministic_analysis_bundle(analysis(fields=("balance",)), tuple(
        (name, f"month,department,balance\n{year}-01,A,{jan}\n{year}-02,A,{feb}\n".encode(),
         stock_context(name), (role,))
        for name, year, jan, feb, role in (
            ("current", 2025, 100, 200, "current"), ("baseline", 2024, 10, 50, "yoy"),
        )
    ))
    assert [v.value for v in bundle.metrics[0].period_values] == [100, 200]
    comparison = bundle.comparisons[0]
    assert (comparison.current_total, comparison.baseline_total, comparison.change_rate) == (200, 50, 300)
    assert comparison.period_start == comparison.period_end == "2025-02"


def test_stock_ratio_and_reconciliation_use_only_latest_period():
    fields = ("balance", "liabilities", "ledger")
    metrics = tuple({"code": field, "aggregation": "sum", "fieldRef": semantic(field)["fieldRef"]}
                    for field in fields) + ({
                        "code": "ratio", "aggregation": "ratio", "numeratorMetric": "balance",
                        "denominatorMetric": "liabilities",
                    },)
    content = (b"month,department,balance,liabilities,ledger\n"
               b"2025-01,A,100,1000,900\n2025-01,B,200,2000,800\n"
               b"2025-02,A,110,10,110\n2025-02,B,230,30,230\n")
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=fields), (("current", content, stock_context("current", fields), ("current",)),),
        profile_metrics=metrics,
        profile_reconciliations=({
            "code": "check", "leftMetric": "balance", "rightMetric": "ledger", "grain": ["department"],
            "absoluteTolerance": 0, "relativeTolerance": 0,
        },),
        profile_dimensions=({"code": "department", "fieldRefs": [semantic("department")["fieldRef"]]},),
    )
    ratio = bundle.derived_metrics[0]
    assert (ratio.numerator, ratio.denominator, ratio.value) == (340, 40, 8.5)
    assert ratio.period_start == ratio.period_end == "2025-02"
    check = bundle.reconciliations[0]
    assert (check.left_total, check.right_total, check.checked_group_count) == (340, 340, 2)
    assert check.passed is True


def test_stock_identity_includes_period_aggregation_and_legacy_defaults_are_compatible():
    # Even a single-period file must distinguish stock from flow semantics.
    content = b"month,department,balance\n2025-01,A,100\n"
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("balance",)), (("current", content, stock_context("current"), ("current",)),),
    )
    stock = bundle.metrics[0]
    payload = stock.model_dump(mode="json", by_alias=True)
    payload.pop("periodAggregation")
    legacy = DeterministicMetricFact.model_validate(payload)
    assert legacy.period_aggregation is None
    flow = assign_fact_ids(bundle.model_copy(update={"metrics": (legacy,)})).metrics[0]
    assert flow.fact_id != stock.fact_id
