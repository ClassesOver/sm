from dataclasses import replace
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.auth import AccessToken


# 以下用例运行完整应用生命周期（启动时在 PostgreSQL 建表），属于集成用例。
@pytest.mark.integration
@pytest.mark.anyio
async def test_base_app_enables_channel_routes_only_when_supplied():
    from smart_reporting.app import application_context, create_base_app
    from smart_reporting.report_channel_api import create_report_channel_router

    origin = "https://reports.test"
    context = replace(application_context,
                      settings=replace(application_context.settings, report_public_base_url=origin))
    async def authenticate(request):
        return None

    router = create_report_channel_router(SimpleNamespace(), authenticate)

    async with AsyncClient(transport=ASGITransport(create_base_app(context)), base_url=origin) as client:
        assert (await client.get("/reports/join")).status_code == 404
    app = create_base_app(context, report_channel_router=router)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url=origin) as client:
            assert (await client.get("/reports/join")).json()["action"] == "join-report-channel"
            assert (await client.get("/reports/channel-mcp")).status_code == 401


@pytest.mark.integration
@pytest.mark.anyio
async def test_agentos_preserves_channel_mcp_handshake():
    from smart_reporting.app import application_context, create_base_app
    from smart_reporting.report_channel_api import create_report_channel_router
    from smart_reporting.report_channel_identity import REPORT_CHANNEL_SCOPE, channel_token_authenticator
    from smart_reporting.report_channel_invitation import ChannelMember
    from smart_reporting.runtime.application import create_agentos_app

    origin = "https://reports.test"
    context = replace(application_context,
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
        async with AsyncClient(transport=ASGITransport(app), base_url=origin) as http:
            rejected = await http.post("/reports/channel-mcp", headers={"Authorization": "Bearer synthetic-workflow"})
            assert rejected.status_code == 401
            assert rejected.headers["WWW-Authenticate"] == "Bearer"
        async with connect("synthetic-channel") as client:
            assert "join_report_channel" in (client.instructions or "")
            result = await client.call_tool("join_report_channel", payload)
            assert result.data["editorUrl"] == origin + "/reports/v1/native/synthetic/1"


@pytest.mark.integration
@pytest.mark.anyio
async def test_base_app_mounts_explicit_document_candidate_gateway():
    from unittest.mock import AsyncMock

    from smart_reporting.app import application_context, create_base_app
    from smart_reporting.document_candidate_contract import DocumentFormat, DocumentScope
    from smart_reporting.document_candidate_setup import build_document_gateway
    from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router

    identity = ConnectorIdentity("dsh", "member", "session")
    scope = DocumentScope(
        "channel-a", "grant-a", "document-a", "1", "a" * 64, DocumentFormat.PDF,
    )

    class PreviewAdapter:
        format = DocumentFormat.PDF

        async def prepare(self, request):
            assert request.scope == scope
            return "preview-task"

        async def status(self, authorized_scope, task_id):
            assert authorized_scope == scope
            return {"taskId": task_id, "status": "preview_ready", "accepted": False}

    async def resolve(channel, caller):
        return scope if channel == "channel-a" and caller == identity else None

    async def authenticate(request):
        return identity

    repository = SimpleNamespace(has_member=AsyncMock(return_value=True))
    gateway = build_document_gateway(resolve, pdf=PreviewAdapter())
    router = create_report_channel_router(repository, authenticate, document_gateway=gateway)
    origin = "https://reports.test"
    context = replace(
        application_context,
        settings=replace(application_context.settings, report_public_base_url=origin),
    )
    app = create_base_app(context, report_channel_router=router)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app), base_url=origin) as client:
            path = "/reports/v1/channels/channel-a/document-tasks"
            created = await client.post(path, json={
                "request_id": "request-one",
                "instruction": "Annotate selected region",
                "selection": [{"page": 0, "rect": [0.1, 0.1, 0.5, 0.5]}],
            })
            assert created.status_code == 202
            assert created.json() == {"taskId": "preview-task"}
            status = await client.get(path + "/preview-task")
            assert status.status_code == 200
            assert status.json()["accepted"] is False
            # A valid connector identity must still be bound to the requested channel.
            unrelated = await client.get(
                "/reports/v1/channels/channel-b/document-tasks/preview-task",
            )
            assert unrelated.status_code == 403
