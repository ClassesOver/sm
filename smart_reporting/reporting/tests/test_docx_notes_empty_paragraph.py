"""独立 RED：空来源段落键入文字后插注，保留来源默认样式与空run属性。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
import pytest

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def empty_source(kind):
    document = Document(); paragraph = document.add_paragraph()
    if kind == 'paragraph-style':
        style = document.styles.add_style('EmptyBody', WD_STYLE_TYPE.PARAGRAPH)
        style.font.name = 'Cambria'; style.font.size = Pt(16); style.font.bold = True
        paragraph.style = style
    elif kind.startswith('empty-run'):
        run = paragraph.add_run(''); run.font.name = 'Arial'; run.font.size = Pt(22); run.italic = True
        run._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
        if kind != 'empty-run':
            paragraph.add_run('').bold = True
        if kind == 'empty-run-mark':
            rpr = OxmlElement('w:rPr')
            size = OxmlElement('w:sz'); size.set(qn('w:val'), '18'); rpr.append(size)
            paragraph._p.get_or_add_pPr().append(rpr)
    document.add_paragraph('Do not change')
    stream = BytesIO(); document.save(stream); return stream.getvalue()


@pytest.mark.parametrize('kind', ['plain', 'paragraph-style', 'empty-run', 'empty-run-sequence', 'empty-run-mark'])
def test_type_into_empty_source_then_insert_note_inherits_server_source_default(kind):
    data = empty_source(kind); model = inspect_docx(data); anchor = model['blocks'][0]
    assert anchor['text'] == '' and model['notes']['referenceBlocks'][0]['editable']
    identity = {'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256']}
    output = patch_docx(data, [
        {'kind': 'patchParagraphRuns', **identity, 'runs': [{'text': '新增😀', 'inheritFrom': 0}, {'noteOperationIndex': 0}]},
        {'kind': 'insertNote', **identity, 'noteKind': 'footnote', 'offset': 4, 'text': '空段输入后的脚注'},
    ])
    paragraph = Document(BytesIO(output)).paragraphs[0]
    assert paragraph.text == '新增😀'
    assert len(paragraph._p.findall('.//' + qn('w:footnoteReference'))) == 1
    assert inspect_docx(output)['notes']['footnotes'][0]['text'] == '空段输入后的脚注'
    assert Document(BytesIO(output)).paragraphs[1].text == 'Do not change'
    if kind == 'paragraph-style':
        assert paragraph.style.style_id == 'EmptyBody'
        assert paragraph.style.font.name == 'Cambria' and paragraph.style.font.size.pt == 16 and paragraph.style.font.bold
    if kind.startswith('empty-run'):
        run = next(run for run in paragraph.runs if run.text)
        assert run.font.name == 'Arial' and run.font.size.pt == (9 if kind == 'empty-run-mark' else 22) and run.italic
        assert run._r.rPr.find(qn('w:noProof')) is not None
        if kind != 'empty-run':
            assert run.bold
    else:
        assert next(run for run in paragraph.runs if run.text).font.name is None
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        assert before.read('word/styles.xml') == after.read('word/styles.xml')
