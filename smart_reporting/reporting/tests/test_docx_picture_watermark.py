"""完整水印图片页复用原生writer，独立ZIP验证实际图片及正文保持。"""
from io import BytesIO
import base64
import hashlib
from zipfile import ZipFile

from docx import Document
from PIL import Image
import pytest

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_native_watermark import _source


def _picture():
    stream = BytesIO(); Image.new('RGB', (12, 8), 'blue').save(stream, 'PNG')
    return {'image': {'base64': base64.b64encode(stream.getvalue()).decode(), 'mime': 'image/png', 'widthPx': 12, 'heightPx': 8}, 'scale': 150, 'washout': False}


def test_picture_watermark_native_save_and_reopen_preserves_body_and_header_text():
    source = _source('页眉原文'); model = inspect_docx(source)['watermark']; spec = _picture()
    output = patch_docx(source, [{'kind': 'setWatermark', 'expectedHeadersSha256': model['expectedHeadersSha256'], 'watermark': spec}])
    actual = inspect_docx(output)['watermark']
    assert actual['picture'] is True and actual['text'] is None
    assert actual['pictureSpec'] == spec
    assert [p.text for p in Document(BytesIO(output)).paragraphs] == ['水印正文', 'Second paragraph']
    with ZipFile(BytesIO(output)) as package:
        headers = [(name, package.read(name)) for name in package.namelist() if name.startswith('word/header') and name.endswith('.xml')]
        assert any(b'WordPictureWatermark1' in xml for _, xml in headers)
        assert all('页眉原文' in xml.decode() for _, xml in headers)
        assert any(hashlib.sha256(package.read(name)).hexdigest() == hashlib.sha256(base64.b64decode(spec['image']['base64'])).hexdigest() for name in package.namelist() if name.startswith('word/media/'))


def test_picture_watermark_auto_washout_replace_and_remove():
    source = _source('页眉原文')
    spec = _picture(); spec.pop('scale'); spec['washout'] = True
    model = inspect_docx(source)['watermark']
    picture = patch_docx(source, [{'kind': 'setWatermark', 'expectedHeadersSha256': model['expectedHeadersSha256'], 'watermark': spec}])
    reopened = inspect_docx(picture)['watermark']
    assert reopened['pictureSpec'] == spec
    text = patch_docx(picture, [{'kind': 'setWatermark', 'expectedHeadersSha256': reopened['expectedHeadersSha256'], 'watermark': {'text': '已替换'}}])
    model = inspect_docx(text)['watermark']
    assert model['text'] == '已替换' and not model['picture']
    removed = patch_docx(text, [{'kind': 'setWatermark', 'expectedHeadersSha256': model['expectedHeadersSha256'], 'watermark': None}])
    final = inspect_docx(removed)['watermark']
    assert final['text'] is None and not final['picture']


def test_picture_watermark_writeback_does_not_depend_on_image_key_order():
    source = _source(); model = inspect_docx(source)['watermark']; spec = _picture()
    spec['image'] = dict(reversed(list(spec['image'].items())))
    output = patch_docx(source, [{'kind': 'setWatermark', 'expectedHeadersSha256': model['expectedHeadersSha256'], 'watermark': spec}])
    assert inspect_docx(output)['watermark']['pictureSpec'] == spec


@pytest.mark.parametrize('change', ['bytes', 'mime', 'dimensions', 'scale', 'washout', 'anchor'])
def test_picture_watermark_rejects_invalid_image_or_stale_anchor(change):
    source = _source(); model = inspect_docx(source)['watermark']; spec = _picture()
    if change == 'bytes': spec['image']['base64'] = 'aW52YWxpZA=='
    elif change == 'mime': spec['image']['mime'] = 'image/jpeg'
    elif change == 'dimensions': spec['image']['widthPx'] = 13
    elif change == 'scale': spec['scale'] = 0
    elif change == 'washout': spec['washout'] = 'false'
    anchor = '0' * 64 if change == 'anchor' else model['expectedHeadersSha256']
    with pytest.raises(ValueError, match='docx_watermark_anchor_invalid' if change == 'anchor' else 'docx_watermark_operation_invalid'):
        patch_docx(source, [{'kind': 'setWatermark', 'expectedHeadersSha256': anchor, 'watermark': spec}])
