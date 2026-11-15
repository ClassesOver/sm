import asyncio
import os
import secrets
import time
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.report_channel_acp import ReportChannelAcp
from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
from smart_reporting.report_channel_invitation import Invitation
from smart_reporting.report_channel_repository import ReportChannelRepository


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.integration
@pytest.mark.anyio
async def test_acp_binding_persists_and_is_deleted_on_revocation():
    url = os.getenv("REPORTING_TEST_DB_URL")
    if not url:
        pytest.skip("Requires the disposable PostgreSQL test database")
    engine = create_async_engine(url)
    repo = ReportChannelRepository(engine)
    channel = uuid4().hex
    reference = uuid4().hex
    try:
        await repo.create_schema()
        await repo.issue(reference, Invitation(channel, "dsh", "synthetic", time.time() + 60))
        member = await repo.exchange(reference, connector="dsh", subject="synthetic",
                                     session="synthetic-session", now=time.time())
        grant = await repo.member_grant(channel, member)
        assert grant
        assert await repo.acp_binding(grant) is None
        assert await repo.enable_acp_binding(grant)
        assert (await repo.acp_binding(grant)).session_id is None
        assert await repo.set_acp_session(grant, "original-dsh-session")
        restored = ReportChannelRepository(engine)
        assert await restored.enable_acp_binding(grant)
        assert (await restored.acp_binding(grant)).session_id == "original-dsh-session"
        assert not await restored.set_acp_session(grant, "different-session")
        request_hash = "a" * 64
        reservations = await asyncio.gather(
            repo.reserve_acp_turn(grant, "chat:message-1", request_hash, limit=1),
            restored.reserve_acp_turn(grant, "chat:message-1", request_hash, limit=1),
        )
        assert sorted(reservations) == ["created", "existing"]
        uncertain = await restored.acp_receipt(grant, "chat:message-1")
        assert uncertain is not None and uncertain.request_digest == request_hash
        assert uncertain.reply is None
        assert await restored.reserve_acp_turn(grant, "chat:message-2", request_hash, limit=1) == "full"
        assert not await repo.complete_acp_turn(grant, "chat:message-1", "b" * 64, "wrong")
        assert await repo.complete_acp_turn(grant, "chat:message-1", request_hash, "original reply")
        assert not await restored.complete_acp_turn(grant, "chat:message-1", request_hash, "overwrite")
        assert (await restored.acp_receipt(grant, "chat:message-1")).reply == "original reply"
        await restored.revoke(channel, connector="dsh", subject="synthetic")
        assert await repo.acp_binding(grant) is None
        assert await repo.acp_receipt(grant, "chat:message-1") is None
        assert not await repo.enable_acp_binding(grant)
    finally:
        await repo.revoke(channel, connector="dsh", subject="synthetic")
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.anyio
async def test_recreated_host_resumes_acp_and_returns_saved_receipt():
    url = os.getenv("REPORTING_TEST_DB_URL")
    if not url:
        pytest.skip("Requires the disposable PostgreSQL test database")
    engine = create_async_engine(url)
    repo = ReportChannelRepository(engine)
    channel = uuid4().hex
    reference = secrets.token_urlsafe(32)
    identity = ConnectorIdentity("dsh", "synthetic", "session")
    calls = []
    started = asyncio.Event()
    finish = asyncio.Event()

    async def authenticate(_request):
        return identity

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def open_session(self, resume=None):
            calls.append(resume)
            return "test-dsh-session"

        async def prompt(self, message):
            calls.append(message)
            if message == "Synthetic in flight":
                started.set()
                await asyncio.wait_for(finish.wait(), 5)
            return f"Reply: {message}"

    def host():
        repository = ReportChannelRepository(engine)
        app = FastAPI()
        app.include_router(create_report_channel_router(
            repository, authenticate, acp=ReportChannelAcp(repository, Client, durable=True),
        ))
        return AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test")

    try:
        await repo.create_schema()
        await repo.issue(reference, Invitation(channel, identity.connector, identity.subject, time.time() + 60))
        first = {"message_id": "first", "text": "Synthetic first"}
        async with host() as http:
            join = await http.post("/reports/v1/channels/invitations/exchange", json={"reference": reference})
            path = join.raise_for_status().json()["acpMessagesPath"]
            assert (await http.post(path, json=first)).raise_for_status().json() == {"reply": "Reply: Synthetic first"}
        async with host() as http:
            assert (await http.post(path, json=first)).raise_for_status().json() == {"reply": "Reply: Synthetic first"}
            second = {"message_id": "second", "text": "Synthetic follow up"}
            assert (await http.post(path, json=second)).raise_for_status().json() == {"reply": "Reply: Synthetic follow up"}
            pending = {"message_id": "pending", "text": "Synthetic in flight"}
            async with host() as other:
                first_host = asyncio.create_task(http.post(path, json=pending))
                try:
                    await asyncio.wait_for(started.wait(), 5)
                    competing = await other.post(path, json={"message_id": "competing", "text": "Do not run"})
                    assert competing.status_code == 409
                    assert competing.json()["detail"] == "report_channel_acp_turn_in_progress"
                    await repo.revoke(channel, connector=identity.connector, subject=identity.subject)
                finally:
                    finish.set()
                    revoked = await first_host
                assert revoked.status_code == 403
            assert (await http.post(path, json=first)).status_code == 403
        assert calls == [
            None, "Synthetic first", "test-dsh-session", "Synthetic follow up",
            "test-dsh-session", "Synthetic in flight",
        ]
    finally:
        await repo.revoke(channel, connector=identity.connector, subject=identity.subject)
        await engine.dispose()
