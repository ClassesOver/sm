"""PictureDialogs三种位图结果复用原生图片writer，真实ZIP关系与像素身份回读。"""
import base64
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from docx import Document
from docx.shared import Inches
from lxml import etree
from PIL import Image

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def image_bytes(size=(80, 60), mode='RGB'):
    image = Image.new(mode, size, 'white'); image.paste('blue', (20, 15, 60, 45))
    stream = BytesIO(); image.save(stream, 'PNG'); return stream.getvalue()


def source():
    doc = Document(); doc.add_paragraph('正文保持').runs[0].bold = True
    doc.add_picture(BytesIO(image_bytes()), width=Inches(2))
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '表格保持'
    doc.add_picture(BytesIO(image_bytes((90, 70))), width=Inches(1))
    doc.add_paragraph('Trailing paragraph'); stream = BytesIO(); doc.save(stream); return stream.getvalue()


def test_picture_dialog_result_retargets_only_selected_picture_and_keeps_drawing():
    original = source(); model = inspect_docx(original); target = next(b for b in model['blocks'] if b['type'] == 'image')
    data = image_bytes((40, 30)); image = {'base64': base64.b64encode(data).decode(), 'mime': 'image/png', 'widthPx': 40, 'heightPx': 30}
    output = patch_docx(original, [{'kind': 'replaceImage', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'], 'expectedImageSha256': target['imageSha256'], 'image': image}])
    actual = inspect_docx(output); images = [b for b in actual['blocks'] if b['type'] == 'image']
    assert images[0]['imageSha256'] != target['imageSha256'] and images[0]['imageEditable'] is True
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'a': 'http://schemas.openxmlformats.org/drawingml/2006/main', 'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
    with ZipFile(BytesIO(original)) as before, ZipFile(BytesIO(output)) as after:
        a = etree.fromstring(before.read('word/document.xml')); b = etree.fromstring(after.read('word/document.xml'))
        first = b.xpath('//a:blip', namespaces=ns)[0]; rid = first.get('{%s}embed' % ns['r'])
        rels = etree.fromstring(after.read('word/_rels/document.xml.rels')); target_path = next(x.get('Target') for x in rels if x.get('Id') == rid)
        assert after.read(str(PurePosixPath('word') / target_path)) == data
        assert b.xpath('//a:blip', namespaces=ns)[1].get('{%s}embed' % ns['r']) == a.xpath('//a:blip', namespaces=ns)[1].get('{%s}embed' % ns['r'])
        for tree in [a, b]: tree.xpath('//a:blip', namespaces=ns)[0].set('{%s}embed' % ns['r'], 'NORMALIZED')
        assert etree.tostring(a, method='c14n') == etree.tostring(b, method='c14n')
        for name in before.namelist():
            if name not in ['word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml', 'docProps/core.xml', 'word/media/image1.png']:
                assert before.read(name) == after.read(name), name


def test_picture_replacement_checks_bytes_dimensions_and_source_hash():
    import pytest
    original = source(); target = next(b for b in inspect_docx(original)['blocks'] if b['type'] == 'image')
    data = image_bytes((40, 30))
    operation = {'kind': 'replaceImage', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'], 'expectedImageSha256': target['imageSha256'], 'image': {'base64': base64.b64encode(data).decode(), 'mime': 'image/png', 'widthPx': 40, 'heightPx': 30}}
    for patch in [{'expectedImageSha256': '0' * 64}, {'expectedObjectSha256': '0' * 64}, {'image': {**operation['image'], 'widthPx': 41}}, {'image': {**operation['image'], 'mime': 'image/jpeg'}}, {'image': {**operation['image'], 'base64': 'YQ=='}}]:
        with pytest.raises(ValueError): patch_docx(original, [{**operation, **patch}])
    with pytest.raises(ValueError): patch_docx(original, [operation, operation])


def test_picture_cutout_transparency_and_changed_aspect_are_saved_as_real_pixels():
    original = source(); target = next(b for b in inspect_docx(original)['blocks'] if b['type'] == 'image')
    transparent = Image.new('RGBA', (40, 20), (0, 0, 0, 0)); transparent.paste((0, 0, 255, 255), (10, 5, 30, 15))
    stream = BytesIO(); transparent.save(stream, 'PNG'); data = stream.getvalue()
    output = patch_docx(original, [{'kind': 'replaceImage', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'], 'expectedImageSha256': target['imageSha256'], 'image': {'base64': base64.b64encode(data).decode(), 'mime': 'image/png', 'widthPx': 40, 'heightPx': 20}}])
    actual = next(b for b in inspect_docx(output)['blocks'] if b['type'] == 'image')
    assert actual['imageWidthPx'] == 192 and actual['imageHeightPx'] == 96
    with ZipFile(BytesIO(output)) as package:
        saved = next(package.read(name) for name in package.namelist() if name.startswith('word/media/') and package.read(name) == data)
        image = Image.open(BytesIO(saved)); assert image.size == (40, 20) and image.mode == 'RGBA'
        assert image.getpixel((0, 0))[3] == 0 and image.getpixel((20, 10)) == (0, 0, 255, 255)


def test_picture_source_gif_replacement_and_protected_readonly():
    import pytest
    original = source(); target = next(b for b in inspect_docx(original)['blocks'] if b['type'] == 'image')
    stream = BytesIO(); Image.new('RGB', (32, 16), 'blue').save(stream, 'GIF'); data = stream.getvalue()
    operation = {'kind': 'replaceImage', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'], 'expectedImageSha256': target['imageSha256'], 'image': {'base64': base64.b64encode(data).decode(), 'mime': 'image/gif', 'widthPx': 32, 'heightPx': 16}}
    assert next(b for b in inspect_docx(patch_docx(original, [operation]))['blocks'] if b['type'] == 'image')['imageEditable'] is True
    with ZipFile(BytesIO(original)) as package:
        output = BytesIO()
        with ZipFile(output, 'w') as changed:
            for name in package.namelist():
                content = package.read(name)
                if name == 'word/settings.xml': content = content.replace(b'</w:settings>', b'<w:documentProtection w:edit="readOnly" w:enforcement="1"/></w:settings>')
                changed.writestr(name, content)
    protected = output.getvalue(); protected_target = next(b for b in inspect_docx(protected)['blocks'] if b['type'] == 'image')
    assert protected_target['imageEditable'] is False
    with pytest.raises(ValueError): patch_docx(protected, [{**operation, 'blockId': protected_target['blockId'], 'expectedObjectSha256': protected_target['expectedObjectSha256']}])
