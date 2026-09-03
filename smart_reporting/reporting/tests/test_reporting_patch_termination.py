from __future__ import annotations

import json

import pytest
from agno.exceptions import StopAgentRun
from agno.run import RunContext

from smart_reporting.reporting.agent import normalize_reporting_tool_arguments
from smart_reporting.reporting.phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
)


def _context(task_kind: str) -> RunContext:
    return RunContext(
        run_id="internal-run",
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: "analysis",
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )


@pytest.mark.anyio
@pytest.mark.parametrize("task_kind", ["analysis_item", "visualization_section"])
async def test_rejected_analysis_patch_stops_current_run_for_fresh_retry(task_kind: str) -> None:
    context = _context(task_kind)
    calls = 0

    def rejected_patch(**_arguments: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {
            "ok": False,
            "status": "rejected",
            "code": "report_analysis_write_intent_invalid",
            "message": "标准 unified diff 语法无效。",
            "details": {"toolName": "apply_analysis_patch"},
        }

    with pytest.raises(StopAgentRun) as raised:
        await normalize_reporting_tool_arguments(
            context,
            "apply_analysis_patch",
            rejected_patch,
            {"patch": "invalid"},
        )

    receipt = json.loads(str(raised.value))
    assert calls == 1
    assert receipt["code"] == "report_analysis_write_intent_invalid"
    assert receipt["retryable"] is False
    assert receipt["runDisposition"] == "stop_current_run"
    assert receipt["recovery"] == {"kind": "fresh_task_retry"}
    assert getattr(context, "_agentos_reporting_tool_run_error").code == receipt["code"]


@pytest.mark.anyio
async def test_non_patch_rejection_keeps_existing_feedback_loop() -> None:
    context = _context("analysis_item")

    result = await normalize_reporting_tool_arguments(
        context,
        "terminal",
        lambda **_arguments: {
            "ok": False,
            "status": "rejected",
            "code": "tool_no_progress",
            "message": "没有变化。",
        },
        {"command": "true"},
    )

    assert result["code"] == "tool_no_progress"
