from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tools.toolkit import ReportWorkspaceTaskToolkit


def _toolkit(*, durable_payload: dict | None = None) -> ReportWorkspaceTaskToolkit:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=7))
    toolkit = object.__new__(ReportWorkspaceTaskToolkit)
    toolkit.kernel = SimpleNamespace(
        scope=AsyncMock(return_value=scope),
        finish_task=AsyncMock(return_value={"ok": True, "status": "accepted"}),
    )
    toolkit._finish_function = SimpleNamespace(name="finish_task")
    toolkit._require_phase_tool = lambda *_args, **_kwargs: None
    toolkit._active_reporting_task_kind = lambda *_args: "visualization_section"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "sectionCode": "section_001",
            "visualizationWorkspace": {"chartOutputRoot": "analysis/charts/section_001"},
        },
    )
    toolkit._ensure_visualization_terminal_settled = AsyncMock()
    toolkit._durable_state = AsyncMock(
        return_value=SimpleNamespace(revision=7, payload=durable_payload or {})
    )
    toolkit._apply_durable_command = AsyncMock(return_value=SimpleNamespace(idempotent=False))
    return toolkit


@pytest.mark.anyio
async def test_section_visualization_allows_zero_chart_submission() -> None:
    toolkit = _toolkit()
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert result["ok"] is True
    assert result["chartCount"] == 0
    assert result["taskFinished"] is True
    assert toolkit._apply_durable_command.await_args.kwargs["payload"] == {
        "sectionCode": "section_001",
        "charts": [],
        "files": [],
    }


@pytest.mark.anyio
async def test_section_visualization_rejects_cross_section_submission() -> None:
    toolkit = _toolkit()
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_002",
        charts=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert result["ok"] is False
    assert result["code"] == "report_visualization_section_invalid"
    assert result["message"] == "sectionCode 与当前章节 Task 契约不匹配。"
    toolkit._apply_durable_command.assert_not_awaited()


@pytest.mark.anyio
async def test_section_visualization_rejects_conflicting_repeat_submission() -> None:
    chart = {
        "chartId": "income",
        "sourcePath": "analysis/charts/section_001/income.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation-1"],
        "metricCodes": ["income"],
        "currentPeriod": "2026-01",
        "sourceDatasetId": "dataset-1",
        "aggregationGrain": "month",
        "comparisonPeriod": None,
        "comparisonType": "none",
        "comparability": "strict",
    }
    toolkit = _toolkit(
        durable_payload={"visualizationSections": {"section_001": {"charts": [chart], "files": []}}}
    )
    result = await toolkit.submit_visualization_charts(
        sectionCode="section_001",
        charts=[],
        run_context=RunContext(run_id="run-1", session_id="session-1"),
    )
    assert result["ok"] is False
    assert result["code"] == "report_visualization_section_conflict"
    toolkit._apply_durable_command.assert_not_awaited()


@pytest.mark.anyio
async def test_section_visualization_requires_its_task_kind() -> None:
    toolkit = _toolkit()

    def reject(*_args, **_kwargs) -> None:
        raise ReportingError("report_phase_tool_forbidden", "当前 Task 无权提交图表。")

    toolkit._require_phase_tool = reject
    result = await toolkit.submit_visualization_charts(sectionCode="section_001", charts=[])
    assert result["ok"] is False
    assert result["code"] == "report_phase_tool_forbidden"


def test_visualization_terminal_forbidden_returns_allowed_command() -> None:
    error = ReportingError(
        "report_visualization_terminal_forbidden",
        "visualization terminal 只允许从工作区根目录执行签发脚本。",
        details={"allowedCommand": "python3 analysis/charts/section_001/charts.py"},
    )

    result = ReportWorkspaceTaskToolkit._failure(error, retryable=False)

    assert result["details"] == {"allowedCommand": "python3 analysis/charts/section_001/charts.py"}
    assert result["requiredActions"] == [
        "保持 workdir 为空，仅使用 details.allowedCommand 原样执行签发脚本；"
        "不要改写命令、添加 cd 或执行其他 terminal 命令。"
    ]
