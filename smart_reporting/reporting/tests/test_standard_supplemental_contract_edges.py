"""标准补证不能因合法源字段同名或维度数量不对称而漏命中。"""

import json
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisItemWorkflow,
    validate_supplemental_evidence,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    run_standard_supplemental,
    standard_computation_candidates,
)


def _collision_state(dimension, period, secondary):
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_field = period
    parent.period_granularity = 'month'
    parent.period_roles = ('current',)
    parent.scope = {}
    parent.unit = '元'
    parent.period_values = (SimpleNamespace(period='2026-01', value=10),
                            SimpleNamespace(period='2026-02', value=20))
    baseline = SimpleNamespace(**{
        **vars(parent), 'fact_id': 'fact-0000000000000001', 'period_roles': ('yoy',),
        'period_values': (SimpleNamespace(period='2025-01', value=5),
                          SimpleNamespace(period='2025-02', value=10)),
    })
    denominator = SimpleNamespace(**{
        **vars(parent), 'fact_id': 'fact-0000000000000002', 'field': 'budget',
        'period_values': (SimpleNamespace(period='2026-01', value=20),
                          SimpleNamespace(period='2026-02', value=40)),
    })
    state.facts.metrics = [parent, baseline, denominator]
    state.facts.derived_metrics = [SimpleNamespace(
        fact_id='fact-0000000000000003', input_fact_ids=(parent.fact_id, denominator.fact_id),
        dataset_ids=('dataset_001',), period_role='current', period_granularity='month',
        scope={}, difference=-30, percentage=50, denominator_scale=1,
    )]
    columns = [period, dimension, 'income', 'budget', *([secondary] if secondary else [])]
    state.instruction['datasets'][0]['columns'] = columns
    state.instruction['currentAnalysis']['periods'] = ['2026-01', '2026-02']
    csv = ','.join(columns) + '\n' + '\n'.join(
        ','.join([label, 'A', str(value), str(value * 2), *(['X'] if secondary else [])])
        for label, value in [('2025-01', 5), ('2025-02', 10), ('2026-01', 10), ('2026-02', 20)]
    ) + '\n'
    return state, csv


@pytest.mark.parametrize('operation,dimension,period,secondary', [
    ('group_summary', 'value', 'period', None),
    ('group_period_series', 'rank', 'value', None),
    ('cross_group_summary', 'value', 'rank', 'dimension_value'),
    ('period_comparison', 'current', 'period', None),
    ('group_ratio', 'ratio', 'period', None),
    ('group_period_comparison', 'current', 'baseline', None),
])
def test_colliding_source_names_keep_labels_and_derived_values_in_standard_path(
    operation, dimension, period, secondary,
):
    state, csv = _collision_state(dimension, period, secondary)
    candidates = standard_computation_candidates(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    candidate = next(item for item in candidates
                     if item['standardComputation']['operation'] == operation
                     and item['standardComputation']['measureField'] == 'income'
                     and (item['standardComputation']['dimensionField'] == dimension
                          or operation == 'cross_group_summary')
                     and (operation != 'cross_group_summary'
                          or item['standardComputation'].get('groupByPeriod')))
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']), 'standard_candidate_id': candidate['candidateId'],
        'standard_computation': None, 'required_columns': tuple(candidate['outputColumns']),
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    request = StandardSupplementalRequest(
        operation=operation, datasetId='dataset_001', outputName='result', measureField='income',
        measureUnit='元', dimensionField=selected.dimension_field,
        secondaryDimensionField=selected.secondary_dimension_field,
        periodField=period, periodGranularity='month', currentPeriods=selected.current_periods,
        baselinePeriods=selected.baseline_periods, baselineMethod=selected.baseline_method,
        includePeriodChange=selected.include_period_change,
        includeMarginalShares=selected.include_marginal_shares, groupByPeriod=selected.group_by_period,
        parentTotal=30,
        parentPeriodTotals=((10, 20) if operation in {'group_period_series', 'group_period_comparison'}
                            or selected.group_by_period else ()),
        baselinePeriodTotals=(
            tuple({'2026-01': 10, '2026-02': 20}[label] for label in selected.baseline_periods)
            if operation == 'group_period_comparison' else ()
        ),
        baselineParentTotal=15 if operation == 'period_comparison' else None,
        denominatorField='budget' if operation == 'group_ratio' else None,
        denominatorParentTotal=60 if operation == 'group_ratio' else None,
        denominatorScale=1 if operation == 'group_ratio' else None,
        ratioFactId=selected.ratio_fact_id,
    )
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset_001',), authorized_fields=requirement.fields,
        csv_content=csv.encode(), request=request,
    )
    finding = payload['findings'][0]
    columns = finding['columns']
    assert len(columns) == len(set(columns))
    assert candidate['outputColumns'] == columns
    meta = finding['columnMeta']
    source_alias, = [name for name in columns if meta.get(name, {}).get('sourceField') == dimension]
    assert source_alias != dimension
    rows = [dict(zip(columns, row, strict=True)) for row in finding['rows']]
    assert {row[source_alias] for row in rows} == {'A'}
    if operation in {'group_period_series', 'cross_group_summary', 'group_period_comparison'}:
        period_alias, = [name for name in columns if meta.get(name, {}).get('sourceField') == period]
        assert period_alias != period
        assert {row[period_alias] for row in rows} == {'2026-01', '2026-02'}
        last = next(row for row in rows if row[period_alias] == '2026-02')
    else:
        last = rows[0]
    if operation in {'group_summary', 'group_period_series', 'cross_group_summary'}:
        assert last['value'] == (30 if operation == 'group_summary' else 20)
        assert last['rank'] == 1
        assert last['share'] == 1
    if operation in {'period_comparison', 'group_period_comparison'}:
        assert last['current'] == (30 if operation == 'period_comparison' else 20)
        assert last['baseline'] == (15 if operation == 'period_comparison' else 10)
        assert last['change'] == (15 if operation == 'period_comparison' else 10)
    if operation == 'group_period_series':
        assert last['previous'] == 10
        assert last['change'] == 10
    if operation == 'cross_group_summary':
        assert last['dimension_value'] == 'X'
        assert source_alias != 'dimension_value'
        assert last['primaryShare'] == last['secondaryShare'] == 1
    if operation == 'group_ratio':
        assert last['numerator'] == 30
        assert last['denominator'] == 60
        assert last['ratio'] == .5
    evidence = validate_supplemental_evidence(json.dumps(payload).encode(), state.instruction['currentAnalysis'])
    assert evidence.findings[0]['rows'] == finding['rows']


def test_catalog_represents_each_measure_despite_asymmetric_frozen_scope_dimensions():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    dimensions = [f'axis{index:03}' for index in range(60)]
    state.facts.metrics = [SimpleNamespace(**{
        **vars(parent), 'field': 'quantity0', 'fact_id': 'fact-0000000000000000', 'scope': {},
    }), SimpleNamespace(**{
        **vars(parent), 'field': 'quantity1', 'fact_id': 'fact-0000000000000001',
        'scope': {dimension: 'selected' for dimension in dimensions[1:]},
    })]
    state.instruction['datasets'][0]['columns'] = ['period', *dimensions, 'quantity0', 'quantity1']

    candidates = standard_computation_candidates(state.facts, state.instruction['datasets'])

    assert {item['standardComputation']['measureField'] for item in candidates} == {'quantity0', 'quantity1'}
    narrow = [item for item in candidates if item['standardComputation']['measureField'] == 'quantity1']
    assert {item['standardComputation']['dimensionField'] for item in narrow} == {'axis000'}
    assert len(candidates) <= 40
    assert sum(len(json.dumps(item, ensure_ascii=False).encode()) for item in candidates) <= 24_000


@pytest.mark.parametrize('operation,dimension', [
    ('group_summary', '__value'), ('group_ratio', '__denominator'),
])
def test_internal_numeric_aliases_do_not_overwrite_legitimate_dimension_values(operation, dimension):
    state, csv = _collision_state(dimension, 'period', None)
    is_ratio = operation == 'group_ratio'
    request = StandardSupplementalRequest(
        operation=operation, datasetId='dataset_001', outputName='result', measureField='income',
        dimensionField=dimension, periodField='period', periodGranularity='month',
        currentPeriods=('2026-01', '2026-02'), parentTotal=30,
        denominatorField='budget' if is_ratio else None,
        denominatorParentTotal=60 if is_ratio else None,
        denominatorScale=1 if is_ratio else None,
        ratioFactId='fact-0000000000000003' if is_ratio else None,
    )

    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset_001',),
        authorized_fields=tuple(state.instruction['datasets'][0]['columns']),
        csv_content=csv.encode(), request=request,
    )

    finding = payload['findings'][0]
    assert len(finding['columns']) == len(set(finding['columns']))
    row, = [dict(zip(finding['columns'], item, strict=True)) for item in finding['rows']]
    assert row[dimension] == 'A'
    if is_ratio:
        assert (row['numerator'], row['denominator'], row['ratio']) == (30, 60, .5)
    else:
        assert row['value'] == 30
    validate_supplemental_evidence(json.dumps(payload).encode(), state.instruction['currentAnalysis'])
