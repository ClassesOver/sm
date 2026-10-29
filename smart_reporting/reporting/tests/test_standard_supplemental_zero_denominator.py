"""冻结总分母为零只使总体比率未知，不拒绝已登记公式的分组复算。"""

import pytest

from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
    build_deterministic_analysis_bundle,
)
from smart_reporting.reporting.tests.test_deterministic_analysis import analysis, context, semantic
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.trace.fact_index import assign_fact_ids
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalRequest,
    StandardSupplementalSpec,
    frozen_period_total,
    run_standard_supplemental,
    standard_computation_candidates,
)


def _registered_zero_state(*, scale=1, group_zero=False, by_period=False):
    fields = ('month', 'department', 'income', 'budget')
    budget = 10 / scale
    rows = f'2026-01,A,20,{budget}\n2026-01,B,10,{-budget}\n'
    if group_zero:
        rows += '2026-01,C,5,0\n'
    csv = ('month,department,income,budget\n' + rows).encode()
    dataset_context = context('dataset_001', fields=fields, sha256='a' * 64, semantics=(
        semantic('income', unit='元'), semantic('budget', unit='万元' if scale == 10000 else '元'),
    )).model_copy(update={'period_values': ('2026-01',)})
    profile = (
        {'code': 'income', 'aggregation': 'sum', 'fieldRef': semantic('income')['fieldRef']},
        {'code': 'budget', 'aggregation': 'sum', 'fieldRef': semantic('budget')['fieldRef']},
        {'code': 'completion', 'aggregation': 'ratio',
         'numeratorMetric': 'income', 'denominatorMetric': 'budget'},
    )
    bundle = assign_fact_ids(build_deterministic_analysis_bundle(
        analysis(fields=('income', 'budget')).model_copy(update={'periods': ('2026-01',)}),
        (('dataset_001', csv, dataset_context, ('current',)),), profile_metrics=profile,
    ))
    numerator = next(item for item in bundle.metrics if item.field == 'income')
    denominator = next(item for item in bundle.metrics if item.field == 'budget')
    ratio, = bundle.derived_metrics
    assert ratio.denominator == 0
    assert ratio.value is None and ratio.percentage is None
    assert ratio.difference == numerator.total
    spec = StandardSupplementalSpec(
        operation='group_ratio', measureField='income', denominatorField='budget',
        dimensionField='department', periodField='month', currentPeriods=('2026-01',),
        parentFactId=numerator.fact_id, denominatorParentFactId=denominator.fact_id,
        ratioFactId=ratio.fact_id, groupByPeriod=by_period,
    )
    state = _standard_analysis_state()
    state.facts = bundle
    state.instruction['datasets'][0]['columns'] = list(fields)
    state.instruction['currentAnalysis']['periods'] = ['2026-01']
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': fields, 'standard_computation': spec,
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    return state, spec, csv, numerator, denominator, ratio


def _ratio_candidates(state):
    return [item for item in standard_computation_candidates(
        state.facts, state.instruction['datasets'], ('2026-01',),
    ) if item['standardComputation']['operation'] == 'group_ratio']


@pytest.mark.parametrize('by_period', [False, True])
@pytest.mark.parametrize('scale', [1, 10000])
@pytest.mark.parametrize('group_zero', [False, True])
def test_registered_zero_total_denominator_routes_and_reconciles_group_ratios(by_period, scale, group_zero):
    state, spec, csv, numerator, denominator, ratio = _registered_zero_state(
        by_period=by_period, scale=scale, group_zero=group_zero,
    )
    original_facts = state.facts.model_dump()
    candidates = _ratio_candidates(state)
    assert {bool(item['standardComputation'].get('groupByPeriod')) for item in candidates} == {False, True}
    assert AnalysisItemWorkflow._standard_plan(state) == (spec,)
    candidate = next(item for item in candidates
                     if bool(item['standardComputation'].get('groupByPeriod')) == by_period)
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected == spec
    request = StandardSupplementalRequest.model_validate({
        **selected.model_dump(mode='json', by_alias=True, exclude_none=True,
                              exclude={'parent_fact_id', 'denominator_parent_fact_id'}),
        'datasetId': 'dataset_001', 'outputName': 'result', 'measureUnit': '元',
        'denominatorScale': scale, 'parentTotal': numerator.total,
        'denominatorParentTotal': denominator.total,
        **({'parentPeriodTotals': (frozen_period_total(numerator, ('2026-01',)),),
            'denominatorPeriodTotals': (frozen_period_total(denominator, ('2026-01',)),)} if by_period else {}),
    })
    payload = run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('dataset_001',), authorized_fields=requirement.fields,
        csv_content=csv, request=request,
    )
    table = payload['findings'][0]
    rows = [dict(zip(table['columns'], row, strict=True)) for row in table['rows']]
    by_group = {row['department']: row for row in rows}
    assert by_group['A']['ratio'] == 2
    assert by_group['B']['ratio'] == -1
    if group_zero:
        assert by_group['C']['ratio'] is None
        assert payload['warnings']
    assert all(check['passed'] for check in payload['reconciliations'])
    assert state.facts.model_dump() == original_facts
    assert ratio.percentage is None and ratio.value is None


@pytest.mark.parametrize('fault', [
    'unregistered', 'scope', 'operand_order', 'scale', 'difference',
    'nonzero_denominator', 'missing_denominator', 'dataset', 'period', 'different_unit',
])
def test_missing_percentage_never_bypasses_registered_formula_boundaries(fault):
    state, _, _, _, denominator, ratio = _registered_zero_state()
    updates = {
        'scope': {'scope': {'site': 'North'}},
        'operand_order': {'input_fact_ids': tuple(reversed(ratio.input_fact_ids))},
        'scale': {'denominator_scale': 10000},
        'difference': {'difference': None},
        'nonzero_denominator': {'denominator': 1},
        'missing_denominator': {'denominator': None},
        'dataset': {'dataset_ids': ('foreign',)},
        'period': {'period_granularity': 'day'},
    }
    if fault == 'different_unit':
        state.facts = state.facts.model_copy(update={'metrics': tuple(
            item.model_copy(update={'unit': '人次'}) if item.fact_id == denominator.fact_id else item
            for item in state.facts.metrics
        )})
    else:
        state.facts = state.facts.model_copy(update={'derived_metrics': (
            () if fault == 'unregistered' else (ratio.model_copy(update=updates[fault]),)
        )})
    assert AnalysisItemWorkflow._standard_plan(state) == ()
    if fault != 'operand_order':
        assert _ratio_candidates(state) == []


@pytest.mark.parametrize('by_period', [False, True])
def test_explicit_registered_zero_denominator_plan_is_supported(by_period):
    state, spec, *_ = _registered_zero_state(by_period=by_period)
    assert AnalysisItemWorkflow._standard_plan(state) == (spec,)
