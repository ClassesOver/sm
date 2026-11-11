"""显式授权/CSRF夹具；备注走真实引擎，PDF仅有效附件占位。"""
import base64
import hashlib
import json
import sys
from io import BytesIO
from zipfile import ZipFile

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.util import Inches

from smart_reporting.report_editor.native_office import inspect_office, patch_office


def _source(*, register_master=True):
    deck = Presentation()
    for index in range(3):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = f'来源 {index}'
        if index == 0:
            slide.notes_slide.notes_text_frame.text = '已有备注\n第二行'
            image = BytesIO()
            Image.new('RGB', (32, 24), 'blue').save(image, 'PNG')
            slide.shapes.add_picture(BytesIO(image.getvalue()), Inches(1), Inches(3), Inches(2), Inches(1.5))
    if register_master:
        master_rel = next(rel for rel in deck.part.rels.values() if rel.reltype == RT.NOTES_MASTER)
        master_ids = etree.Element(qn('p:notesMasterIdLst'))
        etree.SubElement(master_ids, qn('p:notesMasterId')).set(qn('r:id'), master_rel.rId)
        deck._element.insert(deck._element.index(deck._element.find(qn('p:sldMasterIdLst'))) + 1, master_ids)
    output = BytesIO()
    deck.save(output)
    return output.getvalue()


payload = json.load(sys.stdin)
mode = payload['mode']
if mode == 'create':
    content = _source()
    preview = BytesIO()
    Image.new('RGB', (48, 32), 'white').save(preview, 'PDF')
    result = {'bytes': base64.b64encode(content).decode(), 'model': inspect_office('pptx', content),
              'previewPdf': base64.b64encode(preview.getvalue()).decode()}
else:
    content = base64.b64decode(payload['bytes'])
    if payload.get('operations'):
        content = patch_office('pptx', content, payload['operations'])
    if mode == 'render':
        from smart_reporting.report_editor.slides_render import render_pptx_tree
        result = render_pptx_tree(content)
    elif mode == 'independent':
        slides = []
        for slide in Presentation(BytesIO(content)).slides:
            slides.append({'sourceText': slide.shapes[0].text, 'notesText': slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else '',
                           'shapes': [{'id': shape.shape_id, 'text': shape.text if shape.has_text_frame else None,
                                       'geometry': [shape.left, shape.top, shape.width, shape.height],
                                       **({'pictureSha256': hashlib.sha256(shape.image.blob).hexdigest()} if shape.shape_type == 13 else {})}
                                      for shape in slide.shapes]})
        with ZipFile(BytesIO(content)) as archive:
            result = {'slides': slides, 'zip': {item.filename: hashlib.sha256(archive.read(item.filename)).hexdigest()
                                               for item in archive.infolist() if not item.is_dir()},
                      'notesXml': {item.filename: archive.read(item.filename).decode() for item in archive.infolist()
                                   if item.filename.startswith('ppt/notesSlides/') and item.filename.endswith('.xml')}}
    else:
        result = {'bytes': base64.b64encode(content).decode(), 'model': inspect_office('pptx', content),
                  'sha256': hashlib.sha256(content).hexdigest()}
print(json.dumps(result))
