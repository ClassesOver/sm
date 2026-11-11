"""独立读取真实层级字段和追加单选控件产物，不依赖浏览器或 pdf-lib 模型。"""
from __future__ import annotations

import hashlib
import json
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


def verify(directory: Path) -> dict:
    source = PdfReader(directory / 'source.pdf')
    results = []
    before_append = None
    for label in ('name', 'code', 'radio', 'append', 'filled'):
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
                key = (ref.idnum, ref.generation)
                assert key not in seen
                seen.add(key)
                node = ref.get_object()
                part = str(node['/T'])
                assert part and '.' not in part and part not in names
                names.add(part)
                if parent is None:
                    assert '/Parent' not in node
                else:
                    assert node['/Parent'].indirect_reference == parent
                name = prefix + part
                if '/FT' not in node:
                    assert node['/Kids']
                    walk(node['/Kids'], ref, name + '.')
                    continue
                fields[name] = node
                for kid in node['/Kids']:
                    widget = kid.get_object()
                    assert widget['/Parent'].indirect_reference == ref
                    assert widget['/Subtype'] == '/Widget'
                    assert widget['/P'].indirect_reference == reader.pages[0].indirect_reference
                    normal = widget['/AP']['/N']
                    if hasattr(normal, 'get_data'):
                        assert normal.get_data()
                    else:
                        for stream in normal.values():
                            assert stream.get_object().get_data()
                    widgets.append(kid)

        walk(reader.trailer['/Root']['/AcroForm']['/Fields'])
        assert list(reader.pages[0]['/Annots']) == widgets
        expected = ['party.customer.name']
        if label != 'name':
            expected.append('party.customer.code')
        if label in ('radio', 'append', 'filled'):
            expected.append('party.consent')
        assert list(fields) == expected
        assert fields['party.customer.name']['/V'] == 'Alice'
        if label != 'name':
            assert fields['party.customer.code']['/V'] == 'C001'
        if 'party.consent' in fields:
            radio = fields['party.consent']
            assert radio['/FT'] == '/Btn' and radio.get('/Ff', 0) & 32768
            assert bool(radio.get('/Ff', 0) & 2)
            appended = label in ('append', 'filled')
            assert radio['/Opt'] == (['Yes', 'No', 'Maybe'] if appended else ['Yes', 'No'])
            assert len(radio['/Kids']) == (3 if appended else 2)
            assert radio['/V'] == ('/2' if label == 'filled' else '/1')
            expected_states = ['/Off', '/Off', '/2'] if label == 'filled' else ['/Off', '/1', '/Off'] if appended else ['/Off', '/1']
            assert [kid.get_object()['/AS'] for kid in radio['/Kids']] == expected_states
            survivor = []
            for kid in radio['/Kids'][:2]:
                widget = kid.get_object()
                streams = [stream.get_object().get_data() for _, states in sorted(widget['/AP'].items()) for _, stream in sorted(states.get_object().items())]
                survivor.append((kid.idnum, kid.generation, canonical(widget), [hashlib.sha256(stream).hexdigest() for stream in streams]))
            if label == 'radio':
                before_append = survivor
            elif label == 'append':
                assert survivor == before_append
                assert list(radio['/Kids'][-1].get_object()['/Rect']) == [130, 170, 150, 190]
        results.append({'label': label, 'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'fields': list(fields), 'bodyPreserved': True, 'canonicalTreeVerified': True,
                        'appearanceVerified': True, 'radioSurvivorsVerified': label == 'append'})
    return {'ok': True, 'sourceSha256': hashlib.sha256((directory / 'source.pdf').read_bytes()).hexdigest(), 'checks': results}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
