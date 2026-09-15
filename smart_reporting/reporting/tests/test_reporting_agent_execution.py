from __future__ import annotations

import pytest

from smart_reporting.reporting.tools.capabilities import tools_for_task


@pytest.mark.parametrize(
    ("phase", "task_kind", "completion_tool"),
    (
        ("analysis", "analysis_item", "complete_analysis_item"),
        ("analysis", "visualization_section", "submit_visualization_charts"),
        ("section", "section", "render_report_section"),
    ),
)
def test_agent_task_kind_exposes_its_own_completion_tool(
    phase: str, task_kind: str, completion_tool: str
) -> None:
    tools = tools_for_task(phase, task_kind)
    assert tools is not None
    assert completion_tool in tools


def test_visualization_agent_exposes_only_its_section_toolset() -> None:
    tools = tools_for_task("analysis", "visualization_section")
    assert tools == frozenset(
        {
            "delete_file",
            "edit_file",
            "inspect_chart",
            "list_files",
            "move_file",
            "read_file",
            "read_tool_output",
            "run_command",
            "run_python_script",
            "search_content",
            "submit_visualization_charts",
            "view_image",
            "write_file",
            "apply_analysis_patch",
        }
    )
