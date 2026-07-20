import json
import logging
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote

from ag_ui.core import EventType, RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from agno.os.interfaces.agui.input import extract_tool_messages, extract_user_input
from agno.os.interfaces.agui.router import run_entity
from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .agents import create_assistants
from .application import ApplicationContext, create_agentos_app
from .branch import (
    BranchError,
    capability_user_id,
    parse_forwarded_props,
    run_branch,
    validate_branch_identity,
)
from .database import check_database
from .instructions import AGENT_INSTRUCTIONS
from .security import CapabilityError, verify_capability
from .settings import AgentSettings
from .skills import load_skills
from .workspace import WorkspaceError, WorkspaceService

PROTOCOL = "agui.odoo.v2"
BUNDLE_VERSION = "12.0.8.7.0"
COMMAND_CATALOG_HASH = "66999dc4e1f22d94cf04b9fda3463c99538f00f86150204d4d0dea5d73c8cb60"
MAX_RUN_REQUEST_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = 12 * 1024 * 1024
MAX_JSON_MUTATION_REQUEST_BYTES = 64 * 1024
EDIT_MODE_TOOL = "odoo.enter_edit_mode"
EDIT_MODE_COMMANDS = frozenset(
    {
        "编辑",
        "修改",
        "进入编辑模式",
        "编辑当前表单",
        "编辑当前单据",
        "修改当前表单",
        "修改当前单据",
    }
)
EDIT_MODE_TOOL_CHOICE = {
    "type": "function",
    "function": {"name": EDIT_MODE_TOOL},
}
REQUIRED_TOOL_PREAMBLE_EVENTS = frozenset(
    {
        EventType.RUN_STARTED,
        EventType.STATE_SNAPSHOT,
        EventType.THINKING_START,
        EventType.THINKING_END,
        EventType.THINKING_TEXT_MESSAGE_START,
        EventType.THINKING_TEXT_MESSAGE_CONTENT,
        EventType.THINKING_TEXT_MESSAGE_END,
        EventType.REASONING_START,
        EventType.REASONING_MESSAGE_START,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_END,
        EventType.REASONING_END,
        EventType.REASONING_ENCRYPTED_VALUE,
    }
)
logger = logging.getLogger(__name__)


class WorkspaceDeleteFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    path: str
    recursive: StrictBool = False


settings = AgentSettings.from_environment()

workspace_secret = settings.workspace_hmac_secret
agent_skills = load_skills()
workspace_service = WorkspaceService(secret=workspace_secret)
router = APIRouter()


def _application_context(request: Request) -> ApplicationContext:
    return request.app.state.agentos_context


def _strip_trailing_punctuation(value: str) -> str:
    value = value.strip()
    while value and unicodedata.category(value[-1]).startswith("P"):
        value = value[:-1].rstrip()
    return value


def _is_explicit_edit_mode_request(run_input: RunAgentInput) -> bool:
    return (
        _strip_trailing_punctuation(
            extract_user_input(run_input.messages or []),
        )
        in EDIT_MODE_COMMANDS
    )


def _is_fresh_user_request(run_input: RunAgentInput) -> bool:
    messages = run_input.messages or []
    return bool(
        messages
        and messages[-1].role == "user"
        and not run_input.resume
        and not extract_tool_messages(messages)
    )


def _requires_menu_navigation(run_input: RunAgentInput) -> bool:
    for item in run_input.context or []:
        if item.description != "已选 Odoo 菜单":
            continue
        try:
            value = json.loads(item.value)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict) and value.get("navigationRequired") is True:
            return True
    return False


def _declares_tool(run_input: RunAgentInput, tool_name: str) -> bool:
    return any(tool.name == tool_name for tool in (run_input.tools or []))


def _audit_tool_route(request: Request, run_input: RunAgentInput, **values) -> None:
    request_id = request.headers.get("X-Request-ID", "") or run_input.run_id
    payload = {
        "event": "agui_tool_route",
        "run_id": run_input.run_id,
        "request_id": request_id[:256],
        **values,
    }
    logger.info("%s", json.dumps(payload, ensure_ascii=True, separators=(",", ":")))


async def _run_error(message: str, code: str):
    yield RunErrorEvent(type=EventType.RUN_ERROR, message=message, code=code)


async def _guard_required_tool(source, tool_name: str, audit=None):
    accepted = False
    violation = False
    try:
        async for event in source:
            if accepted:
                yield event
                continue
            if event.type == EventType.TOOL_CALL_START:
                if event.tool_call_name == tool_name:
                    accepted = True
                    if audit:
                        audit("accepted")
                    yield event
                    continue
                violation = True
                break
            if event.type in REQUIRED_TOOL_PREAMBLE_EVENTS:
                yield event
                continue
            violation = True
            break
        if not accepted:
            violation = True
    except Exception:
        if accepted:
            raise
        violation = True
    finally:
        if violation:
            close = getattr(source, "aclose", None)
            if close:
                try:
                    await close()
                except Exception:
                    # 关闭失败不能覆盖面向客户端的协议错误。
                    pass

    if violation:
        if audit:
            audit("required_tool_violation")
        yield RunErrorEvent(
            type=EventType.RUN_ERROR,
            message=f"模型未按要求首先调用 {tool_name}，已终止本次运行。",
            code="required_tool_violation",
        )


def _request_thread(request: Request) -> str:
    return str(request.headers.get("X-AGUI-Thread", "")).strip()


def _request_limit(path: str, method: str) -> int | None:
    if path == "/agui":
        return MAX_RUN_REQUEST_BYTES
    if path == "/workspace/upload":
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
    context = _application_context(request)
    path = request.url.path.rstrip("/") or "/"
    protected = path == "/agui" or path.startswith("/workspace")
    if not protected:
        return await call_next(request)
    thread = _request_thread(request)
    if not thread:
        return JSONResponse({"error": "thread_header_required"}, status_code=400)
    try:
        request.state.capability = verify_capability(
            request.headers.get("X-AGUI-Capability", ""),
            context.settings.workspace_hmac_secret,
            thread,
        )
    except CapabilityError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    limit = _request_limit(path, request.method)
    body = await _read_limited_body(request, limit) if limit else b""
    if body is None:
        return JSONResponse({"error": "request_too_large"}, status_code=413)
    if path == "/agui":
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            body_thread = str(payload.get("threadId") or "")
        except (AttributeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"error": "invalid_run_payload"}, status_code=400)
        if body_thread != thread:
            return JSONResponse({"error": "capability_thread_mismatch"}, status_code=403)
        try:
            branch = parse_forwarded_props(payload)
            request.state.branch = branch
            if branch:
                source_claims = verify_capability(
                    request.headers.get("X-AGUI-Source-Capability", ""),
                    context.settings.workspace_hmac_secret,
                    branch.source_thread_id,
                )
                validate_branch_identity(request.state.capability, source_claims)
                request.state.source_capability = source_claims
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=401)
        except BranchError as error:
            return JSONResponse({"error": str(error)}, status_code=403)
    return await call_next(request)


@router.get("/config", include_in_schema=False)
async def integration_config(request: Request):
    context = _application_context(request)
    return {
        "protocol": PROTOCOL,
        "bundle_version": BUNDLE_VERSION,
        "command_catalog_hash": COMMAND_CATALOG_HASH,
        "skills": context.skills.public_metadata(),
        "limits": {
            "run_request_bytes": MAX_RUN_REQUEST_BYTES,
            "workspace_upload_request_bytes": MAX_WORKSPACE_UPLOAD_REQUEST_BYTES,
            "json_mutation_request_bytes": MAX_JSON_MUTATION_REQUEST_BYTES,
        },
    }


def _readiness_checks(context: ApplicationContext):
    checks = {
        "postgresql": False,
        "sandbox_registry": False,
        "hmac": len(context.settings.workspace_hmac_secret.encode("utf-8")) >= 32,
    }
    try:
        check_database(context.settings.database_url)
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
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        entry = await run_in_threadpool(context.workspace_service.upload, threadId, path, content)
        return {"ok": True, "entry": entry}
    except Exception as error:
        _workspace_error(error)


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


assistant, edit_mode_assistant = create_assistants(
    settings,
    agent_skills,
    workspace_service,
    AGENT_INSTRUCTIONS,
    EDIT_MODE_TOOL_CHOICE,
)


@router.post("/agui", include_in_schema=False)
async def run_agui(request: Request, run_input: RunAgentInput):
    context = _application_context(request)
    claims = request.state.capability
    user_id = capability_user_id(claims)
    branch = getattr(request.state, "branch", None)
    encoder = EventEncoder()

    async def events():
        edit_intent = _is_explicit_edit_mode_request(run_input)
        fresh_request = _is_fresh_user_request(run_input)
        navigation_required = _requires_menu_navigation(run_input)
        force_edit_tool = bool(
            edit_intent and fresh_request and not branch and not navigation_required
        )
        tool_declared = _declares_tool(run_input, EDIT_MODE_TOOL)
        audit_values = {
            "forced_tool": EDIT_MODE_TOOL if force_edit_tool else None,
            "edit_route_matched": edit_intent,
            "forced_route_selected": force_edit_tool,
            "menu_navigation_required": navigation_required,
        }
        _audit_tool_route(
            request,
            run_input,
            guard_result="pending" if force_edit_tool else "not_applicable",
            error_code=None,
            **audit_values,
        )

        if branch:
            source = run_branch(
                context.assistant,
                context.workspace_service,
                run_input,
                branch,
                user_id,
            )
        elif not force_edit_tool:
            source = run_entity(context.assistant, run_input, user_id=user_id)
        elif not tool_declared:
            _audit_tool_route(
                request,
                run_input,
                guard_result="required_tool_unavailable",
                error_code="required_tool_unavailable",
                **audit_values,
            )
            source = _run_error(
                f"当前页面未声明 {EDIT_MODE_TOOL}，无法执行明确的编辑命令。",
                "required_tool_unavailable",
            )
        else:
            guarded_source = run_entity(
                context.edit_mode_assistant,
                run_input,
                user_id=user_id,
            )

            def audit_guard(result):
                _audit_tool_route(
                    request,
                    run_input,
                    guard_result=result,
                    error_code=result if result == "required_tool_violation" else None,
                    **audit_values,
                )

            source = _guard_required_tool(
                guarded_source,
                EDIT_MODE_TOOL,
                audit=audit_guard,
            )
        async for event in source:
            yield encoder.encode(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


def create_base_app(context: ApplicationContext) -> FastAPI:
    application = FastAPI(title="Odoo AG-UI 开发智能体")
    application.state.agentos_context = context
    application.middleware("http")(require_workspace_capability)
    application.include_router(router)
    return application


application_context = ApplicationContext(
    settings,
    workspace_service,
    agent_skills,
    assistant,
    edit_mode_assistant,
)
base_app = create_base_app(application_context)
agent_os, app = create_agentos_app(application_context, base_app)


if __name__ == "__main__":
    agent_os.serve(
        app="agentos_dev.app:app",
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        access_log=settings.access_log,
    )
