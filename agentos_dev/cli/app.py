from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutputEvent
from agno.tools import Function

from ..agents import OPENAI_COMPATIBLE_ROLE_MAP
from ..async_utils import complete_cleanup
from ..coding import (
    AgnoCodingExecutor,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
)
from ..coding.adapters import CliCodingAdapter
from ..coding.execution import CodingExecutionKernel, WorkspaceCodingToolkit
from ..context_management import (
    ContextBudgetController,
    clear_terminal_reasoning,
    projected_coding_model,
)
from ..database import create_agent_database
from ..observability import configure_tracing
from ..settings import AgentSettings
from ..skills import (
    SkillValidatorRegistry,
    load_builtin_coding_skills,
    skill_script_receipt_hook,
)
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
    configure_tracing(
        database.async_db,
        enabled=current_settings.tracing_enabled,
        phoenix_endpoint=current_settings.tracing_phoenix_endpoint,
        phoenix_api_key=current_settings.tracing_phoenix_api_key,
        phoenix_project_name=current_settings.tracing_phoenix_project_name,
    )
    workspace_service = WorkspaceService(
        secret=current_settings.workspace_hmac_secret,
        database=database,
        snapshot=current_settings.workspace_snapshot,
        network_allow_list=current_settings.daytona_network_allow_list,
    )
    repository = CodingTaskRepository(database.async_db)
    return CliContext(
        settings=current_settings,
        database=database.async_db,
        workspace_service=workspace_service,
        coding_repository=repository,
    )


def _create_cli_model(
    settings: AgentSettings, *, enable_thinking: bool | None = None
) -> OpenAIChat:
    return OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body=({"enable_thinking": enable_thinking} if enable_thinking is not None else None),
        retries=2,
        exponential_backoff=True,
    )


def create_cli_agent(context: CliContext) -> Agent:
    settings = context.settings
    model = projected_coding_model(_create_cli_model(settings))
    coding_skills = load_builtin_coding_skills(settings.skills_dir)
    validator_registry = SkillValidatorRegistry.from_skills(coding_skills)
    compression_manager = (
        ContextBudgetController(
            model=model,
            context_token_budget=settings.context_token_budget,
            output_token_reserve=settings.output_token_reserve,
        )
        if settings.enable_tool_result_compression
        else None
    )
    return Agent(
        id="coding-agent-cli",
        name="Coding Agent CLI",
        role="在当前 Daytona 工作区执行受控软件开发任务。",
        model=model,
        instructions=CLI_AGENT_INSTRUCTIONS,
        skills=coding_skills,
        tools=[
            WorkspaceCodingToolkit(
                context.workspace_service,
                context.coding_repository,
                validator_registry=validator_registry,
            )
        ],
        db=context.database,
        checkpoint="tool-batch",
        add_history_to_context=True,
        num_history_runs=5,
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=compression_manager,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        tool_hooks=[skill_script_receipt_hook],
        debug_mode=True,
        markdown=True,
        tool_choice="auto",
    )


def create_cli_app_agent(context: CliContext, coding_agent: Agent) -> Agent:
    validator_registry = SkillValidatorRegistry.from_skills(coding_agent.skills)
    supervisor = CodingTaskSupervisor(
        context.coding_repository,
        AgnoCodingExecutor(lambda _agent_id: coding_agent),
        execution_cleanup=CodingExecutionKernel(
            context.workspace_service, context.coding_repository
        ),
        validator_registry=validator_registry,
    )
    adapter = CliCodingAdapter(supervisor)
    facade_tool_hooks = [
        hook for hook in (coding_agent.tool_hooks or []) if hook is not skill_script_receipt_hook
    ]

    async def run_coding_task(
        instruction: str, run_context: RunContext
    ) -> AsyncIterator[RunOutputEvent]:
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
        async for event in adapter.start_events(scope, instruction):
            yield event

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
            "model": _create_cli_model(context.settings, enable_thinking=False),
            "instructions": [
                "必须把用户的完整编码目标原样传给 run_coding_task，并直接返回工具结果。"
            ],
            "tools": [function],
            "tool_choice": {
                "type": "function",
                "function": {"name": "run_coding_task"},
            },
            "skills": None,
            "tool_hooks": facade_tool_hooks,
        }
    )
    app_agent.tool_choice = {
        "type": "function",
        "function": {"name": "run_coding_task"},
    }
    return app_agent


async def run_cli_app(context: CliContext, coding_agent: Agent) -> None:
    app_agent = create_cli_app_agent(context, coding_agent)
    try:
        await app_agent.acli_app(
            session_id=f"cli-{uuid4().hex}",
            user_id="cli",
            stream=True,
            markdown=True,
        )
    finally:
        await complete_cleanup(_close_cli_resources(context, app_agent, coding_agent))


async def _close_cli_resources(context: CliContext, *agents: Agent) -> None:
    clients: list[Any] = []
    seen: set[int] = set()
    for agent in agents:
        models = [
            getattr(agent, "model", None),
            getattr(getattr(agent, "compression_manager", None), "model", None),
        ]
        for model in models:
            client = getattr(model, "async_client", None)
            if client is not None and id(client) not in seen:
                seen.add(id(client))
                clients.append(client)
    clients.append(context.database)
    first_error: BaseException | None = None
    for client in clients:
        close = getattr(client, "close", None)
        if not callable(close):
            continue
        try:
            result = close()
            if isawaitable(result):
                await result
        except BaseException as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def main() -> None:
    context = create_cli_context()
    agent = create_cli_agent(context)
    try:
        asyncio.run(run_cli_app(context, agent))
    except KeyboardInterrupt:
        pass
