from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.team import Team
from fastapi import FastAPI

from .coding.repository import CodingTaskRepository
from .database import AgentDatabase
from .settings import AgentSettings
from .workspace import WorkspaceService

if TYPE_CHECKING:
    from .coding import CodingTaskSupervisor


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    workspace_service: WorkspaceService
    skills: Any
    assistant: Agent
    odoo_command_assistant: Agent
    report_agent: Agent
    assistant_team: Team
    coding_agent: Agent | None = None
    database: AgentDatabase | None = None
    coding_repository: CodingTaskRepository | None = None
    coding_supervisor: CodingTaskSupervisor | None = None


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    agent_os = AgentOS(
        name="HRP开发服务",
        agents=[
            context.assistant,
            context.odoo_command_assistant,
            context.report_agent,
        ],
        teams=[context.assistant_team],
        interfaces=[AGUI(team=context.assistant_team)],
        base_app=base_app,
        db=context.database.async_db if context.database is not None else None,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
    )
    return agent_os, agent_os.get_app()
