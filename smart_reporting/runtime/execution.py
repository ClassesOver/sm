from __future__ import annotations

from typing import Any

from .database import AgentDatabase
from .observability import configure_tracing
from .settings import AgentSettings


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
