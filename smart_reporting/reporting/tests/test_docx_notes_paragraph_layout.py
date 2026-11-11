"""同来源段落的正文、notes和支持的布局操作须原子保存。"""
from io import BytesIO
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
import pytest
from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


@pytest.mark.parametrize('layout', [
    {'kind': 'setParagraphAlignment', 'alignment': 'center'},
    {'kind': 'setParagraphIndent', 'twips': 720},
    {'kind': 'setParagraphSpacing', 'spaceBefore': 240},
])
def test_text_note_and_layout_are_atomic(layout):
    document = Document(); document.add_paragraph('A😀BC'); document.add_paragraph('Untouched')
    buffer = BytesIO(); document.save(buffer); source = buffer.getvalue()
    block = inspect_docx(source)['blocks'][0]
    anchor = {name: block[name] for name in ['blockId', 'expectedObjectSha256']}
    output = patch_docx(source, [
        {'kind': 'patchParagraphRuns', **anchor, 'runs': [
            {'sourceFrom': 0, 'sourceTo': 3}, {'text': '新增', 'inheritFrom': 1},
            {'noteOperationIndex': 0}, {'sourceFrom': 3, 'sourceTo': 5}]},
        {'kind': 'insertNote', **anchor, 'noteKind': 'footnote', 'offset': 5, 'text': '正文布局脚注'},
        {**layout, **anchor},
    ])
    reopened = Document(BytesIO(output)); paragraph = reopened.paragraphs[0]
    assert paragraph.text == 'A😀新增BC'
    assert reopened.paragraphs[1].text == 'Untouched'
    assert inspect_docx(output)['notes']['footnotes'][0]['text'] == '正文布局脚注'
    if layout['kind'] == 'setParagraphAlignment': assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    if layout['kind'] == 'setParagraphIndent': assert paragraph.paragraph_format.left_indent.twips == 720
    if layout['kind'] == 'setParagraphSpacing': assert paragraph.paragraph_format.space_before.twips == 240


@pytest.mark.parametrize('layout', [
    {'kind': 'setParagraphAlignment', 'alignment': 'center'},
    {'kind': 'setParagraphRightIndent', 'twips': 360},
    {'kind': 'setParagraphSpacing', 'spaceAfter': 120, 'lineSpacing': 1.5},
])
def test_existing_note_source_keeps_marker_and_opaque_properties_with_layout(layout):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    document = Document(); paragraph = document.add_paragraph()
    paragraph.paragraph_format.keep_with_next = True
    run = paragraph.add_run('A😀'); run.bold = True
    run._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
    paragraph.add_run('BC').italic = True; document.add_paragraph('Untouched')
    buffer = BytesIO(); document.save(buffer); source = buffer.getvalue()
    block = inspect_docx(source)['blocks'][0]
    source = patch_docx(source, [{'kind': 'insertNote', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'noteKind': 'footnote', 'offset': 3, 'text': '来源脚注'}])
    model = inspect_docx(source); block = model['blocks'][0]
    assert not block['editable']
    anchor = {name: block[name] for name in ['blockId', 'expectedObjectSha256']}
    output = patch_docx(source, [
        {'kind': 'patchParagraphRuns', **anchor, 'runs': [
            {'sourceFrom': 0, 'sourceTo': 3}, {'text': '新增', 'inheritFrom': 1},
            {'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0}, {'sourceFrom': 4, 'sourceTo': 6}]},
        {**layout, **anchor},
    ])
    paragraph = Document(BytesIO(output)).paragraphs[0]
    assert paragraph.text == 'A😀新增BC' and paragraph.paragraph_format.keep_with_next
    assert inspect_docx(output)['notes']['footnotes'][0]['text'] == '来源脚注'
    assert len(paragraph._p.findall('.//' + qn('w:footnoteReference'))) == 1
    for run in paragraph.runs:
        if run.text and run.text != 'BC': assert run.bold and run._r.rPr.find(qn('w:noProof')) is not None
    if layout['kind'] == 'setParagraphAlignment': assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    if layout['kind'] == 'setParagraphRightIndent': assert paragraph.paragraph_format.right_indent.twips == 360
    if layout['kind'] == 'setParagraphSpacing':
        assert paragraph.paragraph_format.space_after.twips == 120
        assert paragraph.paragraph_format.line_spacing == 1.5


def test_multiple_layout_properties_merge_with_text_and_note_without_losing_ppr():
    document = Document(); paragraph = document.add_paragraph('A😀BC')
    paragraph.paragraph_format.keep_with_next = True
    buffer = BytesIO(); document.save(buffer); source = buffer.getvalue()
    block = inspect_docx(source)['blocks'][0]
    anchor = {name: block[name] for name in ['blockId', 'expectedObjectSha256']}
    output = patch_docx(source, [
        {'kind': 'setParagraphAlignment', **anchor, 'alignment': 'center'},
        {'kind': 'setParagraphIndent', **anchor, 'twips': 720},
        {'kind': 'setParagraphRightIndent', **anchor, 'twips': 240},
        {'kind': 'setParagraphSpacing', **anchor, 'spaceBefore': 120, 'spaceAfter': 180, 'lineSpacing': 1.5},
        {'kind': 'patchParagraphRuns', **anchor, 'runs': [{'sourceFrom': 0, 'sourceTo': 5}, {'text': '续写', 'inheritFrom': 4}, {'noteOperationIndex': 0}]},
        {'kind': 'insertNote', **anchor, 'noteKind': 'endnote', 'offset': 7, 'text': '多布局尾注'},
    ])
    paragraph = Document(BytesIO(output)).paragraphs[0]; formatting = paragraph.paragraph_format
    assert paragraph.text == 'A😀BC续写' and formatting.keep_with_next
    assert paragraph.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert formatting.left_indent.twips == 720 and formatting.right_indent.twips == 240
    assert formatting.space_before.twips == 120 and formatting.space_after.twips == 180 and formatting.line_spacing == 1.5
    assert inspect_docx(output)['notes']['endnotes'][0]['text'] == '多布局尾注'


@pytest.mark.parametrize('other', [
    {'kind': 'formatRange', 'from': 0, 'to': 1, 'style': {'bold': True}},
    {'kind': 'setParagraphList', 'list': 'bullet'},
    {'kind': 'deleteParagraph'},
])
def test_note_body_batch_still_rejects_non_layout_operations(other):
    document = Document(); document.add_paragraph('source')
    buffer = BytesIO(); document.save(buffer); source = buffer.getvalue()
    block = inspect_docx(source)['blocks'][0]
    anchor = {name: block[name] for name in ['blockId', 'expectedObjectSha256']}
    with pytest.raises(ValueError):
        patch_docx(source, [
            {'kind': 'patchParagraphRuns', **anchor, 'runs': [{'sourceFrom': 0, 'sourceTo': 6}, {'noteOperationIndex': 0}]},
            {'kind': 'insertNote', **anchor, 'noteKind': 'footnote', 'offset': 6, 'text': '边界脚注'},
            {**other, **anchor},
        ])
