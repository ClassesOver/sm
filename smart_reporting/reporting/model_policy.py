"""Reporting 模型请求能力与 thinking 配置策略。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from agno.models.openai import OpenAIChat, OpenAIResponses

from ..integrations.model_config import reasoning_transport_fields
from ..model_routing import TaskComplexity, log_thinking_selection

ReportingReasoningEffort = Literal["high", "max"]
ThinkingOperation = Literal[
    "request_normalization",
    "domain_resolution",
    "data_understanding",
    "measure_semantics",
    "outline_planning",
    "sql_planning",
    "analysis_planning",
    "analysis_evidence",
    "analysis_summary",
    "analysis_script",
    "visualization_plan",
    "visualization_script",
    "section_generation",
]
ThinkingFailureKind = Literal[
    "schema_failure",
    "capability_mapping_failure",
    "evidence_incomplete",
    "fact_incomplete",
    "sql_validation_failure",
    "python_compile_failure",
    "python_execution_failure",
    "visual_review_failure",
    "transient",
    "semantic_warning",
]

_COMPLEXITY_BUDGETS = {"simple": 1024, "standard": 2048, "complex": 4096}
_INITIAL_THINKING_BUDGETS: dict[ThinkingOperation, int | dict[TaskComplexity, int]] = {
    "request_normalization": 0,
    "domain_resolution": 0,
    "data_understanding": 2048,
    "measure_semantics": 2048,
    "outline_planning": 0,
    "sql_planning": 2048,
    "analysis_planning": 2048,
    "analysis_evidence": _COMPLEXITY_BUDGETS,
    "analysis_summary": _COMPLEXITY_BUDGETS,
    "analysis_script": 0,
    "visualization_plan": _COMPLEXITY_BUDGETS,
    "visualization_script": 0,
    "section_generation": 0,
}
_RECOVERY_THINKING_BUDGETS: dict[
    ThinkingOperation, dict[ThinkingFailureKind, tuple[int, ReportingReasoningEffort]]
] = {
    "request_normalization": {"schema_failure": (1024, "high")},
    "data_understanding": {
        "schema_failure": (4096, "high"),
        "capability_mapping_failure": (4096, "high"),
    },
    "measure_semantics": {
        "schema_failure": (4096, "high"),
        "capability_mapping_failure": (4096, "high"),
    },
    "outline_planning": {"schema_failure": (2048, "high")},
    "sql_planning": {
        "schema_failure": (4096, "high"),
        "sql_validation_failure": (4096, "high"),
    },
    "analysis_planning": {"schema_failure": (4096, "high")},
    "analysis_evidence": {
        "evidence_incomplete": (6144, "max"),
        "fact_incomplete": (6144, "max"),
    },
    "analysis_summary": {"schema_failure": (4096, "high")},
    "analysis_script": {
        "python_compile_failure": (2048, "high"),
        "python_execution_failure": (2048, "high"),
    },
    "visualization_plan": {"schema_failure": (4096, "high")},
    "visualization_script": {
        "python_compile_failure": (2048, "high"),
        "python_execution_failure": (2048, "high"),
        "visual_review_failure": (4096, "high"),
    },
    "section_generation": {"schema_failure": (2048, "high")},
}


@dataclass(frozen=True, slots=True)
class ThinkingPolicyConfig:
    operation: ThinkingOperation
    thinking_enabled: bool
    configured_budget_cap: int

    def __post_init__(self) -> None:
        if self.operation not in _INITIAL_THINKING_BUDGETS:
            raise ValueError("operation 无效")
        if not isinstance(self.thinking_enabled, bool):
            raise ValueError("thinking_enabled 必须是布尔值")
        if (
            isinstance(self.configured_budget_cap, bool)
            or not isinstance(self.configured_budget_cap, int)
            or self.configured_budget_cap < 1
        ):
            raise ValueError("configured_budget_cap 必须是正整数")


@dataclass(frozen=True, slots=True)
class ThinkingRequest:
    operation: ThinkingOperation
    complexity: TaskComplexity = "standard"
    attempt: int = 0
    failure_kind: ThinkingFailureKind | None = None
    configured_budget_cap: int = 8192
    thinking_enabled: bool = True

    def __post_init__(self) -> None:
        if self.operation not in _INITIAL_THINKING_BUDGETS:
            raise ValueError("operation 无效")
        if self.complexity not in _COMPLEXITY_BUDGETS:
            raise ValueError("complexity 无效")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 0:
            raise ValueError("attempt 必须是非负整数")
        if (
            isinstance(self.configured_budget_cap, bool)
            or not isinstance(self.configured_budget_cap, int)
            or self.configured_budget_cap < 1
        ):
            raise ValueError("configured_budget_cap 必须是正整数")


@dataclass(frozen=True, slots=True)
class ThinkingDecision:
    operation: ThinkingOperation
    complexity: TaskComplexity
    enabled: bool
    reasoning_effort: ReportingReasoningEffort | None
    thinking_budget: int
    attempt: int
    reason: str
    policy_version: str = "v1"

    def event_fields(self) -> dict[str, str | int | bool]:
        return {
            "event": "report_thinking_selected",
            "operation": self.operation,
            "complexity": self.complexity,
            "enabled": self.enabled,
            "effort": self.reasoning_effort or "off",
            "budget": self.thinking_budget,
            "attempt": self.attempt,
            "reason": self.reason,
            "policy_version": self.policy_version,
        }


_CURRENT_REPORTING_THINKING: ContextVar[ThinkingDecision | None] = ContextVar(
    "current_reporting_thinking",
    default=None,
)


@contextmanager
def bind_reporting_thinking(decision: ThinkingDecision) -> Iterator[None]:
    """将不可变 thinking 决策绑定到当前协程，并在退出时精确恢复。"""

    token = _CURRENT_REPORTING_THINKING.set(decision)
    log_thinking_selection(decision.event_fields())
    try:
        yield
    finally:
        _CURRENT_REPORTING_THINKING.reset(token)


def current_reporting_thinking_decision() -> ThinkingDecision | None:
    return _CURRENT_REPORTING_THINKING.get()


def select_reporting_thinking(request: ThinkingRequest) -> ThinkingDecision:
    """按单次模型操作选择 thinking，不从模型能力档位推导预算。"""

    budget_source = _INITIAL_THINKING_BUDGETS[request.operation]
    initial_budget = (
        budget_source[request.complexity] if isinstance(budget_source, dict) else budget_source
    )
    budget = initial_budget
    effort: ReportingReasoningEffort = "high"
    reason = "initial_policy" if budget else "initial_off"

    recovery = _RECOVERY_THINKING_BUDGETS.get(request.operation, {}).get(
        request.failure_kind  # type: ignore[arg-type]
    )
    if request.attempt == 1 and recovery is not None:
        budget, effort = recovery
        reason = str(request.failure_kind)
    elif request.attempt > 1:
        reason = "retry_limit_reached"
    elif request.attempt == 1:
        reason = "retry_same_budget"

    if not request.thinking_enabled:
        return ThinkingDecision(
            operation=request.operation,
            complexity=request.complexity,
            enabled=False,
            reasoning_effort=None,
            thinking_budget=0,
            attempt=request.attempt,
            reason="thinking_disabled",
        )
    if budget == 0:
        return ThinkingDecision(
            operation=request.operation,
            complexity=request.complexity,
            enabled=False,
            reasoning_effort=None,
            thinking_budget=0,
            attempt=request.attempt,
            reason=reason,
        )
    return ThinkingDecision(
        operation=request.operation,
        complexity=request.complexity,
        enabled=True,
        reasoning_effort=effort,
        thinking_budget=min(budget, request.configured_budget_cap),
        attempt=request.attempt,
        reason=reason,
    )

_VERIFIED_REPORTING_CONTEXT_TOKEN_LIMITS: tuple[tuple[tuple[str, ...], int], ...] = (
    (("qwen3.6", "qwen3.8"), 256 * 1024),
    (("deepseek-v4",), 256 * 1024),
)


def reporting_model_context_token_limit(model_id: str | None) -> int | None:
    """返回已由当前部署端点验证的上下文窗口，未知模型不推测。"""

    family = str(model_id or "").strip().lower().rsplit("/", 1)[-1]
    for prefixes, token_limit in _VERIFIED_REPORTING_CONTEXT_TOKEN_LIMITS:
        if family.startswith(prefixes):
            return token_limit
    return None


def resolve_reporting_input_token_hard_cap(
    *,
    configured_input_token_cap: int,
    model_id: str | None,
    output_token_reserve: int,
    absolute_input_token_cap: int,
) -> int:
    """按最终路由模型能力收敛单次请求输入上限。"""

    candidates = [configured_input_token_cap, absolute_input_token_cap]
    model_context_limit = reporting_model_context_token_limit(model_id)
    if model_context_limit is not None:
        model_input_limit = model_context_limit - output_token_reserve
        if model_input_limit < 1:
            raise ValueError("Reporting 模型输出预留不得耗尽已验证的上下文窗口")
        candidates.append(model_input_limit)
    return min(candidates)


def reporting_model_output_token_limit(model_id: str | None) -> int | None:
    """返回已由真实端点验证的单次输出上限，未知模型不做推测性限制。"""

    family = str(model_id or "").strip().lower().rsplit("/", 1)[-1]
    if family.startswith(("qwen3.6", "qwen3.8")):
        return 64 * 1024
    if family.startswith("deepseek-v4"):
        return 128 * 1024
    return None


@dataclass(frozen=True, slots=True)
class ReportingThinkingProfile:
    """描述一次 Reporting 模型请求的完整 thinking 配置。"""

    enabled: bool
    reasoning_effort: ReportingReasoningEffort | None = None
    thinking_budget: int | None = None
    temperature: float = 0.1

    def __post_init__(self) -> None:
        if not 0 <= self.temperature <= 2:
            raise ValueError("Reporting thinking temperature 必须在 0 到 2 之间")
        if self.enabled:
            if self.reasoning_effort not in {"high", "max"}:
                raise ValueError("开启 Reporting thinking 时 reasoning_effort 必须是 high 或 max")
            if (
                isinstance(self.thinking_budget, bool)
                or not isinstance(self.thinking_budget, int)
                or self.thinking_budget <= 0
            ):
                raise ValueError("开启 Reporting thinking 时 thinking_budget 必须是正整数")
        elif self.reasoning_effort is not None or self.thinking_budget is not None:
            raise ValueError("关闭 Reporting thinking 时不得保留 effort 或 budget")

    @classmethod
    def off(cls, *, temperature: float = 0.1) -> ReportingThinkingProfile:
        return cls(enabled=False, temperature=temperature)

    @classmethod
    def on(
        cls,
        *,
        reasoning_effort: ReportingReasoningEffort,
        thinking_budget: int,
        temperature: float = 0.1,
    ) -> ReportingThinkingProfile:
        return cls(
            enabled=True,
            reasoning_effort=reasoning_effort,
            thinking_budget=thinking_budget,
            temperature=temperature,
        )


def apply_reporting_thinking_profile[ModelT: OpenAIChat | OpenAIResponses](
    model: ModelT,
    profile: ReportingThinkingProfile,
) -> ModelT:
    """原子应用一次请求配置，关闭时清除所有可能继承的 thinking 字段。"""

    # Planner 和 Section 都从 Report Agent 浅复制模型。必须先删除 Agent 的预算，
    # 再应用当前阶段配置，否则 enable_thinking=false 仍会携带过期 thinking_budget。
    extra_body = dict(model.extra_body or {})
    extra_body.pop("thinking_budget", None)
    extra_body["enable_thinking"] = profile.enabled
    if profile.enabled:
        extra_body["thinking_budget"] = profile.thinking_budget
    transport_effort: str | None = profile.reasoning_effort
    if (
        transport_effort == "max"
        and str(model.id or "").strip().lower().startswith("qwen")
        and not isinstance(extra_body.get("chat_template_kwargs"), dict)
    ):
        # Reporting 领域策略沿用 DeepSeek 的 high/max 两档；Qwen 的 OpenAI-compatible
        # 顶层协议把最高档命名为 xhigh。这里只转换传输值，内部策略和 vLLM
        # chat_template_kwargs 仍保持 max，避免模型路由改变业务复杂度语义。
        transport_effort = "xhigh"
    model.extra_body, model.reasoning_effort = reasoning_transport_fields(
        extra_body=extra_body,
        enabled=profile.enabled,
        reasoning_effort=transport_effort,
    )
    model.temperature = profile.temperature
    return model


def reporting_thinking_profile_from_model(
    model: OpenAIChat | OpenAIResponses,
) -> ReportingThinkingProfile:
    """把共享模型配置冻结为一次请求可复制的完整 profile。"""

    temperature = float(model.temperature) if isinstance(model.temperature, int | float) else 0.1
    extra_body = model.extra_body if isinstance(model.extra_body, dict) else {}
    if extra_body.get("enable_thinking") is not True:
        return ReportingThinkingProfile.off(temperature=temperature)
    template_kwargs = extra_body.get("chat_template_kwargs")
    raw_effort = (
        template_kwargs.get("reasoning_effort")
        if isinstance(template_kwargs, dict)
        else model.reasoning_effort
    )
    budget = extra_body.get("thinking_budget")
    if raw_effort == "high":
        effort: ReportingReasoningEffort = "high"
    elif raw_effort == "max" or (
        raw_effort == "xhigh" and str(model.id or "").strip().lower().startswith("qwen")
    ):
        effort = "max"
    else:
        raise ValueError("Reporting 模型开启 thinking 时缺少 high/max reasoning_effort")
    if isinstance(budget, bool) or not isinstance(budget, int) or budget <= 0:
        raise ValueError("Reporting 模型开启 thinking 时缺少有效 thinking_budget")
    return ReportingThinkingProfile.on(
        reasoning_effort=effort,
        thinking_budget=budget,
        temperature=temperature,
    )
