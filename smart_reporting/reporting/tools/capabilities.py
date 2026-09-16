"""Reporting 固定 Workflow 内部使用的阶段工具能力矩阵。"""

REPORTING_WORKSPACE_TOOL_NAMES = frozenset(
    {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "search_content",
        "move_file",
        "delete_file",
        "run_command",
    }
)

REPORTING_SECTION_TOOL_NAMES = frozenset(
    {
        *REPORTING_WORKSPACE_TOOL_NAMES,
        "read_tool_output",
        "render_report_section",
        "request_analysis_rework",
    }
)
REPORTING_ANALYSIS_ITEM_TOOL_NAMES = frozenset(
    {
        "complete_analysis_item",
        "query_analysis_context",
        "query_analysis_facts",
        "query_profile",
        *REPORTING_WORKSPACE_TOOL_NAMES,
        "read_tool_output",
        "apply_analysis_patch",
        "run_python_script",
    }
)
# 可视化按章节归属：固定 Workflow 提交本章图表，服务端在提交时完成身份校验；
# 不再暴露全局登记/冻结 Agent，最终分析产物由服务端确定性汇总。
REPORTING_VISUALIZATION_SECTION_TOOL_NAMES = frozenset(
    {
        *REPORTING_WORKSPACE_TOOL_NAMES,
        "read_tool_output",
        "submit_visualization_charts",
        "run_python_script",
        "apply_analysis_patch",
    }
)


def tools_for_task(phase: str | None, task_kind: str | None) -> frozenset[str] | None:
    if phase == "section":
        return REPORTING_SECTION_TOOL_NAMES
    if phase == "analysis" and task_kind == "analysis_item":
        return REPORTING_ANALYSIS_ITEM_TOOL_NAMES
    if phase == "analysis" and task_kind == "visualization_section":
        return REPORTING_VISUALIZATION_SECTION_TOOL_NAMES
    return None


__all__ = [
    "REPORTING_ANALYSIS_ITEM_TOOL_NAMES",
    "REPORTING_SECTION_TOOL_NAMES",
    "REPORTING_VISUALIZATION_SECTION_TOOL_NAMES",
    "REPORTING_WORKSPACE_TOOL_NAMES",
    "tools_for_task",
]
