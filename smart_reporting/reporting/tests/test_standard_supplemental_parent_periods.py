"""父指标的期间工作量独立于维度数，且仅在单次枚举内复用。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.workflow.runtime import standard_supplemental as module


def _parent(index=1, periods=('2026-01', '2026-02'), reads=None):
    class Parent(SimpleNamespace):
        @property
        def period_values(self):
            if reads is not None:
                reads['period_values'] += 1
            return self.values

    return Parent(
        dataset_id='data', fact_id=f'fact-{index:016x}', field=f'amount{index}',
        aggregation='sum', period_aggregation='sum', cumulative_policy=None,
        period_field='period', values=tuple(SimpleNamespace(period=p, value=1) for p in periods),
        period_granularity='month', period_roles=('current',), scope={},
        display_name='金额', unit='元', field_ref=None,
    )


def test_parent_period_work_does_not_scale_with_dimensions(monkeypatch):
    work = {'period_key': 0, 'comparison_key': 0, 'period_values': 0}
    original_key = module.metric_period_key
    original_comparison = module.metric_comparison_period_key

    def count_key(*args, **kwargs):
        work['period_key'] += 1
        return original_key(*args, **kwargs)

    def count_comparison(*args, **kwargs):
        work['comparison_key'] += 1
        return original_comparison(*args, **kwargs)

    monkeypatch.setattr(module, 'metric_period_key', count_key)
    monkeypatch.setattr(module, 'metric_comparison_period_key', count_comparison)
    periods = tuple(f'{year}-{month:02d}' for year in (2025, 2026) for month in range(1, 13))
    parents = tuple(_parent(index, periods, work) for index in range(10))
    datasets = [{'datasetId': 'data', 'columns': [
        'period', *(f'axis{i}' for i in range(64)), *(p.field for p in parents),
    ]}]

    candidates = module.standard_computation_candidates(
        SimpleNamespace(metrics=parents, derived_metrics=()), datasets,
    )

    assert candidates
    assert work == {'period_key': 720, 'comparison_key': 240, 'period_values': 30}


@pytest.mark.parametrize('change', ['facts', 'window'])
def test_parent_periods_are_recomputed_on_each_invocation(monkeypatch, change):
    parent = _parent(periods=('2026-01', '2026-02', '2026-03'))
    facts = SimpleNamespace(metrics=(parent,), derived_metrics=())
    datasets = [{'datasetId': 'data', 'columns': ['period', 'group', parent.field]}]
    calls = []
    original = module.metric_comparison_period_key

    def count_comparison(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(module, 'metric_comparison_period_key', count_comparison)
    before = module.standard_computation_candidates(facts, datasets, ('2026-02',))
    calls.clear()
    if change == 'facts':
        parent.values = tuple(SimpleNamespace(period=p, value=1) for p in ('2026-02', '2026-03'))
        requested = ('2026-02',)
    else:
        requested = ('2026-03',)

    after = module.standard_computation_candidates(facts, datasets, requested)

    assert calls == list(requested)
    assert after != before
    comparisons = [c['standardComputation'] for c in after
                   if c['standardComputation']['operation'] == 'group_period_comparison']
    if change == 'facts':
        assert comparisons == []
    else:
        assert len(comparisons) == 1
        assert comparisons[0]['currentPeriods'] == ['2026-03']
        assert comparisons[0]['baselinePeriods'] == ['2026-02']


def test_candidate_content_ids_and_order_match_preoptimization_snapshot():
    parent = _parent()
    parent.field = 'amount'
    candidates = module.standard_computation_candidates(
        SimpleNamespace(metrics=(parent,), derived_metrics=()),
        [{'datasetId': 'data', 'columns': ['period', 'group', 'amount']}],
    )
    # 优化前真实返回值的完整快照，覆盖顺序、ID、正文和输出列。
    assert candidates == [
        {
            'candidateId': 'std-c02d2dd9443b7677', 'datasetId': 'data',
            'fields': ['amount', 'group', 'period'], 'label': '金额',
            'standardComputation': {
                'operation': 'group_summary', 'measureField': 'amount',
                'dimensionField': 'group', 'periodField': 'period',
                'currentPeriods': ['2026-01', '2026-02'], 'baselinePeriods': [],
                'parentFactId': 'fact-0000000000000001',
            },
            'outputColumns': ['group', 'value', 'rank', 'share'],
        },
        {
            'candidateId': 'std-230ccd8b11bab8da', 'datasetId': 'data',
            'fields': ['amount', 'group', 'period'], 'label': '金额',
            'standardComputation': {
                'operation': 'group_period_series', 'measureField': 'amount',
                'dimensionField': 'group', 'periodField': 'period',
                'currentPeriods': ['2026-01', '2026-02'], 'baselinePeriods': [],
                'includePeriodChange': True, 'parentFactId': 'fact-0000000000000001',
            },
            'outputColumns': [
                'period', 'group', 'value', 'rank', 'share', 'previous', 'change', 'changeRate',
            ],
        },
        {
            'candidateId': 'std-80f250ad5710f326', 'datasetId': 'data',
            'fields': ['amount', 'group', 'period'], 'label': '金额',
            'standardComputation': {
                'operation': 'group_period_comparison', 'measureField': 'amount',
                'dimensionField': 'group', 'periodField': 'period',
                'currentPeriods': ['2026-01', '2026-02'], 'baselinePeriods': ['2026-01'],
                'baselineMethod': 'previous_period', 'parentFactId': 'fact-0000000000000001',
            },
            'outputColumns': [
                'period', 'group', 'current', 'baseline', 'change', 'changeRate',
                'contribution', 'rank', 'baselineTotal', 'totalChange',
            ],
        },
    ]
