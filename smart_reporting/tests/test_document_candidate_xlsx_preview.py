import hashlib
import io

import pytest
from openpyxl import Workbook

from smart_reporting.document_candidate_contract import (
    DocumentCandidateRequest, DocumentFormat, DocumentScope,
)
from smart_reporting.document_candidate_xlsx_preview import XlsxLiteralPreviewEngine


def workbook_bytes():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet["A1"] = 12
    sheet["B1"] = "=A1*2"
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


@pytest.mark.anyio
async def test_xlsx_preview_diff_does_not_modify_original_or_accept():
    original = workbook_bytes()
    digest = hashlib.sha256(original).hexdigest()
    scope = DocumentScope("channel", "grant", "book", "1", digest, DocumentFormat.XLSX)

    async def source(_):
        return original

    async def propose(_):
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Change value", ({"sheet": "Sheet1", "range": "A1"},),
    )
    task_id = await engine.prepare(request)
    preview = await engine.status(scope, task_id)
    assert preview["status"] == "preview_ready"
    assert preview["accepted"] is False
    assert preview["changes"] == [{"sheet": "Sheet1", "cell": "A1", "before": 12, "after": 15}]
    assert original == workbook_bytes()
    assert await engine.prepare(request) == task_id
    with pytest.raises(PermissionError):
        await engine.status(
            DocumentScope("channel", "different", "book", "1", digest, DocumentFormat.XLSX),
            task_id,
        )


@pytest.mark.anyio
async def test_xlsx_preview_rejects_formula_overwrite():
    original = workbook_bytes()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"sheet": "Sheet1", "range": "B1", "value": 5},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Overwrite formula", ({"sheet": "Sheet1", "range": "B1"},),
    )
    with pytest.raises(ValueError, match="xlsx_preview_formula_or_merged_cell"):
        await engine.prepare(request)
