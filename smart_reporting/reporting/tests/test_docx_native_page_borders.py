"""页面边框经真实 Python/Node（打包后的固定引擎）保存后，以独立 python-docx / ZIP+lxml 回读确认。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.enum.section import WD_SECTION
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import NS, W, isolated_bundled_engine


def _source() -> bytes:
    doc = Document()
    doc.add_paragraph('第一节正文')
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('第二节正文')
    stream = BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _borders(content: bytes):
    with ZipFile(BytesIO(content)) as archive:
        root = etree.fromstring(archive.read('word/document.xml'))
    result = []
    for sect in root.xpath('.//w:sectPr', namespaces=NS):
        node = sect.find(f'{{{W}}}pgBorders')
        if node is None:
            result.append(None)
            continue
        sides = {etree.QName(child).localname: {key.split('}')[1]: value for key, value in child.attrib.items()} for child in node}
        result.append({'attrs': {key.split('}')[1]: value for key, value in node.attrib.items()}, 'sides': sides})
    return result


def _layout(section, values):
    return {'kind': 'setSectionLayout', 'sectionId': section['sectionId'], 'expectedSectionSha256': section['expectedSectionSha256'], 'values': values}


def test_whole_document_and_section_borders_roundtrip(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    sections = docx_native.inspect_docx(source)['sections']
    assert [section['settings']['pageBorder'] for section in sections] == [False, False]
    shadow = {'offsetFrom': 'text', 'spacePt': 4, 'widthPt': 3, 'color': '1F4E79',
              'sides': {name: {'val': 'single', 'widthPt': 3, 'spacePt': 4, 'color': '1F4E79', 'shadow': True} for name in ('top', 'left', 'bottom', 'right')}}
    saved = docx_native.patch_docx(source, [_layout(section, {'pageBorder': True, 'pageBorderProps': shadow}) for section in sections])
    borders = _borders(saved)
    assert len(borders) == 2
    for border in borders:
        assert border['attrs'] == {'offsetFrom': 'text'}
        assert set(border['sides']) == {'top', 'left', 'bottom', 'right'}
        assert border['sides']['top'] == {'val': 'single', 'sz': '24', 'space': '4', 'color': '1F4E79', 'shadow': '1'}
    assert [p.text for p in Document(BytesIO(saved)).paragraphs] == [p.text for p in Document(BytesIO(source)).paragraphs]
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved)) as after:
        changed = {name for name in before.namelist() if before.read(name) != after.read(name)}
        assert changed <= {'word/document.xml', 'docProps/core.xml'}
    reopened = docx_native.inspect_docx(saved)['sections']
    assert [section['settings']['pageBorder'] for section in reopened] == [True, True]
    # 只改第 2 节为“方框(单实线)”，第 1 节保持
    boxed = docx_native.patch_docx(saved, [_layout(reopened[1], {'pageBorder': True, 'pageBorderProps': None})])
    first, second = _borders(boxed)
    assert first['sides']['top']['shadow'] == '1'
    assert second['attrs'] == {'offsetFrom': 'page'} and second['sides']['top'] == {'val': 'single', 'sz': '4', 'space': '24', 'color': 'auto'}
    cleared = docx_native.patch_docx(boxed, [_layout(section, {'pageBorder': False}) for section in docx_native.inspect_docx(boxed)['sections']])
    assert _borders(cleared) == [None, None]


@pytest.mark.parametrize('values', [
    {'pageBorder': True, 'pageBorderProps': {'offsetFrom': 'text', 'spacePt': 4, 'widthPt': 1.3, 'sides': {'top': {'val': 'single', 'widthPt': 1.3, 'spacePt': 4}}}},
    {'pageBorder': True, 'pageBorderProps': {'offsetFrom': 'text', 'spacePt': 4, 'widthPt': 1, 'sides': {'top': {'val': 'laser', 'widthPt': 1, 'spacePt': 4}}}},
    {'pageBorder': False, 'pageBorderProps': {'offsetFrom': 'text', 'spacePt': 4, 'widthPt': 1, 'sides': {'top': {'val': 'single', 'widthPt': 1, 'spacePt': 4}}}},
    {'pageBorder': 'yes'},
])
def test_invalid_page_border_values_are_rejected(tmp_path, monkeypatch, values):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = _source()
    section = docx_native.inspect_docx(source)['sections'][0]
    with pytest.raises(ValueError):
        docx_native.patch_docx(source, [_layout(section, values)])
