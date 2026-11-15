from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentAdapterRegistry, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_gateway import (
    DocumentCandidateDenied, DocumentCandidateGateway,
)


def scope():
    return DocumentScope("channel-a", "grant-a", "document-a", "1", "a" * 64, DocumentFormat.DOCX)


@pytest.mark.anyio
async def test_gateway_derives_scope_from_host_and_rechecks_after_prepare():
    current = scope()
    seen = []

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            seen.append(request)
            return "task-a"

        async def status(self, authorized_scope, task_id):
            return {"status": "ready"}

    async def resolve(channel, identity):
        return current if channel == "channel-a" and identity == "member" else None

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    task_id = await gateway.prepare(
        "channel-a", "member", request_id="one", instruction="Edit",
        selection=({"objectId": "one"},),
    )
    assert task_id == "task-a"
    assert seen[0].scope == current
    assert (await gateway.status("channel-a", "member", task_id))["status"] == "ready"
    with pytest.raises(DocumentCandidateDenied):
        await gateway.status("channel-b", "member", task_id)


@pytest.mark.anyio
async def test_gateway_does_not_return_result_after_grant_changes():
    current = scope()

    class Adapter:
        format = DocumentFormat.DOCX

        async def prepare(self, request):
            nonlocal current
            current = replace(current, grant="grant-b")
            return "old-task"

        async def status(self, authorized_scope, task_id):
            return {"status": "ready"}

    async def resolve(channel, identity):
        return current

    registry = DocumentAdapterRegistry()
    registry.register(Adapter())
    gateway = DocumentCandidateGateway(registry, resolve)
    with pytest.raises(DocumentCandidateDenied, match="document_scope_changed"):
        await gateway.prepare(
            "channel-a", "member", request_id="one", instruction="Edit",
            selection=({"objectId": "one"},),
        )


@pytest.mark.anyio
async def test_unregistered_format_cannot_execute():
    current = replace(scope(), format=DocumentFormat.XLSX)

    async def resolve(channel, identity):
        return current

    gateway = DocumentCandidateGateway(DocumentAdapterRegistry(), resolve)
    with pytest.raises(ValueError, match="document_adapter_unavailable"):
        await gateway.prepare(
            "channel-a", "member", request_id="one", instruction="Edit",
            selection=({"cell": "A1"},),
        )
