import json
import logging
import unicodedata
from pathlib import PurePosixPath
from urllib.parse import quote

from ag_ui.core import Context, EventType, RunAgentInput, RunErrorEvent
from ag_ui.encoder import EventEncoder
from agno.agent import Agent
from agno.models.message import Message
from agno.os.interfaces.agui.input import extract_tool_messages, extract_user_input
from agno.os.interfaces.agui.router import run_entity
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.team import Team
from fastapi import APIRouter, Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, ValidationError
from starlette.concurrency import run_in_threadpool

from .agent_control import (
    AGENT_CONTEXT_STATUS_DEPENDENCY,
    AGENT_CONTINUATION_STATE_KEY,
    AGENT_LOADED_TOOLKITS_STATE_KEY,
    AGENT_PLAN_STATE_KEY,
)
from .agents import (
    LEGACY_ASSISTANT_IDS,
    LEGACY_ODOO_COMMAND_ASSISTANT_IDS,
    LEGACY_TEAM_IDS,
    ODOO_COMMAND_ASSISTANT_ID,
    TEAM_ROUTE_DEPENDENCY,
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
from .coding_tools import (
    CODEX_EXEC_NEXT_SESSION_STATE_KEY,
    CODEX_EXEC_SESSIONS_STATE_KEY,
)
from .context_management import (
    HISTORY_CONTEXT_DESCRIPTION,
    ProtectedCompressionManager,
    build_budgeted_history_context,
)
from .database import check_database
from .instructions import (
    build_agent_instructions,
    build_odoo_command_instructions,
    build_report_agent_instructions,
)
from .report_data_sources import (
    CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
    MAX_DATASET_FILE_BYTES,
    MAX_REPORT_INPUTS,
    REPORT_DATASET_HANDLES_STATE_KEY,
)
from .security import CapabilityError, verify_capability
from .settings import AgentSettings
from .skills import load_skills, public_skill_metadata
from .workspace import (
    REPORT_JOBS_STATE_KEY,
    WorkspaceError,
    WorkspacePathConflict,
    WorkspaceService,
)

PROTOCOL = "agui.odoo.v2"
BUNDLE_VERSION = "12.0.8.8.10"
COMMAND_CATALOG_HASH = "6529262bf0a1c05a61a1238c67415ed3734e0db58bc12dcd59cf6c534d2467f4"
MAX_RUN_REQUEST_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = 12 * 1024 * 1024
WORKSPACE_FILE_BYTES = 10 * 1024 * 1024
MAX_JSON_MUTATION_REQUEST_BYTES = 64 * 1024
SERVER_TOOL_SCHEMA_TOKEN_RESERVE = 16 * 1024
REPORT_TOOL_MIGRATION_ERROR = "report_tool_migration_required"
REMOVED_REPORT_TOOLS = frozenset(
    {
        "report_list_analysis_capabilities",
        "report_profile_dataset",
        "report_analyze_dataset",
    }
)
LEGACY_REPORT_BASE_TOOLS = frozenset(
    {
        "agent_update_plan",
        "agent_context_status",
        "agent_prepare_continuation",
        "agent_tool_search",
        "agent_load_toolkit",
        "sandbox_exec",
        "sandbox_process_poll",
        "sandbox_process_write",
        "sandbox_process_interrupt",
        "sandbox_process_stop",
        "workspace_list_files",
        "workspace_read_file",
        "workspace_read_lines",
        "workspace_stat",
        "workspace_tree",
        "workspace_search_files",
        "workspace_search_text",
        "workspace_hash_file",
        "workspace_git_status",
        "workspace_git_diff",
        "workspace_git_log",
        "workspace_git_show",
        "workspace_write_file",
        "workspace_replace_file",
        "workspace_move_file",
        "workspace_apply_patch",
        "workspace_apply_patch_set",
        "workspace_apply_hunks",
        "workspace_apply_changes",
        "workspace_create_directory",
        "workspace_copy_file",
        "workspace_delete_file",
        "workspace_view_image",
        "workspace_inspect_pdf",
        *REMOVED_REPORT_TOOLS,
    }
)
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
        REPORT_JOBS_STATE_KEY,
        CODEX_EXEC_SESSIONS_STATE_KEY,
        CODEX_EXEC_NEXT_SESSION_STATE_KEY,
    }
)
logger = logging.getLogger(__name__)


class WorkspaceDeleteFilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str = Field(alias="threadId", min_length=1, max_length=256)
    path: str
    recursive: StrictBool = False


class WorkspaceAttachmentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    workspace_path: str = Field(alias="workspacePath", min_length=1, max_length=1024)


settings = AgentSettings.from_environment()

workspace_secret = settings.workspace_hmac_secret
agent_skills = load_skills(settings.skills_dir)
workspace_service = WorkspaceService(secret=workspace_secret)
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
            CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
            TEAM_ROUTE_DEPENDENCY,
        }
    ]
    state = run_input.state
    if isinstance(state, dict):
        state = {key: value for key, value in state.items() if key not in SERVER_SESSION_STATE_KEYS}
    if len(context) == len(run_input.context or []) and state is run_input.state:
        return run_input
    return run_input.model_copy(update={"context": context, "state": state})


async def _current_attachment_context(
    run_input: RunAgentInput,
    workspace_service: WorkspaceService,
) -> Context | None:
    attachments = None
    for message in reversed(run_input.messages or []):
        if message.role == "user":
            attachments = getattr(message, "attachments", None)
            break
    if attachments is None:
        return None
    if not isinstance(attachments, list) or not 1 <= len(attachments) <= MAX_REPORT_INPUTS:
        raise ValueError("当前消息附件数量无效。")
    values = []
    seen = set()
    for raw in attachments:
        attachment = WorkspaceAttachmentPayload.model_validate(raw)
        relative = workspace_service.normalize_path(
            attachment.workspace_path,
            allow_root=False,
        )[0]
        if relative in seen:
            continue
        seen.add(relative)
        stat = await workspace_service.astat(run_input.thread_id, relative)
        if stat.get("type") != "file":
            raise ValueError("当前消息附件不是普通文件。")
        digest = await workspace_service.ahash_file(run_input.thread_id, relative)
        size = int(digest.get("size", -1))
        if size < 0 or size > MAX_DATASET_FILE_BYTES or size != int(stat.get("size", -2)):
            raise ValueError("当前消息附件大小无效或已变化。")
        sha256 = str(digest.get("sha256") or "")
        if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
            raise ValueError("当前消息附件哈希无效。")
        values.append(
            {
                "path": relative,
                "type": "file",
                "size": size,
                "sha256": sha256,
            }
        )
    return Context(
        description=CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY,
        value=json.dumps(values, ensure_ascii=False, separators=(",", ":")),
    )


async def _prepare_run_input(
    agent,
    run_input: RunAgentInput,
    user_id: str,
    settings,
    *,
    server_context: list[Context] | None = None,
    history_entity: Agent | Team | None = None,
):
    prepared = _sanitize_run_input(run_input)
    if server_context:
        prepared = prepared.model_copy(
            update={"context": [*(prepared.context or []), *server_context]}
        )
    if not _is_fresh_user_request(prepared):
        return prepared
    session_owner = history_entity or agent
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


def _redact_report_analysis_result(event):
    try:
        payload = json.loads(event.content)
    except (AttributeError, TypeError, json.JSONDecodeError):
        payload = {}
    allowed = {
        "exitCode",
        "jobId",
        "ok",
        "roundCount",
        "status",
        "successfulRoundCount",
        "truncated",
    }
    redacted = {key: payload[key] for key in allowed if key in payload}
    redacted["outputRedacted"] = True
    return event.model_copy(
        update={
            "content": json.dumps(redacted, ensure_ascii=False, separators=(",", ":")),
            "raw_event": None,
        }
    )


def _is_report_analysis_result(event) -> bool:
    try:
        payload = json.loads(event.content)
    except (AttributeError, TypeError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and {
        "exitCode",
        "jobId",
        "output",
        "roundCount",
        "status",
        "successfulRoundCount",
    }.issubset(payload)


def _selected_report_skill(run_input: RunAgentInput) -> bool:
    for item in run_input.context or []:
        if item.description != "已选智能体技能":
            continue
        try:
            value = json.loads(item.value)
        except (TypeError, ValueError):
            continue
        if isinstance(value, list) and any(
            isinstance(skill, dict)
            and (
                skill.get("id") in {"report", "workspace-smart-report"}
                or skill.get("name") in {"report", "workspace-smart-report"}
            )
            for skill in value
        ):
            return True
    return False


async def _entity_for_stored_run(
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
        team_session = None
    if isinstance(team_session, TeamSession) and team_session.team_id in {
        context.assistant_team.id,
        *LEGACY_TEAM_IDS,
    }:
        if not run_id or any(run.run_id == run_id for run in (team_session.runs or [])):
            return context.assistant_team
    try:
        session = await context.assistant.aget_session(session_id=thread_id, user_id=user_id)
    except Exception as error:
        logger.warning("agent_route_session_load_failed error_type=%s", type(error).__name__)
        return None
    if not isinstance(session, AgentSession):
        return None
    agent_id = session.agent_id
    if run_id:
        matching = next(
            (run for run in reversed(session.runs or []) if run.run_id == run_id),
            None,
        )
        if matching is None:
            return None
        matching_agent_id = getattr(matching, "agent_id", None)
        if isinstance(matching_agent_id, str) and matching_agent_id:
            agent_id = matching_agent_id
    if agent_id == context.report_agent.id:
        return context.report_agent
    if (
        agent_id == context.odoo_command_assistant.id
        or agent_id in LEGACY_ODOO_COMMAND_ASSISTANT_IDS
    ):
        return context.odoo_command_assistant
    if agent_id == context.assistant.id or agent_id in LEGACY_ASSISTANT_IDS:
        return context.assistant
    return None


def _pending_legacy_report_tool(session: AgentSession, run_id: str | None) -> str | None:
    runs = session.runs or []
    run = next(
        (item for item in reversed(runs) if run_id is None or item.run_id == run_id),
        None,
    )
    if run is None:
        return None
    for requirement in run.requirements or []:
        is_resolved = getattr(requirement, "is_resolved", None)
        if callable(is_resolved) and is_resolved():
            continue
        execution = getattr(requirement, "tool_execution", None)
        name = getattr(execution, "tool_name", None)
        if name in LEGACY_REPORT_BASE_TOOLS:
            return name
    for execution in run.tools or []:
        name = getattr(execution, "tool_name", None)
        pending_confirmation = bool(getattr(execution, "requires_confirmation", False)) and (
            getattr(execution, "confirmed", None) is None
        )
        pending_external = bool(getattr(execution, "external_execution_required", False)) and (
            getattr(execution, "result", None) is None
        )
        pending_removed = (
            name in REMOVED_REPORT_TOOLS and getattr(execution, "result", None) is None
        )
        if name in LEGACY_REPORT_BASE_TOOLS and (
            pending_confirmation or pending_external or pending_removed
        ):
            return name
        result = getattr(execution, "result", None)
        if name not in LEGACY_REPORT_BASE_TOOLS or result is None:
            continue
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, ValueError):
                continue
        if (
            isinstance(result, dict)
            and result.get("status") == "running"
            and isinstance(result.get("sessionId"), str)
            and isinstance(result.get("commandId"), str)
        ):
            return name
    return None


async def _pending_legacy_report_tool_for_run(
    agent: Agent,
    thread_id: str,
    user_id: str,
    run_id: str | None,
) -> str | None:
    try:
        session = await agent.aget_session(session_id=thread_id, user_id=user_id)
    except Exception as error:
        logger.warning(
            "report_tool_migration_session_load_failed error_type=%s", type(error).__name__
        )
        return None
    if not isinstance(session, AgentSession):
        return None
    return _pending_legacy_report_tool(session, run_id)


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


def _team_route_context(*member_ids: str | None) -> Context:
    normalized = [member_id for member_id in member_ids if member_id]
    if not normalized:
        raise RuntimeError("团队成员缺少稳定 ID。")
    route = {"memberId": normalized[0]} if len(normalized) == 1 else {"memberIds": normalized}
    return Context(
        description=TEAM_ROUTE_DEPENDENCY,
        value=json.dumps(route, ensure_ascii=True, separators=(",", ":")),
    )


def _filter_client_tools_for_agent(
    run_input: RunAgentInput,
    entity: Agent | Team,
) -> RunAgentInput:
    if isinstance(entity, Team):
        return run_input
    declared_tools = list(run_input.tools or [])
    if entity.id == ODOO_COMMAND_ASSISTANT_ID:
        tools = [
            tool for tool in declared_tools if is_odoo_command_name(getattr(tool, "name", None))
        ]
    elif entity.id == "report-agent":
        tools = [
            tool
            for tool in declared_tools
            if getattr(tool, "name", None) == "odoo.export_current_view"
        ]
    else:
        tools = []
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


def _request_thread(request: Request) -> str:
    return str(request.headers.get("X-AGUI-Thread", "")).strip()


def _request_limit(path: str, method: str) -> int | None:
    if path == "/agui":
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


assistant, odoo_command_assistant, report_agent = create_assistants(
    settings,
    agent_skills,
    workspace_service,
    build_agent_instructions,
    build_odoo_command_instructions,
    build_report_agent_instructions,
)
assistant_team = create_assistant_team(
    assistant,
    odoo_command_assistant,
    report_agent,
)


@router.post("/agui", include_in_schema=False)
async def run_agui(request: Request, run_input: RunAgentInput):
    context = _application_context(request)
    claims = request.state.capability
    user_id = capability_user_id(claims)
    branch = getattr(request.state, "branch", None)
    encoder = EventEncoder()

    async def events():
        tool_names_by_call_id: dict[str, str] = {}
        fresh_request = _is_fresh_user_request(run_input)
        existing_entity = None
        if fresh_request and not branch:
            existing_entity = await _entity_for_stored_run(
                context,
                run_input.thread_id,
                user_id,
            )
        legacy_agent_session = any(
            existing_entity is agent
            for agent in (
                context.assistant,
                context.odoo_command_assistant,
                context.report_agent,
            )
        )
        report_selected = _selected_report_skill(run_input)
        declared_odoo_commands = [
            tool.name for tool in (run_input.tools or []) if is_odoo_command_name(tool.name)
        ]
        route_name = "stored_run"
        if fresh_request:
            if report_selected:
                route_name = "report_agent"
            elif declared_odoo_commands:
                route_name = "assistant_or_odoo_command_assistant"
            else:
                route_name = "assistant"
        audit_values = {
            "route": route_name,
            "declared_odoo_commands": declared_odoo_commands,
            "report_route_selected": report_selected and fresh_request,
            "legacy_agent_session": legacy_agent_session,
        }
        _audit_tool_route(
            request,
            run_input,
            **audit_values,
        )

        if branch:
            if hasattr(branch, "source_thread_id") and hasattr(branch, "source_run_id"):
                branch_agent = await _entity_for_stored_run(
                    context,
                    branch.source_thread_id,
                    user_id,
                    branch.source_run_id,
                )
            else:
                branch_agent = context.assistant
            if branch_agent is None:
                source = _run_error(
                    "无法确认源运行所属智能体，请刷新会话后重试。",
                    "run_agent_not_found",
                )
            else:
                source = run_branch(
                    branch_agent,
                    context.workspace_service,
                    _filter_client_tools_for_agent(
                        _sanitize_run_input(run_input),
                        branch_agent,
                    ),
                    branch,
                    user_id,
                )
        else:
            run_agent: Agent | Team | None
            history_entity: Agent | Team | None = None
            if fresh_request:
                run_agent = context.assistant_team
                if legacy_agent_session:
                    history_entity = existing_entity
            else:
                run_agent = await _entity_for_stored_run(
                    context,
                    run_input.thread_id,
                    user_id,
                    run_input.run_id,
                )
            if run_agent is None:
                source = _run_error(
                    "无法确认原运行所属智能体，请刷新会话后重试。",
                    "run_agent_not_found",
                )
            else:
                server_context = None
                attachment_error = False
                legacy_report_tool = None
                if not fresh_request and run_agent is context.report_agent:
                    legacy_report_tool = await _pending_legacy_report_tool_for_run(
                        context.report_agent,
                        run_input.thread_id,
                        user_id,
                        run_input.run_id,
                    )
                if legacy_report_tool is not None:
                    attachment_error = True
                    source = _run_error(
                        f"旧版报表工具 {legacy_report_tool} 的待处理调用不能在新工具集下续跑；"
                        "请开始新的报表消息并重新执行该步骤。",
                        REPORT_TOOL_MIGRATION_ERROR,
                    )
                if fresh_request and report_selected:
                    try:
                        attachment_context = await _current_attachment_context(
                            run_input,
                            context.workspace_service,
                        )
                        server_context = (
                            [attachment_context] if attachment_context is not None else None
                        )
                    except (ValidationError, ValueError, WorkspaceError):
                        attachment_error = True
                        source = _run_error(
                            "当前消息附件未同步、已变化或不属于当前工作区，请重新选择附件。",
                            "report_attachment_invalid",
                        )
                if not attachment_error:
                    if fresh_request and run_agent is context.assistant_team:
                        member_ids = (
                            [context.report_agent.id]
                            if report_selected
                            else [
                                context.assistant.id,
                                *(
                                    [context.odoo_command_assistant.id]
                                    if declared_odoo_commands
                                    else []
                                ),
                                *(
                                    [context.report_agent.id]
                                    if existing_entity is context.report_agent
                                    else []
                                ),
                            ]
                        )
                        server_context = [
                            *(server_context or []),
                            _team_route_context(*member_ids),
                        ]
                    prepared_input = await _prepare_run_input(
                        run_agent,
                        _filter_client_tools_for_agent(run_input, run_agent),
                        user_id,
                        context.settings,
                        server_context=server_context,
                        history_entity=history_entity,
                    )
                    source = run_entity(run_agent, prepared_input, user_id=user_id)
        source = _hide_team_delegation_events(source)
        async for event in source:
            if _is_raw_reasoning_event(event):
                continue
            if event.type == EventType.TOOL_CALL_START:
                tool_call_id = str(getattr(event, "tool_call_id", "") or "")
                tool_call_name = str(getattr(event, "tool_call_name", "") or "")
                if tool_call_id and tool_call_name:
                    tool_names_by_call_id[tool_call_id] = tool_call_name
            elif event.type == EventType.TOOL_CALL_RESULT:
                tool_call_id = str(getattr(event, "tool_call_id", "") or "")
                if tool_names_by_call_id.get(
                    tool_call_id
                ) == "report_analyze_dataset" or _is_report_analysis_result(event):
                    event = _redact_report_analysis_result(event)
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
    return application


application_context = ApplicationContext(
    settings,
    workspace_service,
    agent_skills,
    assistant,
    odoo_command_assistant,
    report_agent,
    assistant_team,
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
