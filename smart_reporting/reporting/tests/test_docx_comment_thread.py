"""Validate comment thread actions through the Python bridge and raw DOCX."""
from io import BytesIO
from zipfile import ZipFile

from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_reply import NS, W, W15, modern_source
from smart_reporting.reporting.tests.test_docx_comment_text_host import isolated_bundled_engine


def test_comment_thread_reopens_then_deletes_without_changing_body_text(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    data = modern_source()
    model = docx_native.inspect_docx(data)['commentThreads']
    root = next(target for target in model['targets'] if target['parentId'] is None)
    identity = ('sourceId', 'targetId', 'expectedCommentsSha256', 'expectedObjectSha256')
    reopen = {**{key: root[key] for key in identity}, 'kind': 'resolveComment', 'done': False}
    opened = docx_native.patch_docx(data, [reopen])
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(opened)) as after:
        assert [name for name in before.namelist() if before.read(name) != after.read(name)] == ['word/commentsExtended.xml']
        extended = etree.fromstring(after.read('word/commentsExtended.xml'))
        assert extended[0].get(f'{{{W15}}}done') in ('0', 'false')
        assert extended[0].get('{urn:preserved}keep') == 'root'
    root = next(target for target in docx_native.inspect_docx(opened)['commentThreads']['targets'] if target['parentId'] is None)
    delete = {**{key: root[key] for key in identity}, 'kind': 'deleteComment'}
    with pytest.raises(ValueError):
        docx_native.patch_docx(data, [delete])
    removed = docx_native.patch_docx(opened, [delete])
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(removed)) as after:
        def body_text(package):
            return etree.fromstring(package.read('word/document.xml')).xpath('.//w:body//w:t/text()', namespaces=NS)
        assert body_text(after) == body_text(before)
        document = etree.fromstring(after.read('word/document.xml'))
        for name in ('commentRangeStart', 'commentRangeEnd', 'commentReference'):
            assert not document.findall(f'.//{{{W}}}{name}')
        assert after.read('custom/preserved.xml') == before.read('custom/preserved.xml')
    assert docx_native.inspect_docx(removed)['commentThreads']['targets'] == []
