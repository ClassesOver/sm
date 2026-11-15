from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_pptx_adapter import PptxCandidateAdapter


def scope(grant="grant"):
    return DocumentScope("channel", grant, "deck", "1", "a" * 64, DocumentFormat.PPTX)


@pytest.mark.anyio
async def test_pptx_adapter_preview_is_scoped_and_idempotent():
    engine = AsyncMock()
    engine.prepare.return_value = {
        "status": "preview_ready", "accepted": False,
        "changes": [{"slide_id": 256, "shape_id": 2, "before": "A", "after": "B"}],
    }
    adapter = PptxCandidateAdapter(
        engine, AsyncMock(return_value=True), AsyncMock(return_value=True),
    )
    request = DocumentCandidateRequest(
        scope(), "one", "Rewrite", ({"slide_id": 256, "shape_id": 2},),
    )
    task = await adapter.prepare(request)
    assert task == await adapter.prepare(request)
    engine.prepare.assert_awaited_once_with(request)
    result = await adapter.status(scope(), task)
    result["changes"][0]["after"] = "tampered"
    assert (await adapter.status(scope(), task))["changes"][0]["after"] == "B"
    with pytest.raises(PermissionError):
        await adapter.status(scope("other-grant"), task)
    with pytest.raises(ValueError, match="document_request_id_conflict"):
        await adapter.prepare(DocumentCandidateRequest(
            scope(), "one", "Different", ({"slide_id": 256, "shape_id": 2},),
        ))


@pytest.mark.anyio
async def test_pptx_adapter_revocation_blocks_preview_return():
    engine = AsyncMock()
    engine.prepare.return_value = {"status": "preview_ready", "accepted": False, "changes": []}
    authorize = AsyncMock(side_effect=[True, False])
    adapter = PptxCandidateAdapter(engine, authorize, AsyncMock(return_value=True))
    request = DocumentCandidateRequest(
        scope(), "one", "Rewrite", ({"slide_id": 256, "shape_id": 2},),
    )
    with pytest.raises(PermissionError, match="document_channel_authorization_required"):
        await adapter.prepare(request)
    engine.prepare.assert_awaited_once()
