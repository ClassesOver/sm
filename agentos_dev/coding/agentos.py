"""独立 Coding AgentOS 装配。"""

from contextlib import asynccontextmanager

from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from fastapi import FastAPI

from ..agentos_auth import agentos_authorization_config
from ..settings import AgentSettings
from .cli import (
    _close_cli_resources,
    create_cli_agent,
    create_cli_app_agent,
    create_cli_context,
)


def create_agentos(settings: AgentSettings | None = None) -> AgentOS:
    current_settings = settings or AgentSettings.from_environment()
    authorization_config = agentos_authorization_config(current_settings)
    context = create_cli_context(current_settings)
    worker = create_cli_agent(context)
    facade = create_cli_app_agent(context, worker)

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        try:
            yield
        finally:
            await _close_cli_resources(context, facade, worker)

    return AgentOS(
        name="Coding AgentOS",
        agents=[facade],
        interfaces=[AGUI(agent=facade)],
        db=context.database,
        authorization=True,
        authorization_config=authorization_config,
        cors_allowed_origins=list(current_settings.cors_allowed_origins),
        lifespan=lifespan,
    )


def main() -> None:
    settings = AgentSettings.from_environment()
    agent_os = create_agentos(settings)
    agent_os.serve(
        app=agent_os.get_app(),
        host=settings.host,
        port=settings.port,
        workers=settings.workers,
        reload=settings.reload,
        access_log=settings.access_log,
    )
