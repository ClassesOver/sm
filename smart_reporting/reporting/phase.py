"""Reporting 内部 run 的受信 phase 绑定与工具投影。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from agno.run import RunContext

ReportingPhase = Literal["analysis", "section"]
ReportingTaskKind = Literal["analysis_item", "visualization", "section"]

# Reporting 使用 1M 模型窗口。phase hard cap 是注意力预算，不是事实层上限：
# 全局分析和独立章节只投影当前任务需要的事实摘要；完整 Profile、证据正文和
# 工具结果继续通过受信文件与 outputHandle 按需读取。
# 输出仍由模型级 reserve 单独预留，完整 Profile、工具原文和历史继续留在 checkpoint/handle。
REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP = 128 * 1024
REPORTING_SECTION_INPUT_TOKEN_HARD_CAP = 48 * 1024

REPORTING_PHASE_DEPENDENCY_KEY = "reportingPhase"
REPORTING_TASK_KIND_DEPENDENCY_KEY = "reportingTaskKind"
REPORTING_THINKING_EFFORT_DEPENDENCY_KEY = "reportingThinkingEffort"
REPORTING_TASK_DEPENDENCY = "AgentOS 编码任务"

# 工具按生命周期白名单暴露。Agno callable-tool 缓存键包含 phase/taskKind，实际 Toolkit、
# 模型请求和执行入口都只接受当前阶段白名单中的工具。
# SectionWorkItem 已给出全部授权 evidence 路径和引用；章节 run 不得再执行脚本、
# 修改工作区或浏览其他目录。大型只读结果仍可通过 outputHandle 分段恢复。
REPORTING_SECTION_TOOL_NAMES = frozenset(
    {
        "finish_task",
        "read_file",
        "read_tool_output",
        "render_report_section",
        "request_analysis_rework",
    }
)
# 全局分析只保留当前事实、证据生成和 checkpoint 所需工具。Profile 精确读取统一走
# query_profile；read_profile_pointer 仍保留为内部持久化/历史回放 API，但不再给模型第二
# 个等价入口。原始文件统一用 read_file，避免 read_lines/search_text 与 JMESPath 查询
# 形成三套检索方式。process 是 terminal 后台执行的必要伴随工具，不能与 terminal 合并。
REPORTING_ANALYSIS_ITEM_TOOL_NAMES = frozenset(
    {
        "complete_analysis_item",
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
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
        "finish_task",
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
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
_REPORTING_PROJECTION_METRICS: ContextVar[dict[str, int] | None] = ContextVar(
    "reporting_projection_metrics", default=None
)
_REPORTING_RUN_CONTEXT: ContextVar[RunContext | None] = ContextVar(
    "reporting_run_context", default=None
)


@contextmanager
def bind_reporting_run_context(run_context: RunContext) -> Iterator[None]:
    """让模型投影与工具执行读取同一个 Agno RunContext，不复制业务状态。"""

    token = _REPORTING_RUN_CONTEXT.set(run_context)
    try:
        yield
    finally:
        _REPORTING_RUN_CONTEXT.reset(token)


def current_reporting_run_context() -> RunContext | None:
    return _REPORTING_RUN_CONTEXT.get()


@contextmanager
def capture_reporting_projection_metrics() -> Iterator[dict[str, int]]:
    """聚合当前内部 run 的真实模型投影，不跨并发 Task 共享状态。"""

    metrics = {
        "modelRequestCount": 0,
        "maxCanonicalTokens": 0,
        "maxProjectedTokens": 0,
        "rebaseCount": 0,
        "inputTokenHardCap": 0,
        "completedAnalysisCount": 0,
        "toolEventCount": 0,
    }
    token = _REPORTING_PROJECTION_METRICS.set(metrics)
    try:
        yield metrics
    finally:
        _REPORTING_PROJECTION_METRICS.reset(token)


def record_reporting_projection_metrics(
    metrics: Mapping[str, Any], *, input_token_hard_cap: int
) -> None:
    current = _REPORTING_PROJECTION_METRICS.get()
    if current is None:
        return
    current["modelRequestCount"] += 1
    for source, target in (
        ("canonical_estimated_tokens", "maxCanonicalTokens"),
        ("projected_estimated_tokens", "maxProjectedTokens"),
        ("completed_analysis_count", "completedAnalysisCount"),
    ):
        value = metrics.get(source)
        if not isinstance(value, bool) and isinstance(value, int) and value >= 0:
            current[target] = max(current[target], value)
    if metrics.get("window_rebased") is True:
        current["rebaseCount"] += 1
    if input_token_hard_cap > 0:
        current_cap = current["inputTokenHardCap"]
        current["inputTokenHardCap"] = (
            input_token_hard_cap if current_cap == 0 else min(current_cap, input_token_hard_cap)
        )


def record_reporting_tool_event(event: Any) -> None:
    """记录与 CLI 一致的工具完成/失败事件，只用于性能观测。"""

    current = _REPORTING_PROJECTION_METRICS.get()
    if current is None:
        return
    raw_event = getattr(event, "event", None) or getattr(event, "type", None)
    event_type = str(getattr(raw_event, "value", raw_event) or "").replace("_", "").lower()
    if event_type in {"toolcallcompleted", "toolcallerror"}:
        current["toolEventCount"] += 1


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


def reporting_task_kind_from_acceptance_contract(value: Any) -> ReportingTaskKind | None:
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
    parameters = requirement.get("parameters") if isinstance(requirement, Mapping) else None
    phase_contract = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
    task_kind = phase_contract.get("taskKind") if isinstance(phase_contract, Mapping) else None
    return task_kind if task_kind in {"analysis_item", "visualization", "section"} else None


def reporting_thinking_effort_from_acceptance_contract(
    value: Any,
) -> Literal["off", "high", "max"] | None:
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
    parameters = requirement.get("parameters") if isinstance(requirement, Mapping) else None
    phase_contract = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
    effort = phase_contract.get("thinkingEffort") if isinstance(phase_contract, Mapping) else None
    return effort if effort in {"off", "high", "max"} else None


def reporting_phase_from_run_context(run_context: RunContext | None) -> ReportingPhase | None:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    phase = binding.get(REPORTING_PHASE_DEPENDENCY_KEY) if isinstance(binding, Mapping) else None
    return phase if phase in {"analysis", "section"} else None


def reporting_task_kind_from_run_context(
    run_context: RunContext | None,
) -> ReportingTaskKind | None:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    task_kind = (
        binding.get(REPORTING_TASK_KIND_DEPENDENCY_KEY) if isinstance(binding, Mapping) else None
    )
    return task_kind if task_kind in {"analysis_item", "visualization", "section"} else None


def reporting_thinking_effort_from_run_context(
    run_context: RunContext | None,
) -> Literal["off", "high", "max"] | None:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    effort = (
        binding.get(REPORTING_THINKING_EFFORT_DEPENDENCY_KEY)
        if isinstance(binding, Mapping)
        else None
    )
    return effort if effort in {"off", "high", "max"} else None


def reporting_phase_allows_tool(
    phase: ReportingPhase | None,
    tool_name: str,
    *,
    task_kind: ReportingTaskKind | None = None,
) -> bool:
    if phase == "section":
        return tool_name in REPORTING_SECTION_TOOL_NAMES
    if phase == "analysis":
        if task_kind == "analysis_item":
            return tool_name in REPORTING_ANALYSIS_ITEM_TOOL_NAMES
        if task_kind == "visualization":
            return tool_name in REPORTING_VISUALIZATION_TOOL_NAMES
        return False
    return True
