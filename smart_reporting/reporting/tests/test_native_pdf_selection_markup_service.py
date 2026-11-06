"""Non-text PDF markup preview and actual publication/download service."""
from io import BytesIO

import pytest
from pypdf import PdfReader

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_selection_markup_preview_and_download_do_not_require_text_editing(tmp_path):
    editor, context, source, downloads = await fixture(tmp_path, text_enabled=False)
    operation = {'kind': 'addMarkup', 'pageId': f'sha256:{context.source_file.sha256}:page:0', 'markupType': 'underline', 'quads': [[30, 240, 140, 240, 30, 225, 140, 225]], 'color': [.17, .4, 1]}
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[operation])
    assert preview['appliedOperationIndices'] == [0]
    actual = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[operation], expected_preview_digest=preview['previewDigest'])
    changed = {**operation, 'color': [1, 0, 0]}
    with pytest.raises(ReportingError):
        await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[changed], expected_preview_digest=preview['previewDigest'])
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=[operation], request_id='markup-save')
    assert result['revisionRegistered'] and not result['validation']['ok']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    assert content == actual['content']
    reader = PdfReader(BytesIO(content))
    assert reader.pages[0]['/Annots'][-1].get_object()['/Subtype'] == '/Underline'
    assert reader.pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()


@pytest.mark.anyio
async def test_saved_markup_removal_preview_download_and_stale_identity_without_text_flag(tmp_path):
    import hashlib

    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
    from smart_reporting.reporting.tests.test_pdf_markup_removal import removal

    editor, context, source, downloads = await fixture(tmp_path, text_enabled=False)
    add = {'kind': 'addMarkup', 'pageId': inspect_pdf(source)['pages'][0]['pageId'], 'markupType': 'underline', 'quads': [[30, 240, 140, 240, 30, 225, 140, 225]], 'color': [.17, .4, 1]}
    source = patch_pdf(source, [add])
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace, context.scope), 'native/marked.pdf', source)
    context = context.model_copy(update={'source_file': ArtifactFile(path='native/marked.pdf', size=len(source), sha256=hashlib.sha256(source).hexdigest(), mediaType='application/pdf')})
    operation = removal(source)
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[operation])
    assert preview['appliedOperationIndices'] == [0] and preview['previewDigest']
    actual = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[operation], expected_preview_digest=preview['previewDigest'])
    with pytest.raises(ReportingError):
        await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[{**operation, 'expectedAnnotationSha256': '0' * 64}], expected_preview_digest=preview['previewDigest'])
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=[operation], request_id='remove-markup')
    assert result['revisionRegistered'] and not result['validation']['ok']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    assert content == actual['content']
    assert not inspect_pdf(content)['pages'][0]['markups']
    assert PdfReader(BytesIO(content)).pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()


@pytest.mark.anyio
async def test_saved_note_edit_preview_save_and_download_without_text_flag(tmp_path):
    import hashlib

    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf, patch_pdf
    from smart_reporting.reporting.tests.test_pdf_saved_notes import note_operation

    editor, context, source, downloads = await fixture(tmp_path, text_enabled=False)
    page_id = inspect_pdf(source)['pages'][0]['pageId']
    source = patch_pdf(source, [{'kind': 'addTextAnnotation', 'pageId': page_id, 'rect': [30, 100, 50, 118], 'text': 'original note'}])
    await editor.workspace.awrite_bytes(bind_native_workspace(editor.workspace, context.scope), 'native/note-source.pdf', source)
    context = context.model_copy(update={'source_file': ArtifactFile(path='native/note-source.pdf', size=len(source), sha256=hashlib.sha256(source).hexdigest(), mediaType='application/pdf')})
    operation = note_operation(source)
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[operation])
    assert preview['appliedOperationIndices'] == [0] and preview['previewDigest']
    actual = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[operation], expected_preview_digest=preview['previewDigest'])
    with pytest.raises(ReportingError):
        await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[{**operation, 'contents': 'changed'}], expected_preview_digest=preview['previewDigest'])
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=[operation], request_id='saved-note-edit')
    assert result['revisionRegistered'] and not result['validation']['ok']
    _, chunks = await downloads.stream(result['artifacts']['pdf']['downloadUrl'].split('/')[-2], artifact='pdf')
    content = b''.join([chunk async for chunk in chunks])
    assert content == actual['content']
    assert inspect_pdf(content)['pages'][0]['notes'][0]['contents'] == operation['contents']
    assert PdfReader(BytesIO(content)).pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()
