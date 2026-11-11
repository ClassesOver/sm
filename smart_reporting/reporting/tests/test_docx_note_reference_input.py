from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_notes import xml, replace_parts, note_operation, NS
from smart_reporting.reporting.tests.test_docx_notes_decorations import notes_source


def terminal_source(kind='footnote'):
    data = notes_source(kind); root = xml(data, 'word/document.xml')
    marker = root.xpath(f'//w:{kind}Reference/..', namespaces=NS)[0]
    paragraph = marker.getparent(); paragraph.remove(marker); paragraph.append(marker)
    align = OxmlElement('w:vertAlign'); align.set(qn('w:val'), 'superscript'); marker.find(qn('w:rPr')).append(align)
    return replace_parts(data, {'word/document.xml': etree.tostring(root)})


def body_plan(data, pieces):
    block = inspect_docx(data)['blocks'][0]
    return {'kind': 'patchParagraphRuns', **{key: block[key] for key in ('blockId', 'expectedObjectSha256')}, 'runs': pieces}


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
def test_source_marker_inheritance_becomes_plain_text_without_copying_reference(kind):
    data = terminal_source(kind)
    pieces = [{'sourceFrom': 0, 'sourceTo': 5}, {'noteKind': kind, 'noteId': '1', 'referenceIndex': 0}, {'text': '新增', 'inheritFrom': 5, 'style': {'bold': True}}, {'text': '续写', 'inheritFrom': 5}]
    result = patch_docx(data, [body_plan(data, pieces)])
    paragraph = Document(BytesIO(result)).paragraphs[0]
    assert paragraph.text == 'A😀BC新增续写'
    refs = xml(result, 'word/document.xml').xpath(f'//w:{kind}Reference/@w:id', namespaces=NS)
    assert refs == ['1']
    runs = [run for run in paragraph.runs if run.text in ('新增', '续写')]
    assert [bool(run.bold) for run in runs] == [True, False]
    for run in runs:
        assert run._r.rPr.find(qn('w:noProof')) is not None
        assert run._r.rPr.find(qn('w:vertAlign')).get(qn('w:val')) == 'superscript'
        assert run._r.find(qn(f'w:{kind}Reference')) is None
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(result)) as after:
        for name in before.namelist():
            if name not in ('word/document.xml', 'docProps/core.xml'): assert before.read(name) == after.read(name), name
    note = inspect_docx(result)['notes'][kind + 's'][0]
    # 保存后的普通text已成为可信来源；删除原marker后仍可继续编辑它。
    next_plan = body_plan(result, [{'sourceFrom': 0, 'sourceTo': 5}, {'sourceFrom': 6, 'sourceTo': 10}, {'text': '再改', 'inheritFrom': 6}])
    deleted = patch_docx(result, [next_plan, {**note_operation(note, 'deleteNote', expectedReferences=note['references']), 'noteKind': kind}])
    assert Document(BytesIO(deleted)).paragraphs[0].text == 'A😀BC新增续写再改'
    assert not xml(deleted, 'word/document.xml').xpath(f'//w:{kind}Reference', namespaces=NS)


def test_marker_inheritance_rejects_missing_deletion_bad_coordinate_or_forged_source():
    data = terminal_source(); note = inspect_docx(data)['notes']['footnotes'][0]
    ref = {'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0}
    deletion = note_operation(note, 'deleteNote', expectedReferences=note['references'])
    for pieces, note_ops in [
        ([{'sourceFrom': 0, 'sourceTo': 5}, {'text': 'forged', 'inheritFrom': 5}], []),
        ([ref, {'sourceFrom': 0, 'sourceTo': 5}, {'text': 'forged', 'inheritFrom': 5}], []),
        ([{'sourceFrom': 0, 'sourceTo': 5}, ref, {'text': 'forged', 'inheritFrom': 6}], []),
        ([{'sourceFrom': 0, 'sourceTo': 5}, ref, {'text': 'forged', 'inheritFrom': 5, 'rawRPr': '<evil/>'}], []),
    ]:
        with pytest.raises(ValueError): patch_docx(data, [body_plan(data, pieces), *note_ops])


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
def test_deleted_source_marker_can_supply_plain_text_style_in_same_batch(kind):
    data = terminal_source(kind); note = inspect_docx(data)['notes'][kind + 's'][0]
    pieces = [{'text': '前置', 'inheritFrom': 5}, {'sourceFrom': 0, 'sourceTo': 5}, {'text': '保留文字', 'inheritFrom': 5}]
    result = patch_docx(data, [body_plan(data, pieces), {**note_operation(note, 'deleteNote', expectedReferences=note['references']), 'noteKind': kind}])
    paragraph = Document(BytesIO(result)).paragraphs[0]
    assert paragraph.text == '前置A😀BC保留文字'
    assert not xml(result, 'word/document.xml').xpath(f'//w:{kind}Reference', namespaces=NS)
    for run in (paragraph.runs[0], paragraph.runs[-1]):
        assert run._r.rPr.find(qn('w:noProof')) is not None
        assert run._r.rPr.find(qn('w:vertAlign')).get(qn('w:val')) == 'superscript'
