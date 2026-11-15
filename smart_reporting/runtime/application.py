from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass

from agno.os import AgentOS
from fastapi import FastAPI
from loguru import logger

from ..quality_warnings.service import QualityWarningService
from .database import AgentDatabase
from .settings import AgentSettings


@dataclass(frozen=True)
class ApplicationContext:
    settings: AgentSettings
    database: AgentDatabase | None = None
    quality_warning_service: QualityWarningService | None = None


def create_agentos_app(
    context: ApplicationContext,
    base_app: FastAPI,
) -> tuple[AgentOS, FastAPI]:
    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        if context.database is not None:
            # 在接收请求前完成 Agno 原生建表；结构不兼容或建表失败时直接终止启动。
            await context.database.async_db._create_all_tables()
            logger.info("agent_database_initialized")
        yield

    agent_os = AgentOS(
        name="开发智能体服务",
        agents=[],
        teams=[],
        workflows=[],
        interfaces=[],
        base_app=base_app,
        db=context.database.async_db if context.database is not None else None,
        on_route_conflict="preserve_base_app",
        cors_allowed_origins=list(context.settings.cors_allowed_origins),
        lifespan=lifespan,
        telemetry=False,
    )
    return agent_os, agent_os.get_app()
