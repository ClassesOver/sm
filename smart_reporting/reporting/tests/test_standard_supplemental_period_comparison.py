"""逐期同比保留日历配对、全窗贡献及冻结来源，不能退化成逐月环比。"""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.trace.contracts_v1 import TableOperandV1
from smart_reporting.reporting.trace.table_sources import resolve_source_cell
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    run_standard_supplemental,
    standard_computation_catalog,
)

CURRENT = b'period,group,amount\n2025-01,A,100\n2025-01,B,10\n2025-02,A,30\n2025-02,B,40\n'
BASELINE = b'period,group,amount\n2024-01,A,50\n2024-01,B,20\n2024-02,A,60\n2024-02,B,20\n'


def _request(**updates):
    return StandardSupplementalRequest.model_validate({
        'operation': 'period_comparison', 'datasetId': 'current', 'baselineDatasetId': 'prior',
        'outputName': 'monthly', 'measureField': 'amount', 'measureUnit': '元',
        'dimensionField': 'group', 'periodField': 'period', 'periodGranularity': 'month',
        'currentPeriods': ('2025-02', '2025-01'), 'baselinePeriods': ('2024-01', '2024-02'),
        'groupByPeriod': True, 'parentTotal': 180, 'parentPeriodTotals': (70, 110),
        'baselineParentTotal': 150, 'baselinePeriodTotals': (70, 80), **updates,
    })


def _compute(current=CURRENT, baseline=BASELINE, **updates):
    request = _request(**updates)
    payload = run_standard_supplemental(
        analysis_id='analysis_005', dataset_ids=('current', 'prior'),
        authorized_fields=('period', 'group', 'amount'), csv_content=current, request=request,
        baseline_csv_content=baseline, baseline_authorized_fields=('period', 'group', 'amount'),
    )
    finding, = payload['findings']
    return payload, finding, [dict(zip(finding['columns'], row, strict=True)) for row in finding['rows']]


def test_monthly_yoy_pairs_calendar_months_and_ranks_whole_window_changes():
    payload, finding, rows = _compute()

    assert finding['columns'] == [
        'period', 'group', 'current', 'baseline', 'change', 'changeRate', 'contribution', 'rank',
    ]
    assert [(row['period'], row['group'], row['current'], row['baseline'], row['change'], row['rank'])
            for row in rows] == [
        ('2025-01', 'A', 100, 50, 50, 1), ('2025-02', 'A', 30, 60, -30, 2),
        ('2025-02', 'B', 40, 20, 20, 3), ('2025-01', 'B', 10, 20, -10, 4),
    ]
    assert [row['contribution'] for row in rows] == pytest.approx([5 / 3, -1, 2 / 3, -1 / 3])
    assert [row['changeRate'] for row in rows] == [1, -.5, 1, -.5]
    assert all(check['passed'] for check in payload['reconciliations'])
    assert payload['warnings'] == []


def test_monthly_yoy_baseline_and_contribution_metadata_keep_their_actual_windows():
    _, finding, _ = _compute()
    assert finding['rowPeriodColumn'] == 'period'
    meta = finding['columnMeta']
    assert meta['current']['periodsByRowPeriod']['2025-01'] == ['2025-01']
    assert meta['baseline']['periodsByRowPeriod']['2025-01'] == ['2024-01']
    assert meta['change']['periodsByRowPeriod']['2025-01'] == ['2025-01', '2024-01']
    assert set(meta['contribution']['periodsByRowPeriod']['2025-01']) == {
        '2025-01', '2025-02', '2024-01', '2024-02',
    }
    assert meta['current']['unit'] == '元'
    assert meta['changeRate']['unit'] == '%'
    assert meta['changeRate']['isPercent'] is False


@pytest.mark.parametrize('row_index,period,prior,value,baseline', [
    (0, '2025-01', '2024-01', 100, 50), (1, '2025-02', '2024-02', 30, 60),
])
def test_monthly_yoy_source_cell_resolver_preserves_actual_reference_periods(
    row_index, period, prior, value, baseline,
):
    _, finding, _ = _compute()
    resource = 'trf-' + '1' * 20
    sources = {resource: json.dumps({'findings': [finding]}, ensure_ascii=False).encode()}
    for column, expected_value, periods in (
        ('current', value, (period,)), ('baseline', baseline, (prior,)),
        ('change', value - baseline, (period, prior)),
    ):
        view = resolve_source_cell(TableOperandV1(
            fileResourceId=resource, tablePointer='/findings/0',
            rowIndex=row_index, columnIndex=finding['columns'].index(column), coefficient='1',
        ), sources)
        assert view['value'] == expected_value
        assert view['periods'] == periods
    for column in ('contribution', 'rank'):
        view = resolve_source_cell(TableOperandV1(
            fileResourceId=resource, tablePointer='/findings/0',
            rowIndex=row_index, columnIndex=finding['columns'].index(column), coefficient='1',
        ), sources)
        assert set(view['periods']) == {'2025-01', '2025-02', '2024-01', '2024-02'}


def test_monthly_yoy_does_not_borrow_another_month_or_replace_missing_values_with_zero():
    payload, _, rows = _compute(
        current=b'period,group,amount\n2025-01,A,0\n2025-01,B,10\n2025-02,A,5\n',
        baseline=b'period,group,amount\n2024-01,A,10\n2024-01,B,0\n2024-02,B,20\n',
        parentTotal=15, parentPeriodTotals=(5, 10),
        baselineParentTotal=30, baselinePeriodTotals=(10, 20),
    )
    by_key = {(row['period'], row['group']): row for row in rows}
    assert by_key['2025-01', 'A']['changeRate'] == -1
    assert by_key['2025-01', 'B']['change'] == 10
    assert by_key['2025-01', 'B']['changeRate'] is None
    assert by_key['2025-02', 'A']['baseline'] is None
    assert by_key['2025-02', 'A']['change'] is None
    assert by_key['2025-02', 'B']['current'] is None
    assert by_key['2025-02', 'B']['contribution'] is None
    assert payload['warnings']
    assert any(not check['passed'] for check in payload['reconciliations'])


@pytest.mark.parametrize('updates', [
    {'baselinePeriods': ('2024-01',)},
    {'baselinePeriods': ('2024-01', '2024-03')},
    {'baselinePeriodTotals': ()},
    {'baselinePeriodTotals': (150,)},
    {'parentPeriodTotals': ()},
])
def test_monthly_comparison_rejects_incomplete_or_noncalendar_baselines(updates):
    with pytest.raises(ValidationError):
        _request(**updates)


def test_monthly_yoy_reconciles_each_month_even_when_annual_totals_still_close():
    payload, _, rows = _compute(parentPeriodTotals=(80, 100), baselinePeriodTotals=(80, 70))
    assert len(rows) == 4
    assert payload['warnings']
    assert sum(not check['passed'] for check in payload['reconciliations']) == 4
    assert all(check['passed'] for check in payload['reconciliations']
               if check['name'] in {'monthly_current_total', 'monthly_baseline_total', 'monthly_change'})


def test_monthly_yoy_zero_window_change_keeps_contributions_unknown():
    payload, _, rows = _compute(
        current=b'period,group,amount\n2025-01,A,20\n2025-02,A,10\n',
        baseline=b'period,group,amount\n2024-01,A,10\n2024-02,A,20\n',
        parentTotal=30, parentPeriodTotals=(10, 20),
        baselineParentTotal=30, baselinePeriodTotals=(10, 20),
    )
    assert [row['change'] for row in rows] == [10, -10]
    assert all(row['contribution'] is None for row in rows)
    assert all(check['passed'] for check in payload['reconciliations'])
    assert payload['warnings']


def test_monthly_yoy_signed_ranking_and_absolute_rate_do_not_change_contribution_basis():
    _, _, rows = _compute(
        current=b'period,group,amount\n2025-01,A,-5\n2025-02,A,-50\n',
        baseline=b'period,group,amount\n2024-01,A,-10\n2024-02,A,-10\n',
        parentTotal=-55, parentPeriodTotals=(-50, -5),
        baselineParentTotal=-20, baselinePeriodTotals=(-10, -10),
        rankBy='change_desc', changeRateDenominator='absolute',
    )
    assert [(row['period'], row['rank'], row['changeRate']) for row in rows] == [
        ('2025-01', 1, .5), ('2025-02', 2, -4),
    ]
    assert [row['contribution'] for row in rows] == pytest.approx([-1 / 7, 8 / 7])


def test_monthly_comparison_preserves_same_dataset_support():
    request = _request(baselineDatasetId=None)
    payload = run_standard_supplemental(
        analysis_id='analysis_005', dataset_ids=('current',),
        authorized_fields=('period', 'group', 'amount'),
        csv_content=CURRENT + BASELINE.split(b'\n', 1)[1], request=request,
    )
    assert payload['findings'][0]['rows'][0] == ['2025-01', 'A', 100, 50, 50, 1, 5 / 3, 1]
    assert all(check['passed'] for check in payload['reconciliations'])


def _state():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_granularity = 'month'
    parent.period_roles = ('current',)
    parent.field_ref = 'income.amount'
    parent.unit = '元'
    parent.period_values = (SimpleNamespace(period='2025-01', value=110),
                            SimpleNamespace(period='2025-02', value=70))
    prior = SimpleNamespace(**vars(parent))
    prior.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    prior.dataset_id = 'dataset_prior'
    prior.dataset_sha256 = 'b' * 64
    prior.period_roles = ('yoy',)
    prior.period_values = (SimpleNamespace(period='2024-02', value=80),
                           SimpleNamespace(period='2024-01', value=70))
    state.facts.metrics.append(prior)
    state.instruction['datasets'].append({
        'datasetId': 'dataset_prior', 'sha256': 'b' * 64,
        'columns': ['period', 'department', 'income'],
    })
    state.instruction['currentAnalysis']['datasetIds'].append('dataset_prior')
    state.instruction['currentAnalysis']['periods'] = ['2025-01', '2025-02']
    return state


@pytest.mark.parametrize('rank_by', ['absolute_change_desc', 'change_desc'])
def test_cumulative_yoy_catalog_routes_required_ranking(rank_by):
    state = _state()
    catalog = standard_computation_catalog(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    candidate = next(item for item in catalog['candidates']
                     if item['standardComputation']['operation'] == 'period_comparison'
                     and not item['standardComputation'].get('groupByPeriod'))
    assert 'rank' in candidate['outputColumns']
    spec = StandardSupplementalSpec.model_validate({
        **candidate['standardComputation'], 'rankBy': rank_by,
    })
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': spec, 'standard_candidate_id': candidate['candidateId'],
        'fields': tuple(candidate['fields']),
        'required_columns': ('department', 'current', 'baseline', 'change', 'changeRate', 'contribution', 'rank'),
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.group_by_period is False
    assert selected.rank_by == rank_by
    assert selected.baseline_dataset_id == 'dataset_prior'


def test_monthly_yoy_catalog_routes_a_complete_batch_without_inventing_a_script_spec():
    state = _state()
    catalog = standard_computation_catalog(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    candidate = next(item for item in catalog['candidates']
                     if item['standardComputation']['operation'] == 'period_comparison'
                     and item['standardComputation'].get('groupByPeriod'))
    assert candidate['outputColumns'] == [
        'period', 'department', 'current', 'baseline', 'change', 'changeRate', 'contribution', 'rank',
    ]
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
        'fields': tuple(candidate['fields']), 'required_columns': tuple(candidate['outputColumns']),
    })
    cumulative = StandardSupplementalSpec.model_validate(candidate['standardComputation']).model_copy(
        update={'group_by_period': False})
    requirements = (requirement, *(requirement.model_copy(update={
        'output_name': f'cumulative_{index}', 'standard_candidate_id': None,
        'standard_computation': cumulative,
        'required_columns': ('department', 'current', 'baseline', 'change', 'changeRate', 'contribution'),
    }) for index in range(3)))
    state.decision = state.decision.model_copy(update={'coding_requirements': requirements})
    selected, *others = AnalysisItemWorkflow._standard_plan(state)
    assert len(others) == 3
    assert all(not item.group_by_period for item in others)
    assert selected.group_by_period is True
    assert selected.baseline_dataset_id == 'dataset_prior'
    assert selected.current_periods == ('2025-01', '2025-02')
    assert selected.baseline_periods == ('2024-01', '2024-02')


def test_monthly_comparison_aliases_colliding_source_fields_without_losing_period_bindings():
    request = _request(periodField='rank', dimensionField='change')
    payload = run_standard_supplemental(
        analysis_id='analysis_005', dataset_ids=('current', 'prior'),
        authorized_fields=('rank', 'change', 'amount'),
        csv_content=CURRENT.replace(b'period,group', b'rank,change'), request=request,
        baseline_csv_content=BASELINE.replace(b'period,group', b'rank,change'),
        baseline_authorized_fields=('rank', 'change', 'amount'),
    )
    finding, = payload['findings']
    assert finding['columns'] == [
        'period_rank', 'dimension_change', 'current', 'baseline', 'change', 'changeRate', 'contribution', 'rank',
    ]
    assert finding['rowPeriodColumn'] == 'period_rank'
    assert finding['columnMeta']['period_rank']['sourceField'] == 'rank'
    assert finding['columnMeta']['dimension_change']['sourceField'] == 'change'
    assert finding['rows'][0] == ['2025-01', 'A', 100, 50, 50, 1, 5 / 3, 1]
    assert finding['columnMeta']['baseline']['periodsByRowPeriod']['2025-01'] == ['2024-01']


def test_monthly_yoy_explicit_spec_accepts_aliases_without_relaxing_authorization():
    state = _state()
    spec = StandardSupplementalSpec(
        operation='period_comparison', measureField='income', dimensionField='department',
        periodField='period', currentPeriods=('2025-01-01', '2025-02-01'),
        baselinePeriods=('2024-02-01', '2024-01-01'), groupByPeriod=True,
        parentFactId=state.facts.metrics[0].fact_id, baselineParentFactId=state.facts.metrics[1].fact_id,
        baselineDatasetId='dataset_prior', changeRateDenominator='absolute',
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={'standard_computation': spec})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert len(AnalysisItemWorkflow._standard_plan(state)) == 1
    state.facts.metrics[1].dataset_sha256 = 'c' * 64
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize('fault', ['calendar', 'role', 'scope', 'fields', 'dataset', 'measure', 'window'])
def test_monthly_yoy_preflight_preserves_existing_authorization_boundaries(fault):
    state = _state()
    spec = StandardSupplementalSpec(
        operation='period_comparison', measureField='income', dimensionField='department',
        periodField='period', currentPeriods=('2025-01', '2025-02'),
        baselinePeriods=('2024-01', '2024-02'), groupByPeriod=True,
        parentFactId=state.facts.metrics[0].fact_id, baselineParentFactId=state.facts.metrics[1].fact_id,
        baselineDatasetId='dataset_prior',
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={'standard_computation': spec})
    if fault == 'calendar':
        state.facts.metrics[1].period_values = (SimpleNamespace(period='2024-01', value=70),
                                               SimpleNamespace(period='2024-03', value=80))
        requirement = requirement.model_copy(update={
            'standard_computation': spec.model_copy(update={'baseline_periods': ('2024-01', '2024-03')}),
        })
    elif fault == 'role':
        state.facts.metrics[1].period_roles = ()
    elif fault == 'scope':
        state.facts.metrics[1].scope = {'area': 'south'}
    elif fault == 'fields':
        state.instruction['datasets'][1]['columns'].remove('department')
    elif fault == 'dataset':
        state.instruction['currentAnalysis']['datasetIds'].remove('dataset_prior')
    elif fault == 'measure':
        state.facts.metrics[1].field_ref = 'foreign.amount'
    else:
        state.instruction['currentAnalysis']['periods'] = ['2025-01']
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == ()
