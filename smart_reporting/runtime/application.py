from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.config import MCPConfig
from agno.workflow import Workflow
from fastapi import FastAPI
from fastmcp.server.auth import AuthProvider
from loguru import logger

from ..quality_warnings.service import QualityWarningService
from ..reporting.code_agent.lsp_process import ReportingLspProcessManager
from ..reporting.code_mode import ReportingCodeModeRuntime
from .database import AgentDatabase
from .reporting_runs import enable_reporting_background_streams
from .settings import AgentSettings


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    report_agent: Agent
    report_workflow: Workflow
    database: AgentDatabase | None = None
    quality_warning_service: QualityWarningService | None = None
    mcp_config: MCPConfig | None = None
    mcp_auth: AuthProvider | None = None
    reporting_code_mode_runtime: ReportingCodeModeRuntime | None = None
    reporting_lsp_process_manager: ReportingLspProcessManager | None = None
    recalculation_editor: object | None = None


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        if context.database is not None:
            # 在接收请求前完成 Agno 原生建表；新库不能把初始化留给并发报表步骤。
            # 结构不兼容或建表失败时直接终止启动，避免报告执行后才发现历史未保存。
            await context.database.async_db._create_all_tables()
            logger.info("agent_database_initialized")
        try:
            yield
        finally:
            first_error: BaseException | None = None
            for resource in (
                context.reporting_code_mode_runtime,
                context.reporting_lsp_process_manager,
            ):
                if resource is None:
                    continue
                try:
                    await resource.aclose()
                except BaseException as error:
                    if first_error is None:
                        first_error = error
            if first_error is not None:
                raise first_error

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
        mcp=context.mcp_config or False,
        mcp_auth=context.mcp_auth,
    )
    application = agent_os.get_app()
    if context.recalculation_editor is not None:
        original_lifespan = application.router.lifespan_context

        @asynccontextmanager
        async def refresh_lifespan(app: FastAPI):
            from agno.os.job_queue import QueueWorker, resolve_queue_store

            from ..report_editor.policy_recovery import create_policy_recovery_workflow
            from ..report_editor.recalculation import (
                create_policy_adoption_workflow,
                create_refresh_workflow,
                recalculation_queue_config,
            )

            editor = context.recalculation_editor
            async with original_lifespan(app) as state:
                config = recalculation_queue_config()
                database = editor.recalculation_database

                def resolve_component(kind, component_id):
                    if (kind, component_id) == ('workflow', 'report-editor-refresh'):
                        return create_refresh_workflow(editor, runtime=editor.recalculation_runtime, database=database)
                    if (kind, component_id) == ('workflow', 'report-editor-policy-adoption'):
                        return create_policy_adoption_workflow(editor, runtime=editor.recalculation_runtime, database=database)
                    if (kind, component_id) == ('workflow', 'report-editor-policy-recovery'):
                        return create_policy_recovery_workflow(editor, runtime=editor.recalculation_runtime, database=database)
                    return None

                worker = QueueWorker(store=resolve_queue_store(config, database), config=config,
                    resolve_component=resolve_component)
                await worker.start()
                editor.recalculation_queue_worker = worker
                try:
                    yield state
                finally:
                    editor.recalculation_queue_worker = None
                    # 先停止原生worker，再退出AgentOS生命周期关闭数据库及代码执行资源。
                    await worker.stop()

        application.router.lifespan_context = refresh_lifespan
    enable_reporting_background_streams(application, context.report_agent.id)
    return agent_os, application
