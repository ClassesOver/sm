"""显式夹具：真实原生读写、独立ZIP/XML验收；HTTP授权由smoke夹具模拟。"""
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
from docx import Document
from lxml import etree as E
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}
p = json.load(sys.stdin)
if p['mode'] == 'create':
    d = Document()
    a = d.add_paragraph('A😀B')
    a.paragraph_format.keep_with_next = True
    a.runs[0].bold = True
    d.add_paragraph('Tail')
    d.add_paragraph('Untouched')
    d.sections[0].header.paragraphs[0].text = 'Preserved header'
    f = BytesIO()
    d.save(f)
    data = f.getvalue()
    Path(p['output']).write_bytes(data)
elif p['mode'] == 'patch':
    data = patch_docx(Path(p['source']).read_bytes(), p['operations'])
    Path(p['output']).write_bytes(data)
else:
    data = Path(p['source']).read_bytes()
with ZipFile(BytesIO(data)) as z:
    for name in z.namelist():
        if name.endswith(('.xml', '.rels')):
            E.fromstring(z.read(name))
    xml = E.fromstring(z.read('word/document.xml'))
    facts = {'allXmlValid': True, 'bodyTexts': [''.join(n.xpath('.//w:t/text()', namespaces=NS)) for n in xml.findall('w:body/w:p', NS)], 'lists': len(xml.findall('.//w:numPr', NS)), 'tables': len(xml.findall('.//w:tbl', NS)), 'colspans': xml.xpath('//w:gridSpan/@w:val', namespaces=NS), 'media': [n for n in z.namelist() if n.startswith('word/media/') and not n.endswith('/')], 'colors': xml.xpath('//w:color/@w:val', namespaces=NS)}
    if p.get('original'):
        with ZipFile(p['original']) as original:
            changed = [n for n in original.namelist() if original.read(n) != z.read(n)]
            assert set(changed) <= {'word/document.xml', 'word/numbering.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml', 'docProps/core.xml'}, changed
            facts['changedParts'] = changed
print(json.dumps({'bytes': base64.b64encode(data).decode(), 'model': inspect_docx(data), 'facts': facts}))
