"""独立 Report AgentOS 装配。"""

from contextlib import asynccontextmanager
from typing import Any

from agno.agent import Agent
from agno.os import AgentOS
from agno.os.middleware.user_scope import resolve_run_user_id
from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ...execution_context import (
    ExecutionContext,
    close_execution_resources,
    create_execution_context,
)
from ...settings import AgentSettings
from ...task_execution import TaskExecutionRepository
from ...task_execution.execution import TaskExecutionKernel
from .agent import create_report_agent, create_report_worker
from .data_source import load_configured_report_source_registry
from .delivery.publishing import (
    ReportDownloadCallerScope,
    ReportDownloadGrantService,
    SqlAlchemyDownloadGrantRepository,
    WorkspaceReportDownloadHttpService,
    create_workspace_report_download_router,
)
from .entrypoints import ReportServerIdentity
from .instructions import build_report_agent_instructions
from .interface import ReportAGUI
from .metadata import ReportingMetadataClient
from .models import ReportingError
from .profile import load_configured_reporting_profiles
from .workflow.controller import ReportWorkflowController, reporting_workflow_ids
from .workflow.events import ReportingEventBroker
from .workflow.execution import ReportTaskRunner
from .workflow.runtime import ReportWorkflowRuntime

_REPORTING_DEV_USER_ID = "reporting-dev"


async def _reporting_dev_user_middleware(request: Request, call_next: Any):
    if resolve_run_user_id(request) is None:
        request.state.user_id = _REPORTING_DEV_USER_ID
    return await call_next(request)


class ReportCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    run_id: str = Field(alias="runId", min_length=1, max_length=128)


def create_report_agentos_components(
    context: ExecutionContext,
    settings: AgentSettings,
    *,
    download_grants: ReportDownloadGrantService | None = None,
    event_broker: ReportingEventBroker | None = None,
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
        context_token_budget=settings.report_context_token_budget,
        output_token_reserve=settings.report_output_token_reserve,
    )
    task_runner = ReportTaskRunner(
        task_repository,
        report_worker,
        TaskExecutionKernel(context.workspace_service, task_repository),
        event_sink=event_broker.emit_worker if event_broker is not None else None,
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
        planner_reasoning_effort=settings.report_planner_reasoning_effort,
        workflow_event_sink=event_broker.emit_workflow if event_broker is not None else None,
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
    # TODO: DEV 调试结束后恢复独立 Reporting AgentOS 的 JWT 鉴权。
    # authorization_config = agentos_authorization_config(current_settings)
    context = create_execution_context(current_settings)
    download_repository = SqlAlchemyDownloadGrantRepository(getattr(context.database, "db_engine"))
    download_grants = ReportDownloadGrantService(download_repository)
    event_broker = ReportingEventBroker()
    reporting_agent, workflow, report_worker, runtime, controller = (
        create_report_agentos_components(
            context,
            current_settings,
            download_grants=download_grants,
            event_broker=event_broker,
        )
    )
    base_app = FastAPI()
    # TODO: DEV 调试结束并恢复 JWT 鉴权后移除此固定用户中间件。
    base_app.middleware("http")(_reporting_dev_user_middleware)
    base_app.include_router(_standalone_cancel_router(controller))
    base_app.include_router(_standalone_reporting_events_router(event_broker))
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
        authorization=False,
        # authorization_config=authorization_config,
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


def _standalone_reporting_events_router(event_broker: ReportingEventBroker) -> APIRouter:
    router = APIRouter()

    def event_response(
        request: Request,
        *,
        user_id: str,
        workflow_run_id: str,
        after: int,
    ) -> StreamingResponse:
        async def stream():
            async for event in event_broker.subscribe(
                user_id, workflow_run_id, after=max(0, after)
            ):
                if await request.is_disconnected():
                    return
                if event is None:
                    yield ": keepalive\n\n"
                    continue
                yield event.sse()
                if event.data.get("terminal") is True:
                    return

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "X-Reporting-Workflow-Run-ID": workflow_run_id,
            },
        )

    @router.get("/reporting/runs/{workflow_run_id}/events", include_in_schema=False)
    async def report_events(
        request: Request,
        workflow_run_id: str,
        after: int = 0,
    ) -> StreamingResponse:
        user_id = resolve_run_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="缺少已认证用户身份。")
        if not workflow_run_id.startswith("report-run-") or len(workflow_run_id) > 128:
            raise HTTPException(status_code=404, detail="report_workflow_not_found")

        return event_response(
            request,
            user_id=user_id,
            workflow_run_id=workflow_run_id,
            after=after,
        )

    @router.get("/reporting/external-runs/{external_run_id}/events", include_in_schema=False)
    async def external_report_events(
        request: Request,
        external_run_id: str,
        thread_id: str,
        after: int = 0,
    ) -> StreamingResponse:
        user_id = resolve_run_user_id(request)
        if not user_id:
            raise HTTPException(status_code=401, detail="缺少已认证用户身份。")
        if (
            not external_run_id
            or len(external_run_id) > 128
            or not thread_id
            or len(thread_id) > 256
        ):
            raise HTTPException(status_code=404, detail="report_workflow_not_found")
        _, workflow_run_id = reporting_workflow_ids(
            user_id=user_id,
            thread_id=thread_id,
            external_run_id=external_run_id,
        )
        return event_response(
            request,
            user_id=user_id,
            workflow_run_id=workflow_run_id,
            after=after,
        )

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
