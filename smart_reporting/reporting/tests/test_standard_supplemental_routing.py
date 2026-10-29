"""标准路由可选目录、批量需求与期间别名的授权回归。"""
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _context,
    _standard_analysis_state,
    _standard_evidence,
)
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.standard_supplemental import (
    standard_computation_candidates,
)


def _candidates(state):
    current = state.instruction.get('currentAnalysis') or {}
    return standard_computation_candidates(
        state.facts, state.instruction['datasets'], current.get('periods', ()),
    )


def _summary_candidates(state):
    return [item for item in _candidates(state)
            if item['standardComputation']['operation'] == 'group_summary']


@pytest.mark.parametrize('operation', ['group_period_series', 'cross_group_summary'])
def test_extended_candidate_routes_only_with_all_authorized_dimensions(operation):
    state = _standard_analysis_state()
    state.instruction['datasets'][0]['columns'].append('channel')
    candidate = next(item for item in _candidates(state)
                     if item['standardComputation']['operation'] == operation)
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']), 'standard_computation': None,
        'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.operation == operation
    requirement = requirement.model_copy(update={'fields': ('income', 'period')})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_candidate_id_binds_authorized_fields_without_model_copying_spec():
    state = _standard_analysis_state()
    candidate, = _summary_candidates(state)
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    spec, = AnalysisItemWorkflow._standard_plan(state)
    assert spec.measure_field == 'income'
    assert spec.dimension_field == 'department'
    assert spec.parent_fact_id == state.facts.metrics[0].fact_id
    assert _summary_candidates(state) == [candidate]


@pytest.mark.parametrize('fault', ['candidate', 'fields', 'dataset', 'conflict', 'changed_parent'])
def test_candidate_selection_cannot_expand_authorization_or_override_frozen_semantics(fault):
    state = _standard_analysis_state()
    candidate, = _summary_candidates(state)
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
    })
    if fault == 'candidate':
        requirement = requirement.model_copy(update={'standard_candidate_id': 'std-unknown'})
    elif fault == 'fields':
        requirement = requirement.model_copy(update={'fields': ('income', 'period')})
    elif fault == 'dataset':
        requirement = requirement.model_copy(update={'dataset_id': 'foreign'})
    elif fault == 'changed_parent':
        state.facts.metrics[0].period_aggregation = 'last'
    else:
        original = state.decision.coding_requirements[0].standard_computation
        requirement = requirement.model_copy(update={'standard_computation': original.model_copy(
            update={'current_periods': ('2026-02',)},
        )})
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.parametrize('fault', ['aggregation', 'period_aggregation', 'scope', 'invalid_period', 'duplicate_period'])
def test_catalog_does_not_advertise_unsupported_frozen_inputs(fault):
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    if fault == 'aggregation':
        parent.aggregation = 'average'
    elif fault == 'period_aggregation':
        parent.period_aggregation = None
    elif fault == 'scope':
        parent.scope = {'company': 'not_projected'}
    elif fault == 'invalid_period':
        parent.period_values = (SimpleNamespace(period='unknown', value=1),)
    else:
        parent.period_granularity = 'month'
        parent.period_values = (SimpleNamespace(period='2026-01', value=1),
                                SimpleNamespace(period='2026-01-01', value=2))
    assert _candidates(state) == []


def test_catalog_exposes_explicit_same_dataset_comparison_and_bounds_size():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_roles = ('current',)
    prior = SimpleNamespace(**vars(parent))
    prior.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    prior.period_roles = ('yoy',)
    prior.period_values = (SimpleNamespace(period='2025-01', value=2),)
    state.facts.metrics.append(prior)
    candidates = _candidates(state)
    comparison = next(item for item in candidates if item['standardComputation']['operation'] == 'period_comparison')
    assert comparison['standardComputation']['baselineParentFactId'] == prior.fact_id
    prior.dataset_id = 'foreign'
    assert not any(item['standardComputation']['operation'] == 'period_comparison' for item in _candidates(state))
    state.instruction['datasets'][0]['columns'].extend(f'dim{i}' for i in range(100))
    assert len(_candidates(state)) <= 40


def test_requested_window_crops_current_and_baseline_by_matching_position():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_roles = ('current',)
    parent.period_granularity = 'month'
    parent.period_values = tuple(
        SimpleNamespace(period=f'2026-{month:02d}', value=month) for month in range(1, 4)
    )
    prior = SimpleNamespace(**vars(parent))
    prior.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    prior.period_roles = ('yoy',)
    prior.period_values = tuple(
        SimpleNamespace(period=f'2025-{month:02d}', value=month) for month in range(1, 4)
    )
    state.facts.metrics.append(prior)
    state.instruction['currentAnalysis']['periods'] = ['2026-01', '2026-02']

    comparison = next(
        item['standardComputation'] for item in _candidates(state)
        if item['standardComputation']['operation'] == 'period_comparison'
    )

    assert comparison['currentPeriods'] == ['2026-01', '2026-02']
    assert comparison['baselinePeriods'] == ['2025-01', '2025-02']


@pytest.mark.parametrize('grain,current,prior,expected', [
    ('day', '2026-03-02', '2026-03-01', True),
    ('day', '2026-03-02', '2026-02-02', False),
    ('month', '2026-01', '2025-12', True),
    ('year', '2026', '2025', True),
])
def test_comparison_candidate_uses_frozen_grain_for_previous_period(grain, current, prior, expected):
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_roles = ('current',)
    parent.period_granularity = grain
    parent.period_values = (SimpleNamespace(period=current, value=10),)
    baseline = SimpleNamespace(**vars(parent))
    baseline.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    baseline.period_roles = ('mom',)
    baseline.period_values = (SimpleNamespace(period=prior, value=5),)
    state.facts.metrics.append(baseline)
    comparisons = [item['standardComputation'] for item in _candidates(state)
                   if item['standardComputation']['operation'] == 'period_comparison']
    assert bool(comparisons) is expected
    if expected:
        assert comparisons[0]['baselinePeriods'] == [prior]


@pytest.mark.parametrize('fault', [None, 'unauthorized', 'field', 'scope', 'unit', 'last', 'missing_month'])
def test_cross_dataset_comparison_uses_authorized_calendar_window(fault):
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_roles = ('current',)
    parent.period_granularity = 'month'
    parent.field_ref = 'source.db.income.income'
    parent.unit = '元'
    parent.period_values = tuple(SimpleNamespace(period=f'2026-{m:02d}', value=m) for m in range(1, 12))
    prior = SimpleNamespace(**vars(parent))
    prior.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    prior.dataset_id = 'dataset_prior'
    prior.period_roles = ('yoy',)
    # Deliberately reverse the source order: matching by position is unsafe.
    prior.period_values = tuple(SimpleNamespace(period=f'2025-{m:02d}', value=m) for m in range(12, 0, -1))
    state.facts.metrics.append(prior)
    state.instruction['datasets'].append({
        'datasetId': prior.dataset_id, 'columns': ['period', 'department', 'income'],
        'sha256': prior.dataset_sha256,
    })
    state.instruction['currentAnalysis']['datasetIds'].append(prior.dataset_id)
    if fault == 'unauthorized':
        state.instruction['currentAnalysis']['datasetIds'].remove(prior.dataset_id)
    elif fault == 'field':
        prior.field_ref = 'another.source.income'
    elif fault == 'scope':
        prior.scope = {'income_nature': '其他收入'}
    elif fault == 'unit':
        prior.unit = '万元'
    elif fault == 'last':
        prior.period_aggregation = 'last'
    elif fault == 'missing_month':
        prior.period_values = prior.period_values[2:]
    # The instruction catalog is restricted to the analysis authorization, as in production.
    datasets = [d for d in state.instruction['datasets']
                if d['datasetId'] in state.instruction['currentAnalysis']['datasetIds']]
    comparisons = [item for item in standard_computation_candidates(state.facts, datasets)
                   if item['standardComputation']['operation'] == 'period_comparison']
    if fault is not None:
        assert comparisons == []
        return
    candidate, = comparisons
    spec = candidate['standardComputation']
    assert spec['baselineDatasetId'] == prior.dataset_id
    assert spec['baselinePeriods'] == [f'2025-{m:02d}' for m in range(1, 12)]
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.baseline_dataset_id == prior.dataset_id
    state.instruction['currentAnalysis']['datasetIds'].remove(prior.dataset_id)
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_partially_unknown_requested_window_never_creates_a_partial_candidate():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.period_granularity = 'month'
    parent.period_values = (
        SimpleNamespace(period='2026-01', value=1),
        SimpleNamespace(period='2026-02', value=2),
    )
    state.instruction['currentAnalysis']['periods'] = ['2026-01', 'unknown']

    assert _summary_candidates(state) == []


def _bind_signed_scope(dataset, *, value='开单收入', operator='='):
    query = (
        'SELECT period, department, income FROM db.income '
        f"WHERE income_nature {operator} '{value}'"
    )
    dataset.update({
        'sourceType': 'starrocks_materialized',
        'provenance': {'querySql': query, 'sqlHash': hashlib.sha256(query.encode()).hexdigest()},
    })


def test_signed_query_scope_and_requested_window_enable_exact_candidate():
    state = _standard_analysis_state()
    parent = state.facts.metrics[0]
    parent.scope = {'income_nature': '开单收入'}
    parent.period_granularity = 'month'
    parent.period_values = (
        SimpleNamespace(period='2026-01-01', value=1),
        SimpleNamespace(period='2026-02-01', value=2),
        SimpleNamespace(period='2026-03-01', value=3),
    )
    state.instruction['currentAnalysis']['periods'] = ['2026-01', '2026-02']
    dataset = state.instruction['datasets'][0]
    _bind_signed_scope(dataset)

    candidate, = _summary_candidates(state)

    assert candidate['fields'] == ['department', 'income', 'period']
    assert candidate['standardComputation']['currentPeriods'] == [
        '2026-01-01', '2026-02-01',
    ]
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'standard_computation': None, 'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    selected, = AnalysisItemWorkflow._standard_plan(state)
    assert selected.current_periods == ('2026-01-01', '2026-02-01')


@pytest.mark.parametrize('fault', ['hash', 'value', 'operator', 'or', 'source'])
def test_untrusted_or_non_exact_query_never_authorizes_unprojected_scope(fault):
    state = _standard_analysis_state()
    state.facts.metrics[0].scope = {'income_nature': '开单收入'}
    dataset = state.instruction['datasets'][0]
    _bind_signed_scope(
        dataset,
        value='其他收入' if fault == 'value' else '开单收入',
        operator='LIKE' if fault == 'operator' else '=',
    )
    if fault == 'hash':
        dataset['provenance']['sqlHash'] = '0' * 64
    elif fault == 'or':
        query = ("SELECT period, department, income FROM db.income WHERE "
                 "income_nature = '开单收入' OR income_nature = '其他收入'")
        dataset['provenance'] = {
            'querySql': query, 'sqlHash': hashlib.sha256(query.encode()).hexdigest(),
        }
    elif fault == 'source':
        dataset['sourceType'] = 'url_csv'

    assert _candidates(state) == []


def _add_registered_group_ratio(state):
    numerator = state.facts.metrics[0]
    numerator.unit = '元'
    numerator.scope = {}
    numerator.period_roles = ('current',)
    numerator.period_granularity = 'month'
    denominator = SimpleNamespace(**vars(numerator))
    denominator.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    denominator.field = 'budget'
    denominator.display_name = '预算'
    state.facts.metrics.append(denominator)
    ratio = SimpleNamespace(
        fact_id='fact-cccccccccccccccc', input_fact_ids=(numerator.fact_id, denominator.fact_id),
        dataset_ids=('dataset_001',), denominator_scale=1, difference=0, percentage=100,
        code='income_completion', scope={}, period_granularity='month', period_role='current',
    )
    state.facts.derived_metrics = [ratio]
    state.instruction['datasets'][0]['columns'].append('budget')
    return numerator, denominator, ratio


def test_catalog_exposes_registered_group_ratio_and_preflight_binds_ordered_operands():
    state = _standard_analysis_state()
    numerator, denominator, ratio = _add_registered_group_ratio(state)
    candidate = next(
        item for item in _candidates(state)
        if item['standardComputation']['operation'] == 'group_ratio'
    )
    spec_payload = candidate['standardComputation']
    assert spec_payload['parentFactId'] == numerator.fact_id
    assert spec_payload['denominatorParentFactId'] == denominator.fact_id
    assert spec_payload['ratioFactId'] == ratio.fact_id
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']),
        'standard_computation': None,
        'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})

    selected, = AnalysisItemWorkflow._standard_plan(state)

    assert selected.operation == 'group_ratio'
    assert selected.denominator_field == 'budget'


@pytest.mark.parametrize('fault', ['unordered_inputs', 'unit', 'scope', 'missing_ratio'])
def test_group_ratio_never_routes_without_a_matching_registered_ratio(fault):
    state = _standard_analysis_state()
    numerator, denominator, ratio = _add_registered_group_ratio(state)
    candidate = next(
        item for item in _candidates(state)
        if item['standardComputation']['operation'] == 'group_ratio'
    )
    requirement = state.decision.coding_requirements[0].model_copy(update={
        'fields': tuple(candidate['fields']),
        'standard_computation': None,
        'standard_candidate_id': candidate['candidateId'],
    })
    state.decision = state.decision.model_copy(update={'coding_requirements': (requirement,)})
    if fault == 'unordered_inputs':
        ratio.input_fact_ids = tuple(reversed(ratio.input_fact_ids))
    elif fault == 'unit':
        denominator.unit = '人次'
    elif fault == 'scope':
        denominator.scope = {'area': 'north'}
    else:
        state.facts.derived_metrics = []

    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_candidate_budget_round_robins_operations_so_group_ratio_is_not_starved():
    state = _standard_analysis_state()
    _add_registered_group_ratio(state)
    state.instruction['datasets'][0]['columns'].extend(f'dim{i}' for i in range(100))

    candidates = _candidates(state)

    assert len(candidates) <= 40
    assert any(item['standardComputation']['operation'] == 'group_ratio' for item in candidates)


def test_real_frozen_registered_ratio_produces_group_ratio_candidate():
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )
    from smart_reporting.reporting.tests.test_deterministic_analysis import (
        analysis,
        context,
        semantic,
    )
    from smart_reporting.reporting.trace.fact_index import assign_fact_ids

    profile_metrics = (
        {'code': 'actual', 'aggregation': 'sum', 'fieldRef': semantic('actual')['fieldRef']},
        {'code': 'budget', 'aggregation': 'sum', 'fieldRef': semantic('budget')['fieldRef']},
        {'code': 'completion', 'aggregation': 'ratio',
         'numeratorMetric': 'actual', 'denominatorMetric': 'budget'},
    )
    fields = ('month', 'department', 'actual', 'budget')
    bundle = assign_fact_ids(build_deterministic_analysis_bundle(
        analysis(fields=('actual', 'budget')),
        (('current', b'month,department,actual,budget\n2025-01,A,80,100\n',
          context('current', fields=fields,
                  semantics=(semantic('actual', unit='元'), semantic('budget', unit='元'))),
          ('current',)),),
        profile_metrics=profile_metrics,
    ))

    candidate = next(item for item in standard_computation_candidates(bundle, ({
        'datasetId': 'current', 'columns': list(fields),
    },)) if item['standardComputation']['operation'] == 'group_ratio')

    assert candidate['fields'] == ['actual', 'budget', 'department', 'month']
    assert candidate['standardComputation']['ratioFactId'] == bundle.derived_metrics[0].fact_id


@pytest.mark.parametrize('grain,expected', [('month', ('2026-01-01',)), ('day', None)])
def test_period_aliases_only_normalize_with_frozen_granularity(grain, expected):
    state = _standard_analysis_state()
    state.facts.metrics[0].period_granularity = grain
    state.facts.metrics[0].period_values = (SimpleNamespace(period='2026-01-01', value=1),)
    spec = AnalysisItemWorkflow._standard_spec(state)
    assert (spec.current_periods if spec else None) == expected


@pytest.mark.anyio
async def test_multiple_supported_requirements_use_one_server_batch_without_code():
    state = _standard_analysis_state()
    first = state.decision.coding_requirements[0]
    state.decision = state.decision.model_copy(update={'coding_requirements': (
        first, first.model_copy(update={'output_name': 'another_dimension'}),
    )})
    server = AsyncMock(return_value={
        'evidence': _standard_evidence(),
        'evidenceFile': FileIdentity(path='evidence.json', size=2, sha256='a' * 64),
        'computationRecord': {'method': 'supplemental_standard_batch'},
    })
    code = AsyncMock(side_effect=AssertionError('标准批量路径不应生成脚本'))
    workflow = AnalysisItemWorkflow(decide_evidence=AsyncMock(), run_code=code,
        summarize=AsyncMock(), read_file=AsyncMock(), complete=AsyncMock(), run_standard_supplemental=server)
    await workflow._execute_script(state, _context())
    assert len(server.await_args.kwargs['spec']) == 2
    code.assert_not_awaited()
    unsupported = first.model_copy(update={'output_name': 'complex', 'standard_computation': None})
    state.decision = state.decision.model_copy(update={'coding_requirements': (first, unsupported)})
    assert AnalysisItemWorkflow._standard_plan(state) == ()


@pytest.mark.anyio
@pytest.mark.parametrize('enabled', [False, True])
async def test_planner_receives_candidates_only_when_server_route_is_enabled(monkeypatch, enabled):
    from smart_reporting.reporting.workflow.runtime import analysis_item_workflow as module

    state = _standard_analysis_state()
    requests = []
    async def decide(payload):
        requests.append(payload)
        if enabled:
            candidate = next(item for item in payload['standardComputationCandidates']
                             if item['standardComputation']['operation'] == 'group_summary')
            requirement = state.decision.coding_requirements[0].model_copy(update={
                'standard_candidate_id': candidate['candidateId'], 'standard_computation': None,
            })
            return state.decision.model_copy(update={'coding_requirements': (requirement,)})
        return state.decision
    workflow = AnalysisItemWorkflow(decide_evidence=decide, run_code=AsyncMock(),
        summarize=AsyncMock(), read_file=AsyncMock(), complete=AsyncMock(),
        run_standard_supplemental=AsyncMock() if enabled else None)
    workflow._model_facts = lambda _: {}
    monkeypatch.setattr(module, 'facts_cover_analysis', lambda *args: None)
    await workflow._decide_evidence(state)
    assert len(requests) == 1
    assert ('standardComputationCandidates' in requests[0]) is enabled
    assert ('standardComputationPolicy' in requests[0]) is enabled
    if enabled:
        policy = requests[0]['standardComputationPolicy']
        declared = set(module.StandardSupplementalSpec.model_json_schema()['properties']['operation']['enum'])
        assert set(policy['supportedOperations']) == declared
        assert policy['catalogIsExhaustive'] is False
        assert len(workflow._standard_plan(state)) == 1


def test_large_standard_batch_uses_bounded_table_refs_instead_of_falling_back():
    from smart_reporting.reporting.trace.computation_service import (
        build_standard_supplemental_computation_record,
    )

    record = build_standard_supplemental_computation_record(
        analysis_id='analysis_001', dataset_ids=('dataset_001',), input_files=(),
        evidence_file={'path': 'evidence.json', 'sha256': 'a' * 64},
        method='supplemental_standard_batch', method_version='standard-supplemental-v1',
        parameters={}, execution_id='standard-large', finding_count=600, finding_row_counts=(300, 300),
    )
    assert [ref.json_pointer for ref in record.output_fact_refs] == ['/findings/0', '/findings/1']
    assert record.parameters['findingRowCounts'] == [300, 300]


def test_merged_multi_measure_requirement_never_silently_ignores_a_measure():
    state = _standard_analysis_state()
    other = SimpleNamespace(**vars(state.facts.metrics[0]))
    other.fact_id = 'fact-bbbbbbbbbbbbbbbb'
    other.field = 'visits'
    state.facts.metrics.append(other)
    state.instruction['datasets'][0]['columns'].append('visits')
    original = state.decision.coding_requirements[0]
    state.decision = state.decision.model_copy(update={'coding_requirements': (
        original.model_copy(update={'fields': (*original.fields, 'visits')}),
    )})
    assert AnalysisItemWorkflow._standard_plan(state) == ()


def test_candidate_hint_budget_does_not_overflow_or_drop_authorized_sources():
    import json

    from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
        _project_analysis_summary_payload,
    )

    payload = {'datasets': [{'datasetId': 'dataset_001', 'columns': ['income', 'department', 'period']}],
               'currentAnalysis': {'analysisId': 'analysis_001'},
               'standardComputationCandidates': [{'candidateId': f'std-{index}', 'details': 'x' * 1000}
                                                 for index in range(40)]}
    projected = _project_analysis_summary_payload(payload, max_tokens=800,
        count_tokens=lambda value: len(json.dumps(value)), strict=True)
    assert projected['datasets'] == payload['datasets']
    assert projected['currentAnalysis'] == payload['currentAnalysis']
    assert projected['standardComputationCandidates'] == []
    assert projected['standardComputationCandidatesView']['candidateCount'] == 40
    assert len(payload['standardComputationCandidates']) == 40
