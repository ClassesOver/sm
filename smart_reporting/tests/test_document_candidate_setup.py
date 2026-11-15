from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import DocumentFormat, DocumentScope
from smart_reporting.document_candidate_setup import build_document_gateway, build_word_document_gateway
from smart_reporting.report_channel_api import ConnectorIdentity


@pytest.mark.anyio
async def test_word_gateway_factory_registers_docx_only():
    identity = ConnectorIdentity("dsh", "subject", "session")
    scope = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.DOCX)
    word = SimpleNamespace(
        repository=SimpleNamespace(
            member_grant=AsyncMock(return_value="grant"),
            grant_active=AsyncMock(return_value=True),
        ),
        _draft=AsyncMock(return_value=SimpleNamespace(
            source_sha256="a" * 64, selection=[{"paragraph": "1"}],
        )),
        start=AsyncMock(return_value={"taskId": "task-one"}),
        status=AsyncMock(return_value={"taskId": "task-one", "status": "pending"}),
    )

    async def resolve_scope(channel, caller):
        return scope if channel == "channel" and caller == identity else None

    async def identity_for_scope(authorized_scope):
        return identity if authorized_scope == scope else None

    gateway = build_word_document_gateway(word, resolve_scope, identity_for_scope)
    task = await gateway.prepare(
        "channel", identity, request_id="one", instruction="Revise",
        selection=({"paragraph": "1"},),
    )
    assert task == "task-one"
    assert (await gateway.status("channel", identity, task))["status"] == "pending"

    # Explicitly registering Word must not silently enable spreadsheet edits.
    spreadsheet_scope = DocumentScope(
        "channel", "grant", "document", "1", "a" * 64, DocumentFormat.XLSX
    )

    async def resolve_xlsx(channel, caller):
        return spreadsheet_scope

    disabled = build_word_document_gateway(word, resolve_xlsx, identity_for_scope)
    with pytest.raises(ValueError, match="document_adapter_unavailable"):
        await disabled.prepare(
            "channel", identity, request_id="two", instruction="Edit",
            selection=({"cell": "A1"},),
        )


@pytest.mark.anyio
async def test_four_format_gateway_only_registers_supplied_engines():
    identity = ConnectorIdentity("dsh", "subject", "session")
    current = DocumentScope("channel", "grant", "document", "1", "a" * 64, DocumentFormat.PDF)

    class PdfAdapter:
        format = DocumentFormat.PDF

        async def prepare(self, request):
            assert request.scope == current
            return "pdf-task"

        async def status(self, authorized_scope, task_id):
            return {"taskId": task_id, "status": "preview_ready", "accepted": False}

    async def resolve(channel, caller):
        return current if channel == "channel" and caller == identity else None

    gateway = build_document_gateway(resolve, pdf=PdfAdapter())
    task = await gateway.prepare(
        "channel", identity, request_id="one", instruction="Add note",
        selection=({"page": 0, "rect": [0, 0, 1, 1]},),
    )
    assert task == "pdf-task"
    assert (await gateway.status("channel", identity, task))["accepted"] is False
    from dataclasses import replace
    current = replace(current, format=DocumentFormat.PPTX)
    with pytest.raises(ValueError, match="document_adapter_unavailable"):
        await gateway.prepare(
            "channel", identity, request_id="two", instruction="Edit slide",
            selection=({"slide_id": 256, "shape_id": 2},),
        )


def test_four_format_gateway_rejects_misregistered_adapter():
    class WrongAdapter:
        format = DocumentFormat.XLSX

    async def resolve(channel, caller):
        return None

    with pytest.raises(ValueError, match="document_adapter_format_mismatch"):
        build_document_gateway(resolve, pdf=WrongAdapter())
