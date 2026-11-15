"""Native inspect/patch wiring for a real header revision and strict isolation."""
from io import BytesIO
from zipfile import ZipFile
import pytest
from docx import Document
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_comment_text_host import isolated_bundled_engine


def test_native_header_revision_identity_save_and_reopen(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    doc = Document()
    doc.add_paragraph('Body remains')
    doc.sections[0].header.paragraphs[0].text = 'Header remains'
    out = BytesIO()
    doc.save(out)
    source = BytesIO()
    with ZipFile(BytesIO(out.getvalue())) as before, ZipFile(source, 'w') as after:
        for entry in before.infolist():
            raw = before.read(entry.filename)
            if entry.filename == 'word/header1.xml':
                raw = raw.replace(b'</w:p>', b'<w:del w:id="71" w:author="Ann"><w:r><w:delText>Removed</w:delText></w:r></w:del></w:p>', 1)
            after.writestr(entry, raw)
    content = source.getvalue()
    model = inspect_docx(content)
    target = model['storyRevisions']['targets'][0]
    operation = {'kind': 'resolveStoryRevision', **{k: target[k] for k in ('targetId', 'expectedPartSha256', 'expectedWrapperSha256')}, 'action': 'reject'}
    result = patch_docx(content, [operation])
    assert inspect_docx(result)['storyRevisions']['targets'] == []
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(result)) as after:
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        root = etree.fromstring(after.read('word/header1.xml'))
        assert not root.xpath('//w:del', namespaces=ns)
        assert ''.join(root.xpath('//w:t/text()', namespaces=ns)) == 'Header remainsRemoved'
        for name in before.namelist():
            if name not in {'word/header1.xml', 'docProps/core.xml'} and not name.endswith('/'):
                assert before.read(name) == after.read(name)
    with pytest.raises(ValueError):
        patch_docx(content, [operation, {'kind': 'replaceParagraph', 'blockId': model['blocks'][0]['blockId'], 'text': 'Unauthorized combination'}])
