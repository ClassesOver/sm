"""完整段落对话框：原 XML 段落属性原子补丁与独立回读。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    para = doc.add_paragraph('目标正文')
    para.add_run(' 保留粗体').bold = True
    spacing = OxmlElement('w:spacing')
    for name, value in {'line': '250', 'lineRule': 'auto', 'after': '120', 'afterLines': '200'}.items():
        spacing.set(qn('w:' + name), value)
    para._p.get_or_add_pPr().append(spacing)
    para._p.pPr.append(OxmlElement('w:keepNext'))
    doc.add_paragraph('旁边正文')
    doc.sections[0].header.paragraphs[0].text = '保留页眉'
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def operation(data, values):
    target = inspect_docx(data)['blocks'][0]
    return {'kind': 'setParagraphProperties', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'values': values}


def test_full_paragraph_properties_combines_page_break_flags_outline_and_layout_in_schema_order():
    before = source()
    values = {'align': 'center', 'indentLeft': -365, 'indentRight': 247, 'indentFirstLine': 360,
              'spaceBefore': 0, 'keepNext': False, 'keepLines': True, 'widowControl': False,
              'suppressLineNumbers': True, 'contextualSpacing': True, 'pageBreakBefore': True, 'outlineLevel': 3}
    after = patch_docx(before, [operation(before, values)])
    original, changed = Document(BytesIO(before)), Document(BytesIO(after))
    p = changed.paragraphs[0]
    assert p.paragraph_format.page_break_before is True
    assert p.paragraph_format.keep_with_next is False
    assert p.paragraph_format.keep_together is True
    assert p.paragraph_format.widow_control is False
    assert p._p.pPr.find(qn('w:suppressLineNumbers')) is not None
    assert p._p.pPr.find(qn('w:contextualSpacing')) is not None
    assert p.paragraph_format.left_indent.twips == -365
    assert p.paragraph_format.right_indent.twips == 247
    assert p.paragraph_format.first_line_indent.twips == 360
    assert p.paragraph_format.space_before.twips == 0
    assert p._p.pPr.find(qn('w:outlineLvl')).get(qn('w:val')) == '2'
    spacing = p._p.pPr.find(qn('w:spacing'))
    assert {key: spacing.get(qn('w:' + key)) for key in ['line', 'lineRule', 'after', 'afterLines']} == {'line': '250', 'lineRule': 'auto', 'after': '120', 'afterLines': '200'}
    names = [child.tag.split('}')[1] for child in p._p.pPr]
    assert names.index('keepNext') < names.index('pageBreakBefore') < names.index('spacing') < names.index('ind') < names.index('jc') < names.index('outlineLvl')
    assert [run._r.xml for run in p.runs] == [run._r.xml for run in original.paragraphs[0].runs]
    assert changed.paragraphs[1]._p.xml == original.paragraphs[1]._p.xml
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        for name in a.namelist():
            if name != 'word/document.xml':
                assert a.read(name) == b.read(name), name
    model = inspect_docx(after)['blocks'][0]
    assert model['type'] == 'heading'


@pytest.mark.parametrize('values', [{'keepNext': 'false'}, {'outlineLevel': 10}, {'indentLeft': True}, {'unknown': 1}, {'align': 'distribute'}, {'lineRule': 'auto', 'lineSpacing': 1}, {}])
def test_full_paragraph_properties_rejects_invalid_values(values):
    data = source()
    with pytest.raises(ValueError):
        patch_docx(data, [operation(data, values)])


def test_full_paragraph_properties_rejects_forged_identity_and_same_paragraph_batch():
    data = source()
    op = operation(data, {'keepNext': False})
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(data, [{**op, 'expectedObjectSha256': 'f' * 64}])
    with pytest.raises(ValueError, match='paragraph_properties_batch_conflict'):
        patch_docx(data, [op, {'kind': 'setParagraphPageBreakBefore', 'blockId': op['blockId'], 'expectedObjectSha256': op['expectedObjectSha256'], 'value': True}])


def test_full_paragraph_properties_false_overrides_and_character_indent_preserve_unrelated_attributes():
    before = source()
    after = patch_docx(before, [operation(before, {'pageBreakBefore': False, 'spaceAfter': 0, 'indentFirstLine': 480, 'indentFirstLineChars': 200})])
    p = Document(BytesIO(after)).paragraphs[0]
    assert p._p.pPr.find(qn('w:pageBreakBefore')).get(qn('w:val')) == '0'
    assert p._p.pPr.find(qn('w:ind')).get(qn('w:firstLineChars')) == '200'
    assert p._p.pPr.find(qn('w:spacing')).get(qn('w:after')) == '0'
    assert p._p.pPr.find(qn('w:spacing')).get(qn('w:afterLines')) is None
    assert p._p.pPr.find(qn('w:spacing')).get(qn('w:line')) == '250'


def test_full_paragraph_properties_rejects_protection_and_style_heading_outline():
    doc = Document(BytesIO(source()))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1')
    doc.settings.element.append(protection)
    out = BytesIO(); doc.save(out)
    with pytest.raises(ValueError):
        patch_docx(out.getvalue(), [operation(out.getvalue(), {'keepNext': False})])
    doc = Document(BytesIO(source())); doc.paragraphs[0].style = 'Heading 1'
    out = BytesIO(); doc.save(out)
    with pytest.raises(ValueError):
        patch_docx(out.getvalue(), [operation(out.getvalue(), {'outlineLevel': 3})])


def test_full_paragraph_properties_rejects_aliased_and_encoded_document_protection():
    data = source()
    with ZipFile(BytesIO(data)) as source_zip:
        output = BytesIO()
        with ZipFile(output, 'w') as target_zip:
            for name in source_zip.namelist():
                content = source_zip.read(name)
                if name == 'word/settings.xml':
                    content = content.replace(b'</w:settings>', b'<x:documentProtection xmlns:x="http://schemas.openxmlformats.org/wordprocessingml/2006/main" x:enforcement="&#49;" x:edit="readOnly"/></w:settings>')
                target_zip.writestr(name, content)
    protected = output.getvalue()
    assert inspect_docx(protected)['blocks'][0]['paragraphPropertiesEditable'] is False
    with pytest.raises(ValueError, match='paragraph_properties_unsupported|docx_protection_content_locked'):
        patch_docx(protected, [operation(protected, {'keepNext': False})])


def test_full_paragraph_range_keeps_each_untouched_property_runs_and_package_parts():
    before = source()
    original = Document(BytesIO(before))
    blocks = inspect_docx(before)['blocks']
    operations = [dict(kind='setParagraphProperties', blockId=block['blockId'],
                       expectedObjectSha256=block['expectedObjectSha256'],
                       values={'keepLines': True, 'spaceBefore': 180}) for block in blocks[:2]]
    after = patch_docx(before, operations)
    changed = Document(BytesIO(after))
    for old, new in zip(original.paragraphs, changed.paragraphs):
        assert new.paragraph_format.keep_together is True
        assert new.paragraph_format.space_before.twips == 180
        assert [run._r.xml for run in old.runs] == [run._r.xml for run in new.runs]
        for child in list(old._p.pPr) if old._p.pPr is not None else []:
            if child.tag != qn('w:spacing'):
                assert new._p.pPr.find(child.tag).xml == child.xml
    assert changed.paragraphs[0]._p.pPr.find(qn('w:spacing')).get(qn('w:line')) == '250'
    assert changed.paragraphs[1].paragraph_format.line_spacing is None
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        assert {name for name in a.namelist() if not name.endswith('/')} == {name for name in b.namelist() if not name.endswith('/')}
        for name in a.namelist():
            if name != 'word/document.xml':
                assert a.read(name) == b.read(name), name
    reloaded = inspect_docx(after)['blocks']
    assert [block['text'] for block in reloaded[:2]] == [block['text'] for block in blocks[:2]]
    assert all(a['expectedObjectSha256'] != b['expectedObjectSha256'] for a, b in zip(blocks[:2], reloaded[:2]))
    operations[1]['expectedObjectSha256'] = 'f' * 64
    with pytest.raises(ValueError, match='anchor_invalid'):
        patch_docx(before, operations)


def test_simple_cell_paragraph_range_validates_original_hashes_and_preserves_xml():
    doc = Document()
    table = doc.add_table(rows=1, cols=2)
    cell = table.cell(0, 0)
    cell.paragraphs[0].add_run('第一段粗体').bold = True
    cell.add_paragraph('第二段').paragraph_format.space_after = __import__('docx').shared.Pt(13)
    table.cell(0, 1).text = '其他单元格'
    doc.add_paragraph('表外保留')
    out = BytesIO(); doc.save(out); before = out.getvalue()
    block = inspect_docx(before)['blocks'][0]
    identity = block['cells'][0][0]
    operations = [dict(kind='setTableCellParagraphProperties', blockId=block['blockId'],
                       expectedObjectSha256=block['expectedObjectSha256'], cellId=identity['cellId'],
                       expectedCellSha256=identity['expectedObjectSha256'], paragraphIndex=paragraph['index'],
                       expectedParagraphSha256=paragraph['expectedObjectSha256'], values={'keepLines': True})
                  for paragraph in identity['paragraphs']]
    after = patch_docx(before, operations)
    changed = Document(BytesIO(after))
    for old, new in zip(cell.paragraphs, changed.tables[0].cell(0, 0).paragraphs):
        assert new.paragraph_format.keep_together is True
        assert [run._r.xml for run in new.runs] == [run._r.xml for run in old.runs]
        assert new.paragraph_format.space_after == old.paragraph_format.space_after
    assert changed.tables[0].cell(0, 1)._tc.xml == table.cell(0, 1)._tc.xml
    assert changed.paragraphs[0]._p.xml == doc.paragraphs[0]._p.xml
    with ZipFile(BytesIO(before)) as a, ZipFile(BytesIO(after)) as b:
        for name in a.namelist():
            if name != 'word/document.xml': assert a.read(name) == b.read(name)
    with pytest.raises(ValueError): patch_docx(before, [operations[0], operations[0]])
    forged = {**operations[1], 'expectedParagraphSha256': 'f' * 64}
    with pytest.raises(ValueError, match='anchor_invalid'): patch_docx(before, [operations[0], forged])


@pytest.mark.parametrize('complexity', ['nested', 'merged', 'field', 'protected'])
def test_cell_paragraph_range_keeps_complex_sources_read_only(complexity):
    doc = Document(); table = doc.add_table(rows=1, cols=2)
    cell = table.cell(0, 0); cell.text = '第一段'; cell.add_paragraph('第二段')
    if complexity == 'nested': cell.add_table(rows=1, cols=1)
    elif complexity == 'merged': cell.merge(table.cell(0, 1))
    elif complexity == 'field':
        field = OxmlElement('w:fldSimple'); field.set(qn('w:instr'), 'PAGE')
        cell.paragraphs[0]._p.append(field)
    else:
        protection = OxmlElement('w:documentProtection')
        protection.set(qn('w:edit'), 'readOnly'); protection.set(qn('w:enforcement'), '1')
        doc.settings.element.append(protection)
    out = BytesIO(); doc.save(out); before = out.getvalue()
    block = inspect_docx(before)['blocks'][0]; identity = block['cells'][0][0]
    assert all(not paragraph['editable'] for paragraph in identity['paragraphs'])
    paragraph = identity['paragraphs'][0]
    op = dict(kind='setTableCellParagraphProperties', blockId=block['blockId'], expectedObjectSha256=block['expectedObjectSha256'],
              cellId=identity['cellId'], expectedCellSha256=identity['expectedObjectSha256'], paragraphIndex=paragraph['index'],
              expectedParagraphSha256=paragraph['expectedObjectSha256'], values={'keepLines': True})
    with pytest.raises(ValueError): patch_docx(before, [op])
