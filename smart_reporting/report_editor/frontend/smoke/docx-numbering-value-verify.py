"""编号值夹具与独立OOXML回读；验证不调用产品引擎。"""
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

directory = Path(sys.argv[1])
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
if '--fixture' in sys.argv:
    directory.mkdir(parents=True, exist_ok=True)
    doc = Document()
    numbering = doc.part.numbering_part.element
    for aid, nid in [('91', '91'), ('92', '92')]:
        abstract = OxmlElement('w:abstractNum'); abstract.set(qn('w:abstractNumId'), aid)
        for level, fmt, text in [(0, 'decimal', '%1.'), (1, 'lowerLetter', '%2)')]:
            lvl = OxmlElement('w:lvl'); lvl.set(qn('w:ilvl'), str(level))
            for tag, value in [('start', '1'), ('numFmt', fmt), ('lvlText', text)]:
                child = OxmlElement('w:' + tag); child.set(qn('w:val'), value); lvl.append(child)
            abstract.append(lvl)
        numbering.append(abstract)
        num = OxmlElement('w:num'); num.set(qn('w:numId'), nid)
        ref = OxmlElement('w:abstractNumId'); ref.set(qn('w:val'), aid); num.append(ref); numbering.append(num)
    rows = [('前序编号甲', '91', 0), ('前序编号乙', '91', 0), ('保留正文', None, 0),
        ('当前编号甲', '92', 0), ('当前编号乙', '92', 1), ('后续前序编号', '91', 0)]
    for i, (text, nid, level) in enumerate(rows):
        p = doc.add_paragraph(text)
        if i == 3:
            p.alignment = 1; p.runs[0].bold = True
        if nid:
            num = OxmlElement('w:numPr')
            for tag, value in [('ilvl', str(level)), ('numId', nid)]:
                child = OxmlElement('w:' + tag); child.set(qn('w:val'), value); num.append(child)
            p._p.get_or_add_pPr().append(num)
    doc.add_heading('保留标题', level=1)
    doc.add_table(rows=1, cols=1).cell(0, 0).text = '保留表格'
    doc.sections[0].header.paragraphs[0].text = '保留页眉'
    doc.save(directory / 'source.docx')
    print(json.dumps({'fixture': str(directory / 'source.docx')}))
else:
    with ZipFile(directory / 'source.docx') as a, ZipFile(directory / 'downloaded.docx') as b:
        old = etree.fromstring(a.read('word/document.xml'))
        new = etree.fromstring(b.read('word/document.xml'))
        op = old.xpath('/w:document/w:body/w:p', namespaces=ns)
        np = new.xpath('/w:document/w:body/w:p', namespaces=ns)
        ids = [p.xpath('string(w:pPr/w:numPr/w:numId/@w:val)', namespaces=ns) for p in np]
        assert ids[:3] == ['91', '91', '']
        assert len(set(ids[3:6])) == 1 and ids[3] not in {'91', '92', ''}
        nums = etree.fromstring(b.read('word/numbering.xml'))
        assert nums.xpath(f'string(w:num[@w:numId="{ids[3]}"]/w:abstractNumId/@w:val)', namespaces=ns) == '91'
        assert nums.xpath(f'w:num[@w:numId="{ids[3]}"]/w:lvlOverride[@w:ilvl="0"]/w:startOverride/@w:val', namespaces=ns) == ['9']
        assert np[4].xpath('string(w:pPr/w:numPr/w:ilvl/@w:val)', namespaces=ns) == '1'
        for i in [0, 1, 2, 6]:
            assert etree.tostring(op[i], method='c14n') == etree.tostring(np[i], method='c14n')
        assert np[3].xpath('boolean(w:r/w:rPr/w:b)', namespaces=ns)
        assert np[3].xpath('string(w:pPr/w:jc/@w:val)', namespaces=ns) == 'center'
        original_nums = etree.fromstring(a.read('word/numbering.xml'))
        for child in original_nums:
            kind = etree.QName(child).localname
            attr = 'abstractNumId' if kind == 'abstractNum' else 'numId'
            matches = nums.xpath(f'w:{kind}[@w:{attr}="{child.get(qn("w:" + attr))}"]', namespaces=ns)
            assert len(matches) == 1 and etree.tostring(child, method='c14n') == etree.tostring(matches[0], method='c14n')
        preserved = {}
        for name in a.namelist():
            if name in {'word/document.xml', 'word/numbering.xml', 'docProps/core.xml'}:
                continue
            assert a.read(name) == b.read(name), name
            preserved[name] = hashlib.sha256(b.read(name)).hexdigest()
    source, result = Document(directory / 'source.docx'), Document(directory / 'downloaded.docx')
    assert [p.text for p in source.paragraphs] == [p.text for p in result.paragraphs]
    assert source.tables[0].cell(0, 0).text == result.tables[0].cell(0, 0).text
    data = (directory / 'downloaded.docx').read_bytes()
    evidence = {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data), 'numId': ids[3],
        'sameAbstractNumId': '91', 'startOverride': 9, 'preservedParts': preserved}
    (directory / 'independent-readback.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps(evidence, ensure_ascii=False))
