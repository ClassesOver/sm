from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from agno.agent import Agent, AgentFactory, RemoteAgent
from agno.agent.protocol import AgentProtocol
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

    agents: list[Agent | RemoteAgent | AgentProtocol | AgentFactory] = [context.report_agent]
    if context.report_agent.id == "smart-reporting":
        # 旧 ID 已用于 AgentOS 路由和持久化 session。保留同能力别名，确保升级前
        # 暂停的 run 仍能通过原入口恢复；新请求继续以 smart-reporting 为主入口。
        agents.append(context.report_agent.deep_copy(update={"id": "report-agent"}))

    agent_os = AgentOS(
        name="开发智能体服务",
        # Coding 暂不通过综合服务对外提供。
        agents=agents,
        teams=[],
        workflows=[context.report_workflow] if context.report_workflow is not None else [],
        interfaces=[],
        base_app=base_app,
        db=context.database.async_db if context.database is not None else None,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
        lifespan=lifespan,
        telemetry=False,
    )
    return agent_os, agent_os.get_app()
