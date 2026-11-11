"""真实 Python/Node 引用保存；以独立 ZIP/XML 检查域及非目标内容。"""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import NS, W, isolated_bundled_engine


def reference_source():
    document = Document()
    document.add_paragraph('可信目标😀')
    document.add_paragraph('引用位置')
    document.add_paragraph('题注锚点')
    stream = BytesIO()
    document.save(stream)
    output = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as before, ZipFile(output, 'w', ZIP_DEFLATED) as after:
        for name in before.namelist():
            data = before.read(name)
            if name == 'word/document.xml':
                root = etree.fromstring(data)
                paragraph = root.find('w:body/w:p', NS)
                start = etree.Element(f'{{{W}}}bookmarkStart', {f'{{{W}}}id': '9', f'{{{W}}}name': 'TrustedTarget'})
                end = etree.Element(f'{{{W}}}bookmarkEnd', {f'{{{W}}}id': '9'})
                paragraph.insert(0, start)
                paragraph.append(end)
                data = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
            after.writestr(name, data)
        after.writestr('customXml/reference-opaque.xml', '<keep xmlns="urn:reference-test">😀</keep>')
    return output.getvalue()


def only_document_changed(before, after):
    with ZipFile(BytesIO(before)) as original, ZipFile(BytesIO(after)) as saved:
        assert original.namelist() == saved.namelist()
        assert [name for name in original.namelist() if original.read(name) != saved.read(name)] == ['word/document.xml']
        for name in saved.namelist():
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(saved.read(name))
        return etree.fromstring(saved.read('word/document.xml'))


def test_native_ref_inserts_real_field_and_rejects_stale_or_mixed_intent(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = reference_source()
    model = docx_native.inspect_docx(source)['crossReferences']
    target = next(t for t in model['targets'] if t['text'] == '引用位置')
    bookmark = next(b for b in model['bookmarks'] if b['name'] == 'TrustedTarget')
    operation = {'kind': 'insertCrossReference', 'sourceId': model['sourceId'], 'bookmarkId': bookmark['bookmarkId'],
                 'targetId': target['targetId'], 'expectedParagraphSha256': target['expectedParagraphSha256'], 'offset': 2}
    saved = docx_native.patch_docx(source, [operation])
    root = only_document_changed(source, saved)
    paragraphs = root.findall('w:body/w:p', NS)
    assert ''.join(paragraphs[0].xpath('.//w:t/text()', namespaces=NS)) == '可信目标😀'
    assert ''.join(paragraphs[1].xpath('.//w:t/text()', namespaces=NS)) == '引用可信目标😀位置'
    instructions = paragraphs[1].xpath('.//w:instrText/text()', namespaces=NS)
    assert len(instructions) == 1 and instructions[0].strip().split()[:2] == ['REF', 'TrustedTarget']
    assert paragraphs[1].xpath('.//w:fldChar[@w:fldCharType="begin"]', namespaces=NS)
    assert paragraphs[1].xpath('.//w:fldChar[@w:fldCharType="end"]', namespaces=NS)
    assert docx_native.inspect_docx(saved)['sourceSha256'] != model['sourceSha256']
    with pytest.raises(ValueError):
        docx_native.patch_docx(saved, [operation])
    with pytest.raises(ValueError):
        docx_native.patch_docx(source, [operation, {'kind': 'deleteParagraph', 'blockId': 'foreign'}])


def test_native_caption_seq_numbers_are_derived_from_saved_source(tmp_path, monkeypatch):
    isolated_bundled_engine(tmp_path, monkeypatch)
    source = reference_source()
    model = docx_native.inspect_docx(source)
    target = next(b for b in model['blocks'] if b['text'] == '题注锚点')
    operation = {'kind': 'insertCaption', 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'],
                 'position': 'after', 'label': '图', 'text': '标题 & <😀>'}
    saved = docx_native.patch_docx(source, [operation])
    root = only_document_changed(source, saved)
    fields = root.xpath('.//w:instrText/text()', namespaces=NS)
    assert len(fields) == 1 and fields[0].strip().split()[:2] == ['SEQ', '图']
    assert ''.join(root.xpath('.//w:body/w:p[last()]//w:t/text()', namespaces=NS)) == '图 1 标题 & <😀>'
    reopened = docx_native.inspect_docx(saved)
    target = next(b for b in reopened['blocks'] if b['text'] == '题注锚点')
    with pytest.raises(ValueError):
        docx_native.patch_docx(source, [{**operation, 'number': 99}])
    with pytest.raises(ValueError):
        docx_native.patch_docx(saved, [{**operation, 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256']}])
