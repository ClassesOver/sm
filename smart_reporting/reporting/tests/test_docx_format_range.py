"""formatRange: partial-paragraph character formatting through the native docx bridge."""
from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from docx.shared import Pt, RGBColor

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source() -> bytes:
    doc = Document()
    paragraph = doc.add_paragraph()
    paragraph.add_run('前半部分')
    styled = paragraph.add_run('后半部分')
    styled.italic = True
    styled.font.size = Pt(14)
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def op(block, start, end, style):
    return {'kind': 'formatRange', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'from': start, 'to': end, 'style': style}


def runs(content):
    paragraph = Document(BytesIO(content)).paragraphs[0]
    return [(run.text, bool(run.bold), bool(run.italic), run.font.size.pt if run.font.size else None,
             str(run.font.color.rgb) if run.font.color and run.font.color.type else None) for run in paragraph.runs]


def test_ranges_split_runs_and_keep_formatting_outside_them():
    data = source()
    block = inspect_docx(data)['blocks'][0]
    patched = patch_docx(data, [op(block, 2, 6, {'bold': True}), op(block, 6, 8, {'color': 'c00000'})])
    assert runs(patched) == [
        ('前半', False, False, None, None),
        ('部分', True, False, None, None),
        ('后半', True, True, 14.0, None),
        ('部分', False, True, 14.0, 'C00000'),
    ]
    assert ''.join(run[0] for run in runs(patched)) == '前半部分后半部分'


def test_clear_local_font_properties_restores_inheritance_and_preserves_other_parts():
    from zipfile import ZipFile
    doc = Document()
    styled = doc.add_paragraph().add_run('abcd')
    styled.font.name = 'Arial'
    styled.font.size = Pt(14)
    styled.font.color.rgb = RGBColor.from_string('112233')
    styled.bold = True
    stream = BytesIO()
    doc.save(stream)
    data = stream.getvalue()
    block = inspect_docx(data)['blocks'][0]
    patched = patch_docx(data, [op(block, 1, 3, {'fontFamily': None, 'fontSize': None, 'color': None})])
    paragraph = Document(BytesIO(patched)).paragraphs[0]
    assert [(r.text, r.font.name, r.font.size.pt if r.font.size else None, str(r.font.color.rgb) if r.font.color.rgb else None, r.bold) for r in paragraph.runs] == [
        ('a', 'Arial', 14, '112233', True), ('bc', None, None, None, True), ('d', 'Arial', 14, '112233', True)]
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(patched)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('bad', [
    {'from': 3, 'to': 3}, {'from': 0, 'to': 99}, {'from': -1, 'to': 2},
    {'style': {}}, {'style': {'highlight': 'invalid'}}, {'style': {'bold': 'yes'}}, {'extra': 1},
])
def test_invalid_ranges_and_styles_are_rejected(bad):
    data = source()
    block = inspect_docx(data)['blocks'][0]
    with pytest.raises(ValueError):
        patch_docx(data, [{**op(block, 0, 2, {'bold': True}), **bad}])


def test_selected_highlight_and_vertical_alignment_preserve_mixed_runs_and_other_parts():
    from zipfile import ZipFile
    from docx.enum.text import WD_COLOR_INDEX
    from docx.oxml.ns import qn
    doc = Document(); paragraph = doc.add_paragraph()
    paragraph.add_run('A😀').bold = True
    run = paragraph.add_run('BC'); run.italic = True; run.font.highlight_color = WD_COLOR_INDEX.YELLOW; run.font.superscript = True
    paragraph.add_run('尾').font.subscript = True
    stream = BytesIO(); doc.save(stream); data = stream.getvalue(); block = inspect_docx(data)['blocks'][0]
    output = patch_docx(data, [op(block, 1, 4, {'highlight': 'cyan', 'vertAlign': 'subscript'}), op(block, 4, 5, {'highlight': 'none', 'vertAlign': 'baseline'})])
    result = Document(BytesIO(output)).paragraphs[0].runs
    assert [(r.text, r.bold, r.italic, r._r.rPr.find(qn('w:highlight')).get(qn('w:val')) if r._r.rPr is not None and r._r.rPr.find(qn('w:highlight')) is not None else None,
        r._r.rPr.find(qn('w:vertAlign')).get(qn('w:val')) if r._r.rPr is not None and r._r.rPr.find(qn('w:vertAlign')) is not None else None) for r in result] == [
        ('A', True, None, None, None), ('😀', True, None, 'cyan', 'subscript'), ('B', None, True, 'cyan', 'subscript'), ('C', None, True, 'none', 'baseline'), ('尾', None, None, None, 'subscript')]
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}: assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('style', [{'highlight': None}, {'highlight': '#ffff00'}, {'vertAlign': None}, {'vertAlign': 'super'}])
def test_selected_highlight_and_vertical_reject_invalid_values(style):
    data = source(); block = inspect_docx(data)['blocks'][0]
    with pytest.raises(ValueError): patch_docx(data, [op(block, 0, 2, style)])


def test_selected_highlight_and_vertical_do_not_split_utf16_surrogate_pairs():
    doc = Document(); doc.add_paragraph('A😀B'); stream = BytesIO(); doc.save(stream); data = stream.getvalue(); block = inspect_docx(data)['blocks'][0]
    for start, end in [(1, 2), (2, 3)]:
        with pytest.raises(ValueError): patch_docx(data, [op(block, start, end, {'highlight': 'yellow', 'vertAlign': 'superscript'})])
