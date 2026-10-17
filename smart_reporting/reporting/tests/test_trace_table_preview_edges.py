import csv
import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
from smart_reporting.reporting.delivery.artifacts_v1 import _TABLE_BLOCK
from smart_reporting.reporting.trace.contracts_v1 import TRACE_BUDGETS_V1
from smart_reporting.reporting.trace.dataset_service import (
    TraceCsvPreviewService,
    TraceDatasetFile,
    TracePreviewPermissions,
)
from smart_reporting.reporting.trace.subject_builder import value_matches
from smart_reporting.reporting.trace.table_builder import render_table_markdown


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    "source_value,source_unit,header,original",
    [
        (10000, "元", "收入（万元）", "1.00"),
        (10000, "人次", "就诊量（万人次）", "1.00"),
        (100000000, "元", "收入（亿元）", "1.00"),
        (1, "万元", "收入（元）", "10,000"),
        (10000, "元", "收入(万元)", "1.00"),
        (10000, "元", "收入（万元） · actual_income", "1.00"),
        (-10000, "元", "收入（万元）", "-1.00"),
        (100, "元", "收入（万元）", "0.01"),
        (10000, "万元", "收入（亿元）", "1.00"),
    ],
)
@pytest.mark.parametrize("keep_original,expected", [(True, "valid"), (False, "stale")])
async def test_table_header_unit_cannot_be_bypassed_by_raw_source_number(
    source_value, source_unit, header, original, keep_original, expected
):
    draft_value = original if keep_original else str(source_value)

    def markdown(value):
        return render_table_markdown("table-scaled", (header,), [["1月", value]])

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
                table_id="table-scaled",
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
        markdown(draft_value),
        AsyncMock(return_value=source_value),
        _TABLE_BLOCK,
        value_matches,
        fact_unit_of=AsyncMock(return_value=source_unit),
    )
    assert summary[expected] == 1, (summary, tables[0]["locations"])


@pytest.mark.parametrize("character", ["\\", "\t"])
def test_preview_budget_measures_json_bytes_including_escaping(tmp_path, character):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(("a", "b", "c"))
    for _ in range(100):
        writer.writerow((character * 3500,) * 3)
    raw = stream.getvalue().encode()
    path = tmp_path / "snapshot.csv"
    path.write_bytes(raw)
    file = TraceDatasetFile(
        "dataset-preview01", path, len(raw), hashlib.sha256(raw).hexdigest(), 100
    )
    page = TraceCsvPreviewService(secret=b"preview").preview(
        file, TracePreviewPermissions(), limit=100
    )
    size = len(json.dumps(page.to_payload(), ensure_ascii=False, separators=(",", ":")).encode())
    maximum = TRACE_BUDGETS_V1["preview_max_response_bytes"]
    assert size <= maximum, (size, maximum, len(page.rows), page.truncated_by_budget)


@pytest.mark.parametrize("character", ["\\", "\t", "\n", "\x01"])
@pytest.mark.parametrize("explicit_columns", [False, True])
def test_budget_truncated_pages_preserve_all_rows_in_order(tmp_path, character, explicit_columns):
    stream = io.StringIO()
    writer = csv.writer(stream)
    columns = ("id", "a", "b", "c")
    writer.writerow(columns)
    for row in range(100):
        writer.writerow((str(row), *((character * 3500,) * 3)))
    raw = stream.getvalue().encode()
    path = tmp_path / "snapshot.csv"
    path.write_bytes(raw)
    file = TraceDatasetFile(
        "dataset-preview01", path, len(raw), hashlib.sha256(raw).hexdigest(), 100
    )
    service = TraceCsvPreviewService(secret=b"preview")
    cursor = None
    ids = []
    for _ in range(100):
        page = service.preview(
            file,
            TracePreviewPermissions(),
            columns=columns if explicit_columns else None,
            limit=100,
            cursor=cursor,
            report_id="report",
            revision=1,
        )
        assert (
            len(json.dumps(page.to_payload(), ensure_ascii=False, separators=(",", ":")).encode())
            <= TRACE_BUDGETS_V1["preview_max_response_bytes"]
        )
        assert page.rows
        ids.extend(row[0] for row in page.rows)
        cursor = page.next_cursor
        if cursor is None:
            break
    else:
        pytest.fail("分页未终止")
    assert ids == list(map(str, range(100)))


def test_truncation_counter_only_includes_returned_cells(tmp_path, monkeypatch):
    from smart_reporting.reporting.trace import dataset_service

    monkeypatch.setattr(dataset_service, "_MAX_RESPONSE_BYTES", 5000)
    raw = ("a\n" + "x" * 3000 + "\n" + "y" * 9000 + "\n").encode()
    path = tmp_path / "snapshot.csv"
    path.write_bytes(raw)
    file = TraceDatasetFile("dataset-preview01", path, len(raw), hashlib.sha256(raw).hexdigest(), 2)
    service = TraceCsvPreviewService(secret=b"preview")
    page = service.preview(file, TracePreviewPermissions(), limit=100)
    assert len(page.rows) == 1 and page.truncated_cells == 0 and page.truncated_by_budget
    assert page.next_cursor is not None
    following = service.preview(file, TracePreviewPermissions(), limit=100, cursor=page.next_cursor)
    assert len(following.rows) == 1 and following.truncated_cells == 1
    assert following.next_cursor is None


def test_metadata_budget_failure_is_reported_instead_of_returning_empty_page(tmp_path, monkeypatch):
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.trace import dataset_service

    monkeypatch.setattr(dataset_service, "_MAX_RESPONSE_BYTES", 100)
    raw = b"a\nvalue\n"
    path = tmp_path / "snapshot.csv"
    path.write_bytes(raw)
    file = TraceDatasetFile("dataset-preview01", path, len(raw), hashlib.sha256(raw).hexdigest(), 1)
    with pytest.raises(ReportingError) as error:
        TraceCsvPreviewService(secret=b"preview").preview(file, TracePreviewPermissions())
    assert error.value.code == "resource_limit_exceeded"


def test_complete_response_overhead_can_shrink_page_without_losing_rows(tmp_path, monkeypatch):
    from smart_reporting.reporting.trace import dataset_service

    monkeypatch.setattr(dataset_service, "_MAX_RESPONSE_BYTES", 1300)
    values = ["a" * 400, "b" * 400, "c" * 400]
    raw = ("a\n" + "\n".join(values) + "\n").encode()
    path = tmp_path / "snapshot.csv"
    path.write_bytes(raw)
    file = TraceDatasetFile("dataset-preview01", path, len(raw), hashlib.sha256(raw).hexdigest(), 3)
    service = TraceCsvPreviewService(secret=b"preview")
    cursor = None
    returned = []
    for page_number in range(3):
        page = service.preview(file, TracePreviewPermissions(), limit=100, cursor=cursor)
        assert (
            len(json.dumps(page.to_payload(), ensure_ascii=False, separators=(",", ":")).encode())
            <= 1300
        )
        if page_number == 0:
            assert page.truncated_by_budget and len(page.rows) < 3
        returned.extend(row[0] for row in page.rows)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert returned == values and cursor is None
