"""Shared recovery and thinking policy for Coding Agent consumers.

retry_then_degrade explicitly preserves the workflow's bounded repair attempts.
retryable is accepted only as a legacy fallback; it does not override an explicit policy.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from ..model_policy import ThinkingFailureKind
from ..models import ReportingError

Recovery = Literal["fatal", "retry", "retry_then_degrade"]
TaskKind = Literal["analysis", "visualization"]


@dataclass(frozen=True)
class FailurePolicy:
    analysis: Recovery = "retry"
    visualization: Recovery = "retry"
    thinking: ThinkingFailureKind | None = None
    # 基础设施与部署配置类失败：任务本身已无法继续（取消、超时、租约、工作区），
    # 或运行时装配缺失。即使在最后一次 fresh attempt 也不得降级为零图成稿。
    infrastructure: bool = False


_FATAL = FailurePolicy("fatal", "fatal")
_INFRA = FailurePolicy("fatal", "fatal", infrastructure=True)
_DEGRADE = FailurePolicy("retry_then_degrade", "retry_then_degrade")
_COMPILE = FailurePolicy(thinking="python_compile_failure")
POLICIES = MappingProxyType({
    # Provider 返回未声明或类型不匹配的工具调用属于协议层故障；重试同一
    # 工具上下文不会修复 wire 类型，必须停止并保留原始声明诊断。
    "report_code_custom_tool_protocol_error": _FATAL,
    "report_coding_task_conflict": _INFRA,
    "report_code_mode_runtime_missing": _INFRA,
    # 工作区适配缺少协议能力（如 inspect_plotly_file）是确定性 infra 缺陷；
    # 重试或降级都无法补齐缺失的方法，必须立即停止并保留能力名诊断。
    "report_workspace_capability_missing": _INFRA,
    "report_workspace_unavailable": _INFRA,
    "report_task_cancelled": _INFRA,
    "report_task_timeout": _INFRA,
    "report_phase_artifact_changed": _FATAL,
    "report_capability_invalid": FailurePolicy(visualization="fatal", infrastructure=True),
    "report_task_lease_conflict": FailurePolicy(visualization="fatal", infrastructure=True),
    # 运行时装配缺失：恢复策略沿用默认 retry，只标记为基础设施类。
    "report_visualization_code_agent_missing": FailurePolicy(infrastructure=True),
    "report_visualization_executor_missing": FailurePolicy(infrastructure=True),
    "report_code_model_protocol_missing": FailurePolicy(infrastructure=True),
    # 工作区与任务上下文不匹配、能力状态损坏：确定性的部署/状态缺陷，重跑不可修复。
    "report_coding_task_workspace_mismatch": FailurePolicy(infrastructure=True),
    "report_capability_state_invalid": FailurePolicy(infrastructure=True),
    "report_code_generation_no_submission": _DEGRADE,
    "report_code_model_request_limit": _DEGRADE,
    "report_code_no_progress": _DEGRADE,
    "report_code_generation_rate_limited": _DEGRADE,
    "execution_output_error": FailurePolicy(visualization="retry_then_degrade", thinking="python_execution_failure"),
    "report_visualization_script_failed": FailurePolicy(visualization="retry_then_degrade", thinking="python_execution_failure"),
    "report_chart_file_missing": FailurePolicy(visualization="retry_then_degrade"),
    "report_python_source_shape_invalid": _COMPILE,
    "report_python_source_path_invalid": _COMPILE,
    "report_code_source_invalid": _COMPILE,
    "report_code_mode_execution_failed": FailurePolicy(thinking="python_execution_failure"),
    "report_code_exit_receipt_invalid": FailurePolicy(thinking="python_execution_failure"),
    "report_analysis_script_failed": FailurePolicy(thinking="python_execution_failure"),
    "report_visualization_review_failed": FailurePolicy(thinking="visual_review_failure"),
    "report_analysis_evidence_schema_invalid": FailurePolicy(thinking="schema_failure"),
})


def fresh_attempt_futile(error: BaseException) -> bool:
    """基础设施/部署配置类失败：重开 fresh attempt 同样无法修复，必须立即停止重试。

    分析项、可视化章节与章节成稿的 fresh attempt 循环统一以此为准。
    """

    return (
        isinstance(error, ReportingError)
        and POLICIES.get(error.code, FailurePolicy()).infrastructure
    )


def final_attempt_degradable(error: BaseException) -> bool:
    """最后一次 fresh attempt 失败时能否按零图降级。

    只接受业务/模型侧的 ReportingError；普通异常多为代码缺陷，必须上抛暴露。
    """

    return isinstance(error, ReportingError) and not fresh_attempt_futile(error)


def recovery_for(error: Exception, task: TaskKind) -> Recovery:
    if not isinstance(error, ReportingError):
        return "retry"
    policy = getattr(POLICIES.get(error.code, FailurePolicy()), task)
    # Task cancellation and artifact identity failures can never be downgraded.
    if policy == "fatal":
        return policy
    details = error.details if isinstance(error.details, Mapping) else {}
    explicit = details.get("recovery")
    if explicit in ("fatal", "retry", "retry_then_degrade"):
        return explicit
    if details.get("retryable") is False and policy != "retry_then_degrade":
        return "fatal"
    return policy


def failure_kind(diagnostic: Mapping | None) -> ThinkingFailureKind | None:
    code = diagnostic.get("code") if isinstance(diagnostic, Mapping) else None
    return POLICIES.get(code, FailurePolicy()).thinking if isinstance(code, str) else None
