"""媒体 native 验收夹具：真实 writer、修订文件与独立 ZIP/python-pptx 回读。"""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from zipfile import ZipFile

from lxml import etree
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.native_office import inspect_office, patch_office
from smart_reporting.report_editor.slides_render import render_pptx_tree


def digest(value):
    return hashlib.sha256(value).hexdigest()


def run(payload):
    directory = Path(payload['directory'])
    source = directory / 'source.pptx'
    if payload['mode'] == 'create':
        deck = Presentation()
        for index in range(3):
            slide = deck.slides.add_slide(deck.slide_layouts[6])
            slide.shapes.add_textbox(Inches(.3), Inches(.2), Inches(7), Inches(.5)).text = f'媒体原始正文 {index + 1}'
            slide.notes_slide.notes_text_frame.text = f'媒体保留讲稿 {index + 1}'
        stream = BytesIO(); deck.save(stream)
        items = [dict(slideIndex=index,kind=kind,extension=ext,bytesBase64=base64.b64encode((directory/name).read_bytes()).decode(),name=name) for index,kind,ext,name in [(0,'video','webm','source.webm'),(0,'audio','wav','source.wav'),(1,'video','avi','unsupported.avi')]]
        content = patch_office('pptx', stream.getvalue(), [{'kind':'editSlides','mediaInsertions':items}])
        model = inspect_office('pptx', content)
        movie = next(e for e in model['slides'][0]['elements'] if e.get('mediaKind') == 'video')
        content = patch_office('pptx', content, [{'kind':'editSlides','animationSequences':[dict(slideIndex=0,items=[dict(elementId=movie['id'],effect=effect,trigger='onClick',durationMs=0,delayMs=0) for effect in ('mediaPlay','mediaPause','mediaStop')])]}])
        assert not source.exists(); source.write_bytes(content)
    content = source.read_bytes()
    if payload.get('operations'):
        content = patch_office('pptx', content, payload['operations'])
    if payload.get('output'):
        target = Path(payload['output']); assert not target.exists(); target.write_bytes(content)
    if payload['mode'] == 'render':
        return render_pptx_tree(content)
    if payload['mode'] == 'verify':
        output = Path(payload['file']); saved = output.read_bytes()
        a, b = Presentation(source), Presentation(output)
        assert len(a.slides) == len(b.slides) == 3
        assert [s.notes_slide.notes_text_frame.text for s in a.slides] == [s.notes_slide.notes_text_frame.text for s in b.slides]
        assert [[p.text for p in s.shapes if p.has_text_frame] for s in a.slides] == [[p.text for p in s.shapes if p.has_text_frame] for s in b.slides]
        media = []
        with ZipFile(source) as old, ZipFile(output) as new:
            assert old.testzip() is None and new.testzip() is None
            old_parts = {n for n in old.namelist() if not n.endswith('/')}
            new_parts = {n for n in new.namelist() if not n.endswith('/')}
            assert old_parts <= new_parts
            changed = sorted(n for n in old_parts if old.read(n) != new.read(n))
            assert set(changed) <= {'ppt/slides/slide1.xml','ppt/slides/_rels/slide1.xml.rels','[Content_Types].xml'}, changed
            added = sorted(new_parts - old_parts)
            assert len(added) == 4, added
            for name in new_parts:
                if name.endswith(('.xml','.rels')):
                    etree.fromstring(new.read(name))
            for name in added:
                if name.endswith(('.webm','.wav')):
                    data = new.read(name); expected = (directory / ('insert.webm' if name.endswith('.webm') else 'insert.wav')).read_bytes()
                    assert data == expected
                    rels = etree.fromstring(new.read('ppt/slides/_rels/slide1.xml.rels'))
                    matching = [r for r in rels if r.get('Target','').endswith(name.split('/')[-1])]
                    assert len(matching) == 2
                    media.append({'part':name,'size':len(data),'sha256':digest(data),'dualRelationships':True})
        assert len(media) == 2
        return {'sourceSha256':digest(source.read_bytes()),'savedSha256':digest(saved),'savedSize':len(saved),'changedParts':changed,'addedParts':added,'media':media,'textNotesAndOtherPartsPreserved':True}
    return {'model':inspect_office('pptx',content),'size':len(content),'sha256':digest(content)}


if __name__ == '__main__':
    print(json.dumps(run(json.load(sys.stdin)), ensure_ascii=False))
