"""独立复读按页排列：每页自身 anchor、原对象/AP 流、字段树及实际页归属。"""
from __future__ import annotations
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from pypdf import PdfReader
from pypdf.generic import IndirectObject

spec = importlib.util.spec_from_file_location('form_verify', Path(__file__).with_name('pdf-form-radio-name-verify.py'))
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
canonical, fields = shared.canonical, shared.fields


def view(rect, page):
    x0, y0 = float(page.cropbox.left), float(page.cropbox.bottom)
    w, h, r = float(page.cropbox.width), float(page.cropbox.height), page.rotation % 360
    def point(x, y):
        x, y = float(x) - x0, float(y) - y0
        return {0: (x, h-y), 90: (y, x), 180: (w-x, y), 270: (h-y, w-x)}[r]
    a, b = point(*rect[:2]), point(*rect[2:])
    return [min(a[0], b[0]), min(a[1], b[1]), abs(b[0]-a[0]), abs(b[1]-a[1])]


def pdf_rect(box, page):
    x0, y0 = float(page.cropbox.left), float(page.cropbox.bottom)
    w, h, r = float(page.cropbox.width), float(page.cropbox.height), page.rotation % 360
    dw, dh = (h, w) if r % 180 else (w, h)
    width, height = min(box[2], dw), min(box[3], dh)
    left, top = min(max(box[0], 0), dw-width), min(max(box[1], 0), dh-height)
    def point(x, y):
        px, py = {0: (x, h-y), 90: (y, x), 180: (w-x, y), 270: (w-y, h-x)}[r]
        return px+x0, py+y0
    a, b = point(left, top), point(left+width, top+height)
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1])]


def verify_pair(before_path, after_path, operation):
    source, output = PdfReader(before_path), PdfReader(after_path)
    assert hashlib.sha256(before_path.read_bytes()).hexdigest() == operation['sourceSha256']
    old_fields, new_fields = fields(source), fields(output)
    assert list(old_fields) == list(new_fields)
    old_widgets = {str(ref.idnum)+'R'+(str(ref.generation) if ref.generation else ''): (name, ref, widget)
                   for name, (_, _, widgets) in old_fields.items() for ref, widget in widgets}
    by_page, expected, changed = {}, {}, set()
    for target in operation['targets']:
        name, ref, widget = old_widgets[target['widgetId']]
        assert name == target['fieldName']
        pages = [i for i, page in enumerate(source.pages) if any(canonical(entry) == canonical(ref) for entry in page.get('/Annots', []))]
        assert len(pages) == 1
        by_page.setdefault(pages[0], []).append((ref, widget))
    how = operation['alignment']
    assert how in ('left', 'sameSize'), 'dedicated browser/native verifier covers left and sameSize; eleven modes are native unit tested'
    for index, widgets in by_page.items():
        if len(widgets) < 2:
            continue
        boxes = [view(list(widget['/Rect']), source.pages[index]) for _, widget in widgets]
        anchor, left = boxes[0][:], min(box[0] for box in boxes)
        for (ref, widget), box in zip(widgets, boxes):
            if how == 'left':
                box[0] = left
            else:
                box[2:] = anchor[2:]
            rect = pdf_rect(box, source.pages[index])
            expected[(ref.idnum, ref.generation)] = rect
            if rect != list(widget['/Rect']):
                changed.add((ref.idnum, ref.generation))
    assert len(source.pages) == len(output.pages)
    for before, after in zip(source.pages, output.pages):
        assert canonical(before.get('/Annots', [])) == canonical(after.get('/Annots', []))
        assert before.extract_text() == after.extract_text()
        assert before.get_contents().get_data() == after.get_contents().get_data()
        assert list(before.mediabox) == list(after.mediabox) and list(before.cropbox) == list(after.cropbox)
        assert before.rotation == after.rotation
    checked = 0
    for generation, refs in source.xref.items():
        for number in refs:
            if not number:
                continue
            ref = IndirectObject(number, generation, source)
            before, after = source.get_object(ref), output.get_object(IndirectObject(number, generation, output))
            if (number, generation) in expected:
                assert list(after['/Rect']) == expected[(number, generation)]
            if (number, generation) in changed:
                assert after['/AP']['/N'].get_data()
                before, after = ({k: v for k, v in obj.items() if k not in ('/Rect', '/AP')} for obj in (before, after))
            assert canonical(before) == canonical(after), (number, generation)
            checked += 1
    return {'sha256': hashlib.sha256(after_path.read_bytes()).hexdigest(), 'originalObjectsChecked': checked,
            'changedWidgets': len(changed), 'pageGroups': len(by_page), 'originalUntouchedObjectsAndStreamsPreserved': True,
            'pageOwnershipAndFieldTreePreserved': True, 'objectCountZeroGrowthClaimed': False}


def verify(directory):
    if (directory / 'native-baseline.pdf').exists():
        operation = json.loads((directory / 'native-operation.json').read_text())
        return {'ok': True, 'checks': [verify_pair(directory / 'native-baseline.pdf', directory / 'native-arranged.pdf', operation)]}
    checkpoint = json.loads((directory / 'checkpoint.json').read_text())
    saves = checkpoint['saves']
    baseline = directory / 'singleton-downloaded.pdf'
    checks = []
    for label in ('left', 'sameSize'):
        after = directory / (label+'-downloaded.pdf')
        checks.append({'label': label, **verify_pair(baseline, after, saves[label]['staged'][0])})
        baseline = after
    return {'ok': True, 'checks': checks}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
