from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
from smart_reporting.reporting.delivery.artifacts_v1 import _TABLE_BLOCK
from smart_reporting.reporting.trace.subject_builder import value_matches
from smart_reporting.reporting.trace.table_builder import render_table_markdown


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "source_value,original,text,expected",
    [
        (10000, "1.00", "[1] 10000", "stale"),
        (10000, "1.00", "[^1] 10000", "stale"),
        (10000, "1.00", "[1] 0.01", "stale"),
        (20000, "2.00", "[1] 2.00", "valid"),
        (20000, "2.00", "[2] 10000", "stale"),
        (10000, "1.00", "[1] 1.00", "valid"),
        (20000, "2.00", "2.00", "valid"),
        (20000, "2.00", "[1][2] 2.00", "valid"),
        (10000, "1.00", "[12] 10000", "stale"),
        (10000, "1.00", "[^12] 10000", "stale"),
        (10000, "1.00", "[1]", "stale"),
        (10000, "1.00", "约[1]1.00（复核）", "valid"),
        (10000, "1.00", "1[1]万元", "valid"),
        (10000, "1.00", "10000[1]元", "valid"),
        (10000, "1.00", "1[1]元", "stale"),
    ],
)
async def test_footnote_reference_is_not_the_cell_amount(
    source_value, original, text, expected, header="收入（万元）"
):

    def markdown(value):
        return render_table_markdown("table-income", (header,), [["1月", value]])

    service = object.__new__(ReportEditorTraceService)
    service._workspace = SimpleNamespace(
        read_limited_regular_file=AsyncMock(return_value=markdown(original).encode())
    )
    cell = SimpleNamespace(
        row_key="period:2025-01",
        column_key=header,
        value_selector="periodValues.0",
        fact_refs=(SimpleNamespace(fact_key="fact-" + "a" * 16),),
    )
    index = SimpleNamespace(
        tables=(
            SimpleNamespace(
                table_id="table-income",
                row_keys=(cell.row_key,),
                cells=(cell,),
                origin_markdown=markdown(original),
            ),
        )
    )
    context = SimpleNamespace(scope={"threadId": "thread"}, markdown_path="report.md")
    tables, summary = await service._evaluate_tables(
        index,
        context,
        markdown(text),
        AsyncMock(return_value=source_value),
        _TABLE_BLOCK,
        value_matches,
        fact_unit_of=AsyncMock(return_value="元"),
    )
    assert summary[expected] == 1, (summary, tables[0]["locations"])


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "text,expected",
    [
        ("[10000] 1", "stale"),
        ("[^10000] 1", "stale"),
        ("[1] 10000", "valid"),
    ],
)
async def test_footnote_numbers_are_not_values_in_unscaled_columns(text, expected):
    await test_footnote_reference_is_not_the_cell_amount(
        10000, "10000", text, expected, header="收入"
    )
