"""标准补证热路径的线性工作量契约，不依赖墙钟阈值。"""

import json
import math
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.workflow.runtime import standard_supplemental as module


def test_disabled_marginals_do_not_compute_unrequested_overflowing_totals():
    # 单元与总体均可表示；未请求的边际可能溢出，不能因此破坏旧输出。
    rows = [
        {'dimension': 'A', 'secondary_dimension': 'X', 'value': 1e308},
        {'dimension': 'B', 'secondary_dimension': 'X', 'value': -1e308},
        {'dimension': 'A', 'secondary_dimension': 'Y', 'value': 1e308},
        {'dimension': 'B', 'secondary_dimension': 'Y', 'value': -1e308},
    ]
    result, total = module._cross_group_rows(rows, False, [])
    assert total == 0
    assert len(result) == 4
    assert all(len(row) == 5 and row[-1] is None for row in result)
    assert {row[0] for row in result} == {'A', 'B'}


@pytest.mark.parametrize('operation', [
    'group_period_series', 'group_period_comparison', 'cross_group_summary',
])
def test_period_grouping_reads_each_source_period_only_constant_times(monkeypatch, operation):
    # 回归：按每个期间重新扫描全部行，会把期间读取从 O(N) 放大为 O(P*N)。
    periods = tuple(f'2025-{month:02d}' for month in range(1, 13))
    source_periods = ('2024-12', *periods) if operation == 'group_period_comparison' else periods
    csv = 'period,group,kind,amount\n' + ''.join(
        f'{period},{group},{kind},{value}\n'
        for period in source_periods
        for group, kind, value in (('A', 'X', 1), ('A', 'Y', 2), ('B', 'X', 3), ('B', 'Y', 4))
    )
    reads = {'period': 0, 'rows': 0}

    class CountingRow(dict):
        def __getitem__(self, key):
            if key == 'period':
                reads['period'] += 1
            return super().__getitem__(key)

        def get(self, key, default=None):
            if key == 'period':
                reads['period'] += 1
            return super().get(key, default)

    original_read_rows = module._read_rows

    def count_real_rows(*args, **kwargs):
        rows, warnings = original_read_rows(*args, **kwargs)
        reads['rows'] += len(rows)
        return [CountingRow(row) for row in rows], warnings

    monkeypatch.setattr(module, '_read_rows', count_real_rows)
    options = {
        'currentPeriods': periods, 'parentTotal': 120, 'parentPeriodTotals': (10,) * 12,
    }
    if operation == 'group_period_series':
        options['includePeriodChange'] = True
    elif operation == 'group_period_comparison':
        options.update(baselineMethod='mean', baselinePeriods=('2024-12',), baselinePeriodTotals=(10,))
    else:
        options.update(secondaryDimensionField='kind', groupByPeriod=True, includeMarginalShares=True)
    request = module.StandardSupplementalRequest(
        operation=operation, datasetId='data', outputName='result', measureField='amount',
        dimensionField='group', periodField='period', periodGranularity='month', **options,
    )

    payload = module.run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',),
        authorized_fields=('period', 'group', 'kind', 'amount'), csv_content=csv.encode(), request=request,
    )

    finding = payload['findings'][0]
    result = [dict(zip(finding['columns'], row, strict=True)) for row in finding['rows']]
    assert all(check['passed'] for check in payload['reconciliations'])
    if operation == 'group_period_series':
        assert len(result) == 24
        february_b = next(row for row in result if row['period'] == '2025-02' and row['group'] == 'B')
        assert (february_b['value'], february_b['previous'], february_b['change']) == (7, 7, 0)
    elif operation == 'group_period_comparison':
        assert len(result) == 24
        assert all((row['baselineTotal'], row['totalChange'], row['change']) == (10, 0, 0) for row in result)
        assert {row['group']: row['baseline'] for row in result} == {'A': 3, 'B': 7}
    else:
        assert len(result) == 48
        january_by = next(row for row in result
                          if row['period'] == '2025-01' and row['group'] == 'B' and row['kind'] == 'Y')
        assert (january_by['value'], january_by['primaryTotal'], january_by['secondaryTotal']) == (4, 7, 6)
        assert january_by['primaryShare'] == pytest.approx(4 / 7)
        assert january_by['secondaryShare'] == pytest.approx(2 / 3)
    assert reads['period'] <= 3 * reads['rows'], reads


@pytest.mark.parametrize('shared_dimension', ['primary', 'secondary'])
def test_cross_marginal_totals_sum_each_value_only_constant_times(monkeypatch, shared_dimension):
    # 回归：同一个边际分母不能在其每个交叉单元中重新 fsum 整个成员列表。
    rows = [
        {'dimension': 'shared' if shared_dimension == 'primary' else f'group-{index:02d}',
         'secondary_dimension': f'kind-{index:02d}' if shared_dimension == 'primary' else 'shared',
         'value': 1.0}
        for index in range(64)
    ]
    work = {'summed_values': 0}
    original_fsum = math.fsum

    def count_real_fsum(values):
        values = tuple(values)
        work['summed_values'] += len(values)
        return original_fsum(values)

    monkeypatch.setattr(module.math, 'fsum', count_real_fsum)
    warnings = []

    result, total = module._cross_group_rows(rows, True, warnings)

    assert total == 64
    assert warnings == []
    assert len(result) == 64
    for row in result:
        assert row[2] == 1
        assert row[4] == 1 / 64
        if shared_dimension == 'primary':
            assert row[5:] == [64, 1 / 64, 1, 1]
        else:
            assert row[5:] == [1, 1, 64, 1 / 64]
    assert work['summed_values'] <= 4 * len(rows), work


def test_candidate_budget_does_not_rank_every_oversized_tail_entry(monkeypatch):
    # 回归：预算余量不够时逐项 min + pop 排空余桶，会退化为 O(K²)。
    dimensions = tuple(f'axis{index}' for index in range(16))
    measures = tuple(f'amount{index}' for index in range(8))
    periods = tuple(SimpleNamespace(period=f'{year}-{month:02d}', value=1)
                    for year in (2025, 2026) for month in range(1, 13))
    metrics = tuple(SimpleNamespace(
        dataset_id='data', fact_id=f'fact-{index:016x}', field=measure,
        aggregation='sum', period_aggregation='sum', cumulative_policy=None,
        period_field='period', period_values=periods, period_granularity='month',
        period_roles=('current',), scope={}, display_name=None, unit='元', field_ref=None,
    ) for index, measure in enumerate(measures))
    datasets = [{'datasetId': 'data', 'columns': ['period', *dimensions, *measures]}]
    work = {'built': 0, 'ranked': 0}
    original_output_columns = module.standard_output_columns
    original_min = min

    def count_real_columns(spec):
        work['built'] += 1
        return original_output_columns(spec)

    def count_real_min(values, *args, **kwargs):
        key = kwargs.get('key')
        if key is not None:
            def count_key(value):
                work['ranked'] += 1
                return key(value)
            kwargs['key'] = count_key
        return original_min(values, *args, **kwargs)

    monkeypatch.setattr(module, 'standard_output_columns', count_real_columns)
    monkeypatch.setattr(module, 'min', count_real_min, raising=False)

    candidates = module.standard_computation_candidates(
        SimpleNamespace(metrics=metrics, derived_metrics=()), datasets,
    )

    assert 0 < len(candidates) <= 40
    assert sum(len(json.dumps(item, ensure_ascii=False).encode()) for item in candidates) <= 24_000
    assert {item['standardComputation']['measureField'] for item in candidates} == set(measures)
    advertised_dimensions = {
        field
        for item in candidates
        for field in (item['standardComputation']['dimensionField'],
                      item['standardComputation'].get('secondaryDimensionField'))
        if field is not None
    }
    assert advertised_dimensions == set(dimensions)
    assert work['ranked'] <= 40 * work['built'], work
