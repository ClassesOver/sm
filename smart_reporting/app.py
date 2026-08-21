import logging
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote

from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .agno_function_arguments import install_agno_function_argument_decoder
from .application import ApplicationContext, create_agentos_app
from .database import check_database, create_agent_database
from .execution_context import ExecutionContext, configure_execution_tracing
from .logging_config import configure_file_logging
from .reporting.agent import create_report_agent
from .reporting.bootstrap import create_report_runtime
from .reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
    create_report_download_router,
    install_report_download_access_log_filter,
)
from .reporting.workflow.controller import ReportWorkflowController
from .reporting_identity import (
    apply_report_identity,
    requires_workspace_capability,
)
from .security import CapabilityError, verify_capability
from .settings import AgentSettings
from .workspace import (
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)

MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = 202 * 1024 * 1024
WORKSPACE_FILE_BYTES = 200 * 1024 * 1024
MAX_JSON_MUTATION_REQUEST_BYTES = 64 * 1024
logger = logging.getLogger(__name__)


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
workspace_secret = settings.workspace_hmac_secret
agent_database = create_agent_database(settings.database_url)
configure_execution_tracing(agent_database, settings)
workspace_service = WorkspaceService(
    secret=workspace_secret,
    database=agent_database,
    snapshot=settings.workspace_snapshot,
    network_allow_list=settings.daytona_network_allow_list,
)
report_download_repository = SqlAlchemyDownloadGrantRepository(agent_database.async_engine)
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


def _application_context(request: Request) -> ApplicationContext:
    return request.app.state.agentos_context


def _request_thread(request: Request) -> str:
    return str(request.headers.get("X-Workspace-Thread", "")).strip()


def _request_limit(path: str, method: str) -> int | None:
    if path in {"/workspace/upload", "/workspace/files"} and method == "POST":
        return MAX_WORKSPACE_UPLOAD_REQUEST_BYTES
    if path.startswith("/workspace/") and method in {"POST", "PUT", "PATCH", "DELETE"}:
        return MAX_JSON_MUTATION_REQUEST_BYTES
    return None


async def _read_limited_body(request: Request, limit: int) -> bytes | None:
    content_length = request.headers.get("content-length")
    try:
        if content_length is not None and int(content_length) > limit:
            return None
    except ValueError:
        pass
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            return None
        chunks.append(chunk)
    body = b"".join(chunks)
    request._body = body
    return body


async def require_workspace_capability(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    thread = _request_thread(request)
    capability = str(request.headers.get("X-Workspace-Capability", "")).strip()
    if not requires_workspace_capability(
        path,
        has_thread=bool(thread),
        has_capability=bool(capability),
    ):
        return await call_next(request)
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
    limit = _request_limit(path, request.method)
    body = await _read_limited_body(request, limit) if limit else b""
    if body is None:
        return JSONResponse({"error": "request_too_large"}, status_code=413)
    # AgentOS 原生 run 表单允许调用方提交 user_id/session_id。这里用已验签的
    # Odoo 身份覆盖它们，避免合法 capability 被用于访问其他用户或 thread。
    apply_report_identity(
        request,
        user_id=str(request.state.capability.user),
        thread_id=thread,
    )
    return await call_next(request)


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
        entries = await run_in_threadpool(context.workspace_service.list_files, threadId, path)
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
    try:
        entry = await run_in_threadpool(context.workspace_service.upload, threadId, path, content)
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
        entry = await run_in_threadpool(
            context.workspace_service.create_file_locked,
            threadId,
            path,
            content,
        )
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
        content, mime_type = await run_in_threadpool(
            context.workspace_service.file_bytes,
            threadId,
            path,
        )
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
        await run_in_threadpool(
            context.workspace_service.delete_file,
            thread_id,
            payload.path,
            payload.recursive,
        )
        return {"ok": True}
    except Exception as error:
        _workspace_error(error)


@router.delete("/workspace/sandbox", include_in_schema=False)
async def workspace_destroy(request: Request, payload: dict = Body(...)):
    context = _application_context(request)
    thread_id = str(payload.get("threadId") or "")
    _check_thread(request, thread_id)
    try:
        deleted = await run_in_threadpool(context.workspace_service.destroy, thread_id)
    except Exception as error:
        _workspace_error(error)
    if not deleted:
        return JSONResponse({"ok": True, "deleted": False}, status_code=404)
    return {"ok": True, "deleted": True}


report_worker, report_runtime = create_report_runtime(
    ExecutionContext(
        settings=settings,
        database=agent_database.async_db,
        workspace_service=workspace_service,
        trace_database=agent_database.sync_db,
    ),
    settings,
    download_grants=report_download_grants,
    artifact_persistence=report_artifact_persistence,
)
report_workflow_controller = ReportWorkflowController(
    report_runtime.workflow,
    cancel_cleanup=report_runtime.cleanup_cancelled,
)
report_agent = create_report_agent(report_worker, report_workflow_controller)
report_workflow = report_runtime.workflow()


def create_base_app(context: ApplicationContext) -> FastAPI:
    application = FastAPI(title="开发智能体服务")
    application.state.agentos_context = context
    application.middleware("http")(require_workspace_capability)
    application.include_router(router)
    application.include_router(create_report_download_router(report_downloads))
    application.router.add_event_handler("startup", install_report_download_access_log_filter)
    application.router.add_event_handler("startup", report_download_repository.create_schema)
    return application


application_context = ApplicationContext(
    settings,
    workspace_service,
    report_agent,
    report_workflow=report_workflow,
    database=agent_database,
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
