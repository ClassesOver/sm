from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from agno.agent import Agent
from agno.os import AgentOS
from agno.workflow import Workflow
from fastapi import FastAPI

from .database import AgentDatabase
from .settings import AgentSettings
from .workspace import WorkspaceService


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    workspace_service: WorkspaceService
    report_agent: Agent
    report_workflow: Workflow | None = None
    database: AgentDatabase | None = None


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            yield
        finally:
            await context.workspace_service.aclose()

    agent_os = AgentOS(
        name="开发智能体服务",
        # Coding 暂不通过综合服务对外提供。
        agents=[context.report_agent],
        teams=[],
        workflows=[context.report_workflow] if context.report_workflow is not None else [],
        interfaces=[],
        base_app=base_app,
        db=context.database.async_db if context.database is not None else None,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
        lifespan=lifespan,
    )
    return agent_os, agent_os.get_app()
