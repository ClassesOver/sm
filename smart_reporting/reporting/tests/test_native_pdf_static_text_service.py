"""静态文字复用现有 PDF 文字开关和预览确认合同。"""

from io import BytesIO

import pytest
from pypdf import PdfReader

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["preview", "preview_file", "save"])
async def test_static_text_requires_existing_text_feature_before_engine(
    tmp_path, action
):
    editor, context, _, _ = await fixture(tmp_path, text_enabled=False)
    operation = {
        "kind": "insertText",
        "sourceSha256": context.source_file.sha256,
        "pageId": f"sha256:{context.source_file.sha256}:page:0",
        "origin": [50, 180],
        "text": "ADDED SEARCHABLE TEXT",
        "fontSize": 12,
        "color": [0, 0, 0],
        "align": "left",
    }
    options = dict(expected_sha256=context.source_file.sha256, operations=[operation])
    if action == "save":
        options["request_id"] = "disabled-insert"
    with pytest.raises(ReportingError) as caught:
        await getattr(editor, action)(context, **options)
    assert caught.value.code == "native_pdf_text_disabled"
    assert not editor.repository.rows


@pytest.mark.anyio
@pytest.mark.parametrize("insert_count", [1, 2, 3])
async def test_static_text_preview_confirmation_download_and_source_identity(tmp_path, insert_count):
    editor, context, source, downloads = await fixture(tmp_path)
    operations = [
        {
            "kind": "insertText",
            "sourceSha256": context.source_file.sha256,
            "pageId": f"sha256:{context.source_file.sha256}:page:0",
            "origin": [50, 180],
            "text": "ADDED SEARCHABLE TEXT",
            "fontSize": 12,
            "color": [0.2, 0.4, 0.6],
            "align": "left",
        }
    ]
    if insert_count >= 2:
        operations.append({**operations[0], "origin": [50, 140], "text": "SECOND SEARCHABLE TEXT", "font": "courier"})
    if insert_count == 3:
        from smart_reporting.reporting.delivery.pdf_native import inspect_pdf
        model = inspect_pdf(source, include_text=True)
        target = next(item for item in model["pages"][0]["textObjects"] if item["text"] == "Amount due 500")
        operations.insert(1, {"kind": "replaceText", "sourceSha256": context.source_file.sha256,
            "pageId": operations[0]["pageId"], "objectId": target["objectId"],
            "expectedTextSha256": target["expectedTextSha256"], "newText": "Amount due 750", "font": "courier", "fontSize": 12})
    preview = await editor.preview(
        context, expected_sha256=context.source_file.sha256, operations=operations
    )
    assert preview["appliedOperationIndices"] == list(range(insert_count))
    assert preview["skippedOperations"] == []
    actual = await editor.preview_file(
        context,
        expected_sha256=context.source_file.sha256,
        operations=operations,
        expected_preview_digest=preview["previewDigest"],
    )
    with pytest.raises(ReportingError) as caught:
        await editor.save(
            context,
            expected_sha256=context.source_file.sha256,
            operations=operations,
            request_id="wrong-insert",
            confirmed_preview_digest="0" * 64,
        )
    assert caught.value.code == "native_pdf_text_preview_changed"
    result = await editor.save(
        context,
        expected_sha256=context.source_file.sha256,
        operations=operations,
        request_id="confirmed-insert",
        confirmed_preview_digest=preview["previewDigest"],
    )
    assert result["revisionRegistered"]
    assert result["validation"]["ok"] is False
    token = result["artifacts"]["pdf"]["downloadUrl"].split("/")[-2]
    _, chunks = await downloads.stream(token, artifact="pdf")
    saved = b"".join([chunk async for chunk in chunks])
    assert saved == actual["content"]
    text = PdfReader(BytesIO(saved)).pages[0].extract_text()
    if insert_count >= 2:
        assert "SECOND SEARCHABLE TEXT" in text
    assert "ADDED SEARCHABLE TEXT" in text
    assert "UNCHANGED CONTROL" in text
    if insert_count == 3:
        assert "Amount due 750" in text and "Amount due 500" not in text
    else:
        assert "Amount due 500" in text
    assert (
        await editor.workspace.afile_bytes(
            bind_native_workspace(editor.workspace, context.scope),
            context.source_file.path,
        )
    )[0] == source


@pytest.mark.anyio
async def test_static_text_requires_confirmation_before_reserving_revision(tmp_path):
    editor, context, _, _ = await fixture(tmp_path)
    with pytest.raises(ReportingError) as caught:
        await editor.save(
            context,
            expected_sha256=context.source_file.sha256,
            operations=[{"kind": "insertText"}],
            request_id="unconfirmed-insert",
        )
    assert caught.value.code == "native_pdf_text_confirmation_required"
    assert not editor.repository.rows
