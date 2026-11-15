from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
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
        _draft=AsyncMock(return_value=SimpleNamespace(source_sha256="a" * 64)),
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
        _draft=AsyncMock(return_value=SimpleNamespace(source_sha256="b" * 64)),
        start=AsyncMock(),
    )
    adapter = ChannelWordCandidateAdapter(word, lambda scope: resolve_identity(identity))
    request = DocumentCandidateRequest(scope, "request-one", "Revise", ({"paragraph": "1"},))
    with pytest.raises(PermissionError, match="document_source_changed"):
        await adapter.prepare(request)
    word.start.assert_not_awaited()
