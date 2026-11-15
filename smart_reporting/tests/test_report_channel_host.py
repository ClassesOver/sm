from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken


@pytest.mark.anyio
async def test_base_app_enables_channel_routes_only_when_supplied():
    from smart_reporting.app import application_context, create_base_app

    origin = "https://reports.test"
    context = replace(application_context,
                      settings=replace(application_context.settings, report_public_base_url=origin))
    router = APIRouter()

    @router.get("/reports/join")
    async def join():
        return {"action": "join-report-channel"}

    async with AsyncClient(transport=ASGITransport(create_base_app(context)), base_url=origin) as client:
        assert (await client.get("/reports/join")).status_code == 404
    app = create_base_app(context, report_channel_router=router)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url=origin) as client:
            assert (await client.get("/reports/join")).json() == {"action": "join-report-channel"}
            assert (await client.get("/reports/channel-mcp", headers={"Accept": "text/event-stream"})).status_code == 405


@pytest.mark.anyio
async def test_agentos_preserves_channel_mcp_handshake():
    from smart_reporting.app import application_context, create_base_app
    from smart_reporting.report_channel_api import create_report_channel_router
    from smart_reporting.report_channel_identity import REPORT_CHANNEL_SCOPE, channel_token_authenticator
    from smart_reporting.report_channel_invitation import ChannelMember
    from smart_reporting.runtime.application import create_agentos_app

    origin = "https://reports.test"
    context = replace(application_context, database=None, recalculation_editor=None,
                      reporting_code_mode_runtime=None, reporting_lsp_process_manager=None,
                      settings=replace(application_context.settings, report_public_base_url=origin))

    async def verify_token(bearer):
        if bearer not in {"synthetic-channel", "synthetic-workflow"}:
            return None
        scopes = [REPORT_CHANNEL_SCOPE] if bearer == "synthetic-channel" else [
            "workflows:enterprise-reporting-workflow-v1:run",
        ]
        return AccessToken(token=bearer, client_id="synthetic-client", subject="synthetic-subject",
                           scopes=scopes, claims={"session": "synthetic-session"})

    async def exchange(reference, *, connector, subject, session, now, validate_channel):
        assert reference == "A" * 43
        assert (connector, subject, session) == ("dsh", "synthetic-subject", "synthetic-session")
        validate_channel("synthetic")
        return ChannelMember("synthetic", connector, subject, session)

    authenticate = channel_token_authenticator(SimpleNamespace(verify_token=verify_token), connector="dsh")
    router = create_report_channel_router(SimpleNamespace(exchange=exchange), authenticate,
        editor_path=lambda _: "/reports/v1/native/synthetic/1")
    _, app = create_agentos_app(context, create_base_app(context, report_channel_router=router))

    def make_client(**kwargs):
        return AsyncClient(transport=ASGITransport(app), **kwargs)

    def connect(token):
        transport = StreamableHttpTransport(origin + "/reports/channel-mcp", httpx_client_factory=make_client,
                                            headers={"Authorization": f"Bearer {token}"})
        return Client(transport)

    payload = {"share_link": origin + "/reports/join#" + "A" * 43}
    async with app.router.lifespan_context(app):
        async with connect("synthetic-workflow") as client:
            with pytest.raises(ToolError, match="401"):
                await client.call_tool("join_report_channel", payload)
        async with connect("synthetic-channel") as client:
            assert "join_report_channel" in (client.instructions or "")
            result = await client.call_tool("join_report_channel", payload)
            assert result.data["editorUrl"] == origin + "/reports/v1/native/synthetic/1"
