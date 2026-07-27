from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable
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
from rich.console import Console

from ..agents import OPENAI_COMPATIBLE_ROLE_MAP
from ..agents.report import create_report_worker
from ..async_utils import complete_cleanup
from ..coding import (
    AgnoCodingExecutor,
    CodingScope,
    CodingTaskRepository,
    CodingTaskSupervisor,
)
from ..coding.adapters import CliCodingAdapter
from ..coding.execution import (
    CodingExecutionKernel,
    WorkspaceCodingToolkit,
    create_coding_tool_scheduler_hook,
    is_coding_tool_scheduler_hook,
)
from ..context_management import (
    ContextBudgetController,
    clear_terminal_reasoning,
    projected_coding_model,
)
from ..database import create_agent_database
from ..instructions import build_report_agent_instructions
from ..observability import configure_tracing
from ..report_data_sources import ReportDataSourceToolkit
from ..reporting.adapters import CliReviewAdapter
from ..reporting.agui import REPORT_SOURCE_INTAKE_DEPENDENCY
from ..reporting.binding import TemporarySourceBindingService
from ..reporting.controller import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    ReportWorkflowController,
)
from ..reporting.credentials import TemporaryCredentialStore
from ..reporting.intake import ReportIntakeService
from ..reporting.models import ReportingError
from ..reporting.runtime import ReportWorkflowRuntime
from ..reporting.starrocks import create_starrocks_client
from ..settings import AgentSettings
from ..skills import (
    SkillValidatorRegistry,
    create_skill_script_hook,
    is_skill_script_hook,
    load_builtin_coding_skills,
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
    model.reasoning_effort = "medium"
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
        add_history_to_context=False,
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=compression_manager,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        tool_hooks=[
            create_coding_tool_scheduler_hook(context.coding_repository),
            create_skill_script_hook(context.workspace_service),
        ],
        debug_mode=settings.debug and not settings.enable_thinking,
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
    app_agent = coding_agent.deep_copy(
        update={
            "id": "coding-agent-cli-app",
            "name": "Coding Agent CLI App",
            "model": projected_coding_model(
                _create_cli_model(context.settings, enable_thinking=False)
            ),
            "instructions": [
                "必须把用户的完整编码目标原样传给 run_coding_task，并直接返回工具结果。"
            ],
            "add_history_to_context": True,
            "num_history_runs": 5,
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
            console=Console(force_interactive=bool(app_agent.debug_mode)),
        )
    finally:
        await complete_cleanup(_close_cli_resources(context, app_agent, coding_agent))


def read_report_request(*, read: Callable[[str], str] = input) -> str:
    lines: list[str] = []
    while True:
        line = read("" if lines else "报表目标、连接块和 DDL（单独输入 /run 提交）:\n")
        if line.strip() == "/run":
            break
        lines.append(line)
    value = "\n".join(lines).strip()
    if not value:
        raise ValueError("报表请求不能为空。")
    return value


async def run_cli_report(
    *,
    settings: AgentSettings | None = None,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
) -> None:
    raw = read_report_request(read=read)
    parsed = ReportIntakeService().parse(raw)
    if parsed.source_request is None or not parsed.ddl_tables:
        raise ReportingError(
            "source_connection_incomplete",
            "Report CLI 当前必须同时提供临时 StarRocks 连接块和目标表 DDL。",
        )

    context = create_cli_context(settings)
    credentials = TemporaryCredentialStore()
    bindings = TemporarySourceBindingService(
        credentials,
        create_starrocks_client,
        network_allowlist=context.settings.report_source_network_allow_list,
    )
    session_id = f"cli-report-{uuid4().hex}"
    confirmation = bindings.prepare(
        parsed,
        user_id="cli",
        thread_id=session_id,
        session_id=session_id,
    )
    coding_agent = create_cli_agent(context)
    report_worker = create_report_worker(
        coding_agent,
        context.workspace_service,
        context.coding_repository,
        instructions=build_report_agent_instructions,
        context_token_budget=context.settings.context_token_budget,
        output_token_reserve=context.settings.output_token_reserve,
    )
    supervisor = CodingTaskSupervisor(
        context.coding_repository,
        AgnoCodingExecutor(lambda _agent_id: report_worker),
        execution_cleanup=CodingExecutionKernel(
            context.workspace_service, context.coding_repository
        ),
        validator_registry=SkillValidatorRegistry.from_skills(report_worker.skills),
    )
    data_sources = ReportDataSourceToolkit(
        context.workspace_service,
        config_path=context.settings.report_data_sources_file,
        excluded_database_url=context.settings.database_url,
        temporary_source_bindings=bindings,
        temporary_report_credentials=credentials,
    )
    runtime = ReportWorkflowRuntime(
        db=context.database,
        planner=report_worker,
        report_worker=report_worker,
        supervisor=supervisor,
        workspace_service=context.workspace_service,
        binding_service=bindings,
        credentials=credentials,
        client_factory=create_starrocks_client,
        data_sources=data_sources,
    )
    controller = ReportWorkflowController(
        runtime.workflow,
        cancel_cleanup=runtime.cleanup_cancelled,
    )
    external_run_id = uuid4().hex
    run_context = RunContext(
        run_id=external_run_id,
        session_id=session_id,
        user_id="cli",
        session_state={},
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"externalRunId": external_run_id},
            REPORT_SOURCE_INTAKE_DEPENDENCY: {
                "confirmationId": confirmation.confirmation_id,
                "sourceMode": "temporary_database",
                "sourceType": "starrocks",
                "endpoint": confirmation.endpoint,
                "database": confirmation.database,
                "ddlTables": list(parsed.ddl_tables),
                "metadataFingerprint": parsed.metadata_fingerprint,
                "expiresAt": confirmation.expires_at.isoformat(),
                "requiresConfirmation": True,
            },
        },
    )
    adapter = CliReviewAdapter(read=read, write=write)
    try:
        result = await controller.start(parsed.sanitized_text, None, run_context)
        while result.get("status") == "paused":
            action, feedback = adapter.review_action(result.get("review") or {})
            if action == "approve":
                result = await controller.approve(run_context)
            elif action == "reject":
                assert feedback is not None
                result = await controller.reject(feedback, run_context)
            else:
                result = await controller.cancel(run_context)
        write(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    finally:
        credentials.close_session(user_id="cli", thread_id=session_id, session_id=session_id)
        await complete_cleanup(_close_cli_resources(context, report_worker, coding_agent))


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
    workspace_service = getattr(context, "workspace_service", None)
    if workspace_service is not None:
        clients.append(workspace_service)
    clients.append(context.database)
    first_error: BaseException | None = None
    for client in clients:
        close = getattr(client, "aclose", None) or getattr(client, "close", None)
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


def main(argv: list[str] | None = None) -> None:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments == ["report"]:
            asyncio.run(run_cli_report())
            return
        if arguments:
            raise SystemExit("用法: python -m agentos_dev.cli [report]")
        context = create_cli_context()
        agent = create_cli_agent(context)
        asyncio.run(run_cli_app(context, agent))
    except KeyboardInterrupt:
        pass
