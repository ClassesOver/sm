"""页面颜色经真实 Python/Node 保存后，以独立 python-docx / ZIP+lxml 回读确认。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import NS, W, isolated_bundled_engine


def _source() -> bytes:
    doc = Document()
    doc.add_paragraph('页面颜色正文')
    doc.add_paragraph('Second paragraph')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _background(content: bytes):
    with ZipFile(BytesIO(content)) as archive:
        root = etree.fromstring(archive.read('word/document.xml'))
        settings = etree.fromstring(archive.read('word/settings.xml'))
    nodes = root.xpath('./w:background', namespaces=NS)
    return (nodes[0].get(f'{{{W}}}color') if nodes else None, len(nodes),
            bool(settings.xpath('./w:displayBackgroundShape', namespaces=NS)))


def test_page_color_set_change_remove_with_independent_readback(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    model = docx_native.inspect_docx(source)['pageColor']
    assert model['color'] is None and model['editable'] is True
    saved = docx_native.patch_docx(source, [{'kind': 'setPageColor', 'expectedBackgroundSha256': model['expectedBackgroundSha256'], 'color': 'FFE699'}])
    assert _background(saved) == ('FFE699', 1, True)
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved)) as after:
        changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
        # 固定引擎主保存路径照常更新 core.xml 的 cp:revision / dcterms:modified；其余部件不动。
        assert set(changed) <= {'word/document.xml', 'word/settings.xml', 'docProps/core.xml'}
        assert 'word/document.xml' in changed and 'word/settings.xml' in changed
    assert [p.text for p in Document(BytesIO(saved)).paragraphs] == ['页面颜色正文', 'Second paragraph']
    reopened = docx_native.inspect_docx(saved)['pageColor']
    assert reopened['color'] == 'FFE699'
    removed = docx_native.patch_docx(saved, [{'kind': 'setPageColor', 'expectedBackgroundSha256': reopened['expectedBackgroundSha256'], 'color': None}])
    assert _background(removed)[:2] == (None, 0)
    assert docx_native.inspect_docx(removed)['pageColor']['color'] is None


@pytest.mark.parametrize('patch', [{'color': 'ffe699'}, {'color': '#FFE699'}, {'color': None}, {'expectedBackgroundSha256': 'f' * 64}, {'extra': 1}])
def test_invalid_or_stale_page_color_is_rejected(tmp_path, monkeypatch, patch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    model = docx_native.inspect_docx(source)['pageColor']
    operation = {'kind': 'setPageColor', 'expectedBackgroundSha256': model['expectedBackgroundSha256'], 'color': 'FFE699', **patch}
    with pytest.raises(ValueError):
        docx_native.patch_docx(source, [operation])
