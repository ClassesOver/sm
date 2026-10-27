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
    run_standard_supplemental,
)


def test_standard_finding_metadata_preserves_fraction_scale_and_frozen_measure_unit():
    req = request().model_copy(update={'measure_unit': '元'})
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset-current',),
        authorized_fields=('period', 'department', 'amount'), csv_content=CSV, request=req,
    )
    finding = payload['findings'][0]
    assert finding['columnMeta'] == {
        'value': {'unit': '元'}, 'rank': {'unit': '名'},
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
    assert finding['columnMeta'] == expected
    assert finding['rows'][0][4] == 1.6
    validated = validate_supplemental_evidence(json.dumps(payload).encode(),
        {'analysisId': 'analysis_001', 'datasetIds': ['dataset-current']})
    assert validated.findings[0]['columnMeta'] == expected
