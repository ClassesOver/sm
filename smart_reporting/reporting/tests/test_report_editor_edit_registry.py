"""改图、改表共享侧车的故障域隔离。"""

from __future__ import annotations

import json

import pytest

from smart_reporting.report_editor.chart_edits import (
    ChartEditChartMeta,
    ChartEditFileRef,
    ChartEditRecord,
    TableEditRecord,
    append_chart_edit_record,
    append_table_edit_record,
    chart_edits_registry_path,
    parse_chart_edit_records,
    parse_table_edit_records,
)


class _MemoryWorkspace:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def apath_exists(self, _thread_id: str, _path: str) -> bool:
        return True

    async def afile_bytes(self, _thread_id: str, _path: str) -> tuple[bytes, str]:
        return self.content, "application/json"

    async def awrite_bytes(
        self, _thread_id: str, _path: str, content: bytes, *, overwrite: bool
    ) -> None:
        assert overwrite
        self.content = content


def _chart_record() -> ChartEditRecord:
    return ChartEditRecord(
        editId="cedit-0123456789abcdef",
        chartId="chart-1",
        baseImagePath="reports/revision-1/chart.png",
        baseImageSha256="0" * 64,
        instruction="换配色",
        level=("L1",),
        image=ChartEditFileRef(path="chart-edits/c/chart.png", size=1, sha256="1" * 64),
        script=ChartEditFileRef(path="chart-edits/c/chart.py", size=1, sha256="2" * 64),
        plotDataFiles=(
            ChartEditFileRef(path="chart-input.json", size=1, sha256="3" * 64),
        ),
        chart=ChartEditChartMeta(
            title="图", altText="图", visualForm="bar", datasetIds=("dataset-1",)
        ),
        createdAt="2026-10-26T00:00:00+00:00",
        userId="user-1",
    )


def _table_record() -> TableEditRecord:
    return TableEditRecord(
        editId="tedit-0123456789abcdef",
        tableId="table-1",
        analysisId="analysis-1",
        newTableId="table-1-edit",
        instruction="增加合计",
        bodySha256="4" * 64,
        markdown="[[table:table-1-edit]]\n| A |\n|---|\n| 1 |\n\n[[/table:table-1-edit]]",
        createdAt="2026-10-26T00:00:00+00:00",
        userId="user-1",
    )


def test_registry_parsers_isolate_chart_and_table_corruption() -> None:
    corrupt_table = b'{"version":1,"records":[],"tableEdits":[42]}'
    assert parse_chart_edit_records(corrupt_table) == ()
    with pytest.raises(ValueError, match="改表登记记录损坏"):
        parse_table_edit_records(corrupt_table)

    corrupt_chart = b'{"version":1,"records":[42],"tableEdits":[]}'
    assert parse_table_edit_records(corrupt_chart) == ()
    with pytest.raises(ValueError, match="改图登记记录损坏"):
        parse_chart_edit_records(corrupt_chart)


@pytest.mark.anyio
async def test_append_chart_preserves_corrupt_table_entries() -> None:
    workspace = _MemoryWorkspace(b'{"version":1,"records":[],"tableEdits":[42]}')
    await append_chart_edit_record(workspace, "thread", "reports/revision-1/report.md", _chart_record())

    payload = json.loads(workspace.content)
    assert payload["tableEdits"] == [42]
    assert [item.edit_id for item in parse_chart_edit_records(workspace.content)] == [
        "cedit-0123456789abcdef"
    ]


@pytest.mark.anyio
async def test_append_table_preserves_corrupt_chart_entries() -> None:
    workspace = _MemoryWorkspace(b'{"version":1,"records":[42],"tableEdits":[]}')
    await append_table_edit_record(workspace, "thread", "reports/revision-1/report.md", _table_record())

    payload = json.loads(workspace.content)
    assert payload["records"] == [42]
    assert [item.edit_id for item in parse_table_edit_records(workspace.content)] == [
        "tedit-0123456789abcdef"
    ]
    assert chart_edits_registry_path("reports/revision-1/report.md").endswith(
        "draft/.chart-edits.json"
    )
