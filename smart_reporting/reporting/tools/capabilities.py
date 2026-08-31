"""Reporting Worker 的唯一阶段工具能力矩阵。"""

REPORTING_SECTION_TOOL_NAMES = frozenset(
    {"read_file", "read_tool_output", "render_report_section", "request_analysis_rework"}
)
REPORTING_ANALYSIS_ITEM_TOOL_NAMES = frozenset(
    {
        "complete_analysis_item",
        "process",
        "query_analysis_context",
        "query_analysis_facts",
        "query_profile",
        "read_file",
        "read_tool_output",
        "write_analysis_files",
        "terminal",
    }
)
REPORTING_VISUALIZATION_TOOL_NAMES = frozenset(
    {
        "finalize_report_analysis",
        "get_skill_instructions",
        "get_skill_reference",
        "inspect_chart",
        "process",
        "query_analysis_context",
        "query_analysis_facts",
        "read_file",
        "read_tool_output",
        "register_report_charts",
        "write_analysis_files",
        "terminal",
        "view_image",
    }
)


def tools_for_task(phase: str | None, task_kind: str | None) -> frozenset[str] | None:
    if phase == "section":
        return REPORTING_SECTION_TOOL_NAMES
    if phase == "analysis" and task_kind == "analysis_item":
        return REPORTING_ANALYSIS_ITEM_TOOL_NAMES
    if phase == "analysis" and task_kind == "visualization":
        return REPORTING_VISUALIZATION_TOOL_NAMES
    return None


__all__ = [
    "REPORTING_ANALYSIS_ITEM_TOOL_NAMES",
    "REPORTING_SECTION_TOOL_NAMES",
    "REPORTING_VISUALIZATION_TOOL_NAMES",
    "tools_for_task",
]
