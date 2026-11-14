"""Source paragraph commands checked through independent python-pptx/ZIP readers."""
import json
import subprocess
from io import BytesIO
from unittest.mock import Mock

import pytest
from lxml import etree
from pptx import Presentation
from pptx.oxml.xmlchemy import OxmlElement

from smart_reporting.report_editor.native_office import (
    _NUMBERING_TYPES,
    inspect_office,
    patch_office,
)
from smart_reporting.reporting.tests.test_pptx_paragraph_spacing import (
    ENGINE,
    NS,
    apply,
    assert_preserved,
    source_bytes,
    target,
    xml,
)


def levels_source():
    deck = Presentation(BytesIO(source_bytes()))
    for paragraph, level in zip(deck.slides[0].shapes[0].text_frame.paragraphs, [0, 8]):
        paragraph.level = level
        ppr = paragraph._p.get_or_add_pPr()
        ppr.set('marL', str(285750 * (level + 1)))
        ppr.set('indent', '-285750')
    stream = BytesIO()
    deck.save(stream)
    return stream.getvalue()


def ordered(source, *patches):
    return patch_office('pptx', source, [{'kind': 'editSlides', 'paragraphFormatting': [
        {'slideIndex': 0, 'elementId': target(source)['id'], **patch} for patch in patches
    ]}])


def test_indent_order_clamps_each_paragraph_and_preserves_runs_spacing_and_other_objects():
    source = levels_source()
    reverse = ordered(source, {'indentDelta': -1}, {'indentDelta': 1})
    assert [p.level for p in Presentation(BytesIO(reverse)).slides[0].shapes[0].text_frame.paragraphs] == [1, 8]
    output = ordered(source, {'indentDelta': 1}, {'indentDelta': -1}, {'rtl': False})
    paragraphs = Presentation(BytesIO(output)).slides[0].shapes[0].text_frame.paragraphs
    assert [p.level for p in paragraphs] == [0, 7]
    assert [p.line_spacing.pt for p in paragraphs] == [18, 19]
    assert all(p.runs[0].font.name == 'Arial' and p.runs[0].font.bold for p in paragraphs)
    props = xml(output).xpath('//p:sp[1]//a:pPr', namespaces=NS)
    assert [p.get('marL') for p in props] == ['285750', '2286000']
    assert [p.get('rtl') for p in props] == ['0', '0']
    # Exact comparison after removing only changed attributes and engine creation metadata.
    before, after = xml(source), xml(output)
    for tree in [before, after]:
        for node in tree.xpath('//p:sp[1]/p:nvSpPr/p:cNvPr/a:extLst', namespaces=NS):
            node.getparent().remove(node)
        for ppr in tree.xpath('//p:sp[1]//a:pPr', namespaces=NS):
            for key in ['lvl', 'marL', 'rtl']:
                ppr.attrib.pop(key, None)
    assert etree.tostring(before) == etree.tostring(after)
    states = target(output)['paragraphLists']
    assert [s['level'] or 0 for s in states] == [0, 7]
    assert [s['rtl'] for s in states] == [False, False]


@pytest.mark.parametrize('num_type', sorted(_NUMBERING_TYPES))
def test_all_source_number_formats_and_start_bounds_roundtrip(num_type):
    output = apply(source_bytes(), bullet='number', numType=num_type, startAt=32767)
    props = xml(output).xpath('//p:sp[1]//a:buAutoNum', namespaces=NS)
    assert len(props) == 2
    assert all(node.attrib == {'type': num_type, 'startAt': '32767'} for node in props)
    assert all(s['numType'] == num_type and s['startAt'] == 32767 for s in target(output)['paragraphLists'])


@pytest.mark.parametrize('glyph,font', [('•', 'Arial'), ('o', 'Courier New'), ('§', 'Wingdings'), ('😀', 'Arial')])
def test_glyph_font_size_color_hang_and_none_have_source_semantics(glyph, font):
    source = source_bytes()
    output = apply(source, bullet='char', bulletChar=glyph, bulletFont=font,
                   bulletSizePct=125, bulletColor='#C43E1C', bulletHangEmu=171450)
    props = xml(output).xpath('//p:sp[1]//a:pPr', namespaces=NS)
    for ppr in props:
        assert ppr.find('a:buChar', NS).get('char') == glyph
        assert ppr.find('a:buFont', NS).get('typeface') == font
        assert ppr.find('a:buSzPct', NS).get('val') == '125000'
        assert ppr.find('a:buClr/a:srgbClr', NS).get('val') == 'C43E1C'
        assert ppr.get('marL') == '171450' and ppr.get('indent') == '-171450'
    removed = apply(output, bullet='none')
    for ppr in xml(removed).xpath('//p:sp[1]//a:pPr', namespaces=NS):
        assert ppr.find('a:buNone', NS) is not None
        assert ppr.find('a:buChar', NS) is None and ppr.find('a:buAutoNum', NS) is None
        assert ppr.get('marL') == '0' and ppr.get('indent') == '0'
    assert all(p.runs[0].font.name == 'Arial' for p in Presentation(BytesIO(removed)).slides[0].shapes[0].text_frame.paragraphs)


def test_unset_state_and_existing_picture_bullet_preserved_by_direction():
    plain = inspect_office('pptx', source_bytes())['slides'][0]['elements'][1]['paragraphLists'][0]
    assert all(plain[key] is None for key in ['bulletKind', 'bulletChar', 'bulletFont', 'numType', 'startAt', 'bulletSizePct', 'bulletSizePt', 'bulletColor', 'rtl', 'level', 'indentEmu'])
    assert plain['marLEmu'] == 0  # Pinned parser resolves inherited/default left margin.
    deck = Presentation(BytesIO(source_bytes()))
    ppr = deck.slides[0].shapes[0].text_frame.paragraphs[0]._p.get_or_add_pPr()
    ppr.remove(ppr.find('a:buChar', NS))
    # A genuine pre-existing image relationship stays opaque/read-only to the API.
    from PIL import Image
    image = BytesIO()
    Image.new('RGB', (2, 2), '#008080').save(image, format='PNG')
    image.seek(0)
    _, relationship = deck.slides[0].part.get_or_add_image_part(image)
    node = OxmlElement('a:buBlip')
    blip = OxmlElement('a:blip')
    blip.set('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed', relationship)
    node.append(blip)
    ppr.append(node)
    stream = BytesIO()
    deck.save(stream)
    source = stream.getvalue()
    state = target(source)['paragraphLists'][0]
    assert state['bulletKind'] == 'blip'
    assert not any('xml' in k.lower() or 'media' in k.lower() for k in state)
    output = apply(source, rtl=False)
    assert etree.tostring(xml(source).find('.//a:buBlip', NS)) == etree.tostring(xml(output).find('.//a:buBlip', NS))
    assert_preserved(source, apply(source, align='right'), ['algn'])


INVALID = [
    {'bullet': 'blip'}, {'bulletBlip': {'mediaRef': '../../etc/passwd'}},
    {'bullet': 'none', 'bulletColor': '#000000'}, {'bullet': 'char', 'numType': 'arabicPeriod'},
    {'bulletChar': 'x'}, {'bullet': 'number', 'bulletFont': 'Arial'},
    {'bullet': 'char', 'bulletChar': ''}, {'bullet': 'char', 'bulletChar': 'ab'},
    {'bullet': 'char', 'bulletChar': '\n'}, {'bullet': 'char', 'bulletChar': '\ufffe'},
    {'bullet': 'char', 'bulletFont': 'bad\uffff'}, {'numType': 'not-a-source-choice'},
    {'startAt': 0}, {'startAt': 32768}, {'startAt': True}, {'startAt': 1.5},
    {'bulletHangEmu': -1}, {'bulletHangEmu': 51206401}, {'bulletHangEmu': 1.5},
    {'bulletSizePct': 80}, {'bulletSizePct': True}, {'bulletColor': '#abc'},
    {'rtl': 1}, {'rtl': None}, {'indentDelta': 0}, {'indentDelta': True},
    {'indentDelta': 2}, {'marL': 0}, {'level': 0},
]


@pytest.mark.parametrize('fields', INVALID)
def test_invalid_schema_rejected_before_engine(monkeypatch, fields):
    from smart_reporting.report_editor.pptx_engine import PptxEngine
    engine = Mock(side_effect=AssertionError('invalid input reached engine'))
    monkeypatch.setattr(PptxEngine, '_run_engine', engine)
    with pytest.raises(ValueError):
        patch_office('pptx', b'source', [{'kind': 'editSlides', 'paragraphFormatting': [
            {'slideIndex': 0, 'elementId': 'x', **fields}]}])
    engine.assert_not_called()


def test_direct_bridge_strict_validation_and_level_dependent_overflow_never_write(tmp_path):
    source = tmp_path / 'source.pptx'
    source.write_bytes(levels_source())
    output = tmp_path / 'output.pptx'
    element_id = target(source.read_bytes())['id']
    for fields in [*INVALID, {'bulletHangEmu': 51206400}]:
        request = tmp_path / 'request.json'
        request.write_text(json.dumps({'action': 'edit', 'input': str(source), 'output': str(output),
            'paragraphFormatting': [{'slideIndex': 0, 'elementId': element_id, **fields}]}))
        result = subprocess.run(['node', 'dist/edit-pptx.mjs', str(request)], cwd=ENGINE, capture_output=True, timeout=30)
        assert result.returncode != 0, fields
        assert not output.exists(), fields
    # The same OOXML limit is valid at level zero, rather than an arbitrary /9 cap.
    output_bytes = apply(source_bytes(), bulletHangEmu=51206400)
    assert all(s['marLEmu'] == 51206400 for s in target(output_bytes)['paragraphLists'])


@pytest.mark.parametrize('size,hang', [(75, 171450), (90, 285750), (100, 342900), (125, 0), (150, 51206400)])
def test_source_size_choices_hang_presets_and_standalone_number_updates(size, hang):
    source = apply(source_bytes(), bullet='number', numType='romanUcPeriod', startAt=9)
    output = ordered(source, {'startAt': 1}, {'numType': 'alphaLcPeriod'},
                     {'bulletSizePct': size}, {'bulletHangEmu': hang})
    for ppr in xml(output).xpath('//p:sp[1]//a:pPr', namespaces=NS):
        assert ppr.find('a:buAutoNum', NS).attrib == {'type': 'alphaLcPeriod', 'startAt': '1'}
        assert ppr.find('a:buSzPct', NS).get('val') == str(size * 1000)
        assert ppr.get('marL') == str(hang) and ppr.get('indent') == str(-hang)


def test_noneditable_table_target_is_rejected_by_native_and_direct_bridge(tmp_path):
    deck = Presentation(BytesIO(source_bytes()))
    deck.slides[0].shapes.add_table(1, 1, 914400, 914400, 914400, 914400).table.cell(0, 0).text = 'Read only table'
    stream = BytesIO()
    deck.save(stream)
    source_bytes_value = stream.getvalue()
    table = inspect_office('pptx', source_bytes_value)['slides'][0]['elements'][-1]
    assert table['type'] == 'table' and table['editable'] is False
    record = {'slideIndex': 0, 'elementId': table['id'], 'bullet': 'char', 'bulletHangEmu': 51206400}
    with pytest.raises(ValueError):
        patch_office('pptx', source_bytes_value, [{'kind': 'editSlides', 'paragraphFormatting': [record]}])
    source, output, request = [tmp_path / name for name in ['source.pptx', 'output.pptx', 'request.json']]
    source.write_bytes(source_bytes_value)
    request.write_text(json.dumps({'action': 'edit', 'input': str(source), 'output': str(output), 'paragraphFormatting': [record]}))
    result = subprocess.run(['node', 'dist/edit-pptx.mjs', str(request)], cwd=ENGINE, capture_output=True, timeout=30)
    assert result.returncode != 0 and not output.exists()


@pytest.mark.parametrize('own_margin,own_indent,inherited,expected', [
    (171450, -171450, False, True),
    (None, -171450, False, False),
    (171450, 0, False, False),
    (None, None, True, False),
])
def test_inspect_reports_exact_source_condition_for_indent_delta_margin_recalculation(own_margin, own_indent, inherited, expected):
    deck = Presentation(BytesIO(source_bytes()))
    frame = deck.slides[0].shapes[0].text_frame
    ppr = frame.paragraphs[0]._p.get_or_add_pPr()
    for key, value in [('marL', own_margin), ('indent', own_indent)]:
        ppr.attrib.pop(key, None)
        if value is not None:
            ppr.set(key, str(value))
    if inherited:
        level = OxmlElement('a:lvl1pPr')
        level.set('marL', '171450')
        level.set('indent', '-171450')
        frame._txBody.find('a:lstStyle', NS).append(level)
    stream = BytesIO()
    deck.save(stream)
    source = stream.getvalue()
    raw = xml(source).xpath('//p:sp[1]//a:p[1]/a:pPr', namespaces=NS)[0]
    assert ('marL' in raw.attrib) is (own_margin is not None)
    state = target(source)['paragraphLists'][0]
    assert state['hasExplicitHangingIndent'] is expected
    if own_indent is not None or inherited:
        assert state['indentEmu'] == (own_indent if own_indent is not None else -171450)
