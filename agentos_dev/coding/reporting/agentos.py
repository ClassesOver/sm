"""独立 Report AgentOS 装配。"""

from contextlib import asynccontextmanager
from typing import Any

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.middleware.user_scope import resolve_run_user_id
from fastapi import APIRouter, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...agentos_auth import agentos_authorization_config
from ...execution_context import (
    ExecutionContext,
    close_execution_resources,
    create_execution_context,
)
from ...settings import AgentSettings
from ...task_execution import TaskExecutionRepository
from ...task_execution.execution import TaskExecutionKernel
from .agent import create_report_agent, create_report_worker
from .controller import ReportWorkflowController
from .data_source import load_configured_report_source_registry
from .entrypoints import ReportServerIdentity
from .execution import ReportTaskRunner
from .instructions import build_report_agent_instructions
from .interface import ReportAGUI
from .metadata import ReportingMetadataClient
from .models import ReportingError
from .profile import load_configured_reporting_profiles
from .publishing import (
    ReportDownloadCallerScope,
    ReportDownloadGrantService,
    SqlAlchemyDownloadGrantRepository,
    WorkspaceReportDownloadHttpService,
    create_workspace_report_download_router,
)
from .runtime import ReportWorkflowRuntime


class ReportCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    run_id: str = Field(alias="runId", min_length=1, max_length=128)


def create_report_agentos_components(
    context: ExecutionContext,
    settings: AgentSettings,
    *,
    download_grants: ReportDownloadGrantService | None = None,
) -> tuple[Agent, Any, Agent, ReportWorkflowRuntime, ReportWorkflowController]:
    task_repository = TaskExecutionRepository(context.database)
    report_worker = create_report_worker(
        settings,
        context.database,
        context.workspace_service,
        task_repository,
        instructions=build_report_agent_instructions,
        report_coding_enable_thinking=settings.report_coding_enable_thinking,
        report_enable_vision=settings.report_enable_vision,
        context_token_budget=settings.context_token_budget,
        output_token_reserve=settings.output_token_reserve,
    )
    task_runner = ReportTaskRunner(
        task_repository,
        report_worker,
        TaskExecutionKernel(context.workspace_service, task_repository),
    )
    registry = load_configured_report_source_registry(settings.report_data_sources_dir)
    runtime = ReportWorkflowRuntime(
        db=context.database,
        planner=report_worker,
        report_worker=report_worker,
        task_runner=task_runner,
        workspace_service=context.workspace_service,
        registry=registry,
        profiles=load_configured_reporting_profiles(settings.report_data_sources_dir),
        planner_enable_thinking=settings.report_enable_thinking,
        metadata_client=(
            ReportingMetadataClient(
                settings.report_metadata_url,
                token=settings.report_metadata_token,
            )
            if settings.report_metadata_url
            else None
        ),
        download_grants=download_grants,
        server_identity_factory=(
            _standalone_server_identity if download_grants is not None else None
        ),
    )
    workflow = runtime.workflow()
    controller = ReportWorkflowController(
        runtime.workflow,
        cancel_cleanup=runtime.cleanup_cancelled,
    )
    return (
        create_report_agent(report_worker, controller),
        workflow,
        report_worker,
        runtime,
        controller,
    )


def create_agentos(settings: AgentSettings | None = None) -> AgentOS:
    current_settings = settings or AgentSettings.from_environment()
    authorization_config = agentos_authorization_config(current_settings)
    context = create_execution_context(current_settings)
    download_repository = SqlAlchemyDownloadGrantRepository(getattr(context.database, "db_engine"))
    download_grants = ReportDownloadGrantService(download_repository)
    reporting_agent, workflow, report_worker, runtime, controller = (
        create_report_agentos_components(context, current_settings, download_grants=download_grants)
    )
    base_app = FastAPI()
    base_app.include_router(_standalone_cancel_router(controller))
    base_app.include_router(
        create_workspace_report_download_router(
            WorkspaceReportDownloadHttpService(download_grants, context.workspace_service),
            scope_dependency=_standalone_download_scope(download_grants),
        )
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            await download_repository.create_schema()
            yield
        finally:
            await close_execution_resources(context, reporting_agent, report_worker)

    return AgentOS(
        name="Report AgentOS",
        agents=[reporting_agent],
        workflows=[workflow],
        interfaces=[ReportAGUI(agent=reporting_agent)],
        db=context.database,
        authorization=True,
        authorization_config=authorization_config,
        cors_allowed_origins=list(current_settings.cors_allowed_origins),
        lifespan=lifespan,
        base_app=base_app,
    )


def _standalone_server_identity(scope: dict[str, str]) -> ReportServerIdentity:
    return ReportServerIdentity(
        database="reporting",
        user_id=scope["user_id"],
        company_id="reporting",
        session_id=scope["thread_id"],
        thread_id=scope["thread_id"],
    )


def _standalone_cancel_router(controller: ReportWorkflowController) -> APIRouter:
    router = APIRouter()

    @router.post("/agui/cancel", include_in_schema=False)
    async def cancel_report(
        request: Request,
        payload: ReportCancelPayload,
    ) -> dict[str, Any]:
        user_id = resolve_run_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="缺少已认证用户身份。")
        try:
            result = await controller.cancel_external(
                external_run_id=payload.run_id,
                thread_id=payload.thread_id,
                user_id=user_id,
                probe_storage=True,
            )
        except ReportingError as error:
            raise HTTPException(status_code=409, detail=error.code) from error
        if result is None:
            raise HTTPException(status_code=404, detail="report_workflow_not_found")
        return result

    return router


def _standalone_download_scope(download_grants: ReportDownloadGrantService):
    async def resolve_scope(
        request: Request,
        opaque_grant: str,
    ) -> ReportDownloadCallerScope:
        user_id = resolve_run_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="缺少已认证用户身份。")
        grant = await download_grants.lookup(opaque_grant)
        if grant.scope.user_id != user_id or grant.scope.database != "reporting":
            raise HTTPException(status_code=403, detail="下载授权不属于当前用户。")
        return ReportDownloadCallerScope(
            database=grant.scope.database,
            user_id=user_id,
            company_id=grant.scope.company_id,
            session_id=grant.scope.session_id,
            thread_id=grant.scope.thread_id,
        )

    return resolve_scope


def main() -> None:
    settings = AgentSettings.from_environment()
    agent_os = create_agentos(settings)
    agent_os.serve(
        app="agentos_dev.coding.reporting.server:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        access_log=settings.access_log,
    )
