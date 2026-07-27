import re
from copy import copy
from dataclasses import replace
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.team import Team, TeamMode

from ..context_management import clear_terminal_reasoning
from ..database import AgentDatabase
from ..settings import AgentSettings
from ..workspace import WorkspaceService
from .assistant import (
    ASSISTANT_ID,
    LEGACY_ASSISTANT_IDS,
    AgentInstructions,
    create_assistant,
)
from .odoo_command import (
    LEGACY_ODOO_COMMAND_ASSISTANT_IDS,
    ODOO_COMMAND_ASSISTANT_ID,
    create_odoo_command_assistant,
)

OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "system",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}

ODOO_HOST_COMMAND_NAMES = frozenset(
    {
        "odoo.navigate_menu",
        "odoo.apply_filter",
        "odoo.apply_group",
        "odoo.export_current_view",
        "odoo.open_record",
        "odoo.open_create",
        "odoo.switch_view",
        "odoo.open_x2many_record",
        "odoo.open_x2many_create",
        "odoo.reload_current_form",
        "odoo.enter_edit_mode",
        "odoo.activate_view_control",
        "odoo.search_relation",
        "odoo.stage_current_form",
        "odoo.patch_current_form",
        "odoo.validate_current_form",
        "odoo.save_current_form",
        "odoo.discard_current_form",
    }
)
LEGACY_TEAM_IDS = frozenset({"odoo-assistant-team"})
ODOO_BUSINESS_COMMAND_PATTERN = re.compile(r"odoo\.business\.[a-z0-9_]+\.[a-z0-9_]+\Z")
TEAM_DELEGATION_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": "delegate_task_to_member"},
}
TEAM_ROUTE_DEPENDENCY = "AgentOS 可信团队路由"

TEAM_INSTRUCTIONS = [
    "服务端已按请求边界筛选本轮可用成员；必须委派给其中最匹配用户意图的一个成员，并直接返回其结果。",
    "普通问答委派给 general-assistant；明确要求执行 Odoo 页面或业务操作时委派给 "
    "odoo-command-assistant。",
    "不得改派给本轮不可用的成员，也不得仅因请求声明了 Odoo 工具就推断用户要求执行 Odoo 操作。",
]


def is_odoo_command_name(name: object) -> bool:
    return isinstance(name, str) and (
        name in ODOO_HOST_COMMAND_NAMES or ODOO_BUSINESS_COMMAND_PATTERN.fullmatch(name) is not None
    )


def _tool_name(tool: object) -> str | None:
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def _resolve_member_tools(
    member: Agent,
    run_context: RunContext,
    client_tools: list[Any],
) -> list[Any]:
    configured = member.tools
    if callable(configured):
        server_tools = configured(run_context=run_context, agent=member)
    else:
        server_tools = configured or []
    return [*server_tools, *client_tools]


def _resolve_member_instructions(member: Agent, run_context: RunContext) -> AgentInstructions:
    configured = member.instructions
    if callable(configured):
        return configured(run_context)
    return configured or []


def _bind_member_for_run(
    member: Agent,
    run_context: RunContext,
    client_tools: list[Any],
) -> Agent:
    member_context = replace(run_context, client_tools=client_tools)
    bound = member.deep_copy(
        update={
            "tools": _resolve_member_tools(member, member_context, client_tools),
            "instructions": _resolve_member_instructions(member, member_context),
        }
    )
    bound.num_history_runs = None
    return bound


def create_assistants(
    settings: AgentSettings,
    skills: Any,
    workspace_service: WorkspaceService,
    instructions: AgentInstructions,
    command_instructions: AgentInstructions,
    database: AgentDatabase,
) -> tuple[Agent, Agent]:
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
    assistant = create_assistant(
        settings,
        skills,
        workspace_service,
        instructions,
        primary_model,
        compression_model,
        summary_model,
        database.async_db,
    )
    odoo_command_assistant = create_odoo_command_assistant(
        assistant,
        command_instructions,
    )
    return assistant, odoo_command_assistant


def create_assistant_team(
    assistant: Agent,
    odoo_command_assistant: Agent,
) -> Team:
    all_members = [assistant, odoo_command_assistant]
    members_by_id = {member.id: member for member in all_members}

    def members_for_run(run_context: RunContext) -> list[Agent]:
        declared_client_tools = list(run_context.client_tools or [])
        command_tools = [
            tool for tool in declared_client_tools if is_odoo_command_name(_tool_name(tool))
        ]
        allowed_by_member_id = {
            assistant.id: [],
            odoo_command_assistant.id: command_tools,
        }

        route = (run_context.dependencies or {}).get(TEAM_ROUTE_DEPENDENCY)
        selected = all_members
        if route is not None:
            if not isinstance(route, dict):
                selected = []
            elif isinstance(route.get("memberIds"), list):
                allowed_ids = {
                    member_id for member_id in route["memberIds"] if isinstance(member_id, str)
                }
                selected = [member for member in all_members if member.id in allowed_ids]
            else:
                member = members_by_id.get(route.get("memberId"))
                selected = [member] if member is not None else []

        # Team 领导者只允许调用委派工具；浏览器工具全部绑定到每轮成员副本。
        run_context.client_tools = None
        return [
            _bind_member_for_run(
                member,
                run_context,
                allowed_by_member_id[member.id],
            )
            for member in selected
        ]

    if not isinstance(assistant.model, OpenAIChat):
        raise TypeError("Assistant team requires OpenAIChat")
    routing_model = copy(assistant.model)
    routing_model.extra_body = {
        **(getattr(assistant.model, "extra_body", None) or {}),
        "enable_thinking": False,
    }
    team = Team(
        id="hrp-assistant-team",
        name="HRP 助手团队",
        model=routing_model,
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


__all__ = [
    "ASSISTANT_ID",
    "LEGACY_ASSISTANT_IDS",
    "LEGACY_ODOO_COMMAND_ASSISTANT_IDS",
    "LEGACY_TEAM_IDS",
    "ODOO_COMMAND_ASSISTANT_ID",
    "ODOO_HOST_COMMAND_NAMES",
    "OPENAI_COMPATIBLE_ROLE_MAP",
    "REPORT_CLIENT_COMMAND_NAMES",
    "TEAM_DELEGATION_TOOL_CHOICE",
    "TEAM_INSTRUCTIONS",
    "TEAM_ROUTE_DEPENDENCY",
    "create_assistant",
    "create_assistant_team",
    "create_assistants",
    "create_odoo_command_assistant",
    "is_odoo_command_name",
]
