"""书签经真实 Python/Node 保存后，以独立 ZIP/XML 读取确认范围及保全。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import NS, W, isolated_bundled_engine


def test_native_bookmark_exact_range_save_reopen_and_delete(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    doc = Document()
    doc.add_paragraph('Alpha 😀 Beta')
    doc.add_paragraph('Second paragraph')
    stream = BytesIO()
    doc.save(stream)
    source = stream.getvalue()
    model = docx_native.inspect_docx(source)['bookmarks']
    first, second = model['targets'][:2]
    operation = {'kind': 'createBookmark', 'sourceId': model['sourceId'], 'name': 'ExactRange', 'ranges': [
        {'targetId': first['targetId'], 'expectedParagraphSha256': first['expectedParagraphSha256'], 'from': 6, 'to': 13, 'text': '😀 Beta'},
        {'targetId': second['targetId'], 'expectedParagraphSha256': second['expectedParagraphSha256'], 'from': 0, 'to': 6, 'text': 'Second'},
    ]}
    saved = docx_native.patch_docx(source, [operation])
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(saved)) as after:
        assert before.namelist() == after.namelist()
        assert [name for name in before.namelist() if before.read(name) != after.read(name)] == ['word/document.xml']
        root = etree.fromstring(after.read('word/document.xml'))
        start = root.xpath('.//w:bookmarkStart', namespaces=NS)
        end = root.xpath('.//w:bookmarkEnd', namespaces=NS)
        assert len(start) == len(end) == 1
        assert start[0].get(f'{{{W}}}name') == 'ExactRange'
        assert start[0].get(f'{{{W}}}id') == end[0].get(f'{{{W}}}id')
        assert start[0].getparent() is root.xpath('.//w:body/w:p', namespaces=NS)[0]
        assert end[0].getparent() is root.xpath('.//w:body/w:p', namespaces=NS)[1]
        assert ''.join(root.xpath('.//w:t/text()', namespaces=NS)) == 'Alpha 😀 BetaSecond paragraph'
    reopened = docx_native.inspect_docx(saved)['bookmarks']
    assert [r['text'] for r in reopened['bookmarks'][0]['ranges']] == ['😀 Beta', 'Second']
    removed = docx_native.patch_docx(saved, [{'kind': 'deleteBookmark', 'sourceId': reopened['sourceId'], 'bookmarkId': reopened['bookmarks'][0]['bookmarkId']}])
    assert docx_native.inspect_docx(removed)['bookmarks']['bookmarks'] == []
    with pytest.raises(ValueError, match='docx_engine_failed'):
        docx_native.patch_docx(saved, [operation])
    with pytest.raises(ValueError, match='bookmark_batch_conflict'):
        docx_native.patch_docx(source, [operation, {'kind': 'deleteParagraph', 'blockId': 'foreign'}])
