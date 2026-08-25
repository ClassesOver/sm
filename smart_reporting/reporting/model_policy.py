"""Reporting 模型请求的 thinking 配置策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agno.models.openai import OpenAIChat

from ..model_config import reasoning_transport_fields

ReportingReasoningEffort = Literal["high", "max"]


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


def apply_reporting_thinking_profile[ModelT: OpenAIChat](
    model: ModelT,
    profile: ReportingThinkingProfile,
) -> ModelT:
    """原子应用一次请求配置，关闭时清除所有可能继承的 thinking 字段。"""

    # Planner 和 Section 都从 Report Worker 浅复制模型。必须先删除 Worker 的预算，
    # 再应用当前阶段配置，否则 enable_thinking=false 仍会携带过期 thinking_budget。
    extra_body = dict(model.extra_body or {})
    extra_body.pop("thinking_budget", None)
    extra_body["enable_thinking"] = profile.enabled
    if profile.enabled:
        extra_body["thinking_budget"] = profile.thinking_budget
    model.extra_body, model.reasoning_effort = reasoning_transport_fields(
        extra_body=extra_body,
        enabled=profile.enabled,
        reasoning_effort=profile.reasoning_effort,
    )
    model.temperature = profile.temperature
    return model


def reporting_thinking_profile_from_model(model: OpenAIChat) -> ReportingThinkingProfile:
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
    elif raw_effort == "max":
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
