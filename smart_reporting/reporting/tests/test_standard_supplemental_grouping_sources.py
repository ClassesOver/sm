"""紧凑来源索引覆盖有界候选目录没有列出的合法分组。"""
import json
from itertools import combinations
from types import SimpleNamespace

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.tests.test_standard_supplemental_routing import _bind_signed_scope
from smart_reporting.reporting.workflow.runtime import standard_supplemental as module
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    StandardSupplementalSpec,
)


def _catalog(state):
    build = getattr(module, 'standard_computation_catalog', None)
    assert callable(build), '需要独立于候选数量的 standard_computation_catalog 来源索引 API'
    return build(
        state.facts, state.instruction['datasets'],
        state.instruction['currentAnalysis'].get('periods', ()),
    )


def _sources(state):
    return _catalog(state)['groupingSources']['items']


def _select(state, source, dimensions, **overrides):
    spec = StandardSupplementalSpec(
        operation='cross_group_summary' if len(dimensions) == 2 else 'group_summary',
        measureField=source['measureField'], dimensionField=dimensions[0],
        secondaryDimensionField=dimensions[1] if len(dimensions) == 2 else None,
        periodField=source['periodField'], currentPeriods=source['currentPeriods'],
        parentFactId=source['parentFactId'], **overrides,
    )
    fields = (
        source['measureField'], source['periodField'], *dimensions,
        *source['projectedScopeFields'],
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'dataset_id': source['datasetId'], 'fields': tuple(fields),
        'standard_candidate_id': None, 'standard_computation': spec,
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == (spec,)
    return spec


def test_catalog_preserves_existing_candidate_order_identity_and_payload():
    state = _standard_analysis_state()
    before = module.standard_computation_candidates(state.facts, state.instruction['datasets'])
    catalog = _catalog(state)
    assert catalog['candidates'] == before
    # 改造前基础 fixture 的已登记身份与顺序；不能只比较新 API 与其 wrapper。
    assert [item['candidateId'] for item in catalog['candidates']] == [
        'std-d3f5f8023e450c8c', 'std-ef2ab640d5ad9a99',
    ]
    assert catalog['groupingSources'] == {
        'items': [{
            'datasetId': 'dataset_001', 'parentFactId': state.facts.metrics[0].fact_id,
            'measureField': 'income', 'periodField': 'period', 'currentPeriods': ['2026-01'],
            'dimensionFields': ['department'], 'projectedScopeFields': [],
            'periodAggregation': 'sum',
            'supportedOperations': list(module.STANDARD_SUPPLEMENTAL_OPERATIONS),
            'comparisonBindings': [],
        }],
        'totalItems': 1, 'truncated': False,
    }


def test_hidden_cross_pair_uses_compact_source_and_existing_explicit_preflight():
    state = _standard_analysis_state()
    dimensions = [f'dim{i:02d}' for i in range(20)]
    state.instruction['datasets'][0]['columns'].extend(dimensions)
    catalog = _catalog(state)
    source, = catalog['groupingSources']['items']
    advertised_pairs = {
        tuple(sorted((spec['dimensionField'], spec['secondaryDimensionField'])))
        for candidate in catalog['candidates']
        if (spec := candidate['standardComputation'])['operation'] == 'cross_group_summary'
    }
    hidden_pair = next(pair for pair in combinations(dimensions, 2) if pair not in advertised_pairs)
    assert source['dimensionFields'] == sorted(['department', *dimensions])
    assert len(catalog['candidates']) <= 40
    assert len(json.dumps(catalog['groupingSources'], ensure_ascii=False).encode()) <= 12_000
    _select(state, source, hidden_pair)


def test_source_index_does_not_depend_on_any_candidate_surviving(monkeypatch):
    state = _standard_analysis_state()
    monkeypatch.setattr(module, 'STANDARD_CANDIDATE_LIMIT', 0)
    catalog = _catalog(state)
    assert catalog['candidates'] == []
    source, = catalog['groupingSources']['items']
    _select(state, source, ('department',))


@pytest.mark.parametrize('measure', ['income', 'expense', 'service_count'])
def test_source_index_uses_actual_measure_fields_across_topics(measure):
    state = _standard_analysis_state()
    state.facts.metrics[0].field = measure
    state.instruction['datasets'][0]['columns'] = ['period', 'department', measure]
    source, = _sources(state)
    assert source['measureField'] == measure
    _select(state, source, ('department',))


@pytest.mark.parametrize('fault', [
    'manifest_hash', 'missing_manifest_hash', 'missing_parent_hash', 'aggregation',
    'period_aggregation', 'cumulative', 'missing_measure', 'missing_period',
    'unprojected_scope', 'invalid_period', 'duplicate_period', 'unknown_request',
])
def test_source_index_rejects_unbound_or_nonadditive_parent_facts(fault):
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    dataset = state.instruction['datasets'][0]
    if fault == 'manifest_hash':
        dataset['sha256'] = 'b' * 64
    elif fault == 'missing_manifest_hash':
        dataset.pop('sha256')
    elif fault == 'missing_parent_hash':
        parent.dataset_sha256 = None
    elif fault == 'aggregation':
        parent.aggregation = 'average'
    elif fault == 'period_aggregation':
        parent.period_aggregation = 'last'
        parent.period_values += (SimpleNamespace(period='2026-02', value=2),)
        state.instruction['currentAnalysis']['periods'] = ['2026-01', '2026-02']
    elif fault == 'cumulative':
        parent.cumulative_policy = 'year_to_date'
    elif fault == 'missing_measure':
        dataset['columns'].remove('income')
    elif fault == 'missing_period':
        dataset['columns'].remove('period')
    elif fault == 'unprojected_scope':
        parent.scope = {'company': 'A'}
    elif fault == 'invalid_period':
        parent.period_values = (SimpleNamespace(period='unknown', value=1),)
    elif fault == 'duplicate_period':
        parent.period_granularity = 'month'
        parent.period_values = (
            SimpleNamespace(period='2026-01', value=1),
            SimpleNamespace(period='2026-01-01', value=2),
        )
    else:
        state.instruction['currentAnalysis']['periods'] = ['2026-01', 'unknown']
    assert _catalog(state)['groupingSources'] == {
        'items': [], 'totalItems': 0, 'truncated': False,
    }


@pytest.mark.parametrize('period_aggregation', [None, 'last'])
def test_single_period_source_exposes_only_grouping_operations(period_aggregation):
    state = _standard_analysis_state()
    state.facts.metrics[0].period_aggregation = period_aggregation
    source, = _sources(state)
    assert source['periodAggregation'] == period_aggregation
    assert source['supportedOperations'] == ['group_summary', 'cross_group_summary']
    assert source['comparisonBindings'] == []
    _select(state, source, ('department',))
    for operation in ('group_period_series', 'group_period_comparison', 'period_comparison', 'group_ratio'):
        requirement = state.decision.coding_requirements[0]
        state.decision = state.decision.model_copy(update={'coding_requirements': (
            requirement.model_copy(update={'standard_computation': requirement.standard_computation.model_copy(
                update={'operation': operation},
            )}),
        )})
        assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize('projected', [True, False])
def test_scope_fields_are_required_or_query_bound_but_never_dimensions(projected):
    state = _standard_analysis_state()
    state.facts.metrics[0].scope = {'income_nature': '开单收入'}
    dataset = state.instruction['datasets'][0]
    if projected:
        dataset['columns'].append('income_nature')
    else:
        _bind_signed_scope(dataset)
    source, = _sources(state)
    assert source['dimensionFields'] == ['department']
    assert source['projectedScopeFields'] == (['income_nature'] if projected else [])
    _select(state, source, ('department',))


def test_profile_measure_period_and_empty_columns_are_not_grouping_dimensions():
    state = _standard_analysis_state()
    dataset = state.instruction['datasets'][0]
    dataset['columns'].extend(['amount', 'date', 'unused', 'service'])
    dataset['columnProfile'] = {
        'amount': {'role': 'measure'}, 'date': {'role': 'period'},
        'unused': {'role': 'empty'}, 'service': {'role': 'dimension'},
    }
    source, = _sources(state)
    assert source['dimensionFields'] == ['department', 'service']


def _comparison_state():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_roles = ('current',)
    parent.period_granularity = 'month'
    parent.field_ref = 'source.db.income.income'
    parent.unit = '元'
    prior = SimpleNamespace(**vars(parent))
    prior.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    prior.dataset_id = 'dataset_prior'
    prior.period_roles = ('yoy',)
    prior.period_values = (SimpleNamespace(period='2025-01', value=2),)
    state.facts.metrics.append(prior)
    state.instruction['datasets'][0]['columns'].append('channel')
    state.instruction['datasets'].append({
        'datasetId': prior.dataset_id, 'columns': ['period', 'department', 'income'],
        'sha256': prior.dataset_sha256,
    })
    state.instruction['currentAnalysis']['datasetIds'].append(prior.dataset_id)
    return state, parent, prior


def test_comparison_binding_exposes_only_joint_dimensions_and_routes_real_spec():
    state, parent, prior = _comparison_state()
    source = next(item for item in _sources(state) if item['parentFactId'] == parent.fact_id)
    binding, = source['comparisonBindings']
    assert binding == {
        'baselineParentFactId': prior.fact_id, 'baselineDatasetId': prior.dataset_id,
        'baselinePeriods': ['2025-01'], 'dimensionFields': ['department'],
    }
    spec = StandardSupplementalSpec(
        operation='period_comparison', measureField=source['measureField'],
        dimensionField=binding['dimensionFields'][0], periodField=source['periodField'],
        currentPeriods=source['currentPeriods'], parentFactId=source['parentFactId'],
        baselineParentFactId=binding['baselineParentFactId'],
        baselineDatasetId=binding['baselineDatasetId'], baselinePeriods=binding['baselinePeriods'],
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={'standard_computation': spec})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == (spec,)


@pytest.mark.parametrize('fault', ['hash', 'field_ref', 'scope', 'unit', 'period', 'aggregation'])
def test_comparison_binding_rejects_unbound_or_incompatible_baselines(fault):
    state, parent, prior = _comparison_state()
    if fault == 'hash':
        prior.dataset_sha256 = 'b' * 64
    elif fault == 'field_ref':
        prior.field_ref = 'another.source.income'
    elif fault == 'scope':
        prior.scope = {'income_nature': '其他收入'}
    elif fault == 'unit':
        prior.unit = '万元'
    elif fault == 'period':
        prior.period_values = (SimpleNamespace(period='2025-02', value=2),)
    else:
        prior.period_aggregation = 'last'
    source = next(item for item in _sources(state) if item['parentFactId'] == parent.fact_id)
    assert source['comparisonBindings'] == []


def test_grouping_source_budget_keeps_complete_items_and_truthful_total(monkeypatch):
    state = _standard_analysis_state()
    first = _sources(state)[0]
    parent = state.facts.metrics[0]
    for index in range(1, 4):
        state.facts.metrics.append(SimpleNamespace(**{
            **vars(parent), 'fact_id': f'fact-{index:016x}',
        }))
    # 预算容纳一个完整来源，却无法容纳全部；不可删维度伪装为完整索引。
    budget = len(json.dumps({'items': [first], 'totalItems': 4, 'truncated': True},
                            ensure_ascii=False).encode()) + 10
    monkeypatch.setattr(module, 'STANDARD_GROUPING_SOURCE_BYTES', budget, raising=False)
    index = _catalog(state)['groupingSources']
    assert index['totalItems'] == 4
    assert index['truncated'] is True
    assert 0 < len(index['items']) < 4
    assert len(json.dumps(index, ensure_ascii=False).encode()) <= budget
    for item in index['items']:
        assert set(item) == set(first)
        assert item['dimensionFields'] == ['department']
        assert item['currentPeriods'] == ['2026-01']


@pytest.mark.anyio
@pytest.mark.parametrize('enabled', [False, True])
async def test_planner_exposes_only_authorized_grouping_sources_in_one_decision(monkeypatch, enabled):
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.workflow.runtime import analysis_item_workflow as workflow_module

    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    foreign = SimpleNamespace(**{
        **vars(parent), 'fact_id': 'fact-bbbbbbbbbbbbbbbb', 'dataset_id': 'foreign',
    })
    state.facts.metrics.append(foreign)
    state.instruction['datasets'].append({
        'datasetId': 'foreign', 'columns': ['period', 'income', 'department'],
        'sha256': parent.dataset_sha256,
    })
    requests = []

    async def decide(payload):
        requests.append(payload)
        if enabled:
            # 所有候选被预算限制删去时，模型仍可从来源索引构造现有显式 Spec。
            assert payload['standardComputationCandidates'] == []
            source, = payload['standardComputationPolicy']['groupingSources']['items']
            assert source['datasetId'] == 'dataset_001'
            spec = StandardSupplementalSpec(
                operation='group_summary', measureField=source['measureField'],
                dimensionField=source['dimensionFields'][0], periodField=source['periodField'],
                currentPeriods=source['currentPeriods'], parentFactId=source['parentFactId'],
            )
            requirement = state.decision.coding_requirements[0].model_copy(update={
                'standard_candidate_id': None, 'standard_computation': spec,
            })
            return state.decision.model_copy(update={'coding_requirements': (requirement,)})
        return state.decision

    monkeypatch.setattr(module, 'STANDARD_CANDIDATE_LIMIT', 0)
    monkeypatch.setattr(workflow_module, 'facts_cover_analysis', lambda *args: None)
    workflow = AnalysisItemWorkflow(
        decide_evidence=decide, run_code=AsyncMock(), summarize=AsyncMock(),
        read_file=AsyncMock(), complete=AsyncMock(),
        run_standard_supplemental=AsyncMock() if enabled else None,
    )
    workflow._model_facts = lambda _: {}
    await workflow._decide_evidence(state)
    assert len(requests) == 1
    assert ('standardComputationPolicy' in requests[0]) is enabled
    assert ('standardComputationCandidates' in requests[0]) is enabled
    if enabled:
        assert requests[0]['standardComputationPolicy']['groupingSources']['totalItems'] == 1
        assert len(workflow._standard_plan(state)) == 1


def _planner_source_payload(state):
    return {
        'currentAnalysis': {'analysisId': 'analysis_001'},
        'datasets': [{'datasetId': 'dataset_001', 'columns': ['income', 'department', 'period']}],
        'standardComputationCandidates': [
            {'candidateId': f'std-{index}', 'details': 'x' * 1000} for index in range(40)
        ],
        'standardComputationPolicy': {
            'catalogIsExhaustive': False, 'groupingSources': _catalog(state)['groupingSources'],
        },
    }


def test_planner_budget_drops_candidates_before_complete_grouping_sources():
    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        _project_analysis_summary_payload,
    )

    state = _standard_analysis_state()
    payload = _planner_source_payload(state)
    projected = _project_analysis_summary_payload(
        payload, max_tokens=1000, count_tokens=lambda value: len(json.dumps(value)), strict=True,
    )
    assert projected['standardComputationCandidates'] == []
    assert projected['standardComputationPolicy']['groupingSources'] == (
        payload['standardComputationPolicy']['groupingSources']
    )
    source, = projected['standardComputationPolicy']['groupingSources']['items']
    _select(state, source, ('department',))
    assert len(payload['standardComputationCandidates']) == 40


@pytest.mark.parametrize('strict', [False, True])
def test_tight_planner_budget_omits_whole_sources_with_truthful_truncation(strict):
    from copy import deepcopy

    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        _project_analysis_summary_payload,
    )

    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    state.facts.metrics.extend(
        SimpleNamespace(**{**vars(parent), 'fact_id': f'fact-{index:016x}'})
        for index in range(1, 4)
    )
    payload = _planner_source_payload(state)
    minimal = deepcopy(payload)
    minimal['standardComputationCandidates'] = []
    minimal['standardComputationCandidatesView'] = {
        'truncated': True, 'candidateCount': 40, 'selectedCandidateCount': 0,
    }
    source_index = minimal['standardComputationPolicy']['groupingSources']
    source_index['items'] = source_index['items'][:1]
    source_index['truncated'] = True
    budget = len(json.dumps(minimal)) + 10
    projected = _project_analysis_summary_payload(
        payload, max_tokens=budget, count_tokens=lambda value: len(json.dumps(value)), strict=strict,
    )
    index = projected['standardComputationPolicy']['groupingSources']
    assert len(json.dumps(projected)) <= budget
    assert projected['standardComputationCandidates'] == []
    assert index['totalItems'] == 4
    assert index['truncated'] is True
    assert 0 < len(index['items']) < 4
    assert all(item in payload['standardComputationPolicy']['groupingSources']['items']
               for item in index['items'])
    assert projected['datasets'] == payload['datasets']
    assert len(payload['standardComputationPolicy']['groupingSources']['items']) == 4
