"""跨主题标准补证：比较口径、分母、期间与候选预算不能依赖业务名称。"""

import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_coverage import requirement_output_gaps
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisCodingRequirement,
    AnalysisItemWorkflow,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    run_standard_supplemental,
    standard_computation_candidates,
)


def compute(csv, *, operation, measure='amount', dimension='group', granularity='month', **options):
    request = StandardSupplementalRequest(
        operation=operation, datasetId='data', outputName='result',
        measureField=measure, dimensionField=dimension, periodField='period',
        periodGranularity=granularity, **options,
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=tuple(csv.splitlines()[0].split(',')),
        csv_content=csv.encode(), request=request,
    )
    finding = payload['findings'][0]
    return payload, [dict(zip(finding['columns'], row, strict=True)) for row in finding['rows']]


@pytest.mark.parametrize('measure,dimension', [
    ('income', 'department'), ('visits', 'service'), ('expense', 'cost_center'),
])
def test_period_changes_use_calendar_predecessor_across_topics(measure, dimension):
    payload, rows = compute(
        f'period,{dimension},{measure}\n'
        '2025-01,A,10\n2025-02,A,15\n2025-04,A,30\n',
        operation='group_period_series', measure=measure, dimension=dimension,
        currentPeriods=('2025-04', '2025-02', '2025-01'),
        parentTotal=55, parentPeriodTotals=(30, 15, 10), includePeriodChange=True,
    )
    february = next(row for row in rows if row['period'] == '2025-02')
    assert february['previous'] == 10
    assert february['change'] == 5
    assert february['changeRate'] == .5
    april = next(row for row in rows if row['period'] == '2025-04')
    assert april['previous'] is None
    assert april['change'] is None
    assert payload['warnings']
    assert all(item['passed'] for item in payload['reconciliations'])


@pytest.mark.parametrize('grain,current,prior', [
    ('day', '2024-03-01', '2024-02-29'),
    ('day', '2025-03-01', '2025-02-28'),
    ('month', '2025-01', '2024-12'),
    ('year', '2025', '2024'),
])
@pytest.mark.parametrize('operation', ['group_period_series', 'group_period_comparison'])
def test_calendar_predecessors_cover_leap_days_and_year_boundaries(grain, current, prior, operation):
    options = ({'currentPeriods': (current,), 'parentTotal': 20, 'parentPeriodTotals': (20,),
                'baselineMethod': 'previous_period', 'baselinePeriods': (prior,), 'baselinePeriodTotals': (10,)}
               if operation == 'group_period_comparison' else
               {'currentPeriods': (current, prior), 'parentTotal': 30, 'parentPeriodTotals': (20, 10),
                'includePeriodChange': True})
    _, rows = compute(
        f'period,group,amount\n{prior},A,10\n{current},A,20\n',
        operation=operation, granularity=grain, **options,
    )
    row = next(item for item in rows if item['period'] == current)
    assert row['change'] == 10
    assert row['changeRate'] == 1
    assert row['previous' if operation == 'group_period_series' else 'baseline'] == 10


def test_cross_shares_have_independent_signed_marginal_denominators():
    payload, rows = compute(
        'period,group,type,amount\n'
        '2025-01,A,X,20\n2025-01,A,Y,-20\n2025-01,B,X,30\n',
        operation='cross_group_summary', secondaryDimensionField='type',
        currentPeriods=('2025-01',), parentTotal=30, includeMarginalShares=True,
    )
    ax = next(row for row in rows if row['group'] == 'A' and row['type'] == 'X')
    assert ax['share'] == pytest.approx(2 / 3)
    assert ax['primaryTotal'] == 0
    assert ax['primaryShare'] is None
    assert ax['secondaryTotal'] == 50
    assert ax['secondaryShare'] == .4
    assert payload['warnings']
    assert all(item['passed'] for item in payload['reconciliations'])


def test_period_cross_shares_do_not_mix_denominators_across_periods():
    payload, rows = compute(
        'period,group,type,amount\n'
        '2025-01,A,X,10\n2025-01,A,Y,30\n2025-02,A,X,20\n2025-02,B,X,80\n',
        operation='cross_group_summary', secondaryDimensionField='type',
        currentPeriods=('2025-01', '2025-02'), parentTotal=140,
        parentPeriodTotals=(40, 100), includeMarginalShares=True, groupByPeriod=True,
    )
    january_x = next(row for row in rows if row['period'] == '2025-01' and row['type'] == 'X')
    february_a = next(row for row in rows if row['period'] == '2025-02' and row['group'] == 'A')
    assert january_x['primaryShare'] == .25
    assert january_x['secondaryShare'] == 1
    assert february_a['primaryShare'] == 1
    assert february_a['secondaryShare'] == .2
    assert all(item['passed'] for item in payload['reconciliations'])


def test_median_comparison_exposes_nonadditive_residual_without_blocking():
    payload, rows = compute(
        'period,group,amount\n'
        '2025-01,A,0\n2025-01,B,100\n'
        '2025-02,A,100\n2025-02,B,0\n'
        '2025-03,A,100\n2025-03,B,100\n'
        '2025-04,A,200\n2025-04,B,100\n',
        operation='group_period_comparison', baselineMethod='median',
        currentPeriods=('2025-04',), parentTotal=300, parentPeriodTotals=(300,),
        baselinePeriods=('2025-01', '2025-02', '2025-03'),
        baselinePeriodTotals=(100, 100, 200),
    )
    a = next(row for row in rows if row['group'] == 'A')
    assert a['baseline'] == 100
    assert a['change'] == 100
    assert a['changeRate'] == 1
    # 总体中位数为100，分组中位数之和为200，贡献不能归一化伪造为100%。
    assert a['contribution'] == .5
    change_check = next(item for item in payload['reconciliations']
                        if item['name'].endswith('_change'))
    assert change_check == {
        'name': 'result_2025-04_change', 'left': 100, 'right': 200, 'passed': False,
    }
    assert payload['warnings']


def test_mean_comparison_does_not_fill_missing_groups_with_zero():
    payload, rows = compute(
        'period,group,amount\n'
        '2025-01,A,10\n2025-01,B,20\n2025-02,A,30\n2025-03,A,40\n2025-03,B,10\n',
        operation='group_period_comparison', baselineMethod='mean',
        currentPeriods=('2025-03',), parentTotal=50, parentPeriodTotals=(50,),
        baselinePeriods=('2025-01', '2025-02'), baselinePeriodTotals=(30, 30),
    )
    a = next(row for row in rows if row['group'] == 'A')
    b = next(row for row in rows if row['group'] == 'B')
    assert a['baseline'] == 20
    assert a['change'] == 20
    assert a['contribution'] == 1
    assert b['baseline'] is None
    assert b['change'] is None
    assert payload['warnings']


def test_previous_period_contribution_keeps_zero_change_denominator_unknown():
    payload, rows = compute(
        'period,group,amount\n'
        '2025-01,A,10\n2025-01,B,20\n2025-02,A,20\n2025-02,B,10\n',
        operation='group_period_comparison', baselineMethod='previous_period',
        currentPeriods=('2025-02',), parentTotal=30, parentPeriodTotals=(30,),
        baselinePeriods=('2025-01',), baselinePeriodTotals=(30,),
    )
    assert [row['contribution'] for row in rows] == [None, None]
    assert [row['change'] for row in rows] == [10, -10]
    assert payload['warnings']
    assert all(item['passed'] for item in payload['reconciliations'])


def test_baseline_comparison_metadata_separates_current_and_reference_windows():
    payload, _ = compute(
        'period,group,amount\n2025-01,A,10\n2025-02,A,20\n2025-03,A,40\n',
        operation='group_period_comparison', baselineMethod='mean', measureUnit='人次',
        currentPeriods=('2025-03',), parentTotal=40, parentPeriodTotals=(40,),
        baselinePeriods=('2025-01', '2025-02'), baselinePeriodTotals=(10, 20),
    )
    meta = payload['findings'][0]['columnMeta']
    assert meta['current'] == {
        'unit': '人次', 'periods': ['2025-03'], 'periodRoles': ['current'],
        'periodsByRowPeriod': {'2025-03': ['2025-03']},
    }
    assert meta['baseline'] == {
        'unit': '人次', 'periods': ['2025-01', '2025-02'], 'periodRoles': ['prior'],
        'periodsByRowPeriod': {'2025-03': ['2025-01', '2025-02']},
    }
    assert meta['contribution']['periods'] == ['2025-03', '2025-01', '2025-02']


def test_legacy_explicit_spec_can_select_candidate_with_additive_outputs():
    state = _standard_analysis_state()
    state.instruction['datasets'][0]['columns'].append('service_category')
    candidate = next(item for item in standard_computation_candidates(state.facts, state.instruction['datasets'])
                     if item['standardComputation']['operation'] == 'cross_group_summary'
                     and not item['standardComputation'].get('groupByPeriod'))
    raw = dict(candidate['standardComputation'])
    raw.pop('includeMarginalShares')
    spec = StandardSupplementalSpec.model_validate(raw)
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']), 'standard_candidate_id': candidate['candidateId'],
        'standard_computation': spec,
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.include_marginal_shares is True
    # 明确拒绝的选项不能被候选静默改写。
    explicit = StandardSupplementalSpec.model_validate({**raw, 'includeMarginalShares': False})
    state.decision = state.decision.model_copy(update={
        'coding_requirements': (requirement.model_copy(update={'standard_computation': explicit}),),
    })
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_catalog_covers_dimensions_and_measures_before_repeating_them():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    dimensions = [f'axis{i}' for i in range(8)]
    measures = [f'quantity{i}' for i in range(4)]
    state.facts.metrics = [SimpleNamespace(**{
        **vars(parent), 'field': measure, 'fact_id': f'fact-{index:016x}',
    }) for index, measure in enumerate(measures)]
    state.instruction['datasets'][0]['columns'] = ['period', *dimensions, *measures]
    candidates = standard_computation_candidates(state.facts, state.instruction['datasets'])
    specs = [item['standardComputation'] for item in candidates]
    assert {item['measureField'] for item in specs} == set(measures)
    assert {item['dimensionField'] for item in specs} == set(dimensions)
    assert len(candidates) <= 40
    assert sum(len(json.dumps(item, ensure_ascii=False).encode()) for item in candidates) <= 24_000


@pytest.mark.parametrize('method', ['previous_period', 'mean', 'median'])
def test_generic_baseline_spec_routes_only_with_frozen_baseline_periods(method):
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_granularity = 'month'
    parent.period_values = (
        SimpleNamespace(period='2026-01', value=30), SimpleNamespace(period='2026-02', value=50),
    )
    spec = StandardSupplementalSpec(
        operation='group_period_comparison', measureField='income', dimensionField='department',
        periodField='period', currentPeriods=('2026-02',), parentFactId=parent.fact_id,
        baselineMethod=method, baselinePeriods=('2026-01',),
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={'standard_computation': spec})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.baseline_method == method
    invalid = spec.model_copy(update={'baseline_periods': ('2025-12',)})
    state.decision = state.decision.model_copy(update={
        'coding_requirements': (requirement.model_copy(update={'standard_computation': invalid}),),
    })
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_output_contract_rejects_a_standard_plan_missing_requested_changes():
    state = _standard_analysis_state()
    raw = state.decision.coding_requirements[0].model_dump(mode='json', by_alias=True)
    raw['requiredColumns'] = ['department', 'value', 'changeRate']
    requirement = AnalysisCodingRequirement.model_validate(raw)
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_missing_required_columns_remain_specific_soft_coverage_warnings():
    requirements = [{'outputName': 'service_comparison', 'requiredColumns': ['service', 'changeRate']}]
    findings = [{'name': 'service_comparison', 'columns': ['service', 'value'], 'rows': [['A', 10]]}]
    assert requirement_output_gaps(requirements, findings) == [{
        'code': 'report_analysis_requirement_unfulfilled',
        'outputName': 'service_comparison', 'missingColumns': ['changeRate'],
    }]


def test_explicit_comparison_targets_can_select_but_not_expand_analysis_window():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_granularity = 'month'
    parent.period_values = tuple(SimpleNamespace(period=period, value=30)
                                 for period in ('2026-01', '2026-02', '2026-03'))
    state.instruction['currentAnalysis']['periods'] = ['2026-02', '2026-03']
    spec = StandardSupplementalSpec(
        operation='group_period_comparison', measureField='income', dimensionField='department',
        periodField='period', currentPeriods=('2026-03',), parentFactId=parent.fact_id,
        baselineMethod='median', baselinePeriods=('2026-01', '2026-02'),
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={'standard_computation': spec})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == (spec,)
    invalid = spec.model_copy(update={'current_periods': ('2026-01',)})
    state.decision = state.decision.model_copy(update={
        'coding_requirements': (requirement.model_copy(update={'standard_computation': invalid}),),
    })
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_candidates_advertise_actual_extended_outputs_for_any_topic():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_granularity = 'month'
    parent.period_values = (
        SimpleNamespace(period='2026-01', value=30), SimpleNamespace(period='2026-02', value=50),
    )
    state.instruction['datasets'][0]['columns'].append('service_category')
    candidates = standard_computation_candidates(state.facts, state.instruction['datasets'])
    series = next(item for item in candidates if item['standardComputation']['operation'] == 'group_period_series')
    assert {'previous', 'change', 'changeRate'}.issubset(series['outputColumns'])
    cross = next(item for item in candidates if item['standardComputation'].get('groupByPeriod'))
    assert {'period', 'primaryShare', 'secondaryShare'}.issubset(cross['outputColumns'])
    comparison = next(item for item in candidates
                      if item['standardComputation']['operation'] == 'group_period_comparison')
    assert {'baseline', 'changeRate', 'contribution'}.issubset(comparison['outputColumns'])


def test_batch_preflight_builds_catalog_once_and_never_reuses_it_after_fact_changes(monkeypatch):
    from smart_reporting.reporting.workflow.runtime import analysis_item_workflow as module

    state = _standard_analysis_state()
    candidate = next(item for item in standard_computation_candidates(state.facts, state.instruction['datasets'])
                     if item['standardComputation']['operation'] == 'group_summary')
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_candidate_id': candidate['candidateId'], 'standard_computation': None,
    })
    state.decision = state.decision.model_copy(update={
        'coding_requirements': (requirement, requirement.model_copy(update={'output_name': 'second'})),
    })
    builds = []

    def build(facts, datasets, periods=()):
        builds.append(facts.metrics[0].aggregation)
        return standard_computation_candidates(facts, datasets, periods)

    monkeypatch.setattr(module, 'standard_computation_candidates', build)
    assert len(AnalysisItemWorkflow._standard_plan(state)) == 2
    assert builds == ['sum']
    state.facts.metrics[0].aggregation = 'average'
    assert AnalysisItemWorkflow._standard_plan(state) == ()
    assert builds == ['sum', 'average']
