"""批次原始输入复用及事实定位：输出等价、历史指针和生命周期边界。"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.hospital_operation import deterministic_analysis as deterministic
from smart_reporting.reporting.trace import fact_index, table_builder
from smart_reporting.reporting.workflow.runtime import standard_supplemental_input as inputs

from .test_deterministic_analysis import analysis, context, semantic
from .test_trace_fact_service import _bundle


def _track_reads(monkeypatch):
    calls = []
    original = deterministic.read_analysis_csv

    def read(raw):
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr(deterministic, 'read_analysis_csv', read)
    monkeypatch.setattr(inputs, 'read_analysis_csv', read)
    return calls


def _build(index, raw, *, cache=None, scope=None, role='current'):
    return deterministic.build_deterministic_analysis_bundle(
        analysis().model_copy(update={'analysis_id': f'analysis_{index:03}'}),
        (('current', raw, context('current', sha256=hashlib.sha256(raw).hexdigest(),
                                 semantics=(semantic('amount', scope=scope, unit='元'),)), (role,)),),
        profile_metrics=({'code': 'income', 'fieldRef': 'dynamic_source.dynamic_db.dynamic_table.amount',
                          'kind': 'amount', 'aggregation': 'sum'},),
        _input_cache=cache,
    )


def test_shared_csv_is_parsed_once_with_identical_fact_outputs(monkeypatch):
    calls = _track_reads(monkeypatch)
    raw = b'month,department,amount\n2025-01,001,10\n2025-02,002,-5\n2025-03,001,\n'
    expected = [_build(i, raw).model_dump(mode='json', by_alias=True) for i in range(1, 7)]
    assert len(calls) == 6
    calls.clear()
    cache = inputs.BatchAnalysisInputCache()
    actual = [_build(i, raw, cache=cache).model_dump(mode='json', by_alias=True) for i in range(1, 7)]
    assert actual == expected
    assert calls == [raw]
    assert cache.read(raw)['department'].to_list() == ['001', '002', '001']


def test_shared_parse_keeps_scope_role_and_changed_content_independent(monkeypatch):
    calls = _track_reads(monkeypatch)
    raw = b'month,department,amount\n2025-01,A,10\n2025-01,B,20\n'
    changed = raw.replace(b'B,20', b'B,30')
    cases = [(raw, {'department': 'A'}, 'current'), (raw, {'department': 'B'}, 'current'),
             (raw, {'department': 'A'}, 'yoy'), (changed, {'department': 'B'}, 'current')]
    expected = [_build(i, source, scope=scope, role=role)
                for i, (source, scope, role) in enumerate(cases, 1)]
    calls.clear()
    cache = inputs.BatchAnalysisInputCache()
    actual = [_build(i, source, scope=scope, role=role, cache=cache)
              for i, (source, scope, role) in enumerate(cases, 1)]
    assert actual == expected
    assert calls == [raw, changed]
    assert [bundle.metrics[0].total for bundle in actual] == [10, 20, 10, 30]


@pytest.mark.parametrize('limit', ['MAX_BATCH_INPUT_CACHE_BYTES', 'MAX_BATCH_INPUT_CACHE_ENTRIES'])
def test_fact_build_cache_budget_bypass_preserves_results(monkeypatch, limit):
    calls = _track_reads(monkeypatch)
    raw = b'month,department,amount\n2025-01,A,10\n'
    expected = _build(1, raw)
    calls.clear()
    monkeypatch.setattr(inputs, limit, 0)
    cache = inputs.BatchAnalysisInputCache()
    assert _build(1, raw, cache=cache) == expected
    assert _build(1, raw, cache=cache) == expected
    assert calls == [raw, raw]


def test_fact_build_new_batch_reparses_and_bad_csv_is_never_cached(monkeypatch):
    calls = _track_reads(monkeypatch)
    raw = b'month,department,amount\n2025-01,A,10\n'
    assert _build(1, raw, cache=inputs.BatchAnalysisInputCache()) == _build(
        1, raw, cache=inputs.BatchAnalysisInputCache())
    assert calls == [raw, raw]
    invalid = b'month,department,amount\n2025-01,A,10,extra\n'
    expected = _build(1, invalid)
    calls.clear()
    cache = inputs.BatchAnalysisInputCache()
    assert _build(1, invalid, cache=cache) == expected
    assert _build(1, invalid, cache=cache) == expected
    assert calls == [invalid, invalid]
    assert expected.warnings


def test_pointer_index_matches_old_lookup_for_all_arrays_and_legacy_ids():
    duplicate = 'fact-' + 'a' * 16
    bundle = SimpleNamespace(**{
        attribute: (SimpleNamespace(fact_id=f'fact-{index:016x}'),
                    SimpleNamespace(fact_id=duplicate), SimpleNamespace(fact_id=None))
        for index, attribute in enumerate(fact_index._BUNDLE_ATTRIBUTES.values())
    })
    pointers = fact_index.fact_pointer_index(bundle)
    for _, _, facts in fact_index.bundle_fact_arrays(bundle):
        for fact in facts:
            assert pointers.get(fact.fact_id) == fact_index.fact_pointer(bundle, fact.fact_id)
    assert pointers[duplicate] == '/metrics/1'
    assert pointers[None] == '/metrics/2'
    assert pointers.get('unknown') is None


def test_pointer_index_visits_each_fact_once():
    visits = []

    class Facts:
        def __iter__(self):
            for index in range(500):
                visits.append(index)
                yield SimpleNamespace(fact_id=f'fact-{index:016x}')

    bundle = SimpleNamespace(**{attribute: () for attribute in fact_index._BUNDLE_ATTRIBUTES.values()})
    bundle.metrics = Facts()
    pointers = fact_index.fact_pointer_index(bundle)
    assert len(pointers) == len(visits) == 500
    assert pointers['fact-00000000000001f3'] == '/metrics/499'


def test_production_tables_match_linear_lookup_reference(monkeypatch):
    bundle = _bundle()
    options = {'fact_file_resource_id': 'trf-' + '0' * 20}
    actual = table_builder.build_analysis_tables(bundle, **options)

    def old_lookup(current):
        return {fact.fact_id: fact_index.fact_pointer(current, fact.fact_id)
                for _, _, facts in fact_index.bundle_fact_arrays(current) for fact in facts}

    monkeypatch.setattr(table_builder, 'fact_pointer_index', old_lookup)
    assert table_builder.build_analysis_tables(bundle, **options) == actual


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('stale', [False, True])
async def test_runtime_fact_preparation_reuses_only_verified_input(monkeypatch, stale):
    from agno.run import RunContext

    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin
    from smart_reporting.reporting.workflow.runtime.base import (
        REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY,
    )

    raw = b'month,department,amount\n2025-01,001,10\n2025-02,002,-5\n2025-03,001,\n'
    digest = hashlib.sha256(raw).hexdigest()
    current = context('current', sha256=digest)
    plans = tuple(analysis().model_copy(update={'analysis_id': f'analysis_{i:03}',
                                              'dataset_ids': ('current',)}) for i in range(1, 7))
    metric = {'code': 'income', 'fieldRef': 'dynamic_source.dynamic_db.dynamic_table.amount',
              'kind': 'amount', 'aggregation': 'sum'}
    profile = SimpleNamespace(metrics=(SimpleNamespace(model_dump=lambda **_: metric),),
                              reconciliations=(), dimensions=(), effective_profile_hash='c' * 64)
    expected = {
        plan.analysis_id: deterministic.build_deterministic_analysis_bundle(
            plan, (('current', raw, current, ('current',)),),
            profile_metrics=(metric,), profile_hash=profile.effective_profile_hash,
        ).model_dump(mode='json', by_alias=True) for plan in plans
    }
    calls = _track_reads(monkeypatch)
    stored = {}

    async def write(thread_id, path, content):
        assert thread_id == 'thread-1'
        stored[path] = content
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    read = AsyncMock(return_value=raw.replace(b'002,-5', b'002,-6') if stale else raw)
    harness = SimpleNamespace(
        _state=lambda _: {REPORT_ANALYSIS_DATA_CONTEXT_STATE_KEY: [current.model_dump(by_alias=True)]},
        _profile=lambda _: profile,
        workspace_service=SimpleNamespace(read_limited_regular_file=read),
        _write_immutable_artifact=write, _apply_durable_command=AsyncMock(),
    )
    arguments = dict(run_context=RunContext(run_id='run-1', session_id='thread-1'),
                     thread_id='thread-1', report_run_id='run-1', revision=1,
                     detailed_plan=SimpleNamespace(analyses=plans),
                     dataset_handles=(SimpleNamespace(dataset_id='current', path='datasets/current.csv',
                                                      size=len(raw), sha256=digest,
                                                      period_roles=('current',)),))
    if stale:
        with pytest.raises(ReportingError) as caught:
            await RuntimeAnalysisMixin._prepare_deterministic_analysis_facts(harness, **arguments)
        assert caught.value.code == 'stale_dataset'
        assert not calls and not stored
        harness._apply_durable_command.assert_not_awaited()
    else:
        identities = await RuntimeAnalysisMixin._prepare_deterministic_analysis_facts(harness, **arguments)
        assert calls == [raw]
        assert set(identities) == set(expected)
        assert harness._apply_durable_command.await_count == 6
        for analysis_id, identity in identities.items():
            assert json.loads(stored[identity.path]) == expected[analysis_id]
    read.assert_awaited_once()
