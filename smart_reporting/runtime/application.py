from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import MCPServerConfig
from agno.workflow import Workflow
from fastapi import FastAPI
from fastmcp.server.auth import AuthProvider

from ..async_utils import complete_cleanup
from ..quality_warnings.service import QualityWarningService
from ..workspace import WorkspaceService
from .database import AgentDatabase
from .settings import AgentSettings


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    workspace_service: WorkspaceService
    report_agent: Agent
    report_workflow: Workflow
    database: AgentDatabase | None = None
    quality_warning_service: QualityWarningService | None = None
    mcp_config: MCPServerConfig | None = None
    mcp_auth: AuthProvider | None = None


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        tasks = [asyncio.create_task(context.workspace_service.run_quarantine_cleanup_loop())]
        reconcile = getattr(context.workspace_service, "run_provider_reconcile_loop", None)
        if callable(reconcile):
            tasks.append(asyncio.create_task(reconcile()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await complete_cleanup(task)
                except asyncio.CancelledError:
                    pass
            await context.workspace_service.aclose()

    agent_os = AgentOS(
        name="开发智能体服务",
        # Coding 暂不通过综合服务对外提供。
        agents=[context.report_agent],
        teams=[],
        workflows=[context.report_workflow],
        interfaces=[],
        base_app=base_app,
        db=context.database.async_db if context.database is not None else None,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
        lifespan=lifespan,
        telemetry=False,
        mcp_server=context.mcp_config or False,
        mcp_auth=context.mcp_auth,
    )
    return agent_os, agent_os.get_app()
