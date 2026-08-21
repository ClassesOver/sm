import re
from typing import Any

from agno.run import RunContext
from agno.tools import Toolkit

from .workspace import WorkspaceService

AGENT_PLAN_STATE_KEY = "agentos_plan"
MAX_PLAN_STEPS = 20
MAX_PLAN_STEP_LENGTH = 300
MAX_PLAN_EXPLANATION_LENGTH = 1000
PLAN_STATUSES = frozenset({"pending", "in_progress", "completed"})
_FORBIDDEN_PLAN_CONTENT = re.compile(
    r"snapshotId|hostRevision|modifiers|(?:authorization\s+token)|授权\s*token|"
    r"[\"']?token[\"']?\s*[:=]",
    re.IGNORECASE,
)


def validated_agent_plan(value: object) -> dict[str, Any] | None:
    """返回可安全放入模型上下文的服务端计划副本。"""
    if not isinstance(value, dict) or set(value) != {"plan", "explanation"}:
        return None
    plan = value.get("plan")
    explanation = value.get("explanation")
    if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_PLAN_STEPS:
        return None
    if not isinstance(explanation, str) or len(explanation) > MAX_PLAN_EXPLANATION_LENGTH:
        return None
    if _FORBIDDEN_PLAN_CONTENT.search(explanation):
        return None
    normalized = []
    active = 0
    for item in plan:
        if not isinstance(item, dict) or set(item) != {"step", "status"}:
            return None
        step = item.get("step")
        status = item.get("status")
        if (
            not isinstance(step, str)
            or not step.strip()
            or len(step) > MAX_PLAN_STEP_LENGTH
            or _FORBIDDEN_PLAN_CONTENT.search(step)
            or status not in PLAN_STATUSES
        ):
            return None
        active += status == "in_progress"
        normalized.append({"step": step.strip(), "status": status})
    if active > 1:
        return None
    return {"plan": normalized, "explanation": explanation.strip()}


def build_coding_agent_tools(
    workspace_service: WorkspaceService,
    coding_repository,
    validator_registry=None,
    *,
    run_context: RunContext,
    agent: Any | None = None,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> list[Toolkit]:
    """Coding Agent 固定使用受约束的工作区工具。"""
    from .task_execution.execution import WorkspaceCodingToolkit

    return [
        WorkspaceCodingToolkit(
            workspace_service,
            coding_repository,
            validator_registry=validator_registry,
        )
    ]


class AgentControlToolkit:
    """Coding 执行内核复用的计划状态操作。"""

    def __init__(self, _service: WorkspaceService):
        pass

    def agent_update_plan(
        self,
        plan: list[dict[str, str]],
        explanation: str | None = None,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        if not isinstance(plan, list) or not 1 <= len(plan) <= MAX_PLAN_STEPS:
            raise ValueError(f"计划必须包含 1 至 {MAX_PLAN_STEPS} 个步骤。")
        value = validated_agent_plan({"plan": plan, "explanation": (explanation or "").strip()})
        if value is None:
            raise ValueError("计划格式、状态或内容无效，且最多只能有一个 in_progress 步骤。")
        if run_context is None:
            raise ValueError("缺少当前运行上下文。")
        if run_context.session_state is None:
            run_context.session_state = {}
        run_context.session_state[AGENT_PLAN_STATE_KEY] = value
        return {"ok": True, **value}
