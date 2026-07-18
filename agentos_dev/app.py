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
from .database import SerializedPostgresDb, agent_db_url
from .skills import load_skills
from .workspace import WorkspaceError, WorkspaceService, workspace_tools


PROTOCOL = "agui.odoo.v2"
BUNDLE_VERSION = "12.0.8.3.0"
COMMAND_CATALOG_HASH = "b198faa202457040a5d1549837c2f9128cc3cbaea8788d4bc6b04046faf22245"
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


@base_app.middleware("http")
async def require_workspace_capability(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    protected = path == "/agui" or path.startswith("/workspace")
    if not protected:
        return await call_next(request)
    thread = _request_thread(request)
    if path == "/agui":
        try:
            payload = json.loads((await request.body()).decode("utf-8") or "{}")
            body_thread = str(payload.get("threadId") or "")
        except (UnicodeDecodeError, ValueError):
            return JSONResponse({"error": "invalid_run_payload"}, status_code=400)
        if not thread:
            thread = body_thread
        if body_thread != thread:
            return JSONResponse({"error": "capability_thread_mismatch"}, status_code=403)
    try:
        request.state.capability = verify_capability(
            request.headers.get("X-AGUI-Capability", ""), workspace_secret, thread,
        )
    except CapabilityError as error:
        return JSONResponse({"error": str(error)}, status_code=401)
    return await call_next(request)


@base_app.get("/config", include_in_schema=False)
async def integration_config():
    return {
        "protocol": PROTOCOL,
        "bundle_version": BUNDLE_VERSION,
        "command_catalog_hash": COMMAND_CATALOG_HASH,
        "skills": agent_skills.public_metadata(),
    }


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
        "对象引用工具返回 mention_token_expired、mention_permission_revoked、mention_resource_unavailable 或 policy_denied 时，必须准确报告令牌过期、权限撤销、资源不可用或策略拒绝，不得改用其他对象或旧页面工具绕过。",
        "上下文不存在“已选 Odoo 菜单”时，只能操作当前 action；当前 action 无法满足意图时，请用户用 @ 选择菜单，不要从其他菜单中猜目标。",
        "筛选只能使用当前快照 capabilities.filterFields 中的字段和运算符，提交 JSON domain 与简短可见标签；即使只有一个条件也必须使用条件列表，例如 [[\"id\", \"=\", 1]]；禁止字符串 domain、点号字段和表达式。",
        "严格区分搜索、查看和编辑记录。用户仅要求搜索、筛选或查找记录时，只调用 odoo.apply_filter；无论命中数量多少都必须停止，不得调用 odoo.open_record。只有用户明确要求打开、查看或编辑记录时，才先按名称调用 odoo.apply_filter：唯一命中后立即使用返回的记录 token 调用 odoo.open_record，多条命中时停止并等待用户选择。打开或查看必须使用 readonly 模式；只有用户明确要求编辑或修改时才使用 edit 模式，不得因唯一命中自行升级用户意图。“已选 Odoo 记录候选项”只能在其 snapshotId 和 hostRevision 仍匹配时使用。若工具返回 policy_denied，应准确说明服务器策略拒绝了操作，不得归因于视图或 token。",
        "创建先调用 odoo.open_create 进入空白原生新建表单并等待新快照；随后只能按新快照真实可见可写字段和控件继续暂存、校验与保存，不得假设固定 action、view、模型或字段。",
        "跨模型操作只能使用新快照中真实可见的 Kanban 控件 token 逐步导航；控件语义不明确或存在多个合理路径时请用户选择，不能猜测。",
        "每轮最多跟进四次客户端页面工具；达到上限后明确停止，并请用户继续发送消息完成剩余操作。",
        "页面操作必须通过对应工具调用实现，不能用文字代替执行；收到工具成功结果前，严禁声称已打开、已进入、已修改、已保存或已完成。",
        "One2many 明细必须使用快照 fields 中的 childFields、operations 和 capabilities.x2many 中当前可见的控件、行 token；新增关系字段时先激活可见创建控件，再用新行 token 暂存标量依赖、执行关系搜索并暂存候选；批量 create 只填写可见标量，update/delete 只使用 record.values 中已加载的持久行 ID；禁止猜测未加载行 ID、嵌套 One2many 或临时行别名。",
        "新建单据、存在 onchange/domain 依赖或需要分步填写的表单，必须按“能力发现 → odoo.stage_current_form 暂存依赖标量 → 等待 onchange 新快照 → odoo.search_relation 选择候选并继续暂存 → odoo.validate_current_form → 经独立确认后 odoo.save_current_form”执行；任何一步失败都停止，不能绕过原生校验或直接猜关系 ID。",
        "用户只要求进入编辑模式且未提供字段修改内容时，第一个响应只调用 odoo.enter_edit_mode。odoo.patch_current_form 保留“修改并立即保存”语义，只用于用户明确要求立即保存且不存在待 onchange/domain 依赖的独立修改；复杂或已暂存表单不得改用 patch_current_form。",
        "odoo.business.* 只有在本次 Run 动态声明且用户意图匹配其精确 schema 时才能调用；不得构造未声明业务命令，不得把业务命令降级为通用 RPC、CRUD 或任意模型方法，提交和审批类命令必须等待独立确认结果。",
        "上下文存在“已选智能体技能”时，必须先对每个手动选择的技能按原样调用 get_skill_instructions；手动选择不代表禁止自动使用其他可用技能。",
        "工作区只属于当前 thread。读取目录和文本使用 workspace_list_files、workspace_read_file；写入、移动、删除、Shell、代码和技能脚本执行必须使用对应的需确认工具。",
    ],
    skills=agent_skills,
    tools=workspace_tools(workspace_service, agent_skills),
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
