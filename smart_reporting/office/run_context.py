"""Agno RunContext 的进程内绑定与模型档位读取，供结构化输出执行器共用。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from agno.run import RunContext

REPORTING_TASK_DEPENDENCY = "AgentOS 任务执行"
REPORTING_MODEL_TIER_DEPENDENCY_KEY = "reportingModelTier"
REPORTING_MODEL_ID_DEPENDENCY_KEY = "reportingModelId"

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


__all__ = [
    "REPORTING_MODEL_ID_DEPENDENCY_KEY",
    "REPORTING_MODEL_TIER_DEPENDENCY_KEY",
    "REPORTING_TASK_DEPENDENCY",
    "bind_reporting_run_context",
    "current_reporting_run_context",
    "reporting_model_route_from_run_context",
]
