"""Home列表的实际下载包独立回读，不调用产品编号引擎。"""
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree

root = Path(sys.argv[1])
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
if '--fixture' in sys.argv:
    doc = Document()
    first = doc.add_paragraph('普通列表第一段')
    first.runs[0].bold = True
    first.alignment = 1
    doc.add_paragraph('普通列表第二段')
    doc.add_heading('保留标题', level=1)
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '保留表格'
    doc.sections[0].header.paragraphs[0].text = '保留页眉'
    doc.save(root / 'source.docx')
else:
    with ZipFile(root / 'source.docx') as a, ZipFile(root / 'downloaded.docx') as b:
        old = etree.fromstring(a.read('word/document.xml'))
        new = etree.fromstring(b.read('word/document.xml'))
        before = etree.fromstring(a.read('word/numbering.xml'))
        after = etree.fromstring(b.read('word/numbering.xml'))
        ids = new.xpath('/w:document/w:body/w:p/w:pPr/w:numPr/w:numId/@w:val', namespaces=ns)
        assert len(ids) == 2 and ids[0] != ids[1]
        abstracts = [after.xpath(f'string(w:num[@w:numId="{identity}"]/w:abstractNumId/@w:val)', namespaces=ns) for identity in ids]
        assert abstracts[0] == abstracts[1] and abstracts[0]
        assert len(before.xpath('w:abstractNum', namespaces=ns)) == len(after.xpath('w:abstractNum', namespaces=ns))
        assert [after.xpath(f'w:num[@w:numId="{identity}"]/w:lvlOverride/w:startOverride/@w:val', namespaces=ns) for identity in ids] == [['1'], ['9']]
        for index in [2]:
            assert etree.tostring(old.xpath('/w:document/w:body/w:p', namespaces=ns)[index], method='c14n') == etree.tostring(new.xpath('/w:document/w:body/w:p', namespaces=ns)[index], method='c14n')
        preserved = []
        for name in a.namelist():
            if name not in {'word/document.xml', 'word/numbering.xml', 'docProps/core.xml'}:
                assert a.read(name) == b.read(name), name
                preserved.append(name)
    original, actual = Document(root / 'source.docx'), Document(root / 'downloaded.docx')
    assert [p.text for p in original.paragraphs] == [p.text for p in actual.paragraphs]
    assert actual.paragraphs[0].runs[0].bold is True and actual.paragraphs[0].alignment == 1
    data = (root / 'downloaded.docx').read_bytes()
    evidence = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'numIds': ids, 'sameAbstractNumId': abstracts[0], 'starts': [1, 9], 'preservedParts': preserved}
    (root / 'independent-readback.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps(evidence, ensure_ascii=False))
