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


_FATAL = FailurePolicy("fatal", "fatal")
_DEGRADE = FailurePolicy("retry_then_degrade", "retry_then_degrade")
_COMPILE = FailurePolicy(thinking="python_compile_failure")
POLICIES = MappingProxyType({
    # Provider 返回未声明或类型不匹配的工具调用属于协议层故障；重试同一
    # 工具上下文不会修复 wire 类型，必须停止并保留原始声明诊断。
    "report_code_custom_tool_protocol_error": _FATAL,
    "report_coding_task_conflict": _FATAL,
    "report_code_mode_runtime_missing": _FATAL,
    "report_workspace_unavailable": _FATAL,
    "report_task_cancelled": _FATAL,
    "report_task_timeout": _FATAL,
    "report_phase_artifact_changed": _FATAL,
    "report_capability_invalid": FailurePolicy(visualization="fatal"),
    "report_task_lease_conflict": FailurePolicy(visualization="fatal"),
    "report_code_generation_no_submission": _DEGRADE,
    "report_code_model_request_limit": _DEGRADE,
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
