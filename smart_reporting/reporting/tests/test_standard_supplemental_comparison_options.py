"""显式比较口径不能改写贡献分母、候选身份或冻结授权边界。"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    run_standard_supplemental,
    standard_computation_candidates,
)

COMPARISONS = ('period_comparison', 'group_period_comparison', 'group_period_series')
OPERATIONS = (*COMPARISONS, 'group_summary', 'cross_group_summary', 'group_ratio')
MODELS = (StandardSupplementalRequest, StandardSupplementalSpec)


def _request_data(operation, **options):
    data = {
        'operation': operation, 'datasetId': 'data', 'outputName': 'result',
        'measureField': 'amount', 'dimensionField': 'group', 'periodField': 'period',
        'periodGranularity': 'month', 'currentPeriods': ('2026-02',), 'parentTotal': 20,
    }
    if operation == 'period_comparison':
        data.update(baselinePeriods=('2026-01',), baselineParentTotal=10)
    elif operation == 'group_period_comparison':
        data.update(
            baselineMethod='previous_period', baselinePeriods=('2026-01',),
            baselinePeriodTotals=(10,), parentPeriodTotals=(20,),
        )
    elif operation == 'group_period_series':
        data.update(
            currentPeriods=('2026-01', '2026-02'), parentTotal=30,
            parentPeriodTotals=(10, 20), includePeriodChange=True,
        )
    elif operation == 'cross_group_summary':
        data['secondaryDimensionField'] = 'category'
    elif operation == 'group_ratio':
        data.update(
            denominatorField='denominator', denominatorParentTotal=40,
            denominatorScale=1, ratioFactId='fact-ratio',
        )
    return {**data, **options}


def _model_data(model, operation, **options):
    data = _request_data(operation, **options)
    if model is StandardSupplementalSpec:
        for name in (
            'datasetId', 'outputName', 'periodGranularity', 'parentTotal', 'parentPeriodTotals',
            'baselineParentTotal', 'baselinePeriodTotals', 'denominatorParentTotal', 'denominatorScale',
        ):
            data.pop(name, None)
        data['parentFactId'] = 'fact-parent'
        if operation == 'group_ratio':
            data['denominatorParentFactId'] = 'fact-denominator'
    return data


def _compute(csv, operation, **options):
    request = StandardSupplementalRequest.model_validate(_request_data(operation, **options))
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=tuple(csv.splitlines()[0].split(',')),
        csv_content=csv.encode(), request=request,
    )
    finding = payload['findings'][0]
    rows = [dict(zip(finding['columns'], row, strict=True)) for row in finding['rows']]
    if operation == 'group_period_series':
        rows = [row for row in rows if row['period'] == '2026-02']
    return payload, finding, rows


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('operation', OPERATIONS)
def test_explicit_default_options_preserve_legacy_serialized_payload(model, operation):
    legacy = model.model_validate(_model_data(model, operation)).model_dump(by_alias=True)
    explicit = model.model_validate(_model_data(
        model, operation, changeRateDenominator='signed', rankBy='absolute_change_desc',
    )).model_dump(by_alias=True)

    assert explicit == legacy
    assert 'changeRateDenominator' not in explicit
    assert 'rankBy' not in explicit


@pytest.mark.parametrize('model', MODELS)
@pytest.mark.parametrize('operation', OPERATIONS)
def test_nondefault_options_survive_serialization_only_where_applicable(model, operation):
    data = _model_data(model, operation, changeRateDenominator='absolute')
    if operation in COMPARISONS:
        assert model.model_validate(data).model_dump(by_alias=True)['changeRateDenominator'] == 'absolute'
    else:
        with pytest.raises(ValidationError):
            model.model_validate(data)

    data = _model_data(model, operation, rankBy='change_desc')
    if operation == 'group_period_comparison':
        assert model.model_validate(data).model_dump(by_alias=True)['rankBy'] == 'change_desc'
    else:
        with pytest.raises(ValidationError):
            model.model_validate(data)


@pytest.mark.parametrize('model', MODELS)
def test_series_without_period_changes_rejects_absolute_denominator(model):
    with pytest.raises(ValidationError):
        model.model_validate(_model_data(
            model, 'group_period_series', includePeriodChange=False, changeRateDenominator='absolute',
        ))


@pytest.mark.parametrize('operation', COMPARISONS)
@pytest.mark.parametrize('mode,expected_rate', [('signed', -.5), ('absolute', .5)])
def test_negative_baseline_rate_uses_selected_denominator_without_changing_contribution(
    operation, mode, expected_rate,
):
    payload, finding, rows = _compute(
        'period,group,amount\n'
        '2026-01,A,-10\n2026-01,B,20\n2026-02,A,-5\n2026-02,B,25\n',
        operation, changeRateDenominator=mode,
    )
    by_group = {row['group']: row for row in rows}
    assert by_group['A']['change'] == 5
    assert by_group['A']['changeRate'] == expected_rate
    assert by_group['B']['changeRate'] == .25
    if operation != 'group_period_series':
        assert by_group['A']['contribution'] == .5
        assert by_group['B']['contribution'] == .5
    if mode == 'absolute':
        assert finding['comparison']['changeRateDenominator'] == 'absolute'
    elif operation == 'group_period_comparison':
        assert 'changeRateDenominator' not in finding['comparison']
    else:
        assert 'comparison' not in finding
    assert all(item['passed'] for item in payload['reconciliations'])


@pytest.mark.parametrize('operation', COMPARISONS)
@pytest.mark.parametrize('mode', ['signed', 'absolute'])
def test_selected_denominator_keeps_zero_and_missing_baselines_unknown(operation, mode):
    options = {'parentTotal': 7}
    if operation == 'period_comparison':
        options['baselineParentTotal'] = -1
    elif operation == 'group_period_comparison':
        options.update(parentPeriodTotals=(7,), baselinePeriodTotals=(-1,))
    else:
        options.update(parentTotal=6, parentPeriodTotals=(-1, 7))
    payload, _, rows = _compute(
        'period,group,amount\n'
        '2026-01,A,0\n2026-01,C,9\n2026-01,D,-10\n'
        '2026-02,A,5\n2026-02,B,7\n2026-02,D,-5\n',
        operation, changeRateDenominator=mode, **options,
    )
    by_group = {row['group']: row for row in rows}
    assert by_group['A']['change'] == 5
    assert by_group['A']['changeRate'] is None
    assert by_group['B']['change'] is None
    assert by_group['B']['changeRate'] is None
    if operation != 'group_period_series':
        assert by_group['C']['current'] is None
        assert by_group['C']['change'] is None
        assert by_group['C']['changeRate'] is None
    assert payload['warnings']


@pytest.mark.parametrize('rank_by,expected', [
    ('absolute_change_desc', ['B', 'A', 'C', 'D', 'E']),
    ('change_desc', ['A', 'C', 'D', 'B', 'E']),
])
def test_ranking_direction_breaks_ties_stably_and_keeps_signed_total_change(rank_by, expected):
    _, finding, rows = _compute(
        'period,group,amount\n'
        '2026-01,D,0\n2026-01,C,0\n2026-01,B,50\n2026-01,A,0\n'
        '2026-02,D,-10\n2026-02,C,10\n2026-02,B,10\n2026-02,A,10\n2026-02,E,0\n',
        'group_period_comparison', parentTotal=20, parentPeriodTotals=(20,),
        baselinePeriodTotals=(50,), rankBy=rank_by, changeRateDenominator='absolute',
    )
    assert [row['group'] for row in rows] == expected
    assert [row['rank'] for row in rows] == [1, 2, 3, 4, 5]
    by_group = {row['group']: row for row in rows}
    assert by_group['A']['contribution'] == pytest.approx(-1 / 3)
    assert by_group['B']['contribution'] == pytest.approx(4 / 3)
    assert by_group['E']['change'] is None
    assert all(row['totalChange'] == -30 for row in rows)
    assert finding['comparison']['rankBy'] == rank_by


def _comparison_state(**options):
    state = _standard_analysis_state()
    state.instruction['currentAnalysis']['periods'] = ['2026-02']
    parent = state.facts.metrics[0]
    parent.period_granularity = 'month'
    parent.period_values = (
        SimpleNamespace(period='2026-01', value=10), SimpleNamespace(period='2026-02', value=20),
    )
    spec = StandardSupplementalSpec(
        operation='group_period_comparison', measureField='income', dimensionField='department',
        periodField='period', currentPeriods=('2026-02',), parentFactId=parent.fact_id,
        baselineMethod='previous_period', baselinePeriods=('2026-01',), **options,
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={'standard_computation': spec})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    return state


@pytest.mark.parametrize('option', [
    {'changeRateDenominator': 'absolute'}, {'rankBy': 'change_desc'},
])
def test_candidate_accepts_supported_explicit_comparison_options(option):
    state = _comparison_state(**option)
    candidate = next(item for item in standard_computation_candidates(
        state.facts, state.instruction['datasets'], requested_periods=('2026-02',),
    )
                     if item['standardComputation']['operation'] == 'group_period_comparison'
                     and item['standardComputation']['currentPeriods'] == ['2026-02']
                     and item['standardComputation']['baselineMethod'] == 'previous_period')
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']), 'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})

    spec, = AnalysisItemWorkflow._standard_plan(state)
    assert spec.model_dump(by_alias=True)[next(iter(option))] == next(iter(option.values()))


@pytest.mark.parametrize('fault', ['fields', 'dataset', 'scope', 'frozen_period', 'analysis_window'])
def test_explicit_comparison_options_do_not_expand_frozen_authorization(fault):
    state = _comparison_state(changeRateDenominator='absolute', rankBy='change_desc')
    assert len(AnalysisItemWorkflow._standard_plan(state)) == 1
    requirement = state.decision.coding_requirements[0]
    if fault == 'fields':
        requirement = requirement.model_copy(update={'fields': ('income', 'period')})
    elif fault == 'dataset':
        requirement = requirement.model_copy(update={'dataset_id': 'foreign'})
    elif fault == 'scope':
        state.facts.metrics[0].scope = {'area': 'north'}
    elif fault == 'frozen_period':
        spec = requirement.standard_computation.model_copy(update={'baseline_periods': ('2025-12',)})
        requirement = requirement.model_copy(update={'standard_computation': spec})
    else:
        state.instruction['currentAnalysis']['periods'] = ['2026-01']
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})

    assert AnalysisItemWorkflow._standard_plan(state) == ()
