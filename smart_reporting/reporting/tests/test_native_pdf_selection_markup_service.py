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
