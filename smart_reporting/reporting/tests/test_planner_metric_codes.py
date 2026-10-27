"""业务代码只按受信的同表字段映射修复，不猜测相似列名。"""

import pytest

from smart_reporting.reporting.contract import (
    MeasureSemantic,
    ModelColumn,
    ModelTable,
    SourceSchemaSnapshot,
)
from smart_reporting.reporting.profile.models import EffectiveMetric
from smart_reporting.reporting.workflow.runtime import validation
from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle


def inputs(*, code='budget_income', field_ref='s.db.budget.budget_medical_income', approved=True):
    bundle = AnalysisBundle.model_validate({
        'analyses': [{'code': 'budget', 'description': '核实预算口径后分析执行率',
            'managementQuestion': '预算执行情况如何？', 'primaryMetricFamily': '预算',
            'requirementIds': ['r']}],
        'requirements': [{'requirementId': 'r', 'sourceId': 's',
            'tables': [{'table': 'db.budget', 'periodColumn': 'month',
                        'periodGranularity': 'month', 'measureColumns': [code]}],
            'dimensionColumns': ['month'], 'grainColumns': ['month'], 'relations': []}]})
    snapshot = SourceSchemaSnapshot(source='metadata_api', revision='1', schemaHash='a' * 64,
        tables=(ModelTable(sourceId='s', database='db', name='budget', columns=(
            ModelColumn(name='month', dataType='VARCHAR', nullable=False),
            ModelColumn(name='budget_medical_income', dataType='DOUBLE', nullable=False),
        )),), measureSemantics=((MeasureSemantic(
            fieldRef='s.db.budget.budget_medical_income', aggregation='sum'),) if approved else ()))
    metric = EffectiveMetric(code='budget_income', kind='currency', aggregation='sum', fieldRef=field_ref)
    return bundle, (snapshot,), (metric,)


def test_exact_metric_code_is_repaired_to_approved_physical_column():
    bundle, snapshots, metrics = inputs()
    normalized, repairs = validation._normalize_requirement_metric_codes(bundle, snapshots, metrics)
    assert normalized.requirements[0].tables[0].measure_columns == ('budget_medical_income',)
    assert bundle.requirements[0].tables[0].measure_columns == ('budget_income',)
    assert normalized.analyses == bundle.analyses
    assert repairs[0]['replacements'] == {'budget_income': 'budget_medical_income'}


@pytest.mark.parametrize('field_ref', ['other.db.budget.budget_medical_income',
                                      's.db.other.budget_medical_income'])
def test_mapping_must_belong_to_same_source_and_table(field_ref):
    bundle, snapshots, metrics = inputs(field_ref=field_ref)
    assert validation._normalize_requirement_metric_codes(bundle, snapshots, metrics) == (bundle, [])


def test_unapproved_mapping_is_left_for_existing_validation():
    bundle, snapshots, metrics = inputs(approved=False)
    assert validation._normalize_requirement_metric_codes(bundle, snapshots, metrics) == (bundle, [])


def test_physical_column_and_unknown_code_are_not_reinterpreted():
    for code in ('budget_medical_income', 'budget_incom'):
        bundle, snapshots, metrics = inputs(code=code)
        assert validation._normalize_requirement_metric_codes(bundle, snapshots, metrics) == (bundle, [])


def test_duplicate_code_is_not_resolved_by_order():
    bundle, snapshots, metrics = inputs()
    conflicting = metrics[0].model_copy(update={'field_ref': 's.db.other.amount'})
    for candidates in ((metrics[0], conflicting), (conflicting, metrics[0])):
        assert validation._normalize_requirement_metric_codes(bundle, snapshots, candidates) == (bundle, [])


def test_existing_physical_column_wins_over_profile_code():
    bundle, snapshots, metrics = inputs()
    table = snapshots[0].tables[0]
    table = table.model_copy(update={'columns': (*table.columns, ModelColumn(
        name='budget_income', dataType='DOUBLE', nullable=False))})
    snapshot = snapshots[0].model_copy(update={'tables': (table,)})
    assert validation._normalize_requirement_metric_codes(bundle, (snapshot,), metrics) == (bundle, [])


def test_repaired_code_and_physical_column_are_deduplicated():
    bundle, snapshots, metrics = inputs()
    payload = bundle.model_dump(mode='json', by_alias=True)
    payload['requirements'][0]['tables'][0]['measureColumns'].append('budget_medical_income')
    normalized = validation._normalize_requirement_columns_in_payload(payload, snapshots, metrics)
    assert normalized['requirements'][0]['tables'][0]['measureColumns'] == ['budget_medical_income']
    assert payload['requirements'][0]['tables'][0]['measureColumns'] == [
        'budget_income', 'budget_medical_income',
    ]
