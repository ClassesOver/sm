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
# 可视化按章节并行化(Spec §6.3):章节执行期只产出图稿与分析文件,不接触 report
# 级注册/冻结终态;finalize 阶段才合并注册并冻结。两矩阵互补且互斥,任何章节 run
# 都无法绕过 finalize 收口(见第 8 节不变量)。
REPORTING_VISUALIZATION_SECTION_TOOL_NAMES = frozenset(
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
        "write_analysis_files",
    }
)
REPORTING_VISUALIZATION_FINALIZE_TOOL_NAMES = frozenset(
    {
        "finalize_report_analysis",
        "get_skill_instructions",
        "read_file",
        "read_tool_output",
        "register_report_charts",
        "write_analysis_files",
    }
)


def tools_for_task(phase: str | None, task_kind: str | None) -> frozenset[str] | None:
    if phase == "section":
        return REPORTING_SECTION_TOOL_NAMES
    if phase == "analysis" and task_kind == "analysis_item":
        return REPORTING_ANALYSIS_ITEM_TOOL_NAMES
    if phase == "analysis" and task_kind == "visualization":
        # 历史 run 恢复期读取:legacy visualization trace 校验通过后仍需投影出
        # 旧能力集合,见第 8 节。新 run 不再携带该 task_kind。
        return REPORTING_VISUALIZATION_TOOL_NAMES
    if phase == "analysis" and task_kind == "visualization_section":
        return REPORTING_VISUALIZATION_SECTION_TOOL_NAMES
    if phase == "analysis" and task_kind == "visualization_finalize":
        return REPORTING_VISUALIZATION_FINALIZE_TOOL_NAMES
    return None


__all__ = [
    "REPORTING_ANALYSIS_ITEM_TOOL_NAMES",
    "REPORTING_SECTION_TOOL_NAMES",
    "REPORTING_VISUALIZATION_FINALIZE_TOOL_NAMES",
    "REPORTING_VISUALIZATION_SECTION_TOOL_NAMES",
    "REPORTING_VISUALIZATION_TOOL_NAMES",
    "tools_for_task",
]
