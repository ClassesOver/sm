"""显式 fixture scope 的真实 Python/Node 公式读写与独立 ZIP/XML 回读。"""
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

from docx import Document
from lxml import etree as E
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
NS = {'w': W, 'm': M}


def facts(data):
    with ZipFile(BytesIO(data)) as z:
        for name in z.namelist():
            if name.endswith(('.xml', '.rels')):
                E.fromstring(z.read(name))
        d = E.fromstring(z.read('word/document.xml'))
        return {'allXmlValid': True,
                'bodyTexts': [''.join(p.xpath('.//w:t/text()', namespaces=NS)) for p in d.findall('w:body/w:p', NS)],
                'tableTexts': d.xpath('//w:tbl//w:t/text()', namespaces=NS),
                'sdtTexts': d.xpath('//w:sdtContent//w:t/text()', namespaces=NS),
                'inlineCount': len(d.xpath('//m:oMath[not(parent::m:oMathPara)]', namespaces=NS)),
                'displayCount': len(d.findall('.//m:oMathPara', NS)),
                'fractionCount': len(d.findall('.//m:f', NS)),
                'sqrtCount': len(d.findall('.//m:rad', NS))}


p = json.load(sys.stdin)
if p['mode'] == 'create':
    document = Document()
    a = document.add_paragraph('Body A😀B tail')
    a.paragraph_format.keep_with_next = True
    a.runs[0].bold = True
    document.add_paragraph('Gallery anchor')
    table = document.add_table(rows=1, cols=1)
    table.cell(0, 0).text = 'Table A😀B tail'
    document.sections[0].header.paragraphs[0].text = 'Preserved header'
    stream = BytesIO()
    document.save(stream)
    output = BytesIO()
    with ZipFile(BytesIO(stream.getvalue())) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for name in source.namelist():
            data = source.read(name)
            if name == 'word/document.xml':
                d = E.fromstring(data)
                body = d.find('w:body', NS)
                sdt = E.fromstring(('<w:sdt xmlns:w="' + W + '"><w:sdtPr><w:tag w:val="retain-equation-sdt"/></w:sdtPr><w:sdtContent><w:p><w:r><w:t>SDT anchor</w:t></w:r></w:p></w:sdtContent></w:sdt>').encode())
                body.insert(len(body) - 1, sdt)
                old = E.fromstring(('<w:p xmlns:w="' + W + '" xmlns:m="' + M + '"><m:oMath><m:unknown><m:r><m:t>legacy</m:t></m:r></m:unknown></m:oMath></w:p>').encode())
                body.insert(len(body) - 1, old)
                data = E.tostring(d, xml_declaration=True, encoding='UTF-8', standalone=True)
            target.writestr(name, data)
    data = output.getvalue()
    Path(p['output']).write_bytes(data)
elif p['mode'] == 'patch':
    data = patch_docx(Path(p['source']).read_bytes(), p['operations'])
    Path(p['output']).write_bytes(data)
elif p['mode'] == 'verify':
    with ZipFile(p['source']) as a, ZipFile(p['output']) as b:
        assert a.namelist() == b.namelist()
        changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
        assert changed == ['word/document.xml'], changed
        d = E.fromstring(b.read('word/document.xml'))
        assert d.xpath('//m:unknown/m:r/m:t/text()', namespaces=NS) == ['legacy']
        assert d.xpath('//w:sdtPr/w:tag/@w:val', namespaces=NS) == ['retain-equation-sdt']
        assert d.find('w:body/w:p/w:pPr/w:keepNext', NS) is not None
    print(json.dumps({'changedParts': changed, **facts(Path(p['output']).read_bytes())}))
    sys.exit()
else:
    data = Path(p['source']).read_bytes()
print(json.dumps({'bytes': base64.b64encode(data).decode(), 'model': inspect_docx(data), 'facts': facts(data)}))
