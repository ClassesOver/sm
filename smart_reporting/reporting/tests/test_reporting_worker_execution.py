from __future__ import annotations

import pytest

from smart_reporting.reporting.tools.capabilities import tools_for_task


@pytest.mark.parametrize(
    ("phase", "task_kind", "required_terminal"),
    (
        ("analysis", "analysis_item", "complete_analysis_item"),
        ("analysis", "visualization_section", "submit_visualization_charts"),
        ("section", "section", "render_report_section"),
    ),
)
def test_worker_task_kind_exposes_its_own_terminal_tool(
    phase: str, task_kind: str, required_terminal: str
) -> None:
    tools = tools_for_task(phase, task_kind)
    assert tools is not None
    assert required_terminal in tools


def test_visualization_worker_exposes_only_its_section_toolset() -> None:
    tools = tools_for_task("analysis", "visualization_section")
    assert tools == frozenset(
        {
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
