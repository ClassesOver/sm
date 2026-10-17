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


@pytest.mark.parametrize("days", [333, 334, 365])
def test_table_split_happens_before_validating_all_cells_together(days):
    fields = tuple("value_" + str(i) for i in range(6))
    raw = (
        "month,department,"
        + ",".join(fields)
        + "\n"
        + "".join(
            (date(2025, 1, 1) + timedelta(days=i)).isoformat() + ",A,1,2,3,4,5,6\n"
            for i in range(days)
        )
    ).encode()
    ctx = context(
        "current",
        fields=("month", "department", *fields),
        semantics=tuple(semantic(field, unit="元") for field in fields),
    ).model_copy(update={"period_granularities": {"month": "date"}})
    bundle = build_deterministic_analysis_bundle(
        analysis(fields=fields).model_copy(update={"series_granularity": "day"}),
        (dataset("current", raw, ctx),),
        profile_metrics=metrics(*fields),
    )
    resource = "trf-" + "a" * 20
    # Each eventual part independently fits all declared budgets.
    part1 = build_analysis_table(
        bundle, fact_file_resource_id=resource, column_offset=0, column_limit=5
    )
    part2 = build_analysis_table(
        bundle, fact_file_resource_id=resource, column_offset=5, column_limit=5
    )
    assert len(part1[0].cells) == 5 * days and len(part2[0].cells) == days
    result = build_analysis_tables(bundle, fact_file_resource_id=resource)
    assert len(result) == 2
    assert sum(len(table.cells) for table, _ in result) == 6 * days
    for table, _ in result:
        for cell in table.cells:
            ref = cell.fact_refs[0]
            metric = bundle.metrics[int(ref.json_pointer.rsplit("/", 1)[-1])]
            assert ref.fact_key == metric.fact_id
            assert cell.value_selector.startswith("periodValues.")


@pytest.mark.parametrize(
    "department,ward",
    [
        ("A" * 513, None),
        ("A" * 300, "B" * 300),
        ("A" * 200, "B" * 200),
        ("A" * 512, None),
        ("院" * 600, None),
        ("A" * 1000, None),
        ("A" * 260, "B" * 250),
    ],
)
def test_long_display_group_label_does_not_abort_fact_generation(department, ward):
    fields = (
        ("month", "department", "amount")
        if ward is None
        else ("month", "department", "ward", "amount")
    )
    grain = ("department",) if ward is None else ("department", "ward")
    raw = (
        ",".join(fields)
        + "\n2025-01,"
        + department
        + ("," + ward if ward is not None else "")
        + ",100\n"
    ).encode()
    ctx = context("current", fields=fields, semantics=(semantic("amount", unit="元"),)).model_copy(
        update={"organization_grain": grain}
    )
    bundle = build_deterministic_analysis_bundle(
        analysis().model_copy(update={"organization_grain": grain}),
        (dataset("current", raw, ctx),),
        profile_metrics=metrics("amount"),
    )
    assert bundle.metrics[0].total == 100
    group = bundle.metrics[0].top_groups[0]
    assert len(group.group) <= 512 and group.group_values["department"] == department
    if ward is not None:
        assert group.group_values["ward"] == ward


def test_long_labels_with_same_prefix_remain_distinct_and_stable():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        DeterministicAnalysisBundle,
    )
    from smart_reporting.reporting.trace.fact_index import assign_fact_ids

    labels = ("A" * 1000 + "one", "A" * 1000 + "two")
    orders = []
    for ordering in (labels, tuple(reversed(labels))):
        raw = (
            "month,department,amount\n" + "".join(f"2025-01,{label},100\n" for label in ordering)
        ).encode()
        bundle = build_deterministic_analysis_bundle(
            analysis(),
            (dataset("current", raw, context("current")),),
            profile_metrics=metrics("amount"),
        )
        fact = bundle.metrics[0]
        assert len({item.group for item in fact.top_groups}) == 2
        assert {item.group_values["department"] for item in fact.top_groups} == set(labels)
        assert all(len(item.group) <= 512 for item in fact.top_groups)
        loaded = DeterministicAnalysisBundle.model_validate_json(
            bundle.model_dump_json(by_alias=True)
        )
        assert assign_fact_ids(loaded).model_dump() == bundle.model_dump()
        orders.append([item.group for item in fact.top_groups])
    assert orders[0] == orders[1]


def test_single_small_table_preserves_its_existing_id():
    from .test_trace_table_builder import _bundle

    bundle = _bundle()
    result = build_analysis_tables(bundle, fact_file_resource_id="trf-" + "a" * 20)
    assert len(result) == 1
    assert result[0][0].table_id == "table-" + bundle.analysis_id
