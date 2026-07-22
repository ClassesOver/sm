from collections.abc import Callable
from functools import partial
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from .agent_control import build_agent_tools
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


def create_assistants(
    settings: AgentSettings,
    skills: Any,
    workspace_service: WorkspaceService,
    instructions: AgentInstructions,
    edit_tool_choice: dict[str, Any],
    menu_navigation_tool_choice: dict[str, Any],
) -> tuple[Agent, Agent, Agent]:
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
        id="odoo-assistant",
        name="HRP 助手",
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
    edit_mode_assistant = assistant.deep_copy(update={"tool_choice": edit_tool_choice})
    menu_navigation_assistant = assistant.deep_copy(
        update={"tool_choice": menu_navigation_tool_choice}
    )
    # Agno maps constructor None to 3; post-init None means all runs in session.get_messages.
    for current in (assistant, edit_mode_assistant, menu_navigation_assistant):
        current.num_history_runs = None
    return (
        assistant,
        edit_mode_assistant,
        menu_navigation_assistant,
    )
