from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_notes import insert, note_operation, replace_parts, xml, NS
from smart_reporting.reporting.tests.test_docx_paragraph_borders import op as border_op, pbdr_of, single, W
from smart_reporting.reporting.tests.test_docx_paragraph_shading import op as shade_op, shd_of


def notes_source(kind='footnote'):
    document = Document(); paragraph = document.add_paragraph()
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run('A😀'); run.bold = True
    run._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
    paragraph.add_run('BC').italic = True; document.add_paragraph('Untouched')
    out = BytesIO(); document.save(out); data = out.getvalue()
    data = patch_docx(data, [insert(inspect_docx(data), kind, text='来源注释')])
    root = xml(data, 'word/document.xml')
    marker_run = root.xpath(f'//w:{kind}Reference/..', namespaces=NS)[0]
    marker_run.find(qn('w:rPr')).append(OxmlElement('w:noProof'))
    return replace_parts(data, {'word/document.xml': etree.tostring(root)})


def plan(data, action='existing', kind='footnote'):
    model = inspect_docx(data); block = model['blocks'][0]; note = model['notes'][kind + 's'][0]
    anchor = {key: block[key] for key in ('blockId', 'expectedObjectSha256')}
    runs = [{'sourceFrom': 0, 'sourceTo': 3}, {'text': '新增', 'inheritFrom': 1, 'style': {'color': '0070C0'}}]
    if action != 'delete': runs.append({'noteKind': kind, 'noteId': note['id'], 'referenceIndex': 0})
    runs.append({'sourceFrom': 4, 'sourceTo': 6, 'style': {'bold': True}})
    note_ops = []
    if action == 'insert':
        note_ops = [insert(model, kind, offset=8, text='新增注释')]
        runs.append({'noteOperationIndex': 0})
    elif action == 'update': note_ops = [{**note_operation(note, text='更正注释'), 'noteKind': kind}]
    elif action == 'delete': note_ops = [{**note_operation(note, 'deleteNote', expectedReferences=note['references']), 'noteKind': kind}]
    return {'kind': 'patchParagraphRuns', **anchor, 'runs': runs}, note_ops


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
@pytest.mark.parametrize('action', ['existing', 'insert', 'update', 'delete'])
@pytest.mark.parametrize('reverse', [False, True])
def test_trusted_notes_body_decorations_and_note_edits_are_atomic(kind, action, reverse):
    data = notes_source(kind); model = inspect_docx(data); block = model['blocks'][0]
    assert block['editable'] is False
    assert block['paragraphShadingEditable'] is True
    assert block['paragraphBordersEditable'] is True
    body, note_ops = plan(data, action, kind)
    operations = [shade_op(data, 'edf5fc'), border_op(data, [single('bottom', 'FF0000', 1)]), body, *note_ops]
    output = patch_docx(data, operations[::-1] if reverse else operations)
    saved = Document(BytesIO(output)); paragraph = saved.paragraphs[0]
    assert paragraph.text == 'A😀新增BC' and paragraph.paragraph_format.keep_with_next
    assert shd_of(output) == ('clear', 'auto', 'edf5fc')
    assert pbdr_of(output)['bottom']['color'] == 'FF0000'
    assert [(run.text, bool(run.bold), bool(run.italic)) for run in paragraph.runs if run.text] == [('A😀', True, False), ('新增', True, False), ('BC', True, True)]
    assert str(next(run for run in paragraph.runs if run.text == '新增').font.color.rgb) == '0070C0'
    for run in paragraph.runs:
        if run.text in ('A😀', '新增'): assert run._r.rPr.find(qn('w:noProof')) is not None
    reopened = inspect_docx(output); notes = reopened['notes'][kind + 's']
    assert [note['text'] for note in notes] == ([] if action == 'delete' else ['来源注释', '新增注释'] if action == 'insert' else ['更正注释'] if action == 'update' else ['来源注释'])
    refs = xml(output, 'word/document.xml').xpath(f'//w:{kind}Reference/@w:id', namespaces=NS)
    assert refs == ([] if action == 'delete' else ['1', '2'] if action == 'insert' else ['1'])
    if action != 'delete':
        original_marker = xml(data, 'word/document.xml').xpath(f'//w:{kind}Reference/..', namespaces=NS)[0]
        saved_marker = xml(output, 'word/document.xml').xpath(f'//w:{kind}Reference/..', namespaces=NS)[0]
        assert etree.tostring(original_marker) == etree.tostring(saved_marker)
    assert etree.tostring(saved.paragraphs[1]._p) == etree.tostring(Document(BytesIO(data)).paragraphs[1]._p)
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        allowed = {'word/document.xml'} | ({f'word/{kind}s.xml'} if action != 'existing' else set())
        assert {name for name in before.namelist() if before.read(name) != after.read(name)} <= allowed


@pytest.mark.parametrize('clear', [False, True])
def test_existing_notes_keep_parts_when_decorations_clear_with_body(clear):
    data = notes_source()
    data = patch_docx(data, [shade_op(data, 'edf5fc'), border_op(data, [single('top')])])
    body, _ = plan(data)
    output = patch_docx(data, [body, border_op(data, None), shade_op(data, None, clear)])
    assert Document(BytesIO(output)).paragraphs[0].text == 'A😀新增BC'
    assert pbdr_of(output) is None
    assert shd_of(output) == (('clear', 'auto', 'auto') if clear else None)
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        assert before.read('word/footnotes.xml') == after.read('word/footnotes.xml')


def test_notes_decorations_keep_source_identity_and_unknown_boundaries():
    data = notes_source(); body, _ = plan(data); shade = shade_op(data, 'edf5fc'); border = border_op(data, [single('bottom')])
    note = inspect_docx(data)['notes']['footnotes'][0]
    for batch in [
        [body, shade, border, dict(shade)], [body, shade, border, dict(border)], [body, shade, border, dict(body)],
        [{**body, 'expectedObjectSha256': 'foreign'}, shade, border], [body, {**shade, 'expectedObjectSha256': 'foreign'}, border],
        [body, shade, {**border, 'expectedObjectSha256': 'foreign'}], [body, shade, {**border, 'rawPPr': '<evil/>'}],
        [body, shade, border, {**note_operation(note, text='forged'), 'expectedNoteSha256': 'foreign'}],
    ]:
        with pytest.raises(ValueError): patch_docx(data, batch)
    document = Document(BytesIO(data)); protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1'); document.settings.element.append(protection)
    out = BytesIO(); document.save(out); protected = out.getvalue()
    for key in ('paragraphShadingEditable', 'paragraphBordersEditable'): assert inspect_docx(protected)['blocks'][0][key] is False
    with pytest.raises(ValueError): patch_docx(protected, [shade_op(protected, 'edf5fc'), border_op(protected, [single('bottom')])])


@pytest.mark.parametrize('fault', ['dangling', 'duplicate', 'unknown-inline', 'complex-shading', 'complex-border'])
def test_notes_decoration_capabilities_do_not_claim_untrusted_source(fault):
    data = notes_source(); root = xml(data, 'word/document.xml')
    if fault == 'dangling': root.xpath('//w:footnoteReference', namespaces=NS)[0].set(qn('w:id'), '999')
    elif fault == 'duplicate':
        from copy import deepcopy
        part = xml(data, 'word/footnotes.xml'); part.append(deepcopy(part.xpath('w:footnote[@w:id="1"]', namespaces=NS)[0]))
        data = replace_parts(data, {'word/footnotes.xml': etree.tostring(part)})
    elif fault == 'unknown-inline': root.xpath('//w:p', namespaces=NS)[0].append(etree.fromstring(f'<w:r xmlns:w="{W}"><w:fldChar w:fldCharType="begin"/></w:r>'))
    elif fault == 'complex-shading': root.xpath('//w:pPr', namespaces=NS)[0].append(etree.fromstring(f'<w:shd xmlns:w="{W}" w:val="pct10" w:fill="FF0000"/>'))
    else: root.xpath('//w:pPr', namespaces=NS)[0].append(etree.fromstring(f'<w:pBdr xmlns:w="{W}"><w:top w:val="double"/></w:pBdr>'))
    data = replace_parts(data, {'word/document.xml': etree.tostring(root)})
    block = inspect_docx(data)['blocks'][0]
    if fault == 'complex-shading': assert block['paragraphShadingEditable'] is False and block['paragraphBordersEditable'] is True
    elif fault == 'complex-border': assert block['paragraphBordersEditable'] is False and block['paragraphShadingEditable'] is True
    else: assert block['paragraphShadingEditable'] is False and block['paragraphBordersEditable'] is False
    with pytest.raises(ValueError): patch_docx(data, [shade_op(data, 'edf5fc'), border_op(data, [single('bottom')])])
