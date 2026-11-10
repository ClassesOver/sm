"""Every PDF preview returns an output-bound digest; merge/split pages reproduce byte-identically."""
from io import BytesIO

import pytest
from pypdf import PdfReader

from smart_reporting.reporting.tests.test_native_pdf_text_service import fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.anyio
async def test_drawing_redaction_and_layout_previews_return_reproducible_digests(tmp_path):
    editor, context, source, downloads = await fixture(tmp_path, text_enabled=False)
    sha = context.source_file.sha256
    page_id = (await editor.preview(context, expected_sha256=sha, operations=[]))['model']['pages'][0]['pageId']
    for operations in (
        [{'kind': 'addDrawing', 'pageId': page_id, 'shape': 'rect', 'rect': [20, 20, 80, 60], 'color': [1, 0, 0], 'width': 2}],
        [{'kind': 'redact', 'pageId': page_id, 'rect': [20, 20, 80, 60]}],
        [{'kind': 'splitPages', 'perPage': 2}],
    ):
        preview = await editor.preview(context, expected_sha256=sha, operations=operations)
        assert preview['previewDigest'] and preview['appliedOperationIndices'] == [0], operations
        actual = await editor.preview_file(context, expected_sha256=sha, operations=operations, expected_preview_digest=preview['previewDigest'])
        assert len(PdfReader(BytesIO(actual['content'])).pages) == len(preview['model']['pages'])
    pages = len(PdfReader(BytesIO(source)).pages)
    split = await editor.preview(context, expected_sha256=sha, operations=[{'kind': 'splitPages', 'perPage': 2}])
    assert len(split['model']['pages']) == pages * 2
    operations = [{'kind': 'mergePages', 'perSheet': 2, 'direction': 'vertical', 'separator': False}]
    preview = await editor.preview(context, expected_sha256=sha, operations=operations)
    result = await editor.save(context, expected_sha256=sha, operations=operations, request_id='merge-pages-save')
    assert result['revisionRegistered']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    saved = b''.join([part async for part in chunks])
    assert len(PdfReader(BytesIO(saved)).pages) == len(preview['model']['pages']) == (pages + 1) // 2
