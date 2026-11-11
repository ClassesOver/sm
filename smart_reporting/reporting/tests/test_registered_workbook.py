"""工作簿使用正式计算身份与精确值，不以旧事实数组或正文回填。"""

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_registered_chart_projection import registered_document
from smart_reporting.reporting.workflow.runtime.workbook import build_workbook_sheets


def workbook(document):
    manifest = SimpleNamespace(evidence=(SimpleNamespace(analysis_id='analysis_001',
        summary='测试结论，不能从此文本反推数字', dataset_ids=('dataset-formal',)),), metric_definitions=())
    outline = SimpleNamespace(sections=(SimpleNamespace(code='budget', title='预算', analysis_ids=('analysis_001',)),))
    return build_workbook_sheets(manifest=manifest, outline=outline,
        fact_documents={'analysis_001': document}, datasets={'dataset-formal': {
            'columns': ['value'], 'rows': [['300.123456789123456789']], 'path': 'data.csv', 'sha256': 'a' * 64}},
        period='不得代替事实期间')


@pytest.mark.parametrize('value,expected', [('300.123456789123456789', '300.123456789123456789'),
    ('0', 0), ('12.5', 12.5), ('1e999', '1E+999'), ('1e-999', '1E-999'), (None, None)])
def test_workbook_registered_values_keep_precision_null_identity_and_period(value, expected):
    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    result.update(value=value)
    if value is None:
        result.update(status='unavailable', issueCodes=['missing_data'])
    original = deepcopy(document)
    sheets, sources = workbook(document)
    row = sheets[1]['rows'][1]
    assert row[2] == expected and row[3] == 'CNY'
    assert row[6] == result['factId'] and row[5] == 'dataset-formal'
    assert '[2026-11-01, 2026-12-01)' in row[4]
    source, = sources['cells']
    assert source['jsonPointer'] == '/metricContext/calculations/0/results/0'
    assert source['basisId'] == result['basisId'] and source['metricVersion'] == result['metricVersion']
    assert source['calculationId'] == result['calculationId']
    assert source['status'] == result['status'] and set(result['issueCodes']) <= set(source['issueCodes'])
    assert source['exactValue'] == (None if value is None else str(Decimal(value)))
    if isinstance(expected, str):
        assert 'xlsx_numeric_precision_preserved' in source['issueCodes']
        assert sheets[0]['rows'][1][3] == expected  # 文本不使用数值引用公式，避免重算成0。
        assert '保留精确文本' in row[8]
    elif expected is None:
        assert sheets[0]['rows'][1][3] is None
        assert row[7] == '不可计算' and '未取得对应范围的数据' in row[8] and '未补零' in row[8]
    else:
        assert sheets[0]['rows'][1][3]['value'] == expected
    assert document == original


@pytest.mark.parametrize('fault', ['basis', 'batch', 'unit', 'dataset', 'version', 'dimension', 'duplicate',
    'legacy', 'missing_context'])
def test_workbook_never_borrows_foreign_or_legacy_results(fault):
    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    if fault == 'basis':
        result['basisId'] = 'foreign'
    elif fault == 'batch':
        result['calculationId'] = 'foreign'
    elif fault == 'unit':
        result['unit'] = 'USD'
    elif fault == 'dataset':
        result['datasetIds'].append('foreign')
    elif fault == 'version':
        result['metricVersion']['revision'] = 2
    elif fault == 'dimension':
        result['dimensions'] = [{'dimensionId': 'unexpected', 'value': 'A'}]
    elif fault == 'duplicate':
        document['metricContext']['calculations'][0]['results'].append(deepcopy(result))
    elif fault == 'missing_context':
        document['metricContext'] = None
    else:
        document['metrics'] = [{'factId': 'legacy', 'total': 999, 'unit': 'CNY'}]
        sheets, _ = workbook(document)
        assert all(999 not in row for sheet in sheets for row in sheet['rows'])
        return
    with pytest.raises(ReportingError):
        workbook(document)


def test_registered_workbook_percentage_is_already_percent_points():
    document = registered_document()
    context = document['metricContext']
    result = context['calculations'][0]['results'][0]
    result.update(value='12.5', unit='%')
    for definition in context['metrics']:
        if definition['id'] == result['metricVersion']['metricId']:
            definition['unit'] = '%'
    sheets, _ = workbook(document)
    assert sheets[1]['rows'][1][2:4] == [12.5, '%']


def test_unavailable_registered_workbook_does_not_invent_dataset_membership():
    document = registered_document()
    document['metricContext']['calculations'][0]['results'][0].update(
        value=None, status='unavailable', issueCodes=['missing_data'], datasetIds=[])
    sheets, sources = workbook(document)
    assert sheets[1]['rows'][1][2] is None
    assert sources['cells'][0]['datasetIds'] == []


def test_registered_workbook_real_engine_preserves_exact_text_null_formulas_and_sources(tmp_path):
    import json
    from io import BytesIO
    from zipfile import ZipFile

    from openpyxl import load_workbook

    from smart_reporting.reporting.delivery.xlsx import build_workbook, inspect_workbook
    from smart_reporting.reporting.workflow.runtime.workbook import validate_workbook_snapshot

    document = registered_document()
    calculation = document['metricContext']['calculations'][0]
    original = deepcopy(calculation['results'][0])
    calculation['results'] = []
    for index, value in enumerate(['300.123456789123456789', '0', '12.5', None]):
        result = deepcopy(original)
        result.update(factId=f'fact-{index}', value=value, dimensions=[{'dimensionId': 'project', 'value': str(index)}])
        if value is None:
            result.update(status='unavailable', issueCodes=['missing_data'])
        calculation['results'].append(result)
    calculation['request']['dimensions'] = ['project']
    sheets, sources = workbook(document)
    path = tmp_path / 'registered-results.xlsx'
    build_workbook(output_path=path, title='正式计算输出', period='2026-11', sheets=sheets, source_mapping=sources)
    content = path.read_bytes()
    model = inspect_workbook(content)
    assert validate_workbook_snapshot(model, sheets, sources, content) == []
    with ZipFile(BytesIO(content)) as package:
        assert json.loads(package.read('smart-reporting/source-mapping.json'))['sources'] == sources
    book = load_workbook(BytesIO(content), data_only=True)
    assert book['预算']['C2'].value == '300.123456789123456789'
    assert book['预算']['C2'].data_type == 's'
    assert book['汇总']['D2'].value == '300.123456789123456789'
    assert book['汇总']['D3'].value == 0
    assert book['汇总']['D4'].value == 12.5
    assert book['汇总']['D5'].value is None
    book.close()
