"""已有图像像素替换：真实 PDF 服务预览确认、保存签发与 pypdf 独立回读。"""
from io import BytesIO
import base64
import hashlib

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_models import NativeEditorContext
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_publication_nonblocking import create_publication


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def _png(color, size):
    stream = BytesIO()
    Image.new('RGB', size, color).save(stream, 'PNG')
    return stream.getvalue()


def _source(shared=False):
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(400, 500))
    pdf.drawString(30, 450, 'Body text stays')
    first = ImageReader(BytesIO(_png('red', (8, 6))))
    pdf.drawImage(first, 60, 90, 100, 80)
    pdf.drawImage(first if shared else ImageReader(BytesIO(_png('green', (4, 4)))), 250, 300, 60, 60)
    pdf.save()
    return stream.getvalue()


async def _fixture(tmp_path, content):
    publication, old, downloads = await create_publication(tmp_path)
    key = bind_native_workspace(publication.workspace, old.scope)
    await publication.workspace.awrite_bytes(key, 'native/source.pdf', content)
    context = NativeEditorContext(documentId='document', revision=1, scope=old.scope, format='pdf', origin='upload',
                                  sourceFile=ArtifactFile(path='native/source.pdf', size=len(content), sha256=hashlib.sha256(content).hexdigest(), mediaType='application/pdf'))
    editor = NativeEditorService(publication.workspace, publication.repository, publication.editor_grants,
                                 report_editor=None, pdf_enabled=True, pdf_text_enabled=False, publication=publication)
    return editor, context, downloads


def _images(content):
    page = PdfReader(BytesIO(content)).pages[0]
    return sorted((image.image.size, hashlib.sha256(image.data).hexdigest()) for image in page.images)


@pytest.mark.anyio
async def test_confirmed_pixel_replacement_saves_and_downloads_real_bytes(tmp_path):
    content = _source()
    editor, context, downloads = await _fixture(tmp_path, content)
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    target = next(image for image in model['existingImages'] if image['rect'] == [60, 90, 160, 170])
    assert target['editable'] and target['replaceable']
    replacement = base64.b64encode(_png('blue', (12, 9))).decode()
    operations = [{'kind': 'transformExistingImage', 'sourceSha256': context.source_file.sha256, 'pageId': target['pageId'],
                   'imageId': target['imageId'], 'expectedImageSha256': target['expectedImageSha256'], 'rect': target['rect'], 'image': replacement}]
    with pytest.raises(ReportingError) as caught:
        await editor.save(context, expected_sha256=context.source_file.sha256, operations=operations, request_id='unconfirmed')
    assert caught.value.code == 'native_pdf_text_confirmation_required'
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
    assert preview['appliedOperationIndices'] == [0] and preview['skippedOperations'] == []
    actual = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=operations, expected_preview_digest=preview['previewDigest'])
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=operations, request_id='replace', confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    saved = b''.join([part async for part in chunks])
    assert saved == actual['content']
    sizes = [size for size, _ in _images(saved)]
    assert (12, 9) in sizes and (4, 4) in sizes and (8, 6) not in sizes
    assert 'Body text stays' in PdfReader(BytesIO(saved)).pages[0].extract_text()
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path))[0] == content


@pytest.mark.anyio
async def test_shared_image_stream_cannot_be_replaced(tmp_path):
    content = _source(shared=True)
    editor, context, _ = await _fixture(tmp_path, content)
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    target = model['existingImages'][0]
    assert target['editable'] and target['replaceable'] is False and '多处引用' in target['replaceReason']
    operations = [{'kind': 'transformExistingImage', 'sourceSha256': context.source_file.sha256, 'pageId': target['pageId'],
                   'imageId': target['imageId'], 'expectedImageSha256': target['expectedImageSha256'], 'rect': target['rect'],
                   'image': base64.b64encode(_png('blue', (12, 9))).decode()}]
    with pytest.raises(ReportingError):
        await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
