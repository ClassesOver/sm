from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_channel_api import ConnectorIdentity, create_report_channel_router
from smart_reporting.report_channel_invitation import ChannelMember, parse_channel_invitation
from smart_reporting.report_channel_word import ChannelWordDraft, ReportChannelWordAssistant


@pytest.mark.anyio
@pytest.mark.parametrize("editor_path", ["/reports/../admin", "/reports/%2e%2e/admin", "/reports/native%2fother",
    "/reports/native%5cother", "/reports/native/1#", "/reports/native/%252e%252e",
    "/reports/v1/native/open/synthetic-grant", "/reports/v1/native/%6fpen/synthetic-grant"])
async def test_invalid_editor_path_rejected_before_delegation(editor_path):
    identity = ConnectorIdentity("dsh", "account-a", "session-a")
    delegate = AsyncMock()
    app = FastAPI()
    app.include_router(create_report_channel_router(
        SimpleNamespace(has_member=AsyncMock(return_value=True)), AsyncMock(return_value=identity),
        editor_path=lambda _: editor_path, delegate_word=delegate,
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as client:
        response = await client.post("/reports/v1/channels/channel-a/word-tasks",
            json={"request_id": "one", "instruction": "Update synthetic text"})
    assert response.status_code == 500
    assert response.json()["detail"] == "invalid_report_editor_path"
    delegate.assert_not_awaited()


@pytest.mark.anyio
async def test_channel_word_assistant_uses_server_draft_and_reports_private_status():
    identity = ConnectorIdentity("dsh", "account-a", "session-a")
    authenticate = AsyncMock(return_value=identity)
    repository = SimpleNamespace(has_member=AsyncMock(return_value=True),
        member_grant=AsyncMock(return_value="synthetic-grant"), grant_active=AsyncMock(return_value=True))
    draft = ChannelWordDraft(object(), "source-hash", [], [{"blockId": "synthetic"}], "session-reference")
    resolve = AsyncMock(return_value=draft)
    ai = SimpleNamespace(
        editor=SimpleNamespace(context_for_session=AsyncMock(return_value=SimpleNamespace(format="docx"))),
        start_edit=AsyncMock(return_value={"editId": "task-a", "status": "running", "accepted": False}),
        wait_edit_status=AsyncMock(),
    )
    assistant = ReportChannelWordAssistant(ai, resolve, repository)
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, authenticate, delegate_word=assistant.start, word_status=assistant.status,
    ))
    path = "/reports/v1/channels/channel-a/word-tasks"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as client:
        response = await client.post(path, json={"request_id": "one", "instruction": "Revise synthetic text"})
        assert response.status_code == 202
        assert response.json() == {"taskId": "task-a", "status": "running", "accepted": False}
        resolve.assert_awaited_once_with("channel-a")
        args, kwargs = ai.start_edit.await_args
        assert args == (draft.session,)
        assert kwargs["expected_sha256"] == draft.source_sha256
        assert kwargs["selection"] == draft.selection
        assert kwargs["server_session_reference"] == draft.session_reference
        assert await kwargs["authorization_check"]()
        repository.grant_active.return_value = False
        assert not await kwargs["authorization_check"]()
        ai.wait_edit_status.return_value = {
            "editId": "task-a", "status": "ready", "accepted": False,
            "proposal": {"text": "synthetic candidate"}, "clientRequestId": kwargs["client_request_id"],
        }
        assert (await client.get(path + "/task-a")).json() == {
            "taskId": "task-a", "status": "ready", "accepted": False,
        }
        authenticate.return_value = ConnectorIdentity("dsh", "account-a", "another-session")
        assert (await client.get(path + "/task-a")).status_code == 404
        repository.has_member.return_value = False
        assert (await client.get(path + "/task-a")).status_code == 403


@pytest.mark.anyio
async def test_word_task_delegation_requires_membership():
    identity = ConnectorIdentity("dsh", "account-a", "session-a")
    repository = SimpleNamespace(has_member=AsyncMock(return_value=False))
    delegate = AsyncMock(return_value={"taskId": "synthetic"})
    app = FastAPI()
    app.include_router(create_report_channel_router(repository, AsyncMock(return_value=identity), delegate_word=delegate))
    path = "/reports/v1/channels/channel-a/word-tasks"
    payload = {"request_id": "one", "instruction": "Revise the synthetic report"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as client:
        assert (await client.post(path, json=payload)).status_code == 403
        delegate.assert_not_called()
        repository.has_member.return_value = True
        assert (await client.post(path, json={**payload, "report_id": "other"})).status_code == 422
        response = await client.post(path, json=payload)
    assert response.status_code == 202
    assert response.json() == {"taskId": "synthetic"}
    assert delegate.call_args.args[:2] == ("channel-a", identity)


@pytest.mark.anyio
async def test_link_discovery_and_join_return_editor_entry():
    async def exchange(reference, *, validate_channel, **kwargs):
        validate_channel("a")
        return ChannelMember("a", "dsh", "u", "s")

    repository = SimpleNamespace(exchange=AsyncMock(side_effect=exchange))
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, AsyncMock(return_value=ConnectorIdentity("dsh", "u", "s")),
        editor_path=lambda channel: f"/reports/native/{channel}",
    ))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as client:
        discovery = await client.get("/reports/join")
        repository.exchange.assert_not_called()
        response = await client.post(discovery.json()["exchange"]["path"], json={"reference": "A" * 43})
    assert response.json() == {
        "channel": "a", "editorPath": "/reports/native/a", "messagesPath": "/reports/v1/channels/a/messages",
    }


@pytest.mark.anyio
async def test_editor_issues_link_for_server_selected_channel():
    repository = SimpleNamespace(issue=AsyncMock())
    authorize_editor = AsyncMock(return_value=None)
    origin = "https://reports.test"
    app = FastAPI()
    app.include_router(create_report_channel_router(
        repository, AsyncMock(), authorize_editor=authorize_editor, public_origin=origin,
    ))
    payload = {"connector": "dsh", "subject": "account-a"}
    path = "/reports/v1/channels/invitations"
    async with AsyncClient(transport=ASGITransport(app=app), base_url=origin) as client:
        assert (await client.post(path, json=payload)).status_code == 403
        authorize_editor.return_value = "synthetic-channel"
        assert (await client.post(path, json={**payload, "channel": "different"})).status_code == 422
        repository.issue.assert_not_called()
        response = await client.post(path, json=payload)
    assert response.status_code == 201
    reference, invitation = repository.issue.call_args.args
    assert parse_channel_invitation(response.json()["url"], origin=origin) == reference
    assert invitation.channel == "synthetic-channel"


@pytest.mark.anyio
async def test_exchange_uses_identity_from_host_authenticator():
    repository = SimpleNamespace(exchange=AsyncMock(return_value={"channel": "channel-a"}))
    authenticate = AsyncMock(return_value=None)
    app = FastAPI()
    app.include_router(create_report_channel_router(repository, authenticate))
    path = "/reports/v1/channels/invitations/exchange"
    payload = {"reference": "A" * 43}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://reports.test") as client:
        assert (await client.post(path, json=payload)).status_code == 401
        authenticate.return_value = ConnectorIdentity("dsh", "account-a", "session-a")
        assert (await client.post(path, json={**payload, "subject": "account-b"})).status_code == 422
        repository.exchange.assert_not_called()
        accepted = await client.post(path, json=payload)
        assert accepted.json() == {"channel": "channel-a"}
        assert repository.exchange.call_args.kwargs["subject"] == "account-a"
        assert repository.exchange.call_args.kwargs["session"] == "session-a"
        repository.exchange.side_effect = ValueError("consumed")
        assert (await client.post(path, json=payload)).status_code == 403
