"""已有图像裁剪 / 翻转 / 透明度：真实 PDF 服务预览确认、保存签发与 pypdf 独立回读。"""
from io import BytesIO
import hashlib

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_existing_image_replace import _fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def _quadrants():
    image = Image.new('RGB', (8, 8), 'white')
    for box, color in (((0, 0, 4, 4), 'red'), ((4, 0, 8, 4), (0, 200, 0)), ((0, 4, 4, 8), 'blue')):
        image.paste(color, box)
    stream = BytesIO(); image.save(stream, 'PNG')
    return stream.getvalue()


def _source():
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=(400, 500))
    pdf.drawString(30, 450, 'Body text stays')
    pdf.drawImage(ImageReader(BytesIO(_quadrants())), 60, 90, 100, 80)
    green = BytesIO(); Image.new('RGB', (4, 4), 'green').save(green, 'PNG')
    pdf.drawImage(ImageReader(BytesIO(green.getvalue())), 250, 300, 60, 60)
    pdf.save()
    return stream.getvalue()


def _target_image(content):
    """回读第 1 页上占位最大的图像（目标）为 RGB PIL 图像。"""
    page = PdfReader(BytesIO(content)).pages[0]
    images = sorted(page.images, key=lambda image: image.image.size[0] * image.image.size[1])
    return images[-1].image.convert('RGBA'), [image.image.size for image in images]


async def _save(editor, context, downloads, operations, request_id):
    with pytest.raises(ReportingError) as caught:
        await editor.save(context, expected_sha256=context.source_file.sha256, operations=operations, request_id=request_id + '-unconfirmed')
    assert caught.value.code == 'native_pdf_text_confirmation_required'
    preview = await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
    assert preview['appliedOperationIndices'] == [0] and preview['skippedOperations'] == []
    actual = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=operations, expected_preview_digest=preview['previewDigest'])
    result = await editor.save(context, expected_sha256=context.source_file.sha256, operations=operations, request_id=request_id, confirmed_preview_digest=preview['previewDigest'])
    assert result['revisionRegistered']
    token = result['artifacts']['pdf']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(token, artifact='pdf')
    saved = b''.join([part async for part in chunks])
    assert saved == actual['content']
    return saved, preview


def _close(pixel, expected, tolerance=16):
    assert all(abs(a - b) <= tolerance for a, b in zip(pixel, expected)), (pixel, expected)


@pytest.mark.anyio
@pytest.mark.parametrize('bake, check, expected_size', [
    ({'kind': 'flip', 'axis': 'h'}, lambda image: (_close(image.getpixel((image.width // 4, image.height // 4)), (0, 200, 0, 255)),
                                                  _close(image.getpixel((3 * image.width // 4, image.height // 4)), (255, 0, 0, 255))), (300, 240)),
    ({'kind': 'crop', 'crop': {'l': 0, 't': 0, 'r': .5, 'b': .5}}, lambda image: _close(image.getpixel((image.width - 2, image.height - 2)), (255, 0, 0, 255)), (150, 120)),
    ({'kind': 'rotate', 'quarterTurns': 1}, lambda image: (_close(image.getpixel((image.width // 4, image.height // 4)), (0, 0, 255, 255)),
                                                           _close(image.getpixel((3 * image.width // 4, image.height // 4)), (255, 0, 0, 255))), (240, 300)),
    ({'kind': 'rotate', 'quarterTurns': 3}, lambda image: (_close(image.getpixel((image.width // 4, image.height // 4)), (0, 200, 0, 255)),
                                                           _close(image.getpixel((3 * image.width // 4, image.height // 4)), (255, 255, 255, 255))), (240, 300)),
])
async def test_confirmed_bake_saves_and_downloads_real_bytes(tmp_path, bake, check, expected_size):
    content = _source()
    editor, context, downloads = await _fixture(tmp_path, content)
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    target = next(image for image in model['existingImages'] if image['rect'] == [60, 90, 160, 170])
    assert target['bakeable'] is True
    x1, y1, x2, y2 = target['rect']
    if bake['kind'] == 'crop':
        rect = [x1, y2 - .5 * (y2 - y1), x1 + .5 * (x2 - x1), y2]
    elif bake['kind'] == 'rotate':
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        rect = [cx - (y2 - y1) / 2, cy - (x2 - x1) / 2, cx + (y2 - y1) / 2, cy + (x2 - x1) / 2]
    else:
        rect = target['rect']
    operations = [{'kind': 'transformExistingImage', 'sourceSha256': context.source_file.sha256, 'pageId': target['pageId'],
                   'imageId': target['imageId'], 'expectedImageSha256': target['expectedImageSha256'], 'rect': rect, 'bake': bake}]
    saved, preview = await _save(editor, context, downloads, operations, bake['kind'])
    image, sizes = _target_image(saved)
    assert (4, 4) in sizes, '另一张图像保持原样'
    assert image.size == expected_size
    check(image)
    assert 'Body text stays' in PdfReader(BytesIO(saved)).pages[0].extract_text()
    reopened = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations))['previewDigest']
    assert reopened == preview['previewDigest'], '同一草稿的预览摘要可复现'
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path))[0] == content


@pytest.mark.anyio
async def test_rotation_requires_an_identity_verified_bakeable_target(tmp_path):
    content = _source()
    editor, context, _ = await _fixture(tmp_path, content)
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    target = next(image for image in model['existingImages'] if image['rect'] == [60, 90, 160, 170])
    assert target['bakeable'] is True
    cx, cy = 110, 130
    operation = {'kind': 'transformExistingImage', 'sourceSha256': context.source_file.sha256, 'pageId': target['pageId'],
                 'imageId': target['imageId'], 'expectedImageSha256': target['expectedImageSha256'],
                 'rect': [70, 80, 150, 180], 'bake': {'kind': 'rotate', 'quarterTurns': 1}}
    assert (cx, cy) == ((operation['rect'][0] + operation['rect'][2]) / 2, (operation['rect'][1] + operation['rect'][3]) / 2)
    changed = {**operation, 'rect': target['rect']}
    with pytest.raises(ReportingError):
        await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[changed])


@pytest.mark.anyio
async def test_bake_refuses_moved_rect(tmp_path):
    content = _source()
    editor, context, _ = await _fixture(tmp_path, content)
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    target = next(image for image in model['existingImages'] if image['rect'] == [60, 90, 160, 170])
    x1, y1, x2, y2 = target['rect']
    operations = [{'kind': 'transformExistingImage', 'sourceSha256': context.source_file.sha256, 'pageId': target['pageId'],
                   'imageId': target['imageId'], 'expectedImageSha256': target['expectedImageSha256'], 'rect': [x1 + 10, y1, x2 + 10, y2], 'bake': {'kind': 'flip', 'axis': 'v'}}]
    with pytest.raises(ReportingError):
        await editor.preview(context, expected_sha256=context.source_file.sha256, operations=operations)
