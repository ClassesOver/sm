"""独立复读画布微调实际产物：屏幕方向、原大小、完整原对象/流及来源身份。"""
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


def verify_pair(before_path, after_path, operation, rotation):
    source, output = PdfReader(before_path), PdfReader(after_path)
    assert operation['kind'] == 'editFormWidget'
    assert set(operation) == {'kind', 'sourceSha256', 'fieldName', 'widgetId', 'widgetIdentity', 'expectedWidgetSha256', 'rect'}
    assert hashlib.sha256(before_path.read_bytes()).hexdigest() == operation['sourceSha256']
    old_fields, new_fields = fields(source), fields(output)
    assert list(old_fields) == list(new_fields)
    _, field, widgets = old_fields[operation['fieldName']]
    assert len(widgets) == 1
    ref, widget = widgets[0]
    assert str(ref.idnum)+'R'+(str(ref.generation) if ref.generation else '') == operation['widgetId']
    page_index = next(i for i, page in enumerate(source.pages) if any(canonical(entry) == canonical(ref) for entry in page.get('/Annots', [])))
    assert source.pages[page_index].rotation % 360 == rotation
    # Right 1 display pt, then Up 10 display pt. Default UserUnit only.
    dx, dy = {0: (1, 10), 90: (-10, 1), 180: (-1, -10), 270: (10, -1)}[rotation]
    old_rect = [float(v) for v in widget['/Rect']]
    expected = [old_rect[0]+dx, old_rect[1]+dy, old_rect[2]+dx, old_rect[3]+dy]
    assert operation['rect'] == expected
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
            before = source.get_object(IndirectObject(number, generation, source))
            after = output.get_object(IndirectObject(number, generation, output))
            if (number, generation) == (ref.idnum, ref.generation):
                assert list(after['/Rect']) == expected
                appearance = after['/AP']['/N']
                if field['/FT'] == '/Btn':
                    assert all(stream.get_object().get_data() for stream in appearance.values())
                else:
                    assert appearance.get_data()
                before, after = ({k: v for k, v in obj.items() if k not in ('/Rect', '/AP')} for obj in (before, after))
            assert canonical(before) == canonical(after), (number, generation)
            checked += 1
    return {'sha256': hashlib.sha256(after_path.read_bytes()).hexdigest(), 'size': after_path.stat().st_size,
            'rotation': rotation, 'pdfDelta': [dx, dy], 'rect': expected, 'originalObjectsChecked': checked,
            'originalUntouchedObjectsAndStreamsPreserved': True, 'pageOwnershipAndFieldTreePreserved': True,
            'objectCountZeroGrowthClaimed': False}


def verify(directory):
    if (directory / 'native-cases.json').exists():
        cases = json.loads((directory / 'native-cases.json').read_text())
        return {'ok': True, 'checks': [verify_pair(directory / case['source'], directory / case['output'], case['operation'], case['rotation']) for case in cases]}
    checkpoint = json.loads((directory / 'checkpoint.json').read_text())
    checks = []
    for label, baseline, rotation in (('nudge0', 'check', 0), ('nudge90', 'rotated', 90)):
        checks.append({'label': label, **verify_pair(directory / (baseline+'-downloaded.pdf'), directory / (label+'-downloaded.pdf'), checkpoint['saves'][label]['staged'][0], rotation)})
        assert checkpoint[label+'Gesture']['continuedWithoutReselection']
    return {'ok': True, 'checks': checks}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
