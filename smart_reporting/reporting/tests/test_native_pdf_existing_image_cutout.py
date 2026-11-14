"""已有图像去除背景（固定源 cutout）：真实 PDF 服务预览确认、保存签发与 pypdf 独立回读透明度。"""
from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from smart_reporting.report_editor.native import bind_native_workspace
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_existing_image_bake import _save
from smart_reporting.reporting.tests.test_native_pdf_existing_image_replace import _fixture


@pytest.fixture
def anyio_backend():
    return 'asyncio'


def _source():
    badge = Image.new('RGB', (12, 12), 'white')
    badge.paste((220, 30, 30), (4, 4, 8, 8))
    stream, png = BytesIO(), BytesIO()
    badge.save(png, 'PNG')
    pdf = canvas.Canvas(stream, pagesize=(400, 500))
    pdf.drawString(30, 450, 'Body text stays')
    pdf.drawImage(ImageReader(BytesIO(png.getvalue())), 60, 90, 120, 120)
    green = BytesIO(); Image.new('RGB', (4, 4), 'green').save(green, 'PNG')
    pdf.drawImage(ImageReader(BytesIO(green.getvalue())), 250, 300, 60, 60)
    pdf.save()
    return stream.getvalue()


async def _target(editor, context):
    model = (await editor.preview(context, expected_sha256=context.source_file.sha256, operations=[]))['model']
    return next(image for image in model['existingImages'] if image['rect'] == [60, 90, 180, 210])


def _operation(context, target, bake, rect=None):
    return [{'kind': 'transformExistingImage', 'sourceSha256': context.source_file.sha256, 'pageId': target['pageId'],
             'imageId': target['imageId'], 'expectedImageSha256': target['expectedImageSha256'], 'rect': rect or target['rect'], 'bake': bake}]


@pytest.mark.anyio
async def test_confirmed_cutout_saves_transparent_background_and_keeps_subject(tmp_path):
    content = _source()
    editor, context, downloads = await _fixture(tmp_path, content)
    target = await _target(editor, context)
    assert target['bakeable'] is True
    saved, preview = await _save(editor, context, downloads, _operation(context, target, {'kind': 'cutout', 'tolerance': 30}), 'cutout')
    page = PdfReader(BytesIO(saved)).pages[0]
    images = sorted(page.images, key=lambda image: image.image.size[0] * image.image.size[1])
    assert images[0].image.size == (4, 4), '另一张图像保持原样'
    image = images[-1].image
    assert image.mode == 'RGBA' and image.size == (360, 360)
    for x, y in ((2, 2), (357, 2), (2, 357), (357, 357), (60, 180)):
        assert image.getpixel((x, y))[3] == 0, (x, y, image.getpixel((x, y)))
    red = image.getpixel((180, 180))
    assert red[3] == 255 and abs(red[0] - 220) <= 16 and red[1] <= 46 and red[2] <= 46, red
    assert 'Body text stays' in page.extract_text()
    assert (await editor.workspace.afile_bytes(bind_native_workspace(editor.workspace, context.scope), context.source_file.path))[0] == content


@pytest.mark.anyio
@pytest.mark.parametrize('bake, moved', [({'kind': 'cutout', 'tolerance': 101}, False), ({'kind': 'cutout'}, False), ({'kind': 'cutout', 'tolerance': 30}, True)])
async def test_cutout_rejects_invalid_tolerance_and_moving(tmp_path, bake, moved):
    content = _source()
    editor, context, _ = await _fixture(tmp_path, content)
    target = await _target(editor, context)
    x1, y1, x2, y2 = target['rect']
    with pytest.raises(ReportingError):
        await editor.preview(context, expected_sha256=context.source_file.sha256, operations=_operation(context, target, bake, [x1 + 10, y1, x2 + 10, y2] if moved else None))
