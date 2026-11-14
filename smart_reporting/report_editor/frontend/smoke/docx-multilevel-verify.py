"""独立 lxml/python-docx 验证，不调用产品解析器。"""
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from lxml import etree

directory = Path(sys.argv[1])
source, output = directory / 'source.docx', directory / 'downloaded.docx'
libraries = '--libraries' in sys.argv
ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
with ZipFile(source) as a, ZipFile(output) as b:
    document = etree.fromstring(b.read('word/document.xml'))
    paragraphs = document.xpath('/w:document/w:body/w:p', namespaces=ns)
    ids = [p.xpath('string(w:pPr/w:numPr/w:numId/@w:val)', namespaces=ns) for p in paragraphs[:2]]
    assert ids[0] and ids[1]
    assert (ids[0] != ids[1]) if libraries else (ids[0] == ids[1])
    numbering = etree.fromstring(b.read('word/numbering.xml'))
    abstract_id = numbering.xpath(f'string(w:num[@w:numId="{ids[1] if libraries else ids[0]}"]/w:abstractNumId/@w:val)', namespaces=ns)
    levels = numbering.xpath(f'w:abstractNum[@w:abstractNumId="{abstract_id}"]/w:lvl', namespaces=ns)
    assert len(levels) == 9
    assert levels[0].xpath('string(w:lvlText/@w:val)', namespaces=ns) == ('第%1项' if libraries else '第%1章')
    assert levels[0].xpath('string(w:start/@w:val)', namespaces=ns) == ('7' if libraries else '4')
    if libraries:
        assert levels[0].xpath('string(w:numFmt/@w:val)', namespaces=ns) == 'upperRoman'
        assert levels[0].xpath('string(w:lvlJc/@w:val)', namespaces=ns) == 'right'
        for key, value in [('sz', '28'), ('color', '123ABC')]:
            assert levels[0].xpath(f'string(w:rPr/w:{key}/@w:val)', namespaces=ns) == value
        assert levels[0].xpath('boolean(w:rPr/w:b) and boolean(w:rPr/w:i)', namespaces=ns)
        assert levels[0].xpath('string(w:rPr/w:rFonts/@w:ascii)', namespaces=ns) == 'Arial'
        bullet_id = numbering.xpath(f'string(w:num[@w:numId="{ids[0]}"]/w:abstractNumId/@w:val)', namespaces=ns)
        bullet = numbering.xpath(f'w:abstractNum[@w:abstractNumId="{bullet_id}"]/w:lvl', namespaces=ns)
        assert len(bullet) == 9
        assert bullet[0].xpath('string(w:numFmt/@w:val)', namespaces=ns) == 'bullet'
        assert bullet[0].xpath('string(w:lvlText/@w:val)', namespaces=ns) == '★'
        assert bullet[0].xpath('string(w:rPr/w:rFonts/@w:ascii)', namespaces=ns) == 'Arial'
    assert paragraphs[0].xpath('string(w:pPr/w:jc/@w:val)', namespaces=ns) == 'center'
    assert paragraphs[0].xpath('boolean(w:r/w:rPr/w:b)', namespaces=ns)
    original_document = etree.fromstring(a.read('word/document.xml'))
    original_paragraphs = original_document.xpath('/w:document/w:body/w:p', namespaces=ns)
    for old, new in zip(original_paragraphs[2:], paragraphs[2:], strict=True):
        assert etree.tostring(old, method='c14n') == etree.tostring(new, method='c14n')
    preserved = {}
    for name in a.namelist():
        if name.endswith('/') or name in ['word/document.xml', 'word/numbering.xml', 'docProps/core.xml']:
            continue
        assert a.read(name) == b.read(name), name
        preserved[name] = hashlib.sha256(b.read(name)).hexdigest()
    original_numbering = etree.fromstring(a.read('word/numbering.xml'))
    for child in original_numbering:
        kind = etree.QName(child).localname
        attribute = 'abstractNumId' if kind == 'abstractNum' else 'numId'
        identity = child.get(f'{{{ns["w"]}}}{attribute}')
        match = numbering.xpath(f'w:{kind}[@w:{attribute}="{identity}"]', namespaces=ns)
        assert len(match) == 1
        assert etree.tostring(child, method='c14n') == etree.tostring(match[0], method='c14n')
assert [p.text for p in Document(output).paragraphs] == [p.text for p in Document(source).paragraphs]
result = {'sha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'size': output.stat().st_size, 'numId': ids[0], 'levels': 9, 'start': 7 if libraries else 4, 'format': '第%1项' if libraries else '第%1章', 'libraries': libraries, 'preservedParts': preserved}
(directory / 'independent-readback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
