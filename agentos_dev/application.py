from agno.agent import Agent
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from fastapi import FastAPI

from .settings import AgentSettings


def create_agentos_app(
    settings: AgentSettings,
    base_app: FastAPI,
    assistant: Agent,
) -> tuple[AgentOS, FastAPI]:
    agent_os = AgentOS(
        name="Odoo AG-UI 开发服务",
        agents=[assistant],
        interfaces=[AGUI(agent=assistant)],
        base_app=base_app,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(settings.cors_allowed_origins),
    )
    return agent_os, agent_os.get_app()
