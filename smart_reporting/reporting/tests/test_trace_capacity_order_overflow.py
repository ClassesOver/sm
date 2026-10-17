from datetime import date, timedelta

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_deterministic_reconciliation_edges import dataset, metrics
from smart_reporting.reporting.trace.table_builder import (
    build_analysis_table,
    build_analysis_tables,
)


def bundle_from(raw, fields, daily=False):
    ctx = context(
        "current",
        fields=("month", "department", *fields),
        semantics=tuple(semantic(f, unit="元") for f in fields),
    )
    item = analysis(fields=fields)
    if daily:
        ctx = ctx.model_copy(update={"period_granularities": {"month": "date"}})
        item = item.model_copy(update={"series_granularity": "day"})
    return build_deterministic_analysis_bundle(
        item, (dataset("current", raw, ctx),), profile_metrics=metrics(*fields)
    )


@pytest.mark.parametrize(
    "days,width", [(400, 5), (401, 5), (500, 6), (1000, 1), (1001, 1), (1200, 2), (1200, 6)]
)
def test_auto_tables_cover_valid_frozen_facts(days, width):
    fields = tuple(f"value_{i}" for i in range(width))
    raw = (
        "month,department,"
        + ",".join(fields)
        + "\n"
        + "".join(
            (date(2022, 1, 1) + timedelta(days=i)).isoformat()
            + ",A,"
            + ",".join(str(j + 1) for j in range(width))
            + "\n"
            for i in range(days)
        )
    ).encode()
    bundle = bundle_from(raw, fields, True)
    assert all(len(f.period_values) == days for f in bundle.metrics)
    if days <= 1000:
        part = build_analysis_table(
            bundle, fact_file_resource_id="trf-" + "a" * 20, column_limit=min(width, 2000 // days)
        )
        assert len(part[0].cells) <= 2000
    result = build_analysis_tables(bundle, fact_file_resource_id="trf-" + "a" * 20)
    assert sum(len(t.cells) for t, _ in result) == width * days
    assert len({table.table_id for table, _ in result}) == len(result)
    seen = set()
    for table, markdown in result:
        assert len(table.row_keys) <= 1000 and len(table.cells) <= 2000
        assert table.table_id in markdown
        for cell in table.cells:
            ref = cell.fact_refs[0]
            fact = bundle.metrics[int(ref.json_pointer.rsplit("/", 1)[-1])]
            assert ref.fact_key == fact.fact_id
            period = fact.period_values[int(cell.value_selector.rsplit(".", 1)[-1])]
            assert cell.row_key == "period:" + period.period
            key = (fact.field, period.period)
            assert key not in seen
            seen.add(key)
    assert len(seen) == days * width


@pytest.mark.parametrize("amount", ["1e307", "1e308"])
def test_overflow_does_not_drop_healthy_metric(amount):
    raw = f"month,department,amount,visits\n2025-01,A,{amount},10\n2025-01,A,{amount},20\n".encode()
    bundle = bundle_from(raw, ("amount", "visits"))
    assert next(f for f in bundle.metrics if f.field == "visits").total == 30
    if amount == "1e308":
        assert all(f.field != "amount" for f in bundle.metrics)
        assert bundle.warnings
    else:
        assert next(f for f in bundle.metrics if f.field == "amount").total == 2e307


@pytest.mark.parametrize("missing", [False, True])
def test_sparse_periods_are_chronological(missing):
    raw = b"month,department,actual,budget\n2025-01,A,100,\n2025-02,A,,200\n2025-03,A,300,300\n"
    if not missing:
        raw = raw.replace(b"100,\n", b"100,100\n").replace(b"A,,200", b"A,200,200")
    bundle = bundle_from(raw, ("actual", "budget"))
    table, _ = build_analysis_tables(bundle, fact_file_resource_id="trf-" + "a" * 20)[0]
    assert table.row_keys == ("period:2025-01", "period:2025-02", "period:2025-03")


@pytest.mark.parametrize(
    "raw",
    [
        b"month,department,amount,visits\n2025-01,A,1e308,10\n2025-02,A,1e308,20\n",
        b"month,department,amount,visits\n2025-01,A,1e308,10\n2025-02,A,1e308,20\n2025-01,B,-1e308,30\n2025-02,B,-1e308,40\n",
        b"month,department,amount,visits\n2025-01,A,-1e308,10\n2025-01,A,-1e308,20\n",
    ],
)
def test_aggregate_and_group_overflow_preserve_unrelated_facts(raw):
    bundle = bundle_from(raw, ("amount", "visits"))
    assert {fact.field for fact in bundle.metrics} == {"visits"}
    assert bundle.metrics[0].total == (100 if b",B," in raw else 30)
    assert any("amount" in warning and "非有限" in warning for warning in bundle.warnings)
