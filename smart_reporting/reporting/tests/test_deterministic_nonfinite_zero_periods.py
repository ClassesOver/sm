import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset, metrics


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "1e999"])
@pytest.mark.parametrize("aggregation", ["sum", "average", "min", "max"])
def test_nonfinite_measure_does_not_abort_unrelated_finite_facts(bad, aggregation):
    raw = f"month,department,amount,visits\n2025-01,A,100,10\n2025-02,A,{bad},20\n".encode()
    ctx = context(
        "current",
        fields=("month", "department", "amount", "visits"),
        semantics=(semantic("amount", aggregation, unit="元"), semantic("visits", unit="人次")),
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")),
        (dataset("current", raw, ctx),),
        profile_metrics=({**metrics("amount")[0], "aggregation": aggregation}, *metrics("visits")),
    )
    assert next(m for m in bundle.metrics if m.field == "visits").total == 30
    assert {m.field for m in bundle.metrics} == {"visits"}
    assert any("amount" in warning and "非有限数值" in warning for warning in bundle.warnings)


@pytest.mark.parametrize("aggregation", ["count", "count_distinct"])
@pytest.mark.parametrize("role", ["yoy", "mom"])
def test_zero_count_period_is_preserved_and_compared(aggregation, role):
    entries = []
    for name, period, value in [
        ("current", "2025-01", ""),
        (role, "2024-01" if role == "yoy" else "2024-12", "p1"),
    ]:
        raw = f"month,department,patient\n{period},A,{value}\n".encode()
        ctx = context(
            name,
            fields=("month", "department", "patient"),
            semantics=(semantic("patient", aggregation, unit="人次"),),
        )
        entry = dataset(name, raw, ctx)
        entries.append((*entry[:3], (name,)))
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("patient",)),
        tuple(entries),
        profile_metrics=({**metrics("patient")[0], "aggregation": aggregation},),
    )
    assert bundle.metrics[0].total == 0
    assert bundle.metrics[0].period_values[0].value == 0
    assert bundle.metrics[0].top_groups[0].value == 0
    assert len(bundle.comparisons) == 1, (bundle.metrics[0].period_values, bundle.warnings)
    assert bundle.comparisons[0].current_total == 0 and bundle.comparisons[0].change_rate == -100


@pytest.mark.parametrize("aggregation", ["count", "count_distinct"])
def test_zero_count_can_be_a_real_ratio_numerator(aggregation):
    raw = b"month,department,patient,visits\n2025-01,A,,10\n"
    ctx = context(
        "current",
        fields=("month", "department", "patient", "visits"),
        semantics=(semantic("patient", aggregation, unit="人次"), semantic("visits", unit="人次")),
    )
    definitions = ({**metrics("patient")[0], "aggregation": aggregation}, *metrics("visits")) + (
        {
            "code": "ratio",
            "aggregation": "ratio",
            "numeratorMetric": "patient",
            "denominatorMetric": "visits",
        },
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("patient", "visits")),
        (dataset("current", raw, ctx),),
        profile_metrics=definitions,
    )
    assert len(bundle.derived_metrics) == 1, bundle.warnings
    assert bundle.derived_metrics[0].value == 0


def test_invalid_non_numeric_control():
    raw = b"month,department,amount,visits\n2025-01,A,100,10\n2025-02,A,invalid,20\n"
    ctx = context(
        "current",
        fields=("month", "department", "amount", "visits"),
        semantics=(semantic("amount", unit="元"), semantic("visits", unit="人次")),
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("amount", "visits")),
        (dataset("current", raw, ctx),),
        profile_metrics=metrics("amount", "visits"),
    )
    assert [m.total for m in bundle.metrics] == [100, 30]


@pytest.mark.parametrize("aggregation", ["count", "count_distinct"])
@pytest.mark.parametrize("label", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_nonfinite_looking_identifier_is_still_a_real_counted_value(aggregation, label):
    raw = f"month,department,patient\n2025-01,A,{label}\n".encode()
    ctx = context(
        "current",
        fields=("month", "department", "patient"),
        semantics=(semantic("patient", aggregation),),
    )
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("patient",)),
        (dataset("current", raw, ctx),),
        profile_metrics=({**metrics("patient")[0], "aggregation": aggregation},),
    )
    fact = bundle.metrics[0]
    assert fact.total == fact.period_values[0].value == fact.top_groups[0].value == 1
    assert not any("非有限数值" in warning for warning in bundle.warnings)


@pytest.mark.parametrize("aggregation", ["count", "count_distinct"])
def test_generated_zero_count_period_stays_traceable_in_drilldown(tmp_path, aggregation):
    from smart_reporting.reporting.trace.dataset_service import (
        TraceDatasetFile,
        verified_dataset_snapshot,
    )
    from smart_reporting.reporting.trace.drilldown_builder import build_drilldown_metrics
    from smart_reporting.reporting.trace.drilldown_service import TraceDrilldownService
    from smart_reporting.reporting.trace.semantic_bindings import (
        render_bound_numbers,
        resolve_number_reference,
    )

    raw = b"month,department,patient\n2025-01,A,\n2025-01,B,\n"
    dataset_id = "dataset-current01"
    ctx = context(
        dataset_id,
        fields=("month", "department", "patient"),
        semantics=(semantic("patient", aggregation),),
    )
    entry = dataset(dataset_id, raw, ctx)
    definitions = ({**metrics("patient")[0], "aggregation": aggregation},)
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=("patient",)), (entry,), profile_metrics=definitions
    )
    fact = bundle.metrics[0]
    token = "{{value:" + fact.fact_id + ":periodValues.0:}}"
    text, refs, notices = render_bound_numbers(
        "2025年1月计数为" + token, [bundle.model_dump_json(by_alias=True)], key="zero"
    )
    assert text.endswith("0") and len(refs) == 1 and not notices
    assert resolve_number_reference(token, [bundle.model_dump_json(by_alias=True)])["value"] == 0
    declarations = build_drilldown_metrics(
        bundles=[bundle.model_dump(mode="json", by_alias=True)],
        dataset_columns={dataset_id: ctx.fields},
        profile_metrics=definitions,
        profile_dimensions=(
            {"code": "department", "fieldRefs": [semantic("department")["fieldRef"]]},
        ),
        measure_semantics=ctx.metric_semantics,
        row_preserving_dataset_ids=(dataset_id,),
    )
    assert len(declarations) == 1
    path = tmp_path / "snapshot.csv"
    path.write_bytes(raw)
    file = TraceDatasetFile(dataset_id, path, len(raw), entry[2].sha256, 2)
    with verified_dataset_snapshot(file) as snapshot:
        page = TraceDrilldownService(secret=b"zero-count").drilldown(
            snapshot, declarations[0], dimension_code="department", report_id="report", revision=1
        )
    assert page.observed_value == 0 and page.reconciled is True
    assert dict(page.rows) == {"A": 0, "B": 0}


def test_nonfinite_values_outside_fixed_scope_do_not_remove_valid_fact():
    raw = b"month,department,amount\n2025-01,A,100\n2025-01,B,NaN\n"
    ctx = context("current", semantics=(semantic("amount", scope={"department": "A"}, unit="元"),))
    bundle = build_deterministic_analysis_bundle(
        analysis(), (dataset("current", raw, ctx),), profile_metrics=metrics("amount")
    )
    assert bundle.metrics[0].total == 100
    assert not any("非有限数值" in warning for warning in bundle.warnings)
