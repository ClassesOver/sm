"""已有批注回复：原 bytes 身份、共享范围、真实父关系与增量 XML 保全。"""
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED

from lxml import etree as E
import pytest

from smart_reporting.reporting.delivery import docx_native
from smart_reporting.reporting.tests.test_docx_comment_text_host import isolated_bundled_engine, source, W, R

W14 = 'http://schemas.microsoft.com/office/word/2010/wordml'
W15 = 'http://schemas.microsoft.com/office/word/2012/wordml'
EX_REL = 'http://schemas.microsoft.com/office/2011/relationships/commentsExtended'
EX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml'
NS = {'w': W, 'w14': W14, 'w15': W15}


@pytest.fixture
def engine(tmp_path, monkeypatch):
    return isolated_bundled_engine(tmp_path, monkeypatch)


def rewrite(content, changes):
    out = BytesIO()
    with ZipFile(BytesIO(content)) as original, ZipFile(out, 'w', ZIP_DEFLATED) as edited:
        for name in original.namelist():
            edited.writestr(name, changes.get(name, original.read(name)))
        for name, value in changes.items():
            if name not in original.namelist():
                edited.writestr(name, value)
    return out.getvalue()


def modern_source():
    data = source()
    with ZipFile(BytesIO(data)) as z:
        comments = z.read('word/comments.xml').decode().replace('<w:comments ', f'<w:comments xmlns:w14="{W14}" ').replace('<w:p>', '<w:p w14:paraId="AA000001">', 1)
        reply = '<w:comment w:id="2" w:author="Bob"><w:p w14:paraId="AA000002"><w:r><w:t>Existing reply</w:t></w:r></w:p></w:comment>'
        comments = comments.replace('</w:comments>', reply + '</w:comments>')
        document = z.read('word/document.xml').decode().replace('<w:commentRangeStart w:id="1"/>', '<w:commentRangeStart w:id="1"/><w:commentRangeStart w:id="2"/>').replace('<w:commentRangeEnd w:id="1"/>', '<w:commentRangeEnd w:id="2"/><w:r><w:commentReference w:id="2"/></w:r><w:commentRangeEnd w:id="1"/>')
        extended = f'<w15:commentsEx xmlns:w15="{W15}" xmlns:x="urn:preserved"><w15:commentEx w15:paraId="AA000001" w15:done="1" x:keep="root"/><w15:commentEx w15:paraId="AA000002" w15:paraIdParent="AA000001" w15:done="1"/><x:opaque x:token="do-not-rebuild"/></w15:commentsEx>'
        rels = z.read('word/_rels/document.xml.rels').decode().replace('</Relationships>', f'<Relationship Id="rId21" Type="{EX_REL}" Target="commentsExtended.xml"/></Relationships>')
        types = z.read('[Content_Types].xml').decode().replace('</Types>', f'<Override PartName="/word/commentsExtended.xml" ContentType="{EX_TYPE}"/></Types>')
    return rewrite(data, {'word/comments.xml': comments, 'word/document.xml': document, 'word/commentsExtended.xml': extended, 'word/_rels/document.xml.rels': rels, '[Content_Types].xml': types, 'word/people.xml': '<w15:people xmlns:w15="'+W15+'"><w15:person w15:author="Alice"/></w15:people>', 'custom/preserved.xml': '<x:payload xmlns:x="urn:preserved" paraId="00000002" durableId="00000003">unchanged</x:payload>'})


def operation(target, text='回复中文😀', client='reply-1'):
    return {'kind': 'replyComment', **{k: target[k] for k in ('sourceId', 'targetId', 'expectedCommentsSha256', 'expectedObjectSha256')}, 'clientId': client, 'author': '用户', 'date': '2026-11-11T01:02:03Z', 'text': text}


def selected(document, comment_id):
    active = False
    text = ''
    for n in document.iter():
        if n.tag == f'{{{W}}}commentRangeStart' and n.get(f'{{{W}}}id') == comment_id:
            active = True
        elif n.tag == f'{{{W}}}commentRangeEnd' and n.get(f'{{{W}}}id') == comment_id:
            active = False
        elif active and n.tag == f'{{{W}}}t':
            text += n.text or ''
    return text


def test_reply_creates_real_parent_relation_and_shared_exact_anchor(tmp_path, engine):
    data = source()
    model = docx_native.inspect_docx(data)['commentReplies']
    assert model['readOnlyReason'] is None
    parent = model['targets'][0]
    assert parent['canReply'] is True and parent['parentId'] is None
    edits = [operation(parent), operation(parent, '第二条回复', 'reply-2')]
    output = docx_native.patch_docx(data, edits)
    (tmp_path/'source.docx').write_bytes(data)
    (tmp_path/'saved.docx').write_bytes(output)
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        assert after.testzip() is None
        for name in after.namelist():
            if name.endswith(('.xml', '.rels')):
                E.fromstring(after.read(name))
        doc = E.fromstring(after.read('word/document.xml'))
        comments = E.fromstring(after.read('word/comments.xml'))
        ex = E.fromstring(after.read('word/commentsExtended.xml'))
        parent_para = comments[0][-1].get(f'{{{W14}}}paraId')
        assert parent_para
        assert comments[0].xpath('.//w:t/text()', namespaces=NS) == ['Original note']
        assert [c.get(f'{{{W}}}author') for c in comments[1:]] == ['用户', '用户']
        assert [''.join(c.xpath('.//w:t/text()', namespaces=NS)) for c in comments[1:]] == ['回复中文😀', '第二条回复']
        for child in list(comments)[1:]:
            cid = child.get(f'{{{W}}}id')
            pid = child[-1].get(f'{{{W14}}}paraId')
            linked = ex.xpath('w15:commentEx[@w15:paraId=$pid]', namespaces=NS, pid=pid)
            assert len(linked) == 1 and linked[0].get(f'{{{W15}}}paraIdParent') == parent_para
            assert selected(doc, cid) == selected(doc, '1') == 'Anchor text'
        rels = E.fromstring(after.read('word/_rels/document.xml.rels'))
        assert len([n for n in rels if n.get('Type') == EX_REL and n.get('Target') == 'commentsExtended.xml']) == 1
        changed = [n for n in before.namelist() if before.read(n) != after.read(n)]
        assert set(changed) == {'word/document.xml','word/comments.xml','word/_rels/document.xml.rels','[Content_Types].xml'}
        evidence = {'changedParts': changed, 'addedParts': sorted(set(after.namelist())-set(before.namelist())), 'parentParaId':parent_para, 'sharedAnchor':'Anchor text', 'allXmlValid':True}
    reopened = docx_native.inspect_docx(output)['commentReplies']
    assert [t['parentId'] for t in reopened['targets']] == [None, '1', '1']
    assert [t['canReply'] for t in reopened['targets']] == [True, False, False]
    (tmp_path/'zip-lxml.json').write_text(json.dumps(evidence,ensure_ascii=False),encoding='utf8')
    with pytest.raises(ValueError, match='docx_engine_failed'):
        docx_native.patch_docx(output, edits)


def test_reply_preserves_existing_modern_records_people_unknown_xml_and_root_anchor(tmp_path, engine):
    data = modern_source()
    model = docx_native.inspect_docx(data)['commentReplies']
    assert [t['parentId'] for t in model['targets']] == [None, '1']
    assert model['targets'][1]['canReply'] is False
    output = docx_native.patch_docx(data, [operation(model['targets'][0])])
    (tmp_path/'modern-source.docx').write_bytes(data); (tmp_path/'modern-saved.docx').write_bytes(output)
    with ZipFile(BytesIO(data)) as a, ZipFile(BytesIO(output)) as b:
        changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
        assert set(changed) == {'word/document.xml','word/comments.xml','word/commentsExtended.xml'}
        old_ex = a.read('word/commentsExtended.xml').decode()
        assert old_ex.removesuffix('</w15:commentsEx>') in b.read('word/commentsExtended.xml').decode()
        old_comments = E.fromstring(a.read('word/comments.xml'))
        comments = E.fromstring(b.read('word/comments.xml'))
        for original, retained in zip(old_comments, comments):
            assert E.tostring(original) == E.tostring(retained)
        assert b.read('word/people.xml') == a.read('word/people.xml')
        assert b.read('custom/preserved.xml') == a.read('custom/preserved.xml')
        doc = E.fromstring(b.read('word/document.xml'))
        assert selected(doc,'1') == selected(doc,'2') == selected(doc,comments[-1].get(f'{{{W}}}id')) == 'Anchor text'
    assert docx_native.inspect_docx(output)['commentReplies']['targets'][-1]['parentId'] == '1'


def test_reply_rejects_forged_stale_nonroot_and_ambiguous_parent_atomically(tmp_path, engine):
    data = modern_source(); model = docx_native.inspect_docx(data)['commentReplies']; edit = operation(model['targets'][0])
    for bad in ({**edit,'sourceId':'f'*64},{**edit,'expectedObjectSha256':'0'*64},operation(model['targets'][1]),{**edit,'text':'\ud800'}):
        with pytest.raises(ValueError):
            docx_native.patch_docx(data, [edit,bad])
    with pytest.raises(ValueError):
        docx_native.patch_docx(data,[edit,{'kind':'createComment'}])
    with ZipFile(BytesIO(data)) as z:
        old = z.read('word/commentsExtended.xml').decode()
    for raw in (old.replace('w15:paraId="AA000002"','w15:paraId="AA000001"'),old.replace('w15:paraIdParent="AA000001"','w15:paraIdParent="DEADBEEF"')):
        malformed=rewrite(data,{'word/commentsExtended.xml':raw})
        inspected=docx_native.inspect_docx(malformed)['commentReplies']
        assert inspected['readOnlyReason']
        with pytest.raises(ValueError):
            docx_native.patch_docx(malformed,[edit])


def test_reply_refuses_relationship_alias_to_extended_metadata(engine):
    data = modern_source()
    with ZipFile(BytesIO(data)) as z:
        rels = z.read('word/_rels/document.xml.rels').decode().replace('</Relationships>', '<Relationship Id="rId22" Type="urn:foreign-metadata" Target="commentsExtended.xml"/></Relationships>')
    ambiguous = rewrite(data, {'word/_rels/document.xml.rels': rels})
    model = docx_native.inspect_docx(ambiguous)['commentReplies']
    assert model['readOnlyReason'] == 'docx_comment_reply_extended_part_identity'


def test_reply_uses_partial_cross_paragraph_parent_range_including_empty_paragraph(tmp_path, engine):
    from smart_reporting.reporting.tests.test_docx_comment_text_host import ANCHOR
    data = source()
    anchor = ('<w:p><w:r><w:t>Before </w:t></w:r><w:commentRangeStart w:id="1"/>'
              '<w:r><w:rPr><w:b/></w:rPr><w:t>First</w:t></w:r></w:p><w:p/>'
              '<w:p><w:r><w:t>End</w:t></w:r><w:commentRangeEnd w:id="1"/>'
              '<w:r><w:commentReference w:id="1"/></w:r><w:r><w:t> after</w:t></w:r></w:p>')
    with ZipFile(BytesIO(data)) as z:
        data = rewrite(data, {'word/document.xml':z.read('word/document.xml').decode().replace(ANCHOR,anchor)})
    target = docx_native.inspect_docx(data)['commentReplies']['targets'][0]
    assert target['canReply'] is True
    reply = operation(target, '第一段 <&>😀\n第二段')
    output = docx_native.patch_docx(data,[reply])
    with ZipFile(BytesIO(output)) as z:
        document = E.fromstring(z.read('word/document.xml'))
        comments = E.fromstring(z.read('word/comments.xml'))
        assert selected(document,'1') == selected(document,comments[-1].get(f'{{{W}}}id')) == 'FirstEnd'
        assert document.xpath('.//w:body/w:p[2]/w:r',namespaces=NS) == []
        assert comments[-1].xpath('w:p//w:t/text()',namespaces=NS) == ['第一段 <&>😀','第二段']
    assert docx_native.inspect_docx(output)['commentReplies']['targets'][-1]['parentId'] == '1'
    (tmp_path/'cross-source.docx').write_bytes(data);(tmp_path/'cross-saved.docx').write_bytes(output)
