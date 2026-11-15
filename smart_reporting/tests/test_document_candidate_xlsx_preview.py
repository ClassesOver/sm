import hashlib
import io

import pytest
from openpyxl import Workbook, load_workbook

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
    assert preview["formulaCount"] == 1
    assert preview["requiresFormulaRecalculation"] is True
    assert preview["changes"] == [{"sheet": "Sheet1", "cell": "A1", "before": 12, "after": 15}]
    # Rebuilding XLSX archives is not byte-for-byte deterministic (ZIP metadata).
    # Reopen the *same* source bytes to verify the preview never modified cells.
    unchanged = load_workbook(io.BytesIO(original), data_only=False)
    try:
        assert unchanged['Sheet1']['A1'].value == 12
        assert unchanged['Sheet1']['B1'].value == '=A1*2'
    finally:
        unchanged.close()
    assert hashlib.sha256(original).hexdigest() == digest
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


@pytest.mark.anyio
async def test_xlsx_preview_same_request_id_rejects_changed_instruction():
    original = workbook_bytes()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )
    proposals = []

    async def source(_):
        return original

    async def propose(request):
        proposals.append(request.instruction)
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    selection = ({"sheet": "Sheet1", "range": "A1"},)
    first = DocumentCandidateRequest(scope, "same", "First instruction", selection)
    second = DocumentCandidateRequest(scope, "same", "Different instruction", selection)
    assert await engine.prepare(first) == await engine.prepare(first)
    with pytest.raises(ValueError, match="document_request_id_conflict"):
        await engine.prepare(second)
    assert proposals == ["First instruction"]


@pytest.mark.anyio
async def test_concurrent_identical_xlsx_previews_propose_once():
    import asyncio

    original = workbook_bytes()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )
    calls = 0

    async def source(_):
        return original

    async def propose(_):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "same", "Edit", ({"sheet": "Sheet1", "range": "A1"},),
    )
    results = await asyncio.gather(*(engine.prepare(request) for _ in range(8)))
    assert len(set(results)) == 1
    assert calls == 1


@pytest.mark.anyio
async def test_cached_xlsx_preview_rechecks_source_on_retry_and_status():
    original = workbook_bytes()
    changed = original + b"changed"
    current = original
    digest = hashlib.sha256(original).hexdigest()
    scope = DocumentScope("channel", "grant", "book", "1", digest, DocumentFormat.XLSX)
    proposals = 0

    async def source(_):
        return current

    async def propose(_):
        nonlocal proposals
        proposals += 1
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "same", "Edit", ({"sheet": "Sheet1", "range": "A1"},),
    )
    task = await engine.prepare(request)
    current = changed
    with pytest.raises(PermissionError, match="document_source_changed"):
        await engine.prepare(request)
    with pytest.raises(PermissionError, match="document_source_changed"):
        await engine.status(scope, task)
    assert proposals == 1


@pytest.mark.anyio
async def test_xlsx_preview_rejects_source_changed_during_proposal():
    original = workbook_bytes()
    current = original
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )

    async def source(_):
        return current

    async def propose(_):
        nonlocal current
        current = original + b"modified"
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Edit", ({"sheet": "Sheet1", "range": "A1"},),
    )
    with pytest.raises(PermissionError, match="document_source_changed"):
        await engine.prepare(request)


@pytest.mark.anyio
async def test_xlsx_preview_status_is_defensively_copied():
    original = workbook_bytes()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Edit", ({"sheet": "Sheet1", "range": "A1"},),
    )
    task = await engine.prepare(request)
    result = await engine.status(scope, task)
    result["changes"][0]["after"] = 999
    assert (await engine.status(scope, task))["changes"][0]["after"] == 15


@pytest.mark.anyio
async def test_xlsx_preview_rejects_protected_worksheet():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet["A1"] = 12
    sheet.protection.sheet = True
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    original = output.getvalue()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    request = DocumentCandidateRequest(
        scope, "one", "Edit", ({"sheet": "Sheet1", "range": "A1"},),
    )
    with pytest.raises(ValueError, match="xlsx_preview_protected_sheet"):
        await XlsxLiteralPreviewEngine(source, propose).prepare(request)


@pytest.mark.anyio
async def test_xlsx_preview_rejects_source_changed_during_workbook_inspection():
    original = workbook_bytes()
    changed = original + b"new revision"
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )
    reads = 0

    async def source(_):
        nonlocal reads
        reads += 1
        return original if reads < 3 else changed

    async def propose(_):
        return ({"sheet": "Sheet1", "range": "A1", "value": 15},)

    engine = XlsxLiteralPreviewEngine(source, propose)
    request = DocumentCandidateRequest(
        scope, "one", "Edit", ({"sheet": "Sheet1", "range": "A1"},),
    )
    with pytest.raises(PermissionError, match="document_source_changed"):
        await engine.prepare(request)
    assert reads == 3


@pytest.mark.anyio
@pytest.mark.parametrize("address", ["A1", "B2"])
async def test_xlsx_preview_rejects_entire_merged_range_including_anchor(address):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sheet1"
    sheet["A1"] = 12
    sheet.merge_cells("A1:B2")
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    original = output.getvalue()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"sheet": "Sheet1", "range": address, "value": 15},)

    request = DocumentCandidateRequest(
        scope, "one", "Edit merged cell", ({"sheet": "Sheet1", "range": address},),
    )
    with pytest.raises(ValueError, match="xlsx_preview_formula_or_merged_cell"):
        await XlsxLiteralPreviewEngine(source, propose).prepare(request)


@pytest.mark.anyio
@pytest.mark.parametrize("visibility", ["hidden", "veryHidden"])
async def test_xlsx_preview_rejects_hidden_worksheet(visibility):
    workbook = Workbook()
    workbook.active.title = "Visible"
    sheet = workbook.create_sheet("Hidden")
    sheet["A1"] = "private value"
    sheet.sheet_state = visibility
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    original = output.getvalue()
    scope = DocumentScope(
        "channel", "grant", "book", "1", hashlib.sha256(original).hexdigest(),
        DocumentFormat.XLSX,
    )

    async def source(_):
        return original

    async def propose(_):
        return ({"sheet": "Hidden", "range": "A1", "value": "changed"},)

    request = DocumentCandidateRequest(
        scope, "one", "Edit", ({"sheet": "Hidden", "range": "A1"},),
    )
    with pytest.raises(ValueError, match="xlsx_preview_hidden_sheet"):
        await XlsxLiteralPreviewEngine(source, propose).prepare(request)
