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
    "source_unit,header", [("元", "收入（万元）"), ("人次", "就诊量（万人次）")]
)
@pytest.mark.parametrize(
    "draft_value,expected",
    [
        ("约1.00", "valid"),
        ("1.00（估算）", "valid"),
        ("约10000", "stale"),
        ("10000（估算）", "stale"),
        ("合计10000", "stale"),
        ("合计1.00", "valid"),
        ("约1（估算）", "valid"),
        ("1.00（原值10000）", "valid"),
        ("2025年估算1.00", "valid"),
        ("约10000{unit}（估算）", "valid"),
        ("1{display_unit}（估算）", "valid"),
        ("1.00{unit}", "stale"),
        ("1美元", "stale"),
        ("10000（1{display_unit}）", "stale"),
        ("约10,000", "stale"),
        ("1.00（2025年估算）", "valid"),
        ("0.01（原值10000）", "stale"),
        ("1{unit}（实际应为10000）", "stale"),
        ("约1%", "stale"),
    ],
)
async def test_table_header_unit_cannot_be_bypassed_by_raw_source_number(
    source_unit, header, draft_value, expected, source_value=10000
):
    draft_value = draft_value.format(
        unit=source_unit, display_unit="万元" if source_unit == "元" else "万人次"
    )

    def markdown(value):
        return render_table_markdown("table-scaled", (header,), [["1月", value]])

    service = object.__new__(ReportEditorTraceService)
    service._workspace = SimpleNamespace(
        read_limited_regular_file=AsyncMock(return_value=markdown("1.00").encode())
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
                table_id="table-scaled",
                row_keys=(cell.row_key,),
                cells=(cell,),
                origin_markdown=markdown("1.00"),
            ),
        )
    )
    context = SimpleNamespace(scope={"threadId": "thread"}, markdown_path="report.md")
    tables, summary = await service._evaluate_tables(
        index,
        context,
        markdown(draft_value),
        AsyncMock(return_value=source_value),
        _TABLE_BLOCK,
        value_matches,
        fact_unit_of=AsyncMock(return_value=source_unit),
    )
    assert summary[expected] == 1, (summary, tables[0]["locations"])


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "source_value,text,expected",
    [
        (-10000, "减少1.00（冲回）", "valid"),
        (-10000, "增加1.00", "stale"),
        (-10000, "-1.00（冲回）", "valid"),
        (0, "约0（估算）", "valid"),
        (0, "10000（备注0）", "stale"),
    ],
)
async def test_annotated_zero_and_negative_values_preserve_sign(source_value, text, expected):
    await test_table_header_unit_cannot_be_bypassed_by_raw_source_number(
        "元", "收入（万元）", text, expected, source_value=source_value
    )
