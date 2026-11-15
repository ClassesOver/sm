import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_acp_client import ReportAcpClient, ReportAcpError
from smart_reporting.report_channel_acp import (
    ReportChannelAcp,
    ReportChannelAcpConflict,
    ReportChannelAcpDenied,
)
from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
from smart_reporting.report_channel_host import mount_report_channel


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


@pytest.mark.anyio
async def test_blank_acp_message_returns_422_not_500():
    identity = ConnectorIdentity("dsh", "synthetic", "session")

    class Conversation:
        async def prompt(self, caller, text, *, message_id):
            raise ValueError("Report message must contain between 1 and 8000 characters")

    class Bridge:
        async def restore(self, channel, caller):
            return Conversation()

    async def authenticate(request):
        return identity

    app = FastAPI()
    app.include_router(create_report_channel_router(object(), authenticate, acp=Bridge()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        response = await http.post("/reports/v1/channels/report-a/acp/messages",
                                   json={"message_id": "blank", "text": "   "})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "text"]


@pytest.mark.anyio
async def test_revocation_cancels_inflight_acp_prompt():
    import asyncio

    identity = ConnectorIdentity("dsh", "synthetic", "session")
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class Repository:
        active = True

        async def member_grant(self, channel, caller):
            return "grant" if self.active and caller == identity else None

    repository = Repository()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def open_session(self, resume=None):
            return "session-id"

        async def prompt(self, message):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    conversation = await ReportChannelAcp(repository, Client).bind("report-a", identity)
    turn = asyncio.create_task(conversation.prompt(identity, "hello", message_id="first"))
    await asyncio.wait_for(started.wait(), 2)
    repository.active = False
    with pytest.raises(ReportChannelAcpDenied):
        await asyncio.wait_for(turn, 3)
    assert cancelled.is_set()


@pytest.mark.anyio
async def test_cancelled_acp_turn_keeps_unknown_receipt_after_reauthorization():
    import asyncio

    identity = ConnectorIdentity("dsh", "synthetic", "session")
    started = asyncio.Event()
    cancelled = asyncio.Event()
    calls = []

    class Repository:
        grant = "grant-a"

        async def member_grant(self, channel, caller):
            return self.grant if caller == identity else None

    repository = Repository()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def open_session(self, resume=None):
            return "session-id"

        async def prompt(self, message):
            calls.append(message)
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    conversation = await ReportChannelAcp(repository, Client).bind("report-a", identity)
    pending = asyncio.create_task(conversation.prompt(identity, "hello", message_id="first"))
    await asyncio.wait_for(started.wait(), 2)
    repository.grant = None
    with pytest.raises(ReportChannelAcpDenied):
        await asyncio.wait_for(pending, 3)
    assert cancelled.is_set()
    repository.grant = "grant-a"
    with pytest.raises(ReportChannelAcpConflict, match="outcome_unknown"):
        await conversation.prompt(identity, "hello", message_id="first")
    assert calls == ["hello"]


@pytest.mark.anyio
@pytest.mark.parametrize("failure,status", [("denied", 403), ("unavailable", 502)])
async def test_acp_restore_failure_uses_safe_http_status(failure, status):
    identity = ConnectorIdentity("dsh", "synthetic", "session")

    class Bridge:
        async def restore(self, channel, caller):
            if failure == "denied":
                raise ReportChannelAcpDenied("private membership detail")
            raise ReportAcpError("private subprocess detail")

    async def authenticate(request):
        return identity

    app = FastAPI()
    app.include_router(create_report_channel_router(object(), authenticate, acp=Bridge()))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as http:
        response = await http.post("/reports/v1/channels/report-a/acp/messages",
                                   json={"message_id": "one", "text": "hello"})
    assert response.status_code == status
    assert "private" not in response.text


@pytest.mark.anyio
@pytest.mark.parametrize("shutdown_failure", [False, True])
async def test_durable_revocation_cancels_turn_and_preserves_unknown_receipt(shutdown_failure):
    import asyncio
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    identity = ConnectorIdentity("dsh", "synthetic", "session")
    started, cancelled = asyncio.Event(), asyncio.Event()

    class Repository:
        active = True
        receipt = None

        async def member_grant(self, channel, caller):
            return "grant" if self.active and caller == identity else None

        async def enable_acp_binding(self, grant):
            return True

        @asynccontextmanager
        async def acp_turn_lock(self, grant):
            yield True

        async def acp_binding(self, grant):
            return SimpleNamespace(session_id=None)

        async def acp_receipt(self, grant, message_id):
            return self.receipt

        async def set_acp_session(self, *args):
            return True

        async def reserve_acp_turn(self, grant, message_id, digest, **kwargs):
            self.receipt = SimpleNamespace(request_digest=digest, reply=None)
            return "created"

    repository = Repository()

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def open_session(self, resume=None):
            return "session-id"

        async def prompt(self, message):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                if shutdown_failure:
                    raise ReportAcpError("synthetic shutdown failure") from None
                raise

    conversation = await ReportChannelAcp(repository, Client, durable=True).bind("report-a", identity)
    pending = asyncio.create_task(conversation.prompt(identity, "hello", message_id="first"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        repository.active = False
        done, _ = await asyncio.wait({pending}, timeout=2)
        assert done, "revocation must stop a durable in-flight turn"
        with pytest.raises(ReportChannelAcpDenied):
            await pending
        assert cancelled.is_set()
        repository.active = True
        with pytest.raises(ReportChannelAcpConflict, match="outcome_unknown"):
            await conversation.prompt(identity, "hello", message_id="first")
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.anyio
async def test_revoked_turn_closes_actual_acp_subprocess(tmp_path):
    import asyncio

    identity = ConnectorIdentity("dsh", "synthetic", "session")
    started = asyncio.Event()
    processes = []

    class Repository:
        active = True

        async def member_grant(self, *args):
            return "grant" if self.active else None

    repository = Repository()
    peer = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request['method'] == 'initialize':
        result = {'protocolVersion': 1}
    elif request['method'] == 'session/new':
        result = {'sessionId': 'synthetic'}
    else:
        # Wait for the parent to close stdin during cancellation.
        sys.stdin.read()
        break
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""

    class Client(ReportAcpClient):
        async def prompt(self, text):
            processes.append(self._process)
            started.set()
            return await super().prompt(text)

    conversation = await ReportChannelAcp(
        repository, lambda: Client((sys.executable, "-u", "-c", peer), tmp_path),
    ).bind("channel", identity)
    pending = asyncio.create_task(conversation.prompt(identity, "hello", message_id="first"))
    try:
        await asyncio.wait_for(started.wait(), 2)
        repository.active = False
        with pytest.raises(ReportChannelAcpDenied):
            await asyncio.wait_for(pending, 5)
        assert processes[0].returncode is not None
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
