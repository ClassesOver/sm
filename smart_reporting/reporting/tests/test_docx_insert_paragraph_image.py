"""真实 DOCX 引擎读写契约：insertParagraphImage（Word 图片粘贴的保存协议）。

走真实 edit-docx 桥（dist/tsx），产物用 lxml 独立回读，不依赖引擎类型：
media part 字节、关系、document.xml 内联 drawing、[Content_Types] 默认项，
以及非目标部件逐字节保留。
"""
from __future__ import annotations

import base64
import io
import zipfile

import pytest
from docx import Document
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'pic': 'http://schemas.openxmlformats.org/drawingml/2006/picture',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
    'ct': 'http://schemas.openxmlformats.org/package/2006/content-types',
}

PNG_BYTES = bytes.fromhex(
    '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
    '0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082'
)
JPEG_BYTES = bytes.fromhex('ffd8ffe000104a46494600010100000100010000ffd9')


@pytest.fixture
def source() -> bytes:
    document = Document()
    document.add_paragraph('锚点段落')
    document.add_paragraph('尾随段落')
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = '保留'
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def paragraph_anchor(content: bytes) -> dict:
    block = next(
        block for block in inspect_docx(content)['blocks']
        if block['type'] == 'paragraph' and block['text'] == '锚点段落'
    )
    assert block['editable'] is True
    return block


def image_operation(anchor: dict, **overrides) -> dict:
    operation = {
        'kind': 'insertParagraphImage', 'blockId': anchor['blockId'],
        'expectedObjectSha256': anchor['expectedObjectSha256'], 'position': 'before',
        'image': {'mime': 'image/png', 'base64': base64.b64encode(PNG_BYTES).decode(), 'widthPx': 100, 'heightPx': 80},
    }
    operation.update(overrides)
    return operation


def drawings(edited: bytes) -> list[etree._Element]:
    document = etree.fromstring(zipfile.ZipFile(io.BytesIO(edited)).read('word/document.xml'))
    return document.findall('.//w:drawing', NS)


def test_image_paste_writes_media_relationship_and_inline_drawing(source):
    anchor = paragraph_anchor(source)
    edited = patch_docx(source, [image_operation(anchor)])

    # document.xml: 恰好一个新增内联 drawing，位于锚点段落之前（position before）
    assert len(drawings(edited)) == 1
    drawing = drawings(edited)[0]
    assert drawing.find('.//wp:inline', NS) is not None
    assert drawing.find('.//wp:anchor', NS) is None
    embed = drawing.find('.//a:blip', NS).get(f'{{{NS["r"]}}}embed')
    extent = drawing.find('.//wp:extent', NS)
    assert extent.get('cx') == str(100 * 9525) and extent.get('cy') == str(80 * 9525)

    # 关系：新增 image 关系，目标 media part 字节与粘贴位图逐字节一致
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        rels = etree.fromstring(archive.read('word/_rels/document.xml.rels'))
        relationship = next(rel for rel in rels.findall('rel:Relationship', NS) if rel.get('Id') == embed)
        assert relationship.get('Type') == 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/image'
        target = relationship.get('Target')
        assert target.startswith('media/')
        assert archive.read(f'word/{target}') == PNG_BYTES
        names = set(archive.namelist())

    # 正文：图片段落 + 锚点段落文字原样
    document = etree.fromstring(zipfile.ZipFile(io.BytesIO(edited)).read('word/document.xml'))
    texts = [''.join(node.itertext()) for node in document.findall('.//w:body/w:p', NS)]
    assert texts[0] == ''
    assert texts[1] == '锚点段落'

    # [Content_Types].xml 声明 png 默认类型
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        types = etree.fromstring(archive.read('[Content_Types].xml'))
        assert any(default.get('Extension') == 'png' for default in types.findall('ct:Default', NS))

    # 非目标部件逐字节保留（core.xml 的 dcterms:modified 属保存时间戳，允许变化）
    with zipfile.ZipFile(io.BytesIO(source)) as before, zipfile.ZipFile(io.BytesIO(edited)) as after:
        assert names >= set(before.namelist())
        for name in before.namelist():
            if name in {'word/document.xml', 'docProps/core.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'}:
                continue
            assert before.read(name) == after.read(name), name


def test_image_paste_after_position_lands_between_paragraphs(source):
    anchor = paragraph_anchor(source)
    edited = patch_docx(source, [image_operation(anchor, position='after')])
    document = etree.fromstring(zipfile.ZipFile(io.BytesIO(edited)).read('word/document.xml'))
    texts = [''.join(node.itertext()) for node in document.findall('.//w:body/w:p', NS)]
    assert texts == ['锚点段落', '', '尾随段落']


def test_image_paste_accepts_jpeg_magic_and_binds_bytes(source):
    anchor = paragraph_anchor(source)
    edited = patch_docx(source, [image_operation(
        anchor, image={'mime': 'image/jpeg', 'base64': base64.b64encode(JPEG_BYTES).decode(), 'widthPx': 640, 'heightPx': 480})])
    drawing = drawings(edited)[0]
    embed = drawing.find('.//a:blip', NS).get(f'{{{NS["r"]}}}embed')
    with zipfile.ZipFile(io.BytesIO(edited)) as archive:
        rels = etree.fromstring(archive.read('word/_rels/document.xml.rels'))
        target = next(rel for rel in rels.findall('rel:Relationship', NS) if rel.get('Id') == embed).get('Target')
        assert archive.read(f'word/{target}') == JPEG_BYTES
        types = etree.fromstring(archive.read('[Content_Types].xml'))
        assert any(default.get('Extension') == 'jpg' for default in types.findall('ct:Default', NS))


@pytest.mark.parametrize('overrides', [
    {'image': {'mime': 'image/gif', 'base64': 'R0lGODlhAQABAAAAACw=', 'widthPx': 1, 'heightPx': 1}},
    {'image': {'mime': 'image/png', 'base64': base64.b64encode(JPEG_BYTES).decode(), 'widthPx': 1, 'heightPx': 1}},
    {'image': {'mime': 'image/png', 'base64': '!!!', 'widthPx': 1, 'heightPx': 1}},
    {'image': {'mime': 'image/png', 'base64': base64.b64encode(PNG_BYTES).decode(), 'widthPx': 0, 'heightPx': 1}},
    {'image': {'mime': 'image/png', 'base64': base64.b64encode(PNG_BYTES).decode(), 'widthPx': 10001, 'heightPx': 1}},
    {'image': {'mime': 'image/png', 'base64': base64.b64encode(PNG_BYTES).decode(), 'widthPx': 1, 'heightPx': 1, 'wrap': 'front'}},
    {'position': 'middle'},
    {'expectedObjectSha256': '0' * 64},
])
def test_image_paste_rejects_out_of_contract_payloads(source, overrides):
    anchor = paragraph_anchor(source)
    with pytest.raises(ValueError, match='docx_'):
        patch_docx(source, [image_operation(anchor, **overrides)])


def test_image_paste_rejects_bytes_over_cap(source):
    anchor = paragraph_anchor(source)
    oversized = b'\x89PNG\r\n\x1a\n' + b'\x00' * (8 * 1024 * 1024 + 1 - 8)
    with pytest.raises(ValueError, match='docx_'):
        patch_docx(source, [image_operation(anchor, image={
            'mime': 'image/png', 'base64': base64.b64encode(oversized).decode(), 'widthPx': 1, 'heightPx': 1})])
