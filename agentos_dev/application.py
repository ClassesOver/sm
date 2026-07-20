from dataclasses import dataclass
from typing import Any

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from fastapi import FastAPI

from .settings import AgentSettings
from .workspace import WorkspaceService


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    workspace_service: WorkspaceService
    skills: Any
    assistant: Agent
    edit_mode_assistant: Agent


def create_agentos_app(
    settings: AgentSettings,
    base_app: FastAPI,
    assistant: Agent,
    *,
    workspace_service: WorkspaceService | None = None,
    skills: Any = None,
    edit_mode_assistant: Agent | None = None,
) -> tuple[AgentOS, FastAPI]:
    if workspace_service is not None and edit_mode_assistant is not None:
        base_app.state.agentos_context = ApplicationContext(
            settings=settings,
            workspace_service=workspace_service,
            skills=skills,
            assistant=assistant,
            edit_mode_assistant=edit_mode_assistant,
        )
    agent_os = AgentOS(
        name="Odoo AG-UI 开发服务",
        agents=[assistant],
        interfaces=[AGUI(agent=assistant)],
        base_app=base_app,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(settings.cors_allowed_origins),
    )
    return agent_os, agent_os.get_app()
