"""全院逐月同比无需借用业务维度，仍须冻结身份与完整期间校验。"""

import pytest
from pydantic import ValidationError

from smart_reporting.reporting.tests.test_standard_supplemental_period_comparison import (
    _compute,
    _request,
    _state,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisCodingRequirement,
    AnalysisItemWorkflow,
)
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalSpec,
    run_standard_supplemental,
    standard_computation_catalog,
)


def test_ungrouped_monthly_yoy_sums_each_month_and_ranks_without_synthetic_dimension():
    payload, finding, rows = _compute(dimensionField=None)
    assert finding['columns'] == [
        'period', 'current', 'baseline', 'change', 'changeRate', 'contribution', 'rank',
    ]
    assert finding['rowKeyColumns'] == ['period']
    assert [(r['period'], r['current'], r['baseline'], r['change'], r['rank']) for r in rows] == [
        ('2025-01', 110, 70, 40, 1), ('2025-02', 70, 80, -10, 2),
    ]
    assert [r['changeRate'] for r in rows] == pytest.approx([4 / 7, -1 / 8])
    assert [r['contribution'] for r in rows] == pytest.approx([4 / 3, -1 / 3])
    assert finding['columnMeta']['baseline']['periodsByRowPeriod']['2025-01'] == ['2024-01']
    assert all(check['passed'] for check in payload['reconciliations'])
    assert payload['warnings'] == []


@pytest.mark.parametrize('with_dimension', [False, True])
def test_ungrouped_candidate_routes_from_frozen_facts_even_without_business_dimensions(with_dimension):
    state = _state()
    if not with_dimension:
        for dataset in state.instruction['datasets']:
            dataset['columns'].remove('department')
    catalog = standard_computation_catalog(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    candidates = [c for c in catalog['candidates']
                  if c['standardComputation']['operation'] == 'period_comparison'
                  and c['standardComputation'].get('dimensionField') is None]
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate['standardComputation']['groupByPeriod'] is True
    assert candidate['fields'] == ['income', 'period']
    assert candidate['outputColumns'] == [
        'period', 'current', 'baseline', 'change', 'changeRate', 'contribution', 'rank',
    ]
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']), 'standard_computation': None,
        'standard_candidate_id': candidate['candidateId'],
        'required_columns': tuple(candidate['outputColumns']),
    })
    requirement = AnalysisCodingRequirement.model_validate(requirement.model_dump(by_alias=True))
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.dimension_field is None
    assert selected.baseline_dataset_id == 'dataset_prior'
    assert selected.current_periods == ('2025-01', '2025-02')
    state.facts.metrics[1].dataset_sha256 = 'c' * 64
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_explicit_ungrouped_spec_validates_requirement_without_inventing_a_field():
    state = _state()
    spec = StandardSupplementalSpec(
        operation='period_comparison', dimensionField=None, groupByPeriod=True,
        measureField='income', periodField='period',
        currentPeriods=('2025-01', '2025-02'), baselinePeriods=('2024-01', '2024-02'),
        parentFactId=state.facts.metrics[0].fact_id,
        baselineParentFactId=state.facts.metrics[1].fact_id, baselineDatasetId='dataset_prior',
    )
    raw = state.decision.coding_requirements[0].model_dump(by_alias=True)
    raw.update(fields=['income', 'period'], standardCandidateId=None,
               standardComputation=spec.model_dump(by_alias=True))
    requirement = AnalysisCodingRequirement.model_validate(raw)
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == (spec,)


@pytest.mark.parametrize('updates', [
    {'groupByPeriod': False, 'parentPeriodTotals': (), 'baselinePeriodTotals': ()},
    {'secondaryDimensionField': 'other'},
    {'operation': 'group_summary', 'baselinePeriods': (), 'baselineDatasetId': None,
     'baselineParentTotal': None, 'groupByPeriod': False,
     'parentPeriodTotals': (), 'baselinePeriodTotals': ()},
])
def test_missing_dimension_is_rejected_outside_ungrouped_period_comparison(updates):
    with pytest.raises(ValidationError):
        _request(dimensionField=None, **updates)


def test_ungrouped_missing_month_keeps_null_instead_of_borrowing_or_zero_filling():
    payload, _, rows = _compute(
        current=chr(10).join(['period,amount', '2025-01,110']).encode(),
        dimensionField=None, parentTotal=110, parentPeriodTotals=(0, 110),
    )
    february = next(row for row in rows if row['period'] == '2025-02')
    assert february['current'] is None
    assert february['baseline'] == 80
    assert february['change'] is None
    assert february['contribution'] is None
    assert payload['warnings']


@pytest.mark.parametrize('denominator,expected', [('signed', -3), ('absolute', 3)])
def test_ungrouped_zero_and_negative_baselines(denominator, expected):
    payload, _, rows = _compute(
        current=chr(10).join(['period,amount', '2025-01,20', '2025-02,10']).encode(),
        baseline=chr(10).join(['period,amount', '2024-01,-10', '2024-02,0']).encode(),
        dimensionField=None, parentTotal=30, parentPeriodTotals=(10, 20),
        baselineParentTotal=-10, baselinePeriodTotals=(-10, 0),
        changeRateDenominator=denominator,
    )
    by_period = {row['period']: row for row in rows}
    assert by_period['2025-01']['changeRate'] == expected
    assert by_period['2025-02']['changeRate'] is None
    assert all(check['passed'] for check in payload['reconciliations'])
    assert payload['warnings']


def test_ungrouped_comparison_still_requires_authorized_baseline_fields():
    with pytest.raises(ValueError, match='未授权字段'):
        run_standard_supplemental(
            analysis_id='analysis_006', dataset_ids=('current', 'prior'),
            authorized_fields=('period', 'amount'),
            csv_content=b'period,amount', baseline_csv_content=b'period,amount',
            baseline_authorized_fields=('period',), request=_request(dimensionField=None),
        )


def test_ungrouped_binding_remains_discoverable_when_candidates_are_truncated(monkeypatch):
    from smart_reporting.reporting.workflow.runtime import standard_supplemental

    state = _state()
    for dataset in state.instruction['datasets']:
        dataset['columns'].remove('department')
    monkeypatch.setattr(standard_supplemental, 'STANDARD_CANDIDATE_LIMIT', 0)
    catalog = standard_computation_catalog(
        state.facts, state.instruction['datasets'], state.instruction['currentAnalysis']['periods'],
    )
    assert catalog['candidates'] == []
    source = next(item for item in catalog['groupingSources']['items']
                  if item['datasetId'] == state.facts.metrics[0].dataset_id)
    assert source['dimensionFields'] == []
    assert source['supportedOperations'] == ['period_comparison']
    binding, = source['comparisonBindings']
    assert binding['baselineDatasetId'] == 'dataset_prior'
    assert binding['baselinePeriods'] == ['2024-01', '2024-02']
    assert binding['dimensionFields'] == []


def test_ungrouped_month_missing_on_both_sides_remains_visible_and_null():
    payload, _, rows = _compute(
        current=chr(10).join(['period,amount', '2025-01,110']).encode(),
        baseline=chr(10).join(['period,amount', '2024-01,70']).encode(),
        dimensionField=None, parentTotal=110, parentPeriodTotals=(0, 110),
        baselineParentTotal=70, baselinePeriodTotals=(70, 0),
    )
    february = next(row for row in rows if row['period'] == '2025-02')
    assert all(february[field] is None for field in (
        'current', 'baseline', 'change', 'changeRate', 'contribution',
    ))
    assert payload['warnings']


@pytest.mark.parametrize('period_field', ['period', 'current'])
def test_ungrouped_same_csv_comparison_preserves_period_alias_and_source_scope(period_field):
    content = chr(10).join([
        f'{period_field},company,amount',
        '2025-01,selected,110', '2025-02,selected,70',
        '2024-01,selected,70', '2024-02,selected,80',
        '2025-01,foreign,999', '2024-01,foreign,999',
    ]).encode()
    result = run_standard_supplemental(
        analysis_id='analysis_006', dataset_ids=('current',),
        authorized_fields=(period_field, 'company', 'amount'), csv_content=content,
        request=_request(dimensionField=None, baselineDatasetId=None,
                         periodField=period_field, scope={'company': 'selected'}),
    )
    finding, = result['findings']
    assert finding['columns'][0] == ('period_current' if period_field == 'current' else 'period')
    assert finding['rowKeyColumns'] == [finding['columns'][0]]
    assert finding['rows'] == [
        ['2025-01', 110, 70, 40, 4 / 7, 4 / 3, 1],
        ['2025-02', 70, 80, -10, -1 / 8, -1 / 3, 2],
    ]
    assert finding['scope'] == {'company': 'selected'}
    assert result['warnings'] == []
    assert all(check['passed'] for check in result['reconciliations'])
