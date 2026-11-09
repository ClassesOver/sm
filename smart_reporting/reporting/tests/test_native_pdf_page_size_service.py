"""Actual paper bytes through preview/service/publication without the text flag."""
from io import BytesIO

import pytest
from pypdf import PdfReader

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_page_size_preview_digest_and_download_work_with_text_editing_disabled(tmp_path):
    editor, context, source, downloads = await fixture(tmp_path, text_enabled=False)
    operations = [{'kind': 'setPageSize', 'preset': 'A4'}]
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
    assert preview['previewDigest']
    assert preview['appliedOperationIndices'] == [0]
    assert preview['model']['pages'][0]['mediaBox']['width'] == 595
    assert preview['model']['pages'][0]['mediaBox']['height'] == 842
    actual = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=operations, expected_preview_digest=preview['previewDigest'])
    page = PdfReader(BytesIO(actual['content'])).pages[0]
    assert (float(page.mediabox.width), float(page.mediabox.height)) == (595, 842)
    with pytest.raises(ReportingError) as caught:
        await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[{'kind': 'setPageSize', 'preset': 'A5'}], expected_preview_digest=preview['previewDigest'])
    assert caught.value.code == 'native_pdf_text_preview_changed'
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=operations, request_id='page-size-save')
    assert result['revisionRegistered'] and not result['validation']['ok']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    saved = b''.join([part async for part in chunks])
    assert saved == actual['content']
    assert PdfReader(BytesIO(saved)).pages[0].extract_text() == PdfReader(BytesIO(source)).pages[0].extract_text()
