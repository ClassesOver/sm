from dataclasses import dataclass
from typing import Any

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team
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
    report_agent: Agent
    assistant_team: Team


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    agent_os = AgentOS(
        name="HRP开发服务",
        agents=[context.assistant, context.report_agent],
        teams=[context.assistant_team],
        interfaces=[AGUI(team=context.assistant_team)],
        base_app=base_app,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
    )
    return agent_os, agent_os.get_app()
