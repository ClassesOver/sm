from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.models.openai import OpenAIChat

from ..agents import OPENAI_COMPATIBLE_ROLE_MAP
from ..coding import (
    AgnoCodingExecutor,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
    TaskState,
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
    )
    repository = CodingTaskRepository(database.async_db)
    return CliContext(
        settings=current_settings,
        database=database.async_db,
        workspace_service=workspace_service,
        coding_repository=repository,
    )


def create_cli_agent(context: CliContext) -> Agent:
    settings = context.settings
    model = OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": settings.enable_thinking},
        retries=2,
        exponential_backoff=True,
    )
    return Agent(
        id="coding-agent-cli",
        name="Coding Agent CLI",
        role="在当前 Daytona 工作区执行受控软件开发任务。",
        model=model,
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


async def run_cli_supervisor(
    context: CliContext,
    agent: Agent,
    *,
    message: str,
    session_id: str,
    user_id: str,
) -> None:
    async with context.workspace_service._async_client() as client:
        sandbox = await context.workspace_service._asandbox_for(client, session_id)
        sandbox_id = str(getattr(sandbox, "id", "") or "")
    if not sandbox_id:
        raise RuntimeError("CLI Daytona 工作区不可用。")
    scope = CodingScope(session_id, user_id, session_id, sandbox_id, str(agent.id))
    supervisor = CodingTaskSupervisor(
        context.coding_repository,
        AgnoCodingExecutor(lambda _agent_id: agent),
        execution_cleanup=CodingExecutionKernel(
            context.workspace_service, context.coding_repository
        ),
    )
    adapter = CliCodingAdapter(supervisor)
    existing = await context.coding_repository.get_task_snapshot(session_id)
    if existing is None:
        events = await adapter.run(scope, message)
    elif existing.state in {TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED}:
        successor_scope = CodingScope(
            f"{session_id}:{uuid4().hex}",
            user_id,
            session_id,
            sandbox_id,
            str(agent.id),
        )
        events = [
            event
            async for event in adapter.start(
                successor_scope,
                message,
                predecessor_task_id=existing.scope.external_run_id,
            )
        ]
    else:
        await adapter.instruct(scope, uuid4().hex, message)
        events = [event async for event in adapter.resume(scope)]
    for event in events:
        if event.type == "final_message":
            print(str(event.data.get("content") or ""))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动独立 Coding Agent CLI。")
    parser.add_argument("message", nargs="?", help="进入交互模式前先执行的任务。")
    parser.add_argument("--session-id", default=None, help="复用指定 CLI 会话和工作区。")
    parser.add_argument("--user-id", default="app-cli", help="会话持久化使用的用户标识。")
    return parser


def main(argv: list[str] | None = None) -> None:
    arguments = _parser().parse_args(argv)
    context = create_cli_context()
    agent = create_cli_agent(context)
    session_id = arguments.session_id or f"app-cli-{uuid4().hex}"
    if arguments.message is None:
        raise SystemExit("Supervisor CLI 当前要求提供一条编码任务消息。")
    asyncio.run(
        run_cli_supervisor(
            context,
            agent,
            message=arguments.message,
            session_id=session_id,
            user_id=arguments.user_id,
        )
    )
