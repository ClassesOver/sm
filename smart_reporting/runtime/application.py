from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass

from agno.agent import Agent, AgentFactory, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.os import AgentOS
from agno.os.config import MCPServerConfig
from fastapi import FastAPI
from fastmcp.server.auth import AuthProvider

from ..async_utils import complete_cleanup
from ..quality_warnings.service import QualityWarningService
from ..reporting.workflow.controller import ReportWorkflowController
from ..workspace import WorkspaceService
from .database import AgentDatabase
from .settings import AgentSettings


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    workspace_service: WorkspaceService
    report_agent: Agent
    database: AgentDatabase | None = None
    quality_warning_service: QualityWarningService | None = None
    mcp_config: MCPServerConfig | None = None
    mcp_auth: AuthProvider | None = None
    report_workflow_controller: ReportWorkflowController | None = None


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        tasks = [
            asyncio.create_task(context.workspace_service.run_quarantine_cleanup_loop())
        ]
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
        # Reporting Workflow 只能由 smart-reporting facade 驱动。原生 Workflow
        # 路由无法覆盖 facade 的 thread 所有权和终态清理契约，因此不直接注册。
        workflows=[],
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
    application = agent_os.get_app()
    report_workflow_controller = context.report_workflow_controller
    if report_workflow_controller is not None:
        agentos_lifespan = application.router.lifespan_context

        @asynccontextmanager
        async def reporting_lifespan(app: FastAPI):
            # AgentOS 把数据库 lifespan 放在用户 lifespan 内层；在最终应用外包一层，
            # 才能保证 Reporting 自建后台任务先停止并完成持久化，然后 Agno 再关库。
            async with agentos_lifespan(app):
                try:
                    yield
                finally:
                    await report_workflow_controller.aclose()

        application.router.lifespan_context = reporting_lifespan
    return agent_os, application
