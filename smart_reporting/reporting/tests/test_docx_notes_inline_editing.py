"""下一批独立 RED：同一来源段落的最终 runs 与真实 note 引用原子保存。"""
from io import BytesIO
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
import pytest

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    document = Document(); paragraph = document.add_paragraph()
    paragraph.add_run('A😀').bold = True; paragraph.add_run('BC尾').italic = True
    document.add_paragraph('Untouched paragraph')
    output = BytesIO(); document.save(output); return output.getvalue()


def paragraph_plan(model, runs):
    anchor = model['blocks'][0]
    return {'kind': 'patchParagraphRuns', 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'runs': runs}


def insert(model, offset, kind='footnote'):
    anchor = model['blocks'][0]
    return {'kind': 'insertNote', 'noteKind': kind, 'blockId': anchor['blockId'], 'expectedObjectSha256': anchor['expectedObjectSha256'], 'offset': offset, 'text': 'Mixed paragraph note'}


def source_run(start, end):
    return {'sourceFrom': start, 'sourceTo': end}


def inspected_runs(content):
    return [(run.text, bool(run.bold), bool(run.italic), str(run.font.color.rgb) if run.font.color.rgb else None)
            for run in Document(BytesIO(content)).paragraphs[0].runs if run.text]


def assert_note(content, kind, prefix):
    model = inspect_docx(content); note = model['notes'][kind + 's'][0]
    assert note['id'] == '1' and len(note['references']) == 1
    with ZipFile(BytesIO(content)) as package:
        from lxml import etree
        root = etree.fromstring(package.read('word/document.xml'))
    paragraph = root.find(qn('w:body')).find(qn('w:p'))
    before = []
    for run in paragraph.findall(qn('w:r')):
        if run.find(qn('w:' + kind + 'Reference')) is not None:
            assert ''.join(before) == prefix
            break
        before.extend(run.itertext())
    else:
        pytest.fail('note 部件存在但正文没有实际引用')
    assert Document(BytesIO(content)).paragraphs[1].text == 'Untouched paragraph'


def test_text_then_note_uses_current_utf16_position_and_preserves_original_runs():
    data = source(); model = inspect_docx(data)
    # 当前位置5来自原文3 + 新增2；原文offset5位于C之后，不能混用。
    operations = [paragraph_plan(model, [source_run(0, 3), {'text': '新增', 'inheritFrom': 1}, {'noteOperationIndex': 0}, source_run(3, 6)]), insert(model, 5)]
    output = patch_docx(data, operations)
    assert_note(output, 'footnote', 'A😀新增')
    characters = [(char, bold, italic, color) for text, bold, italic, color in inspected_runs(output) for char in text]
    assert characters == [(char, True, False, None) for char in 'A😀新增'] + [(char, False, True, None) for char in 'BC尾']


def test_note_then_text_in_the_same_paragraph_keeps_real_marker_and_italic_suffix():
    data = source(); model = inspect_docx(data)
    operations = [paragraph_plan(model, [source_run(0, 3), {'noteOperationIndex': 0}, {'text': '追加', 'inheritFrom': 3}, source_run(3, 6)]), insert(model, 3)]
    output = patch_docx(data, operations)
    assert_note(output, 'footnote', 'A😀')
    runs = inspected_runs(output)
    assert runs[0] == ('A😀', True, False, None)
    assert ''.join(run[0] for run in runs[1:]) == '追加BC尾'
    assert all(run[2] for run in runs[1:])


def test_delete_note_then_replace_same_paragraph_text_without_losing_unselected_runs():
    data = source(); model = inspect_docx(data)
    data = patch_docx(data, [insert(model, 3)])
    model = inspect_docx(data); note = model['notes']['footnotes'][0]
    # 来源marker占一格：A😀[3..4]BC尾；删注后替换B，原C尾仍是来源5..7。
    operations = [paragraph_plan(model, [source_run(0, 3), {'text': '改', 'inheritFrom': 4}, source_run(5, 7)]),
                  {'kind': 'deleteNote', 'noteKind': 'footnote', 'noteId': note['id'], 'expectedNoteSha256': note['expectedNoteSha256'], 'expectedReferences': note['references']}]
    output = patch_docx(data, operations)
    assert inspect_docx(output)['notes']['footnotes'] == []
    runs = inspected_runs(output)
    assert runs[0] == ('A😀', True, False, None)
    assert ''.join(run[0] for run in runs[1:]) == '改C尾'
    assert all(run[2] for run in runs[1:])
    with ZipFile(BytesIO(output)) as package:
        assert b'footnoteReference' not in package.read('word/document.xml')


def test_emoji_replacement_and_formatting_keep_every_outside_source_run_unchanged():
    data = source(); model = inspect_docx(data)
    operations = [paragraph_plan(model, [source_run(0, 3), {'text': '字😀', 'inheritFrom': 3, 'style': {'bold': True, 'color': '112233'}}, {'noteOperationIndex': 0}, source_run(4, 6)]), insert(model, 6, 'endnote')]
    output = patch_docx(data, operations)
    assert_note(output, 'endnote', 'A😀字😀')
    assert inspected_runs(output) == [('A😀', True, False, None), ('字😀', True, True, '112233'), ('C尾', False, True, None)]
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


@pytest.mark.parametrize('fault', ['surrogate-cut', 'inherit-surrogate', 'overlap', 'raw-xml', 'unknown-style', 'stale-source', 'offset-mismatch', 'missing-new-marker', 'copied-new-marker', 'foreign-note-index', 'malformed-text'])
def test_invalid_final_run_plans_fail_before_writing_any_output(tmp_path, fault):
    import json
    from smart_reporting.reporting.delivery.office_engine import run_bridge
    data = source(); model = inspect_docx(data)
    pieces = [source_run(0, 3), {'noteOperationIndex': 0}, source_run(3, 6)]
    plan = paragraph_plan(model, pieces); note = insert(model, 3)
    if fault == 'malformed-text': pieces.insert(1, {'text': '\ud800', 'inheritFrom': 1}); note['offset'] = 4
    elif fault == 'surrogate-cut': pieces[0]['sourceTo'] = 2
    elif fault == 'inherit-surrogate': pieces.insert(1, {'text': 'x', 'inheritFrom': 2}); note['offset'] = 4
    elif fault == 'overlap': pieces[-1]['sourceFrom'] = 1
    elif fault == 'raw-xml': pieces[0]['rawRPr'] = '<w:rPr/>'
    elif fault == 'unknown-style': pieces[0]['style'] = {'rawRPr': '<w:rPr/>'}
    elif fault == 'stale-source': plan['expectedObjectSha256'] = 'foreign'
    elif fault == 'offset-mismatch': note['offset'] = 4
    elif fault == 'missing-new-marker': pieces.pop(1)
    elif fault == 'copied-new-marker': pieces.insert(2, {'noteOperationIndex': 0})
    elif fault == 'foreign-note-index': pieces[1]['noteOperationIndex'] = 1
    original, output, request = (tmp_path / name for name in ['source.docx', 'output.docx', 'request.json'])
    original.write_bytes(data)
    request.write_text(json.dumps({'kind': 'patch', 'input': str(original), 'output': str(output), 'operations': [plan, note]}), encoding='utf-8')
    result = run_bridge('doc', 'edit-docx', request)
    assert result.returncode != 0
    assert not output.exists()
    assert original.read_bytes() == data


@pytest.mark.parametrize('fault', ['drop', 'copy', 'move', 'wrong-id', 'delete-without-identity'])
def test_existing_note_marker_cannot_be_forged_or_removed_via_final_runs(fault):
    data = source(); data = patch_docx(data, [insert(inspect_docx(data), 3)])
    model = inspect_docx(data)
    marker = {'noteKind': 'footnote', 'noteId': '1', 'referenceIndex': 0}
    pieces = [source_run(0, 3), marker, source_run(4, 7)]
    if fault == 'drop': pieces.pop(1)
    elif fault == 'copy': pieces.insert(2, dict(marker))
    elif fault == 'move': pieces = [marker, source_run(0, 3), source_run(4, 7)]
    elif fault == 'wrong-id': marker['noteId'] = '999'
    operations = [paragraph_plan(model, pieces)]
    if fault == 'delete-without-identity':
        pieces.pop(1)
        operations.append({'kind': 'deleteNote', 'noteKind': 'footnote', 'noteId': '1', 'expectedNoteSha256': 'foreign', 'expectedReferences': model['notes']['footnotes'][0]['references']})
    with pytest.raises(ValueError): patch_docx(data, operations)


def test_repeated_text_keeps_distinct_source_raw_properties_after_note_and_text_insertion():
    from docx.oxml import OxmlElement
    document = Document(); paragraph = document.add_paragraph()
    first = paragraph.add_run('甲甲'); first.bold = True; first._r.get_or_add_rPr().append(OxmlElement('w:noProof'))
    second = paragraph.add_run('甲甲'); second.italic = True; second._r.get_or_add_rPr().append(OxmlElement('w:vanish'))
    stream = BytesIO(); document.save(stream); data = stream.getvalue(); model = inspect_docx(data)
    plan = paragraph_plan(model, [source_run(0, 2), {'text': '新增', 'inheritFrom': 2}, {'noteOperationIndex': 0}, source_run(2, 4)])
    output = patch_docx(data, [plan, insert(model, 4)])
    paragraph = Document(BytesIO(output)).paragraphs[0]
    text_runs = [run for run in paragraph.runs if run.text]
    assert text_runs[0].text == '甲甲' and text_runs[0].bold
    assert text_runs[0]._r.rPr.find(qn('w:noProof')) is not None
    assert ''.join(run.text for run in text_runs[1:]) == '新增甲甲'
    assert all(run.italic and run._r.rPr.find(qn('w:vanish')) is not None for run in text_runs[1:])


def test_soft_line_break_and_its_original_run_properties_survive_mixed_editing():
    document = Document(); paragraph = document.add_paragraph()
    run = paragraph.add_run('A😀'); run.bold = True; run.add_break(); run.add_text('BC尾')
    stream = BytesIO(); document.save(stream); data = stream.getvalue(); model = inspect_docx(data)
    plan = paragraph_plan(model, [source_run(0, 4), {'text': '新增', 'inheritFrom': 4}, {'noteOperationIndex': 0}, source_run(4, 7)])
    output = patch_docx(data, [plan, insert(model, 6)])
    paragraph = Document(BytesIO(output)).paragraphs[0]
    assert paragraph.text == 'A😀\n新增BC尾'
    assert all(run.bold for run in paragraph.runs if run.text)
    assert len(paragraph._p.findall('.//' + qn('w:br'))) == 1


@pytest.mark.parametrize('operation', ['insert', 'update'])
def test_malformed_note_text_is_rejected_without_silent_unicode_replacement(operation, tmp_path):
    data = source(); model = inspect_docx(data)
    if operation == 'insert':
        operations = [insert(model, 3)]; operations[0]['text'] = '\ud800'
    else:
        data = patch_docx(data, [insert(model, 3)]); note = inspect_docx(data)['notes']['footnotes'][0]
        operations = [{'kind': 'updateNote', 'noteKind': 'footnote', 'noteId': note['id'], 'expectedNoteSha256': note['expectedNoteSha256'], 'text': '\ud800'}]
    import json
    from smart_reporting.reporting.delivery.office_engine import run_bridge
    original, output, request = (tmp_path / name for name in ['source.docx', 'output.docx', 'request.json'])
    original.write_bytes(data)
    request.write_text(json.dumps({'kind': 'patch', 'input': str(original), 'output': str(output), 'operations': operations}), encoding='utf-8')
    result = run_bridge('doc', 'edit-docx', request)
    assert result.returncode != 0
    assert not output.exists()
