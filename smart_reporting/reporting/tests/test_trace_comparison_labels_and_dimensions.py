import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset, metrics
from smart_reporting.reporting.tests.test_trace_lineage_regressions import _scoped_ratio
from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers
from smart_reporting.reporting.trace.table_builder import build_analysis_tables


@pytest.mark.parametrize(
    "names",
    [("收入", "收入", "成本"), ("收入", "收入", "收入（1）"), ("指标", "指标", "指标（1）")],
)
def test_comparison_names_do_not_collide(names):
    fields = ("a", "b", "c")
    entries = []
    for role, period, values in [
        ("current", "2025-01", "100,200,300"),
        ("yoy", "2024-01", "50,100,150"),
    ]:
        raw = f"month,department,a,b,c\n{period},A,{values}\n".encode()
        ctx = context(
            role,
            fields=("month", "department", *fields),
            semantics=tuple(semantic(f, unit="元") for f in fields),
        )
        entry = dataset(role, raw, ctx)
        entries.append((*entry[:3], (role,)))
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=fields), tuple(entries), profile_metrics=metrics(*fields)
    )
    assert len(bundle.comparisons) == 3
    # Business names are independently valid frozen metric display names.
    bundle = bundle.model_copy(
        update={
            "metrics": tuple(
                m.model_copy(update={"display_name": names[fields.index(m.field)]})
                for m in bundle.metrics
            )
        }
    )
    bundle = type(bundle).model_validate_json(bundle.model_dump_json(by_alias=True))
    result = build_analysis_tables(bundle, fact_file_resource_id="trf-" + "a" * 20)
    assert len(result) == 1
    assert len(set(result[0][0].column_keys)) == 3


def test_incompatible_dimensions_never_register_a_difference():
    bundle = _scoped_ratio("A")
    fact = bundle.derived_metrics[0]
    assert fact.value == 10 and fact.percentage is None
    assert fact.difference is None and "difference=" not in fact.formula
    token = "{{value:" + fact.fact_id + ":difference:}}"
    text, refs, notices = render_bound_numbers(
        "收入与就诊人次相差" + token,
        [bundle.model_dump_json(by_alias=True)],
        key="invalid-difference",
    )
    assert not refs and notices, (text, refs, notices)


def test_dimensioned_ratio_raw_value_remains_valid():
    bundle = _scoped_ratio("A")
    fact = bundle.derived_metrics[0]
    token = "{{value:" + fact.fact_id + ":value:}}"
    text, refs, notices = render_bound_numbers(
        "人均收入为" + token, [bundle.model_dump_json(by_alias=True)], key="valid-ratio"
    )
    assert len(refs) == 1 and not notices and text.endswith("10")


def test_same_dimension_difference_is_valid():
    raw = b"month,department,a,b\n2025-01,A,100,10\n"
    ctx = context(
        "current",
        fields=("month", "department", "a", "b"),
        semantics=(semantic("a", unit="元"), semantic("b", unit="元")),
    )
    defs = metrics("a", "b") + (
        {"code": "ratio", "aggregation": "ratio", "numeratorMetric": "a", "denominatorMetric": "b"},
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("a", "b")), (dataset("current", raw, ctx),), profile_metrics=defs
    )
    fact = bundle.derived_metrics[0]
    token = "{{value:" + fact.fact_id + ":difference:元}}"
    text, refs, notices = render_bound_numbers(
        "两个金额相差" + token, [bundle.model_dump_json(by_alias=True)], key="valid-difference"
    )
    assert len(refs) == 1 and not notices and "90元" in text


@pytest.mark.parametrize("frozen_inputs", [False, True])
@pytest.mark.parametrize(
    "units,supported",
    [
        (("元", "人次"), False),
        (("元", "元"), True),
        ((None, None), True),
        (("元", None), False),
    ],
)
def test_legacy_difference_is_checked_against_input_units(frozen_inputs, units, supported):
    bundle = _scoped_ratio("A")
    metrics = tuple(
        metric.model_copy(update={"unit": unit})
        for metric, unit in zip(bundle.metrics, units, strict=True)
    )
    old = bundle.derived_metrics[0].model_copy(
        update={
            "difference": 90,
            "input_fact_ids": bundle.derived_metrics[0].input_fact_ids if frozen_inputs else (),
        }
    )
    bundle = bundle.model_copy(update={"metrics": metrics, "derived_metrics": (old,)})
    token = "{{value:" + old.fact_id + ":difference:}}"
    _, refs, notices = render_bound_numbers(
        "差额为" + token, [bundle.model_dump_json(by_alias=True)], key="legacy-units"
    )
    assert bool(refs) is supported
    assert bool(notices) is not supported
