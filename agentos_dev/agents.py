from collections.abc import Callable
from functools import partial
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.team import Team, TeamMode

from .agent_control import build_agent_tools, build_report_agent_tools
from .context_management import (
    ProtectedCompressionManager,
    RollingSessionSummaryManager,
    clear_terminal_reasoning,
)
from .database import SerializedAsyncPostgresDb
from .settings import AgentSettings
from .workspace import WorkspaceService

OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "user",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}

AgentInstructions = str | list[str] | Callable[..., str | list[str]]

ASSISTANT_ID = "general-assistant"
LEGACY_ASSISTANT_IDS = frozenset({"odoo-assistant"})
TEAM_DELEGATION_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": "delegate_task_to_member"},
}
TEAM_ROUTE_DEPENDENCY = "AgentOS 可信团队路由"

TEAM_INSTRUCTIONS = [
    "服务端已按请求边界筛选本轮可用成员；只委派给唯一可用成员，并直接返回其结果。",
    "不得改派给本轮不可用的成员，也不得根据菜单名称、附件或模糊意图推断特殊路由。",
]


def create_assistants(
    settings: AgentSettings,
    skills: Any,
    workspace_service: WorkspaceService,
    instructions: AgentInstructions,
    report_instructions: AgentInstructions,
    edit_tool_choice: dict[str, Any],
    menu_navigation_tool_choice: dict[str, Any],
) -> tuple[Agent, Agent, Agent, Agent]:
    primary_model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": settings.enable_thinking},
        retries=2,
        exponential_backoff=True,
    )
    compression_model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": False},
        retries=2,
        exponential_backoff=True,
    )
    summary_model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": False},
        retries=2,
        exponential_backoff=True,
    )
    assistant = Agent(
        id=ASSISTANT_ID,
        name="HRP 助手",
        role="处理普通问答、Odoo 页面操作和工作区任务。",
        model=primary_model,
        instructions=instructions,
        skills=skills,
        tools=partial(
            build_agent_tools,
            workspace_service,
            context_token_budget=settings.context_token_budget,
            output_token_reserve=settings.output_token_reserve,
        ),
        cache_callables=False,
        db=SerializedAsyncPostgresDb(db_url=settings.database_url),
        checkpoint="tool-batch",
        add_history_to_context=False,
        enable_session_summaries=settings.enable_session_summaries,
        add_session_summary_to_context=False,
        session_summary_manager=RollingSessionSummaryManager(model=summary_model)
        if settings.enable_session_summaries
        else None,
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=ProtectedCompressionManager(
            model=compression_model,
            compress_token_limit=settings.history_token_budget,
        )
        if settings.enable_tool_result_compression
        else None,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        debug_mode=settings.debug and not settings.enable_thinking,
        markdown=True,
        tool_choice="auto",
    )
    edit_mode_assistant = assistant.deep_copy(
        update={
            "id": "edit-mode-assistant",
            "name": "编辑模式助手",
            "role": "只处理简短且完整的进入编辑模式请求。",
            "tool_choice": edit_tool_choice,
        }
    )
    menu_navigation_assistant = assistant.deep_copy(
        update={
            "id": "menu-navigation-assistant",
            "name": "菜单导航助手",
            "role": "只处理上下文明确要求的 Odoo 菜单导航。",
            "tool_choice": menu_navigation_tool_choice,
        }
    )
    report_agent = assistant.deep_copy(
        update={
            "id": "report-agent",
            "name": "智能报表",
            "role": "在当前 Daytona 工作区执行受控 Python 编码、数据分析和智能报表任务。",
            "instructions": report_instructions,
            "skills": None,
            "tools": partial(
                build_report_agent_tools,
                workspace_service,
                context_token_budget=settings.context_token_budget,
                output_token_reserve=settings.output_token_reserve,
                report_data_sources_file=settings.report_data_sources_file,
                database_url=settings.database_url,
            ),
            "tool_choice": "auto",
        }
    )
    # Agno maps constructor None to 3; post-init None means all runs in session.get_messages.
    for current in (assistant, edit_mode_assistant, menu_navigation_assistant, report_agent):
        current.num_history_runs = None
    return (
        assistant,
        edit_mode_assistant,
        menu_navigation_assistant,
        report_agent,
    )


def create_assistant_team(
    assistant: Agent,
    edit_mode_assistant: Agent,
    menu_navigation_assistant: Agent,
    report_agent: Agent,
) -> Team:
    all_members = [
        assistant,
        edit_mode_assistant,
        menu_navigation_assistant,
        report_agent,
    ]
    members_by_id = {member.id: member for member in all_members}

    def members_for_run(run_context: RunContext) -> list[Agent]:
        route = (run_context.dependencies or {}).get(TEAM_ROUTE_DEPENDENCY)
        if route is None:
            return all_members
        if not isinstance(route, dict):
            return []
        member = members_by_id.get(route.get("memberId"))
        return [member] if member is not None else []

    team = Team(
        id="odoo-assistant-team",
        name="HRP 助手团队",
        model=assistant.model,
        mode=TeamMode.route,
        members=members_for_run,
        instructions=TEAM_INSTRUCTIONS,
        determine_input_for_members=False,
        tool_choice=TEAM_DELEGATION_TOOL_CHOICE,
        db=assistant.db,
        checkpoint="tool-batch",
        add_history_to_context=False,
        enable_session_summaries=assistant.enable_session_summaries,
        add_session_summary_to_context=False,
        session_summary_manager=assistant.session_summary_manager,
        compress_tool_results=assistant.compress_tool_results,
        compression_manager=assistant.compression_manager,
        post_hooks=[clear_terminal_reasoning],
        retries=0,
        stream_member_events=True,
        cache_callables=False,
        debug_mode=assistant.debug_mode,
        markdown=True,
    )
    team.num_history_runs = None
    return team
