"""冻结表格必须绑定耐久事实；回读覆盖所有页、行和单元格。"""
import hashlib
import json
from copy import deepcopy
from io import BytesIO

import pytest
from pptx import Presentation

from smart_reporting.management.preference_preflight_readback import readback
from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.delivery.pptx_tables import project_fact_slide_tables
from smart_reporting.reporting.tests.test_pptx_native_tables import preferences, table_input
from smart_reporting.reporting.tests.test_trace_table_builder import _bundle
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.tests.test_preference_report_preflight import native_case


@pytest.mark.anyio
@pytest.mark.parametrize('fault', [None, 'unregistered', 'projection', 'analysis', 'changed_bytes'])
async def test_pptx_tables_require_registered_fact_projection(tmp_path, monkeypatch, fault):
    from smart_reporting.management import preference_report_preflight as module

    service, args, repository, context, root, spec, _, _ = await native_case(tmp_path, 'pptx')
    raw = _bundle().model_dump_json(by_alias=True).encode()
    source = FileIdentity(path='facts.json', size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    (root / source.path).write_bytes(raw if fault != 'changed_bytes' else raw + b' ')
    tables = project_fact_slide_tables('analysis_001', source, raw)
    if fault == 'projection':
        tables[0]['rows'][-1][-1] = '伪造展示值'
    elif fault == 'analysis':
        tables[0]['sourceAnalysisId'] = 'analysis_999'
    spec['slides'] = [{**spec['slides'][0], 'tables': tables}]
    def saved(path, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        (root / path).write_bytes(data)
        return {'path': path, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    job = deepcopy(context.job)
    pointer = job['pptxNativeInput']
    pointer['spec'] = saved('native-spec.json', spec)
    pointer['receipt'] = saved('report.pptx.receipt.json', {'schemaVersion': 'pptx-native-receipt/1',
        'binding': pointer['binding'], 'artifact': pointer['artifact'], 'spec': pointer['spec']})
    changed = context.model_copy(update={'job': job})
    repository.state.payload['reportEditorContexts']['1'] = changed.model_dump(mode='json', by_alias=True)
    repository.state.payload['workflowCheckpoint'] = {'deterministicFactFiles': {'analysis_001': source.model_dump()}}
    repository.state.payload['artifacts'] = [pointer['artifact'], pointer['spec'], pointer['receipt']]
    if fault != 'unregistered':
        repository.state.payload['artifacts'].append(source.model_dump())
    grant, _ = await service.grants.issue(changed)
    args['editor_session'], _ = await service.grants.exchange(grant)
    args['expected_context_hash'] = changed.digest()
    calls = []
    async def generated(function, draft, materials, **kwargs):
        calls.append(True)
        assert materials.slides[0]['tables'] == tables
        assert (materials.workspace / source.path).read_bytes() == raw
        assert source.model_dump() in materials.state['sources']
        return {'status': 'incomplete', 'canApply': False, 'formats': {'pptx': {'artifact': {'size': 7}}}}
    monkeypatch.setattr(module, 'run_office_engine', generated)
    result = await service.run(**args)
    if fault:
        assert not calls
        assert result['formats']['pptx']['availability'] == 'unavailable'
        assert (root / 'report.pptx').read_bytes() == b'published-native-artifact'
    else:
        assert calls == [True]
        assert source.model_dump() in result['binding']['identities']


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('repeat,borders', [(True, 'all'), (False, 'light'), (False, 'none')])
def test_pptx_readback_covers_all_table_rows_cells_and_styles(tmp_path, repeat, borders):
    source = table_input(rows=24)
    resolved = preferences(repeatHeader=repeat, borders=borders, striped=True)
    path = tmp_path / 'complete.pptx'
    slides = ({'title': '冻结表格', 'bullets': [], 'tables': [source]},)
    build_editable_pptx(output_path=path, title='验收表格', period='2025年', theme='executive',
        slides=slides, preferences=resolved, generated_date='2026-11-13')
    frozen = {'state': {'_documentContext': {'title': '验收表格', 'periodLabel': '2025年',
        'generatedDate': '2026-11-13'}}, 'slides': slides}
    first = readback(path.read_bytes(), 'pptx', resolved, frozen)
    table_checks = [item for item in first['checks'] if item['path'] and '.tables.' in item['path']]
    assert table_checks and all(item['passed'] and item['coverage'] == 'complete' for item in table_checks)
    assert all(item['passed'] for item in first['checks'] if item['path'] and '.typography.table.' in item['path'])
    deck = Presentation(path)
    tables = [shape.table for slide in deck.slides for shape in slide.shapes if shape.has_table]
    tables[-1].cell(len(tables[-1].rows) - 1, 1).text = '篡改末页末单元格'
    changed = BytesIO()
    deck.save(changed)
    second = readback(changed.getvalue(), 'pptx', resolved, frozen)
    assert any(item['path'] == 'pptx.tables.content' and not item['passed'] for item in second['checks'])


def test_pptx_readback_reconstructs_wide_multiline_and_rejects_missing_table_or_style(tmp_path):
    source = table_input(rows=2)
    source['headers'] = ['期间', *[f'列{index}' for index in range(8)]]
    source['rows'] = [[f'期间{index}', *[f'{index}.{column:04}\n原样说明' for column in range(8)]]
        for index in range(2)]
    resolved = preferences(repeatHeader=True, borders='light', striped=False, captionNumbering=False)
    resolved['aspectRatio'] = '4:3'
    path = tmp_path / 'wide-multiline.pptx'
    slides = ({'title': '冻结宽表', 'bullets': [], 'tables': [source]},)
    build_editable_pptx(output_path=path, title='宽表回读', period='2025年', theme='executive',
        slides=slides, preferences=resolved, generated_date='2026-11-13')
    frozen = {'state': {'_documentContext': {'title': '宽表回读', 'periodLabel': '2025年',
        'generatedDate': '2026-11-13'}}, 'slides': slides}
    def checks(deck):
        raw = BytesIO()
        deck.save(raw)
        return readback(raw.getvalue(), 'pptx', resolved, frozen)['checks']
    deck = Presentation(path)
    assert all(item['passed'] for item in checks(deck))
    shapes = [shape for slide in deck.slides for shape in slide.shapes if shape.has_table]
    assert len(shapes) == 2
    properties = shapes[-1]._element.xpath('.//p:cNvPr')[0]
    properties.set('hidden', '1')
    assert any(item['path'] == 'pptx.tables.visibility' and not item['passed'] for item in checks(deck))
    properties.attrib.pop('hidden')
    from pptx.dml.color import RGBColor
    shapes[-1].table.cell(2, 1).text_frame.paragraphs[-1].runs[0].font.color.rgb = RGBColor(255, 0, 0)
    assert any(item['path'] == 'pptx.typography.table.color' and not item['passed'] for item in checks(deck))
    shape = shapes[-1]._element
    shape.getparent().remove(shape)
    assert any(item['path'] == 'pptx.tables.content' and not item['passed'] for item in checks(deck))
