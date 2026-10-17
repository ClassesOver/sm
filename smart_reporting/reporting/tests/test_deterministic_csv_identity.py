"""CSV identity and arbitrary source names must survive fact generation."""

from __future__ import annotations

import hashlib

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.trace.dataset_service import TraceDatasetFile
from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService

from .test_deterministic_analysis import analysis, context, semantic


@pytest.mark.parametrize("identifiers", [("001", "1"), ("1.0", "1"), ("true", "True")])
def test_distinct_fact_and_drilldown_preserve_identifiers(tmp_path, identifiers):
    content = ("month,department,patient_id\n"
               + "".join(f"2025-01,A,{value}\n" for value in identifiers)).encode()
    digest = hashlib.sha256(content).hexdigest()
    ctx = context(
        "dataset-current01", sha256=digest,
        fields=("month", "department", "patient_id"),
        semantics=(semantic("patient_id", "count_distinct"),),
    )
    metrics = ({"code": "patients", "aggregation": "count_distinct",
                "fieldRef": semantic("patient_id")["fieldRef"]},)
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("patient_id",)),
        (("dataset-current01", content, ctx, ("current",)),), profile_metrics=metrics,
    )
    path = tmp_path / "snapshot.csv"
    path.write_bytes(content)
    file = TraceDatasetFile("dataset-current01", path, len(content), digest, len(identifiers))
    (declaration,) = build_drilldown_metrics(
        bundles=(bundle.model_dump(mode="json", by_alias=True),),
        dataset_columns={file.dataset_id: ctx.fields}, profile_metrics=metrics,
        profile_dimensions=({"code": "department", "fieldRefs": [semantic("department")["fieldRef"]]},),
        measure_semantics=ctx.metric_semantics,
        row_preserving_dataset_ids=(file.dataset_id,),
    )
    page = TraceDrilldownService(secret=b"test").drilldown(
        file, declaration, dimension_code="department", report_id="report", revision=1,
    )
    assert bundle.metrics[0].total == page.observed_value == len(identifiers)
    assert page.reconciled is True


def test_scope_and_groups_keep_leading_zero_identifiers():
    content = b"month,department,amount\n2025-01,001,100\n2025-01,1,200\n"
    for scope, expected, groups in (
        ({}, 300, {"001": 100, "1": 200}),
        ({"department": "001"}, 100, {"001": 100}),
    ):
        bundle = build_deterministic_analysis_bundle(
            analysis(), (("current", content, context(
                "current", semantics=(semantic("amount", scope=scope),),
            ), ("current",)),),
        )
        fact = bundle.metrics[0]
        assert fact.total == expected
        assert {group.group: group.value for group in fact.top_groups} == groups


def test_identifier_type_changes_after_csv_inference_window_are_retained():
    identifiers = [str(index) for index in range(100)] + ["patient-X"]
    content = ("month,department,patient_id\n"
               + "".join(f"2025-01,A,{value}\n" for value in identifiers)).encode()
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("patient_id",)), (("current", content, context(
            "current", fields=("month", "department", "patient_id"),
            semantics=(semantic("patient_id", "count_distinct"),),
        ), ("current",)),),
    )
    assert bundle.metrics[0].total == 101


@pytest.mark.parametrize("role", ["metric", "dimension", "period"])
@pytest.mark.parametrize("name", ["__period", "__value", "__valid", "__input", "__group_0"])
def test_source_names_do_not_collide_with_internal_columns(role, name):
    period, dimension, field = (
        name if role == "period" else "month",
        name if role == "dimension" else "department",
        name if role == "metric" else "amount",
    )
    ctx = context("current", fields=(period, dimension, field), semantics=({
        **semantic(field), "additiveAcross": [period, dimension],
    },))
    ctx = ctx.model_copy(update={"organization_grain": (dimension,), "time_series_sort_field": period})
    item = analysis(fields=(field,)).model_copy(update={"organization_grain": (dimension,)})
    content = f"{period},{dimension},{field}\n2025-01,A,100\n2025-02,B,200\n".encode()
    bundle = build_deterministic_analysis_bundle(item, (("current", content, ctx, ("current",)),))
    fact = bundle.metrics[0]
    assert fact.total == 300
    assert [(value.period, value.value) for value in fact.period_values] == [
        ("2025-01", 100), ("2025-02", 200),
    ]
    assert [(group.group, group.value) for group in fact.top_groups] == [("B", 200), ("A", 100)]


@pytest.mark.parametrize("dimension", ["__value", "__valid", "__input", "__group_0"])
def test_reconciliation_handles_internal_column_names(dimension):
    ctx = context(
        "current", fields=("month", dimension, "left", "right"),
        semantics=(semantic("left"), semantic("right")),
    ).model_copy(update={"organization_grain": (dimension,)})
    item = analysis(fields=("left", "right")).model_copy(update={"organization_grain": (dimension,)})
    content = f"month,{dimension},left,right\n2025-01,A,100,110\n2025-01,B,200,190\n".encode()
    bundle = build_deterministic_analysis_bundle(
        item, (("current", content, ctx, ("current",)),),
        profile_metrics=tuple({"code": field, "aggregation": "sum", "fieldRef": semantic(field)["fieldRef"]}
                              for field in ("left", "right")),
        profile_reconciliations=({
            "code": "check", "leftMetric": "left", "rightMetric": "right", "grain": ["branch"],
            "absoluteTolerance": 0, "relativeTolerance": 0,
        },),
        profile_dimensions=({"code": "branch", "fieldRefs": [semantic(dimension)["fieldRef"]]},),
    )
    check = bundle.reconciliations[0]
    assert check.difference == 0
    assert check.checked_group_count == 2
    assert check.failed_group_count == 2
    assert check.passed is False
