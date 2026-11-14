"""尺寸窗口的独立来源；使用真实 PPTX inspect/edit/render-tree。"""
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.util import Inches, Pt
from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.slides_render import render_pptx_tree

p = json.load(sys.stdin)
if p['mode'] == 'create':
    deck = Presentation()
    deck.slide_width, deck.slide_height = 9144123, 6858000
    for index in range(2):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1))
        box.text = f'尺寸保真 {index + 1} & <PC> 😀'
        box.text_frame.paragraphs[0].runs[0].font.size = Pt(20)
        box.text_frame.paragraphs[0].runs[0].font.bold = True
        slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(2), Inches(3), Inches(3), Inches(1))
    stream = BytesIO()
    deck.save(stream)
    content = stream.getvalue()
else:
    content = Path(p['source']).read_bytes()
    if p.get('operations'):
        content = patch_office('pptx', content, p['operations'])
if p['mode'] == 'render':
    print(json.dumps(render_pptx_tree(content)))
else:
    if p.get('output'):
        Path(p['output']).write_bytes(content)
    print(json.dumps({'model': inspect_office('pptx', content), 'sha256': hashlib.sha256(content).hexdigest(), 'size': len(content)}, ensure_ascii=False))
