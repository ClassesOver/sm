"""真实 ZIP 回归：注释文本与正文引用必须作为同一批原子修改。"""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from docx import Document
from lxml import etree

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def source():
    doc = Document(); p = doc.add_paragraph(); p.add_run('A😀').bold = True; p.add_run('BC尾').italic = True
    doc.add_paragraph('Unchanged')
    out = BytesIO(); doc.save(out); return out.getvalue()


def insert(model, kind='footnote', offset=3, **extra):
    block = model['blocks'][0]
    return {'kind': 'insertNote', 'noteKind': kind, 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'offset': offset, 'text': 'New note', **extra}


def note_operation(note, kind='updateNote', **extra):
    return {'kind': kind, 'noteKind': 'footnote', 'noteId': note['id'], 'expectedNoteSha256': note['expectedNoteSha256'], **extra}


def xml(content, name):
    with ZipFile(BytesIO(content)) as package: return etree.fromstring(package.read(name))


def replace_parts(content, parts):
    out = BytesIO()
    with ZipFile(BytesIO(content)) as before, ZipFile(out, 'w', ZIP_DEFLATED) as after:
        for item in before.infolist(): after.writestr(item, parts.get(item.filename, before.read(item.filename)))
    return out.getvalue()


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
def test_insert_allocates_server_id_and_atomically_writes_marker_part_relationship_and_content_type(kind):
    data = source(); model = inspect_docx(data)
    output = patch_docx(data, [insert(model, kind)])
    saved = inspect_docx(output); note = saved['notes'][kind + 's'][0]
    assert note['id'] == '1' and note['text'] == 'New note'
    assert len(note['references']) == 1
    document = xml(output, 'word/document.xml')
    assert document.xpath(f'//w:{kind}Reference/@w:id', namespaces=NS) == ['1']
    assert document.xpath('//w:p[1]/w:r/w:t/text()', namespaces=NS) == ['A😀', 'BC尾']
    relationships = xml(output, 'word/_rels/document.xml.rels')
    assert len([r for r in relationships if r.get('Type', '').endswith('/' + kind + 's')]) == 1
    assert any(p.get('PartName') == f'/word/{kind}s.xml' for p in xml(output, '[Content_Types].xml'))
    assert saved['blocks'][0]['editable'] is False
    assert saved['notes']['referenceBlocks'][0]['editable'] is True
    with ZipFile(BytesIO(data)) as before, ZipFile(BytesIO(output)) as after:
        for name in before.namelist():
            if name not in {'word/document.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml', 'docProps/core.xml'}:
                assert before.read(name) == after.read(name), name


def test_updates_text_then_deletes_note_and_every_reference_without_changing_other_body_runs():
    data = source(); inserted = patch_docx(data, [insert(inspect_docx(data))]); model = inspect_docx(inserted); note = model['notes']['footnotes'][0]
    updated = patch_docx(inserted, [note_operation(note, text='Changed\nSecond line')])
    current = inspect_docx(updated); note = current['notes']['footnotes'][0]
    assert note['text'] == 'Changed\nSecond line'
    with ZipFile(BytesIO(inserted)) as before, ZipFile(BytesIO(updated)) as after:
        assert before.read('word/document.xml') == after.read('word/document.xml')
    deleted = patch_docx(updated, [note_operation(note, 'deleteNote', expectedReferences=note['references'])])
    assert inspect_docx(deleted)['notes']['footnotes'] == []
    assert not xml(deleted, 'word/document.xml').xpath('//w:footnoteReference', namespaces=NS)
    paragraph = Document(BytesIO(deleted)).paragraphs[0]
    assert [(r.text, bool(r.bold), bool(r.italic)) for r in paragraph.runs] == [('A😀', True, False), ('BC尾', False, True)]


@pytest.mark.parametrize('fault', ['client-id', 'surrogate', 'stale-block', 'mixed-body', 'stale-note', 'foreign-references'])
def test_invalid_note_batch_is_rejected(fault):
    data = source(); model = inspect_docx(data); operations = [insert(model)]
    if fault == 'client-id': operations[0]['noteId'] = '999'
    elif fault == 'surrogate': operations[0]['offset'] = 2
    elif fault == 'stale-block': operations[0]['expectedObjectSha256'] = 'foreign'
    elif fault == 'mixed-body': operations.append({'kind': 'replaceParagraph', 'blockId': model['blocks'][0]['blockId'], 'expectedObjectSha256': model['blocks'][0]['expectedObjectSha256'], 'text': 'Changed'})
    else:
        data = patch_docx(data, operations); note = inspect_docx(data)['notes']['footnotes'][0]
        operations = [note_operation(note, text='Changed')] if fault == 'stale-note' else [note_operation(note, 'deleteNote', expectedReferences=[])]
        if fault == 'stale-note': operations[0]['expectedNoteSha256'] = 'foreign'
    with pytest.raises(ValueError): patch_docx(data, operations)


def test_unchanged_complex_note_and_separator_are_preserved_verbatim():
    data = source(); inserted = patch_docx(data, [insert(inspect_docx(data))])
    with ZipFile(BytesIO(inserted)) as package: original = package.read('word/footnotes.xml')
    complex_entry = b'<w:footnote w:id="9"><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Complex table</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:footnote>'
    document = xml(inserted, 'word/document.xml')
    second = document.xpath('/w:document/w:body/w:p', namespaces=NS)[1]
    reference_run = etree.SubElement(second, f'{{{W}}}r')
    etree.SubElement(reference_run, f'{{{W}}}footnoteReference').set(f'{{{W}}}id', '9')
    data = replace_parts(inserted, {'word/footnotes.xml': original.replace(b'</w:footnotes>', complex_entry + b'</w:footnotes>'), 'word/document.xml': etree.tostring(document)})
    model = inspect_docx(data); assert not model['notes']['footnotes'][1]['editable']
    output = patch_docx(data, [note_operation(model['notes']['footnotes'][0], text='Changed')])
    with ZipFile(BytesIO(output)) as package:
        assert complex_entry in package.read('word/footnotes.xml')
    with pytest.raises(ValueError): patch_docx(data, [note_operation(model['notes']['footnotes'][1], text='Flatten')])
    complex_note = inspect_docx(output)['notes']['footnotes'][1]
    deleted = patch_docx(output, [note_operation(complex_note, 'deleteNote', expectedReferences=complex_note['references'])])
    assert [note['id'] for note in inspect_docx(deleted)['notes']['footnotes']] == ['1']
    assert xml(deleted, 'word/document.xml').xpath('//w:footnoteReference/@w:id', namespaces=NS) == ['1']


def test_deletion_requires_all_reference_identities_and_removes_repeated_markers_atomically():
    data = source(); data = patch_docx(data, [insert(inspect_docx(data))])
    document = xml(data, 'word/document.xml')
    second = document.xpath('/w:document/w:body/w:p', namespaces=NS)[1]
    run = etree.SubElement(second, f'{{{W}}}r'); etree.SubElement(run, f'{{{W}}}footnoteReference').set(f'{{{W}}}id', '1')
    data = replace_parts(data, {'word/document.xml': etree.tostring(document)})
    note = inspect_docx(data)['notes']['footnotes'][0]
    assert len(note['references']) == 2
    with pytest.raises(ValueError): patch_docx(data, [note_operation(note, 'deleteNote', expectedReferences=note['references'][:1])])
    output = patch_docx(data, [note_operation(note, 'deleteNote', expectedReferences=note['references'])])
    assert not xml(output, 'word/document.xml').xpath('//w:footnoteReference', namespaces=NS)


@pytest.mark.parametrize('fault', ['duplicate-note', 'dangling-reference', 'nonstandard-relationship'])
def test_unsupported_note_source_only_disables_notes_and_keeps_unrelated_body_editable(fault):
    data = source(); data = patch_docx(data, [insert(inspect_docx(data))]); parts = {}
    if fault == 'duplicate-note':
        root = xml(data, 'word/footnotes.xml')
        from copy import deepcopy
        root.append(deepcopy(root.xpath('w:footnote[@w:id="1"]', namespaces=NS)[0]))
        parts['word/footnotes.xml'] = etree.tostring(root)
    elif fault == 'dangling-reference':
        root = xml(data, 'word/document.xml'); root.xpath('//w:footnoteReference', namespaces=NS)[0].set(f'{{{W}}}id', '999')
        parts['word/document.xml'] = etree.tostring(root)
    else:
        root = xml(data, 'word/_rels/document.xml.rels')
        for rel in root:
            if rel.get('Type', '').endswith('/footnotes'): rel.set('Target', 'notes/nonstandard.xml')
        parts['word/_rels/document.xml.rels'] = etree.tostring(root)
    data = replace_parts(data, parts); model = inspect_docx(data)
    assert 'notes' not in model
    block = model['blocks'][1]; assert block['editable']
    output = patch_docx(data, [{'kind': 'replaceParagraph', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'text': 'Still editable'}])
    assert xml(output, 'word/document.xml').xpath('/w:document/w:body/w:p[2]//w:t/text()', namespaces=NS) == ['Still editable']


def test_table_cell_reference_disables_note_deletion_instead_of_leaving_a_dangling_marker():
    data = source(); data = patch_docx(data, [insert(inspect_docx(data))])
    doc = Document(BytesIO(data)); cell = doc.add_table(rows=1, cols=1).cell(0, 0)
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    marker = OxmlElement('w:footnoteReference'); marker.set(qn('w:id'), '1'); cell.paragraphs[0].add_run()._r.append(marker)
    out = BytesIO(); doc.save(out); data = out.getvalue()
    model = inspect_docx(data)
    assert 'notes' not in model
    block = model['blocks'][1]
    output = patch_docx(data, [{'kind': 'replaceParagraph', 'blockId': block['blockId'], 'expectedObjectSha256': block['expectedObjectSha256'], 'text': 'Still editable'}])
    assert len(xml(output, 'word/document.xml').xpath('//w:footnoteReference', namespaces=NS)) == 2


@pytest.mark.parametrize('kind', ['footnote', 'endnote'])
def test_reference_block_text_uses_single_marker_and_actual_utf16_run_coordinates(kind):
    """AI 插入坐标沿用 planner run 投影，不把多位显示编号当正文字符。"""
    from docx.enum.text import WD_BREAK

    document = Document()
    paragraph = document.add_paragraph('甲😀')
    run = paragraph.add_run()
    run.add_tab()
    run.add_break()
    run.add_break(WD_BREAK.PAGE)
    paragraph.add_run('尾')
    output = BytesIO()
    document.save(output)
    data = output.getvalue()
    model = inspect_docx(data)
    assert model['notes']['referenceBlocks'][0]['text'] == '甲😀\t\n\f尾'
    # 第10–12个引用具有多位显示编号，写入坐标仍各占一个UTF-16码元。
    data = patch_docx(data, [insert(model, kind, text=f'注释{index}') for index in range(12)])
    current = inspect_docx(data)
    reference = current['notes']['referenceBlocks'][0]
    expected = '甲😀' + '\ufffc' * 12 + '\t\n\f尾'
    assert reference['text'] == expected
    assert len(expected.encode('utf-16-le')) // 2 == 19
    assert reference['text'] != current['blocks'][0]['text']
    assert reference['blockId'] == current['blocks'][0]['blockId']
    assert reference['expectedObjectSha256'] == current['blocks'][0]['expectedObjectSha256']
    assert reference['editable'] is True
    # 用返回文本的UTF-16坐标在引用之后、tab之前插入，真实保存后原控制字符保留。
    offset = len(('甲😀' + '\ufffc' * 12).encode('utf-16-le')) // 2
    saved = patch_docx(data, [insert(current, kind, offset=offset, text='精确坐标新增')])
    updated = inspect_docx(saved)
    assert updated['notes']['referenceBlocks'][0]['text'] == '甲😀' + '\ufffc' * 13 + '\t\n\f尾'
    assert updated['notes'][kind + 's'][-1]['text'] == '精确坐标新增'
    document_xml = xml(saved, 'word/document.xml')
    assert len(document_xml.xpath(f'//w:{kind}Reference', namespaces=NS)) == 13
    assert len(document_xml.xpath('//w:tab', namespaces=NS)) == 1
    assert len(document_xml.xpath('//w:br', namespaces=NS)) == 2
