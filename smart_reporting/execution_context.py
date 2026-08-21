from __future__ import annotations

from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from agno.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb

from .agno_function_arguments import install_agno_function_argument_decoder
from .database import AgentDatabase, create_agent_database
from .observability import configure_tracing, flush_tracing
from .settings import AgentSettings
from .workspace import WorkspaceService


@dataclass(frozen=True)
class ExecutionContext:
    settings: AgentSettings
    database: AsyncBaseDb
    workspace_service: WorkspaceService
    trace_database: BaseDb | None = None


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
    workspace_service = workspace_factory(
        secret=current_settings.workspace_hmac_secret,
        database=database,
        snapshot=current_settings.workspace_snapshot,
        network_allow_list=current_settings.daytona_network_allow_list,
    )
    return ExecutionContext(
        settings=current_settings,
        database=database.async_db,
        workspace_service=workspace_service,
        trace_database=database.sync_db,
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
    trace_database = getattr(context, "trace_database", None)
    if trace_database is not None:
        clients.append(trace_database)

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
