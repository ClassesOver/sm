from __future__ import annotations

import pytest
from agno.run import RunContext

from smart_reporting.reporting.delivery.report_runtime import REPORT_VISUAL_THEME
from smart_reporting.reporting.instructions import build_report_agent_instructions
from smart_reporting.reporting.phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    reporting_task_kind_from_acceptance_contract,
    reporting_task_kind_from_run_context,
)
from smart_reporting.reporting.tools.capabilities import tools_for_task


def _context(phase: str, task_kind: str) -> RunContext:
    return RunContext(
        run_id=f"run-{task_kind}",
        session_id=f"session-{task_kind}",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_PHASE_DEPENDENCY_KEY: phase,
                REPORTING_TASK_KIND_DEPENDENCY_KEY: task_kind,
            }
        },
    )


@pytest.mark.parametrize(
    ("phase", "task_kind"),
    (
        ("analysis", "analysis_item"),
        ("analysis", "visualization_section"),
        ("section", "section"),
    ),
)
def test_current_task_kinds_are_projected_from_run_context(phase: str, task_kind: str) -> None:
    assert reporting_task_kind_from_run_context(_context(phase, task_kind)) == task_kind


def test_unknown_task_kind_is_not_projected() -> None:
    contract = {
        "requirements": [
            {"parameters": {"phase": "analysis", "phaseContract": {"taskKind": "unknown"}}}
        ]
    }
    assert reporting_task_kind_from_acceptance_contract(contract) is None


def test_visualization_instructions_require_section_submission() -> None:
    instructions = "\n".join(
        build_report_agent_instructions(_context("analysis", "visualization_section"))
    )
    assert "submit_visualization_charts" in instructions
    assert "章节" in instructions
    assert "reportVisualTheme" in instructions
    assert "颜色不得成为唯一信息通道" in instructions


def test_visualization_instruction_theme_projects_report_theme() -> None:
    from smart_reporting.reporting.workflow.runtime.analysis import _visualization_instruction_theme

    assert _visualization_instruction_theme() == REPORT_VISUAL_THEME


def test_capability_matrix_exposes_only_section_visualization_tools() -> None:
    visualization_tools = tools_for_task("analysis", "visualization_section")
    assert visualization_tools is not None
    assert visualization_tools == frozenset(
        {
            "get_skill_instructions",
            "get_skill_reference",
            "inspect_chart",
            "process",
            "read_file",
            "read_tool_output",
            "submit_visualization_charts",
            "terminal",
            "view_image",
            "create_analysis_file",
            "overwrite_analysis_file",
        }
    )
