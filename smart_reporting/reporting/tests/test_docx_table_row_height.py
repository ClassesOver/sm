"""来源行高编辑保留规则、段落和非目标部件。"""
from io import BytesIO
from zipfile import ZipFile

import pytest
from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.oxml.ns import qn

from smart_reporting.reporting.delivery.docx_native import inspect_docx, patch_docx


def source():
    doc = Document()
    table = doc.add_table(rows=2, cols=2)
    for index, cell in enumerate(table._cells):
        cell.text = f'原始中文段落 {index}'
        cell.paragraphs[0]._p.set(qn('w:rsidR'), '12345678')
    table.rows[0].height = 300 * 635
    table.rows[0].height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
    out = BytesIO()
    doc.save(out)
    return out.getvalue()


def anchor(content):
    return next(item for item in inspect_docx(content)['blocks'] if item['type'] == 'table')


def operation(content, steps):
    target = anchor(content)
    return {'kind': 'setTableRowHeights', 'blockId': target['blockId'],
            'expectedObjectSha256': target['expectedObjectSha256'], 'steps': steps}


def test_set_clear_row_height_preserves_exact_rule_and_original_paragraphs():
    content = source()
    assert anchor(content).get('rowHeightEditable') is True
    result = patch_docx(content, [operation(content, [{'top': 0, 'bottom': 2, 'heightTwips': 600}])])
    table = Document(BytesIO(result)).tables[0]
    assert [int(row.height / 635) for row in table.rows] == [600, 600]
    assert table.rows[0].height_rule == WD_ROW_HEIGHT_RULE.EXACTLY
    assert table.rows[1].height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST
    cleared = patch_docx(result, [operation(result, [{'top': 0, 'bottom': 1, 'heightTwips': None}])])
    table = Document(BytesIO(cleared)).tables[0]
    assert table.rows[0]._tr.trPr.find(qn('w:trHeight')) is None
    original = Document(BytesIO(content)).tables[0]
    assert [p._p.xml for c in table._cells for p in c.paragraphs] == [p._p.xml for c in original._cells for p in c.paragraphs]
    for output in [result, cleared]:
        with ZipFile(BytesIO(content)) as before, ZipFile(BytesIO(output)) as after:
            names = {name for name in before.namelist() if not name.endswith('/')}
            assert names == {name for name in after.namelist() if not name.endswith('/')}
            assert [name for name in names if before.read(name) != after.read(name)] == ['word/document.xml']


@pytest.mark.parametrize('step', [
    {'top': 0, 'bottom': 1, 'heightTwips': True},
    {'top': 0, 'bottom': 3, 'heightTwips': 600},
    {'top': 0, 'bottom': 1, 'heightTwips': -1},
    {'top': 0, 'bottom': 1, 'heightTwips': 600, 'maxHeightTwips': 999999},
])
def test_row_height_rejects_invalid_steps(step):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, [step])])


def test_row_height_uses_actual_section_bound_and_rejects_layout_mix():
    from copy import deepcopy
    from docx.enum.section import WD_SECTION
    doc = Document(BytesIO(source()))
    second = doc.add_section(WD_SECTION.NEW_PAGE)
    second.page_height = 12000 * 635
    second.top_margin = 1200 * 635
    second.bottom_margin = 1800 * 635
    doc._body._body.insert(-1, deepcopy(doc.tables[0]._tbl))
    out = BytesIO()
    doc.save(out)
    content = out.getvalue()
    model = inspect_docx(content)
    targets = [item for item in model['blocks'] if item['type'] == 'table']
    limits = [int((s.page_height - s.top_margin - s.bottom_margin) / 635) for s in doc.sections]
    assert [item['rowHeightMaxTwips'] for item in targets] == limits
    target = targets[1]
    op = {'kind': 'setTableRowHeights', 'blockId': target['blockId'],
          'expectedObjectSha256': target['expectedObjectSha256'],
          'steps': [{'top': 0, 'bottom': 1, 'heightTwips': 30000}]}
    result = patch_docx(content, [op])
    after = [item for item in inspect_docx(result)['blocks'] if item['type'] == 'table']
    assert after[1]['rowHeightsTwips'][0] == limits[1]
    assert after[0]['expectedObjectSha256'] == targets[0]['expectedObjectSha256']
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'maxHeightTwips': 31680}])
    section = model['sections'][1]
    layout = {'kind': 'setSectionLayout', 'sectionId': section['sectionId'],
              'expectedSectionSha256': section['expectedSectionSha256'], 'values': {'marginTop': 2400}}
    for batch in [[op, layout], [layout, op]]:
        with pytest.raises(ValueError, match='batch_conflict'):
            patch_docx(content, batch)


def test_row_height_rejects_protected_source_and_forged_identity():
    from docx.oxml import OxmlElement
    content = source()
    op = operation(content, [{'top': 0, 'bottom': 1, 'heightTwips': 600}])
    with pytest.raises(ValueError):
        patch_docx(content, [{**op, 'expectedObjectSha256': '0' * 64}])
    doc = Document(BytesIO(content))
    protection = OxmlElement('w:documentProtection')
    protection.set(qn('w:edit'), 'readOnly')
    protection.set(qn('w:enforcement'), '1')
    doc.settings._element.append(protection)
    out = BytesIO()
    doc.save(out)
    protected = out.getvalue()
    assert anchor(protected)['rowHeightEditable'] is False
    with pytest.raises(ValueError):
        patch_docx(protected, [operation(protected, op['steps'])])


@pytest.mark.parametrize(('value', 'rule'), [(300, 'auto'), (0, 'auto'), (0, None)])
def test_automatic_source_height_can_be_set_and_cleared(value, rule):
    doc = Document(BytesIO(source()))
    height = doc.tables[0].rows[0]._tr.trPr.find(qn('w:trHeight'))
    height.set(qn('w:val'), str(value))
    if rule is None:
        height.attrib.pop(qn('w:hRule'), None)
    else:
        height.set(qn('w:hRule'), rule)
    out = BytesIO()
    doc.save(out)
    content = out.getvalue()
    assert anchor(content)['rowHeightEditable'] is True
    changed = patch_docx(content, [operation(content, [{'top': 0, 'bottom': 1, 'heightTwips': 600}])])
    result = Document(BytesIO(changed)).tables[0].rows[0]
    assert int(result.height / 635) == 600
    assert result.height_rule == WD_ROW_HEIGHT_RULE.AT_LEAST
    cleared = patch_docx(content, [operation(content, [{'top': 0, 'bottom': 1, 'heightTwips': None}])])
    assert Document(BytesIO(cleared)).tables[0].rows[0]._tr.trPr.find(qn('w:trHeight')) is None


def test_distribute_rows_forces_at_least_and_replays_in_order():
    content = source()
    steps = [{'top': 0, 'bottom': 1, 'heightTwips': 600},
             {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': 750},
             {'top': 0, 'bottom': 1, 'heightTwips': 900}]
    result = patch_docx(content, [operation(content, steps)])
    rows = Document(BytesIO(result)).tables[0].rows
    assert [int(row.height / 635) for row in rows] == [900, 750]
    assert [row.height_rule for row in rows] == [WD_ROW_HEIGHT_RULE.AT_LEAST] * 2
    cleared = patch_docx(result, [operation(result, [
        {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': 600},
        {'top': 0, 'bottom': 1, 'heightTwips': None},
    ])])
    assert Document(BytesIO(cleared)).tables[0].rows[0]._tr.trPr.find(qn('w:trHeight')) is None


@pytest.mark.parametrize('step', [
    {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': None},
    {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': 0},
    {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': 600, 'heightRule': 'exact'},
    {'kind': 'unknown', 'top': 0, 'bottom': 2, 'heightTwips': 600},
])
def test_distribute_rows_rejects_invalid_protocol(step):
    content = source()
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, [step])])


def test_distribute_rows_preserves_measured_height_above_section_bound():
    content = source()
    limit = anchor(content)['rowHeightMaxTwips']
    measured = limit + 300
    assert measured <= 31680
    result = patch_docx(content, [operation(content, [
        {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': measured},
    ])])
    assert anchor(result)['rowHeightsTwips'] == [measured, measured]
    with pytest.raises(ValueError):
        patch_docx(content, [operation(content, [
            {'kind': 'distributeTableRows', 'top': 0, 'bottom': 2, 'heightTwips': 31681},
        ])])
