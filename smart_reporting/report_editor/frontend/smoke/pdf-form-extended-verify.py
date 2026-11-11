"""独立复读浏览器真实下载，验证表单扩展和原始正文。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from pypdf import PdfReader


def verify(directory: Path) -> dict:
    source_path = directory / 'source.pdf'
    source = PdfReader(source_path)
    names = ['customer_date', 'customer_choice', 'customer_radio']
    assert not source.get_fields()
    results = []
    for label, count in [('date', 1), ('choice', 2), ('radio', 3), ('filled', 3), ('properties', 3), ('arrange', 3)]:
        path = directory / f'{label}-downloaded.pdf'
        reader = PdfReader(path)
        assert len(reader.pages) == len(source.pages) == 3
        assert list(reader.get_fields()) == names[:count]
        for actual, original in zip(reader.pages, source.pages):
            assert actual.extract_text() == original.extract_text()
            assert original.get_contents().get_data() in actual.get_contents().get_data()
            assert list(actual.mediabox) == list(original.mediabox)
            assert list(actual.cropbox) == list(original.cropbox)
            assert actual.rotation == original.rotation
        roots = reader.trailer['/Root']['/AcroForm']['/Fields']
        widget_refs = []
        for root in roots:
            field = root.get_object()
            for kid in field['/Kids']:
                widget = kid.get_object()
                widget_refs.append(kid)
                assert widget['/Subtype'] == '/Widget'
                assert widget['/Parent'].indirect_reference == root
                assert widget['/P'].indirect_reference == reader.pages[0].indirect_reference
                appearance = widget['/AP']['/N']
                if hasattr(appearance, 'get_data'):
                    assert appearance.get_data()
                else:
                    for stream in appearance.values():
                        assert stream.get_object().get_data()
        assert list(reader.pages[0]['/Annots']) == widget_refs
        filled = label in ('filled', 'properties', 'arrange')
        date = roots[0].get_object()
        assert date['/FT'] == '/Tx'
        assert date['/V'] == ('2026-12-25' if filled else '2026-11-11')
        assert bool(date.get('/Ff', 0) & 2) == (label not in ('properties', 'arrange'))
        for owner in (date, date['/Kids'][0].get_object()):
            assert owner['/AA']['/F']['/JS'] == 'AFDate_FormatEx("yyyy-mm-dd");'
            assert owner['/AA']['/K']['/JS'] == 'AFDate_KeystrokeEx("yyyy-mm-dd");'
        if count >= 2:
            choice = roots[1].get_object()
            assert choice['/FT'] == '/Ch' and choice['/V'] == ('One' if filled else 'Two')
            assert [option[0] if isinstance(option, list) else option for option in choice['/Opt']] == ['One', 'Two']
        if count >= 3:
            radio = roots[2].get_object()
            assert radio['/FT'] == '/Btn' and radio.get('/Ff', 0) & 32768
            assert radio['/Opt'] == ['Yes', 'No']
            assert radio['/V'] == ('/1' if filled else '/0')
            assert [kid.get_object()['/AS'] for kid in radio['/Kids']] == (['/Off', '/1'] if filled else ['/0', '/Off'])
        if label in ('properties', 'arrange'):
            assert list(date['/Kids'][0].get_object()['/Rect']) == [40, 190, 160, 214]
        if label == 'arrange':
            assert list(roots[1].get_object()['/Kids'][0].get_object()['/Rect']) == [40, 140, 160, 164]
        results.append({'label': label, 'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'fields': names[:count], 'bodyPreserved': True, 'appearanceVerified': True, 'valuesVerified': True})
    return {'ok': True, 'sourceSha256': hashlib.sha256(source_path.read_bytes()).hexdigest(), 'checks': results}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]))))
