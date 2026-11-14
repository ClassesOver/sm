"""背景窗口：真实原生保存/渲染，独立核对背景与其余包内容。"""
import hashlib
import json
import posixpath
import sys
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt


def run(p):
    directory = Path(p['directory'])
    if p['mode'] == 'create':
        deck = Presentation()
        image = BytesIO()
        Image.new('RGB', (6, 4), '#00aabb').save(image, format='PNG', dpi=(96, 96))
        for index in range(3):
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = RGBColor.from_string('E8EEF4')
            text = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
            text.text = f'背景保真 {index + 1} & <PC> 😀'
            text.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
            text.text_frame.paragraphs[0].runs[0].font.bold = True
            text.click_action.hyperlink.address = 'https://example.invalid/preserved'
            slide.shapes.add_picture(BytesIO(image.getvalue()), Inches(2), Inches(3), Inches(1), Inches(1))
            slide.notes_slide.notes_text_frame.text = f'保留讲稿 {index + 1}'
        assert not (directory / 'revision-1.pptx').exists()
        deck.save(directory / 'revision-1.pptx')
        Image.new('RGB', (8, 5), '#dd4422').save(directory / 'background.png', format='PNG', dpi=(96, 96))
        (directory / 'invalid.png').write_text('not an image')
    source = Path(p.get('source', directory / 'revision-1.pptx'))
    content = source.read_bytes()
    if p.get('operations'):
        from smart_reporting.report_editor.native_office import patch_office
        content = patch_office('pptx', content, p['operations'])
    if p.get('output'):
        output = Path(p['output'])
        assert not output.exists(), '禁止覆盖已保存产物'
        output.write_bytes(content)
    if p['mode'] == 'render':
        from smart_reporting.report_editor.slides_render import render_pptx_tree
        return render_pptx_tree(content)
    if p['mode'] != 'verify':
        from smart_reporting.report_editor.native_office import inspect_office
        return {'model': inspect_office('pptx', content), 'size': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
    output = Path(p.get('file', directory / 'downloaded.pptx'))
    ns = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
          'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
          'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
          'rel': 'http://schemas.openxmlformats.org/package/2006/relationships'}
    old_deck, new_deck = Presentation(source), Presentation(output)
    assert len(old_deck.slides) == len(new_deck.slides) == 3
    assert (old_deck.slide_width, old_deck.slide_height) == (new_deck.slide_width, new_deck.slide_height)
    for a, b in zip(old_deck.slides, new_deck.slides):
        assert [shape.text for shape in a.shapes if shape.has_text_frame] == [shape.text for shape in b.shapes if shape.has_text_frame]
        assert a.notes_slide.notes_text_frame.text == b.notes_slide.notes_text_frame.text
    with ZipFile(source) as a, ZipFile(output) as b:
        assert a.testzip() is None and b.testzip() is None
        names_a = {n for n in a.namelist() if not n.endswith('/')}
        names_b = {n for n in b.namelist() if not n.endswith('/')}
        assert not names_a - names_b
        added = sorted(names_b - names_a)
        assert len(added) == 1 and added[0].startswith('ppt/media/'), added
        assert b.read(added[0]) == (directory / 'background.png').read_bytes()
        for name in names_b:
            if name.endswith(('.xml', '.rels')):
                etree.fromstring(b.read(name))
        changed = sorted(name for name in names_a if a.read(name) != b.read(name))
        allowed = {f'ppt/slides/slide{n}.xml' for n in [1, 2, 3]} | {'ppt/slides/_rels/slide1.xml.rels', '[Content_Types].xml'}
        assert set(changed) <= allowed, changed
        roots = [etree.fromstring(b.read(f'ppt/slides/slide{n}.xml')) for n in [1, 2, 3]]
        fill = roots[0].find('p:cSld/p:bg/p:bgPr/a:blipFill', ns)
        assert fill is not None and fill.find('a:tile', ns) is not None
        embed = fill.find('a:blip', ns).get('{'+ns['r']+'}embed')
        rel_path = 'ppt/slides/_rels/slide1.xml.rels'
        old_rels, new_rels = [etree.fromstring(z.read(rel_path)) for z in [a, b]]
        rel = new_rels.find(f'rel:Relationship[@Id="{embed}"]', ns)
        assert rel is not None and rel.get('Type') == ns['r']+'/image'
        assert posixpath.normpath(posixpath.join('ppt/slides', rel.get('Target'))) == added[0]
        new_rels.remove(rel)
        assert etree.tostring(old_rels, method='c14n') == etree.tostring(new_rels, method='c14n'), '非目标关系改变'
        gradient = roots[1].find('p:cSld/p:bg/p:bgPr/a:gradFill', ns)
        assert gradient is not None
        assert [(n.get('pos'), n.find('a:srgbClr', ns).get('val')) for n in gradient.findall('a:gsLst/a:gs', ns)] == [('0', 'FF8800'), ('100000', '004488')]
        assert gradient.find('a:lin', ns).get('ang') == '2700000'
        assert roots[2].find('p:cSld/p:bg', ns) is None
        assert [r.get('showMasterSp', '1') for r in roots] == ['0', '1', '0']
        for n, actual in enumerate(roots, 1):
            original = etree.fromstring(a.read(f'ppt/slides/slide{n}.xml'))
            for root in [original, actual]:
                root.attrib.pop('showMasterSp', None)
                for bg in root.findall('p:cSld/p:bg', ns):
                    bg.getparent().remove(bg)
            assert etree.tostring(original, method='c14n') == etree.tostring(actual, method='c14n'), ('背景外XML改变', n)
        if '[Content_Types].xml' in changed:
            old_types, new_types = [etree.fromstring(z.read('[Content_Types].xml')) for z in [a, b]]
            assert {etree.tostring(n, method='c14n') for n in old_types} == {etree.tostring(n, method='c14n') for n in new_types}, '内容类型集合改变'
    return {'ok': True, 'changedParts': changed, 'addedMedia': added,
            'sourceSha256': hashlib.sha256(content).hexdigest(), 'outputSha256': hashlib.sha256(output.read_bytes()).hexdigest(),
            'backgroundImageByteIdentical': True, 'onlyBackgroundsAndGraphicsChanged': True,
            'textGeometryNotesLinksForegroundMediaAndOtherPartsPreserved': True}


if __name__ == '__main__':
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
