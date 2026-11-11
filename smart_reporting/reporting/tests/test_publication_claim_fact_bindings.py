"""发布核对事实身份，不把未绑定选择器的计划 claim 当成事实合计。"""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin


@pytest.mark.anyio
@pytest.mark.parametrize(('entry', 'value'), [
    ({'baselineTotal': 10475201732, 'change': 648339771}, 10475201732),
    ({'total': 11123541503}, 1011231045.73),
    ({'total': 11123541503,
      'periodValues': [{'period': '2025-11', 'value': 537347472}]}, 537347472),
])
async def test_legacy_claim_without_selector_is_not_compared_to_arbitrary_fact_field(entry, value):
    runtime = object.__new__(RuntimePublicationMixin)
    runtime._read_identity_bytes = AsyncMock(return_value=json.dumps({
        'metrics': [{'factId': 'fact-aaaaaaaaaaaaaaaa', **entry}],
    }).encode())
    checkpoint = SimpleNamespace(deterministic_fact_files={'analysis_001': object()})
    artifact = SimpleNamespace(section_code='section_001', claims=[SimpleNamespace(
        claim_id='claim_001', fact_ids=('fact-aaaaaaaaaaaaaaaa',), value=value,
    )])

    issues, warnings = await runtime._verify_claim_fact_bindings('thread', checkpoint, (artifact,))

    assert issues == []
    assert warnings == []


@pytest.mark.anyio
async def test_unknown_fact_still_reports_identity_issue():
    runtime = object.__new__(RuntimePublicationMixin)
    runtime._read_identity_bytes = AsyncMock(return_value=b'{"metrics": []}')
    checkpoint = SimpleNamespace(deterministic_fact_files={'analysis_001': object()})
    artifact = SimpleNamespace(section_code='section_001', claims=[SimpleNamespace(
        claim_id='claim_001', fact_ids=('fact-aaaaaaaaaaaaaaaa',), value=30,
    )])

    issues, warnings = await runtime._verify_claim_fact_bindings('thread', checkpoint, (artifact,))

    assert [issue['code'] for issue in issues] == ['report_claim_fact_unknown']
    assert warnings == []


@pytest.mark.anyio
async def test_registered_metric_result_is_known_to_publication_gate():
    from smart_reporting.reporting.tests.test_registered_chart_projection import registered_document

    document = registered_document()
    result = document['metricContext']['calculations'][0]['results'][0]
    runtime = object.__new__(RuntimePublicationMixin)
    runtime._read_identity_bytes = AsyncMock(return_value=json.dumps(document).encode())
    checkpoint = SimpleNamespace(deterministic_fact_files={'analysis_001': object()})
    artifact = SimpleNamespace(section_code='section_001', claims=[SimpleNamespace(
        claim_id='claim_001', fact_ids=(result['factId'],), value=result['value'],
    )])

    issues, warnings = await runtime._verify_claim_fact_bindings('thread', checkpoint, (artifact,))

    assert issues == [] and warnings == []


@pytest.mark.anyio
@pytest.mark.parametrize('mutation', [
    'basis', 'calculation', 'unit', 'duplicate', 'structure', 'noncanonical_alias', 'partial_noncanonical',
])
async def test_invalid_registered_result_is_disclosed_without_becoming_a_known_fact(mutation):
    from smart_reporting.reporting.tests.test_registered_chart_projection import registered_document

    document = registered_document()
    calculation = document['metricContext']['calculations'][0]
    result = calculation['results'][0]
    fact_id = result['factId']
    if mutation == 'basis':
        result['basisId'] = 'foreign-basis'
    elif mutation == 'calculation':
        result['calculationId'] = 'foreign-calculation'
    elif mutation == 'unit':
        result['unit'] = '%'
    elif mutation == 'duplicate':
        calculation['results'].append(dict(result))
    elif mutation == 'noncanonical_alias':
        result['fact_id'] = result.pop('factId')
    elif mutation == 'partial_noncanonical':
        extra = {key: value for key, value in result.items() if key != 'factId'}
        calculation['results'].append({**extra, 'fact_id': 'fact-second'})
    else:
        document['metricContext'] = {'calculations': [{'results': [result]}]}
    runtime = object.__new__(RuntimePublicationMixin)
    runtime._read_identity_bytes = AsyncMock(return_value=json.dumps(document).encode())
    checkpoint = SimpleNamespace(deterministic_fact_files={'analysis_001': object()})
    artifact = SimpleNamespace(section_code='section_001', claims=[SimpleNamespace(
        claim_id='claim_001', fact_ids=(fact_id,), value=30,
    )])

    issues, warnings = await runtime._verify_claim_fact_bindings('thread', checkpoint, (artifact,))

    assert [item['code'] for item in issues] == ['report_claim_fact_file_unreadable', 'report_claim_fact_unknown']
    assert warnings == []
