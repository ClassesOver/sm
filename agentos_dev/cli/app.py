from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.tools import Function

from ..agents import OPENAI_COMPATIBLE_ROLE_MAP
from ..coding import (
    AgnoCodingExecutor,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
)
from ..coding.adapters import CliCodingAdapter
from ..coding.execution import CodingExecutionKernel, WorkspaceCodingToolkit
from ..context_management import clear_terminal_reasoning
from ..database import create_agent_database
from ..settings import AgentSettings
from ..skills import load_builtin_coding_skills
from ..workspace import WorkspaceService

CLI_AGENT_INSTRUCTIONS = [
    "你是独立运行的 Coding Agent。使用中文简洁交付，只操作当前会话隔离的 Daytona 工作区。",
    "修改前检查相关实现、测试和文档，只做完成任务所需的最小改动，不覆盖用户已有的无关改动。",
    "所有文件、命令和图片操作必须使用当前声明的工具，并以真实工具结果为准。",
    "修改后复查差异并运行与范围匹配的验证；最终准确说明改动、检查结果和未验证风险。",
]
CLI_ROUTER_MODEL_ID = "qwen-plus"


@dataclass(frozen=True)
class CliContext:
    settings: AgentSettings
    database: AsyncBaseDb
    workspace_service: WorkspaceService
    coding_repository: CodingTaskRepository


def create_cli_context(settings: AgentSettings | None = None) -> CliContext:
    current_settings = settings or AgentSettings.from_environment()
    database = create_agent_database(current_settings.database_url)
    workspace_service = WorkspaceService(
        secret=current_settings.workspace_hmac_secret,
        database=database,
        snapshot=current_settings.workspace_snapshot,
    )
    repository = CodingTaskRepository(database.async_db)
    return CliContext(
        settings=current_settings,
        database=database.async_db,
        workspace_service=workspace_service,
        coding_repository=repository,
    )


def _create_cli_model(settings: AgentSettings, *, model_id: str | None = None) -> OpenAIChat:
    return OpenAIChat(
        id=model_id or settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        retries=2,
        exponential_backoff=True,
    )


def create_cli_agent(context: CliContext) -> Agent:
    settings = context.settings
    return Agent(
        id="coding-agent-cli",
        name="Coding Agent CLI",
        role="在当前 Daytona 工作区执行受控软件开发任务。",
        model=_create_cli_model(settings),
        instructions=CLI_AGENT_INSTRUCTIONS,
        skills=load_builtin_coding_skills(),
        tools=[WorkspaceCodingToolkit(context.workspace_service, context.coding_repository)],
        db=context.database,
        checkpoint="tool-batch",
        add_history_to_context=True,
        num_history_runs=5,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        debug_mode=settings.debug and not settings.enable_thinking,
        markdown=True,
        tool_choice="auto",
    )


def create_cli_app_agent(context: CliContext, coding_agent: Agent) -> Agent:
    supervisor = CodingTaskSupervisor(
        context.coding_repository,
        AgnoCodingExecutor(lambda _agent_id: coding_agent),
        execution_cleanup=CodingExecutionKernel(
            context.workspace_service, context.coding_repository
        ),
    )
    adapter = CliCodingAdapter(supervisor)

    async def run_coding_task(instruction: str, run_context: RunContext) -> str:
        external_run_id = str(run_context.run_id or "")
        session_id = str(run_context.session_id or "")
        user_id = str(run_context.user_id or "")
        if not external_run_id or not session_id or not user_id:
            raise ValueError("task_context_missing")
        async with context.workspace_service._async_client() as client:
            sandbox = await context.workspace_service._asandbox_for(client, session_id)
            sandbox_id = str(getattr(sandbox, "id", "") or "")
        if not sandbox_id:
            raise RuntimeError("CLI Daytona 工作区不可用。")
        scope = CodingScope(
            external_run_id,
            user_id,
            session_id,
            sandbox_id,
            str(coding_agent.id),
        )
        final = ""
        for event in await adapter.run(scope, instruction):
            if event.type == "final_message":
                final = str(event.data.get("content") or "")
            elif event.type == "terminal" and event.data.get("state") != "completed":
                raise RuntimeError(str(event.data.get("code") or "coding_task_failed"))
        return final

    function = Function(
        name="run_coding_task",
        description="把完整编码目标交给 CodingTaskSupervisor 执行并返回验收结果。",
        parameters={
            "type": "object",
            "properties": {"instruction": {"type": "string", "minLength": 1}},
            "required": ["instruction"],
            "additionalProperties": False,
        },
        entrypoint=run_coding_task,
        stop_after_tool_call=True,
    )
    app_agent = coding_agent.deep_copy(
        update={
            "id": "coding-agent-cli-app",
            "name": "Coding Agent CLI App",
            "model": _create_cli_model(context.settings, model_id=CLI_ROUTER_MODEL_ID),
            "instructions": [
                "必须把用户的完整编码目标原样传给 run_coding_task，并直接返回工具结果。"
            ],
            "tools": [function],
            "tool_choice": {
                "type": "function",
                "function": {"name": "run_coding_task"},
            },
            "skills": None,
        }
    )
    return app_agent


async def run_cli_app(context: CliContext, coding_agent: Agent) -> None:
    app_agent = create_cli_app_agent(context, coding_agent)
    await app_agent.acli_app(
        session_id=f"cli-{uuid4().hex}",
        user_id="cli",
        stream=True,
        markdown=True,
    )


def main() -> None:
    context = create_cli_context()
    agent = create_cli_agent(context)
    try:
        asyncio.run(run_cli_app(context, agent))
    except KeyboardInterrupt:
        pass
