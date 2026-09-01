import re
from typing import Any

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
