"""文字水印经真实 Python/Node 保存后，以独立 python-docx / ZIP+lxml 回读确认。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import isolated_bundled_engine


def _source(header: str | None = None) -> bytes:
    doc = Document()
    doc.add_paragraph('水印正文')
    doc.add_paragraph('Second paragraph')
    if header is not None:
        doc.sections[0].header.paragraphs[0].text = header
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _headers(content: bytes) -> dict[str, str]:
    with ZipFile(BytesIO(content)) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist() if name.startswith('word/header') and name.endswith('.xml')}


def test_text_watermark_set_restyle_remove_with_independent_readback(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source('页眉原文')
    model = docx_native.inspect_docx(source)['watermark']
    assert model['text'] is None and model['editable'] is True
    saved = docx_native.patch_docx(source, [{'kind': 'setWatermark', 'expectedHeadersSha256': model['expectedHeadersSha256'], 'watermark': {'text': '严禁复制'}}])
    headers = _headers(saved)
    assert any('string="严禁复制"' in xml and 'Watermarks' in xml for xml in headers.values())
    assert all('页眉原文' in xml for xml in headers.values() if 'string="严禁复制"' in xml)
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved)) as after:
        changed = {name for name in after.namelist() if not name.endswith('/') and (name not in before.namelist() or before.read(name) != after.read(name))}
    # 固定引擎主保存路径照常更新 core.xml；水印只改页眉部件，必要时连带 document.xml 的节引用。
    assert changed - {'docProps/core.xml', 'word/document.xml', '[Content_Types].xml', 'word/_rels/document.xml.rels'} <= set(headers)
    document = Document(BytesIO(saved))
    assert [p.text for p in document.paragraphs] == ['水印正文', 'Second paragraph']
    assert document.sections[0].header.paragraphs[-1].text == '页眉原文' or '页眉原文' in [p.text for p in document.sections[0].header.paragraphs]
    reopened = docx_native.inspect_docx(saved)['watermark']
    assert reopened['text'] == '严禁复制'
    styled = docx_native.patch_docx(saved, [{'kind': 'setWatermark', 'expectedHeadersSha256': reopened['expectedHeadersSha256'],
        'watermark': {'text': 'CONFIDENTIAL', 'colorHex': '1F4E79', 'opacity': 0.4, 'diagonal': False, 'italic': True, 'fontFamily': 'Arial'}}])
    xml = next(xml for xml in _headers(styled).values() if 'CONFIDENTIAL' in xml)
    assert 'fillcolor="#1F4E79"' in xml and '<v:fill opacity="0.4"/>' in xml and 'rotation:315' not in xml and 'font-style:italic' in xml
    removed = docx_native.patch_docx(styled, [{'kind': 'setWatermark', 'expectedHeadersSha256': docx_native.inspect_docx(styled)['watermark']['expectedHeadersSha256'], 'watermark': None}])
    assert not any('<v:textpath' in xml for xml in _headers(removed).values())
    assert docx_native.inspect_docx(removed)['watermark']['text'] is None


@pytest.mark.parametrize('patch', [
    {'watermark': None}, {'watermark': {'text': ''}}, {'watermark': {'text': 'x', 'colorHex': '#FF0000'}},
    {'watermark': {'text': 'x', 'sizePt': 72}}, {'expectedHeadersSha256': 'f' * 64}, {'extra': 1},
])
def test_invalid_or_stale_watermark_is_rejected(tmp_path, monkeypatch, patch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    model = docx_native.inspect_docx(source)['watermark']
    operation = {'kind': 'setWatermark', 'expectedHeadersSha256': model['expectedHeadersSha256'], 'watermark': {'text': '草稿'}, **patch}
    with pytest.raises(ValueError):
        docx_native.patch_docx(source, [operation])
