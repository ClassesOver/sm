"""完整总体证明来自冻结CSV完整枚举，不能仅凭总额闭合。"""
import hashlib
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_standard_supplemental import CSV, request
from smart_reporting.reporting.workflow.runtime import standard_supplemental as standard


def _inputs(csv=CSV):
    req = request().model_copy(update={'measure_unit': '元', 'period_granularity': 'month'})
    parent = SimpleNamespace(fact_id='fact-' + 'a' * 16, dataset_id='dataset-current',
        dataset_sha256=hashlib.sha256(csv).hexdigest(), field='amount', period_field='period',
        aggregation='sum', period_aggregation='sum', cumulative_policy=None, scope={}, unit='元',
        period_granularity='month', period_values=[SimpleNamespace(period='2025-01', value=100),
                                                  SimpleNamespace(period='2025-02', value=100)])
    payload = standard.run_standard_supplemental(analysis_id='analysis_001',
        dataset_ids=('dataset-current',), authorized_fields=('period','department','amount'),
        csv_content=csv, request=req)
    return req, parent, payload


def _proof(csv=CSV, mutate=None):
    req, parent, payload = _inputs(csv)
    if mutate:
        mutate(parent, payload)
    return standard.build_standard_population_proof(
        csv_content=csv, dataset_sha256=hashlib.sha256(csv).hexdigest(),
        request=req, parent_fact=parent, finding=payload['findings'][0])


def test_complete_members_are_bound_to_frozen_dataset_parent_and_window():
    proof = _proof()
    assert proof['completePopulation'] is True
    assert proof['members'] == ['内科', '外科']
    assert proof['memberCount'] == 2
    assert proof['datasetSha256'] == hashlib.sha256(CSV).hexdigest()
    assert proof['populationFactId'] == 'fact-' + 'a' * 16
    assert proof['periods'] == ['2025-01', '2025-02']
    assert proof['invalidRowCount'] == 0


@pytest.mark.parametrize('mutate', [
    lambda parent,payload: payload['findings'][0].update(rows=[['伪造',200,1,1.0]]),
    lambda parent,payload: setattr(parent,'dataset_sha256','b'*64),
    lambda parent,payload: setattr(parent,'scope',{'company':'other'}),
    lambda parent,payload: payload['findings'][0].update(scope={'company':'other'}),
    lambda parent,payload: payload['findings'][0].update(periods=['2025-01']),
])
def test_equal_total_or_wrong_identity_is_not_complete_population(mutate):
    assert _proof(mutate=mutate) is None


def test_unparseable_rows_prevent_complete_population_even_if_total_still_closes():
    assert _proof(CSV + '2025-01,遗漏科室,unknown\n'.encode()) is None


@pytest.mark.parametrize('row', ['invalid,A,0\n', '2025-01,,0\n'])
def test_unknown_period_or_member_prevents_complete_population(row):
    assert _proof(CSV + row.encode()) is None


def test_proof_survives_existing_evidence_validation_without_authorizing_model_claims():
    import json

    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        validate_supplemental_evidence,
    )

    _, _, payload = _inputs()
    payload['findings'][0]['populationProof'] = _proof()
    evidence = validate_supplemental_evidence(json.dumps(payload).encode(),
        {'analysisId':'analysis_001','datasetIds':['dataset-current']})
    assert evidence.findings[0]['populationProof'] == _proof()


def test_real_month_start_labels_keep_explicit_month_grain_in_table_and_proof():
    csv = CSV.replace(b'2025-01,', b'2025-01-01,').replace(b'2025-02,', b'2025-02-01,')
    req, parent, _ = _inputs(csv)
    periods = ('2025-01-01', '2025-02-01')
    req = req.model_copy(update={'current_periods': periods})
    parent.period_values = [SimpleNamespace(period=period, value=100) for period in periods]
    payload = standard.run_standard_supplemental(analysis_id='analysis_001',
        dataset_ids=('dataset-current',), authorized_fields=('period','department','amount'),
        csv_content=csv, request=req)
    finding = payload['findings'][0]
    assert finding['periods'] == list(periods)
    assert finding['periodGranularity'] == 'month'
    proof = standard.build_standard_population_proof(csv_content=csv,
        dataset_sha256=hashlib.sha256(csv).hexdigest(), request=req, parent_fact=parent, finding=finding)
    assert proof['periods'] == list(periods)
    assert proof['periodGranularity'] == 'month'


def test_parent_with_wider_window_cannot_authorize_subset_as_total_population():
    assert _proof(mutate=lambda parent,payload: parent.period_values.append(
        SimpleNamespace(period='2025-03', value=0))) is None
