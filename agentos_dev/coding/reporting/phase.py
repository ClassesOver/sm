"""Reporting 内部 run 的受信 phase 绑定与工具投影。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from agno.run import RunContext

ReportingPhase = Literal["analysis", "section"]

REPORTING_PHASE_DEPENDENCY_KEY = "reportingPhase"
REPORTING_TASK_DEPENDENCY = "AgentOS 编码任务"

# SectionWorkItem 已给出全部授权 evidence 路径和引用；章节 run 不得再执行脚本、
# 修改工作区或浏览其他目录。大型只读结果仍可通过 outputHandle 分段恢复。
REPORTING_SECTION_TOOL_NAMES = frozenset(
    {
        "finish_task",
        "read_file",
        "read_lines",
        "read_tool_output",
        "render_report_section",
        "request_analysis_rework",
    }
)
REPORTING_ANALYSIS_FORBIDDEN_TOOL_NAMES = frozenset(
    {"render_report_section", "request_analysis_rework"}
)


def reporting_phase_from_acceptance_contract(value: Any) -> ReportingPhase | None:
    if not isinstance(value, Mapping):
        return None
    requirements = value.get("requirements")
    if (
        not isinstance(requirements, Sequence)
        or isinstance(requirements, (str, bytes))
        or len(requirements) != 1
    ):
        return None
    requirement = requirements[0]
    if not isinstance(requirement, Mapping):
        return None
    parameters = requirement.get("parameters")
    phase = parameters.get("phase") if isinstance(parameters, Mapping) else None
    return phase if phase in {"analysis", "section"} else None


def reporting_phase_from_run_context(run_context: RunContext | None) -> ReportingPhase | None:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    phase = binding.get(REPORTING_PHASE_DEPENDENCY_KEY) if isinstance(binding, Mapping) else None
    return phase if phase in {"analysis", "section"} else None


def reporting_phase_allows_tool(phase: ReportingPhase | None, tool_name: str) -> bool:
    if phase == "section":
        return tool_name in REPORTING_SECTION_TOOL_NAMES
    if phase == "analysis":
        return tool_name not in REPORTING_ANALYSIS_FORBIDDEN_TOOL_NAMES
    return True
