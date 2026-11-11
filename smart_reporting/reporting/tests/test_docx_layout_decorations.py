from io import BytesIO

import pytest
from docx import Document
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_notes_decorations import notes_source, plan
from smart_reporting.reporting.tests.test_docx_paragraph_borders import op as border_op, pbdr_of, single
from smart_reporting.reporting.tests.test_docx_paragraph_shading import op as shade_op, shd_of


def layout(data):
    block = inspect_docx(data)['blocks'][0]
    anchor = {key: block[key] for key in ('blockId', 'expectedObjectSha256')}
    return [
        {'kind': 'setParagraphAlignment', **anchor, 'alignment': 'center'},
        {'kind': 'setParagraphIndent', **anchor, 'twips': 720},
        {'kind': 'setParagraphRightIndent', **anchor, 'twips': 360},
        {'kind': 'setParagraphSpacing', **anchor, 'spaceBefore': 240, 'spaceAfter': 120, 'lineSpacing': 1.5},
    ]


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
@pytest.mark.parametrize('action', ['existing', 'insert', 'update', 'delete'])
@pytest.mark.parametrize('reverse', [False, True])
def test_notes_body_layout_and_both_decorations_compose_from_current_ppr(kind, action, reverse):
    data = notes_source(kind); source = Document(BytesIO(data))
    body, note_ops = plan(data, action, kind)
    operations = [shade_op(data, 'edf5fc'), border_op(data, [single('bottom', 'FF0000', 1)]), *layout(data), body, *note_ops]
    output = patch_docx(data, operations[::-1] if reverse else operations)
    saved = Document(BytesIO(output)); paragraph = saved.paragraphs[0]
    assert paragraph.text == 'A😀新增BC'
    assert paragraph.paragraph_format.keep_with_next
    assert paragraph.paragraph_format.left_indent.twips == 720
    assert paragraph.paragraph_format.right_indent.twips == 360
    assert paragraph.paragraph_format.space_before.twips == 240
    assert paragraph.paragraph_format.space_after.twips == 120
    assert paragraph.paragraph_format.line_spacing == 1.5
    assert paragraph._p.pPr.find(qn('w:jc')).get(qn('w:val')) == 'center'
    assert shd_of(output) == ('clear', 'auto', 'edf5fc')
    assert pbdr_of(output)['bottom']['color'] == 'FF0000'
    assert etree.tostring(saved.paragraphs[1]._p) == etree.tostring(source.paragraphs[1]._p)
    assert next(run for run in paragraph.runs if run.text == '新增')._r.rPr.find(qn('w:noProof')) is not None
    notes = inspect_docx(output)['notes'][kind + 's']
    assert [note['text'] for note in notes] == ([] if action == 'delete' else ['来源注释', '新增注释'] if action == 'insert' else ['更正注释'] if action == 'update' else ['来源注释'])


@pytest.mark.parametrize('reverse', [False, True])
def test_plain_body_layout_and_decorations_without_notes(reverse):
    document = Document(); document.add_paragraph('Plain'); out = BytesIO(); document.save(out); data = out.getvalue()
    block = inspect_docx(data)['blocks'][0]
    body = {'kind': 'patchParagraphRuns', **{key: block[key] for key in ('blockId', 'expectedObjectSha256')}, 'runs': [{'sourceFrom': 0, 'sourceTo': 5}, {'text': '新增', 'inheritFrom': 0, 'style': {'bold': True}}]}
    operations = [body, *layout(data), shade_op(data, 'edf5fc'), border_op(data, [single('bottom', 'FF0000', 1)])]
    output = patch_docx(data, operations[::-1] if reverse else operations)
    paragraph = Document(BytesIO(output)).paragraphs[0]
    assert paragraph.text == 'Plain新增' and paragraph.runs[-1].bold
    assert paragraph.paragraph_format.left_indent.twips == 720
    assert paragraph.paragraph_format.right_indent.twips == 360
    assert paragraph.paragraph_format.space_before.twips == 240
    assert paragraph.paragraph_format.line_spacing == 1.5
    assert shd_of(output) == ('clear', 'auto', 'edf5fc') and 'bottom' in pbdr_of(output)


@pytest.mark.parametrize('fault', ['hash', 'fields', 'layout_value', 'protection'])
def test_combined_layout_decorations_keeps_source_and_field_guards(fault):
    data = notes_source(); body, notes = plan(data)
    operations = [body, *layout(data), shade_op(data, 'edf5fc'), border_op(data, [single('bottom', 'FF0000', 1)]), *notes]
    if fault == 'hash': operations[2]['expectedObjectSha256'] = 'foreign'
    elif fault == 'fields': operations[1]['rawPPr'] = '<evil/>'
    elif fault == 'layout_value': operations[2]['twips'] = 1
    else:
        from docx.oxml import OxmlElement
        document = Document(BytesIO(data)); protection = OxmlElement('w:documentProtection'); protection.set(qn('w:enforcement'), '1'); protection.set(qn('w:edit'), 'readOnly'); document.settings.element.append(protection)
        out = BytesIO(); document.save(out); data = out.getvalue()
    with pytest.raises(ValueError): patch_docx(data, operations)
