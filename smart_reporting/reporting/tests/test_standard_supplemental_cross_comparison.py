"""双维比较复用期间授权，贡献和排名须区分全院与主维度内部。"""

import json

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_supplemental_period_comparison import _state
from smart_reporting.reporting.trace.contracts_v1 import TableOperandV1
from smart_reporting.reporting.trace.table_sources import resolve_source_cell
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    run_standard_supplemental,
    standard_computation_candidates,
    standard_computation_catalog,
)

CURRENT = b'period,department,category,amount\n2025-01,A,X,120\n2025-01,A,Y,30\n2025-01,B,X,30\n2025-01,B,Y,50\n'
PRIOR = b'period,department,category,amount\n2024-01,A,X,100\n2024-01,A,Y,40\n2024-01,B,X,10\n2024-01,B,Y,60\n'


def _compute(current=CURRENT, prior=PRIOR, **updates):
    request = StandardSupplementalRequest.model_validate({
        'operation': 'period_comparison', 'datasetId': 'current', 'baselineDatasetId': 'prior',
        'outputName': 'department_category_yoy', 'measureField': 'amount', 'measureUnit': '元',
        'dimensionField': 'department', 'secondaryDimensionField': 'category',
        'periodField': 'period', 'periodGranularity': 'month',
        'currentPeriods': ['2025-01'], 'baselinePeriods': ['2024-01'],
        'parentTotal': 230, 'baselineParentTotal': 210, **updates,
    })
    payload = run_standard_supplemental(
        analysis_id='analysis_008', dataset_ids=('current', 'prior'),
        authorized_fields=('period', 'department', 'category', 'amount'), csv_content=current,
        request=request, baseline_csv_content=prior,
        baseline_authorized_fields=('period', 'department', 'category', 'amount'),
    )
    finding, = payload['findings']
    rows = [dict(zip(finding['columns'], row, strict=True)) for row in finding['rows']]
    return payload, finding, {(row['department'], row['category']): row for row in rows}


def test_dual_comparison_aligns_pairs_and_distinguishes_global_and_group_contribution():
    payload, finding, rows = _compute()
    assert len(rows) == 4
    assert rows['A', 'X']['change'] == 20
    assert rows['A', 'Y']['change'] == -10
    assert rows['A', 'X']['contribution'] == 1
    assert rows['A', 'X']['primaryChange'] == 10
    assert rows['A', 'X']['primaryContribution'] == 2
    assert rows['A', 'Y']['primaryContribution'] == -1
    assert [rows[key]['primaryRank'] for key in [('A', 'X'), ('A', 'Y'), ('B', 'X'), ('B', 'Y')]] == [1, 2, 1, 2]
    assert finding['columnMeta']['primaryChange']['unit'] == '元'
    assert finding['columnMeta']['primaryContribution']['isPercent'] is False
    assert finding['comparison']['primaryDimensionField'] == 'department'
    assert all(check['passed'] for check in payload['reconciliations'])
    assert payload['warnings'] == []


def test_zero_group_change_keeps_local_contribution_unknown_without_hiding_offsets():
    current = b'period,department,category,amount\n2025-01,A,X,150\n2025-01,A,Y,0\n'
    prior = b'period,department,category,amount\n2024-01,A,X,100\n2024-01,A,Y,50\n'
    payload, _, rows = _compute(current, prior, parentTotal=150, baselineParentTotal=150)
    assert rows['A', 'X']['change'] == 50
    assert rows['A', 'Y']['change'] == -50
    assert all(row['primaryChange'] == 0 and row['primaryContribution'] is None for row in rows.values())
    assert [rows['A', key]['primaryRank'] for key in ('X', 'Y')] == [1, 2]
    assert payload['warnings']


def test_missing_pair_is_not_zero_filled_or_used_as_complete_group_decomposition():
    current = b'period,department,category,amount\n2025-01,A,X,120\n'
    prior = b'period,department,category,amount\n2024-01,A,X,100\n2024-01,A,Y,40\n'
    payload, _, rows = _compute(current, prior, parentTotal=120, baselineParentTotal=140)
    assert rows['A', 'Y']['current'] is None
    assert rows['A', 'Y']['change'] is None
    assert all(row['primaryChange'] is None and row['primaryContribution'] is None
               and row['primaryRank'] is None for row in rows.values())
    assert payload['warnings']


def test_dual_comparison_retains_period_pairing_and_local_ranks_per_period():
    payload, finding, rows = _compute(
        groupByPeriod=True, parentPeriodTotals=(230,), baselinePeriodTotals=(210,),
    )
    assert finding['rowPeriodColumn'] == 'period'
    assert all(row['period'] == '2025-01' for row in rows.values())
    assert rows['A', 'X']['primaryContribution'] == 2
    assert finding['columnMeta']['primaryChange']['periodsByRowPeriod']['2025-01'] == ['2025-01', '2024-01']
    assert all(check['passed'] for check in payload['reconciliations'])


def test_monthly_local_contributions_never_mix_different_periods_of_same_department():
    current = (b'period,department,category,amount\n2025-01,A,X,120\n2025-01,A,Y,30\n'
               b'2025-02,A,X,20\n2025-02,A,Y,70\n')
    prior = (b'period,department,category,amount\n2024-01,A,X,100\n2024-01,A,Y,40\n'
             b'2024-02,A,X,40\n2024-02,A,Y,40\n')
    _, finding, _ = _compute(
        current, prior, currentPeriods=['2025-01', '2025-02'], baselinePeriods=['2024-02', '2024-01'],
        groupByPeriod=True, parentTotal=240, baselineParentTotal=220,
        parentPeriodTotals=(150, 90), baselinePeriodTotals=(80, 140),
    )
    rows = {(row[0], row[2]): dict(zip(finding['columns'], row, strict=True)) for row in finding['rows']}
    assert [(rows[key]['primaryChange'], rows[key]['primaryContribution'], rows[key]['primaryRank'])
            for key in [('2025-01', 'X'), ('2025-01', 'Y'), ('2025-02', 'X'), ('2025-02', 'Y')]] == [
        (10, 2, 1), (10, -1, 2), (10, -2, 2), (10, 3, 1),
    ]
    assert rows['2025-02', 'Y']['contribution'] == 1.5
    assert finding['columnMeta']['primaryContribution']['periodsByRowPeriod']['2025-02'] == ['2025-02', '2024-02']


@pytest.mark.parametrize('rank_by,ranks', [('absolute_change_desc', [2, 1]), ('change_desc', [1, 2])])
def test_local_ranking_respects_signed_option_without_changing_contribution_denominator(rank_by, ranks):
    current = b'period,department,category,amount\n2025-01,A,X,30\n2025-01,A,Y,10\n'
    prior = b'period,department,category,amount\n2024-01,A,X,10\n2024-01,A,Y,40\n'
    _, _, rows = _compute(current, prior, parentTotal=40, baselineParentTotal=50, rankBy=rank_by)
    assert [rows['A', key]['primaryRank'] for key in ('X', 'Y')] == ranks
    assert [rows['A', key]['primaryContribution'] for key in ('X', 'Y')] == [-2, 3]


def test_cross_keys_do_not_merge_combinations_with_same_concatenated_label():
    current = b'period,department,category,amount\n2025-01,A|B,C,20\n2025-01,A,B|C,15\n'
    prior = b'period,department,category,amount\n2024-01,A|B,C,10\n2024-01,A,B|C,5\n'
    _, _, rows = _compute(current, prior, parentTotal=35, baselineParentTotal=15)
    assert set(rows) == {('A|B', 'C'), ('A', 'B|C')}
    assert all(row['change'] == 10 and row['primaryRank'] == 1 for row in rows.values())


@pytest.mark.parametrize('by_period', [False, True])
def test_cross_source_query_preserves_group_change_and_contribution_semantics(by_period):
    _, finding, _ = _compute(**(
        {'groupByPeriod': True, 'parentPeriodTotals': (230,), 'baselinePeriodTotals': (210,)}
        if by_period else {}
    ))
    sources = {'trf-' + '1' * 20: json.dumps({'findings': [finding]}).encode()}
    for column, expected, unit in [('primaryChange', 10, '元'), ('primaryContribution', 2, '%')]:
        view = resolve_source_cell(TableOperandV1(
            fileResourceId='trf-' + '1' * 20, tablePointer='/findings/0', rowIndex=0,
            columnIndex=finding['columns'].index(column), coefficient='1',
        ), sources)
        assert view['value'] == expected
        assert view['unit'] == unit
        assert set(view['periods']) == {'2025-01', '2024-01'}


def test_same_dataset_cross_comparison_preserves_two_periods_without_external_baseline():
    combined = CURRENT + PRIOR.split(b'\n', 1)[1]
    payload, _, rows = _compute(combined, None, baselineDatasetId=None)
    assert rows['A', 'X']['change'] == 20
    assert rows['A', 'Y']['primaryContribution'] == -1
    assert all(check['passed'] for check in payload['reconciliations'])


def test_cross_comparison_spec_requires_distinct_authorized_secondary_dimension():
    data = dict(operation='period_comparison', measureField='amount', dimensionField='department',
                secondaryDimensionField='category', periodField='period', currentPeriods=['2025-01'],
                baselinePeriods=['2024-01'], parentFactId='fact-parent', baselineParentFactId='fact-prior')
    assert StandardSupplementalSpec(**data).secondary_dimension_field == 'category'
    with pytest.raises(ValidationError):
        StandardSupplementalSpec(**{**data, 'secondaryDimensionField': 'department'})


def _cross_state():
    state = _state()
    for dataset in state.instruction['datasets']:
        dataset['columns'].append('category')
    return state


def test_catalog_advertises_cross_comparisons_with_complete_outputs_and_valid_bindings():
    state = _cross_state()
    candidates = standard_computation_candidates(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    cross = [candidate for candidate in candidates
             if candidate['standardComputation']['operation'] == 'period_comparison'
             and candidate['standardComputation'].get('secondaryDimensionField')]
    assert {candidate['standardComputation'].get('groupByPeriod', False) for candidate in cross} == {False, True}
    for candidate in cross:
        requirement = state.decision.coding_requirements[0].model_copy(update={
            'standard_candidate_id': candidate['candidateId'], 'standard_computation': None,
            'fields': tuple(candidate['fields']), 'required_columns': tuple(candidate['outputColumns']),
        })
        state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
        selected, = AnalysisItemWorkflow._standard_plan(state)
        assert selected.secondary_dimension_field is not None
        assert {'primaryContribution', 'primaryRank'}.issubset(candidate['outputColumns'])


@pytest.mark.parametrize('missing_side', [None, 'current', 'baseline'])
def test_explicit_cross_comparison_uses_signed_sources_and_rejects_missing_dimension(missing_side):
    state = _cross_state()
    catalog = standard_computation_catalog(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    source = next(item for item in catalog['groupingSources']['items']
                  if item['datasetId'] == 'dataset_001')
    binding, = source['comparisonBindings']
    spec = StandardSupplementalSpec(
        operation='period_comparison', measureField=source['measureField'],
        dimensionField='department', secondaryDimensionField='category',
        periodField=source['periodField'], currentPeriods=source['currentPeriods'],
        parentFactId=source['parentFactId'], baselinePeriods=binding['baselinePeriods'],
        baselineParentFactId=binding['baselineParentFactId'], baselineDatasetId=binding['baselineDatasetId'],
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_candidate_id': None, 'standard_computation': spec,
        'fields': ('period', 'department', 'category', 'income'),
        'required_columns': ('department', 'category', 'primaryContribution', 'primaryRank'),
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    if missing_side is not None:
        dataset = state.instruction['datasets'][0 if missing_side == 'current' else 1]
        dataset['columns'].remove('category')
    assert bool(AnalysisItemWorkflow._standard_plan(state)) is (missing_side is None)
