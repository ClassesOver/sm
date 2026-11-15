import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_acp_client import ReportAcpClient, ReportAcpError
from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
from smart_reporting.report_channel_host import mount_report_channel
from smart_reporting.report_channel_acp import (
    ReportChannelAcp,
    ReportChannelAcpConflict,
    ReportChannelAcpDenied,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_acp_conversation_keeps_session_and_collects_chunks(tmp_path):
    peer = """
import json, sys
turn = 0
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    params = request['params']
    if method == 'initialize':
        result = {'protocolVersion': 1}
    elif method == 'session/new':
        assert params['mcpServers'] == []
        result = {'sessionId': 'synthetic'}
    else:
        assert method == 'session/prompt' and params['sessionId'] == 'synthetic'
        turn += 1
        for text in ('reply ', str(turn)):
            print(json.dumps({'jsonrpc': '2.0', 'method': 'session/update', 'params': {
                'sessionId': 'synthetic', 'update': {'sessionUpdate': 'agent_message_chunk',
                'content': {'type': 'text', 'text': text}}}}), flush=True)
        result = {'stopReason': 'end_turn'}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""
    async with ReportAcpClient((sys.executable, "-u", "-c", peer), tmp_path) as client:
        await client.open_session()
        assert await client.prompt("Synthetic report") == "reply 1"
        assert await client.prompt("Follow up") == "reply 2"


@pytest.mark.anyio
@pytest.mark.parametrize("wire", ["not JSON", "[]", '{"id":1,"result":{"protocolVersion":1}}'])
async def test_invalid_acp_frames_fail_as_protocol_errors(tmp_path, wire):
    peer = f"import sys; sys.stdin.readline(); print({wire!r}, flush=True)"
    async with ReportAcpClient((sys.executable, "-u", "-c", peer), tmp_path) as client:
        with pytest.raises(ReportAcpError, match="Invalid ACP frame"):
            await client.open_session()
        with pytest.raises(ReportAcpError, match="process is closed"):
            await client.open_session()


@pytest.mark.anyio
async def test_timed_out_peer_is_closed(tmp_path):
    peer = "import sys; sys.stdin.read()"
    async with ReportAcpClient((sys.executable, "-u", "-c", peer), tmp_path, timeout=0.2) as client:
        with pytest.raises(TimeoutError):
            await client.open_session()
        with pytest.raises(ReportAcpError, match="process is closed"):
            await client.open_session()


@pytest.mark.anyio
async def test_uncertain_acp_delivery_is_not_resubmitted():
    identity = ConnectorIdentity("dsh", "synthetic", "session")
    submitted = []

    class Repository:
        async def member_grant(self, channel, member):
            return "grant" if channel == "report-a" and member == identity else None

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def open_session(self, resume=None):
            assert resume == ("private-session" if submitted else None)
            return "private-session"

        async def prompt(self, message):
            submitted.append(message)
            if message == "First edit":
                raise ReportAcpError("ACP peer disconnected")
            return "Received next edit"

    bridge = ReportChannelAcp(Repository(), Client)
    conversation = await bridge.bind("report-a", identity)
    with pytest.raises(ReportAcpError, match="peer disconnected"):
        await conversation.prompt(identity, "First edit", message_id="first")
    with pytest.raises(ReportChannelAcpConflict, match="report_channel_acp_outcome_unknown"):
        await conversation.prompt(identity, "First edit", message_id="first")
    assert await conversation.prompt(identity, "Next edit", message_id="second") == "Received next edit"
    assert submitted == ["First edit", "Next edit"]


@pytest.mark.anyio
async def test_binding_rechecks_grant_before_sending_and_releasing_reply():
    identity = object()
    calls = []

    class Repository:
        grant = "grant-1"

        async def member_grant(self, channel, member):
            return self.grant if channel == "report-a" and member is identity else None

    repository = Repository()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def open_session(self, resume=None):
            calls.append(resume)
            return "private-acp-session"

        async def prompt(self, message):
            calls.append(message)
            if message == "revoke while running":
                repository.grant = None
            return "synthetic reply"

    bridge = ReportChannelAcp(repository, Client)
    with pytest.raises(ReportChannelAcpDenied):
        await bridge.bind("report-b", identity)
    assert calls == []
    conversation = await bridge.bind("report-a", identity)
    with pytest.raises(ReportChannelAcpDenied):
        await conversation.prompt(object(), "wrong identity", message_id="wrong")
    assert await conversation.prompt(identity, "first turn", message_id="first") == "synthetic reply"
    with pytest.raises(ReportChannelAcpDenied):
        await conversation.prompt(identity, "revoke while running", message_id="revoked")
    assert calls == [None, "first turn", "private-acp-session", "revoke while running"]
    repository.grant = "replacement-grant"
    with pytest.raises(ReportChannelAcpDenied):
        await conversation.prompt(identity, "stale conversation", message_id="first")
    assert "stale conversation" not in calls


@pytest.mark.anyio
async def test_private_acp_endpoint_requires_exchange_and_reuses_bound_conversation():
    identity = ConnectorIdentity("dsh", "synthetic", "synthetic-session")

    class Repository:
        async def exchange(self, reference, *, validate_channel, **_):
            assert reference == "A" * 43
            validate_channel("report-a")
            return type("Member", (), {"channel": "report-a"})()

        async def has_member(self, channel, caller):
            return channel == "report-a" and caller == identity

        async def conversation(self, channel, **kwargs):
            assert channel == "report-a"

    class Conversation:
        async def prompt(self, caller, text, *, message_id):
            assert caller == identity
            if text.endswith("Clarify the conclusion"):
                return "Clarify the conclusion without changing the facts"
            assert message_id == "chat:" + text
            return text.upper()

    class Bridge:
        async def restore(self, channel, caller):
            return None

        async def bind(self, channel, caller):
            assert (channel, caller) == ("report-a", identity)
            return Conversation()

    async def authenticate(request):
        return identity if request.headers.get("authorization") == "Bearer synthetic" else None

    async def delegate(channel, caller, payload):
        assert (channel, caller) == ("report-a", identity)
        assert payload.instruction == "Clarify the conclusion without changing the facts"
        return {"taskId": "synthetic-task", "status": "running"}

    async def status(channel, caller, task_id):
        assert (channel, caller, task_id) == ("report-a", identity, "synthetic-task")
        return {"taskId": task_id, "status": "succeeded"}

    app = FastAPI()
    mount_report_channel(
        app, create_report_channel_router(
            Repository(), authenticate, acp=Bridge(), delegate_word=delegate,
            word_status=status, editor_path=lambda _: "/reports/v1/native/report-a/1",
        ),
        origin="https://reports.test",
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        headers = {"authorization": "Bearer synthetic"}
        path = "/reports/v1/channels/report-a/acp/messages"
        manifest = (await http.get("/reports/join")).raise_for_status()
        assert manifest.headers["cache-control"] == "no-store"
        assert manifest.json()["conversation"]["pathField"] == "acpMessagesPath"
        assert manifest.json()["wordCandidates"]["pathField"] == "wordTasksPath"
        assert "mcp" not in manifest.text.lower()
        assert (await http.get("/reports/channel-mcp")).status_code == 404
        first = {"text": "first", "message_id": "first"}
        assert (await http.post(path, headers=headers, json=first)).status_code == 403
        joined = await http.post("/reports/v1/channels/invitations/exchange",
                                 headers=headers, json={"reference": "A" * 43})
        assert joined.json()["acpMessagesPath"] == path
        assert (await http.post(path, json=first)).status_code == 401
        assert (await http.post(path.replace("report-a", "report-b"), headers=headers,
                                json=first)).status_code == 403
        for text in ("first", "second"):
            response = await http.post(path, headers=headers, json={"text": text, "message_id": text})
            assert response.json() == {"reply": text.upper()}
        word_path = joined.json()["wordTasksPath"]
        payload = {
            "request_id": "synthetic-request", "instruction": "Clarify the conclusion",
            "prepare_with_acp": True,
        }
        assert (await http.post(word_path.replace("report-a", "report-b"),
                                headers=headers, json=payload)).status_code == 403
        receipt = (await http.post(word_path, headers=headers, json=payload)).raise_for_status().json()
        response = await http.get(word_path + "/" + receipt["taskId"], headers=headers)
        assert response.raise_for_status().json()["status"] == "succeeded"
        assert receipt["reviewPath"] == "/reports/v1/native/report-a/1#word-task=synthetic-task"


@pytest.mark.anyio
async def test_restored_acp_conversation_is_cached_across_requests():
    identity = ConnectorIdentity("dsh", "synthetic", "session")
    restores = []

    class Conversation:
        async def prompt(self, caller, message, *, message_id):
            assert caller == identity
            return message.upper()

    conversation = Conversation()

    class Bridge:
        async def restore(self, channel, caller):
            restores.append((channel, caller))
            return conversation

    async def authenticate(request):
        return identity

    app = FastAPI()
    app.include_router(create_report_channel_router(
        object(), authenticate, acp=Bridge(),
    ))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        path = "/reports/v1/channels/report-a/acp/messages"
        for i in range(2):
            response = await http.post(path, json={"message_id": str(i), "text": "hello"})
            assert response.status_code == 200
            assert response.json() == {"reply": "HELLO"}
    assert restores == [("report-a", identity)]


@pytest.mark.anyio
async def test_concurrent_acp_requests_share_one_restored_conversation():
    import asyncio

    identity = ConnectorIdentity("dsh", "synthetic", "session")
    restores = 0

    class Conversation:
        async def prompt(self, caller, message, *, message_id):
            return message.upper()

    class Bridge:
        async def restore(self, channel, caller):
            nonlocal restores
            restores += 1
            await asyncio.sleep(0)
            return Conversation()

    async def authenticate(request):
        return identity

    app = FastAPI()
    app.include_router(create_report_channel_router(object(), authenticate, acp=Bridge()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        path = "/reports/v1/channels/report-a/acp/messages"
        responses = await asyncio.gather(*(
            http.post(path, json={"message_id": str(i), "text": "hello"})
            for i in range(8)
        ))
    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == {"reply": "HELLO"} for response in responses)
    assert restores == 1


@pytest.mark.anyio
async def test_acp_cleanup_preserves_error_after_peer_closes_pipe(tmp_path):
    # A peer can exit before the host finishes writing or cleaning up stdin.
    peer = "import sys; sys.exit(0)"
    async with ReportAcpClient((sys.executable, "-u", "-c", peer), tmp_path, timeout=1) as client:
        with pytest.raises((ReportAcpError, BrokenPipeError, ConnectionResetError)):
            await client.open_session()
        assert client._process is None
