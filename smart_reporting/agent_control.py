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


# 任务调度器（读写锁）允许以读锁并行的工具：只读 Skill / 报告数据源元信息，
# 不调用外部模型、不修改工作区或任务状态。
SCHEDULER_PARALLEL_SAFE_TOOLS = frozenset(
    {
        "get_skill_instructions",
        "get_skill_reference",
        "report_list_data_sources",
        "report_describe_data_source",
        # 该工具只按受信身份读取 Profile 节点，不修改工作区或任务状态。
        "inspect_profile_index",
        "read_profile_pointer",
    }
)

# 批量调用准入额外放行的只读工具；它们在调度器里仍串行执行
# （例如 view_image 会调用视觉模型，并行会放大限流与费用）。
PARALLEL_SAFE_TOOLS = SCHEDULER_PARALLEL_SAFE_TOOLS | frozenset(
    {
        "list_files",
        "read_file",
        "read_lines",
        "search_text",
        "tree",
        "git_status",
        "git_diff",
        "read_tool_output",
        "view_image",
    }
)


def _reads_skill_script_only(name: str, arguments: Any) -> bool:
    return bool(
        name == "get_skill_script"
        and isinstance(arguments, dict)
        and arguments.get("execute", False) is False
    )


def is_parallel_safe_tool(name: str, arguments: Any) -> bool:
    """批量准入：get_skill_script 仅在只读取脚本（execute=False）时可并行。"""

    return name in PARALLEL_SAFE_TOOLS or _reads_skill_script_only(name, arguments)


def is_scheduler_parallel_safe_tool(name: str, arguments: Any) -> bool:
    """任务调度器：只对 SCHEDULER_PARALLEL_SAFE_TOOLS 与只读 skill 脚本使用读锁。"""

    return name in SCHEDULER_PARALLEL_SAFE_TOOLS or _reads_skill_script_only(name, arguments)
