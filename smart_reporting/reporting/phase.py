"""Reporting 内部 run 的受信 phase 绑定与工具投影。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from agno.run import RunContext

from .models import ReportingError
from .tools.capabilities import tools_for_task

ReportingPhase = Literal["analysis", "section"]
ReportingTaskKind = Literal[
    "analysis_item",
    "visualization_section",
    "section",
]

# Reporting 使用 1M 模型窗口。analysis phase hard cap 是注意力预算，不是事实层上限：
# 单项分析只投影当前任务需要的事实摘要；完整 Profile、证据正文和工具结果继续通过
# 受信文件与 outputHandle 按需读取。章节需要直接消费冻结证据正文，使用 Reporting
# 已配置的统一输入预算，避免复杂报表在模型调用前被额外的固定 cap 拒绝。
# 输出仍由模型级 reserve 单独预留，完整 Profile、工具原文和历史继续留在 checkpoint/handle。
# 单项分析的任务 JSON 可能包含跨 Dataset 的冻结 facts；上限需要覆盖真实的
# 不可压缩首轮前缀，同时仍低于默认 Reporting 输入预算，给工具回执和重试留余量。
REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP = 160 * 1024

REPORTING_PHASE_DEPENDENCY_KEY = "reportingPhase"
REPORTING_TASK_KIND_DEPENDENCY_KEY = "reportingTaskKind"
REPORTING_MODEL_TIER_DEPENDENCY_KEY = "reportingModelTier"
REPORTING_MODEL_ID_DEPENDENCY_KEY = "reportingModelId"
REPORTING_THINKING_EFFORT_DEPENDENCY_KEY = "reportingThinkingEffort"
REPORTING_THINKING_BUDGET_DEPENDENCY_KEY = "reportingThinkingBudget"
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
REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY = (
    "agentos_reporting_visualization_script_failure_pending"
)
REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY = "reportingVisualInspectionMode"
REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY = "agentos_reporting_visualization_tool_budget"
REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR = "_agentos_reporting_visualization_budget"
REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY = "analysisFactBudgetVersion"
REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY = "analysisFactQueryLimit"
REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY = "analysisFactQueriesUsed"
REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY = "analysisRecovery"
REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY = "agentos_reporting_analysis_fact_budget"
REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR = "_agentos_reporting_analysis_fact_budget"
# 单项分析按计划复杂度可提升到 8 次；4 次是缺少复杂度信息时的安全默认值。
REPORTING_ANALYSIS_FACT_QUERY_LIMIT = 4
REPORTING_TASK_DEPENDENCY = "AgentOS 任务执行"

# 当前可视化章节 Agent 共用受信预算与脚本状态；图表提交和章节收口均在同一章节
# 子工作流内完成，不再存在独立的全局 finalize Agent。
REPORTING_VISUALIZATION_TASK_KINDS = frozenset({"visualization_section"})
REPORTING_VISUALIZATION_FACT_QUERY_LIMIT = 4
REPORTING_VISUALIZATION_READ_FILE_LIMIT = 12
REPORTING_VISUALIZATION_EXPLORATION_TOOL_NAMES = frozenset(
    {
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


def reporting_visual_inspection_mode_from_run_context(
    run_context: RunContext | None,
) -> Literal["vision", "deterministic"]:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    mode = (
        binding.get(REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY)
        if isinstance(binding, Mapping)
        else None
    )
    # 历史 v2 Task 没有该字段，沿用当时强制视觉回执的语义，不能静默解释成降级模式。
    return mode if mode in {"vision", "deterministic"} else "vision"


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


def reporting_python_script_failed(result: Any) -> bool:
    """统一判定受控 Python runner 回执是否表示执行失败。"""

    if not isinstance(result, Mapping):
        return False
    if result.get("ok") is False and result.get("code") == "execution_output_error":
        return True
    for key in ("exitCode", "exit_code"):
        exit_code = result.get(key)
        if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
            return True
    output = result.get("output")
    if not isinstance(output, str):
        return False
    # 图表脚本会逐项自检并在保持进程 exit code 为 0 时输出明确失败标记；
    # 这里只识别协议化行，避免普通业务日志中的 ERROR 单词造成误判。
    return any(
        ": ERROR " in line.strip() or line.strip().startswith("[FAIL]")
        for line in output.splitlines()
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
    # 与 ReportingTaskKind Literal 保持同一白名单，未知 taskKind 一律拒绝为 None。
    return (
        task_kind
        if task_kind
        in {
            "analysis_item",
            "visualization_section",
            "section",
        }
        else None
    )


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


def reporting_thinking_budget_from_acceptance_contract(value: Any) -> int | None:
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
    budget = phase_contract.get("thinkingBudget") if isinstance(phase_contract, Mapping) else None
    return (
        budget if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0 else None
    )


def reporting_visual_inspection_mode_from_acceptance_contract(
    value: Any,
) -> Literal["vision", "deterministic"] | None:
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
    mode = (
        phase_contract.get("visualInspectionMode") if isinstance(phase_contract, Mapping) else None
    )
    return mode if mode in {"vision", "deterministic"} else None


def _visualization_phase_contract(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    requirements = value.get("requirements")
    if (
        not isinstance(requirements, Sequence)
        or isinstance(requirements, (str, bytes))
        or len(requirements) != 1
        or not isinstance(requirements[0], Mapping)
    ):
        return None
    parameters = requirements[0].get("parameters")
    contract = parameters.get("phaseContract") if isinstance(parameters, Mapping) else None
    return (
        contract
        if isinstance(contract, Mapping)
        and contract.get("taskKind") in REPORTING_VISUALIZATION_TASK_KINDS
        else None
    )


def reporting_visualization_recovery_from_acceptance_contract(value: Any) -> bool:
    contract = _visualization_phase_contract(value)
    return bool(contract and contract.get("visualizationRecovery") is True)


def reporting_visualization_budget_from_acceptance_contract(value: Any) -> tuple[int, int]:
    contract = _visualization_phase_contract(value)

    def count(key: str) -> int:
        raw = contract.get(key, 0) if contract else 0
        return raw if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0 else 0

    return count("visualizationToolCalls"), count("visualizationScriptFailures")


def reporting_visualization_budget_contract_from_acceptance_contract(value: Any) -> dict[str, int]:
    """读取当前可视化 Agent 的服务端签发动态预算，拒绝旧 taskKind。"""

    contract = _visualization_phase_contract(value)
    if contract is None:
        return {
            "visualizationBudgetVersion": 0,
            "visualizationEvidenceReadUnits": 0,
            "visualizationReadLimit": REPORTING_VISUALIZATION_READ_FILE_LIMIT,
            "visualizationFactQueryLimit": REPORTING_VISUALIZATION_FACT_QUERY_LIMIT,
            "visualizationAttemptToolLimit": 48,
            "visualizationTotalToolLimit": 64,
            "visualizationReadUnitsUsed": 0,
            "visualizationFactQueriesUsed": 0,
            "visualizationToolCalls": 0,
            "visualizationScriptFailures": 0,
        }
    version = contract.get("visualizationBudgetVersion")
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
        if not isinstance(contract.get(key), int)
        or isinstance(contract.get(key), bool)
        or contract[key] < int(key in required_positive)
    ]
    if version != 1 or invalid:
        raise ReportingError(
            "report_phase_contract_invalid",
            "visualization 动态预算标量缺失或无效。",
            details={"invalidFields": invalid, "version": version},
        )
    return {
        "visualizationBudgetVersion": 1,
        **{key: contract[key] for key in (*required_nonnegative, *required_positive)},
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
    # 与 ReportingTaskKind Literal 保持同一白名单，未知 taskKind 一律拒绝为 None。
    return (
        task_kind
        if task_kind
        in {
            "analysis_item",
            "visualization_section",
            "section",
        }
        else None
    )


def reporting_model_route_from_run_context(
    run_context: RunContext | None,
) -> tuple[str, str] | None:
    """读取执行器签发的模型档位和 ID；缺失或不一致时保持默认模型。"""

    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    if not isinstance(binding, Mapping):
        return None
    tier = binding.get(REPORTING_MODEL_TIER_DEPENDENCY_KEY)
    model_id = binding.get(REPORTING_MODEL_ID_DEPENDENCY_KEY)
    if tier not in {"fast", "standard", "strong"} or not isinstance(model_id, str) or not model_id:
        return None
    return tier, model_id


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


def reporting_thinking_budget_from_run_context(run_context: RunContext | None) -> int | None:
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    budget = (
        binding.get(REPORTING_THINKING_BUDGET_DEPENDENCY_KEY)
        if isinstance(binding, Mapping)
        else None
    )
    return (
        budget if isinstance(budget, int) and not isinstance(budget, bool) and budget > 0 else None
    )


def reporting_visualization_recovery_from_run_context(run_context: RunContext | None) -> bool:
    if reporting_task_kind_from_run_context(run_context) not in REPORTING_VISUALIZATION_TASK_KINDS:
        return False
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


def reporting_visualization_exploration_count(
    run_context: RunContext | None, tool_name: str
) -> int:
    if run_context is None or not isinstance(run_context.session_state, Mapping):
        return 0
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
    budgets = run_context.session_state.get(REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY)
    stored = budgets.get(identity) if isinstance(budgets, Mapping) else None
    base_key, stored_key, in_flight_key = (
        (REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY, "readUnitsUsed", "inFlightReadUnits")
        if tool_name == "read_file"
        else (
            REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY,
            "factQueriesUsed",
            "inFlightFactQueries",
        )
    )

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    return (
        count(binding.get(base_key))
        + count(stored.get(stored_key) if isinstance(stored, Mapping) else 0)
        + count(stored.get(in_flight_key) if isinstance(stored, Mapping) else 0)
    )


def reporting_visualization_exploration_budget_exhausted_from_run_context(
    run_context: RunContext | None,
) -> bool:
    if (
        reporting_phase_from_run_context(run_context) != "analysis"
        or reporting_task_kind_from_run_context(run_context) != "visualization_section"
    ):
        return False
    dependencies = (
        run_context.dependencies
        if run_context is not None and isinstance(run_context.dependencies, Mapping)
        else {}
    )
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}

    def limit(key: str, default: int) -> int:
        value = binding.get(key)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
            else default
        )

    return reporting_visualization_exploration_count(run_context, "query_analysis_facts") >= limit(
        REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
        REPORTING_VISUALIZATION_FACT_QUERY_LIMIT,
    ) or reporting_visualization_exploration_count(run_context, "read_file") >= limit(
        REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY, REPORTING_VISUALIZATION_READ_FILE_LIMIT
    )


def reporting_visualization_budget_from_run_context(
    run_context: RunContext | None,
) -> tuple[int, int]:
    if run_context is None or not isinstance(run_context.session_state, Mapping):
        return 0, 0
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
    budgets = run_context.session_state.get(REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY)
    stored_value = budgets.get(identity) if isinstance(budgets, Mapping) else None
    stored: Mapping[str, Any] = stored_value if isinstance(stored_value, Mapping) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    return (
        count(
            stored.get("baseTotal", binding.get(REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY))
        )
        + count(stored.get("attemptedCount"))
        + count(stored.get("inFlightCount")),
        count(
            stored.get(
                "baseScriptFailures",
                binding.get(REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY),
            )
        )
        + count(stored.get("scriptFailureCount")),
    )


def reporting_visualization_usage_from_run_context(
    run_context: RunContext | None,
) -> dict[str, int]:
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
    stored_value = budgets.get(identity) if isinstance(budgets, Mapping) else None
    stored: Mapping[str, Any] = stored_value if isinstance(stored_value, Mapping) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    attempts = count(stored.get("attemptedCount")) + count(stored.get("inFlightCount"))
    successes = count(stored.get("successfulCount"))
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
        "visualizationAttemptSuccessfulToolCalls": successes,
        "visualizationAttemptRejectedToolCalls": max(attempts - successes, 0),
    }


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


def reporting_phase_allows_tool(
    phase: ReportingPhase | None,
    tool_name: str,
    *,
    task_kind: ReportingTaskKind | None = None,
) -> bool:
    allowed = tools_for_task(phase, task_kind)
    if allowed is not None:
        return tool_name in allowed
    if phase == "analysis":
        return False
    return True
