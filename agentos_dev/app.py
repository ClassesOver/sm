import os
import json

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from dotenv import dotenv_values
from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .security import CapabilityError, verify_capability
from .database import SerializedPostgresDb, agent_db_url, check_database
from .skills import load_skills
from .workspace import WorkspaceError, WorkspaceService, workspace_tools
from .report import report_tools


PROTOCOL = "agui.odoo.v2"
BUNDLE_VERSION = "12.0.8.6.0"
COMMAND_CATALOG_HASH = "66999dc4e1f22d94cf04b9fda3463c99538f00f86150204d4d0dea5d73c8cb60"
MAX_RUN_REQUEST_BYTES = 2 * 1024 * 1024
MAX_WORKSPACE_UPLOAD_REQUEST_BYTES = 12 * 1024 * 1024
MAX_JSON_MUTATION_REQUEST_BYTES = 64 * 1024
DEFAULT_ENV_FILE = "/home/junge/pros/agents_app/.env"
DEFAULT_MODEL_ID = "qwen3.6-35b-a3b"
DEFAULT_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
OPENAI_COMPATIBLE_ROLE_MAP = {
    "system": "user",
    "user": "user",
    "assistant": "assistant",
    "tool": "tool",
    "model": "assistant",
}


def load_environment():
    env_file = os.getenv("AGENT_ENV_FILE", DEFAULT_ENV_FILE).strip() or DEFAULT_ENV_FILE
    for key, value in dotenv_values(env_file).items():
        if value is not None and key not in os.environ:
            os.environ[key] = value


def env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


load_environment()


def allowed_origins():
    value = os.getenv(
        "AGENTOS_CORS_ORIGINS",
        "http://127.0.0.1:18069,http://localhost:18069",
    )
    return [origin.strip() for origin in value.split(",") if origin.strip()]


base_app = FastAPI(title="Odoo AG-UI 开发智能体")
workspace_secret = os.getenv("AGUI_WORKSPACE_HMAC_SECRET", "")
agent_skills = load_skills()
workspace_service = WorkspaceService(secret=workspace_secret)


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


@base_app.middleware("http")
async def require_workspace_capability(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    protected = path == "/agui" or path.startswith("/workspace")
    if not protected:
        return await call_next(request)
    thread = _request_thread(request)
    if not thread:
        return JSONResponse({"error": "thread_header_required"}, status_code=400)
    try:
        request.state.capability = verify_capability(
            request.headers.get("X-AGUI-Capability", ""), workspace_secret, thread,
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
    return await call_next(request)


@base_app.get("/config", include_in_schema=False)
async def integration_config():
    return {
        "protocol": PROTOCOL,
        "bundle_version": BUNDLE_VERSION,
        "command_catalog_hash": COMMAND_CATALOG_HASH,
        "skills": agent_skills.public_metadata(),
        "limits": {
            "run_request_bytes": MAX_RUN_REQUEST_BYTES,
            "workspace_upload_request_bytes": MAX_WORKSPACE_UPLOAD_REQUEST_BYTES,
            "json_mutation_request_bytes": MAX_JSON_MUTATION_REQUEST_BYTES,
        },
    }


def _readiness_checks():
    checks = {
        "postgresql": False,
        "sandbox_registry": False,
        "hmac": len(workspace_secret.encode("utf-8")) >= 32,
    }
    try:
        check_database()
        checks["postgresql"] = True
    except Exception:
        return checks
    try:
        workspace_service.registry.ensure_initialized()
        checks["sandbox_registry"] = True
    except Exception:
        pass
    return checks


@base_app.get("/ready", include_in_schema=False)
async def readiness():
    checks = await run_in_threadpool(_readiness_checks)
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


@base_app.get("/workspace/files", include_in_schema=False)
async def workspace_files(request: Request, threadId: str, path: str = ""):
    _check_thread(request, threadId)
    try:
        entries = await run_in_threadpool(workspace_service.list_files, threadId, path)
        return {"ok": True, "path": path, "entries": entries}
    except Exception as error:
        _workspace_error(error)


@base_app.post("/workspace/upload", include_in_schema=False)
async def workspace_upload(
    request: Request,
    threadId: str = Form(...),
    path: str = Form(...),
    file: UploadFile = File(...),
):
    _check_thread(request, threadId)
    content = await file.read(10 * 1024 * 1024 + 1)
    try:
        entry = await run_in_threadpool(workspace_service.upload, threadId, path, content)
        return {"ok": True, "entry": entry}
    except Exception as error:
        _workspace_error(error)


@base_app.get("/workspace/file", include_in_schema=False)
async def workspace_file(
    request: Request,
    threadId: str,
    path: str,
    download: bool = False,
):
    _check_thread(request, threadId)
    try:
        content, mime_type = await run_in_threadpool(
            workspace_service.file_bytes, threadId, path,
        )
    except Exception as error:
        _workspace_error(error)
    safe_name = "".join(
        char for char in path.rsplit("/", 1)[-1]
        if ord(char) >= 32 and ord(char) != 127 and char not in {'"', "\\"}
    ) or "download"
    disposition = "attachment" if download else "inline"
    if not download and mime_type not in {
        "application/json", "application/pdf", "image/jpeg", "image/png", "image/webp",
        "text/csv", "text/markdown", "text/plain",
    }:
        mime_type = "application/octet-stream"
        disposition = "attachment"
    return Response(content, media_type=mime_type, headers={
        "Content-Disposition": f'{disposition}; filename="{safe_name}"',
        "X-Content-Type-Options": "nosniff",
    })


@base_app.delete("/workspace/file", include_in_schema=False)
async def workspace_delete_file(request: Request, payload: dict = Body(...)):
    thread_id = str(payload.get("threadId") or "")
    _check_thread(request, thread_id)
    try:
        await run_in_threadpool(
            workspace_service.delete_file,
            thread_id,
            str(payload.get("path") or ""),
            bool(payload.get("recursive")),
        )
        return {"ok": True}
    except Exception as error:
        _workspace_error(error)


@base_app.delete("/workspace/sandbox", include_in_schema=False)
async def workspace_destroy(request: Request, payload: dict = Body(...)):
    thread_id = str(payload.get("threadId") or "")
    _check_thread(request, thread_id)
    try:
        deleted = await run_in_threadpool(workspace_service.destroy, thread_id)
    except Exception as error:
        _workspace_error(error)
    if not deleted:
        return JSONResponse({"ok": True, "deleted": False}, status_code=404)
    return {"ok": True, "deleted": True}


assistant = Agent(
    id="odoo-assistant",
    name="Odoo 助手",
    model=OpenAIChat(
        id=os.getenv("MODEL", DEFAULT_MODEL_ID),
        base_url=os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        api_key=os.getenv("OPENAI_API_KEY"),
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": False},
        temperature=0.0,
    ),
    instructions=[
        "使用中文简洁回答。",
        "可以使用本次请求携带的完整对话历史。",
        "涉及 Odoo 业务数据时仅使用请求中的 Odoo 页面状态和本次请求明确选择的菜单或记录候选；页面状态无法确认的数据不要猜测。",
        "每次页面工具返回新快照后，必须重新发现当前 viewType、可见字段、动态 modifiers、capabilities 和本次 Run 声明的工具；旧快照字段、记录、候选和控件 token 一律不得复用。",
        "调用 odoo.open_menu 时，target 必须原样复制“Odoo 宿主快照”中的 pageTarget；调用其他 Odoo 页面工具时，target 必须原样复制其中的 viewTarget。不得从 action.resId 推导当前表单记录。",
        "上下文存在“已选 Odoo 菜单”时，先用其中的 menuId 和当前 PageTarget 调用 odoo.open_menu；只能使用该菜单，不能改选或猜测其他菜单。导航后必须等待客户端返回新快照再决定下一步。",
        "上下文存在“已选 Odoo 引用”时，只能使用其中原样提供的 token 和绑定动作，不得改选对象、猜测对象或把 read/view 动作升级为 edit。多个 read 记录必须先用当前 PageTarget 一次调用 odoo.read_mentioned_records 批量读取；唯一的页面动作随后执行，并使用当前 PageTarget。菜单 open/create 分别调用 odoo.open_mentioned_menu，记录 view/edit 调用 odoo.open_mentioned_record，收藏或临时筛选 apply 调用 odoo.apply_mentioned_filter。",
        "收藏筛选和当前筛选绑定为 read 时必须调用 odoo.business.report.filters，绑定为 apply 时仍调用 odoo.apply_mentioned_filter；两者不得互相降级。菜单、记录和当前页面记录候选不能作为 Pandas 报表数据源。",
        "筛选报表必须先调用 describe。总行数不超过 5000 时才可调用 detail；超过后必须明确调用 aggregate。优先采用 describe 返回的原有 groupBy，调整维度或指标时只能选择返回的字段和聚合白名单。",
        "多个筛选默认分别分析。只有用户明确要求且字段结构兼容时才调用 pandas_concat_datasets 纵向合并；禁止自动 join。报表工具只接受 Odoo 报表命令生成的数据路径或用户明确加入当前 thread 工作区的 CSV、XLSX、JSON、JSONL 文件。",
        "报表回答必须注明筛选标签、行数、明细或聚合口径、用户时区、币种规则和生成时间。",
        "对象引用工具返回 mention_token_expired、mention_permission_revoked、mention_resource_unavailable 或 policy_denied 时，必须准确报告令牌过期、权限撤销、资源不可用或策略拒绝，不得改用其他对象或旧页面工具绕过。",
        "上下文不存在“已选 Odoo 菜单”时，只能操作当前 action；当前 action 无法满足意图时，请用户用 @ 选择菜单，不要从其他菜单中猜目标。",
        "筛选只能使用当前快照 capabilities.filterFields 中的字段和运算符，提交 JSON domain 与简短可见标签；即使只有一个条件也必须使用条件列表，例如 [[\"id\", \"=\", 1]]；禁止字符串 domain、点号字段和表达式。",
        "严格区分搜索、查看和编辑记录。用户仅要求搜索、筛选或查找记录时，只调用 odoo.apply_filter；无论命中数量多少都必须停止，不得调用 odoo.open_record。只有用户明确要求打开、查看或编辑记录时，才先按名称调用 odoo.apply_filter：唯一命中后立即使用返回的记录 token 调用 odoo.open_record，多条命中时停止并等待用户选择。打开或查看必须使用 readonly 模式；只有用户明确要求编辑或修改时才使用 edit 模式，不得因唯一命中自行升级用户意图。“已选 Odoo 记录候选项”只能在其 snapshotId 和 hostRevision 仍匹配时使用。若工具返回 policy_denied，应准确说明服务器策略拒绝了操作，不得归因于视图或 token。",
        "创建先调用 odoo.open_create 进入空白原生新建表单并等待新快照；随后只能按新快照真实可见可写字段和控件继续暂存、校验与保存，不得假设固定 action、view、模型或字段。",
        "跨模型操作只能使用新快照中真实可见的 Kanban 控件 token 逐步导航；控件语义不明确或存在多个合理路径时请用户选择，不能猜测。",
        "每轮最多跟进四次客户端页面工具；达到上限后明确停止，并请用户继续发送消息完成剩余操作。",
        "页面操作必须通过对应工具调用实现，不能用文字代替执行；收到工具成功结果前，严禁声称已打开、已进入、已修改、已保存或已完成。",
        "One2many 明细必须使用 capabilities.x2many 中的 fieldToken、行 token、schemaSource、schemaHash、childFieldCount、operations 和 unsupportedReason；父表单快照不提供完整 childFields 或明细 values，新增、查看和编辑必须调用 odoo.open_x2many_record 或 odoo.open_x2many_create 进入真实明细表单，禁止猜测未加载字段、行 ID、嵌套 One2many 或临时行别名。",
        "数百行 One2many 导入只允许对已保存且无脏数据的父表单使用已注册 profile：先以字段 token 和聊天附件 ID 调用 odoo.prepare_x2many_import，再轮询 odoo.get_x2many_import_status；仅在 ready 后用原样 jobToken 调用动态声明的 odoo.business.x2many_import.execute，完成后调用 odoo.reload_current_form。不得构造行数据、schema 摘要或绕过确认链。",
        "新建单据、存在 onchange/domain 依赖或需要分步填写的表单，必须按“能力发现 → odoo.stage_current_form 暂存依赖标量 → 等待 onchange 新快照 → odoo.search_relation 选择候选并继续暂存 → odoo.validate_current_form → 经独立确认后 odoo.save_current_form”执行；任何一步失败都停止，不能绕过原生校验或直接猜关系 ID。",
        "用户只要求进入编辑模式且未提供字段修改内容时，第一个响应只调用 odoo.enter_edit_mode。odoo.patch_current_form 保留“修改并立即保存”语义，只用于用户明确要求立即保存且不存在待 onchange/domain 依赖的独立修改；复杂或已暂存表单不得改用 patch_current_form。",
        "odoo.business.* 只有在本次 Run 动态声明且用户意图匹配其精确 schema 时才能调用；不得构造未声明业务命令，不得把业务命令降级为通用 RPC、CRUD 或任意模型方法，提交和审批类命令必须等待独立确认结果。",
        "上下文存在“已选智能体技能”时，必须先对每个手动选择的技能按原样调用 get_skill_instructions；手动选择不代表禁止自动使用其他可用技能。",
        "工作区只属于当前 thread。读取目录和文本使用 workspace_list_files、workspace_read_file；新建文件使用 workspace_write_file，移动或重命名使用 workspace_move_file，这些操作不需要确认，但都不能覆盖已有目标。覆盖文件使用 workspace_replace_file，删除文件或目录使用 workspace_delete_file，执行可信技能脚本使用 run_skill_script；这三类操作需要确认。不存在任意 Shell 或 Python 执行工具。报表工具可自动在当前 thread 的 reports/ UUID 路径生成数据集和图表。",
    ],
    skills=agent_skills,
    tools=workspace_tools(workspace_service, agent_skills) + report_tools(workspace_service),
    db=SerializedPostgresDb(db_url=agent_db_url()),
    add_history_to_context=True,
    num_history_runs=10,
    debug_mode=env_flag("AGENT_DEBUG"),
    markdown=True,
)

agent_os = AgentOS(
    name="Odoo AG-UI 开发服务",
    agents=[assistant],
    interfaces=[AGUI(agent=assistant)],
    base_app=base_app,
    on_route_conflict="preserve_base_app",
    cors_allowed_origins=allowed_origins(),
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(
        app="agentos_dev.app:app",
        host=os.getenv("AGENT_OS_HOST", "127.0.0.1"),
        port=int(os.getenv("AGENT_OS_PORT", "7777")),
        workers=int(os.getenv("AGENT_OS_WORKERS", "4")),
        reload=env_flag("AGENT_OS_RELOAD"),
        access_log=env_flag("AGENT_OS_ACCESS_LOG"),
    )
