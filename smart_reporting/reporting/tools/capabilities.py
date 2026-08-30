"""Reporting Worker 的唯一阶段工具能力矩阵。"""

from ..phase import (
    REPORTING_ANALYSIS_ITEM_TOOL_NAMES,
    REPORTING_SECTION_TOOL_NAMES,
    REPORTING_VISUALIZATION_TOOL_NAMES,
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
