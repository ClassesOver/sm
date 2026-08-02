from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.agent import RunOutput, RunOutputEvent
from agno.tools import Function
from rich.console import Console

from ..agents import OPENAI_COMPATIBLE_ROLE_MAP
from ..async_utils import complete_cleanup
from ..context_management import (
    ContextBudgetController,
    clear_terminal_reasoning,
    projected_coding_model,
)
from ..database import create_agent_database
from ..execution_context import (
    ExecutionContext,
    close_execution_resources,
    create_execution_context,
)
from ..instructions import (
    CODING_DELIVERABLE_VERIFICATION_INSTRUCTION,
    CODING_VALIDATOR_FEEDBACK_INSTRUCTION,
    PURE_CODING_PARALLEL_READ_INSTRUCTIONS,
)
from ..observability import configure_tracing, flush_tracing
from ..settings import AgentSettings
from ..skills import (
    SkillValidatorRegistry,
    create_skill_script_hook,
    is_skill_script_hook,
    load_builtin_coding_skills,
)
from ..task_execution.execution import (
    CodingExecutionKernel,
    WorkspaceCodingToolkit,
    create_coding_tool_scheduler_hook,
    is_coding_tool_scheduler_hook,
)
from ..workspace import WorkspaceService
from . import (
    AgnoCodingExecutor,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
)
from .adapters import CliCodingAdapter

CLI_AGENT_INSTRUCTIONS = [
    "你是独立运行的 Coding Agent。使用中文简洁交付，只操作当前会话隔离的 Daytona 工作区。",
    "修改前检查相关实现、测试和文档，只做完成任务所需的最小改动，不覆盖用户已有的无关改动。",
    "所有文件、命令和图片操作必须使用当前声明的工具，并以真实工具结果为准。",
    "计划最多更新两次：开始执行时一次、完成全部验证后一次；禁止按文件逐项更新计划。",
    "首次运行与任务范围匹配的测试时直接使用 verify；仅在验证失败并修改后再次验证，避免先用 terminal 重复执行同一命令。",
    "verify 始终在工作区根目录执行，命令中禁止添加 cd /workspace。",
    '探测工作区根目录时调用 list_files(path="")，禁止把 /workspace 或 /home/daytona/workspace 作为工具路径。',
    "明确需要创建多个文件时，必须一次调用 create_files 并传入所有文件；混合创建和修改时使用一次 apply_patch，新文件格式为 *** Add File: path 且正文每行以 + 开头，禁止使用 ---/+++ 或 /dev/null。",
    CODING_VALIDATOR_FEEDBACK_INSTRUCTION,
    CODING_DELIVERABLE_VERIFICATION_INSTRUCTION,
    "修改后复查差异并运行与范围匹配的验证；最终准确说明改动、检查结果和未验证风险。",
    *PURE_CODING_PARALLEL_READ_INSTRUCTIONS,
]


@dataclass(frozen=True)
class CliContext(ExecutionContext):
    coding_repository: CodingTaskRepository | Any = None


def create_cli_context(settings: AgentSettings | None = None) -> CliContext:
    context = create_execution_context(
        settings,
        database_factory=create_agent_database,
        tracing_configurer=configure_tracing,
        workspace_factory=WorkspaceService,
    )
    return CliContext(
        settings=context.settings,
        database=context.database,
        workspace_service=context.workspace_service,
        trace_database=context.trace_database,
        coding_repository=CodingTaskRepository(context.database),
    )


def _create_cli_model(
    settings: AgentSettings, *, enable_thinking: bool | None = None
) -> OpenAIChat:
    return OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body=({"enable_thinking": enable_thinking} if enable_thinking is not None else None),
        retries=2,
        exponential_backoff=True,
    )


def create_cli_agent(context: CliContext) -> Agent:
    settings = context.settings
    model = projected_coding_model(
        _create_cli_model(settings, enable_thinking=settings.coding_enable_thinking)
    )
    model.temperature = 0
    model.reasoning_effort = settings.coding_reasoning_effort
    extra_body = dict(model.extra_body or {})
    if settings.coding_enable_thinking:
        extra_body["thinking_budget"] = settings.coding_thinking_budget
    else:
        extra_body.pop("thinking_budget", None)
    model.extra_body = extra_body
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
    workspace_toolkit = WorkspaceCodingToolkit(
        context.workspace_service,
        context.coding_repository,
        validator_registry=validator_registry,
    )

    return Agent(
        id="coding-agent-cli",
        name="Coding Agent CLI",
        role="在当前 Daytona 工作区执行受控软件开发任务。",
        model=model,
        instructions=CLI_AGENT_INSTRUCTIONS,
        skills=coding_skills,
        tools=[workspace_toolkit],
        db=context.database,
        checkpoint="tool-batch",
        add_history_to_context=False,
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=compression_manager,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        tool_hooks=[
            create_coding_tool_scheduler_hook(context.coding_repository),
            create_skill_script_hook(context.workspace_service),
        ],
        debug_mode=settings.debug,
        markdown=True,
        tool_choice="auto",
    )


class DirectCodingAgent(Agent):
    """保持 Agno Agent 接口，确定性地把输入交给 CodingTaskSupervisor。"""

    _run_coding_task: Callable[[str, RunContext], AsyncIterator[RunOutputEvent]]

    def arun(
        self,
        input: Any,
        *,
        stream: bool | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        run_id: str | None = None,
        run_context: RunContext | None = None,
        **_kwargs: Any,
    ):
        context = run_context or RunContext(
            run_id=run_id or uuid4().hex,
            session_id=session_id or self.session_id or f"cli-{uuid4().hex}",
            user_id=user_id,
        )
        instruction = input if isinstance(input, str) else str(input)
        events = self._run_coding_task(instruction, context)
        if stream is not False:
            return events

        async def complete() -> RunOutput:
            content = ""
            async for event in events:
                event_content = getattr(event, "content", None)
                if isinstance(event_content, str):
                    content += event_content
            return RunOutput(
                run_id=str(context.run_id or ""),
                session_id=str(context.session_id or ""),
                content=content,
            )

        return complete()


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
        hook
        for hook in (coding_agent.tool_hooks or [])
        if not is_skill_script_hook(hook) and not is_coding_tool_scheduler_hook(hook)
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
    app_agent = DirectCodingAgent(
        db=coding_agent.db,
        checkpoint=coding_agent.checkpoint,
        add_history_to_context=False,
        num_history_runs=None,
        compression_manager=coding_agent.compression_manager,
        compress_tool_results=coding_agent.compress_tool_results,
        debug_mode=coding_agent.debug_mode,
        markdown=True,
        model=coding_agent.model,
        role=coding_agent.role,
        telemetry=coding_agent.telemetry,
        tool_hooks=facade_tool_hooks,
        tools=[function],
        tool_choice={
            "type": "function",
            "function": {"name": "run_coding_task"},
        },
        id="coding-agent-cli-app",
        name="Coding Agent CLI App",
        instructions=["把收到的完整编码目标原样交给 CodingTaskSupervisor，并直接返回执行结果。"],
    )
    app_agent.num_history_runs = None
    app_agent._run_coding_task = run_coding_task
    return app_agent


async def run_cli(
    context: CliContext | None = None,
    coding_agent: Agent | None = None,
    *,
    initial_input: str | None = None,
) -> None:
    if context is None:
        settings = replace(
            AgentSettings.from_environment(),
            debug=True,
            tracing_enabled=True,
        )
        context = create_cli_context(settings)
    coding_agent = coding_agent or create_cli_agent(context)
    app_agent = create_cli_app_agent(context, coding_agent)
    session_id = f"cli-{uuid4().hex}"
    console = Console(force_interactive=bool(app_agent.debug_mode))
    try:
        try:
            if initial_input is not None:
                await app_agent.aprint_response(
                    initial_input,
                    session_id=session_id,
                    user_id="cli",
                    stream=True,
                    markdown=True,
                    console=console,
                )
            else:
                await app_agent.acli_app(
                    input=None,
                    session_id=session_id,
                    user_id="cli",
                    stream=True,
                    markdown=True,
                    exit_on=["exit", "quit", "bye", "/exit", "/quit"],
                    console=console,
                )
        except EOFError:
            pass
    finally:
        await complete_cleanup(_close_cli_resources(context, app_agent, coding_agent))


async def _close_cli_resources(context: CliContext, *agents: Agent) -> None:
    await close_execution_resources(context, *agents, tracing_flusher=flush_tracing)


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments not in ([], ["--stdin"]):
            raise SystemExit("用法: python -m agentos_dev.coding.cli [--stdin]")
        initial_input = sys.stdin.read() if arguments else None
        if initial_input is not None and not initial_input.strip():
            raise SystemExit("coding_cli_input_empty")
        asyncio.run(run_cli(initial_input=initial_input))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
