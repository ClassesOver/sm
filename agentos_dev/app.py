import asyncio
import json
import logging
import unicodedata
from contextlib import suppress
from pathlib import PurePosixPath
from typing import cast
from urllib.parse import quote

from ag_ui.core import (
    Context,
    EventType,
    RunAgentInput,
    RunErrorEvent,
)
from ag_ui.encoder import EventEncoder
from agno.agent import Agent
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.os.interfaces.agui.input import extract_tool_messages, extract_user_input
from agno.os.interfaces.agui.router import run_entity
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team import Team
from daytona.common.errors import DaytonaNotFoundError
from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .agent_control import (
    AGENT_CONTEXT_STATUS_DEPENDENCY,
    AGENT_CONTINUATION_STATE_KEY,
    AGENT_LOADED_TOOLKITS_STATE_KEY,
    AGENT_PLAN_STATE_KEY,
)
from .agents import (
    create_assistant_team,
    create_assistants,
    is_odoo_command_name,
)
from .application import ApplicationContext, create_agentos_app
from .branch import (
    BranchError,
    capability_user_id,
    parse_forwarded_props,
    run_branch,
    validate_branch_identity,
)
from .coding import AgnoCodingExecutor, CodingTaskSupervisor
from .coding.agent import create_coding_agent
from .coding.execution import (
    CODING_EXECUTION_MIGRATION_STATE_KEY,
    CODING_FINISH_FAILURE_STATE_KEY,
    CODING_FINISH_STATE_KEY,
    CODING_TASK_DEPENDENCY,
    CODING_TOOL_OUTPUT_STATE_KEY,
    CODING_TOOL_PROGRESS_STATE_KEY,
    CodingExecutionKernel,
)
from .coding.reporting.agent import (
    create_report_agent,
    create_report_worker,
)
from .coding.reporting.agui import bind_server_request, prepare_agui_envelope
from .coding.reporting.controller import (
    REPORT_WORKFLOW_CONTROL_STATE_KEY,
    ReportWorkflowController,
)
from .coding.reporting.data_source import load_configured_report_source_registry
from .coding.reporting.data_sources import (
    CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
    REPORT_DATASET_HANDLES_STATE_KEY,
)
from .coding.reporting.entrypoints import ReportServerIdentity
from .coding.reporting.instructions import build_report_agent_instructions
from .coding.reporting.metadata import ReportingMetadataClient
from .coding.reporting.models import ReportingError
from .coding.reporting.publishing import (
    ReportDownloadCallerScope,
    ReportDownloadGrantService,
    SqlAlchemyDownloadGrantRepository,
    WorkspaceReportDownloadHttpService,
    create_workspace_report_download_router,
    install_report_download_access_log_filter,
)
from .coding.reporting.runtime import ReportWorkflowRuntime
from .coding.reporting.workspace import (
    REPORT_DELIVERY_STATE_KEY,
    REPORT_JOBS_STATE_KEY,
)
from .coding.repository import (
    TERMINAL_EXECUTION_STATUSES,
    CodingRepositoryError,
    CodingTaskRepository,
)
from .coding.tools import (
    CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
    CODEX_EXEC_NEXT_SESSION_STATE_KEY,
    CODEX_EXEC_SESSIONS_STATE_KEY,
)
from .context_management import (
    HISTORY_CONTEXT_DESCRIPTION,
    ProtectedCompressionManager,
    build_budgeted_history_context,
)
from .database import check_database, create_agent_database
from .instructions import (
    build_agent_instructions,
    build_odoo_command_instructions,
)
from .observability import configure_tracing
from .security import CapabilityError, verify_capability
from .settings import AgentSettings
from .skills import SkillValidatorRegistry, load_skills, public_skill_metadata
from .workspace import (
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)

PROTOCOL = "agui.odoo.v2"
BUNDLE_VERSION = "12.0.8.8.11"
COMMAND_CATALOG_HASH = "6529262bf0a1c05a61a1238c67415ed3734e0db58bc12dcd59cf6c534d2467f4"
MAX_RUN_REQUEST_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = 202 * 1024 * 1024
WORKSPACE_FILE_BYTES = 200 * 1024 * 1024
MAX_JSON_MUTATION_REQUEST_BYTES = 64 * 1024
SSE_HEARTBEAT_SECONDS = 15
SERVER_TOOL_SCHEMA_TOKEN_RESERVE = 16 * 1024
RAW_REASONING_EVENTS = frozenset(
    {
        EventType.THINKING_TEXT_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_CONTENT,
        EventType.REASONING_MESSAGE_CHUNK,
        EventType.REASONING_ENCRYPTED_VALUE,
    }
)
SERVER_SESSION_STATE_KEYS = frozenset(
    {
        AGENT_PLAN_STATE_KEY,
        AGENT_CONTINUATION_STATE_KEY,
        AGENT_LOADED_TOOLKITS_STATE_KEY,
        REPORT_DATASET_HANDLES_STATE_KEY,
        REPORT_DELIVERY_STATE_KEY,
        REPORT_JOBS_STATE_KEY,
        REPORT_WORKFLOW_CONTROL_STATE_KEY,
        CODEX_EXEC_CLOSED_SESSIONS_STATE_KEY,
        CODEX_EXEC_SESSIONS_STATE_KEY,
        CODEX_EXEC_NEXT_SESSION_STATE_KEY,
        CODING_EXECUTION_MIGRATION_STATE_KEY,
        CODING_FINISH_FAILURE_STATE_KEY,
        CODING_FINISH_STATE_KEY,
        CODING_TOOL_OUTPUT_STATE_KEY,
        CODING_TOOL_PROGRESS_STATE_KEY,
    }
)
logger = logging.getLogger(__name__)
REPORT_SKILL_CONTEXT_DESCRIPTION = "已选智能体技能"


class WorkspaceDeleteFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    path: str
    recursive: StrictBool = False


class CodingCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    run_id: str = Field(alias="runId", min_length=1, max_length=128)


settings = AgentSettings.from_environment()
workspace_secret = settings.workspace_hmac_secret
agent_skills = load_skills(settings.skills_dir)
agent_database = create_agent_database(settings.database_url)
configure_tracing(
    agent_database.async_db,
    enabled=settings.tracing_enabled,
    phoenix_endpoint=settings.tracing_phoenix_endpoint,
    phoenix_api_key=settings.tracing_phoenix_api_key,
    phoenix_project_name=settings.tracing_phoenix_project_name,
)
coding_repository = CodingTaskRepository(agent_database.async_db)
workspace_service = WorkspaceService(
    secret=workspace_secret,
    database=agent_database,
    snapshot=settings.workspace_snapshot,
    network_allow_list=settings.daytona_network_allow_list,
)
report_download_repository = SqlAlchemyDownloadGrantRepository(agent_database.async_engine)
report_download_grants = ReportDownloadGrantService(report_download_repository)
report_downloads = WorkspaceReportDownloadHttpService(report_download_grants, workspace_service)
router = APIRouter()


def _application_context(request: Request) -> ApplicationContext:
    return request.app.state.agentos_context


def _is_fresh_user_request(run_input: RunAgentInput) -> bool:
    messages = run_input.messages or []
    return bool(
        messages
        and messages[-1].role == "user"
        and not run_input.resume
        and not extract_tool_messages(messages)
    )


def _sanitize_run_input(run_input: RunAgentInput) -> RunAgentInput:
    context = [
        item
        for item in (run_input.context or [])
        if item.description
        not in {
            HISTORY_CONTEXT_DESCRIPTION,
            AGENT_CONTEXT_STATUS_DEPENDENCY,
            CODING_TASK_DEPENDENCY,
            CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
        }
    ]
    state = run_input.state
    if isinstance(state, dict):
        state = {key: value for key, value in state.items() if key not in SERVER_SESSION_STATE_KEYS}
    if len(context) == len(run_input.context or []) and state is run_input.state:
        return run_input
    return run_input.model_copy(update={"context": context, "state": state})


async def _prepare_run_input(
    agent,
    run_input: RunAgentInput,
    user_id: str,
    settings,
    *,
    server_context: list[Context] | None = None,
):
    prepared = _sanitize_run_input(run_input)
    if server_context:
        prepared = prepared.model_copy(
            update={"context": [*(prepared.context or []), *server_context]}
        )
    if not _is_fresh_user_request(prepared):
        return prepared
    session_owner = agent
    try:
        session = await session_owner.aget_session(
            session_id=prepared.thread_id,
            user_id=user_id,
        )
    except Exception as error:
        logger.warning("history_context_load_failed error_type=%s", type(error).__name__)
        return prepared
    if not isinstance(session, (AgentSession, TeamSession)):
        return prepared

    compression_manager = (
        agent.compression_manager
        if isinstance(agent.compression_manager, ProtectedCompressionManager)
        else None
    )
    history_status: dict[str, object] = {}
    mandatory_messages = [Message(role="user", content=extract_user_input(prepared.messages or []))]
    mandatory_messages.extend(
        Message(role="user", content=item.value) for item in prepared.context or []
    )
    if prepared.tools:
        mandatory_messages.append(
            Message(
                role="user",
                content=json.dumps(
                    [
                        item.model_dump() if hasattr(item, "model_dump") else item
                        for item in prepared.tools
                    ],
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
            )
        )
    mandatory_tokens: int | None
    try:
        mandatory_tokens = agent.model.count_tokens(mandatory_messages)
    except Exception:
        mandatory_tokens = None
    effective_history_budget = min(
        settings.history_token_budget,
        max(
            1,
            settings.context_token_budget
            - settings.output_token_reserve
            - SERVER_TOOL_SCHEMA_TOKEN_RESERVE
            - (mandatory_tokens or 0),
        ),
    )
    try:
        history, changed = await build_budgeted_history_context(
            session,
            agent.model,
            history_token_budget=effective_history_budget,
            compression_manager=compression_manager,
            include_summary=settings.enable_session_summaries,
            status=history_status,
        )
    except Exception as error:
        logger.warning("history_context_build_failed error_type=%s", type(error).__name__)
        return prepared
    history_status.update(
        {
            "configuredHistoryTokenBudget": settings.history_token_budget,
            "contextTokenBudget": settings.context_token_budget,
            "outputReserveTokens": settings.output_token_reserve,
            "mandatoryContextTokensEstimate": mandatory_tokens,
        }
    )

    if changed:
        if session.session_data is None:
            session.session_data = {}
        try:
            if isinstance(session_owner, Team) and isinstance(session, TeamSession):
                await session_owner.asave_session(session)
            elif isinstance(session_owner, Agent) and isinstance(session, AgentSession):
                await session_owner.asave_session(session)
        except Exception as error:
            logger.warning("history_compression_save_failed error_type=%s", type(error).__name__)
    context = list(prepared.context or [])
    if history is not None:
        context.append(history)
    context.append(
        Context(
            description=AGENT_CONTEXT_STATUS_DEPENDENCY,
            value=json.dumps(history_status, ensure_ascii=False, separators=(",", ":")),
        )
    )
    return prepared.model_copy(update={"context": context})


def _has_reasoning_key(value) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if ("reasoning" in normalized or "thinking" in normalized) and item not in (
                None,
                "",
                False,
                [],
                {},
            ):
                return True
            if _has_reasoning_key(item):
                return True
    elif isinstance(value, list):
        return any(_has_reasoning_key(item) for item in value)
    return False


def _is_raw_reasoning_event(event) -> bool:
    if event.type in RAW_REASONING_EVENTS:
        return True
    return event.type == EventType.RAW and _has_reasoning_key(getattr(event, "event", None))


async def _team_for_stored_run(
    context: ApplicationContext,
    thread_id: str,
    user_id: str,
    run_id: str | None = None,
) -> Agent | Team | None:
    try:
        team_session = await context.assistant_team.aget_session(
            session_id=thread_id, user_id=user_id
        )
    except Exception as error:
        logger.warning("team_route_session_load_failed error_type=%s", type(error).__name__)
        return None
    if isinstance(team_session, TeamSession) and team_session.team_id == context.assistant_team.id:
        if not run_id or any(run.run_id == run_id for run in (team_session.runs or [])):
            return context.assistant_team
    return None


def _report_skill_selected(run_input: RunAgentInput) -> bool:
    for item in run_input.context or []:
        if item.description != REPORT_SKILL_CONTEXT_DESCRIPTION:
            continue
        try:
            selected = json.loads(item.value)
        except (TypeError, ValueError):
            continue
        if not isinstance(selected, list):
            continue
        for skill in selected:
            if not isinstance(skill, dict):
                continue
            identifiers = {str(skill.get(key) or "").strip().lower() for key in ("id", "name")}
            if "report" in identifiers:
                return True
    return False


async def _has_active_report_workflow(agent: Agent, thread_id: str, user_id: str) -> bool:
    try:
        session = await agent.aget_session(session_id=thread_id, user_id=user_id)
    except Exception as error:
        logger.warning("report_route_session_load_failed error_type=%s", type(error).__name__)
        return False
    if not isinstance(session, AgentSession) or not isinstance(session.session_data, dict):
        return False
    state = session.session_data.get("session_state")
    if not isinstance(state, dict):
        state = getattr(session, "session_state", None)
    if not isinstance(state, dict):
        return False
    control = state.get(REPORT_WORKFLOW_CONTROL_STATE_KEY)
    return isinstance(control, dict) and control.get("status") in {"running", "paused"}


async def _hide_team_delegation_events(source):
    hidden_call_ids: set[str] = set()
    async for event in source:
        call_id = str(getattr(event, "tool_call_id", "") or "")
        if event.type == EventType.TOOL_CALL_START and (
            getattr(event, "tool_call_name", "") == "delegate_task_to_member"
        ):
            if call_id:
                hidden_call_ids.add(call_id)
            continue
        if call_id and call_id in hidden_call_ids:
            continue
        yield event


def _filter_odoo_client_tools(run_input: RunAgentInput) -> RunAgentInput:
    declared_tools = list(run_input.tools or [])
    tools = [tool for tool in declared_tools if is_odoo_command_name(getattr(tool, "name", None))]
    if len(tools) == len(declared_tools):
        return run_input
    return run_input.model_copy(update={"tools": tools})


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


async def _run_report_entity(
    agent: Agent,
    run_input: RunAgentInput,
    envelope,
    user_id: str,
    identity: ReportServerIdentity,
):
    source = run_entity(agent, run_input, user_id=user_id).__aiter__()
    while True:
        with bind_server_request(envelope, identity):
            try:
                event = await source.__anext__()
            except StopAsyncIteration:
                return
        yield event


async def _with_sse_heartbeats(source):
    iterator = source.__aiter__()
    pending = asyncio.create_task(iterator.__anext__())
    try:
        while True:
            done, _pending = await asyncio.wait({pending}, timeout=SSE_HEARTBEAT_SECONDS)
            if not done:
                yield None
                continue
            try:
                event = pending.result()
            except StopAsyncIteration:
                return
            yield event
            pending = asyncio.create_task(iterator.__anext__())
    finally:
        if not pending.done():
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending


def _request_thread(request: Request) -> str:
    return str(request.headers.get("X-AGUI-Thread", "")).strip()


def _request_limit(path: str, method: str) -> int | None:
    if path == "/agui" or (path == "/agui/cancel" and method == "POST"):
        return MAX_RUN_REQUEST_BYTES
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
    context = _application_context(request)
    path = request.url.path.rstrip("/") or "/"
    path_parts = path.strip("/").split("/")
    if len(path_parts) >= 3 and path_parts[0] in {"agents", "teams"} and path_parts[2] == "runs":
        resource = path_parts[0][:-1]
        return JSONResponse({"error": f"{resource}_run_route_disabled"}, status_code=404)
    protected = (
        path in {"/agui", "/agui/cancel"}
        or path.startswith("/workspace")
        or path.startswith("/reports/v1/download/")
    )
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
        "skills": public_skill_metadata(context.skills),
        "limits": {
            "run_request_bytes": MAX_RUN_REQUEST_BYTES,
            "workspace_upload_request_bytes": MAX_WORKSPACE_UPLOAD_REQUEST_BYTES,
            "workspace_file_bytes": WORKSPACE_FILE_BYTES,
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


async def _report_download_scope(request: Request) -> ReportDownloadCallerScope:
    claims = getattr(request.state, "capability", None)
    thread = _request_thread(request)
    if claims is None or claims.thread != thread:
        raise HTTPException(status_code=403, detail="capability_thread_mismatch")
    return ReportDownloadCallerScope(
        database=claims.database,
        user_id=str(claims.user),
        company_id=str(claims.company),
        session_id=claims.odoo_session,
        thread_id=thread,
    )


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


@router.post("/agui/cancel", include_in_schema=False)
async def cancel_coding_task(request: Request, payload: CodingCancelPayload):
    context = _application_context(request)
    _check_thread(request, payload.thread_id)
    report_controller = context.report_workflow_controller
    user_id = capability_user_id(request.state.capability)

    async def cancel_report(*, probe_storage: bool):
        if report_controller is None:
            return None
        try:
            return await report_controller.cancel_external(
                external_run_id=payload.run_id,
                thread_id=payload.thread_id,
                user_id=user_id,
                probe_storage=probe_storage,
            )
        except ReportingError as error:
            raise HTTPException(status_code=409, detail=error.code) from error

    report_result = await cancel_report(probe_storage=False)
    if report_result is not None:
        return report_result
    if context.coding_repository is None:
        report_result = await cancel_report(probe_storage=True)
        if report_result is not None:
            return report_result
        raise HTTPException(status_code=404, detail="coding_task_not_found")
    snapshot = await context.coding_repository.get_task_snapshot(payload.run_id)
    if snapshot is not None and context.coding_supervisor is not None:
        try:
            task = await context.coding_supervisor.cancel_task(snapshot.scope)
        except CodingRepositoryError as error:
            raise HTTPException(status_code=409, detail=error.code) from error
        return {"ok": True, "status": task.state.value}
    legacy_task = await context.coding_repository.get_task(payload.run_id)
    if legacy_task is None:
        report_result = await cancel_report(probe_storage=True)
        if report_result is not None:
            return report_result
        raise HTTPException(status_code=404, detail="coding_task_not_found")
    try:
        context.coding_repository._assert_scope(
            legacy_task,
            capability_user_id(request.state.capability),
            payload.thread_id,
        )
    except CodingRepositoryError as error:
        raise HTTPException(status_code=403, detail=error.code) from error
    if legacy_task.status == "cancelled":
        return {"ok": True, "status": "cancelled", "status_is_cached": True}
    executions = await context.coding_repository.list_executions(payload.run_id)
    async with context.workspace_service._async_client() as client:
        sandbox = await context.workspace_service._asandbox_for(client, payload.thread_id)
        if str(getattr(sandbox, "id", "") or "") != legacy_task.sandbox_id:
            raise HTTPException(status_code=409, detail="coding_task_sandbox_mismatch")
        await context.coding_repository.set_task_status(payload.run_id, "cancelled")
        for execution in executions:
            if execution.status in TERMINAL_EXECUTION_STATUSES or execution.retained_service:
                continue
            await context.coding_repository.update_execution(
                execution.execution_id,
                status="terminated",
            )
            with suppress(DaytonaNotFoundError):
                await sandbox.process.delete_session(execution.daytona_session_id)
    return {"ok": True, "status": "cancelled"}


assistant = create_assistants(
    settings,
    agent_skills,
    workspace_service,
    build_agent_instructions,
    agent_database,
)
coding_agent = create_coding_agent(
    assistant,
    workspace_service,
    coding_repository,
    context_token_budget=settings.context_token_budget,
    output_token_reserve=settings.output_token_reserve,
)
# Coding/Report 不属于助手 Team，继续沿用各自原有的长任务执行配置。
coding_agent.checkpoint = "tool-batch"
coding_model = cast(OpenAIChat, coding_agent.model)
coding_model.extra_body = {
    **(coding_model.extra_body or {}),
    "enable_thinking": settings.enable_thinking,
}
report_worker = create_report_worker(
    coding_agent,
    workspace_service,
    coding_repository,
    instructions=build_report_agent_instructions,
    context_token_budget=settings.context_token_budget,
    output_token_reserve=settings.output_token_reserve,
)
report_supervisor = CodingTaskSupervisor(
    coding_repository,
    AgnoCodingExecutor(lambda _agent_id: report_worker),
    execution_cleanup=CodingExecutionKernel(workspace_service, coding_repository),
    validator_registry=SkillValidatorRegistry.from_skills(report_worker.skills),
)
report_source_registry = load_configured_report_source_registry(settings.report_data_sources_dir)
report_runtime = ReportWorkflowRuntime(
    db=agent_database.async_db,
    planner=report_worker,
    report_worker=report_worker,
    supervisor=report_supervisor,
    workspace_service=workspace_service,
    registry=report_source_registry,
    metadata_client=(
        ReportingMetadataClient(
            settings.report_metadata_url,
            token=settings.report_metadata_token,
        )
        if settings.report_metadata_url
        else None
    ),
    download_grants=report_download_grants,
)
report_workflow_controller = ReportWorkflowController(
    report_runtime.workflow,
    cancel_cleanup=report_runtime.cleanup_cancelled,
    publication_issuer=report_runtime.issue_http_publication,
)
report_agent = create_report_agent(report_worker, report_workflow_controller)
coding_supervisor = CodingTaskSupervisor(
    coding_repository,
    AgnoCodingExecutor(lambda _agent_id: coding_agent),
    execution_cleanup=CodingExecutionKernel(workspace_service, coding_repository),
    validator_registry=SkillValidatorRegistry.from_skills(coding_agent.skills),
)
assistant_team = create_assistant_team(
    assistant,
    build_odoo_command_instructions,
)


@router.post("/agui", include_in_schema=False)
async def run_agui(request: Request, run_input: RunAgentInput):
    context = _application_context(request)
    claims = request.state.capability
    user_id = capability_user_id(claims)
    branch = getattr(request.state, "branch", None)
    encoder = EventEncoder()

    async def events():
        filtered_input = _filter_odoo_client_tools(run_input)
        declared_odoo_commands = [tool.name for tool in (filtered_input.tools or [])]
        report_selected = _report_skill_selected(filtered_input)
        report_active = False
        if not branch:
            report_active = await _has_active_report_workflow(
                context.report_agent,
                filtered_input.thread_id,
                user_id,
            )
        report_route = not branch and (report_selected or report_active)
        audit_values = {
            "route": "report_agent" if report_route else "assistant_team",
            "declared_odoo_commands": declared_odoo_commands,
            "report_route_selected": report_route,
        }
        _audit_tool_route(
            request,
            run_input,
            **audit_values,
        )

        if branch:
            if hasattr(branch, "source_thread_id") and hasattr(branch, "source_run_id"):
                branch_team = await _team_for_stored_run(
                    context,
                    branch.source_thread_id,
                    user_id,
                    branch.source_run_id,
                )
            else:
                branch_team = context.assistant_team
            if branch_team is None:
                source = _run_error(
                    "无法确认源运行所属团队，请刷新会话后重试。",
                    "run_team_not_found",
                )
            else:
                source = run_branch(
                    branch_team,
                    context.workspace_service,
                    _sanitize_run_input(filtered_input),
                    branch,
                    user_id,
                )
        elif report_route:
            try:
                report_identity = ReportServerIdentity(
                    database=claims.database,
                    user_id=str(claims.user),
                    company_id=str(claims.company),
                    session_id=claims.odoo_session,
                    thread_id=filtered_input.thread_id,
                )
                routed_input = filtered_input
                envelope = None
                if not report_active:
                    prepared_report = prepare_agui_envelope(filtered_input)
                    routed_input = prepared_report.run_input
                    envelope = prepared_report.envelope
                routed_input = routed_input.model_copy(update={"tools": []})
                prepared_input = await _prepare_run_input(
                    context.report_agent,
                    routed_input,
                    user_id,
                    context.settings,
                )
                source = _run_report_entity(
                    context.report_agent,
                    prepared_input,
                    envelope,
                    user_id,
                    report_identity,
                )
            except ReportingError as error:
                source = _run_error(error.message, error.code)
        else:
            prepared_input = await _prepare_run_input(
                context.assistant_team,
                filtered_input,
                user_id,
                context.settings,
            )
            source = run_entity(context.assistant_team, prepared_input, user_id=user_id)
        source = _hide_team_delegation_events(source)
        async for event in _with_sse_heartbeats(source):
            if event is None:
                yield ": heartbeat\n\n"
                continue
            if _is_raw_reasoning_event(event):
                continue
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
    application = FastAPI(title="HRP AG-UI 开发智能体")
    application.state.agentos_context = context
    application.middleware("http")(require_workspace_capability)
    application.include_router(router)
    application.include_router(
        create_workspace_report_download_router(
            report_downloads,
            scope_dependency=_report_download_scope,
        )
    )
    application.router.add_event_handler("startup", install_report_download_access_log_filter)
    application.router.add_event_handler("startup", report_download_repository.create_schema)
    return application


application_context = ApplicationContext(
    settings,
    workspace_service,
    agent_skills,
    assistant,
    report_agent,
    assistant_team,
    coding_agent=coding_agent,
    database=agent_database,
    coding_repository=coding_repository,
    coding_supervisor=coding_supervisor,
    report_workflow_controller=report_workflow_controller,
    report_worker=report_worker,
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
