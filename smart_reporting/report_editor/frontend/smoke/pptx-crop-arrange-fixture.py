"""授权路由 smoke 的真实 PPTX 引擎 fixture；PDF 仅为明确标注的附件占位。"""
import base64
import hashlib
import json
import sys
from io import BytesIO
from zipfile import ZipFile

from PIL import Image
from pptx import Presentation
from pptx.util import Emu, Inches

from smart_reporting.report_editor.native_office import inspect_office, patch_office


def image():
    stream = BytesIO()
    Image.new('RGB', (120, 80), '#2468a0').save(stream, 'PNG')
    return stream.getvalue()


payload = json.load(sys.stdin)
mode = payload['mode']
if mode == 'create':
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    for name, text, x, y, width in [('Arrange A', 'First shape', 80, 70, 120), ('Arrange B', 'Second shape', 260, 125, 140), ('Arrange C', 'Third shape', 500, 180, 100)]:
        shape = slide.shapes.add_textbox(Emu(x * 9525), Emu(y * 9525), Emu(width * 9525), Emu(64 * 9525))
        shape.name = name
        shape.text = text
    picture = slide.shapes.add_picture(BytesIO(image()), Inches(1), Inches(3.5), Inches(3), Inches(2))
    picture.name = 'Crop source'
    untouched = presentation.slides.add_slide(presentation.slide_layouts[6])
    untouched.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = 'Untouched second slide'
    stream = BytesIO(); presentation.save(stream)
    content = stream.getvalue()
    preview = BytesIO(); Image.new('RGB', (48, 32), 'white').save(preview, 'PDF')
    print(json.dumps({'bytes': base64.b64encode(content).decode(), 'model': inspect_office('pptx', content),
                      'previewPdf': base64.b64encode(preview.getvalue()).decode()}))
else:
    content = base64.b64decode(payload['bytes'])
    if payload.get('operations'):
        content = patch_office('pptx', content, payload['operations'])
    if mode == 'slide-xml':
        with ZipFile(BytesIO(content)) as archive:
            result = {'xml': archive.read(payload['path']).decode()}
    elif mode == 'render':
        from smart_reporting.report_editor.slides_render import render_pptx_tree
        result = render_pptx_tree(content)
    elif mode == 'independent':
        presentation = Presentation(BytesIO(content))
        slides = []
        for slide in presentation.slides:
            shapes = [{'name': shape.name, 'text': shape.text if shape.has_text_frame else None,
                       'geometry': [shape.left, shape.top, shape.width, shape.height]} for shape in slide.shapes]
            pictures = [{'name': shape.name, 'sha256': hashlib.sha256(shape.image.blob).hexdigest(),
                         'srcRect': {'l': shape.crop_left, 't': shape.crop_top, 'r': shape.crop_right, 'b': shape.crop_bottom},
                         'geometry': [shape.left, shape.top, shape.width, shape.height]} for shape in slide.shapes if shape.shape_type == 13]
            slides.append({'shapes': shapes, 'pictures': pictures})
        with ZipFile(BytesIO(content)) as archive:
            result = {'slides': slides, 'zip': {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()},
                      'slideXml': archive.read('ppt/slides/slide1.xml').decode()}
    else:
        result = {'bytes': base64.b64encode(content).decode(), 'model': inspect_office('pptx', content), 'sha256': hashlib.sha256(content).hexdigest()}
    print(json.dumps(result))
