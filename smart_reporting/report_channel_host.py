"""Explicit composition for a private report-channel host."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.routing import Route

from .report_channel_api import ReportChannelRouter


def mount_report_channel(
    app: FastAPI, router: ReportChannelRouter, *, origin: str,
) -> None:
    """Install the explicitly selected private report-channel transport."""
    if router.acp_enabled:
        app.include_router(router)
        return

    from .report_channel_mcp import create_report_channel_mcp

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

    class ChannelMcp:
        async def __call__(self, scope, receive, send):
            if await router.authenticate(Request(scope)) is None:
                response = JSONResponse({"detail": "connector_authentication_required"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                await response(scope, receive, send)
                return
            await mcp(scope, receive, send)

    endpoints.routes.append(Route("/reports/channel-mcp", ChannelMcp(), methods=["GET", "POST", "DELETE"]))
    app.include_router(endpoints)
