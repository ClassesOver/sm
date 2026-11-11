"""独立 ZIP 复核：混编最终 runs 不能绕过跨段共享注释的引用身份。"""
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from docx.oxml.ns import qn
from lxml import etree
import pytest

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


@pytest.fixture
def shared_note():
    document = Document()
    paragraph = document.add_paragraph()
    paragraph.add_run('A😀').bold = True
    paragraph.add_run('BC尾').italic = True
    document.add_paragraph('Untouched paragraph')
    output = BytesIO()
    document.save(output)
    original = output.getvalue()
    anchor = inspect_docx(original)['blocks'][0]
    seeded = patch_docx(original, [{
        'kind': 'insertNote', 'noteKind': 'footnote', 'blockId': anchor['blockId'],
        'expectedObjectSha256': anchor['expectedObjectSha256'], 'offset': 3, 'text': 'Shared note',
    }])
    with ZipFile(BytesIO(seeded)) as package:
        entries = {name: package.read(name) for name in package.namelist()}
    root = etree.fromstring(entries['word/document.xml'])
    paragraphs = root.find(qn('w:body')).findall(qn('w:p'))
    run = etree.SubElement(paragraphs[1], qn('w:r'))
    etree.SubElement(run, qn('w:footnoteReference')).set(qn('w:id'), '1')
    entries['word/document.xml'] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as package:
        for name, content in entries.items():
            package.writestr(name, content)
    data = output.getvalue()
    model = inspect_docx(data)
    anchor, note = model['blocks'][0], model['notes']['footnotes'][0]
    assert len(note['references']) == 2
    plan = {'kind': 'patchParagraphRuns', 'blockId': anchor['blockId'],
            'expectedObjectSha256': anchor['expectedObjectSha256'], 'runs': [
                {'sourceFrom': 0, 'sourceTo': 3}, {'text': '新增', 'inheritFrom': 4},
                {'sourceFrom': 4, 'sourceTo': 7},
            ]}
    delete = {'kind': 'deleteNote', 'noteKind': 'footnote', 'noteId': '1',
              'expectedNoteSha256': note['expectedNoteSha256'], 'expectedReferences': note['references']}
    return data, plan, delete


def test_mixed_paragraph_deletion_removes_all_shared_note_references(shared_note):
    data, plan, delete = shared_note
    result = patch_docx(data, [plan, delete])
    assert inspect_docx(result)['notes']['footnotes'] == []
    with ZipFile(BytesIO(result)) as package:
        root = etree.fromstring(package.read('word/document.xml'))
        assert not root.findall('.//' + qn('w:footnoteReference'))
    paragraphs = Document(BytesIO(result)).paragraphs
    assert paragraphs[0].text == 'A😀新增BC尾'
    assert paragraphs[1].text == 'Untouched paragraph'
    text_runs = [run for run in paragraphs[0].runs if run.text]
    assert text_runs[0].text == 'A😀' and text_runs[0].bold
    assert all(run.italic for run in text_runs[1:])


@pytest.mark.parametrize('fault', ['partial-references', 'retained-deleted-marker', 'repeated-source-span', 'span-covers-marker'])
def test_final_runs_cannot_bypass_shared_reference_identity(shared_note, fault):
    data, plan, delete = shared_note
    if fault == 'partial-references':
        delete['expectedReferences'] = delete['expectedReferences'][:1]
    elif fault == 'retained-deleted-marker':
        plan['runs'] = [
            {'sourceFrom': 0, 'sourceTo': 3}, {'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0},
            {'sourceFrom': 4, 'sourceTo': 7},
        ]
    elif fault == 'repeated-source-span':
        plan['runs'] = [{'sourceFrom': 0, 'sourceTo': 3}, {'sourceFrom': 0, 'sourceTo': 3}, {'sourceFrom': 4, 'sourceTo': 7}]
    else:
        plan['runs'] = [{'sourceFrom': 0, 'sourceTo': 7}]
    with pytest.raises(ValueError):
        patch_docx(data, [plan, delete])
