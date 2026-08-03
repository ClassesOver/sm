import re
from copy import copy
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
    AgentInstructions,
    create_assistant,
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
ODOO_BUSINESS_COMMAND_PATTERN = re.compile(r"odoo\.business\.[a-z0-9_]+\.[a-z0-9_]+\Z")

TEAM_INSTRUCTIONS = [
    "你是 HRP 助手团队，是所有请求的唯一入口；使用中文简洁回答。",
    "普通问答可以直接回答；需要普通助手的技能或工作区工具时，委派给唯一成员 general-assistant。",
    "Odoo 页面和业务 command 是团队领导者的顶层客户端工具，必须由你直接调用，不得委派或复制给成员。",
    "本轮声明工具只表示能力可用，不能单独作为操作意图；仅在用户明确要求对应操作时调用。",
]


def is_odoo_command_name(name: object) -> bool:
    return isinstance(name, str) and (
        name in ODOO_HOST_COMMAND_NAMES or ODOO_BUSINESS_COMMAND_PATTERN.fullmatch(name) is not None
    )


def create_assistants(
    settings: AgentSettings,
    skills: Any,
    workspace_service: WorkspaceService,
    instructions: AgentInstructions,
    database: AgentDatabase,
) -> Agent:
    primary_model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": settings.assistant_enable_thinking},
        temperature=1.0,
        retries=2,
        exponential_backoff=True,
    )
    compression_model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": False},
        temperature=1.0,
        retries=2,
        exponential_backoff=True,
    )
    summary_model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": False},
        temperature=1.0,
        retries=2,
        exponential_backoff=True,
    )
    return create_assistant(
        settings,
        skills,
        workspace_service,
        instructions,
        primary_model,
        compression_model,
        summary_model,
        database.async_db,
    )


def create_assistant_team(
    assistant: Agent,
    command_instructions: AgentInstructions,
) -> Team:
    def instructions_for_run(run_context: RunContext) -> list[str]:
        instructions = list(TEAM_INSTRUCTIONS)
        if any(
            is_odoo_command_name(getattr(tool, "name", None))
            for tool in run_context.client_tools or []
        ):
            configured = command_instructions
            instructions.extend(configured(run_context) if callable(configured) else configured)
        return instructions

    if not isinstance(assistant.model, OpenAIChat):
        raise TypeError("Assistant team requires OpenAIChat")
    routing_model = copy(assistant.model)
    team = Team(
        id="hrp-assistant-team",
        name="HRP 助手团队",
        model=routing_model,
        mode=TeamMode.coordinate,
        members=[assistant],
        instructions=instructions_for_run,
        determine_input_for_members=False,
        tool_choice="auto",
        db=assistant.db,
        checkpoint="runs",
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
    "ODOO_HOST_COMMAND_NAMES",
    "OPENAI_COMPATIBLE_ROLE_MAP",
    "REPORT_CLIENT_COMMAND_NAMES",
    "TEAM_INSTRUCTIONS",
    "create_assistant",
    "create_assistant_team",
    "create_assistants",
    "is_odoo_command_name",
]
