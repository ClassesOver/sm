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
    menu_navigation_assistant: Agent


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    agent_os = AgentOS(
        name="HRP AG-UI 开发服务",
        agents=[context.assistant],
        interfaces=[AGUI(agent=context.assistant)],
        base_app=base_app,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
    )
    return agent_os, agent_os.get_app()
