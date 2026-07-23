from collections.abc import Callable
from functools import partial
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from ..agent_control import build_agent_tools
from ..context_management import (
    ProtectedCompressionManager,
    RollingSessionSummaryManager,
    clear_terminal_reasoning,
)
from ..database import SerializedAsyncPostgresDb
from ..settings import AgentSettings
from ..workspace import WorkspaceService

AgentInstructions = str | list[str] | Callable[..., str | list[str]]

ASSISTANT_ID = "general-assistant"
LEGACY_ASSISTANT_IDS = frozenset({"odoo-assistant"})


def create_assistant(
    settings: AgentSettings,
    skills: Any,
    workspace_service: WorkspaceService,
    instructions: AgentInstructions,
    primary_model: OpenAIChat,
    compression_model: OpenAIChat,
    summary_model: OpenAIChat,
) -> Agent:
    assistant = Agent(
        id=ASSISTANT_ID,
        name="HRP 助手",
        role="处理普通问答、已选技能和工作区任务。",
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
    # Agno 构造时会把 None 归一化为 3；这里恢复全部 run 的检索语义。
    assistant.num_history_runs = None
    return assistant
