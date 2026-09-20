from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workspace import inspect_report_plotly_file


def _service(payload: object) -> SimpleNamespace:
    content = json.dumps(payload, ensure_ascii=False).encode()
    return SimpleNamespace(
        normalize_path=lambda path, **_kwargs: (path, None),
        read_limited_regular_file=AsyncMock(return_value=content),
    )


@pytest.mark.anyio
async def test_plotly_artifact_accepts_bounded_figure_json() -> None:
    service = _service(
        {
            "data": [{"type": "bar", "x": ["一月", "二月"], "y": [10, 12]}],
            "layout": {"title": {"text": "收入趋势"}},
            "config": {"displaylogo": False},
        }
    )

    result = await inspect_report_plotly_file(
        service,
        thread_id="thread-1",
        path="analysis/charts/income.plotly.json",
    )

    assert result["sourcePath"] == "analysis/charts/income.plotly.json"
    assert result["mediaType"] == "application/vnd.plotly.v1+json"
    assert result["traceCount"] == 1
    assert len(result["sha256"]) == 64


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"data": [{"type": "sunburst", "labels": ["收入"]}]},
        {"data": [{"type": "bar", "x": [1], "y": [2], "src": "remote:1"}]},
        {"data": [{"type": "bar", "x": [1], "y": [2]}], "layout": {"images": [{"source": "https://example.com/x.png"}]}},
        {"data": [{"type": "bar", "x": [1], "y": [2]}], "layout": {"hovertemplate": "<script>alert(1)</script>"}},
        {"data": [{"type": "bar", "x": [1], "y": [2]}], "config": {"onClick": "javascript:alert(1)"}},
        {"data": [{"type": "bar", "x": [1], "y": [2]}], "layout": {"annotations": [{"text": "<script>alert(1)</script>"}]}},
        {"data": [{"type": "bar", "x": [1], "y": [2]}], "layout": {"images": [{"source": "//example.com/x.png"}]}},
        {"data": [{"type": "bar", "x": [float("nan")], "y": [2]}]},
    ],
)
async def test_plotly_artifact_rejects_unsupported_or_executable_content(
    payload: object,
) -> None:
    with pytest.raises(ReportingError, match="Plotly"):
        await inspect_report_plotly_file(
            _service(payload),
            thread_id="thread-1",
            path="analysis/charts/income.plotly.json",
        )


@pytest.mark.anyio
async def test_plotly_artifact_rejects_excessive_trace_count() -> None:
    payload = {"data": [{"type": "bar", "x": [1], "y": [2]}] * 101}

    with pytest.raises(ReportingError, match="Plotly"):
        await inspect_report_plotly_file(
            _service(payload),
            thread_id="thread-1",
            path="analysis/charts/income.plotly.json",
        )
