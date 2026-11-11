"""独立核验文本属性真实下载，不使用引擎或浏览器模型。"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import IndirectObject


def canonical(value):
    if isinstance(value, IndirectObject):
        return ['ref', value.idnum, value.generation]
    if isinstance(value, dict):
        return [[str(key), canonical(item)] for key, item in sorted(value.items())]
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return repr(value)


def identity(ref):
    return [ref.idnum, ref.generation]


def normal(widget):
    ref = widget['/AP'].raw_get('/N')
    stream = ref.get_object()
    assert stream.get_data()
    fonts = stream['/Resources']['/Font']
    assert len(fonts) == 1
    font = next(iter(fonts.values())).get_object()
    assert font['/Subtype'] == '/Type1'
    assert font['/BaseFont'] == '/Helvetica'
    return {'ref': identity(ref), 'sha256': hashlib.sha256(stream.get_data()).hexdigest(), 'font': str(font['/BaseFont'])}


def verify(directory: Path) -> dict:
    source = PdfReader(directory / 'source.pdf')
    results = []
    baseline = None
    previous_appearance = None
    for label in ('name', 'code', 'properties', 'unlimited', 'filled'):
        path = directory / f'{label}-downloaded.pdf'
        reader = PdfReader(path)
        assert len(reader.pages) == len(source.pages) == 3
        for actual, original in zip(reader.pages, source.pages):
            assert actual.extract_text() == original.extract_text()
            assert original.get_contents().get_data() in actual.get_contents().get_data()
            assert list(actual.mediabox) == list(original.mediabox)
            assert list(actual.cropbox) == list(original.cropbox)
            assert actual.rotation == original.rotation
        fields = {}
        widgets = []
        seen = set()

        def walk(refs, parent=None, prefix=''):
            names = set()
            for ref in refs:
                key = tuple(identity(ref))
                assert key not in seen
                seen.add(key)
                node = ref.get_object()
                part = str(node['/T'])
                assert part and '.' not in part and part not in names
                names.add(part)
                if parent is None:
                    assert '/Parent' not in node
                else:
                    assert identity(node.raw_get('/Parent')) == identity(parent)
                name = prefix + part
                if '/FT' not in node:
                    assert node['/Kids']
                    walk(node['/Kids'], ref, name + '.')
                    continue
                assert node['/FT'] == '/Tx'
                assert len(node['/Kids']) == 1
                widget_ref = node['/Kids'][0]
                widget = widget_ref.get_object()
                assert identity(widget.raw_get('/Parent')) == identity(ref)
                assert widget['/Subtype'] == '/Widget'
                assert identity(widget.raw_get('/P')) == identity(reader.pages[0].indirect_reference)
                normal(widget)
                fields[name] = (ref, node, widget_ref, widget)
                widgets.append(widget_ref)

        walk(reader.trailer['/Root']['/AcroForm']['/Fields'])
        assert list(reader.pages[0]['/Annots']) == widgets
        assert list(fields) == (['party.customer.name'] if label == 'name' else ['party.customer.name', 'party.customer.code'])
        ref, field, widget_ref, widget = fields['party.customer.name']
        assert field['/V'] == ('Alice Updated' if label == 'filled' else 'Alice')
        assert bool(field.get('/Ff', 0) & 2)
        appearance = normal(widget)
        if label != 'name':
            code_ref, code, code_widget_ref, code_widget = fields['party.customer.code']
            assert code['/V'] == 'C001'
            snapshot = {'targetRef': identity(ref), 'targetWidgetRef': identity(widget_ref),
                        'targetFieldInvariant': canonical({key: value for key, value in field.items() if key not in ('/Ff', '/MaxLen', '/Q', '/DA', '/V')}),
                        'targetWidgetInvariant': canonical({key: value for key, value in widget.items() if key != '/AP'}),
                        'codeRef': identity(code_ref), 'codeWidgetRef': identity(code_widget_ref),
                        'code': canonical(code), 'codeWidget': canonical(code_widget), 'codeAppearance': normal(code_widget)}
            if label == 'code':
                baseline = snapshot
            else:
                assert snapshot == baseline, label
        if label in ('properties', 'unlimited', 'filled'):
            multiline = label == 'properties'
            assert bool(field.get('/Ff', 0) & 4096) == multiline
            assert field.get('/MaxLen') == (32 if multiline else None)
            assert field.get('/Q', 0) == (1 if multiline else 2)
            size = 16 if multiline else 18
            assert re.search(r'/Helvetica\s+' + str(size) + r'(?:\.0+)?\s+Tf', str(field['/DA']))
            assert appearance != previous_appearance
        previous_appearance = appearance
        results.append({'label': label, 'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'bodyPreserved': True, 'canonicalTreeVerified': True, 'targetValue': str(field['/V']),
                        'appearanceVerified': True, 'targetAppearance': appearance,
                        'unrelatedFieldAndAppearancePreserved': label in ('properties', 'unlimited', 'filled'),
                        'targetReferencesPreserved': label in ('properties', 'unlimited', 'filled')})
    return {'ok': True, 'sourceSha256': hashlib.sha256((directory / 'source.pdf').read_bytes()).hexdigest(), 'checks': results}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
