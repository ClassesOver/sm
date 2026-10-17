"""图表来源响应不泄露内部路径，并执行已有预览资源预算。"""

import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.trace_sources import ReportEditorTraceService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.trace.contracts_v1 import TRACE_BUDGETS_V1


def preview(document, **kwargs):
    content = json.dumps(document, ensure_ascii=False).encode()
    return ReportEditorTraceService._chart_input_payload(
        content, file_ref=SimpleNamespace(
            resource_id="trf-" + "a" * 20, size=len(content), sha256=hashlib.sha256(content).hexdigest(),
        ), limit=100, offset=0, **kwargs,
    )


def test_chart_preview_only_exposes_public_source_metadata():
    source = {
        "analysisId": "analysis_001", "path": "reports/private/facts/analysis_001.json",
        "sha256": "a" * 64, "dataPath": "metrics[0].periodValues",
        "internal": {"path": "/private/workspace"},
    }
    result = preview({"columns": ["period", "value"], "rows": [["2025-01", 1]], "source": source})
    assert result["source"] == {key: source[key] for key in ("analysisId", "sha256", "dataPath")}
    assert "private" not in json.dumps(result)


@pytest.mark.parametrize("document", [
    {"columns": ["label"], "rows": [["长" * 2000]]},
    {"columns": ["c"] * 51, "rows": [[1] * 51]},
    {"columns": ["长" * 2000], "rows": [[1]]},
    {"columns": [f"c{i}" for i in range(50)], "rows": [["x" * 3000] * 50 for _ in range(10)]},
])
def test_chart_preview_enforces_cell_column_and_response_budgets(document):
    with pytest.raises(ReportingError) as error:
        preview(document)
    assert error.value.code == "resource_limit_exceeded"


@pytest.mark.parametrize("rows", [[[1, 2]], ["wrong row"], [[{"value": 1}]], [[float("nan")]]])
def test_chart_preview_rejects_invalid_rows(rows):
    with pytest.raises(ReportingError) as error:
        preview({"columns": ["value"], "rows": rows})
    assert error.value.code == "snapshot_integrity_failed"


def test_chart_preview_budget_matches_utf8_response_size():
    document = {"columns": ["a", "b", "c"], "rows": [["汉" * 1000] * 3 for _ in range(100)]}
    result = preview(document)
    assert result["rows"] == document["rows"]
    assert len(json.dumps(result, ensure_ascii=False).encode("utf-8")) < TRACE_BUDGETS_V1["preview_max_response_bytes"]


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_combined_chart_sources_cannot_bypass_response_budget(monkeypatch):
    service = ReportEditorTraceService(None, cursor_secret=b"chart-test")
    document = {"columns": [f"c{i}" for i in range(50)], "rows": [["x" * 3000] * 50 for _ in range(4)]}
    content = json.dumps(document).encode()
    assert len(content) < TRACE_BUDGETS_V1["preview_max_response_bytes"]
    refs = tuple(SimpleNamespace(resource_id=f"file-{i}", size=len(content), sha256="a" * 64) for i in range(3))
    trace = SimpleNamespace(
        chart_id="chart_001", image_file_resource_id="file-0",
        plot_data_file_resource_ids=("file-1", "file-2"), dataset_ids=(),
        transform_notes=(), computation_id=None,
    )

    async def index(_context):
        return SimpleNamespace(files=refs, chart_traces=(trace,))

    async def read(*_args, **_kwargs):
        return content

    monkeypatch.setattr(service, "require_index", index)
    monkeypatch.setattr(service, "_read_registered_file", read)
    try:
        with pytest.raises(ReportingError) as error:
            await service.chart_source(SimpleNamespace(), "chart_001")
        assert error.value.code == "resource_limit_exceeded"
    finally:
        await service.exports.aclose()
