"""真实经典批注夹具与独立 ZIP/lxml 回读；生产代码不引用。"""
import base64, hashlib, json, posixpath, sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from lxml import etree as E
from pptx import Presentation
from pptx.util import Inches

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/package/2006/relationships'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
COMMENT_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.comments+xml'
AUTHORS_TYPE = 'application/vnd.openxmlformats-officedocument.presentationml.commentAuthors+xml'
TEXTS = ['第一页正文：批注不得改动 <&> 中文', '第二页正文：原始来源定位😀']
COMMENTS = [
    [(0, 1, '爱丽丝原批注😀 <&> "引号"'), (1, 1, '鲍勃同索引批注 & 保留')],
    [(0, 2, '第二页最后一条批注 <保留身份>')],
]

def rewrite(data, changes):
    stream = BytesIO()
    with ZipFile(BytesIO(data)) as original, ZipFile(stream, 'w', ZIP_DEFLATED) as target:
        for name in original.namelist():
            target.writestr(name, changes.get(name, original.read(name)))
        for name, value in changes.items():
            if name not in original.namelist(): target.writestr(name, value)
    return stream.getvalue()

def encoded(root): return E.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)

def create(variant='classic'):
    deck = Presentation()
    for text in TEXTS:
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(7), Inches(1.5)).text = text
    stream = BytesIO(); deck.save(stream); data = stream.getvalue()
    with ZipFile(BytesIO(data)) as z:
        changes = {}
        authors = E.Element('{'+P+'}cmAuthorLst', nsmap={'p': P})
        for author_id, name, initials, last in [(0, 'Alice 爱丽丝', 'AL', '2'), (1, 'Bob 鲍勃', 'BB', '1')]:
            E.SubElement(authors, '{'+P+'}cmAuthor', id=str(author_id), name=name, initials=initials, lastIdx=last, clrIdx=str(author_id))
        changes['ppt/commentAuthors.xml'] = encoded(authors)
        pres_rels = E.fromstring(z.read('ppt/_rels/presentation.xml.rels'))
        E.SubElement(pres_rels, '{'+R+'}Relationship', Id='rIdFixtureAuthors', Type=REL+'commentAuthors', Target='commentAuthors.xml')
        E.SubElement(pres_rels, '{'+R+'}Relationship', Id='rIdFixtureOpaque', Type='urn:fixture:preserved', Target='../custom/preserved.xml')
        changes['ppt/_rels/presentation.xml.rels'] = encoded(pres_rels)
        types = E.fromstring(z.read('[Content_Types].xml'))
        E.SubElement(types, '{'+CT+'}Override', PartName='/ppt/commentAuthors.xml', ContentType=AUTHORS_TYPE)
        E.SubElement(types, '{'+CT+'}Override', PartName='/custom/preserved.xml', ContentType='application/xml')
        for index, records in enumerate(COMMENTS, 1):
            comments = E.Element('{'+P+'}cmLst', nsmap={'p': P})
            for author_id, idx, text in records:
                item = E.SubElement(comments, '{'+P+'}cm', authorId=str(author_id), idx=str(idx), dt='2026-11-11T01:02:03Z')
                E.SubElement(item, '{'+P+'}pos', x='10', y='10')
                E.SubElement(item, '{'+P+'}text').text = text
            part = 'ppt/comments/comment'+str(index)+'.xml'
            changes[part] = encoded(comments)
            rels_path = 'ppt/slides/_rels/slide'+str(index)+'.xml.rels'
            rels = E.fromstring(z.read(rels_path))
            E.SubElement(rels, '{'+R+'}Relationship', Id='rIdFixtureComment', Type=REL+'comments', Target='../comments/comment'+str(index)+'.xml')
            changes[rels_path] = encoded(rels)
            E.SubElement(types, '{'+CT+'}Override', PartName='/'+part, ContentType=COMMENT_TYPE)
        if variant == 'modern':
            rels = E.fromstring(changes['ppt/slides/_rels/slide1.xml.rels'])
            E.SubElement(rels, '{'+R+'}Relationship', Id='rIdModernFixture', Type='http://schemas.microsoft.com/office/2018/10/relationships/comments', Target='../comments/modern1.xml')
            changes['ppt/slides/_rels/slide1.xml.rels'] = encoded(rels)
            changes['ppt/comments/modern1.xml'] = b'<p188:cmLst xmlns:p188="http://schemas.microsoft.com/office/powerpoint/2018/8/main"/>'
            E.SubElement(types, '{'+CT+'}Override', PartName='/ppt/comments/modern1.xml', ContentType='application/vnd.ms-powerpoint.comments+xml')
        elif variant == 'broken':
            comments = E.fromstring(changes['ppt/comments/comment1.xml']); comments[0].set('authorId', '999')
            changes['ppt/comments/comment1.xml'] = encoded(comments)
        elif variant != 'classic': raise ValueError(variant)
        changes['[Content_Types].xml'] = encoded(types)
        changes['custom/preserved.xml'] = '<opaque xmlns="urn:fixture:preserved" token="保持原字节">未知部件😀 &amp; 保全</opaque>'.encode()
    return rewrite(data, changes)

def readback(data):
    with ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        for name in z.namelist():
            if name.endswith(('.xml', '.rels')): E.fromstring(z.read(name))
        authors = {int(a.get('id')): dict(a.attrib) for a in E.fromstring(z.read('ppt/commentAuthors.xml'))}
        slides=[]
        for index in range(1, 3):
            path='ppt/slides/slide'+str(index)+'.xml'; rels=E.fromstring(z.read('ppt/slides/_rels/slide'+str(index)+'.xml.rels'))
            refs=[r for r in rels if r.get('Type')==REL+'comments']; assert len(refs)<=1
            part=posixpath.normpath(posixpath.join('ppt/slides',refs[0].get('Target'))) if refs else None
            records=[]
            if part:
                for c in E.fromstring(z.read(part)):
                    records.append({'authorId':int(c.get('authorId')), 'idx':int(c.get('idx')), 'author':authors.get(int(c.get('authorId')),{}).get('name'), 'text':''.join(c.xpath('p:text/text()',namespaces={'p':P}))})
            slides.append({'path':path,'part':part,'comments':records,'bodySha256':hashlib.sha256(z.read(path)).hexdigest()})
        return {'authors':authors,'slides':slides,'parts':z.namelist(),'opaqueSha256':hashlib.sha256(z.read('custom/preserved.xml')).hexdigest(),'sha256':hashlib.sha256(data).hexdigest(),'allXmlValid':True}

def verify(source, output, expected):
    a=readback(source);b=readback(output)
    assert a['opaqueSha256']==b['opaqueSha256']
    assert [s['bodySha256'] for s in a['slides']]==[s['bodySha256'] for s in b['slides']]
    assert b['slides'][1]['comments']==[] and b['slides'][1]['part'] is None
    assert 'ppt/comments/comment2.xml' not in b['parts']
    records=b['slides'][0]['comments'];assert not any(c['authorId']==0 and c['idx']==1 for c in records)
    kept=[c for c in records if c['authorId']==1 and c['idx']==1];assert len(kept)==1 and kept[0]['text']==COMMENTS[0][1][2]
    added=[c for c in records if c['author']=='用户'];assert [c['text'] for c in added]==expected
    assert len(records)==1+len(expected)
    with ZipFile(BytesIO(source)) as before, ZipFile(BytesIO(output)) as after:
        types=E.fromstring(after.read('[Content_Types].xml'));assert not any(t.get('PartName')=='/ppt/comments/comment2.xml' for t in types)
        changed=[n for n in before.namelist() if n not in after.namelist() or before.read(n)!=after.read(n)]
        allowed={'[Content_Types].xml','ppt/commentAuthors.xml','ppt/comments/comment1.xml','ppt/comments/comment2.xml','ppt/slides/_rels/slide2.xml.rels'}
        assert set(changed)<=allowed,changed
        for n in before.namelist():
            if n not in allowed: assert before.read(n)==after.read(n),n
    body=lambda data:[[s.text for s in slide.shapes if s.has_text_frame] for slide in Presentation(BytesIO(data)).slides]
    assert body(source)==body(output)==[[text] for text in TEXTS]
    return {'source':a,'output':b,'changedParts':changed,'unrelatedPartsByteExact':True,'sameIdxOtherAuthorPreserved':True,'lastCommentPartRelationshipOverrideRemoved':True,'pythonPptxBodyUnchanged':True}

if __name__=='__main__':
    p=json.load(sys.stdin);mode=p['mode']
    if mode=='create':
        data=create(p.get('variant','classic'));Path(p['path']).write_bytes(data)
        print(json.dumps({'bytes':base64.b64encode(data).decode(),'readback':readback(data)},ensure_ascii=False))
    elif mode=='readback':print(json.dumps(readback(Path(p['path']).read_bytes()),ensure_ascii=False))
    elif mode=='verify':print(json.dumps(verify(Path(p['source']).read_bytes(),Path(p['output']).read_bytes(),p['expected']),ensure_ascii=False))
    else:
        from smart_reporting.report_editor.native_office import inspect_office,patch_office
        data=Path(p['path']).read_bytes()
        if mode=='patch':
            data=patch_office('pptx',data,p['operations']);Path(p['output']).write_bytes(data)
        elif mode=='render':
            from smart_reporting.report_editor.slides_render import render_pptx_tree
            if p.get('operations'):data=patch_office('pptx',data,p['operations'])
            print(json.dumps(render_pptx_tree(data)));sys.exit(0)
        elif mode!='inspect':raise ValueError(mode)
        model = {**inspect_office('pptx', data), 'sha256': hashlib.sha256(data).hexdigest()}
        print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':model},ensure_ascii=False))
