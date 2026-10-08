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
    ("original", "draft", "has_reference", "expected"),
    [
        ("—", "—", False, "valid"),
        ("—", "0", False, "stale"),
        ("—", "1,200", False, "stale"),
        ("1,200", "—", False, "stale"),
        ("—", "—", True, "stale"),
    ],
)
async def test_missing_period_placeholder_is_not_an_edited_value(
    original, draft, has_reference, expected,
):
    def markdown(value):
        return render_table_markdown("table-monthly", ("收入（元）",), [["2025-12", value]])

    service = object.__new__(ReportEditorTraceService)
    service._workspace = SimpleNamespace(
        read_limited_regular_file=AsyncMock(return_value=markdown(original).encode()),
    )
    cell = SimpleNamespace(
        row_key="period:2025-12", column_key="收入（元）",
        fact_refs=(SimpleNamespace(),) if has_reference else (),
    )
    index = SimpleNamespace(tables=(SimpleNamespace(
        table_id="table-monthly", row_keys=(cell.row_key,), cells=(cell,), origin_markdown=None,
    ),))
    context = SimpleNamespace(scope={"threadId": "thread"}, markdown_path="report.md")
    tables, summary = await service._evaluate_tables(
        index, context, markdown(draft), AsyncMock(return_value=None), _TABLE_BLOCK, value_matches,
    )

    assert summary[expected] == 1
    assert tables[0]["locations"][0]["status"] == expected
