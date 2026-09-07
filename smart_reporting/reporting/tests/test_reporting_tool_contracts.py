from __future__ import annotations

import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tools.sections import RuntimeSectionsMixin
from smart_reporting.reporting.tools.toolkit import ReportingToolkit
from smart_reporting.task_execution import MAX_TOOL_OUTPUT_READ_BYTES


def _toolkit(*, durable_payload: dict | None = None) -> ReportingToolkit:
    scope = SimpleNamespace(thread_id="thread-1", task=SimpleNamespace(mutation_sequence=7))
    toolkit = object.__new__(ReportingToolkit)
    toolkit.runtime = SimpleNamespace(
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


def test_render_report_section_is_bound_to_toolkit_instance() -> None:
    descriptor = inspect.getattr_static(RuntimeSectionsMixin, "render_report_section")

    assert not isinstance(descriptor, staticmethod)


def test_signed_fact_page_preserves_structured_read_receipt() -> None:
    toolkit = _toolkit()
    path = "报表/智能分析/run-1/facts/revision-1/analysis_001.json"
    toolkit._active_reporting_phase = lambda *_args: "analysis"
    toolkit._active_reporting_task_kind = lambda *_args: "analysis_item"
    toolkit._phase_parameters = lambda *_args: (
        {},
        {
            "currentAnalysisId": "analysis_001",
            "deterministicFactFiles": {"analysis_001": {"path": path}},
        },
    )
    result = {
        "path": path,
        "offset": 0,
        "nextOffset": MAX_TOOL_OUTPUT_READ_BYTES,
        "totalBytes": 125_429,
        "content": "x" * MAX_TOOL_OUTPUT_READ_BYTES,
        "hasMore": True,
        "sha256": "a" * 64,
    }

    preview_bytes = toolkit._tool_preview_bytes(
        SimpleNamespace(),
        "read_file",
        {"path": path},
        result,
    )
    serialized_bytes = len(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )

    assert preview_bytes is not None
    assert preview_bytes >= serialized_bytes


def test_section_evidence_page_preserves_structured_read_receipt() -> None:
    toolkit = _toolkit()
    toolkit._active_reporting_phase = lambda *_args: "section"
    toolkit._active_reporting_task_kind = lambda *_args: "section"
    result = {
        "path": "evidence/section.json",
        "offset": 0,
        "nextOffset": MAX_TOOL_OUTPUT_READ_BYTES,
        "totalBytes": 125_429,
        "content": '{"value":"收入"}' * 3_000,
        "hasMore": True,
        "sha256": "a" * 64,
    }

    preview_bytes = toolkit._tool_preview_bytes(
        SimpleNamespace(),
        "read_file",
        {"path": result["path"]},
        result,
    )

    assert toolkit._retain_bounded_tool_result(SimpleNamespace(), "read_file") is True
    assert preview_bytes is not None
    assert preview_bytes >= len(result["content"].encode())


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

    result = ReportingToolkit._failure(error, retryable=False)

    assert result["details"] == {"allowedCommand": "python3 analysis/charts/section_001/charts.py"}
    assert result["requiredActions"] == [
        "保持 workdir 为空，仅使用 details.allowedCommand 原样执行签发脚本；"
        "不要改写命令、添加 cd 或执行其他 terminal 命令。"
    ]


@pytest.mark.anyio
async def test_visualization_terminal_settlement_uses_runtime_repository() -> None:
    toolkit = object.__new__(ReportingToolkit)
    repository = SimpleNamespace(
        list_executions=AsyncMock(
            return_value=[
                SimpleNamespace(
                    execution_id="execution-1",
                    internal_run_id="internal-1",
                    kind="terminal",
                    status="running",
                )
            ]
        )
    )
    toolkit.runtime = SimpleNamespace(repository=repository)
    scope = SimpleNamespace(external_run_id="external-1", internal_run_id="internal-1")

    with pytest.raises(ReportingError) as rejected:
        await toolkit._ensure_visualization_terminal_settled(scope)

    assert rejected.value.code == "report_visualization_script_running"
    repository.list_executions.assert_awaited_once_with("external-1")
