from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest,
    DocumentFormat,
    DocumentScope,
)
from smart_reporting.document_candidate_word_adapter import ChannelWordCandidateAdapter
from smart_reporting.report_channel_api import ConnectorIdentity


@pytest.mark.anyio
async def test_word_adapter_delegates_only_authorized_matching_source():
    identity = ConnectorIdentity("dsh", "subject", "session")
    scope = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.DOCX)
    repository = SimpleNamespace(
        member_grant=AsyncMock(return_value="grant"),
        grant_active=AsyncMock(return_value=True),
    )
    word = SimpleNamespace(
        repository=repository,
        _draft=AsyncMock(return_value=SimpleNamespace(source_sha256="a" * 64, selection=[{"paragraph": "1"}])),
        start=AsyncMock(return_value={"taskId": "word-task"}),
        status=AsyncMock(return_value={"taskId": "word-task", "status": "pending"}),
    )
    adapter = ChannelWordCandidateAdapter(word, lambda scope: resolve_identity(identity))
    request = DocumentCandidateRequest(scope, "request-one", "Revise paragraph", ({"paragraph": "1"},))
    assert await adapter.prepare(request) == "word-task"
    assert word.start.await_args.args[:2] == ("channel", identity)
    assert (await adapter.status(scope, "word-task"))["status"] == "pending"

    repository.member_grant.return_value = "different-grant"
    with pytest.raises(PermissionError):
        await adapter.prepare(request)
    assert word.start.await_count == 1


async def resolve_identity(identity):
    return identity


@pytest.mark.anyio
async def test_word_adapter_rejects_changed_source_before_delegation():
    identity = ConnectorIdentity("dsh", "subject", "session")
    scope = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.DOCX)
    word = SimpleNamespace(
        repository=SimpleNamespace(
            member_grant=AsyncMock(return_value="grant"),
            grant_active=AsyncMock(return_value=True),
        ),
        _draft=AsyncMock(return_value=SimpleNamespace(source_sha256="b" * 64, selection=[{"paragraph": "1"}])),
        start=AsyncMock(),
    )
    adapter = ChannelWordCandidateAdapter(word, lambda scope: resolve_identity(identity))
    request = DocumentCandidateRequest(scope, "request-one", "Revise", ({"paragraph": "1"},))
    with pytest.raises(PermissionError, match="document_source_changed"):
        await adapter.prepare(request)
    word.start.assert_not_awaited()


@pytest.mark.anyio
async def test_word_adapter_rejects_selection_mismatch_without_starting_edit():
    identity = ConnectorIdentity("dsh", "subject", "session")
    scope = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.DOCX)
    word = SimpleNamespace(
        repository=SimpleNamespace(
            member_grant=AsyncMock(return_value="grant"),
            grant_active=AsyncMock(return_value=True),
        ),
        _draft=AsyncMock(return_value=SimpleNamespace(
            source_sha256="a" * 64, selection=[{"paragraph": "2"}],
        )),
        start=AsyncMock(),
    )
    adapter = ChannelWordCandidateAdapter(word, lambda scope: resolve_identity(identity))
    request = DocumentCandidateRequest(scope, "request-one", "Revise", ({"paragraph": "1"},))
    with pytest.raises(ValueError, match="document_selection_mismatch"):
        await adapter.prepare(request)
    word.start.assert_not_awaited()


@pytest.mark.anyio
async def test_word_adapter_binds_validated_selection_instead_of_resolving_again():
    from smart_reporting.report_channel_word import ChannelWordDraft, ReportChannelWordAssistant

    identity = ConnectorIdentity("dsh", "subject", "session")
    scope = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.DOCX)
    repository = SimpleNamespace(member_grant=AsyncMock(return_value="grant"),
                                 grant_active=AsyncMock(return_value=True))
    selected = [{"blockId": "A"}]
    first = ChannelWordDraft(object(), scope.source_sha256, [], selected)
    second = ChannelWordDraft(object(), scope.source_sha256, [], [{"blockId": "B"}])
    ai = SimpleNamespace(
        editor=SimpleNamespace(context_for_session=AsyncMock(return_value=SimpleNamespace(format="docx"))),
        start_edit=AsyncMock(return_value={"editId": "task", "status": "running", "accepted": False}),
    )
    word = ReportChannelWordAssistant(ai, AsyncMock(side_effect=[first, second]), repository)
    adapter = ChannelWordCandidateAdapter(word, AsyncMock(return_value=identity))
    request = DocumentCandidateRequest(scope, "request", "Change A", tuple(selected))
    assert await adapter.prepare(request) == "task"
    assert ai.start_edit.await_args.kwargs["selection"] == selected
    assert ai.start_edit.await_args.args == (first.session,)


@pytest.mark.anyio
async def test_word_adapter_rejects_replacement_grant_before_start():
    from fastapi import HTTPException

    from smart_reporting.report_channel_word import ChannelWordDraft, ReportChannelWordAssistant

    identity = ConnectorIdentity("dsh", "subject", "session")
    scope = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.DOCX)
    repository = SimpleNamespace(member_grant=AsyncMock(side_effect=["grant", "replacement"]),
                                 grant_active=AsyncMock(return_value=True))
    draft = ChannelWordDraft(object(), scope.source_sha256, [], [{"blockId": "A"}])
    ai = SimpleNamespace(
        editor=SimpleNamespace(context_for_session=AsyncMock(return_value=SimpleNamespace(format="docx"))),
        start_edit=AsyncMock(return_value={"editId": "task", "status": "running", "accepted": False}),
    )
    word = ReportChannelWordAssistant(ai, AsyncMock(return_value=draft), repository)
    adapter = ChannelWordCandidateAdapter(word, AsyncMock(return_value=identity))
    request = DocumentCandidateRequest(scope, "request", "Change A", tuple(draft.selection))
    with pytest.raises((HTTPException, PermissionError)):
        await adapter.prepare(request)
    ai.start_edit.assert_not_awaited()


@pytest.mark.anyio
async def test_word_snapshot_copies_nested_data_before_authorization_await():
    from smart_reporting.report_channel_api import DelegateRequest
    from smart_reporting.report_channel_word import ChannelWordDraft, ReportChannelWordAssistant

    identity = ConnectorIdentity("dsh", "subject", "session")
    selection = [{"blockId": "A"}]
    operations = [{"kind": "formatParagraph", "style": {"bold": True}}]
    draft = ChannelWordDraft(object(), "a" * 64, operations, selection)

    async def member_grant(*args):
        selection[0]["blockId"] = "B"
        operations[0]["style"]["bold"] = False
        return "grant"

    repository = SimpleNamespace(member_grant=member_grant, grant_active=AsyncMock(return_value=True))
    ai = SimpleNamespace(start_edit=AsyncMock(return_value={"editId": "task", "status": "running", "accepted": False}))
    word = ReportChannelWordAssistant(ai, AsyncMock(), repository)
    await word.start("channel", identity, DelegateRequest(request_id="one", instruction="Change A"),
                     validated_draft=draft, expected_grant="grant")
    assert ai.start_edit.await_args.kwargs["selection"] == [{"blockId": "A"}]
    assert ai.start_edit.await_args.kwargs["operations"][0]["style"]["bold"] is True
