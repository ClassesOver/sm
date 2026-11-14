"""简单正文修订宿主：真实 ZIP、授权快照及独立 XML 回读。"""
from io import BytesIO
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from lxml import etree
import pytest

from smart_reporting.reporting.delivery import docx_native

ENGINE = Path(__file__).resolve().parents[1] / 'doc_engine'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
INS = '<w:ins w:id="7" w:author="甲"><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve"> 新😀 </w:t></w:r></w:ins>'
DEL = '<w:del w:id="7" w:author="乙"><w:r><w:rPr><w:i/></w:rPr><w:delText>旧文</w:delText></w:r></w:del>'
PARA = '<w:p w:rsidR="AABBCCDD"><w:bookmarkStart w:id="2" w:name="keep"/><w:r><w:t>保留</w:t></w:r>' + INS + DEL + '<w:bookmarkEnd w:id="2"/></w:p>'


def rewrite(content, transform):
    out = BytesIO()
    with ZipFile(BytesIO(content)) as old, ZipFile(out, 'w', ZIP_DEFLATED) as new:
        for name in old.namelist():
            data = old.read(name)
            new.writestr(name, transform(name, data))
    return out.getvalue()


def source():
    doc = Document()
    doc.add_paragraph('preceding')
    doc.add_paragraph('placeholder')
    doc.add_paragraph('following')
    out = BytesIO()
    doc.save(out)
    return rewrite(out.getvalue(), lambda n, b: b.replace(b'<w:p><w:r><w:t>placeholder</w:t></w:r></w:p>', PARA.encode()) if n == 'word/document.xml' else b)


def run_source(engine, script, request):
    return subprocess.run([str(ENGINE / 'node_modules/.bin/tsx'), str(ENGINE / 'bridge' / f'{script}.ts'), str(request)], cwd=ENGINE, capture_output=True, text=True, timeout=120)


@pytest.fixture(autouse=True)
def source_bridge(monkeypatch):
    # 避免共享目录旧 dist 掩盖源码；仍经过完整 Python allowlist / identity receipt。
    monkeypatch.setattr(docx_native, 'run_bridge', run_source)


def anchor(content):
    return docx_native.inspect_docx(content)['blocks'][1]


def operation(block, index=0, action='accept'):
    target = block['reviewTargets'][index]
    return {'kind': 'resolveTextRevision', **{k: target[k] for k in ('blockId', 'expectedObjectSha256', 'revisionId')}, 'action': action}


@pytest.mark.parametrize('index,action,replacement', [
    (0, 'accept', INS[INS.index('>') + 1:-len('</w:ins>')]),
    (0, 'reject', ''), (1, 'accept', ''),
    (1, 'reject', DEL[DEL.index('>') + 1:-len('</w:del>')].replace('w:delText', 'w:t')),
])
def test_four_decisions_preserve_actual_zip_parts(index, action, replacement):
    content = source()
    block = anchor(content)
    assert block['editable'] is False
    assert block['revisionReadOnlyReason'] is None
    assert len(block['reviewTargets']) == 2
    result = docx_native.patch_docx(content, [operation(block, index, action)])
    with ZipFile(BytesIO(content)) as old, ZipFile(BytesIO(result)) as new:
        assert new.testzip() is None
        assert {n for n in old.namelist() if not n.endswith('/')} == {n for n in new.namelist() if not n.endswith('/')}
        for name in old.namelist():
            if name != 'word/document.xml':
                assert old.read(name) == new.read(name), name
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(new.read(name))
        actual = etree.fromstring(new.read('word/document.xml')).find('w:body', NS)[1]
        expected = etree.fromstring(PARA.replace(INS if index == 0 else DEL, replacement).replace('<w:p ', f'<w:p xmlns:w="{W}" ', 1).encode())
        assert etree.tostring(actual, method='c14n', exclusive=True) == etree.tostring(expected, method='c14n', exclusive=True)
    assert len(anchor(result)['reviewTargets']) == 1


def test_same_snapshot_merge_and_shifted_output_index():
    content = source()
    model = docx_native.inspect_docx(content)
    block, preceding = model['blocks'][1], model['blocks'][0]
    ops = [operation(block), operation(block, 1, 'reject'), {'kind': 'insertParagraph', 'blockId': preceding['blockId'], 'expectedObjectSha256': preceding['expectedObjectSha256'], 'position': 'before', 'text': 'inserted'}]
    result = docx_native.patch_docx(content, ops)
    with ZipFile(BytesIO(result)) as archive:
        body = etree.fromstring(archive.read('word/document.xml')).find('w:body', NS)
        assert ''.join(body[2].itertext()) == '保留 新😀 旧文'
        assert not body[2].xpath('.//w:ins|.//w:del|.//w:delText', namespaces=NS)
        assert body[2].get(f'{{{W}}}rsidR') == 'AABBCCDD'


def test_recorded_text_revision_uses_authorized_user_and_reopens_real_package():
    original = '<w:p w:rsidR="AABBCCDD"><w:r><w:rPr><w:b/></w:rPr><w:t>前旧后</w:t></w:r></w:p>'
    content = rewrite(source(), lambda name, data: data.replace(PARA.encode(), original.encode()) if name == 'word/document.xml' else data)
    block = anchor(content)
    operation = {'kind': 'recordTextRevision', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'from': 1, 'to': 2, 'text': '新'}
    result = docx_native.patch_docx(content, [operation], revision_author='authenticated-user-17')
    with ZipFile(BytesIO(result)) as archive:
        assert archive.testzip() is None
        paragraph = etree.fromstring(archive.read('word/document.xml')).find('w:body', NS)[1]
        inserted = paragraph.find('w:ins', NS)
        deleted = paragraph.find('w:del', NS)
        assert inserted is not None and inserted.get(f'{{{W}}}author') == 'authenticated-user-17'
        assert deleted is not None and deleted.get(f'{{{W}}}author') == 'authenticated-user-17'
        assert inserted.get(f'{{{W}}}date') and inserted.get(f'{{{W}}}date') == deleted.get(f'{{{W}}}date')
        assert ''.join(inserted.itertext()) == '新'
        assert ''.join(deleted.itertext()) == '旧'
        assert paragraph.get(f'{{{W}}}rsidR') == 'AABBCCDD'
        assert len({inserted.get(f'{{{W}}}id'), deleted.get(f'{{{W}}}id')}) == 2
        reopened = docx_native.inspect_docx(result)['blocks'][1]
        assert sorted((item['type'], item['sourceRange']['text'], item['author']) for item in reopened['reviewTargets']) == [('deletion', '旧', 'authenticated-user-17'), ('insertion', '新', 'authenticated-user-17')]
    with pytest.raises(ValueError):
        docx_native.patch_docx(content, [{**operation, 'author': 'forged'}], revision_author='authenticated-user-17')
    deletion = {**operation, 'from': 1, 'to': 3, 'text': ''}
    removed = docx_native.patch_docx(content, [deletion], revision_author='authenticated-user-17')
    with ZipFile(BytesIO(removed)) as archive:
        paragraph = etree.fromstring(archive.read('word/document.xml')).find('w:body', NS)[1]
        assert paragraph.find('w:ins', NS) is None
        deleted = paragraph.find('w:del', NS)
        assert deleted is not None and deleted.get(f'{{{W}}}author') == 'authenticated-user-17'
        assert ''.join(deleted.itertext()) == '旧后'


def test_track_revisions_setting_toggles_and_reopens_without_changing_other_parts():
    content = source()
    model = docx_native.inspect_docx(content)
    assert model['trackRevisions'] is False
    operation = {'kind': 'setTrackRevisions', 'sourceSha256': model['sourceSha256'], 'enabled': True}
    enabled = docx_native.patch_docx(content, [operation])
    assert docx_native.inspect_docx(enabled)['trackRevisions'] is True
    with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(enabled)) as after:
        for name in before.namelist():
            if name not in {'word/settings.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name
        settings = etree.fromstring(after.read('word/settings.xml'))
        assert len(settings.xpath('./w:trackRevisions', namespaces=NS)) == 1
        assert len(settings.xpath('./w:doNotTrackMoves', namespaces=NS)) == len(etree.fromstring(before.read('word/settings.xml')).xpath('./w:doNotTrackMoves', namespaces=NS))
    enabled_model = docx_native.inspect_docx(enabled)
    disabled = docx_native.patch_docx(enabled, [{'kind': 'setTrackRevisions', 'sourceSha256': enabled_model['sourceSha256'], 'enabled': False}])
    assert docx_native.inspect_docx(disabled)['trackRevisions'] is False
    with ZipFile(BytesIO(disabled)) as archive:
        settings = etree.fromstring(archive.read('word/settings.xml'))
        assert not settings.xpath('./w:trackRevisions', namespaces=NS)


@pytest.mark.parametrize('mutate', [
    lambda op: {**op, 'expectedObjectSha256': '0' * 64},
    lambda op: {**op, 'revisionId': 'foreign'},
    lambda op: {**op, 'action': 'all'},
    lambda op: {**op, 'xml': '<w:p/>'},
    lambda op: {**op, 'blockId': 'foreign'},
    lambda op: op,
    lambda op: {**op, 'action': 'reject'},
])
def test_late_invalid_revision_does_not_write_output(tmp_path, mutate):
    content = source()
    block = anchor(content)
    op = operation(block)
    input_path, output, request = tmp_path / 'in.docx', tmp_path / 'out.docx', tmp_path / 'request.json'
    input_path.write_bytes(content)
    request.write_text(json.dumps({'kind': 'patch', 'input': str(input_path), 'output': str(output), 'operations': [op, mutate(op)]}))
    completed = run_source('doc', 'edit-docx', request)
    assert completed.returncode != 0
    assert not output.exists()
    assert input_path.read_bytes() == content


@pytest.mark.parametrize('kind,values', [
    ('replaceParagraph', {'text': 'forged'}), ('formatParagraph', {'style': {'bold': True}}),
    ('patchParagraphRuns', {'runs': [{'text': 'forged'}]}),
    ('setParagraphStyle', {'styleId': 'Normal'}), ('deleteParagraph', {}),
    ('insertParagraph', {'position': 'after', 'text': 'insert'}),
    ('insertSectionBreak', {'type': 'nextPage'}),
    ('insertNote', {'noteKind': 'footnote', 'offset': 0, 'text': 'note'}),
])
def test_same_paragraph_conflicts_rejected(kind, values):
    content = source()
    block = anchor(content)
    other = {'kind': kind, 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], **values}
    with pytest.raises(ValueError):
        docx_native.patch_docx(content, [operation(block), other])


@pytest.mark.parametrize('location', ['document', 'body', 'protected'])
def test_document_scope_and_protection_never_authorize_revision(location):
    content = source()
    source_block = anchor(content)
    def transform(name, data):
        if location == 'protected' and name == 'word/settings.xml':
            return data.replace(b'</w:settings>', b'<w:documentProtection w:enforcement="1" w:edit="readOnly"/></w:settings>')
        if name == 'word/document.xml':
            if location == 'document':
                return data.replace(W.encode(), b'urn:foreign')
            if location == 'body':
                return data.replace(b'<w:body>', b'<w:body xmlns:w="urn:foreign">')
        return data
    content = rewrite(content, transform)
    if location != 'protected':
        inspect_reason = 'docx_equation_namespace' if location == 'document' else 'docx_comment_source_namespace_rebound'
        with pytest.raises(ValueError, match=inspect_reason):
            docx_native.inspect_docx(content)
        with pytest.raises(ValueError, match='docx_revision_anchor_invalid'):
            docx_native.patch_docx(content, [{'kind': 'resolveTextRevision', 'blockId': source_block['blockId'], 'expectedObjectSha256': source_block['expectedObjectSha256'], 'revisionId': 'forged', 'action': 'accept'}])
        return
    block = anchor(content)
    assert block['reviewTargets'] == []
    assert block['revisionReadOnlyReason'] == 'docx_revision_protected'
    with pytest.raises(ValueError):
        docx_native.patch_docx(content, [{'kind': 'resolveTextRevision', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'revisionId': 'forged', 'action': 'accept'}])


@pytest.mark.parametrize('protection', [
    '<x:documentProtection xmlns:x="' + W + '" x:edit="readOnly" x:enforcement="1"/>',
    '<w:documentProtection w:edit="readOnly" w:enforcement="&#49;"/>',
])
def test_real_namespaced_protection_cannot_bypass_vendor_lexical_parser(protection):
    content = rewrite(source(), lambda n, b: b.replace(b'</w:settings>', protection.encode() + b'</w:settings>') if n == 'word/settings.xml' else b)
    block = anchor(content)
    assert block['reviewTargets'] == []
    assert block['revisionReadOnlyReason'] == 'docx_revision_protected'
    with pytest.raises(ValueError, match='revision_protected'):
        docx_native.patch_docx(content, [{'kind': 'resolveTextRevision', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'revisionId': 'forged', 'action': 'accept'}])


def test_source_ranges_bind_identical_wrappers_multirun_emoji_and_breaks():
    prefix = '<w:r><w:t>A😀</w:t><w:tab/><w:br/><w:br w:type="page"/><w:br w:type="column"/><w:br w:clear="none"/><w:cr/></w:r>'
    wrapper = '<w:ins w:id="9"><w:r><w:t xml:space="preserve"> 文😀 </w:t></w:r><w:r><w:t>&amp;尾</w:t></w:r></w:ins>'
    paragraph = '<w:p>' + prefix + wrapper + wrapper + '</w:p>'
    content = rewrite(source(), lambda n, b: b.replace(PARA.encode(), paragraph.encode()) if n == 'word/document.xml' else b)
    block = anchor(content)
    assert block['revisionReadOnlyReason'] is None
    first, second = block['reviewTargets']
    text = ' 文😀 &尾'
    start = len('A😀\t\n\f\v\x1e\n'.encode('utf-16-le')) // 2
    size = len(text.encode('utf-16-le')) // 2
    assert first['sourceRange'] == {'from': start, 'to': start + size, 'text': text}
    assert second['sourceRange'] == {'from': start + size, 'to': start + 2 * size, 'text': text}
    assert first['revisionId'] != second['revisionId']
    result = docx_native.patch_docx(content, [operation(block), operation(block, 1, 'reject')])
    assert anchor(result)['reviewTargets'] == []


def test_unknown_inline_mapping_and_nested_sdt_are_explicitly_readonly():
    opaque = rewrite(source(), lambda n, b: b.replace('<w:t>保留</w:t>'.encode(), '<w:drawing/><w:t>保留</w:t>'.encode()) if n == 'word/document.xml' else b)
    assert anchor(opaque)['revisionReadOnlyReason'] == 'docx_revision_projection_unsupported'
    assert anchor(opaque)['reviewTargets'] == []
    nested = rewrite(source(), lambda n, b: b.replace(PARA.encode(), ('<w:sdt><w:sdtContent>' + PARA + '</w:sdtContent></w:sdt>').encode()) if n == 'word/document.xml' else b)
    block = anchor(nested)
    assert block['reviewTargets'] == []
    assert block['revisionReadOnlyReason'] == 'docx_revision_block_unsupported'
