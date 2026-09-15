from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.tools.code import CodeMode

from ..integrations.agno_function_arguments import install_agno_function_argument_decoder
from ..reporting.code_agent.lsp_process import ReportingLspProcessManager
from ..reporting.host_workspace import ReportingWorkspaceRegistry
from ..reporting.knowledge import ReportingKnowledgeIndex
from ..sandbox.factory import create_sandbox_provider
from ..task_execution import DEFAULT_TERMINAL_TIMEOUT
from ..workspace import AsyncSandboxRegistry, WorkspaceService
from .database import AgentDatabase, create_agent_database
from .observability import configure_tracing, flush_tracing
from .settings import AgentSettings


@dataclass(frozen=True)
class ExecutionContext:
    settings: AgentSettings
    database: AsyncBaseDb
    workspace_service: WorkspaceService
    trace_database: BaseDb | None = None
    reporting_workspace_registry: ReportingWorkspaceRegistry | None = None
    reporting_code_mode_runtime: Any | None = None
    reporting_knowledge_index: ReportingKnowledgeIndex | None = None
    reporting_lsp_process_manager: ReportingLspProcessManager | None = None


def configure_execution_tracing(
    database: AgentDatabase,
    settings: AgentSettings,
    *,
    tracing_configurer: Any = configure_tracing,
) -> None:
    tracing_configurer(
        database.sync_db,
        enabled=settings.tracing_enabled,
        batch_processing=True,
    )


def create_execution_context(
    settings: AgentSettings | None = None,
    *,
    database_factory: Any = create_agent_database,
    tracing_configurer: Any = configure_tracing,
    workspace_factory: Any = WorkspaceService,
) -> ExecutionContext:
    install_agno_function_argument_decoder()
    current_settings = settings or AgentSettings.from_environment()
    database = database_factory(current_settings.database_url)
    configure_execution_tracing(
        database,
        current_settings,
        tracing_configurer=tracing_configurer,
    )
    async_registry = AsyncSandboxRegistry(database.async_db)
    provider = create_sandbox_provider(current_settings, registry=async_registry)
    workspace_service = workspace_factory(
        secret=current_settings.workspace_hmac_secret,
        database=database,
        snapshot=current_settings.workspace_snapshot,
        network_allow_list=current_settings.daytona_network_allow_list,
        async_registry=async_registry,
        provider=provider,
    )
    reporting_workspace_registry = ReportingWorkspaceRegistry(
        current_settings.reporting_host_workspace_root,
        secret=current_settings.workspace_hmac_secret,
    )
    from ..reporting.code_mode import ReportingCodeModeRuntime

    reporting_code_mode_runtime = ReportingCodeModeRuntime(
        CodeMode(
            allow_shell=True,
            allow_restart=True,
            snapshot=False,
            cwd=str(reporting_workspace_registry.root),
            timeout=DEFAULT_TERMINAL_TIMEOUT,
            max_kernels=max(
                current_settings.report_analysis_concurrency,
                current_settings.report_section_concurrency,
            ),
        )
    )
    reporting_knowledge_index = ReportingKnowledgeIndex(reporting_workspace_registry.root)
    reporting_lsp_process_manager = ReportingLspProcessManager()
    return ExecutionContext(
        settings=current_settings,
        database=database.async_db,
        workspace_service=workspace_service,
        trace_database=database.sync_db,
        reporting_workspace_registry=reporting_workspace_registry,
        reporting_code_mode_runtime=reporting_code_mode_runtime,
        reporting_knowledge_index=reporting_knowledge_index,
        reporting_lsp_process_manager=reporting_lsp_process_manager,
    )


async def close_execution_resources(
    context: ExecutionContext,
    *agents: Agent,
    tracing_flusher: Any = flush_tracing,
) -> None:
    clients: list[Any] = []
    seen: set[int] = set()
    for agent in agents:
        for model in (
            getattr(agent, "model", None),
            getattr(getattr(agent, "compression_manager", None), "model", None),
            getattr(getattr(agent, "session_summary_manager", None), "model", None),
        ):
            client = getattr(model, "async_client", None)
            if client is not None and id(client) not in seen:
                seen.add(id(client))
                clients.append(client)
    clients.extend((context.workspace_service, context.database))
    reporting_registry = getattr(context, "reporting_workspace_registry", None)
    code_mode_runtime = getattr(context, "reporting_code_mode_runtime", None)
    knowledge_index = getattr(context, "reporting_knowledge_index", None)
    lsp_process_manager = getattr(context, "reporting_lsp_process_manager", None)
    trace_database = getattr(context, "trace_database", None)
    if trace_database is not None:
        clients.append(trace_database)
    if code_mode_runtime is not None:
        clients.append(code_mode_runtime)
    if reporting_registry is not None:
        clients.append(reporting_registry)
    if knowledge_index is not None:
        clients.append(knowledge_index)
    if lsp_process_manager is not None:
        clients.append(lsp_process_manager)

    first_error: BaseException | None = None
    try:
        if not tracing_flusher():
            first_error = RuntimeError("agent_tracing_flush_failed")
    except BaseException as error:
        first_error = error
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
