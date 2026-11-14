"""独立 ZIP/lxml/python-pptx 回读，不调用编辑器源解析器。"""
import hashlib
import json
import sys
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation

directory = Path(sys.argv[1])
summary = json.loads((directory / 'summary.json').read_text())
namespace = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
             'p': 'http://schemas.openxmlformats.org/presentationml/2006/main'}
with ZipFile(directory / 'source.pptx') as before, ZipFile(directory / 'downloaded.pptx') as after:
    before_parts = {name for name in before.namelist() if not name.endswith('/')}
    after_parts = {name for name in after.namelist() if not name.endswith('/')}
    assert before_parts == after_parts
    changed = [name for name in sorted(before_parts) if before.read(name) != after.read(name)]
    assert sorted(changed) == sorted(summary['changedParts']), changed
    checks = []
    for name, spid, expected in ((summary['changedParts'][0], '9001', '母版品牌更新 <&> 😀'),
                                  (summary['changedParts'][1], '9002', '版式品牌更新\n第二行')):
        root = etree.fromstring(after.read(name))
        shape = root.xpath(f'.//p:sp[p:nvSpPr/p:cNvPr[@id="{spid}"]]', namespaces=namespace)
        assert len(shape) == 1
        paragraphs = shape[0].xpath('./p:txBody/a:p', namespaces=namespace)
        actual = '\n'.join(''.join(p.xpath('.//a:t/text()', namespaces=namespace)) for p in paragraphs)
        assert actual == expected, actual
        checks.append({'partPath': name, 'spid': spid, 'text': actual})
    untouched = [name for name in before_parts if name not in changed]
    assert all(before.read(name) == after.read(name) for name in untouched)
deck = Presentation(directory / 'downloaded.pptx')
assert len(deck.slides) == 2
for index, slide in enumerate(deck.slides):
    assert slide.shapes[0].text == f'公式验收保留正文 {index + 1} <&> 😀'
    assert slide.notes_slide.notes_text_frame.text == f'保留讲稿 {index + 1}'
assert deck.slide_master.shapes[-1].text == '母版品牌更新 <&> 😀'
assert deck.slide_layouts[6].shapes[-1].text == '版式品牌更新\n第二行'
sha = hashlib.sha256((directory / 'downloaded.pptx').read_bytes()).hexdigest()
assert sha == summary['downloadSha256']
result = {'ok': True, 'downloadSha256': sha, 'changedParts': changed, 'partTextChecks': checks,
          'untouchedArchiveEntries': len(untouched), 'allSlideNotesRelationshipsAndMediaBytesPreserved': True,
          'independentPythonPptxOpened': True, 'slideCount': 2}
(directory / 'independent-verify.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False))
