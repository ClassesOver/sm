"""Explicit composition for a private report-channel host."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from starlette.routing import Route

from .report_channel_mcp import create_report_channel_mcp


def mount_report_channel(app: FastAPI, router: APIRouter, *, origin: str) -> None:
    """Install the supplied authorized channel routes and start their MCP lifespan."""
    channel_app = FastAPI()
    channel_app.include_router(router)
    mcp = create_report_channel_mcp(channel_app, origin=origin).http_app(
        transport="streamable-http", stateless_http=True, path="/reports/channel-mcp",
    )

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.router.lifespan_context(mcp):
            yield

    endpoints = APIRouter(lifespan=lifespan)
    endpoints.include_router(router)
    endpoints.routes.append(Route("/reports/channel-mcp", mcp, methods=["GET", "POST", "DELETE"]))
    app.include_router(endpoints)
