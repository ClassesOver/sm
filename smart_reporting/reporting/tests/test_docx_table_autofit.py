"""AutoFit三个模式必须可回放并保留原段落和非目标文件。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def test_autofit_modes_survive_save_reopen_without_rebuilding_paragraphs():
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    table.autofit = False
    for i, cell in enumerate(table._cells):
        cell.text = f'中文原内容 {i}'
        cell.paragraphs[0]._p.set(qn('w:rsidR'), '12345678')
    buffer = BytesIO()
    doc.save(buffer)
    original = buffer.getvalue()
    content = original
    paragraphs = [p._p.xml for cell in table._cells for p in cell.paragraphs]
    for mode in ['contents', 'window', 'fixed']:
        target = next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')
        assert target.get('autoFitEditable') is True
        content = patch_docx(content, [{'kind': 'setTableAutoFit', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'steps': [{'mode': mode}]}])
        after = next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')
        assert after['autoFitMode'] == mode
        assert [p._p.xml for cell in Document(BytesIO(content)).tables[0]._cells for p in cell.paragraphs] == paragraphs
        with ZipFile(BytesIO(original)) as before_zip, ZipFile(BytesIO(content)) as after_zip:
            names = {name for name in before_zip.namelist() if not name.endswith('/')}
            assert names == {name for name in after_zip.namelist() if not name.endswith('/')}
            assert [name for name in names if before_zip.read(name) != after_zip.read(name)] == ['word/document.xml']


@pytest.mark.parametrize('steps', [[{'mode': 'unknown'}], [{'mode': 'fixed', 'widthTwips': 999}], [], [{'mode': True}]])
def test_autofit_rejects_forged_steps(steps):
    doc = Document()
    doc.add_table(rows=1, cols=2)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    target = next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')
    with pytest.raises(ValueError):
        patch_docx(content, [{'kind': 'setTableAutoFit', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'steps': steps}])


def test_autofit_uses_source_section_width_and_rejects_layout_mix():
    from docx.enum.section import WD_SECTION
    doc = Document()
    doc.add_table(rows=1, cols=2)
    second = doc.add_section(WD_SECTION.NEW_PAGE)
    second.page_width = 10000 * 635
    second.left_margin = 1800 * 635
    second.right_margin = 1800 * 635
    doc.add_table(rows=1, cols=2)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    model = inspect_docx(content)
    targets = [block for block in model['blocks'] if block['type'] == 'table']
    assert [block['autoFitContentWidthTwips'] for block in targets] == [
        int((section.page_width - section.left_margin - section.right_margin) / 635) for section in doc.sections]
    target = targets[1]
    op = {'kind': 'setTableAutoFit', 'blockId': target['blockId'],
          'expectedObjectSha256': target['expectedObjectSha256'],
          'steps': [{'mode': 'contents'}, {'mode': 'window'}, {'mode': 'fixed'}]}
    result = patch_docx(content, [op])
    after = [block for block in inspect_docx(result)['blocks'] if block['type'] == 'table']
    assert after[1]['autoFitWidthsTwips'] == [3195, 3195]
    assert after[0]['expectedObjectSha256'] == targets[0]['expectedObjectSha256']
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'contentWidthTwips': 31680}])
    section = model['sections'][1]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginLeft': 2500}}
    for batch in [[op, layout], [layout, op]]:
        with pytest.raises(ValueError, match='batch_conflict'):
            patch_docx(content, batch)


def test_autofit_rejects_protected_source_forged_identity_and_ambiguous_columns():
    from docx.oxml import OxmlElement
    doc = Document()
    doc.add_table(rows=1, cols=2)
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    target = next(block for block in inspect_docx(content)['blocks'] if block['type'] == 'table')
    op = {'kind': 'setTableAutoFit', 'blockId': target['blockId'],
          'expectedObjectSha256': target['expectedObjectSha256'], 'steps': [{'mode': 'fixed'}]}
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    buffer = BytesIO()
    doc.save(buffer)
    protected = buffer.getvalue()
    target = next(block for block in inspect_docx(protected)['blocks'] if block['type'] == 'table')
    assert target['autoFitEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [{**op, 'blockId': target['blockId'], 'expectedObjectSha256': target['expectedObjectSha256']}])
    doc.settings._element.remove(protection)
    doc.sections[0]._sectPr.find(qn('w:cols')).set(qn('w:num'), '2')
    buffer = BytesIO()
    doc.save(buffer)
    target = next(block for block in inspect_docx(buffer.getvalue())['blocks'] if block['type'] == 'table')
    assert target['autoFitEditable'] is False


def test_autofit_can_mix_independent_section_break():
    from docx.enum.section import WD_SECTION
    doc = Document()
    doc.add_table(rows=1, cols=2)
    doc.add_section(WD_SECTION.NEW_PAGE)
    doc.add_paragraph('另一节的分节锚点')
    buffer = BytesIO()
    doc.save(buffer)
    content = buffer.getvalue()
    model = inspect_docx(content)
    table = next(block for block in model['blocks'] if block['type'] == 'table')
    paragraph = next(block for block in model['blocks'] if block['text'] == '另一节的分节锚点')
    assert table['autoFitSectionId'] != paragraph['sourceSectionId']
    fit = {'kind': 'setTableAutoFit', 'blockId': table['blockId'],
           'expectedObjectSha256': table['expectedObjectSha256'], 'steps': [{'mode': 'contents'}]}
    split = {'kind': 'insertSectionBreak', 'blockId': paragraph['blockId'],
             'expectedObjectSha256': paragraph['expectedObjectSha256'], 'type': 'nextPage'}
    for operations in [[fit, split], [split, fit]]:
        result = inspect_docx(patch_docx(content, operations))
        assert len(result['sections']) == 3
        assert next(block for block in result['blocks'] if block['type'] == 'table')['autoFitMode'] == 'contents'
