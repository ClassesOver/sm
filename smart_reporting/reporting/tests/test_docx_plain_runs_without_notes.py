"""全局注释不可用不应阻止普通锚定段落的字符混编。"""
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from lxml import etree
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx
from smart_reporting.reporting.tests.test_docx_notes import source, insert, xml, replace_parts, NS, W


def unavailable_source(fault):
    data = source(); data = patch_docx(data, [insert(inspect_docx(data))])
    if fault == 'duplicate':
        root = xml(data, 'word/footnotes.xml'); root.append(deepcopy(root.xpath('w:footnote[@w:id="1"]', namespaces=NS)[0]))
        return replace_parts(data, {'word/footnotes.xml': etree.tostring(root)})
    root = xml(data, 'word/document.xml'); root.xpath('//w:footnoteReference', namespaces=NS)[0].set(f'{{{W}}}id', '999')
    return replace_parts(data, {'word/document.xml': etree.tostring(root)})


@pytest.mark.parametrize('fault', ['duplicate', 'dangling'])
def test_plain_run_plan_preserves_unavailable_notes_verbatim(fault):
    data = unavailable_source(fault); model = inspect_docx(data)
    assert 'notes' not in model
    block = model['blocks'][1]; assert block['editable']
    plan = {'kind': 'patchParagraphRuns', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'runs': [
        {'sourceFrom': 0, 'sourceTo': 9}, {'text': '新增', 'inheritFrom': 0, 'style': {'bold': True}}]}
    output = patch_docx(data, [plan])
    paragraph = Document(BytesIO(output)).paragraphs[1]
    assert paragraph.text == 'Unchanged新增'
    assert [(run.text, bool(run.bold)) for run in paragraph.runs] == [('Unchanged', False), ('新增', True)]
    assert 'notes' not in inspect_docx(output)
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'docProps/core.xml'}: assert before.read(name) == after.read(name), name
    assert etree.tostring(xml(data, 'word/document.xml').xpath('//w:body/w:p', namespaces=NS)[0]) == etree.tostring(xml(output, 'word/document.xml').xpath('//w:body/w:p', namespaces=NS)[0])


@pytest.mark.parametrize('fault', ['note-source', 'forged-marker', 'source-reference', 'note-operation', 'hash', 'foreign-block-hash', 'unknown-inline'])
def test_plain_run_fallback_does_not_relax_notes_or_identity(fault):
    data = unavailable_source('duplicate'); model = inspect_docx(data); block = model['blocks'][0 if fault == 'note-source' else 1]
    plan = {'kind': 'patchParagraphRuns', 'blockId': block['blockId'], 'expectedObjectSha256': 'foreign' if fault == 'hash' else block['expectedObjectSha256'], 'runs': [{'text': 'change', 'inheritFrom': 0}]}
    if fault == 'foreign-block-hash': plan['expectedObjectSha256'] = model['blocks'][0]['expectedObjectSha256']
    if fault == 'unknown-inline':
        root = xml(data, 'word/document.xml'); paragraph = root.xpath('//w:body/w:p', namespaces=NS)[1]
        paragraph.append(etree.Element(f'{{{W}}}sdt'))
        data = replace_parts(data, {'word/document.xml': etree.tostring(root)})
        block = inspect_docx(data)['blocks'][1]; assert not block['editable']
        plan.update({name: block[name] for name in ['blockId', 'expectedObjectSha256']})
    operations = [plan]
    if fault == 'forged-marker': plan['runs'].append({'noteOperationIndex': 0})
    if fault == 'source-reference': plan['runs'].append({'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0})
    if fault == 'note-operation': operations.append({'kind': 'insertNote', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'noteKind': 'footnote', 'offset': 0, 'text': 'forbidden'})
    with pytest.raises(ValueError): patch_docx(data, operations)
