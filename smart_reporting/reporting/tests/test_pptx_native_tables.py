"""PPTX 原生表格只消费受控表体，续页和样式可独立回读。"""
import json
from hashlib import sha256
from io import BytesIO

import pytest
from pptx import Presentation

from smart_reporting.preferences.models import FormatPreferences, resolve_format_preferences
from smart_reporting.reporting.delivery.pptx import build_editable_pptx


def table_input(rows=24):
    return {'tableId': 'frozen-table', 'caption': '冻结收入表',
        'headers': ['期间', '收入（元）'],
        'rows': [[f'2025-{index + 1:02}', '1234.5600' if index == 0 else str(index)] for index in range(rows)],
        'sourceAnalysisId': 'analysis_001',
        'sourceFile': {'path': 'facts/analysis_001.json', 'size': 2, 'sha256': sha256(b'{}').hexdigest()}}


def preferences(**tables):
    return resolve_format_preferences(FormatPreferences.model_validate({'common': {'signer': '冻结署名'},
        'pptx': {'tables': tables, 'typography': {'table': {'size': 18, 'color': '#123456',
            'bold': True, 'font': 'serif', 'lineHeight': 1.3}}}}), 'pptx')


def test_native_table_paginated_repeats_headers_and_preserves_literal_values(tmp_path):
    source = table_input()
    output = tmp_path / 'tables.pptx'
    built = build_editable_pptx(output_path=output, title='受控表格', period='2025年', theme='executive',
        slides=({'title': '分析结论', 'bullets': ['来源已冻结'], 'tables': [source]},),
        preferences=preferences(borders='all', striped=True), generated_date='2026-11-13')
    deck = Presentation(output)
    shapes = [shape for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert len(shapes) > 1
    actual_rows = []
    for shape in shapes:
        assert [cell.text for cell in shape.table.rows[0].cells] == source['headers']
        actual_rows.extend([[cell.text for cell in row.cells] for row in list(shape.table.rows)[1:]])
        assert shape.top + shape.height < deck.slide_height * 660 / 720
        run = shape.table.cell(1, 1).text_frame.paragraphs[0].runs[0]
        assert run.font.size.pt == 18
        assert str(run.font.color.rgb) == '123456'
        assert run.font.bold is True
        assert 'a:lnL' in shape.table.cell(1, 1)._tc.xml
    assert actual_rows == source['rows']
    assert built.issues == ()


def test_native_table_repeat_header_off_and_bad_grid_are_nonblocking(tmp_path):
    source = table_input()
    output = tmp_path / 'no-repeat.pptx'
    built = build_editable_pptx(output_path=output, title='受控表格', period='2025年', theme='executive',
        slides=({'title': '分析结论', 'bullets': ['保留正文'], 'tables': [source,
            {**source, 'rows': [['缺列']]}]},),
        preferences=preferences(repeatHeader=False, borders='none', striped=False), generated_date='2026-11-13')
    deck = Presentation(output)
    grids = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert len(grids) > 1
    assert [cell.text for cell in grids[0].rows[0].cells] == source['headers']
    assert [cell.text for cell in grids[1].rows[0].cells] != source['headers']
    assert any(issue['code'] == 'pptx_table_input_invalid' for issue in built.issues)
    assert '保留正文' in '\n'.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)


def test_native_wide_table_and_overlong_cell_keep_every_literal_and_return_specific_warning(tmp_path):
    source = table_input(rows=1)
    source['headers'] = ['期间', *[f'列{index}' for index in range(8)]]
    source['rows'] = [['原始期间', '极长内容' * 2000, *[f'{index}.0000' for index in range(7)]]]
    output = tmp_path / 'wide.pptx'
    built = build_editable_pptx(output_path=output, title='受控宽表', period='2025年', theme='executive',
        slides=({'title': '宽表', 'bullets': [], 'tables': [source]},),
        preferences=preferences(captionNumbering=False), generated_date='2026-11-13')
    deck = Presentation(output)
    tables = [shape for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert len(tables) == 2
    recovered = [tables[0].table.cell(1, 0).text,
        *[table.table.cell(1, col).text for table in tables for col in range(1, len(table.table.columns))]]
    assert recovered == source['rows'][0]
    assert all(shape.top + shape.height <= deck.slide_height * 640 / 720 for shape in tables)
    assert any(issue.get('code') == 'pptx_table_row_unfit' for issue in built.issues)
    assert not any(getattr(shape, 'text', '').startswith('表 1 ') for slide in deck.slides for shape in slide.shapes)


def test_projection_rejects_source_identity_and_analysis_mismatch():
    from smart_reporting.reporting.delivery.pptx_tables import project_fact_slide_tables
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity

    from .test_trace_table_builder import _bundle

    raw = _bundle().model_dump_json(by_alias=True).encode()
    identity = FileIdentity(path='facts/analysis.json', size=len(raw), sha256=sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='source_identity_mismatch'):
        project_fact_slide_tables('analysis_001', identity, raw + b' ')
    with pytest.raises(ValueError, match='source_analysis_mismatch'):
        project_fact_slide_tables('analysis_999', identity, raw)


def test_four_three_native_table_grid_matches_actual_frame_and_preserves_multiline(tmp_path):
    source = table_input(rows=2)
    source['rows'][0][0] = '第一行\n第二行含|符号与&原值'
    prefs = {**preferences(), 'aspectRatio': '4:3'}
    output = tmp_path / 'four-three.pptx'
    build_editable_pptx(output_path=output, title='4:3表格', period='2025年', theme='executive',
        slides=({'title': '多行表格', 'bullets': ['原正文保留'], 'tables': [source]},),
        preferences=prefs, generated_date='2026-11-13')
    deck = Presentation(output)
    shape = next(shape for slide in deck.slides for shape in slide.shapes if shape.has_table)
    assert abs(sum(column.width for column in shape.table.columns) - shape.width) <= 2
    assert shape.table.cell(1, 0).text == source['rows'][0][0]
    assert shape.left + shape.width < deck.slide_width


@pytest.mark.anyio
async def test_formal_generation_freezes_controlled_fact_tables_and_actual_editable_cells(tmp_path, monkeypatch):
    from smart_reporting.reporting.delivery.pptx_tables import project_fact_slide_tables
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity

    from .test_pptx_native_input import pptx_native_case

    case = await pptx_native_case(tmp_path, monkeypatch, with_tables=True)
    native = case.rendered['pptxNativeInput']
    async def read(file):
        return await case.runtime._read_identity_bytes(case.scope.workspace_key, FileIdentity.model_validate(file))

    spec = json.loads(await read(native['spec']))
    table = spec['slides'][0]['tables'][0]
    assert table['sourceFile'] in case.durable.payload['artifacts']
    assert spec['slides'][0]['tables'] == project_fact_slide_tables(table['sourceAnalysisId'],
        FileIdentity.model_validate(table['sourceFile']), await read(table['sourceFile']))
    deck = Presentation(BytesIO(await read(native['artifact'])))
    actual = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert [[cell.text for cell in row.cells] for row in actual[0].rows] == [table['headers'], *table['rows']]
    assert native['artifact']['sha256'] == sha256(await read(native['artifact'])).hexdigest()


@pytest.mark.parametrize('accent,expected', [('#FFFFFF', '000000'), ('#E5F4D8', '000000'),
    ('#FFD966', '000000'), ('#174A66', 'FFFFFF')])
def test_native_table_header_keeps_readable_contrast_for_light_and_dark_themes(tmp_path, accent, expected):
    from smart_reporting.management.preference_preflight_readback import readback

    source = table_input(rows=2)
    resolved = preferences()
    resolved['common']['accentColor'] = accent
    slides = ({'title': '主题色表头核验', 'bullets': [], 'tables': [source]},)
    output = tmp_path / 'theme-table.pptx'
    build_editable_pptx(output_path=output, title='可读性验证', period='2025年', theme='executive',
        slides=slides, preferences=resolved, generated_date='2026-11-13')
    deck = Presentation(output)
    native = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert native
    for table in native:
        for cell in table.rows[0].cells:
            assert cell._tc.xpath('./a:tcPr/a:solidFill/a:srgbClr/@val') == [accent[1:]]
            for paragraph in cell.text_frame.paragraphs:
                assert paragraph.runs and all(str(run.font.color.rgb) == expected for run in paragraph.runs)
    frozen = {'state': {'_documentContext': {'title': '可读性验证', 'periodLabel': '2025年',
        'generatedDate': '2026-11-13'}}, 'slides': slides}
    actual = readback(output.read_bytes(), 'pptx', resolved, frozen)
    assert all(check['passed'] for check in actual['checks'] if check['path'] == 'pptx.typography.table.color')
