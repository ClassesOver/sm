"""模型路由的稳定领域契约，不依赖 Agno 或 Reporting 运行时。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

ModelTier = Literal["fast", "standard", "strong"]
TaskComplexity = Literal["simple", "standard", "complex"]


class RouteFailure(StrEnum):
    """会影响模型路由的已分类失败原因。"""

    SCHEMA = "schema"
    EVIDENCE = "evidence"
    TRANSIENT = "transient"


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """一个档位的当前模型实现和无敏感请求策略。"""

    tier: ModelTier
    model_id: str
    reasoning_effort: Literal["off", "high", "max"]

    def __post_init__(self) -> None:
        if not self.model_id.strip():
            raise ValueError("model_id 不能为空")
        if self.tier == "fast" and self.reasoning_effort != "off":
            raise ValueError("fast 档位必须关闭 reasoning")
        if self.tier == "standard" and self.reasoning_effort != "high":
            raise ValueError("standard 档位必须使用 high reasoning")
        if self.tier == "strong" and self.reasoning_effort != "max":
            raise ValueError("strong 档位必须使用 max reasoning")


@dataclass(frozen=True, slots=True)
class TaskPolicy:
    """业务任务到稳定能力档位的映射，禁止直接持有模型 ID。"""

    task_kind: str
    simple_tier: ModelTier
    standard_tier: ModelTier
    complex_tier: ModelTier

    def tier_for(self, complexity: TaskComplexity) -> ModelTier:
        return {
            "simple": self.simple_tier,
            "standard": self.standard_tier,
            "complex": self.complex_tier,
        }[complexity]


@dataclass(frozen=True, slots=True)
class ModelRouteRequest:
    """仅由服务端构造的模型选择输入。"""

    task_kind: str
    complexity: TaskComplexity
    failure: RouteFailure | None = None
    attempt: int = 0

    def __post_init__(self) -> None:
        if not self.task_kind:
            raise ValueError("task_kind 不能为空")
        if self.attempt < 0 or self.attempt > 1:
            raise ValueError("attempt 必须为 0 或 1")
        if self.failure is None and self.attempt != 0:
            raise ValueError("首次路由 attempt 必须为 0")
        if self.failure is not None and self.attempt == 0:
            object.__setattr__(self, "attempt", 1)


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """已冻结的路由结果，供模型工厂和可观测层共同使用。"""

    task_kind: str
    complexity: TaskComplexity
    tier: ModelTier
    model_id: str
    attempt: int
    reason: str
    policy_version: str = "v1"

    def event_fields(self) -> dict[str, str | int]:
        return {
            "event": "report_model_selected",
            "task_kind": self.task_kind,
            "complexity": self.complexity,
            "tier": self.tier,
            "model_id": self.model_id,
            "attempt": self.attempt,
            "reason": self.reason,
            "policy_version": self.policy_version,
        }
