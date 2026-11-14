"""查找替换夹具：真实引擎、独立PPTX文本/格式/ZIP保真核对。"""
import hashlib
import json
import sys
import uuid
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt
from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.slides_render import render_pptx_tree

QUERY, REPLACEMENT = '收入', '营收 $& <PC> 😀'
TARGETS = {'PlainTitle', 'PlainShape', 'SecondTitle'}
NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def create():
    deck = Presentation()
    for index in range(3):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(0.6), Inches(7), Inches(1.4))
        box.name = ['PlainTitle', 'SecondTitle', 'PreservedTitle'][index]
        box.text = ['收入 收入 & <保真> 😀', '收入 Revenue', '第三页保留'][index]
        run = box.text_frame.paragraphs[0].runs[0]
        run.font.name, run.font.size, run.font.bold = 'Calibri', Pt(20), True
        if index == 0:
            shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(1), Inches(2.2), Inches(4), Inches(0.7))
            shape.name, shape.text = 'PlainShape', '收入预测'
            shape.fill.solid()
            shape.fill.fore_color.rgb = RGBColor(220, 235, 250)
            shape.line.color.rgb = RGBColor(31, 79, 120)
            shape.text_frame.paragraphs[0].runs[0].font.size = Pt(18)
            # 显式格式的普通形状；另保留下面带p:style的来源，检验安全边界。
            shape._element.remove(shape._element.find('p:style', NS))
            mixed = slide.shapes.add_textbox(Inches(1), Inches(3.2), Inches(6), Inches(0.6))
            mixed.name = 'MixedRuns'
            for text, bold in [('收入', True), (' 风险提示', False)]:
                part = mixed.text_frame.paragraphs[0].add_run()
                part.text, part.font.bold, part.font.size = text, bold, Pt(18)
            table = slide.shapes.add_table(2, 2, Inches(1), Inches(4), Inches(5), Inches(1)).table
            table.cell(0, 0).text, table.cell(0, 1).text = '收入', '100'
            table.cell(1, 0).text, table.cell(1, 1).text = '成本', '50'
            linked = slide.shapes.add_textbox(Inches(1), Inches(5.3), Inches(6), Inches(0.5))
            linked.name, linked.text = 'LinkedText', '收入 超链接'
            linked.text_frame.paragraphs[0].runs[0].hyperlink.address = 'https://example.invalid/preserved'
        if index == 1:
            box = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(6), Inches(0.8))
            box.name, box.text = 'CaseText', 'Revenue revenue'
            styled = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1), Inches(3.6), Inches(5), Inches(0.7))
            styled.name, styled.text = 'StyleReferenceShape', '收入样式引用'
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def verify(directory):
    first, second = directory / 'revision-1.pptx', directory / 'downloaded.pptx'
    before_deck, after_deck = Presentation(first), Presentation(second)
    assert (before_deck.slide_width, before_deck.slide_height) == (after_deck.slide_width, after_deck.slide_height)
    assert len(before_deck.slides) == len(after_deck.slides) == 3
    shapes, replacement_count = [], 0
    for before_slide, after_slide in zip(before_deck.slides, after_deck.slides):
        assert len(before_slide.shapes) == len(after_slide.shapes)
        for original, actual in zip(before_slide.shapes, after_slide.shapes):
            assert (original.name, original.shape_id) == (actual.name, actual.shape_id)
            for attribute in ['left', 'top', 'width', 'height', 'rotation']:
                assert getattr(original, attribute) == getattr(actual, attribute), (original.name, attribute)
            if original.has_text_frame:
                expected = original.text.replace(QUERY, REPLACEMENT) if original.name in TARGETS else original.text
                assert actual.text == expected, (original.name, actual.text, expected)
                replacement_count += original.text.count(QUERY) if original.name in TARGETS else 0
                for old_paragraph, new_paragraph in zip(original.text_frame.paragraphs, actual.text_frame.paragraphs):
                    assert len(old_paragraph.runs) == len(new_paragraph.runs)
                    for old_run, new_run in zip(old_paragraph.runs, new_paragraph.runs):
                        for attribute in ['name', 'size', 'bold', 'italic', 'underline']:
                            assert getattr(old_run.font, attribute) == getattr(new_run.font, attribute), (original.name, attribute)
                        assert old_run.hyperlink.address == new_run.hyperlink.address
            if original.has_table:
                assert [[c.text for c in row.cells] for row in original.table.rows] == [[c.text for c in row.cells] for row in actual.table.rows]
            shapes.append(original.name)
    assert replacement_count == 4
    canonical = lambda element: etree.tostring(element, method='c14n', exclusive=True)
    identities, restored = [], 0
    with ZipFile(first) as a, ZipFile(second) as b:
        assert a.testzip() is None and b.testzip() is None
        added = sorted(set(b.namelist()) - set(a.namelist()))
        assert all(name.endswith('/') and not b.read(name) for name in added)
        assert {n for n in a.namelist() if not n.endswith('/')} == {n for n in b.namelist() if not n.endswith('/')}
        changed = [n for n in a.namelist() if a.read(n) != b.read(n)]
        for name in b.namelist():
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(b.read(name))
        for name in changed:
            assert name.endswith('.xml') and name.startswith(('ppt/slides/slide', 'ppt/slideLayouts/slideLayout', 'ppt/slideMasters/slideMaster')), name
            original, actual = etree.fromstring(a.read(name)), etree.fromstring(b.read(name))
            for source in original.xpath('.//p:sp', namespaces=NS):
                identity = source.find('p:nvSpPr/p:cNvPr', NS)
                if identity is None or identity.get('name') not in TARGETS:
                    continue
                matches = actual.getroottree().xpath(original.getroottree().getpath(source), namespaces=NS)
                assert len(matches) == 1
                old_texts, new_texts = source.findall('.//a:t', NS), matches[0].findall('.//a:t', NS)
                assert len(old_texts) == len(new_texts)
                for old, new in zip(old_texts, new_texts):
                    assert new.text == old.text.replace(QUERY, REPLACEMENT)
                    restored += old.text.count(QUERY)
                    new.text = old.text
            # 保存器原有的creationId补充须逐项核验，不抹掉其它扩展。
            for old in original.xpath('.//p:cNvPr', namespaces=NS):
                matches = actual.getroottree().xpath(original.getroottree().getpath(old), namespaces=NS)
                assert len(matches) == 1
                new = matches[0]
                if len(old) == 0 and len(new):
                    assert len(new) == 1 and new[0].tag == '{' + NS['a'] + '}extLst'
                    extension_list = new[0]
                    assert len(extension_list) == 1 and extension_list[0].get('uri') == '{FF2B5EF4-FFF2-40B4-BE49-F238E27FC236}'
                    extension = extension_list[0]
                    assert len(extension) == 1 and extension[0].tag == '{http://schemas.microsoft.com/office/drawing/2014/main}creationId'
                    identities.append(str(uuid.UUID(extension[0].get('id').strip('{}'))))
                    new.remove(extension_list)
            assert canonical(original) == canonical(actual), name + ' changed outside intended text/creation identity'
    assert restored == 4 and len(identities) == len(set(identities))
    result = {'ok': True, 'sourceBytes': first.stat().st_size, 'outputBytes': second.stat().st_size,
              'sourceSha256': hashlib.sha256(first.read_bytes()).hexdigest(), 'outputSha256': hashlib.sha256(second.read_bytes()).hexdigest(),
              'slideCount': 3, 'shapeNames': shapes, 'replacementCount': replacement_count,
              'changedParts': changed, 'addedEmptyZipDirectories': added, 'addedUniqueCreationIds': len(identities),
              'onlyTextAndCreationIdentityChanged': True, 'mixedRunsTablesLinksPreserved': True, 'geometryAndFontPropertiesPreserved': True}
    (directory / 'independent-check.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    return result


def main(payload):
    if payload['mode'] == 'verify':
        return verify(Path(payload['directory']))
    content = create() if payload['mode'] == 'create' else Path(payload['source']).read_bytes()
    if payload.get('operations'):
        content = patch_office('pptx', content, payload['operations'])
    if payload['mode'] == 'render':
        return render_pptx_tree(content)
    if payload.get('output'):
        Path(payload['output']).write_bytes(content)
    return {'model': inspect_office('pptx', content), 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}


if __name__ == '__main__':
    print(json.dumps(main(json.load(sys.stdin)), ensure_ascii=False))
