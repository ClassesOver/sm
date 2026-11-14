"""完整字体对话框沿既有字符格式及来源run计划写回。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    p = doc.add_paragraph()
    for text, latin, asian, color, bold in [('Latin', 'Cambria', '宋体', '112233', True), (' 中文', 'Arial', '楷体', '445566', False)]:
        run = p.add_run(text); run.bold = bold
        fonts = OxmlElement('w:rFonts')
        for name, value in {'ascii': latin, 'hAnsi': latin, 'eastAsia': asian, 'cs': 'Arial', 'cstheme': 'minorBidi'}.items(): fonts.set(qn('w:' + name), value)
        run._r.get_or_add_rPr().append(fonts)
        for tag, attrs in [('color', {'val': color}), ('lang', {'val': 'en-US', 'eastAsia': 'zh-CN'}), ('bdr', {'val': 'single', 'sz': '4', 'color': '778899'})]:
            child = OxmlElement('w:' + tag)
            for name, value in attrs.items(): child.set(qn('w:' + name), value)
            run._r.rPr.append(child)
    doc.add_paragraph('邻段不得改变')
    doc.sections[0].header.paragraphs[0].text = '页眉不得改变'
    stream = BytesIO(); doc.save(stream); return stream.getvalue()


def operation(data, style, kind='formatRange', **extra):
    target = inspect_docx(data)['blocks'][0]
    return {'kind': kind, 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256'],
            **({'from': 1, 'to': 7} if kind == 'formatRange' else {}), 'style': {'fontDialog': True, **style}, **extra}


def test_complete_font_dialog_writes_both_slots_and_advanced_fields_without_flattening_source_runs():
    before = source()
    values = {'fontAscii': 'Calibri', 'eastAsiaFont': '仿宋', 'charScalePct': 125, 'charSpacingTwips': 25,
              'positionHalfPoints': 5, 'kernHalfPoints': 20, 'dstrike': True, 'caps': 'small', 'vanishOwn': True}
    after = patch_docx(before, [operation(before, values)])
    old, new = Document(BytesIO(before)), Document(BytesIO(after))
    assert new.paragraphs[0].text == old.paragraphs[0].text
    assert new.paragraphs[1]._p.xml == old.paragraphs[1]._p.xml
    selected = [run for run in new.paragraphs[0].runs if run.text in ('atin', ' 中')]
    assert len(selected) == 2
    for run in selected:
        fonts = run._r.rPr.find(qn('w:rFonts'))
        assert fonts.get(qn('w:ascii')) == fonts.get(qn('w:hAnsi')) == 'Calibri'
        assert fonts.get(qn('w:eastAsia')) == '仿宋'
        assert fonts.get(qn('w:cs')) == 'Arial'
        assert fonts.get(qn('w:cstheme')) == 'minorBidi'
        for tag, value in [('w', '125'), ('spacing', '25'), ('position', '5'), ('kern', '20')]:
            assert run._r.rPr.find(qn('w:' + tag)).get(qn('w:val')) == value
        for tag in ['lang', 'bdr', 'dstrike', 'smallCaps', 'vanish']:
            assert run._r.rPr.find(qn('w:' + tag)) is not None
    assert selected[0].bold is True and selected[1].bold is False
    assert selected[0].font.color.rgb != selected[1].font.color.rgb
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        for name in a.namelist():
            if name not in ('word/document.xml', 'docProps/core.xml'): assert a.read(name) == b.read(name), name


@pytest.mark.parametrize('style', [{'charScalePct': 0}, {'charScalePct': 601}, {'dstrike': 'false'}, {'charSpacingTwips': True}, {'caps': 'weird'}, {'fontAscii': '<bad\x00>'}])
def test_complete_font_dialog_rejects_invalid_fields(style):
    data = source()
    with pytest.raises(ValueError): patch_docx(data, [operation(data, style)])


def test_font_dialog_explicit_off_and_direct_property_clear_preserve_untouched_slots_and_unknown_properties():
    before = source()
    values = {'fontAscii': 'Calibri', 'eastAsiaFont': '仿宋', 'charScalePct': 125, 'charSpacingTwips': 25,
              'positionHalfPoints': 5, 'kernHalfPoints': 20, 'dstrike': True, 'caps': 'small', 'vanishOwn': True}
    formatted = patch_docx(before, [operation(before, values, kind='formatParagraph')])
    cleared = patch_docx(formatted, [operation(formatted, {'fontAscii': None, 'charScalePct': None, 'charSpacingTwips': None,
                           'positionHalfPoints': None, 'kernHalfPoints': 0, 'dstrike': False, 'caps': 'none', 'vanishOwn': False}, kind='formatParagraph')])
    for run in Document(BytesIO(cleared)).paragraphs[0].runs:
        props = run._r.rPr; fonts = props.find(qn('w:rFonts'))
        assert fonts.get(qn('w:ascii')) is None and fonts.get(qn('w:hAnsi')) is None
        assert fonts.get(qn('w:eastAsia')) == '仿宋'
        assert fonts.get(qn('w:cs')) == 'Arial' and fonts.get(qn('w:cstheme')) == 'minorBidi'
        for tag in ['w', 'spacing', 'position']: assert props.find(qn('w:' + tag)) is None
        for tag in ['dstrike', 'caps', 'smallCaps', 'vanish', 'kern']: assert props.find(qn('w:' + tag)).get(qn('w:val')) in ('0', 'false')
        for tag in ['lang', 'bdr']: assert props.find(qn('w:' + tag)) is not None


def test_font_mode_remains_strict_and_protected_sources_are_rejected():
    data = source()
    for values in [{'fontDialog': False, 'charScalePct': 125}, {'fontDialog': 'true', 'fontAscii': 'Calibri'}, {'unknown': 1}]:
        with pytest.raises(ValueError): patch_docx(data, [operation(data, values)])
    raw = operation(data, {'fontAscii': 'Calibri'}); raw['style'].pop('fontDialog')
    with pytest.raises(ValueError): patch_docx(data, [raw])
    doc = Document(BytesIO(data)); protection = OxmlElement('w:documentProtection'); protection.set(qn('w:edit'), 'trackedChanges'); protection.set(qn('w:enforcement'), '1'); doc.settings.element.append(protection)
    out = BytesIO(); doc.save(out); protected = out.getvalue()
    assert inspect_docx(protected)['blocks'][0]['fontDialogEditable'] is False
    with pytest.raises(ValueError): patch_docx(protected, [operation(protected, {'fontAscii': 'Calibri'})])


def test_latin_only_slot_change_and_clear_never_invent_an_asian_slot():
    doc = Document(BytesIO(source()))
    for run in doc.paragraphs[0].runs: run._r.rPr.find(qn('w:rFonts')).attrib.pop(qn('w:eastAsia'))
    out = BytesIO(); doc.save(out); before = out.getvalue()
    for value in ['Calibri', None]:
        after = patch_docx(before, [operation(before, {'fontAscii': value}, kind='formatParagraph')])
        for run in Document(BytesIO(after)).paragraphs[0].runs:
            fonts = run._r.rPr.find(qn('w:rFonts'))
            assert fonts.get(qn('w:ascii')) == value and fonts.get(qn('w:hAnsi')) == value
            assert fonts.get(qn('w:eastAsia')) is None
            assert fonts.get(qn('w:cs')) == 'Arial' and fonts.get(qn('w:cstheme')) == 'minorBidi'
