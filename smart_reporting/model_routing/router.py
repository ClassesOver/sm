"""确定性模型路由器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .models import (
    ModelProfile,
    ModelRouteRequest,
    ModelSelection,
    ModelTier,
    RouteFailure,
    TaskPolicy,
)
from .observability import log_model_selection

ModelRouteEventSink = Callable[[dict[str, str | int]], None]


class ModelRouter:
    """根据受信任务、复杂度和失败分类选择三档模型。"""

    def __init__(
        self,
        profiles: Mapping[ModelTier, ModelProfile],
        policies: Mapping[str, TaskPolicy],
        *,
        event_sink: ModelRouteEventSink | None = None,
    ) -> None:
        if set(profiles) != {"fast", "standard", "strong"}:
            raise ValueError("模型目录必须完整包含 fast、standard、strong 三档")
        self._profiles = profiles
        self._policies = policies
        self._event_sink = event_sink

    def select(self, request: ModelRouteRequest) -> ModelSelection:
        policy = self._policies.get(request.task_kind)
        if policy is None:
            raise ValueError(f"未知 task_kind: {request.task_kind}")
        tier = policy.tier_for(request.complexity)
        reason = "complexity_route"
        if request.failure in {RouteFailure.SCHEMA, RouteFailure.EVIDENCE}:
            if tier == "strong":
                raise ValueError("没有可用的升级档位")
            tier = "strong"
            reason = (
                "schema_repair" if request.failure is RouteFailure.SCHEMA else "evidence_repair"
            )
        elif request.failure is RouteFailure.TRANSIENT:
            reason = "transient_retry"
        profile = self._profiles[tier]
        selection = ModelSelection(
            task_kind=request.task_kind,
            complexity=request.complexity,
            tier=tier,
            model_id=profile.model_id,
            attempt=request.attempt,
            reason=reason,
        )
        if self._event_sink is not None:
            self._event_sink(selection.event_fields())
        else:
            log_model_selection(selection.event_fields())
        return selection
