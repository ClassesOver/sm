"""独立 pypdf/PyMuPDF 回读原生画布产物；不依赖 Node 写入器的复核结果。"""
from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageChops
from pypdf import PdfReader
from pypdf.generic import IndirectObject


def verify(directory: Path) -> dict:
    shared = runpy.run_path(str(Path(__file__).with_name('pdf-form-radio-name-verify.py')))
    canonical, fields = shared['canonical'], shared['fields']
    before_path, after_path = directory / 'source.pdf', directory / 'downloaded.pdf'
    source, output = PdfReader(before_path), PdfReader(after_path)
    operations = json.loads((directory / 'staged.json').read_text())
    assert len(operations) == 1 and operations[0]['kind'] == 'editFormWidgetRects'
    operation = operations[0]
    assert operation['sourceSha256'] == hashlib.sha256(before_path.read_bytes()).hexdigest()
    changes = {change['widgetId']: change for change in operation['changes']}
    assert len(changes) == len(operation['changes']) == 2
    old_fields, new_fields = fields(source), fields(output)
    assert list(old_fields) == list(new_fields)
    assert canonical(source.metadata) == canonical(output.metadata)
    assert len(source.pages) == len(output.pages)
    for before, after in zip(source.pages, output.pages):
        assert canonical(before.get('/Annots', [])) == canonical(after.get('/Annots', []))
        assert before.extract_text() == after.extract_text()
        assert before.get_contents().get_data() == after.get_contents().get_data()
        assert list(before.mediabox) == list(after.mediabox)
        assert list(before.cropbox) == list(after.cropbox)
        assert before.rotation == after.rotation
    original_objects = 0
    for generation, refs in source.xref.items():
        for number in refs:
            if not number:
                continue
            before = source.get_object(IndirectObject(number, generation, source))
            after = output.get_object(IndirectObject(number, generation, output))
            widget_id = str(number) + 'R' + (str(generation) if generation else '')
            if widget_id in changes:
                assert [float(value) for value in after['/Rect']] == changes[widget_id]['rect']
                assert canonical(before.get('/AP')) == canonical(after.get('/AP'))
                before, after = ({key: value for key, value in obj.items() if key != '/Rect'} for obj in (before, after))
            assert canonical(before) == canonical(after), (number, generation)
            original_objects += 1
    for name, (_, field, widgets) in old_fields.items():
        _, after_field, after_widgets = new_fields[name]
        assert canonical(field) == canonical(after_field)
        assert field.get('/V') == after_field.get('/V')
        assert len(widgets) == len(after_widgets)
    old_render, new_render = pymupdf.open(before_path), pymupdf.open(after_path)
    pixels = []
    for change in changes.values():
        _, _, widgets = old_fields[change['fieldName']]
        old_rect = next(widget['/Rect'] for ref, widget in widgets if str(ref.idnum) + 'R' + (str(ref.generation) if ref.generation else '') == change['widgetId'])
        page_index = next(index for index, page in enumerate(source.pages) if any(str(ref.idnum) + 'R' + (str(ref.generation) if ref.generation else '') == change['widgetId'] for ref in page['/Annots']))
        page_height = old_render[page_index].rect.height
        images = []
        for document, rect in ((old_render, old_rect), (new_render, change['rect'])):
            x1, y1, x2, y2 = map(float, rect)
            clip = pymupdf.Rect(x1, page_height-y2, x2, page_height-y1)
            pixmap = document[page_index].get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, alpha=False)
            images.append(Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples))
        assert images[0].size == images[1].size
        assert ImageChops.difference(*images).getbbox() is None, change['fieldName']
        pixels.append({'fieldName': change['fieldName'], 'pixels': list(images[0].size), 'exactTranslatedAppearance': True})
    saved = json.loads((directory / 'save.json').read_text())['result']
    actual_sha = hashlib.sha256(after_path.read_bytes()).hexdigest()
    assert saved['artifacts']['pdf']['sha256'] == actual_sha
    assert saved['artifacts']['pdf']['size'] == after_path.stat().st_size
    assert saved['validation']['ok'] is False and saved['validation']['issues']
    return {'ok': True, 'sha256': actual_sha, 'size': after_path.stat().st_size,
            'originalObjectsChecked': original_objects, 'originalAPAndDAUnchanged': True,
            'nativeFieldTreeValuesAndBodyPreserved': True, 'pixelChecks': pixels,
            'failedValidationWithSpecificIssuesAndDownloadPreserved': True}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1])), ensure_ascii=False, indent=2))
