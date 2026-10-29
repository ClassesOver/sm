"""登记比率的逐期分组只复用冻结公式，不平均组内或跨期比率。"""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.tests.test_standard_supplemental_routing import (
    _add_registered_group_ratio,
)
from smart_reporting.reporting.trace.contracts_v1 import TableOperandV1
from smart_reporting.reporting.trace.table_sources import resolve_source_cell
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisItemWorkflow,
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    frozen_period_total,
    run_standard_supplemental,
    standard_computation_candidates,
)

CSV = (
    'period,group,actual,plan\n'
    '2026-01,A,10,10\n2026-01,A,90,190\n'
    '2026-02,A,30,10\n2026-02,A,170,90\n'
)


def _request_payload(**updates):
    return {
        'operation': 'group_ratio', 'datasetId': 'data', 'outputName': 'result',
        'measureField': 'actual', 'denominatorField': 'plan', 'measureUnit': '元',
        'dimensionField': 'group', 'periodField': 'period', 'periodGranularity': 'month',
        'currentPeriods': ('2026-01', '2026-02'), 'groupByPeriod': True,
        'parentTotal': 300, 'parentPeriodTotals': (100, 200),
        'denominatorParentTotal': 300, 'denominatorPeriodTotals': (200, 100),
        'denominatorScale': 1, 'ratioFactId': 'registered-ratio', **updates,
    }


def _compute(csv=CSV, **updates):
    request = StandardSupplementalRequest.model_validate(_request_payload(**updates))
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=tuple(csv.splitlines()[0].split(',')),
        csv_content=csv.encode(), request=request,
    )
    table = payload['findings'][0]
    return payload, [dict(zip(table['columns'], row, strict=True)) for row in table['rows']]


@pytest.mark.parametrize('measure,denominator,dimension,unit', [
    ('income', 'budget', 'department', '元'),
    ('expense', 'cost_target', 'cost_center', '元'),
    ('visits', 'service_plan', 'service', '人次'),
])
def test_period_ratio_aggregates_operands_before_division_across_topics(measure, denominator, dimension, unit):
    csv = CSV.replace('group,actual,plan', f'{dimension},{measure},{denominator}')
    payload, rows = _compute(csv, measureField=measure, denominatorField=denominator,
                             dimensionField=dimension, measureUnit=unit)
    assert payload['findings'][0]['columns'] == [
        'period', dimension, 'numerator', 'denominator', 'difference', 'ratio',
    ]
    assert rows == [
        {'period': '2026-01', dimension: 'A', 'numerator': 100, 'denominator': 200,
         'difference': -100, 'ratio': .5},
        {'period': '2026-02', dimension: 'A', 'numerator': 200, 'denominator': 100,
         'difference': 100, 'ratio': 2},
    ]
    assert all(check['passed'] for check in payload['reconciliations'])
    assert payload['warnings'] == []


def test_period_ratio_does_not_change_legacy_whole_window_shape_or_average_monthly_ratios():
    raw = _request_payload(groupByPeriod=False)
    raw.pop('parentPeriodTotals')
    raw.pop('denominatorPeriodTotals')
    request = StandardSupplementalRequest.model_validate(raw)
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=('period', 'group', 'actual', 'plan'), csv_content=CSV.encode(), request=request,
    )
    table = payload['findings'][0]
    assert table['columns'] == ['group', 'numerator', 'denominator', 'difference', 'ratio']
    assert table['rows'] == [['A', 300, 300, 0, 1]]


def test_period_ratio_keeps_signed_denominators_and_zero_numerator_distinct_from_zero_denominator():
    payload, rows = _compute(
        'period,group,actual,plan\n2026-01,A,0,10\n2026-01,B,5,0\n2026-01,C,10,-20\n',
        currentPeriods=('2026-01',), parentTotal=15, parentPeriodTotals=(15,),
        denominatorParentTotal=-10, denominatorPeriodTotals=(-10,),
    )
    by_group = {row['group']: row for row in rows}
    assert by_group['A']['ratio'] == 0
    assert by_group['A']['difference'] == -10
    assert by_group['B']['ratio'] is None
    assert by_group['B']['difference'] == 5
    assert by_group['C']['ratio'] == -.5
    assert by_group['C']['difference'] == 30
    assert payload['warnings']
    assert all(check['passed'] for check in payload['reconciliations'])


def test_period_ratio_missing_operand_is_unknown_in_only_its_actual_period():
    payload, rows = _compute(
        'period,group,actual,plan\n2026-01,A,20,\n2026-01,B,,10\n'
        '2026-02,A,40,20\n2026-02,B,5,0\n',
        parentTotal=65, parentPeriodTotals=(20, 45),
        denominatorParentTotal=30, denominatorPeriodTotals=(10, 20),
    )
    by_key = {(row['period'], row['group']): row for row in rows}
    assert by_key['2026-01', 'A']['denominator'] is None
    assert by_key['2026-01', 'A']['difference'] is None
    assert by_key['2026-01', 'A']['ratio'] is None
    assert by_key['2026-01', 'B']['numerator'] is None
    assert by_key['2026-01', 'B']['ratio'] is None
    assert by_key['2026-02', 'A']['ratio'] == 2
    assert by_key['2026-02', 'B']['ratio'] is None
    assert payload['warnings']
    assert all(check['passed'] for check in payload['reconciliations'])


def test_period_denominator_reconciles_in_original_units_before_output_scale_conversion():
    payload, rows = _compute(
        'period,group,actual,plan\n2026-01,A,5000,1\n2026-02,A,15000,3\n',
        parentTotal=20000, parentPeriodTotals=(5000, 15000), denominatorParentTotal=4,
        denominatorPeriodTotals=(1, 3), denominatorScale=10000,
    )
    assert [row['denominator'] for row in rows] == [10000, 30000]
    assert [row['difference'] for row in rows] == [-5000, -15000]
    assert [row['ratio'] for row in rows] == [.5, .5]
    for period, expected in (('2026-01', 1), ('2026-02', 3)):
        check, = [check for check in payload['reconciliations']
                  if period in check['name'] and 'denominator' in check['name']]
        assert (check['left'], check['right'], check['passed']) == (expected, expected, True)


@pytest.mark.parametrize('totals', [None, (), (300,), (200, 100, 0)])
def test_period_ratio_requires_one_explicit_denominator_total_for_every_period(totals):
    raw = _request_payload()
    if totals is None:
        raw.pop('denominatorPeriodTotals')
    else:
        raw['denominatorPeriodTotals'] = totals
    with pytest.raises(ValidationError) as captured:
        StandardSupplementalRequest.model_validate(raw)
    assert any(error['type'] == 'value_error' and 'denominatorPeriodTotals' in error['msg']
               for error in captured.value.errors(include_input=False))


def test_incorrect_period_denominators_warn_even_when_full_window_denominator_closes():
    payload, rows = _compute(denominatorPeriodTotals=(199, 101))
    assert [row['ratio'] for row in rows] == [.5, 2]
    period_checks = [check for check in payload['reconciliations']
                     if 'denominator' in check['name'] and any(
                         period in check['name'] for period in ('2026-01', '2026-02'))]
    assert len(period_checks) == 2
    assert all(check['passed'] is False for check in period_checks)
    full_checks = [check for check in payload['reconciliations']
                   if 'denominator' in check['name'] and check not in period_checks]
    assert len(full_checks) == 1 and full_checks[0]['passed'] is True
    assert payload['warnings']
    validated = validate_supplemental_evidence(json.dumps(payload).encode(),
        {'analysisId': 'analysis_001', 'datasetIds': ['data']})
    assert validated.findings[0]['rows']


def test_period_ratio_keeps_full_window_denominator_reconciliation():
    payload, _ = _compute(denominatorParentTotal=299)
    failed = [check for check in payload['reconciliations'] if check['passed'] is False]
    assert len(failed) == 1
    assert 'denominator' in failed[0]['name']
    assert (failed[0]['left'], failed[0]['right']) == (300, 299)
    assert payload['warnings']


def test_period_denominator_totals_cannot_be_attached_to_legacy_whole_window_ratio():
    raw = _request_payload(groupByPeriod=False)
    raw.pop('parentPeriodTotals')
    with pytest.raises(ValidationError) as captured:
        StandardSupplementalRequest.model_validate(raw)
    assert any(error['type'] == 'value_error' for error in captured.value.errors(include_input=False))


def _registered_state():
    state = _standard_analysis_state()
    numerator, denominator, ratio = _add_registered_group_ratio(state)
    for fact, values in ((numerator, (100, 200)), (denominator, (200, 100))):
        fact.total = 300
        fact.period_values = tuple(SimpleNamespace(period=period, value=value)
                                   for period, value in zip(('2026-01', '2026-02'), values, strict=True))
    state.instruction['currentAnalysis']['periods'] = ['2026-01', '2026-02']
    return state, numerator, denominator, ratio


def _period_spec(numerator, denominator, ratio):
    return StandardSupplementalSpec(
        operation='group_ratio', measureField='income', denominatorField='budget',
        dimensionField='department', periodField='period', currentPeriods=('2026-01', '2026-02'),
        parentFactId=numerator.fact_id, denominatorParentFactId=denominator.fact_id,
        ratioFactId=ratio.fact_id, groupByPeriod=True,
    )


def test_period_ratio_catalog_preflight_executor_and_validator_share_the_same_contract():
    state, numerator, denominator, ratio = _registered_state()
    candidates = standard_computation_candidates(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    ratio_candidates = [candidate for candidate in candidates
                        if candidate['standardComputation']['operation'] == 'group_ratio']
    assert {bool(candidate['standardComputation'].get('groupByPeriod'))
            for candidate in ratio_candidates} == {False, True}
    candidate, = [candidate for candidate in ratio_candidates
                   if candidate['standardComputation'].get('groupByPeriod')]
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']), 'standard_computation': None,
        'standard_candidate_id': candidate['candidateId'], 'required_columns': tuple(candidate['outputColumns']),
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected == _period_spec(numerator, denominator, ratio)
    request = StandardSupplementalRequest.model_validate(_request_payload(
        datasetId='dataset_001', measureField='income', denominatorField='budget', dimensionField='department',
        ratioFactId=ratio.fact_id, parentTotal=frozen_period_total(numerator, selected.current_periods),
        denominatorParentTotal=frozen_period_total(denominator, selected.current_periods),
        parentPeriodTotals=tuple(frozen_period_total(numerator, (period,)) for period in selected.current_periods),
        denominatorPeriodTotals=tuple(frozen_period_total(denominator, (period,))
                                      for period in selected.current_periods),
    ))
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset_001',), authorized_fields=requirement.fields,
        csv_content=CSV.replace('group,actual,plan', 'department,income,budget').encode(), request=request,
    )
    validated = validate_supplemental_evidence(json.dumps(payload).encode(),
        {'analysisId': 'analysis_001', 'datasetIds': ['dataset_001']})
    assert validated.findings[0]['columns'] == candidate['outputColumns']
    assert validated.findings[0]['rows'] == [
        ['2026-01', 'A', 100, 200, -100, .5], ['2026-02', 'A', 200, 100, 100, 2],
    ]


@pytest.mark.parametrize('fault', ['unregistered', 'scope', 'average', 'last', 'cumulative', 'operand_order'])
def test_period_ratio_preflight_never_relaxes_registered_formula_or_sum_parent_boundaries(fault):
    state, numerator, denominator, ratio = _registered_state()
    spec = _period_spec(numerator, denominator, ratio)
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': ('period', 'department', 'income', 'budget'), 'standard_computation': spec,
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    if fault == 'unregistered':
        state.facts.derived_metrics = []
    elif fault == 'scope':
        denominator.scope = {'site': 'North'}
    elif fault == 'average':
        numerator.aggregation = 'average'
    elif fault == 'last':
        denominator.period_aggregation = 'last'
    elif fault == 'cumulative':
        numerator.cumulative_policy = 'cumulative'
    else:
        ratio.input_fact_ids = tuple(reversed(ratio.input_fact_ids))
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize('operation', [
    'group_summary', 'group_period_series', 'period_comparison', 'group_period_comparison',
])
def test_group_by_period_is_not_silently_enabled_on_other_operations(operation):
    with pytest.raises(ValidationError, match='groupByPeriod'):
        StandardSupplementalSpec(operation=operation, measureField='income', dimensionField='department',
            periodField='period', currentPeriods=('2026-01',), parentFactId='registered-parent', groupByPeriod=True)


def test_period_ratio_source_cells_keep_exact_row_periods_and_fraction_scale():
    payload, _ = _compute()
    table = payload['findings'][0]
    assert table['rowPeriodColumn'] == 'period'
    assert table['columnMeta']['ratio']['unit'] == '%'
    assert table['columnMeta']['ratio']['isPercent'] is False
    resource = 'trf-' + '1' * 20
    registered = {resource: json.dumps(payload).encode()}
    for row_index, period in enumerate(('2026-01', '2026-02')):
        for column in ('numerator', 'denominator', 'difference', 'ratio'):
            view = resolve_source_cell(TableOperandV1(fileResourceId=resource, tablePointer='/findings/0',
                rowIndex=row_index, columnIndex=table['columns'].index(column), coefficient='1'), registered)
            assert view['periods'] == (period,)
