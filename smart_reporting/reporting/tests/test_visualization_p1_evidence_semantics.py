"""P1: immutable units, semantic periods and durable unsuccessful attempts."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _context,
    _visualization_payload,
    _visualization_plan,
)
from smart_reporting.reporting.tests.test_reporting_state import initial_state
from smart_reporting.reporting.workflow.runtime.chart_inputs import _table_for_binding
from smart_reporting.reporting.workflow.runtime.phase_models import ChartDataBinding
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    VisualizationSectionWorkflow,
)
from smart_reporting.reporting.workflow.state import ReportingStateReducer


def test_scalar_measure_units_preserve_derived_and_comparison_without_lending_to_ratios():
    document = {'derivedMetrics': [{'unit': '元/人次', 'value': -2.5, 'percentage': 25}],
                'comparisons': [{'unit': '万元', 'currentTotal': 2, 'baselineTotal': 3, 'change': -1, 'changeRate': -.333}]}
    original = deepcopy(document)
    for path, fields, expected in [
        ('derivedMetrics[0]', ['value', 'percentage'], {'value': {'unit': '元/人次'}}),
        ('comparisons[0]', ['currentTotal', 'baselineTotal', 'change', 'changeRate'],
         {key: {'unit': '万元'} for key in ['currentTotal', 'baselineTotal', 'change']}),
    ]:
        binding = ChartDataBinding(analysisId='a', factPath='facts.json', dataPath=path, fields=fields, role='main')
        columns, rows, metadata = _table_for_binding(document, binding)
        assert metadata == expected
        assert rows == [[document[path.split('[')[0]][0][field] for field in fields]]
    assert document == original


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('cancelled', [False, True])
async def test_failed_or_cancelled_workflow_keeps_original_plan_and_execution_evidence(cancelled):
    plan = _visualization_plan()
    error = asyncio.CancelledError() if cancelled else RuntimeError('renderer unavailable')
    error.standard_chart_routes = ({'chartId': 'chart_001', 'route': 'coding'},)
    error.standard_execution_attempts = ({'routePhase': 'group', 'status': 'failed', 'durationMs': 17},)
    records = []

    async def record(event, _context):
        records.append(event)

    workflow = VisualizationSectionWorkflow(generate_plan=AsyncMock(return_value=plan),
        run_code=AsyncMock(side_effect=error), submit=AsyncMock(), record_evidence=record)
    with pytest.raises(type(error)):
        await workflow.run(_visualization_payload(), _context())
    assert records[0]['event'] == 'plan'
    assert records[0]['plan']['charts'][0]['chartId'] == 'chart_001'
    execution = next(item for item in records if item['event'] == 'execution')
    assert execution['status'] == ('cancelled' if cancelled else 'failed')
    assert execution['routes'] == [{'chartId': 'chart_001', 'route': 'coding'}]
    assert execution['executionAttempts'] == [{'routePhase': 'group', 'status': 'failed', 'durationMs': 17}]
    assert execution['chartCount'] == 1
    assert execution['formCounts'] == {'unknown': 1}
    assert execution['plan'] == plan.model_dump(mode='json', by_alias=True)


def test_durable_evidence_is_separate_from_business_warnings_and_keeps_attempts():
    state = initial_state()
    for attempt, status in [(0, 'failed'), (1, 'cancelled')]:
        state = ReportingStateReducer.apply(state, {
            'name': 'record_visualization_evidence', 'commandId': f'vis-{attempt}',
            'payload': {'sectionCode': 's1', 'taskId': f'task-{attempt}',
                        'event': {'event': 'execution', 'status': status, 'formCounts': {'custom': 1, 'unknown': 1}}},
        }).state
    assert state.payload['warnings'] == []
    assert [item['event']['status'] for item in state.payload['visualizationEvidence']] == ['failed', 'cancelled']


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('fault', ['wrong_period', 'unavailable', 'ungrounded', 'borrowed_evidence', 'matches', 'visible_window', 'current_in_comparison'])
async def test_chart_period_review_uses_existing_semantic_stage_and_never_rejects_artifacts(monkeypatch, fault):
    import json

    from smart_reporting.reporting.model_policy import ThinkingRequest
    from smart_reporting.reporting.workflow.runtime import sections
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )
    from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        review_chart_period_semantics,
    )

    chart = _visualization_plan().charts[0].model_copy(update={
        'title': '上年度收入趋势', 'alt_text': '上一统计年度按月收入', 'current_period': '上一统计年度',
    })
    if fault == 'visible_window':
        chart = chart.model_copy(update={'standard_form': 'line', 'standard_labels': ('2025-02-01',)})
    if fault == 'current_in_comparison':
        chart = chart.model_copy(update={'comparison_type': 'mom', 'comparison_period': '上一月',
            'current_period': '2025 年 2 月'})
    plan = _visualization_plan(charts=(chart,))
    doc = {'columns': ['period', 'value'], 'rows': [['2025-01-01', 1], ['2025-02-01', 2]]}
    item = ChartInputFile('input.json', json.dumps(doc).encode())
    inputs = ChartInputMaterialization(files=(item,), entries=({'chartId': chart.chart_id, 'path': item.path, 'sha256': item.sha256},))

    async def stage(_agent, schema, stage, payload, **kwargs):
        assert schema is SectionSemanticReview and stage == 'semantics'
        expected = ['2025-02'] if fault == 'visible_window' else ['2025-01', '2025-02']
        assert payload['references'][0]['periods'] == expected
        assert '上年度收入趋势' in next(iter(payload['contexts'].values()))
        if fault == 'unavailable':
            raise RuntimeError('model unavailable')
        return SectionSemanticReview.model_validate({'interpretations': [
            {'claimId': ref['claimId'], 'periods':
                (['2025-02'] if ref['claimId'].endswith('-currentPeriod') else expected)
                if fault == 'current_in_comparison' else
                expected if fault in {'matches', 'visible_window', 'borrowed_evidence'} else ['2024-01', '2024-02'],
             'periodEvidence': ['不存在的年份'] if fault == 'ungrounded' else
                 ['上年度收入趋势'] if fault == 'borrowed_evidence' else [ref['displayText']]}
            for ref in payload['references']
        ]})

    monkeypatch.setattr(sections, '_run_section_stage', stage)
    warnings = await review_chart_period_semantics(plan, inputs, object(), section_code='s1', scope=object(),
        run_context=_context(), thinking_request=ThinkingRequest(operation='visualization_plan'))
    if fault in {'matches', 'visible_window'}:
        assert warnings == ()
    elif fault == 'current_in_comparison':
        assert [(warning['details']['field'], warning['code']) for warning in warnings] == [
            ('currentPeriod', 'report_chart_period_unreviewed')]
    elif fault == 'borrowed_evidence':
        assert {warning['details']['field'] for warning in warnings} == {'altText', 'currentPeriod'}
        assert all(warning['code'] == 'report_chart_period_unreviewed' for warning in warnings)
    else:
        assert warnings and all(warning['chartId'] == 'chart_001' for warning in warnings)
        assert all(warning['code'] == ('report_chart_period_mismatch' if fault == 'wrong_period'
                                      else 'report_chart_period_unreviewed') for warning in warnings)
    assert plan.charts[0] == chart


def test_binding_correction_uses_structured_column_directory_without_choosing_another_business_metric():
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        _validate_visualization_plan_bindings,
    )
    chart = _visualization_plan().charts[0]
    binding = chart.data_bindings[0].model_copy(update={'data_path': 'findings[0]', 'fields': ('period', 'income')})
    chart = chart.model_copy(update={'data_bindings': (binding,)})
    payload = {'visualizationFacts': [{'analysisId': 'analysis_001', 'factFile': {'path': 'facts/analysis_001.json'},
        'dataDescriptors': [{'dataPath': 'findings[0]', 'fields': ['name', 'columns', 'rows']},
                            {'dataPath': 'findings[0].rows', 'fields': ['period', 'income', 'cost']}]}]}
    result = _validate_visualization_plan_bindings(_visualization_plan(charts=(chart,)), payload)
    assert result.charts[0].data_bindings[0].data_path == 'findings[0].rows'
    assert result.charts[0].data_bindings[0].fields == ('period', 'income')


@pytest.mark.parametrize('data_path', ['metrics[0].periodValues', 'metrics[9].periodValues', 'metrics[0].topGroups'])
def test_binding_does_not_replace_a_business_table_based_only_on_matching_columns(data_path):
    from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
        _validate_visualization_plan_bindings,
    )

    chart = _visualization_plan().charts[0]
    binding = chart.data_bindings[0].model_copy(update={'data_path': data_path})
    plan = _visualization_plan(charts=(chart.model_copy(update={'data_bindings': (binding,)}),))
    payload = {'visualizationFacts': [{'analysisId': 'analysis_001', 'factFile': {'path': 'facts/analysis_001.json'},
        'dataDescriptors': [
            {'dataPath': 'metrics[0].periodValues', 'fields': ['period', 'revenue']},
            {'dataPath': 'metrics[1].periodValues', 'fields': ['period', 'value']},
        ]}]}
    assert _validate_visualization_plan_bindings(plan, payload).charts[0].data_bindings == (binding,)


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_semantic_warning_remains_visible_when_warning_storage_fails_without_rejecting_chart():
    from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
        _execution_receipt,
        _inspection,
    )
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult
    code = CodeGenerationResult(script_file=FileIdentity(path='charts/charts.py', size=1, sha256='b' * 64),
        execution_receipt=_execution_receipt('charts/charts.py', 1, 'b' * 64, ('charts/chart.png',)),
        visual_inspection_receipts=(_inspection(),))
    submitted = []
    async def submit(plan, _inspections, _context):
        submitted.append(plan)
        return {'status': 'accepted'}
    records = []
    async def evidence(event, _context):
        records.append(event)
    workflow = VisualizationSectionWorkflow(generate_plan=AsyncMock(return_value=_visualization_plan()),
        run_code=AsyncMock(return_value=code), submit=submit,
        review_plan=AsyncMock(return_value=({'code': 'report_chart_period_mismatch', 'chartId': 'chart_001', 'message': '来源为上一统计期'},)),
        record_warnings=AsyncMock(side_effect=RuntimeError('storage unavailable')), record_evidence=evidence)
    result = await workflow.run(_visualization_payload(), _context())
    assert result.status == 'accepted' and len(submitted) == 1
    assert 'chart_001：来源为上一统计期' in result.plan.warnings
    assert records[-1]['event'] == 'workflow' and records[-1]['status'] == 'accepted'
    execution = next(item for item in records if item['event'] == 'execution')
    submission = next(item for item in records if item['event'] == 'submission')
    assert execution['outputFiles'][0]['path'] == 'charts/chart.png'
    assert submission['status'] == 'accepted' and submission['planSha256'] == execution['planSha256']
    assert submission['chartIds'] == ['chart_001'] and submission['outputFiles'] == execution['outputFiles']


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('explicit_custom', [False, True])
async def test_production_runtime_wires_pagination_inputs_route_failure_and_semantics_to_durable_state(monkeypatch, explicit_custom):
    """替换模型/绘图外部边界，真实运行analysis闭包与durable reducer。"""
    from smart_reporting.reporting.models import ReportingError
    from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
        _execution_receipt,
        _inspection,
    )
    from smart_reporting.reporting.tests.test_reporting_planner_contracts import (
        _final_attempt_runtime,
    )
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime import analysis, standard_chart_routing
    from smart_reporting.reporting.workflow.runtime import (
        visualization_section_workflow as workflow_module,
    )
    from smart_reporting.reporting.workflow.runtime.chart_inputs import (
        ChartInputFile,
        ChartInputMaterialization,
    )
    from smart_reporting.reporting.workflow.runtime.code_generation import CodeGenerationResult

    runtime, toolkit, run_section = _final_attempt_runtime(monkeypatch, AsyncMock())
    state = initial_state()
    async def apply_durable(_context, command):
        nonlocal state
        state = ReportingStateReducer.apply(state, command).state
    runtime._apply_durable_command = apply_durable
    facts = _visualization_payload()['visualizationFacts'][0]
    facts['factFile'].update(size=2, sha256='a' * 64)
    runtime._visualization_section_fact_projection = AsyncMock(return_value=facts)
    workspace = SimpleNamespace(identity=SimpleNamespace(workspace_key='ws', root='/tmp/ws'))
    runtime._run_workspace = lambda _context: workspace
    runtime.visualization_code_agent_factory = lambda: None
    runtime.code_mode_runtime = object()
    plan = _visualization_plan()
    if explicit_custom:
        plan = _visualization_plan(charts=(plan.charts[0].model_copy(update={'standard_form': 'custom'}),))
    monkeypatch.setattr(analysis.ReportingStructuredOutputExecutor, 'run', AsyncMock(return_value=plan))
    async def prepare(plan, *_args, **_kwargs):
        item = ChartInputFile('inputs/data.json', b'{"columns":["period","value"],"rows":[["2025-01",2]]}')
        return ChartInputMaterialization(files=(item,), entries=({'chartId': plan.charts[0].chart_id,
            'path': item.path, 'sha256': item.sha256},))
    monkeypatch.setattr(analysis, 'prepare_chart_inputs', prepare)
    code = CodeGenerationResult(script_file=FileIdentity(path='charts/charts.py', size=1, sha256='b' * 64),
        execution_receipt=_execution_receipt('charts/charts.py', 1, 'b' * 64, ('charts/chart.png',)),
        visual_inspection_receipts=(_inspection(),))
    monkeypatch.setattr(analysis, 'ReportingCodeGenerationRunner', lambda *_args, **_kwargs: SimpleNamespace(run=AsyncMock(return_value=code)))
    error = ReportingError('route_failed', 'route unavailable')
    error.standard_execution_attempts = ({'status': 'failed', 'routePhase': 'group', 'durationMs': 31},)
    monkeypatch.setattr(standard_chart_routing, 'run_standard_chart_routes', AsyncMock(side_effect=error))
    monkeypatch.setattr(workflow_module, 'review_chart_period_semantics', AsyncMock(return_value=(
        {'code': 'report_chart_period_mismatch', 'chartId': 'section_001-chart_001', 'message': '期间待复核'},)))
    async def workflow_run(workflow, payload, context):
        plan = await workflow.generate_plan(payload, context)
        assert await workflow.review_plan(plan, context)
        await workflow.preflight_plan(plan, context)
        await workflow.run_code(plan, context, diagnostic=None)
        await workflow.submit(plan, (), context)
        return SimpleNamespace(plan=plan)
    monkeypatch.setattr(workflow_module.VisualizationSectionWorkflow, 'run', workflow_run)
    await run_section()
    events = [record['event'] for record in state.payload['visualizationEvidence']]
    assert [event['event'] for event in events] == [
        'original_plan', 'pagination', 'inputs', 'preflight', 'route_fallback', 'coding_started', 'execution',
    ]
    assert events[0]['plan']['charts'][0]['chartId'] == 'chart_001'
    assert list(events[1]['pageMapping'].values()) == [[events[1]['plan']['charts'][0]['chartId']]]
    import hashlib
    assert events[2]['files'][0]['sha256'] == hashlib.sha256(b'{"columns":["period","value"],"rows":[["2025-01",2]]}').hexdigest()
    assert events[2]['sourceFiles'] == [{'path': 'facts/analysis_001.json', 'size': 2, 'sha256': 'a' * 64}]
    assert events[2]['chartInputFiles'] == [{
        'chartId': events[1]['plan']['charts'][0]['chartId'],
        'path': 'inputs/data.json', 'size': 53, 'sha256': events[2]['files'][0]['sha256'],
    }]
    preflight, fallback, coding, execution = events[3:]
    expected = ({'form': 'custom', 'status': 'custom'} if explicit_custom else
                {'form': 'unknown', 'status': 'unsupported', 'diagnosticCode': 'standard_form_unsupported'})
    assert preflight['charts'] == [{'chartId': execution['chartIds'][0], **expected}]
    assert fallback['executionAttempts'][0]['durationMs'] == 31
    assert coding['chartIds'] == execution['chartIds']
    assert {event['planKey'] for event in events[2:]} == {execution['planKey']}
    assert preflight['planSha256'] == fallback['planSha256'] == coding['planSha256'] == execution['planSha256']
    assert execution['status'] == 'completed'
    assert toolkit.submit_visualization_charts.await_count == 1
