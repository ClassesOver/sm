"""批内原始 CSV 复用：真实解析、内容绑定、可变结果隔离与授权边界。"""

import hashlib
from types import SimpleNamespace

import polars as pl
import pytest

from smart_reporting.reporting.workflow.runtime import standard_supplemental as standard
from smart_reporting.reporting.workflow.runtime import standard_supplemental_input as inputs


def _tracking_cache(monkeypatch):
    original = inputs.read_analysis_csv
    calls = []

    def parse(content):
        calls.append(content)
        return original(content)

    monkeypatch.setattr(inputs, 'read_analysis_csv', parse)
    return inputs, inputs.BatchAnalysisInputCache(), calls


def test_repeated_content_is_parsed_once_and_preserves_raw_values(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    content = b'group,amount\n001,02\n'

    first = cache.read(content)
    second = cache.read(bytes(bytearray(content)))

    assert first.to_dicts() == [{'group': '001', 'amount': '02'}]
    assert second.to_dicts() == [{'group': '001', 'amount': '02'}]
    assert calls == [content]


def test_changed_content_never_reuses_another_input_frame(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    first = b'group,amount\nA,10\n'
    changed = b'group,amount\nA,20\n'

    assert cache.read(first).to_dicts() == [{'group': 'A', 'amount': '10'}]
    assert cache.read(changed).to_dicts() == [{'group': 'A', 'amount': '20'}]
    assert cache.read(first).to_dicts() == [{'group': 'A', 'amount': '10'}]
    assert calls == [first, changed]


def test_new_batch_has_no_previous_batch_cache(monkeypatch):
    module, cache, calls = _tracking_cache(monkeypatch)
    content = b'group,amount\nA,10\n'

    cache.read(content)
    second = module.BatchAnalysisInputCache().read(content)

    assert second.to_dicts() == [{'group': 'A', 'amount': '10'}]
    assert calls == [content, content]


def test_returned_frame_mutation_never_changes_cached_raw_frame(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    content = b'group,amount\nA,10\n'
    first = cache.read(content)

    first.replace_column(1, pl.Series('amount', ['999']))
    first.drop_in_place('group')

    assert cache.read(content).to_dicts() == [{'group': 'A', 'amount': '10'}]
    assert calls == [content]


def test_failed_csv_parse_is_never_cached(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    invalid = b'group,amount\nA,1,2\n'

    for _ in range(2):
        with pytest.raises(pl.exceptions.PolarsError):
            cache.read(invalid)

    assert calls == [invalid, invalid]


def test_cache_byte_budget_includes_frame_but_never_blocks_read(monkeypatch):
    module, cache, calls = _tracking_cache(monkeypatch)
    content = b'group,amount\nA,10\n'
    monkeypatch.setattr(module, 'MAX_BATCH_INPUT_CACHE_BYTES', len(content))

    for _ in range(2):
        assert cache.read(content).to_dicts() == [{'group': 'A', 'amount': '10'}]

    assert calls == [content, content]


def test_cache_entry_budget_preserves_first_input_and_does_not_block_later_inputs(monkeypatch):
    module, cache, calls = _tracking_cache(monkeypatch)
    monkeypatch.setattr(module, 'MAX_BATCH_INPUT_CACHE_ENTRIES', 1)
    first = b'group,amount\nA,10\n'
    second = b'group,amount\nB,20\n'

    cache.read(first)
    assert cache.read(second).to_dicts() == [{'group': 'B', 'amount': '20'}]
    assert cache.read(first).to_dicts() == [{'group': 'A', 'amount': '10'}]
    assert cache.read(second).to_dicts() == [{'group': 'B', 'amount': '20'}]

    assert calls == [first, second, second]


def _request(scope, total):
    return standard.StandardSupplementalRequest(
        operation='group_summary', datasetId='data', outputName='summary',
        measureField='amount', measureUnit='元', dimensionField='group', periodField='period',
        periodGranularity='month', currentPeriods=('2025-01',), parentTotal=total, scope=scope,
    )


def _run(cache, content, request, *, fields=('period', 'group', 'region', 'amount')):
    return standard.run_standard_supplemental(
        analysis_id='analysis_001', dataset_ids=('data',), authorized_fields=fields,
        csv_content=content, request=request, _input_cache=cache,
    )


def test_standard_requests_share_raw_parse_but_keep_scope_and_authorization_independent(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    content = b'period,group,region,amount\n2025-01,A,east,10\n2025-01,B,west,20\n'

    east = _run(cache, content, _request({'region': 'east'}, 10))
    west = _run(cache, content, _request({'region': 'west'}, 20))

    assert east['findings'][0]['rows'] == [['A', 10, 1, 1]]
    assert west['findings'][0]['rows'] == [['B', 20, 1, 1]]
    with pytest.raises(ValueError, match='未授权字段'):
        _run(cache, content, _request({'region': 'west'}, 20), fields=('period', 'group', 'region'))
    foreign = _request({'region': 'west'}, 20).model_copy(update={'dataset_id': 'foreign'})
    with pytest.raises(ValueError, match='未授权 dataset'):
        _run(cache, content, foreign)
    assert calls == [content]


def test_population_proof_shares_raw_parse_but_independently_recomputes_findings(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    content = b'period,group,region,amount\n2025-01,A,east,10\n2025-01,B,west,20\n'
    sha = hashlib.sha256(content).hexdigest()
    request = _request({'region': 'east'}, 10)
    finding = _run(cache, content, request)['findings'][0]
    parent = SimpleNamespace(
        dataset_sha256=sha, dataset_id='data', field='amount', period_field='period',
        period_granularity='month', unit='元', scope={'region': 'east'}, aggregation='sum',
        period_aggregation='sum', cumulative_policy=None, fact_id='parent',
        period_values=(SimpleNamespace(period='2025-01', value=10),),
    )

    proof = standard.build_standard_population_proof(
        csv_content=content, dataset_sha256=sha, request=request, parent_fact=parent,
        finding=finding, _input_cache=cache,
    )

    assert proof['members'] == ['A']
    assert proof['completePopulation'] is True
    altered = {**finding, 'rows': [['A', 11, 1, 1]]}
    assert standard.build_standard_population_proof(
        csv_content=content, dataset_sha256=sha, request=request, parent_fact=parent,
        finding=altered, _input_cache=cache,
    ) is None
    assert calls == [content]


def test_baseline_and_current_content_are_cached_separately(monkeypatch):
    _, cache, calls = _tracking_cache(monkeypatch)
    current = b'period,group,amount\n2025-02,A,30\n'
    baseline = b'period,group,amount\n2025-01,A,10\n'
    request = standard.StandardSupplementalRequest(
        operation='period_comparison', datasetId='current', baselineDatasetId='baseline',
        outputName='comparison', measureField='amount', dimensionField='group', periodField='period',
        periodGranularity='month', currentPeriods=('2025-02',), baselinePeriods=('2025-01',),
        parentTotal=30, baselineParentTotal=10,
    )

    for _ in range(2):
        result = standard.run_standard_supplemental(
            analysis_id='analysis_001', dataset_ids=('current', 'baseline'),
            authorized_fields=('period', 'group', 'amount'), csv_content=current, request=request,
            baseline_csv_content=baseline, baseline_authorized_fields=('period', 'group', 'amount'),
            _input_cache=cache,
        )
        assert result['findings'][0]['rows'] == [['A', 30, 10, 20, 2, 1, 1]]
        assert all(check['passed'] for check in result['reconciliations'])

    assert calls == [current, baseline]


@pytest.mark.anyio
async def test_runtime_callback_reuses_one_raw_parse(monkeypatch):
    from smart_reporting.reporting.tests.test_standard_supplemental_artifact import (
        test_runtime_standard_callback_signs_evidence_without_script as run_callback,
    )

    _, _, calls = _tracking_cache(monkeypatch)
    original = standard.read_analysis_csv
    legacy_calls = []

    def legacy_parse(content):
        legacy_calls.append(content)
        return original(content)

    monkeypatch.setattr(standard, 'read_analysis_csv', legacy_parse)

    await run_callback(monkeypatch, 'batch')

    assert len(calls) + len(legacy_calls) == 1, {
        'cached_parses': len(calls), 'legacy_parses': len(legacy_calls),
    }
