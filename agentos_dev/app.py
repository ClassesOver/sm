import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from dotenv import dotenv_values
from fastapi import FastAPI


PROTOCOL = "agui.odoo.v2"
BUNDLE_VERSION = "12.0.7.0.0"
COMMAND_CATALOG_HASH = "53d746a41bb0bbfcb97ba179c1f4f8f1e4d5e4f274cb8358e3562368c99ccdf6"
DEFAULT_ENV_FILE = "/home/junge/pros/agents_app/.env"
DEFAULT_MODEL_ID = "qwen3.6-35b-a3b"
DEFAULT_OPENAI_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DB_FILE = "/tmp/agui_agentos_dev.db"
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


@base_app.get("/config", include_in_schema=False)
async def integration_config():
    return {
        "protocol": PROTOCOL,
        "bundle_version": BUNDLE_VERSION,
        "command_catalog_hash": COMMAND_CATALOG_HASH,
    }


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
        "上下文存在 Selected Odoo menu 时，先用其中的 menuId 和当前 PageTarget 调用 odoo.open_menu；只能使用该菜单，不能改选或猜测其他菜单。导航后必须等待客户端返回新快照再决定下一步。",
        "上下文不存在 Selected Odoo menu 时，只能操作当前 action；当前 action 无法满足意图时，请用户用 @ 选择菜单，不要从其他菜单中猜目标。",
        "筛选只能使用当前快照 capabilities.filterFields 中的字段和运算符，提交 JSON domain 与简短可见标签；即使只有一个条件也必须使用条件列表，例如 [[\"id\", \"=\", 1]]；禁止字符串 domain、点号字段和表达式。",
        "用户要求按名称查看或编辑记录时，必须先调用 odoo.apply_filter 在当前 SearchView 按名称筛选，不得仅回复无法通过 token 打开。唯一命中后立即使用返回的记录 token 调用 odoo.open_record：查看使用 readonly 模式，编辑使用 edit 模式；多条命中时停止并等待用户选择。Selected Odoo record candidate 只能在其 snapshotId 和 hostRevision 仍匹配时使用。若工具返回 policy_denied，应准确说明服务器策略拒绝了操作，不得归因于视图或 token。",
        "创建只调用 odoo.open_create 进入空白原生新建表单，不填写、不保存。打开编辑态后不修改字段、不保存。",
        "跨模型操作只能使用新快照中真实可见的 Kanban 控件 token 逐步导航；控件语义不明确或存在多个合理路径时请用户选择，不能猜测。",
        "每轮最多跟进四次客户端页面工具；达到上限后明确停止，并请用户继续发送消息完成剩余操作。",
        "用户只要求编辑当前表单、进入编辑模式，且未提供任何字段修改内容时，调用 odoo.enter_edit_mode；该操作不修改字段也不保存。用户明确提供字段和值时才调用 odoo.patch_current_form；只读模式会自动进入编辑模式、同步状态并保存。",
    ],
    db=SqliteDb(db_file=os.getenv("AGENT_DB_FILE", DEFAULT_DB_FILE)),
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
