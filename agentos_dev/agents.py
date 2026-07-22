from collections.abc import Callable
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from .database import SerializedAsyncPostgresDb
from .settings import AgentSettings
from .workspace import WorkspaceReportToolkit, WorkspaceService

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
    assistant = Agent(
        id="odoo-assistant",
        name="HRP 助手",
        model=OpenAIChat(
            id=settings.model_id,
            base_url=settings.openai_base_url,
            api_key=settings.openai_api_key,
            role_map=OPENAI_COMPATIBLE_ROLE_MAP,
            extra_body={"enable_thinking": False},
            temperature=0.0,
        ),
        instructions=instructions,
        skills=skills,
        tools=[WorkspaceReportToolkit(workspace_service)],
        db=SerializedAsyncPostgresDb(db_url=settings.database_url),
        add_history_to_context=True,
        num_history_runs=10,
        debug_mode=settings.debug,
        markdown=True,
        tool_choice="auto",
    )
    edit_mode_assistant = assistant.deep_copy(update={"tool_choice": edit_tool_choice})
    menu_navigation_assistant = assistant.deep_copy(
        update={"tool_choice": menu_navigation_tool_choice}
    )
    return (
        assistant,
        edit_mode_assistant,
        menu_navigation_assistant,
    )
