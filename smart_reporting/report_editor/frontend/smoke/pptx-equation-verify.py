"""独立 ZIP/lxml/python-pptx 回读；不调用应用解析器或写入桥。"""
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn

root = Path(sys.argv[1])
expected = json.loads((root / 'expected.json').read_text())
source, output = root / 'source.pptx', root / 'downloaded.pptx'
a, b = Presentation(source), Presentation(output)
assert len(a.slides) == len(b.slides) == 2
assert (a.slide_width, a.slide_height) == (b.slide_width, b.slide_height)
assert [shape.text for shape in b.slides[0].shapes if shape.has_text_frame] == [a.slides[0].shapes[0].text, *expected]
for old, new in zip(a.slides, b.slides):
    assert old.notes_slide.notes_text_frame.text == new.notes_slide.notes_text_frame.text
    assert etree.tostring(old.shapes[0]._element) == etree.tostring(new.shapes[0]._element)
items = []
for shape, text in zip(list(b.slides[0].shapes)[1:], expected):
    assert shape.text == text
    assert (shape.left, shape.top, shape.width, shape.height) == (round((a.slide_width / 9525 - 96) / 2) * 9525,
        round((a.slide_height / 9525 - 96) / 2) * 9525, 914400, 914400)
    run = shape.text_frame.paragraphs[0].runs[0]
    assert run.font.name == 'Cambria Math' and run.font.italic is True and run.font.size.pt == 18
    body = shape._element.find(qn('p:txBody')).find(qn('a:bodyPr'))
    assert body.get('wrap') == 'none' and body.find(qn('a:spAutoFit')) is not None
    assert body.find(qn('a:normAutofit')) is None
    items.append({'text': text, 'font': run.font.name, 'sizePt': run.font.size.pt, 'italic': run.font.italic,
                  'geometryEMU': [shape.left, shape.top, shape.width, shape.height]})
with ZipFile(source) as old, ZipFile(output) as new:
    assert old.testzip() is None and new.testzip() is None
    assert {name for name in old.namelist() if not name.endswith('/')} == {name for name in new.namelist() if not name.endswith('/')}
    changed = sorted(name for name in old.namelist() if old.read(name) != new.read(name))
    assert changed == ['ppt/slides/slide1.xml'], changed
    for name in new.namelist():
        if name.endswith(('.xml', '.rels')):
            node = etree.fromstring(new.read(name))
            assert not node.xpath('//*[local-name()="oMath" or local-name()="oMathPara"]')
proof = {'ok': True, 'sourceSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
         'outputSha256': hashlib.sha256(output.read_bytes()).hexdigest(), 'changedParts': changed,
         'equations': items, 'independentZipAndPythonPptx': True, 'sourceTextNotesOtherSlideAndOtherPartsPreserved': True,
         'format': 'Unicode math font textbox; source feature is not OMML'}
(root / 'independent-readback.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2))
print(json.dumps(proof, ensure_ascii=False))
