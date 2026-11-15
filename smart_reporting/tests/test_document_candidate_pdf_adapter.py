from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_pdf_adapter import PdfCandidateAdapter
from smart_reporting.document_candidate_pdf_targets import validate_pdf_selection


def scope():
    return DocumentScope("channel", "grant", "pdf", "1", "a" * 64, DocumentFormat.PDF)


@pytest.mark.parametrize("target", [
    {"page": -1, "rect": [0, 0, 1, 1]},
    {"page": True, "rect": [0, 0, 1, 1]},
    {"page": 0, "rect": [0.5, 0, 0.1, 1]},
    {"page": 0, "rect": [0, 0, float("nan"), 1]},
    {"page": 0, "rect": [0, 0, 1, 2]},
    {"page": 0, "rect": [0, 0, 1, 1], "raw_pdf": "unsafe"},
])
def test_pdf_selection_rejects_invalid_geometry(target):
    with pytest.raises(ValueError):
        validate_pdf_selection((target,))


@pytest.mark.anyio
async def test_pdf_adapter_delegates_only_valid_authorized_preview():
    engine = AsyncMock()
    engine.prepare.return_value = "task-one"
    engine.status.return_value = {"status": "preview_ready", "accepted": False}
    adapter = PdfCandidateAdapter(
        engine, AsyncMock(return_value=True), AsyncMock(return_value=True),
    )
    request = DocumentCandidateRequest(
        scope(), "one", "Add note", ({"page": 0, "rect": [0.1, 0.2, 0.3, 0.4]},),
    )
    assert await adapter.prepare(request) == "task-one"
    assert (await adapter.status(scope(), "task-one"))["accepted"] is False
    engine.prepare.assert_awaited_once_with(request)


@pytest.mark.anyio
async def test_pdf_adapter_rejects_revoked_grant_before_engine():
    engine = AsyncMock()
    adapter = PdfCandidateAdapter(
        engine, AsyncMock(return_value=False), AsyncMock(return_value=True),
    )
    request = DocumentCandidateRequest(
        scope(), "one", "Add note", ({"page": 0, "rect": [0, 0, 1, 1]},),
    )
    with pytest.raises(PermissionError, match="document_channel_authorization_required"):
        await adapter.prepare(request)
    engine.prepare.assert_not_awaited()
