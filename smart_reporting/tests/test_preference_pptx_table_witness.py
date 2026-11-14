"""原生表格组见证记录实际覆盖对象；不将可解析性视为视觉证据。"""

from io import BytesIO

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.reporting.tests.test_pptx_native_tables import preferences

MARKER = 'pptx_native_table_fields_v1'


def table_readback(source_count=1, native_count=1, body_values=None):
    deck = Presentation()
    cover = deck.slides.add_slide(deck.slide_layouts[6])
    heading = cover.shapes.add_textbox(Inches(.5), Inches(.2), Inches(8), Inches(.6))
    heading.text = '表格见证'
    heading.text_frame.paragraphs[0].runs[0].font.size = Pt(16)
    heading.text_frame.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string('174A66')
    for _ in range(native_count):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        table = slide.shapes.add_table(2, 2, Inches(.5), Inches(1), Inches(8), Inches(1)).table
        for row, values in zip(table.rows, [['期间', '指标'], body_values or ['2025', '1.2000']], strict=True):
            for cell, value in zip(row.cells, values, strict=True):
                cell.text = value
    output = BytesIO()
    deck.save(output)
    source = {'caption': '登记指标', 'headers': ['期间', '指标'], 'rows': [body_values or ['2025', '1.2000']]}
    frozen = {'state': {'_documentContext': {'title': '表格见证', 'periodLabel': '2025年',
        'generatedDate': '2026-11-13'}}, 'slides': ({'title': '登记指标', 'bullets': [],
        'tables': [source.copy() for _ in range(source_count)]},)}
    return readback(output.getvalue(), 'pptx', preferences(), frozen)['checks']


def test_table_group_witness_marks_only_all_table_checks_with_actual_object_counts():
    checks = table_readback()
    table_checks = [item for item in checks if item['path'] and (
        item['path'].startswith('pptx.tables.') or item['path'].startswith('pptx.typography.table.'))]
    assert table_checks and all(item.get('evidenceKind') == MARKER for item in table_checks)
    witness = [item for item in table_checks if item['path'] == 'pptx.tables.objectCoverage']
    assert len(witness) == 1 and witness[0]['passed'] is True
    assert witness[0]['evidenceObjects'] == {'sourceTables': 1, 'nativeTables': 1, 'checkedNativeTables': 1,
        'bodyRuns': 2}
    assert all(item.get('evidenceKind') != MARKER for item in checks if item not in table_checks)


@pytest.mark.parametrize('source_count,native_count', [(1, 0), (0, 1), (2, 1), (1, 2)])
def test_missing_or_extra_native_tables_cannot_offer_complete_success(source_count, native_count):
    checks = table_readback(source_count, native_count)
    group = [item for item in checks if item.get('evidenceKind') == MARKER]
    assert group and any(item['passed'] is False for item in group)
    witness = next(item for item in group if item['path'] == 'pptx.tables.objectCoverage')
    assert witness['evidenceObjects']['sourceTables'] == source_count
    assert witness['evidenceObjects']['nativeTables'] == native_count


def test_no_table_objects_produce_no_group_witness():
    assert not any(item.get('evidenceKind') == MARKER for item in table_readback(0, 0))


def test_empty_native_body_without_runs_does_not_claim_body_style_objects():
    witness = next(item for item in table_readback(body_values=['', ''])
        if item['path'] == 'pptx.tables.objectCoverage')
    assert witness['evidenceObjects']['bodyRuns'] == 0
