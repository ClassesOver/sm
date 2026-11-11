import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from docx import Document
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_comment_reply import NS, W, W15, modern_source, rewrite

p=json.load(sys.stdin)
if p['mode']=='create':
    if p['case']=='toc':
        d=Document()
        d.add_paragraph('目录前言')
        d.add_heading('业务概览 & 总览',level=1)
        d.add_paragraph('正文不要被改写')
        d.add_heading('区域说明',level=2)
        buf=BytesIO();d.save(buf); data=buf.getvalue()
    else:
        data=modern_source()
        with ZipFile(BytesIO(data)) as z:
            original=z.read('word/commentsExtended.xml')
        changed=original.replace(b'w15:done="1"',b'w15:done="0"',1)
        assert changed!=original
        data=rewrite(data,{'word/commentsExtended.xml':changed})
elif p['mode']=='inspect':
    data=Path(p['source']).read_bytes()
else:
    data=patch_docx(Path(p['source']).read_bytes(),p['operations'])
if p.get('output'): Path(p['output']).write_bytes(data)
with ZipFile(BytesIO(data)) as z:
    assert z.testzip() is None
    for n in z.namelist():
        if n.endswith(('.xml','.rels')): etree.fromstring(z.read(n))
    xml=etree.fromstring(z.read('word/document.xml'))
    facts={'text':xml.xpath('.//w:body//w:t/text()',namespaces=NS),
           'tocFields': [x.strip() for x in xml.xpath('.//w:instrText/text()',namespaces=NS) if x.strip().startswith('TOC')],
           'dirtyFields': xml.xpath('.//w:fldChar[@w:fldCharType="begin"]/@w:dirty',namespaces=NS),
           'commentAnchors':{name:xml.xpath('.//w:'+name+'/@w:id',namespaces=NS) for name in ('commentRangeStart','commentRangeEnd','commentReference')}}
    if 'word/commentsExtended.xml' in z.namelist():
        x=etree.fromstring(z.read('word/commentsExtended.xml'))
        facts['done']=[e.get(f'{{{W15}}}done') for e in x]
    if p['mode']=='patch':
        with ZipFile(p['source']) as before:
            facts['changedParts']=sorted(n for n in set(z.namelist())|set(before.namelist()) if n not in z.namelist() or n not in before.namelist() or z.read(n)!=before.read(n))
print(json.dumps({'bytes':base64.b64encode(data).decode(),'model':inspect_docx(data),'facts':facts},ensure_ascii=False))
