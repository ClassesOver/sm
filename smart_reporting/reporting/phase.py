"""Reporting 内部 run 的受信 phase 绑定与工具投影。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from agno.run import RunContext

from .models import ReportingError

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
REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY = "reportingVisualizationRegistered"
REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY = "reportingVisualizationToolCalls"
REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY = "reportingVisualizationScriptFailures"
REPORTING_VISUALIZATION_BUDGET_VERSION_DEPENDENCY_KEY = "visualizationBudgetVersion"
REPORTING_VISUALIZATION_EVIDENCE_READ_UNITS_DEPENDENCY_KEY = "visualizationEvidenceReadUnits"
REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY = "visualizationReadUnitsUsed"
REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY = "visualizationFactQueriesUsed"
REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY = "visualizationReadLimit"
REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY = "visualizationFactQueryLimit"
REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY = "visualizationAttemptToolLimit"
REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY = "visualizationTotalToolLimit"
REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY = "reportingVisualizationRecovery"
REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY = "agentos_reporting_visualization_tool_budget"
REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR = "_agentos_reporting_visualization_budget"
REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY = "analysisFactBudgetVersion"
REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY = "analysisFactQueryLimit"
REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY = "analysisFactQueriesUsed"
REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY = "analysisRecovery"
REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY = "agentos_reporting_analysis_fact_budget"
REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR = "_agentos_reporting_analysis_fact_budget"
REPORTING_ANALYSIS_FACT_QUERY_LIMIT = 2
REPORTING_TASK_DEPENDENCY = "AgentOS 编码任务"

# 工具按生命周期白名单暴露。Agno callable-tool 缓存键包含 phase/taskKind，实际 Toolkit、
# 模型请求和执行入口都只接受当前阶段白名单中的工具。
# SectionWorkItem 已给出全部授权 evidence 路径和引用；章节 run 不得再执行脚本、
# 修改工作区或浏览其他目录。大型只读结果仍可通过 outputHandle 分段恢复。
REPORTING_SECTION_TOOL_NAMES = frozenset(
    {
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
# 可视化阶段的探索工具必须有独立上限；否则模型可能在创建脚本前耗尽总预算。
REPORTING_VISUALIZATION_FACT_QUERY_LIMIT = 4
REPORTING_VISUALIZATION_READ_FILE_LIMIT = 12
REPORTING_VISUALIZATION_EXPLORATION_TOOL_NAMES = frozenset(
    {
        "get_skill_instructions",
        "get_skill_reference",
        "query_analysis_context",
        "query_analysis_facts",
        "read_file",
        "read_tool_output",
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
        "modelInputTokens": 0,
        "modelOutputTokens": 0,
        "modelTotalTokens": 0,
        "modelReasoningTokens": 0,
        "modelCacheReadTokens": 0,
        "modelCacheWriteTokens": 0,
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
    if event_type == "modelrequestcompleted":
        for field, alias in (
            ("input_tokens", "modelInputTokens"),
            ("output_tokens", "modelOutputTokens"),
            ("total_tokens", "modelTotalTokens"),
            ("reasoning_tokens", "modelReasoningTokens"),
            ("cache_read_tokens", "modelCacheReadTokens"),
            ("cache_write_tokens", "modelCacheWriteTokens"),
        ):
            value = getattr(event, field, None)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                current[alias] += value


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


def reporting_visualization_registered_from_acceptance_contract(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    requirements = value.get("requirements")
    if (
        not isinstance(requirements, Sequence)
        or isinstance(requirements, (str, bytes))
        or len(requirements) != 1
    ):
        return False
    requirement = requirements[0]
    parameters = requirement.get("parameters") if isinstance(requirement, Mapping) else None
    phase_contract = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
    return (
        phase_contract.get("chartsRegistered") is True
        if isinstance(phase_contract, Mapping)
        else False
    )


def reporting_visualization_recovery_from_acceptance_contract(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    requirements = value.get("requirements")
    if (
        not isinstance(requirements, Sequence)
        or isinstance(requirements, (str, bytes))
        or len(requirements) != 1
    ):
        return False
    requirement = requirements[0]
    parameters = requirement.get("parameters") if isinstance(requirement, Mapping) else None
    phase_contract = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
    return (
        phase_contract.get("visualizationRecovery") is True
        if isinstance(phase_contract, Mapping)
        else False
    )


def reporting_visualization_budget_from_acceptance_contract(value: Any) -> tuple[int, int]:
    """读取 Workflow 签发的可视化累计预算，拒绝模型输入覆盖计数。"""

    if not isinstance(value, Mapping):
        return 0, 0
    requirements = value.get("requirements")
    if (
        not isinstance(requirements, Sequence)
        or isinstance(requirements, (str, bytes))
        or len(requirements) != 1
    ):
        return 0, 0
    requirement = requirements[0]
    parameters = requirement.get("parameters") if isinstance(requirement, Mapping) else None
    phase_contract = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
    if not isinstance(phase_contract, Mapping) or phase_contract.get("taskKind") != "visualization":
        return 0, 0

    def count(key: str) -> int:
        raw = phase_contract.get(key, 0)
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0

    return count("visualizationToolCalls"), count("visualizationScriptFailures")


def reporting_visualization_budget_contract_from_acceptance_contract(
    value: Any,
) -> dict[str, int]:
    """读取服务端签发的动态预算；历史契约保持原固定预算语义。"""

    phase_contract: Mapping[str, Any] = {}
    if isinstance(value, Mapping):
        requirements = value.get("requirements")
        if (
            isinstance(requirements, Sequence)
            and not isinstance(requirements, (str, bytes))
            and len(requirements) == 1
            and isinstance(requirements[0], Mapping)
        ):
            parameters = requirements[0].get("parameters")
            candidate = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
            if isinstance(candidate, Mapping) and candidate.get("taskKind") == "visualization":
                phase_contract = candidate

    def count(key: str, default: int = 0) -> int:
        raw = phase_contract.get(key, default)
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else default

    if "visualizationBudgetVersion" not in phase_contract:
        return {
            "visualizationBudgetVersion": 0,
            "visualizationEvidenceReadUnits": 0,
            "visualizationReadLimit": REPORTING_VISUALIZATION_READ_FILE_LIMIT,
            "visualizationFactQueryLimit": REPORTING_VISUALIZATION_FACT_QUERY_LIMIT,
            "visualizationAttemptToolLimit": 48,
            "visualizationTotalToolLimit": 64,
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": count("visualizationToolCalls"),
            "visualizationScriptFailures": count("visualizationScriptFailures"),
        }

    version = phase_contract.get("visualizationBudgetVersion")
    required_nonnegative = (
        "visualizationEvidenceReadUnits",
        "visualizationReadUnitsUsed",
        "visualizationFactQueriesUsed",
        "visualizationToolCalls",
        "visualizationScriptFailures",
    )
    required_positive = (
        "visualizationReadLimit",
        "visualizationFactQueryLimit",
        "visualizationAttemptToolLimit",
        "visualizationTotalToolLimit",
    )
    invalid = [
        key
        for key in (*required_nonnegative, *required_positive)
        if not isinstance(phase_contract.get(key), int)
        or isinstance(phase_contract.get(key), bool)
        or phase_contract[key] < int(key in required_positive)
    ]
    if version != 1 or invalid:
        # version 字段一旦存在就是新协议，不能再借用历史默认值补齐签发缺口。
        raise ReportingError(
            "report_phase_contract_invalid",
            "visualization v1 动态预算标量缺失或无效。",
            details={"invalidFields": invalid, "version": version},
        )
    return {
        "visualizationBudgetVersion": 1,
        **{key: phase_contract[key] for key in (*required_nonnegative, *required_positive)},
    }


def reporting_analysis_fact_budget_contract_from_acceptance_contract(
    value: Any,
) -> dict[str, int | bool]:
    """读取单项分析 facts 子预算；新版本契约缺字段时不得退回宽松默认。"""

    phase_contract: Mapping[str, Any] = {}
    if isinstance(value, Mapping):
        requirements = value.get("requirements")
        if (
            isinstance(requirements, Sequence)
            and not isinstance(requirements, (str, bytes))
            and len(requirements) == 1
            and isinstance(requirements[0], Mapping)
        ):
            parameters = requirements[0].get("parameters")
            candidate = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
            if isinstance(candidate, Mapping) and candidate.get("taskKind") == "analysis_item":
                phase_contract = candidate

    if "analysisFactBudgetVersion" not in phase_contract:
        return {
            "analysisFactBudgetVersion": 0,
            "analysisFactQueryLimit": REPORTING_ANALYSIS_FACT_QUERY_LIMIT,
            "analysisFactQueriesUsed": 0,
            "analysisRecovery": False,
        }

    required_counts = ("analysisFactQueryLimit", "analysisFactQueriesUsed")
    invalid = [
        key
        for key in required_counts
        if not isinstance(phase_contract.get(key), int)
        or isinstance(phase_contract.get(key), bool)
        or phase_contract[key] < int(key == "analysisFactQueryLimit")
    ]
    if not isinstance(phase_contract.get("analysisRecovery"), bool):
        invalid.append("analysisRecovery")
    if phase_contract.get("analysisFactBudgetVersion") != 1 or invalid:
        raise ReportingError(
            "report_phase_contract_invalid",
            "analysis item v1 facts 子预算标量缺失或无效。",
            details={
                "invalidFields": invalid,
                "version": phase_contract.get("analysisFactBudgetVersion"),
            },
        )
    return {
        "analysisFactBudgetVersion": 1,
        "analysisFactQueryLimit": phase_contract["analysisFactQueryLimit"],
        "analysisFactQueriesUsed": phase_contract["analysisFactQueriesUsed"],
        "analysisRecovery": phase_contract["analysisRecovery"],
    }


def reporting_visualization_budget_from_run_context(
    run_context: RunContext | None,
) -> tuple[int, int]:
    """读取当前 worker 的累计预算，供任意 fresh retry 保留已经发生的调用。"""

    if run_context is None or not isinstance(run_context.session_state, Mapping):
        return 0, 0
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    external_run_id = binding.get("externalRunId")
    identity = f"{external_run_id or ''}:{run_context.run_id or ''}"
    budgets = run_context.session_state.get(REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY)
    stored = budgets.get(identity) if isinstance(budgets, Mapping) else None
    stored = stored if isinstance(stored, Mapping) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    base_total = count(
        stored.get(
            "baseTotal",
            binding.get(REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY),
        )
    )
    base_failures = count(
        stored.get(
            "baseScriptFailures",
            binding.get(REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY),
        )
    )
    total = base_total + count(stored.get("attemptedCount")) + count(stored.get("inFlightCount"))
    failures = base_failures + count(stored.get("scriptFailureCount"))
    return total, failures


def reporting_visualization_usage_from_run_context(
    run_context: RunContext | None,
) -> dict[str, int]:
    """返回可跨 fresh retry 签发的全部累计预算使用量。"""

    total, failures = reporting_visualization_budget_from_run_context(run_context)
    if run_context is None or not isinstance(run_context.session_state, Mapping):
        return {
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": total,
            "visualizationScriptFailures": failures,
            "visualizationAttemptSuccessfulToolCalls": 0,
            "visualizationAttemptRejectedToolCalls": 0,
        }
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
    budgets = run_context.session_state.get(REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY)
    stored = budgets.get(identity) if isinstance(budgets, Mapping) else None
    stored = stored if isinstance(stored, Mapping) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    attempt_calls = count(stored.get("attemptedCount")) + count(stored.get("inFlightCount"))
    attempt_successes = count(stored.get("successfulCount"))
    return {
        "visualizationReadUnitsUsed": count(
            stored.get(
                "baseReadUnits", binding.get(REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY)
            )
        )
        + count(stored.get("readUnitsUsed")),
        "visualizationFactQueriesUsed": count(
            stored.get(
                "baseFactQueries", binding.get(REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY)
            )
        )
        + count(stored.get("factQueriesUsed")),
        "visualizationToolCalls": total,
        "visualizationScriptFailures": failures,
        "visualizationAttemptSuccessfulToolCalls": attempt_successes,
        "visualizationAttemptRejectedToolCalls": max(attempt_calls - attempt_successes, 0),
    }


def reporting_analysis_fact_usage_from_run_context(run_context: RunContext | None) -> int:
    """读取当前分析项 facts 查询总数，fresh retry 必须继承已发生的额度。"""

    if run_context is None or not isinstance(run_context.session_state, Mapping):
        return 0
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
    budgets = run_context.session_state.get(REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY)
    stored = budgets.get(identity) if isinstance(budgets, Mapping) else None
    stored = stored if isinstance(stored, Mapping) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    return (
        count(binding.get(REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY))
        + count(stored.get("queriesUsed"))
        + count(stored.get("inFlightQueries"))
    )


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


def reporting_visualization_registered_from_run_context(
    run_context: RunContext | None,
) -> bool:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    return (
        binding.get(REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY) is True
        if isinstance(binding, Mapping)
        else False
    )


def reporting_visualization_recovery_from_run_context(
    run_context: RunContext | None,
) -> bool:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    return (
        binding.get(REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY) is True
        if isinstance(binding, Mapping)
        else False
    )


def reporting_analysis_recovery_from_run_context(run_context: RunContext | None) -> bool:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    return (
        binding.get(REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY) is True
        if isinstance(binding, Mapping)
        else False
    )


def reporting_visualization_exploration_count(
    run_context: RunContext | None,
    tool_name: str,
) -> int:
    """读取当前可视化 run 中某类探索工具的已完成调用数。"""

    if run_context is None or not isinstance(run_context.session_state, Mapping):
        return 0
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
    budgets = run_context.session_state.get(REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY)
    stored = budgets.get(identity) if isinstance(budgets, Mapping) else None
    if tool_name == "read_file":
        base_key = REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY
        stored_key = "readUnitsUsed"
        in_flight_key = "inFlightReadUnits"
    else:
        base_key = REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY
        stored_key = "factQueriesUsed"
        in_flight_key = "inFlightFactQueries"

    def count(raw: Any) -> int:
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0

    legacy_counts = stored.get("toolCounts") if isinstance(stored, Mapping) else None
    stored_value = stored.get(stored_key) if isinstance(stored, Mapping) else None
    if stored_value is None and isinstance(legacy_counts, Mapping):
        stored_value = legacy_counts.get(tool_name)

    return (
        count(binding.get(base_key))
        + count(stored_value)
        + count(stored.get(in_flight_key) if isinstance(stored, Mapping) else 0)
    )


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
