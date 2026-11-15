from typing import Any

AGENT_PLAN_STATE_KEY = "agentos_plan"


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
