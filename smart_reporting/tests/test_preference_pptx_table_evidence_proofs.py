"""真实原生宽表/续页与后部对象负例；不产生视觉或生命周期V。"""

import json
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pptx import Presentation
from pptx.dml.color import RGBColor

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.preferences.approval_contract import evaluate_required_coverage
from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.tests.test_pptx_native_tables import preferences, table_input
from smart_reporting.tests.test_preference_pptx_table_evidence import (
    FIELDS,
    GUARDS,
    MARKER,
    mapped,
    material,
)


@pytest.fixture(scope='module')
def native_tables(tmp_path_factory):
    source = table_input(rows=10)
    source['headers'] = ['期间', *[f'字段{index}' for index in range(8)]]
    source['rows'] = [[f'期间{row}', *[f'{row}.{column:04}\n原样说明' if row or column else ''
        for column in range(8)]] for row in range(10)]
    second = table_input(rows=3)
    second.update(tableId='second-table', caption='第二张冻结表')
    resolved = preferences(repeatHeader=False, borders='light', striped=True, captionNumbering=True)
    resolved['common']['accentColor'] = '#F2D487'
    resolved['typography']['table'].update(bold=False, color='#123456', spaceBefore=2, spaceAfter=3)
    slides = ({'title': '冻结宽表', 'bullets': [], 'tables': [source, second]},)
    path = tmp_path_factory.mktemp('pptx-table-evidence') / 'wide.pptx'
    build_editable_pptx(output_path=path, title='全部表格字段核对', period='2026年', theme='executive',
        slides=slides, preferences=resolved, generated_date='2026-11-13')
    frozen = {'state': {'_documentContext': {'title': '全部表格字段核对', 'periodLabel': '2026年',
        'generatedDate': '2026-11-13'}}, 'slides': slides}
    return SimpleNamespace(content=path.read_bytes(), resolved=resolved, frozen=frozen)


def evidence(case, content):
    actual = readback(content, 'pptx', case.resolved, case.frozen)
    inputs = material()
    inputs[0]['formats']['pptx']['readback'] = actual
    identity = {'size': len(content), 'sha256': sha256(content).hexdigest()}
    inputs[0]['formats']['pptx']['artifact'].update(identity)
    inputs[3]['formats']['pptx']['artifact'].update(identity)
    return actual, mapped(inputs), inputs


def save(label, content, actual, rows):
    root = Path('output/system-config-preferences/pptx-table-field-evidence')
    root.mkdir(parents=True, exist_ok=True)
    filename = label + '.pptx'
    (root / filename).write_bytes(content)
    group = [item for item in actual['checks'] if item.get('evidenceKind') == MARKER]
    (root / (label + '-proof.json')).write_text(json.dumps({'file': filename,
        'size': len(content), 'sha256': sha256(content).hexdigest(),
        'realGenerator': True, 'realReader': True, 'binding': 'fixture', 'retention': 'fixture_same_identity_not_sql',
        'objectWitness': [item for item in group if item['path'] == 'pptx.tables.objectCoverage'],
        'guardSummary': {path: {'checked': sum(item['path'] == 'pptx.' + path for item in group),
            'failed': sum(item['path'] == 'pptx.' + path and not item['passed'] for item in group)} for path in GUARDS},
        'failedChecks': [item for item in group if not item['passed']], 'evidence': rows}, ensure_ascii=False, indent=2))


@pytest.mark.parametrize('fault', ['valid', 'last_cell_color', 'missing_last_table', 'extra_table', 'hidden', 'bounds'])
def test_real_all_table_fields_and_late_native_object_faults(native_tables, fault):
    case = native_tables
    deck = Presentation(BytesIO(case.content))
    shapes = [(slide, shape) for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert len(shapes) > 2, '输入必须确实展开宽表列分组及续页，不用单表代替完整性负例'
    slide, last = shapes[-1]
    if fault == 'last_cell_color':
        cell = last.table.cell(len(last.table.rows) - 1, len(last.table.columns) - 1)
        cell.text_frame.paragraphs[-1].runs[-1].font.color.rgb = RGBColor(254, 1, 2)
    elif fault == 'missing_last_table':
        last._element.getparent().remove(last._element)
    elif fault == 'extra_table':
        slide.shapes._spTree.insert_element_before(deepcopy(last._element), 'p:extLst')
    elif fault == 'hidden':
        last._element.xpath('.//p:cNvPr')[0].set('hidden', '1')
    elif fault == 'bounds':
        last.left = -1000
    output = BytesIO()
    deck.save(output)
    content = case.content if fault == 'valid' else output.getvalue()
    actual, rows, inputs = evidence(case, content)
    save(fault, content, actual, rows)
    assert len(rows) == 11
    assert {row['path'] for row in rows} == {'pptx.' + path for path in FIELDS}
    failed = {row['path'] for row in rows if row['status'] == 'failed'}
    assert failed == ({'pptx.typography.table.color'} if fault == 'last_cell_color' else
        {'pptx.' + path for path in FIELDS} if fault != 'valid' else set())
    assert all(row['scenario'] == 'configured_field' and row['dimension'] == 'native' for row in rows)
    gaps = evaluate_required_coverage({**inputs[1], 'expectedBinding': inputs[2]}, rows)
    assert gaps and any('visual' in gap['missingDimensions'] for gap in gaps)
    if fault == 'valid':
        witnesses = [item for item in actual['checks'] if item['path'] == 'pptx.tables.objectCoverage']
        assert len(witnesses) == 1
        objects = witnesses[0]['evidenceObjects']
        assert objects['sourceTables'] == 2 and objects['nativeTables'] > 2
        assert objects['checkedNativeTables'] == objects['nativeTables'] and objects['bodyRuns'] > 0
        assert not any(gap.get('path') in {row['path'] for row in rows}
            and gap.get('scenario') == 'configured_field' for gap in gaps)


def test_empty_native_body_runs_are_real_objects_but_header_only_styles_cannot_qualify_body_overrides(tmp_path):
    source = table_input(rows=1)
    source['rows'] = [['', '']]
    resolved = preferences(repeatHeader=True, borders='light', striped=True)
    resolved['typography']['table'].update(bold=False, color='#123456', spaceBefore=2, spaceAfter=3)
    slides = ({'title': '空表体角色', 'bullets': [], 'tables': [source]},)
    path = tmp_path / 'empty-body.pptx'
    build_editable_pptx(output_path=path, title='空表体角色', period='2026年', theme='executive',
        slides=slides, preferences=resolved, generated_date='2026-11-13')
    case = SimpleNamespace(resolved=resolved, frozen={'slides': slides, 'state': {'_documentContext': {
        'title': '空表体角色', 'periodLabel': '2026年', 'generatedDate': '2026-11-13'}}})
    content = path.read_bytes()
    actual, rows, _ = evidence(case, content)
    assert len(rows) == 11 and all(row['status'] == 'passed' for row in rows)
    save('empty-body-with-native-runs', content, actual, rows)
    deck = Presentation(BytesIO(content))
    tables = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
    for table in tables:
        for row in list(table.rows)[1:]:
            for cell in row.cells:
                assert cell.text == ''
                for paragraph in cell.text_frame.paragraphs:
                    for run in tuple(paragraph.runs):
                        run._r.getparent().remove(run._r)
    output = BytesIO()
    deck.save(output)
    actual, rows, _ = evidence(case, output.getvalue())
    assert len(rows) == 9 and all(row['status'] == 'passed' for row in rows)
    assert not any(row['path'] in {'pptx.typography.table.color', 'pptx.typography.table.bold'} for row in rows)
    assert all(item['passed'] for item in actual['checks'] if item['path'] == 'pptx.tables.nativeRuns')
    save('empty-body-without-native-runs', output.getvalue(), actual, rows)
