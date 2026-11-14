"""固定源 StylesPane 定义使用既有 StyleUpsert 合并并与应用同次保存。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    run = doc.add_paragraph('样式正文 alpha').runs[0]
    lang = OxmlElement('w:lang'); lang.set(qn('w:val'), 'en-US'); run._r.get_or_add_rPr().append(lang)
    doc.add_paragraph('邻段保留')
    doc.sections[0].header.paragraphs[0].text = '页眉保留'
    out = BytesIO(); doc.save(out); return out.getvalue()


def definition(data, **changes):
    model = inspect_docx(data)['stylesPane']
    return {'kind': 'upsertStyle', 'expectedStylesSha256': model['expectedStylesSha256'],
            'upsert': {'styleId': 'ReportBody', 'name': 'Report Body', 'type': 'paragraph', 'basedOn': 'Normal',
                       'rPr': {'font': 'Cambria', 'eastAsiaFont': '宋体', 'sizeHalfPoints': 27, 'bold': True},
                       'pPr': {'align': 'center', 'spaceAfterTwips': 160, 'lineSpacing': 1.5}, **changes}}


def test_style_create_and_application_share_one_save_and_preserve_source_parts():
    data = source(); model = inspect_docx(data); block = model['blocks'][0]
    apply = {'kind': 'applyDocumentStyle', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'],
             'actions': [{'type': 'paragraph', 'styleId': 'ReportBody'}]}
    result = patch_docx(data, [definition(data), apply])
    doc = Document(BytesIO(result)); before = Document(BytesIO(data))
    assert doc.paragraphs[0].style.style_id == 'ReportBody'
    style = doc.styles['Report Body']; assert style.font.name == 'Cambria'
    assert style.font.size.pt == 13.5 and style.font.bold is True
    assert style.element.rPr.rFonts.get(qn('w:eastAsia')) == '宋体'
    assert doc.paragraphs[0].runs[0]._r.rPr.find(qn('w:lang')) is not None
    assert doc.paragraphs[1]._p.xml == before.paragraphs[1]._p.xml
    with ZipFile(BytesIO(data)) as a, ZipFile(BytesIO(result)) as b:
        for name in a.namelist():
            if name not in ('word/styles.xml', 'word/document.xml', 'docProps/core.xml'):
                assert a.read(name) == b.read(name), name


def test_style_modify_merges_touched_fields_and_keeps_unrelated_definition_xml():
    data = patch_docx(source(), [definition(source())])
    before = Document(BytesIO(data)).styles['Report Body']
    result = patch_docx(data, [definition(data, rPr={'italic': True}, pPr={'align': None})])
    style = Document(BytesIO(result)).styles['Report Body']
    assert style.font.name == before.font.name and style.font.size == before.font.size
    assert style.font.bold and style.font.italic
    assert style.paragraph_format.alignment is None
    assert style.paragraph_format.space_after == before.paragraph_format.space_after


@pytest.mark.parametrize('changes', [
    {'basedOn': 'Missing'}, {'basedOn': 'ReportBody'}, {'type': 'table'},
    {'rPr': {'sizeHalfPoints': 1}}, {'rPr': {'rawRPr': '<w:rPr/>'}},
    {'pPr': {'numPr': {'numId': '1', 'ilvl': 0}}}, {'name': 'Normal'},
])
def test_styles_pane_rejects_forged_or_out_of_source_ui_definitions(changes):
    data = source()
    with pytest.raises(ValueError): patch_docx(data, [definition(data, **changes)])


def test_styles_definition_identity_cannot_be_reused_for_another_styles_part():
    data = source(); operation = definition(data); operation['expectedStylesSha256'] = '0' * 64
    with pytest.raises(ValueError): patch_docx(data, [operation])


def test_character_style_range_preserves_untouched_rpr_and_toggle_matches_source_unset_mark():
    data = source(); model = inspect_docx(data); block = model['blocks'][0]
    create = definition(data, styleId='ReportEmphasis', name='Report Emphasis', type='character', basedOn=None, pPr={}, rPr={'italic': True})
    # Character definitions never receive paragraph properties, including an empty pPr.
    create['upsert'].pop('pPr')
    apply = {'kind': 'applyDocumentStyle', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'],
             'actions': [{'type': 'character', 'styleId': 'ReportEmphasis', 'from': 2, 'to': 5}]}
    styled = patch_docx(data, [create, apply]); doc = Document(BytesIO(styled))
    runs = doc.paragraphs[0].runs
    assert [run.text for run in runs] == ['样式', '正文 ', 'alpha']
    assert runs[1].style.style_id == 'ReportEmphasis'
    assert all(run._r.rPr.find(qn('w:lang')) is not None for run in runs)
    block = inspect_docx(styled)['blocks'][0]
    cleared = patch_docx(styled, [{**apply, 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'],
                                  'actions': [{'type': 'character', 'styleId': None, 'from': 2, 'to': 5}]}])
    runs = Document(BytesIO(cleared)).paragraphs[0].runs
    assert runs[1]._r.rPr is None
    assert runs[0]._r.rPr.find(qn('w:lang')) is not None and runs[2]._r.rPr.find(qn('w:lang')) is not None


def test_caret_character_style_run_plan_can_create_the_definition_and_type_in_one_save():
    data = source(); block = inspect_docx(data)['blocks'][0]
    create = definition(data, styleId='ReportEmphasis', name='Report Emphasis', type='character', basedOn=None, rPr={'italic': True})
    create['upsert'].pop('pPr')
    plan = {'kind': 'patchParagraphRuns', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'],
            'runs': [{'sourceFrom': 0, 'sourceTo': 2}, {'text': 'Z', 'inheritFrom': 1, 'style': {'styleId': 'ReportEmphasis'}},
                     {'sourceFrom': 2, 'sourceTo': len('样式正文 alpha')}]}
    doc = Document(BytesIO(patch_docx(data, [create, plan])))
    assert doc.paragraphs[0].text == '样式Z正文 alpha'
    typed = [run for run in doc.paragraphs[0].runs if run.text == 'Z']
    assert len(typed) == 1 and typed[0].style.style_id == 'ReportEmphasis'
    assert typed[0]._r.rPr.find(qn('w:lang')) is not None


def test_style_application_rejects_mixed_same_block_mutations_instead_of_losing_them():
    data = source(); block = inspect_docx(data)['blocks'][0]
    base = {'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256']}
    with pytest.raises(ValueError):
        patch_docx(data, [{'kind': 'applyDocumentStyle', **base, 'actions': [{'type': 'paragraph', 'styleId': 'Normal'}]},
                          {'kind': 'replaceParagraph', **base, 'text': 'cannot disappear'}])


def test_paragraph_style_turns_heading_into_body_and_keeps_existing_list_numbering():
    doc = Document(); doc.add_paragraph('原标题', 'Heading 1'); doc.add_paragraph('原列表', 'List Bullet')
    out = BytesIO(); doc.save(out); data = out.getvalue(); model = inspect_docx(data)
    operations = [definition(data)]
    for block in model['blocks']:
        operations.append({'kind': 'applyDocumentStyle', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'],
                           'actions': [{'type': 'paragraph', 'styleId': 'ReportBody'}]})
    result = patch_docx(data, operations); saved = Document(BytesIO(result)); actual = inspect_docx(result)['blocks']
    assert [p.style.style_id for p in saved.paragraphs] == ['ReportBody', 'ReportBody']
    assert actual[0]['type'] == 'paragraph' and actual[1]['type'] == 'listItem'
    assert actual[1]['list'] == model['blocks'][1]['list']


def test_new_style_inheriting_heading_converts_a_list_item_and_removes_its_numbering():
    doc = Document(); doc.add_paragraph('列表转标题', 'List Bullet')
    out = BytesIO(); doc.save(out); data = out.getvalue(); block = inspect_docx(data)['blocks'][0]
    result = patch_docx(data, [definition(data, basedOn='Heading1'),
                              {'kind': 'applyDocumentStyle', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'],
                               'actions': [{'type': 'paragraph', 'styleId': 'ReportBody'}]}])
    paragraph = Document(BytesIO(result)).paragraphs[0]
    assert paragraph.style.style_id == 'ReportBody'
    assert paragraph._p.pPr.find(qn('w:numPr')) is None
    assert inspect_docx(result)['blocks'][0]['type'] == 'heading'
