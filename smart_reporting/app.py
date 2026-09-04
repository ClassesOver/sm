import unicodedata
from os import getenv
from pathlib import PurePosixPath
from urllib.parse import quote

from agno.os.config import MCPServerConfig
from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from loguru import logger as loguru_logger
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .context_management import validate_configured_tiktoken_cache
from .http.identity import (
    apply_report_identity,
    requires_workspace_capability,
)
from .http.request_limits import (
    RequestBodyLimitError,
    agentos_run_request_limit,
    install_streaming_body_limit,
    is_agentos_run_create,
    read_limited_body,
    request_body_limit_error,
    validate_agentos_run_multipart,
)
from .http.security import CapabilityError, verify_capability
from .integrations.agno_function_arguments import install_agno_function_argument_decoder
from .quality_warnings.api import create_quality_warning_router
from .quality_warnings.repository import SqlAlchemyQualityWarningRepository
from .quality_warnings.service import QualityWarningService
from .reporting.agent import create_report_agent
from .reporting.bootstrap import create_report_runtime
from .reporting.data_source.starrocks import StarRocksSourceConfig
from .reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
    create_report_download_router,
    install_report_download_access_log_filter,
)
from .reporting.diagnostics import (
    ReportingDependencyDiagnostics,
    create_reporting_dependency_diagnostics_router,
)
from .reporting.workflow.controller import ReportWorkflowController
from .reporting.workflow.repository import REPORTING_DB_SCHEMA
from .reporting_mcp import (
    ReportingMcpAdapter,
    create_reporting_mcp_tools,
)
from .reporting_mcp.identity import CapabilityTokenVerifier
from .runtime.application import ApplicationContext, create_agentos_app
from .runtime.database import check_database, create_agent_database
from .runtime.execution import ExecutionContext, configure_execution_tracing
from .runtime.logging import configure_file_logging
from .runtime.settings import AgentSettings
from .sandbox.factory import create_sandbox_provider
from .workspace import (
    AsyncSandboxRegistry,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)

MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = 202 * 1024 * 1024
WORKSPACE_FILE_BYTES = 200 * 1024 * 1024


class WorkspaceDeleteFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    path: str
    recursive: StrictBool = False


install_agno_function_argument_decoder()
settings = AgentSettings.from_environment()
configure_file_logging(
    settings.log_file_path,
    debug=settings.debug,
    max_bytes=settings.log_file_max_bytes,
    backup_count=settings.log_file_backup_count,
)
validate_configured_tiktoken_cache()
workspace_secret = settings.workspace_hmac_secret
agent_database = create_agent_database(settings.database_url)
configure_execution_tracing(agent_database, settings)
async_sandbox_registry = AsyncSandboxRegistry(agent_database.async_db)
sandbox_provider = create_sandbox_provider(settings, registry=async_sandbox_registry)
workspace_service = WorkspaceService(
    secret=workspace_secret,
    database=agent_database,
    snapshot=settings.workspace_snapshot,
    network_allow_list=settings.daytona_network_allow_list,
    async_registry=async_sandbox_registry,
    provider=sandbox_provider,
)
report_download_repository = SqlAlchemyDownloadGrantRepository(agent_database.async_engine)
quality_warning_repository = SqlAlchemyQualityWarningRepository(agent_database.async_engine)
quality_warning_service = QualityWarningService(quality_warning_repository)
report_artifact_repository = SqlAlchemyReportArtifactRepository(agent_database.async_engine)
report_download_grants = ReportDownloadGrantService(report_download_repository)
report_artifact_persistence = ReportArtifactPersistenceService(
    report_artifact_repository,
    workspace_service,
)
report_downloads = ReportDownloadHttpService(
    report_download_grants,
    report_artifact_repository,
)
router = APIRouter()


async def _log_reporting_runtime_identity() -> None:
    """记录实际启动的 Reporting 版本和数据库边界，便于确认镜像是否已更新。"""

    loguru_logger.info(
        "reporting_runtime_started workflow_id={} build_id={} database_backend={} "
        "reporting_schema={} workers={}",
        "enterprise-reporting-workflow-v1",
        getenv("REPORTING_BUILD_ID", "unknown"),
        agent_database.backend,
        REPORTING_DB_SCHEMA,
        settings.workers,
    )


def _application_context(request: Request) -> ApplicationContext:
    return request.app.state.agentos_context


def _request_thread(request: Request) -> str:
    return str(request.headers.get("X-Workspace-Thread", "")).strip()


def _request_limit(path: str, method: str) -> int | None:
    if path in {"/workspace/upload", "/workspace/files"} and method == "POST":
        return MAX_WORKSPACE_UPLOAD_REQUEST_BYTES
    return agentos_run_request_limit(path, method)


async def require_workspace_capability(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    thread = _request_thread(request)
    capability = str(request.headers.get("X-Workspace-Capability", "")).strip()
    capability_required = requires_workspace_capability(
        path,
        has_thread=bool(thread),
        has_capability=bool(capability),
    )
    if capability_required:
        if not thread:
            return JSONResponse({"error": "thread_header_required"}, status_code=400)
        context = _application_context(request)
        try:
            request.state.capability = verify_capability(
                capability,
                context.settings.workspace_hmac_secret,
                thread,
            )
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=401)
    workspace_upload = (
        path in {"/workspace/upload", "/workspace/files"} and request.method == "POST"
    )
    streaming_limit = None
    if workspace_upload:
        try:
            streaming_limit = install_streaming_body_limit(
                request, MAX_WORKSPACE_UPLOAD_REQUEST_BYTES
            )
        except RequestBodyLimitError as error:
            return JSONResponse({"error": error.code}, status_code=error.status_code)

    limit = None if workspace_upload else _request_limit(path, request.method)
    body = await read_limited_body(request, limit) if limit else b""
    if body is None:
        return JSONResponse({"error": "request_too_large"}, status_code=413)
    if body and is_agentos_run_create(path, request.method):
        try:
            validate_agentos_run_multipart(request.headers.get("content-type", ""), body)
        except RequestBodyLimitError as error:
            return JSONResponse({"error": error.code}, status_code=error.status_code)
    # AgentOS 原生 run 表单允许调用方提交 user_id/session_id。这里用已验签的
    # Odoo 身份覆盖它们，避免合法 capability 被用于访问其他用户或 thread。
    if capability_required:
        apply_report_identity(
            request,
            user_id=str(request.state.capability.user),
            thread_id=thread,
            database=request.state.capability.database,
            company_id=str(request.state.capability.company),
        )
    try:
        response = await call_next(request)
    except (RequestBodyLimitError, BaseExceptionGroup) as error:
        limit_error = request_body_limit_error(error)
        if limit_error is None:
            raise
        return JSONResponse({"error": limit_error.code}, status_code=limit_error.status_code)
    # FastAPI 的 multipart 解析器会把 receive 异常统一转换为 400；传输层记录的
    # 超限事实优先级更高，不能因解析器的异常归一化而绕过 413 契约。
    if streaming_limit is not None and streaming_limit.error is not None:
        return JSONResponse(
            {"error": streaming_limit.error.code},
            status_code=streaming_limit.error.status_code,
        )
    return response


def _readiness_checks(context: ApplicationContext):
    checks = {
        "postgresql": False,
        "sandbox_registry": False,
        "hmac": len(context.settings.workspace_hmac_secret.encode("utf-8")) >= 32,
    }
    try:
        check_database(context.database or context.settings.database_url)
        checks["postgresql"] = True
    except Exception:
        return checks
    try:
        context.workspace_service.registry.ensure_initialized()
        checks["sandbox_registry"] = True
    except Exception:
        pass
    return checks


@router.get("/ready", include_in_schema=False)
async def readiness(request: Request):
    checks = await run_in_threadpool(_readiness_checks, _application_context(request))
    ready = all(checks.values())
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )


def _check_thread(request: Request, thread_id: str):
    claims = getattr(request.state, "capability", None)
    if not claims or claims.thread != thread_id or _request_thread(request) != thread_id:
        raise HTTPException(status_code=403, detail="capability_thread_mismatch")


def _workspace_error(error: Exception):
    if isinstance(error, WorkspaceError):
        raise HTTPException(status_code=400, detail=str(error)) from error
    raise HTTPException(status_code=502, detail="workspace_backend_failed") from error


def _content_disposition(disposition: str, filename: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    if not ascii_name or ascii_name.startswith("."):
        suffix = PurePosixPath(filename).suffix
        ascii_suffix = unicodedata.normalize("NFKD", suffix).encode("ascii", "ignore").decode()
        ascii_name = f"download{ascii_suffix}"
    encoded_name = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{encoded_name}"


@router.get("/workspace/files", include_in_schema=False)
async def workspace_files(request: Request, threadId: str, path: str = ""):
    context = _application_context(request)
    _check_thread(request, threadId)
    try:
        entries = await context.workspace_service.alist_files(threadId, path)
        return {"ok": True, "path": path, "entries": entries}
    except Exception as error:
        _workspace_error(error)


@router.post("/workspace/upload", include_in_schema=False)
async def workspace_upload(
    request: Request,
    threadId: str = Form(...),
    path: str = Form(...),
    file: UploadFile = File(...),
):
    context = _application_context(request)
    _check_thread(request, threadId)
    content = await file.read(WORKSPACE_FILE_BYTES + 1)
    if len(content) > WORKSPACE_FILE_BYTES:
        return JSONResponse({"error": "export_file_too_large"}, status_code=413)
    try:
        entry = await context.workspace_service.aupload(threadId, path, content)
        return {"ok": True, "entry": entry}
    except Exception as error:
        _workspace_error(error)


@router.post("/workspace/files", include_in_schema=False, status_code=201)
async def workspace_file_create(
    request: Request,
    threadId: str = Form(...),
    path: str = Form(...),
    file: UploadFile = File(...),
):
    context = _application_context(request)
    _check_thread(request, threadId)
    content = await file.read(WORKSPACE_FILE_BYTES + 1)
    if len(content) > WORKSPACE_FILE_BYTES:
        return JSONResponse({"error": "export_file_too_large"}, status_code=413)
    try:
        entry = await context.workspace_service.acreate_file_locked(threadId, path, content)
        return JSONResponse({"ok": True, "entry": entry}, status_code=201)
    except WorkspacePathConflict:
        return JSONResponse({"error": "workspace_path_conflict"}, status_code=409)
    except Exception:
        return JSONResponse({"error": "workspace_upload_failed"}, status_code=502)


@router.get("/workspace/file", include_in_schema=False)
async def workspace_file(
    request: Request,
    threadId: str,
    path: str,
    download: bool = False,
):
    context = _application_context(request)
    _check_thread(request, threadId)
    try:
        content, mime_type = await context.workspace_service.afile_bytes(threadId, path)
    except Exception as error:
        _workspace_error(error)
    safe_name = (
        "".join(
            char
            for char in path.rsplit("/", 1)[-1]
            if ord(char) >= 32 and ord(char) != 127 and char not in {'"', "\\"}
        )
        or "download"
    )
    disposition = "attachment" if download else "inline"
    if not download and mime_type not in {
        "application/json",
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/webp",
        "text/csv",
        "text/markdown",
        "text/plain",
    }:
        mime_type = "application/octet-stream"
        disposition = "attachment"
    return Response(
        content,
        media_type=mime_type,
        headers={
            "Content-Disposition": _content_disposition(disposition, safe_name),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/workspace/file", include_in_schema=False)
async def workspace_delete_file(
    request: Request,
    payload: WorkspaceDeleteFilePayload = Body(...),
):
    context = _application_context(request)
    thread_id = payload.thread_id
    _check_thread(request, thread_id)
    try:
        await context.workspace_service.adelete_file(thread_id, payload.path, payload.recursive)
        return {"ok": True}
    except Exception as error:
        _workspace_error(error)


@router.delete("/workspace/sandbox", include_in_schema=False)
async def workspace_destroy(request: Request, payload: dict = Body(...)):
    context = _application_context(request)
    thread_id = str(payload.get("threadId") or "")
    _check_thread(request, thread_id)
    try:
        deleted = await context.workspace_service.adestroy(thread_id)
    except Exception as error:
        _workspace_error(error)
    if not deleted:
        return JSONResponse({"ok": True, "deleted": False}, status_code=404)
    return {"ok": True, "deleted": True}


reporting_agent_template, report_runtime = create_report_runtime(
    ExecutionContext(
        settings=settings,
        database=agent_database.async_db,
        workspace_service=workspace_service,
        trace_database=agent_database.sync_db,
    ),
    settings,
    download_grants=report_download_grants,
    artifact_persistence=report_artifact_persistence,
    quality_warning_service=quality_warning_service,
)
report_workflow_controller = ReportWorkflowController(
    report_runtime.workflow,
    thread_ownership=report_runtime.state_repository,
    terminal_cleanup=report_runtime.cleanup_terminal,
)
report_agent = create_report_agent(reporting_agent_template, report_workflow_controller)
reporting_dependency_diagnostics = ReportingDependencyDiagnostics(
    sources=tuple(
        source
        for source in report_runtime.registry.sources.values()
        if isinstance(source, StarRocksSourceConfig)
    ),
    metadata_client=report_runtime.metadata_client,
    sandbox_check=workspace_service.check_sandbox_service,
)
router.include_router(
    create_reporting_dependency_diagnostics_router(reporting_dependency_diagnostics)
)


def create_base_app(context: ApplicationContext) -> FastAPI:
    application = FastAPI(title="开发智能体服务")
    application.state.agentos_context = context
    application.middleware("http")(require_workspace_capability)
    application.include_router(router)
    application.include_router(create_report_download_router(report_downloads))
    application.include_router(create_quality_warning_router())
    application.router.add_event_handler("startup", _log_reporting_runtime_identity)
    application.router.add_event_handler("startup", install_report_download_access_log_filter)
    application.router.add_event_handler("startup", report_download_repository.create_schema)
    application.router.add_event_handler("startup", quality_warning_service.create_schema)
    return application


application_context = ApplicationContext(
    settings,
    workspace_service,
    report_agent,
    database=agent_database,
    quality_warning_service=quality_warning_service,
    mcp_config=MCPServerConfig(
        tools=create_reporting_mcp_tools(
            ReportingMcpAdapter(report_workflow_controller, workspace_service)
        ),
        enable_builtin_tools=False,
        allowed_hosts=list(settings.reporting_mcp_allowed_hosts),
    ),
    mcp_auth=CapabilityTokenVerifier(settings.workspace_hmac_secret),
    report_workflow_controller=report_workflow_controller,
)
base_app = create_base_app(application_context)
agent_os, app = create_agentos_app(application_context, base_app)


if __name__ == "__main__":
    agent_os.serve(
        app="smart_reporting.app:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        access_log=settings.access_log,
    )
