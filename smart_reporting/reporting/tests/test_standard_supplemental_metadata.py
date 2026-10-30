"""服务端补证登记准确单位与真实 JSON 位置。"""
import json

import pytest

from smart_reporting.reporting.tests.test_standard_supplemental import CSV, request
from smart_reporting.reporting.trace.computation_service import (
    build_standard_supplemental_computation_record,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    run_standard_supplemental,
)


def test_standard_finding_carries_verified_metric_identity_and_explicit_row_keys():
    req = StandardSupplementalRequest.model_validate({
        **request().model_dump(by_alias=True), 'metricCodes': ['cost_total']})
    payload = run_standard_supplemental(analysis_id='analysis_001',
        dataset_ids=('dataset-current',), authorized_fields=('period', 'department', 'amount'),
        csv_content=CSV, request=req)
    finding = payload['findings'][0]
    assert finding['metricCodes'] == ['cost_total']
    assert finding['rowKeyColumns'] == ['department']
    validated = validate_supplemental_evidence(json.dumps(payload).encode(), {
        'analysisId': 'analysis_001', 'datasetIds': ['dataset-current'],
        'allowedMetricCodes': ['cost_total'],
    })
    assert not validated.findings[0].get('metricScopeRejected')


def test_standard_finding_metadata_preserves_fraction_scale_and_frozen_measure_unit():
    req = request().model_copy(update={'measure_unit': '元'})
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset-current',),
        authorized_fields=('period', 'department', 'amount'), csv_content=CSV, request=req,
    )
    finding = payload['findings'][0]
    assert finding['columnMeta'] == {
        'value': {'unit': '元', 'measureSemantic': {
            'aggregation': 'sum', 'additiveAcross': ['department']}}, 'rank': {'unit': '名'},
        'share': {'unit': '%', 'isPercent': False},
    }
    assert finding['rows'][0][-1] == 0.65
    validated = validate_supplemental_evidence(json.dumps(payload).encode(),
        {'analysisId': 'analysis_001', 'datasetIds': ['dataset-current']})
    assert validated.findings[0]['columnMeta'] == finding['columnMeta']


def test_standard_output_references_resolve_real_finding_rows():
    record = build_standard_supplemental_computation_record(
        analysis_id='analysis_001', dataset_ids=('dataset-current',), input_files=(),
        evidence_file={'path': 'evidence.json', 'size': 10, 'sha256': 'a' * 64},
        method='supplemental_standard_group_summary', method_version='standard-supplemental-v1',
        parameters={}, execution_id='standard-1', finding_count=2,
    )
    document = {'findings': [{'rows': [['A', 10], ['B', 20]]}]}
    for index, ref in enumerate(record.output_fact_refs):
        node = document
        for key in ref.json_pointer.strip('/').split('/'):
            node = node[int(key)] if isinstance(node, list) else node[key]
        assert node == document['findings'][0]['rows'][index]


@pytest.mark.parametrize('unit', [None, '万元'])
def test_comparison_metadata_does_not_invent_measure_unit_or_change_ratio_scale(unit):
    req = request('period_comparison').model_copy(update={'measure_unit': unit})
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset-current',),
        authorized_fields=('period', 'department', 'amount'), csv_content=CSV, request=req,
    )
    finding = payload['findings'][0]
    expected = {'changeRate': {'unit': '%', 'isPercent': False},
                'contribution': {'unit': '%', 'isPercent': False}}
    if unit is not None:
        expected.update({column: {'unit': unit} for column in ('current', 'baseline', 'change')})
    for column in ('current', 'baseline', 'change', 'changeRate', 'contribution'):
        periods = req.current_periods if column == 'current' else req.baseline_periods if column == 'baseline' else (*req.current_periods, *req.baseline_periods)
        expected.setdefault(column, {})['periods'] = list(periods)
    expected['current']['periodRoles'] = ['current']
    expected['baseline']['periodRoles'] = ['prior']
    assert finding['columnMeta'] == expected
    assert finding['rows'][0][4] == 1.6
    validated = validate_supplemental_evidence(json.dumps(payload).encode(),
        {'analysisId': 'analysis_001', 'datasetIds': ['dataset-current']})
    assert validated.findings[0]['columnMeta'] == expected


def test_comparison_periods_survive_catalog_binding_and_source_cell_replay():
    from smart_reporting.reporting.trace.contracts_v1 import TableDerivationV1, TableOperandV1
    from smart_reporting.reporting.trace.semantic_quantity import build_quantity_catalog
    from smart_reporting.reporting.trace.table_sources import (
        resolve_source_cell,
        resolve_table_derivation,
        table_derivation_token,
    )

    req = request('period_comparison').model_copy(update={
        'measure_unit': '元', 'period_granularity': 'month',
        'current_periods': ('2025-01',), 'baseline_periods': ('2024-01',), 'parent_total': 100,
    })
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset-current',),
        authorized_fields=('period', 'department', 'amount'), csv_content=CSV, request=req,
    )
    raw = json.dumps(payload, ensure_ascii=False).encode()
    resource = 'trf-' + '1' * 20
    catalog = build_quantity_catalog([raw.decode()], {resource: raw})
    expected = {'current': ('2025-01',), 'baseline': ('2024-01',),
                'change': ('2025-01', '2024-01')}
    for name, periods in expected.items():
        descriptor = next(item for item in catalog.prompt if item.get('column') == name)
        assert descriptor['periods'] == list(periods)
        binding = catalog.resolve({'operation': 'value', 'left': [descriptor['sourceId']],
            'rowLabel': '内科', 'evidence': ['内科收入']}, '内科收入', display_unit='元')
        assert binding is not None and binding.view['periods'] == periods
        column = payload['findings'][0]['columns'].index(name)
        cell = resolve_source_cell(TableOperandV1(fileResourceId=resource, tablePointer='/findings/0',
            rowIndex=0, columnIndex=column, coefficient='1'), {resource: raw})
        assert cell['periods'] == periods
    assert payload['findings'][0]['columnMeta']['changeRate']['periods'] == list(expected['change'])
    assert payload['findings'][0]['columnMeta']['contribution']['periods'] == list(expected['change'])
    difference = TableDerivationV1(unit='元', operands=tuple(
        TableOperandV1(fileResourceId=resource, tablePointer='/findings/0',
                       rowIndex=0, columnIndex=column, coefficient=coefficient)
        for column, coefficient in ((1, '1'), (2, '-1'))
    ))
    token = table_derivation_token(difference, {resource: raw})
    view = resolve_table_derivation(token, difference, {resource: raw})
    assert view['value'] == 10
    assert view['periods'] == expected['change']
    assert view['period_roles'] == {'current': expected['current'], 'prior': expected['baseline']}


def test_group_ratio_operands_keep_units_periods_and_replayable_difference():
    from smart_reporting.reporting.trace.contracts_v1 import TableDerivationV1, TableOperandV1
    from smart_reporting.reporting.trace.semantic_quantity import build_quantity_catalog
    from smart_reporting.reporting.trace.table_sources import (
        resolve_table_derivation,
        table_derivation_token,
    )

    request = StandardSupplementalRequest(
        operation='group_ratio', datasetId='dataset-current', outputName='completion',
        measureField='actual', denominatorField='budget', measureUnit='元',
        dimensionField='department', periodField='period', periodGranularity='month',
        currentPeriods=('2025-01',), parentTotal=80, denominatorParentTotal=10,
        denominatorScale=10, ratioFactId='fact-ratio',
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset-current',),
        authorized_fields=('period', 'department', 'actual', 'budget'),
        csv_content=b'period,department,actual,budget\n2025-01,A,80,10\n', request=request,
    )
    raw = json.dumps(payload, ensure_ascii=False).encode()
    resource = 'trf-' + '2' * 20
    catalog = build_quantity_catalog([raw.decode()], {resource: raw})
    descriptors = {item['column']: item for item in catalog.prompt}
    assert descriptors['numerator']['unit'] == '元'
    assert descriptors['denominator']['unit'] == '元'
    assert payload['findings'][0]['columnMeta']['ratio'] == {'unit': '%', 'isPercent': False}
    assert descriptors['difference']['periods'] == ['2025-01']
    derivation = TableDerivationV1(unit='元', operands=(
        TableOperandV1(fileResourceId=resource, tablePointer='/findings/0',
                       rowIndex=0, columnIndex=1, coefficient='1'),
        TableOperandV1(fileResourceId=resource, tablePointer='/findings/0',
                       rowIndex=0, columnIndex=2, coefficient='-1'),
    ))
    view = resolve_table_derivation(
        table_derivation_token(derivation, {resource: raw}), derivation, {resource: raw},
    )
    assert view['value'] == -20
    assert view['periods'] == ('2025-01',)
