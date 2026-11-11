"""授权/CSRF路由fixture；真实PPTX引擎，PDF仅为有效附件占位。"""
import base64
import hashlib
import json
import sys
from io import BytesIO
from zipfile import ZipFile

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL_TYPE
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt

from smart_reporting.report_editor.native_office import inspect_office, patch_office


def _source():
    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[6])
    for index, name in enumerate(('A', 'B', 'After')):
        shape = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(1 + index * 2.5), Inches(1), Inches(2), Inches(1))
        shape.name = name
        shape.text = f'来源 {name}'
        paragraph = shape.text_frame.paragraphs[0]
        paragraph.alignment = PP_ALIGN.CENTER if index == 0 else PP_ALIGN.RIGHT
        font = paragraph.runs[0].font
        font.name = 'Arial' if index == 0 else 'Calibri'
        for tag in ('a:ea', 'a:cs'):
            face = OxmlElement(tag)
            face.set('typeface', font.name)
            paragraph.runs[0]._r.get_or_add_rPr().append(face)
        font.size = Pt(32 if index == 0 else 16)
        font.bold = index == 0
        font.italic = False
        font.underline = False
        font.color.rgb = RGBColor.from_string('123456' if index == 0 else '987654')
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string('55AA77' if index == 0 else 'EEEEEE')
        shape.line.color.rgb = RGBColor.from_string('224466' if index == 0 else '222222')
        shape.line.width = Pt(2 if index == 0 else 1)
    stream = BytesIO()
    Image.new('RGB', (100, 80), 'blue').save(stream, format='PNG')
    picture = slide.shapes.add_picture(BytesIO(stream.getvalue()), Inches(1), Inches(3), Inches(2), Inches(1.6))
    picture.name = 'Image'
    picture.crop_left = .125
    picture.crop_top = .25
    second = deck.slides.add_slide(deck.slide_layouts[6])
    second.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1)).text = '另一页内容'
    output = BytesIO()
    deck.save(output)
    content = output.getvalue()
    return content, inspect_office('pptx', content)


payload = json.load(sys.stdin)
mode = payload['mode']
if mode == 'create':
    content, model = _source()
    preview = BytesIO()
    Image.new('RGB', (48, 32), 'white').save(preview, 'PDF')
    print(json.dumps({'bytes': base64.b64encode(content).decode(), 'model': model,
                      'previewPdf': base64.b64encode(preview.getvalue()).decode()}))
else:
    content = base64.b64decode(payload['bytes'])
    if payload.get('operations'):
        content = patch_office('pptx', content, payload['operations'])
    if mode == 'render':
        from smart_reporting.report_editor.slides_render import render_pptx_tree
        result = render_pptx_tree(content)
    elif mode == 'independent':
        presentation = Presentation(BytesIO(content))
        slides = []
        for slide in presentation.slides:
            def shape_info(shape):
                item = {'id': shape.shape_id, 'name': shape.name, 'text': shape.text if shape.has_text_frame else None,
                        'geometry': [shape.left, shape.top, shape.width, shape.height]}
                if shape.has_text_frame:
                    item['paragraphs'] = [{'align': int(paragraph.alignment) if paragraph.alignment is not None else None,
                                           'runs': [{'text': run.text, 'name': run.font.name,
                                                     'size': run.font.size.pt if run.font.size else None,
                                                     'bold': run.font.bold, 'italic': run.font.italic,
                                                     'underline': run.font.underline,
                                                     'color': str(run.font.color.rgb) if run.font.color.type == MSO_COLOR_TYPE.RGB else None}
                                                    for run in paragraph.runs]} for paragraph in shape.text_frame.paragraphs]
                if hasattr(shape, 'fill') and shape.fill.type == MSO_FILL_TYPE.SOLID:
                    item['fill'] = str(shape.fill.fore_color.rgb) if shape.fill.fore_color.type == MSO_COLOR_TYPE.RGB else None
                if hasattr(shape, 'line'):
                    item['line'] = {'width': shape.line.width,
                                    'color': str(shape.line.color.rgb) if shape.line.color.type == MSO_COLOR_TYPE.RGB else None}
                item['url'] = shape.click_action.hyperlink.address
                if shape.shape_type == 6:
                    item['children'] = [shape_info(child) for child in shape.shapes]
                if shape.shape_type == 13:
                    item['pictureSha256'] = hashlib.sha256(shape.image.blob).hexdigest()
                    item['srcRect'] = [shape.crop_left, shape.crop_top, shape.crop_right, shape.crop_bottom]
                return item
            shapes = [shape_info(shape) for shape in slide.shapes]
            pictures = [{'name': shape.name, 'sha256': hashlib.sha256(shape.image.blob).hexdigest(),
                         'srcRect': {'l': shape.crop_left, 't': shape.crop_top, 'r': shape.crop_right, 'b': shape.crop_bottom},
                         'geometry': [shape.left, shape.top, shape.width, shape.height]} for shape in slide.shapes if shape.shape_type == 13]
            slides.append({'shapes': shapes, 'pictures': pictures})
        with ZipFile(BytesIO(content)) as archive:
            result = {'slides': slides, 'zip': {item.filename: hashlib.sha256(archive.read(item.filename)).hexdigest() for item in archive.infolist() if not item.is_dir()},
                      'slideXml': archive.read('ppt/slides/slide1.xml').decode()}
    else:
        result = {'bytes': base64.b64encode(content).decode(), 'model': inspect_office('pptx', content), 'sha256': hashlib.sha256(content).hexdigest()}
    print(json.dumps(result))
