from unittest.mock import AsyncMock

import pytest

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_xlsx_adapter import XlsxCandidateAdapter


def scope():
    return DocumentScope("channel", "grant", "workbook", "1", "a" * 64, DocumentFormat.XLSX)


@pytest.mark.anyio
async def test_xlsx_adapter_prepares_only_valid_authorized_targets():
    engine = AsyncMock()
    engine.prepare.return_value = "task-one"
    engine.status.return_value = {"status": "pending"}
    authorized = AsyncMock(return_value=True)
    source = AsyncMock(return_value=True)
    adapter = XlsxCandidateAdapter(engine, authorized, source)
    request = DocumentCandidateRequest(
        scope(), "one", "Update cells", ({"sheet": "Sheet1", "range": "A1:B2"},),
    )
    assert await adapter.prepare(request) == "task-one"
    assert (await adapter.status(scope(), "task-one"))["status"] == "pending"
    engine.prepare.assert_awaited_once_with(request)
    assert authorized.await_count == 4
    assert source.await_count == 4


@pytest.mark.anyio
async def test_xlsx_adapter_rejects_bad_target_without_engine_call():
    engine = AsyncMock()
    adapter = XlsxCandidateAdapter(
        engine, AsyncMock(return_value=True), AsyncMock(return_value=True),
    )
    request = DocumentCandidateRequest(
        scope(), "one", "Update", ({"sheet": "Sheet1", "range": "XFE1"},),
    )
    with pytest.raises(ValueError, match="xlsx_target_out_of_bounds"):
        await adapter.prepare(request)
    engine.prepare.assert_not_awaited()


@pytest.mark.anyio
async def test_xlsx_adapter_suppresses_result_if_source_changes():
    engine = AsyncMock()
    engine.prepare.return_value = "task-one"
    source = AsyncMock(side_effect=[True, False])
    adapter = XlsxCandidateAdapter(engine, AsyncMock(return_value=True), source)
    request = DocumentCandidateRequest(
        scope(), "one", "Update", ({"sheet": "Sheet1", "range": "A1"},),
    )
    with pytest.raises(PermissionError, match="document_source_changed"):
        await adapter.prepare(request)
    engine.prepare.assert_awaited_once()
