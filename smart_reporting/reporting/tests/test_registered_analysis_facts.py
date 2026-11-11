"""正式分析保留回执身份与Decimal值，不借助旧Profile重新计算。"""

from decimal import Decimal

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.semantics.planning import build_metric_planning_context
from smart_reporting.reporting.tests.test_semantic_planning import receipts
from smart_reporting.reporting.tests.test_semantic_selection import selection_context


def analysis_inputs():
    from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisItem
    context = selection_context()
    selection, calculation = receipts(context)
    result = calculation.results[0].model_copy(update={'value': Decimal('300.123456789123456789'),
        'status': 'computed', 'issue_codes': ('data_readiness_unknown',), 'dataset_ids': ('dataset-formal',)})
    view = build_metric_planning_context(context,
        (selection, calculation.model_copy(update={'results': (result,)})), report_revision='initial')
    analysis = DetailedAnalysisItem(analysisId='analysis_001', domain='budget', datasetIds=('dataset-explore',),
        managementQuestion='预算是多少？', primaryMetricFamily='预算', evidenceSummary='正式计算回执',
        suggestedSection='预算核对', fields=('period', 'project_id', 'amount'), metrics=('amount',), periods=(), comparisonBasis=('本期',),
        organizationGrain=('project_id',), actions=('核对已登记预算',), recommendedCharts=(),
        completionConditions=('披露数据限制',), allowedMetricCodes=('budget',),
        allowedFieldRefs=('warehouse.test.budget.amount',))
    return analysis, view, result


def test_analysis_facts_keep_original_result_without_recalculating():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    analysis, view, result = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, view, ())
    assert bundle.metric_context.calculations[0].results[0] == result
    assert bundle.metric_context.calculations[0].results[0].fact_id == 'fact-budget'
    assert bundle.metric_context.calculations[0].results[0].value == Decimal('300.123456789123456789')
    assert bundle.metrics == () and bundle.derived_metrics == ()
    assert '300.123456789123456789' in bundle.model_dump_json(by_alias=True)


@pytest.mark.parametrize('mutation', ['unknown_metric', 'unknown_field', 'wrong_revision'])
def test_analysis_cannot_expand_registered_metric_scope(mutation):
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    analysis, view, _ = analysis_inputs()
    if mutation == 'unknown_metric':
        analysis = analysis.model_copy(update={'allowed_metric_codes': ('forged',)})
    elif mutation == 'unknown_field':
        analysis = analysis.model_copy(update={'allowed_field_refs': ('warehouse.test.hidden.amount',)})
    else:
        view = view.model_copy(update={'report_revision': 'different'})
    with pytest.raises(ReportingError):
        build_registered_analysis_bundle(analysis, view, (), report_revision='initial')


def test_unavailable_calculation_and_unresolved_question_keep_their_reasons():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    analysis, _, _ = analysis_inputs()
    context = selection_context()
    view = build_metric_planning_context(context, receipts(context), report_revision='initial')
    bundle = build_registered_analysis_bundle(analysis, view, ())
    result = bundle.metric_context.calculations[0].results[0]
    assert result.value is None and result.issue_codes == ('missing_data',)
    assert not hasattr(bundle.metric_context, 'coverage')


def test_model_projection_retains_fact_id_and_exact_value():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.workflow.runtime.analysis import (
        _model_facing_deterministic_facts,
    )
    analysis, view, result = analysis_inputs()
    projected = _model_facing_deterministic_facts(build_registered_analysis_bundle(analysis, view, ()))
    assert projected['metricContext']['calculations'][0]['results'][0]['factId'] == result.fact_id
    assert projected['metricContext']['calculations'][0]['results'][0]['value'] == str(result.value)


def test_registered_finding_keeps_fact_pointer_without_rounding_or_claiming_completeness():
    from smart_reporting.reporting.semantics.analysis_facts import (
        build_registered_analysis_bundle,
        build_registered_finding_graph,
    )
    analysis, view, result = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, view, ())
    from smart_reporting.reporting.delivery.artifacts_v1 import Citation
    citation = Citation(citationId='citation_formal', datasetId='dataset-formal',
        requirementId='metric-budget', snapshotHash='b' * 64)
    graph = build_registered_finding_graph((bundle,), context=view, snapshot_hash='a' * 64,
        files={'analysis_001': {'path': 'facts.json', 'sha256': 'c' * 64}}, citations=(citation,), dataset_snapshots={'dataset-formal': 'b' * 64})
    card, = graph.findings
    assert card.fact_refs == (result.fact_id,)
    assert card.metric_versions == (result.metric_version,)
    assert str(result.value) in card.summary
    assert card.citation_ids == ('citation_formal',)
    assert card.source_refs[0].pointer == '/metricContext/calculations/0/results/0'
    assert card.limitations == ('data_readiness_unknown',)
    assert graph.claim_support[0].fact_refs == (result.fact_id,)
    assert graph.question_coverage[0].status == 'partial'


def test_registered_finding_refuses_unrelated_dataset_citation():
    from smart_reporting.reporting.delivery.artifacts_v1 import Citation
    from smart_reporting.reporting.semantics.analysis_facts import (
        build_registered_analysis_bundle,
        build_registered_finding_graph,
    )
    analysis, view, _ = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, view, ())
    citation = Citation(citationId='unrelated', datasetId='exploration-other',
        requirementId='other', snapshotHash='b' * 64)
    graph = build_registered_finding_graph((bundle,), context=view, snapshot_hash='a' * 64,
        files={'analysis_001': {'path': 'facts.json', 'sha256': 'c' * 64}}, citations=(citation,), dataset_snapshots={'dataset-formal': 'b' * 64})
    assert graph.findings[0].evidence_level == 'evidence_missing'
    assert graph.findings[0].citation_ids == ()
    assert graph.claim_support[0].support_status == 'unverified'


def test_registered_finding_does_not_accept_a_forged_snapshot_hash():
    from smart_reporting.reporting.delivery.artifacts_v1 import Citation
    from smart_reporting.reporting.semantics.analysis_facts import (
        build_registered_analysis_bundle,
        build_registered_finding_graph,
    )
    analysis, view, _ = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, view, ())
    citation = Citation(citationId='forged', datasetId='dataset-formal',
        requirementId='metric-budget', snapshotHash='d' * 64)
    graph = build_registered_finding_graph((bundle,), context=view, snapshot_hash='a' * 64,
        files={'analysis_001': {'path': 'facts.json', 'sha256': 'c' * 64}}, citations=(citation,),
        dataset_snapshots={'dataset-formal': 'b' * 64})
    assert graph.findings[0].citation_ids == ()
    assert graph.claim_support[0].support_status == 'unverified'


def test_registered_fact_index_and_editor_resolution_keep_original_identity():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.contracts_v1 import FactRefV1
    from smart_reporting.reporting.trace.fact_index import (
        fact_binding_records,
        fact_pointer,
        fact_pointer_index,
    )
    from smart_reporting.reporting.trace.fact_service import expand_fact_tree, resolve_fact

    analysis, view, result = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, view, ())
    pointer = '/metricContext/calculations/0/results/0'
    assert fact_pointer(bundle, result.fact_id) == pointer
    assert fact_pointer_index(bundle)[result.fact_id] == pointer
    assert fact_binding_records(bundle)[result.fact_id]['entry'] == result.model_dump(mode='json', by_alias=True)
    ref = FactRefV1(analysisId=analysis.analysis_id, fileResourceId='trf-' + 'a' * 20,
        jsonPointer=pointer, factKind='metric', factKey=result.fact_id)
    resolved = resolve_fact(bundle.model_dump_json(by_alias=True).encode(), ref)
    assert resolved['entry']['metricVersion'] == result.metric_version.model_dump(by_alias=True)
    assert resolved['displayValue'] == str(result.value)
    assert resolved['displayUnit'] == result.unit
    assert resolved['inputFactRefs'] == ()
    assert expand_fact_tree(bundle.model_dump_json(by_alias=True).encode(), ref)['factId'] == result.fact_id


@pytest.mark.parametrize('mutation', ['duplicate', 'invalid_context', 'invalid_result'])
def test_registered_fact_document_rejects_corrupt_nested_identity(mutation):
    import json

    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.fact_service import read_fact_document

    analysis, view, _ = analysis_inputs()
    document = build_registered_analysis_bundle(analysis, view, ()).model_dump(mode='json', by_alias=True)
    results = document['metricContext']['calculations'][0]['results']
    if mutation == 'duplicate':
        results.append(dict(results[0]))
    elif mutation == 'invalid_context':
        document['metricContext'] = {'calculations': []}
    else:
        results[0]['value'] = 'NaN'
    with pytest.raises(ReportingError, match='事实文件'):
        read_fact_document(json.dumps(document).encode())


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_materialization_budget_includes_formal_receipt_datasets(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.workflow.runtime import datasets as runtime
    from smart_reporting.reporting.workflow.runtime.base import REPORT_APPROVED_QUERIES_STATE_KEY

    monkeypatch.setattr(runtime, 'MAX_REPORT_INPUTS', 1)
    _, context, _ = analysis_inputs()
    harness = SimpleNamespace(
        _state=lambda _: {REPORT_APPROVED_QUERIES_STATE_KEY: []},
        _envelope=lambda _: SimpleNamespace(file_inputs=('attachment',)),
        _metric_planning_context=AsyncMock(return_value=context),
        _registered_metric_dataset_handles=AsyncMock(return_value=(SimpleNamespace(dataset_id='formal'),)),
        _policy_query_adapters=AsyncMock(side_effect=AssertionError('超预算不得执行数据库查询')),
    )
    with pytest.raises(ReportingError) as caught:
        await runtime.RuntimeDatasetsMixin.materialize_datasets(harness, None, None)
    assert caught.value.code == 'report_dataset_count_invalid'


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_runtime_keeps_supplement_identity_without_certifying_unsupported_cause():
    import hashlib
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.delivery.artifacts_v1 import Citation
    from smart_reporting.reporting.hospital_operation.findings import FindingGraph
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity, ReportingCheckpoint
    from smart_reporting.reporting.workflow.runtime.analysis import RuntimeAnalysisMixin

    analysis, context, result = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, context, ())
    original = json.dumps({'analysisId': analysis.analysis_id,
        'reconciliations': [{'name': '模型自报对账', 'passed': True}],
        'findings': [{'name': '预算增加证明管理改善', 'metricCodes': ['budget'], 'value': 999}]}).encode()
    supplement = FileIdentity(path='supplement.json', size=len(original), sha256=hashlib.sha256(original).hexdigest())
    facts = FileIdentity(path='facts.json', size=1, sha256='a' * 64)
    saved = {}

    async def write(_thread, path, content):
        saved['graph'] = FindingGraph.model_validate_json(content)
        return FileIdentity(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    harness = SimpleNamespace(
        _metric_planning_context=AsyncMock(return_value=context),
        _registered_metric_dataset_handles=AsyncMock(return_value=(SimpleNamespace(dataset_id='dataset-formal', sha256='b' * 64),)),
        _read_identity_model=AsyncMock(return_value=bundle), _read_identity_bytes=AsyncMock(return_value=original),
        _write_immutable_artifact=write,
        _persist_reporting_checkpoint=AsyncMock(side_effect=lambda _, checkpoint: checkpoint),
        _update_reporting_checkpoint=RuntimeAnalysisMixin._update_reporting_checkpoint,
        _merge_checkpoint_files=RuntimeAnalysisMixin._merge_checkpoint_files,
    )
    checkpoint = await RuntimeAnalysisMixin._restore_or_create_finding_graph(harness, run_context=None,
        checkpoint=ReportingCheckpoint(revision=1, phase='analysis', outlineHash='d' * 64, profileCoverage=_coverage()),
        thread_id='thread', report_run_id='run', revision=1, fact_files={analysis.analysis_id: facts},
        analysis_items={analysis.analysis_id: {'analysisId': analysis.analysis_id, 'datasetIds': ['dataset-formal'],
            'evidenceFiles': [supplement.model_dump(by_alias=True)]}},
        citation_bindings=(Citation(citationId='citation_formal', datasetId='dataset-formal',
            requirementId='metric-budget', snapshotHash='b' * 64),))
    graph = saved['graph']
    assert checkpoint.finding_graph_hash == graph.snapshot_hash
    assert graph.findings[0].fact_refs == (result.fact_id,)
    assert all('管理改善' not in card.summary for card in graph.findings)
    assert graph.claim_support[0].kind == 'fact'
    assert any('ClaimSupport' in warning for warning in graph.warnings)
    harness._read_identity_bytes.assert_awaited_once_with('thread', supplement)


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
@pytest.mark.parametrize('already_registered', [False, True])
async def test_actual_analysis_validation_uses_registered_basis_without_profile_state(monkeypatch, already_registered):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from agno.run import RunContext

    from smart_reporting.reporting.data_sources import DatasetHandle
    from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from smart_reporting.reporting.tests.test_dynamic_checkpoint import _coverage
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime import analysis as runtime
    from smart_reporting.reporting.workflow.runtime import base

    analysis, context, _ = analysis_inputs()
    handle = DatasetHandle(dataset_id='dataset-explore', source_id='warehouse', path='dataset.csv',
        row_count=1, size=1, sha256='a' * 64, requirement_id='requirement_001', sql_hash='b' * 64)
    state = {
        base.REPORT_OUTLINE_STATE_KEY: {'title': '预算核对'},
        base.REPORT_DATASET_LINEAGE_STATE_KEY: [], base.REPORT_DATA_REQUIREMENTS_STATE_KEY: [],
        base.REPORT_DETAILED_ANALYSIS_PLAN_STATE_KEY: DetailedAnalysisPlan(
            analyses=(analysis,), datasetIds=analysis.dataset_ids).model_dump(by_alias=True),
        base.REPORT_ANALYSIS_CONTEXT_FILE_STATE_KEY: FileIdentity(path='context.json', size=1, sha256='c' * 64).model_dump(by_alias=True),
        base.REPORT_PROFILE_COVERAGE_STATE_KEY: _coverage().model_dump(by_alias=True),
    }
    captured = {}

    class ValidationCaptured(Exception):
        pass

    async def capture(_thread, _path, payload):
        captured.update(payload)
        raise ValidationCaptured

    from smart_reporting.reporting.hospital_operation.outline import ReportOutline
    outline = ReportOutline(reportType='topic', title='预算核对', sections=[{
        'code': 'section_001', 'sectionNumber': '1', 'title': '预算', 'analysisIds': [analysis.analysis_id]}])
    monkeypatch.setattr(runtime, '_frozen_outline', lambda _: outline)
    harness = SimpleNamespace(
        _feedback=lambda _: None, _state=lambda _: state,
        _scope=lambda _: {'externalRunId': 'run', 'callerThreadId': 'thread', 'threadId': 'thread', 'userId': 'user'},
        state_repository=SimpleNamespace(get_or_create=AsyncMock(return_value=SimpleNamespace(phase=runtime.DurableReportingPhase.ANALYSIS_RUNNING,
            payload={'approvedOutline': outline.model_dump(mode='json', by_alias=True)} if already_registered else {}))),
        _apply_durable_command=AsyncMock(),
        _workflow_result=lambda _: {'jobId': 'job', 'datasets': [handle.public_dict()]},
        _bind_report_document_context=AsyncMock(), _data_shapes=lambda _: (),
        _metric_planning_context=AsyncMock(return_value=context),
        _write_artifact_validation_context=capture,
    )
    with pytest.raises(ValidationCaptured):
        await runtime.RuntimeAnalysisMixin.run_reporting_analysis(harness, None, RunContext(run_id='run', session_id='thread'))
    assert context.metrics[0].id in captured['forbiddenVisibleTerms']
    if already_registered:
        harness._apply_durable_command.assert_not_awaited()
    else:
        command = harness._apply_durable_command.await_args.args[1]
        assert command.name == 'freeze_report_outline'
        assert command.payload['outline']['title'] == '预算核对'
        assert command.payload['outline']['sections'][0]['analysisIds'] == [analysis.analysis_id]


def test_registered_server_table_binds_exact_result_and_verifies_frozen_cell():
    from types import SimpleNamespace

    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.table_builder import build_analysis_tables
    from smart_reporting.reporting.trace.table_quality import evaluate_table_quality

    analysis, context, result = analysis_inputs()
    bundle = build_registered_analysis_bundle(analysis, context, ())
    resource = 'trf-' + 'a' * 20
    built = build_analysis_tables(bundle, fact_file_resource_id=resource)
    assert len(built) == 1
    trace, markdown = built[0]
    assert str(result.value) in markdown
    assert context.metrics[0].name in markdown
    assert result.period.start.isoformat() in markdown and result.period.end.isoformat() in markdown
    cell, = trace.cells
    assert cell.value_selector == 'value'
    assert cell.fact_refs[0].fact_key == result.fact_id
    assert cell.fact_refs[0].json_pointer == '/metricContext/calculations/0/results/0'
    index = SimpleNamespace(report_basis_id=context.basis_id, tables=(trace,), fact_files=(SimpleNamespace(file_resource_id=resource, analysis_id=analysis.analysis_id),))
    checks = evaluate_table_quality(index, markdown, {resource: bundle.model_dump(mode='json', by_alias=True)}, original_markdown=markdown)
    assert checks[trace.table_id].status == 'verified'
    edited = markdown.replace(str(result.value), '999')
    assert evaluate_table_quality(index, edited, {resource: bundle.model_dump(mode='json', by_alias=True)},
        original_markdown=markdown)[trace.table_id].status == 'unknown'


def test_unavailable_registered_table_preserves_reason_without_zero_or_verified_cell():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.table_builder import build_analysis_tables

    analysis, _, _ = analysis_inputs()
    context = selection_context()
    view = build_metric_planning_context(context, receipts(context), report_revision='initial')
    bundle = build_registered_analysis_bundle(analysis, view, ())
    trace, markdown = build_analysis_tables(bundle, fact_file_resource_id='trf-' + 'a' * 20)[0]
    from smart_reporting.reporting.trace.table_quality import _blocks, _grid

    assert '未取得对应范围的数据' in _grid(_blocks(markdown)[trace.table_id])[1][0] and '—' in markdown
    assert trace.cells[0].fact_refs[0].fact_key == 'fact-budget'


@pytest.mark.anyio
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_actual_server_tables_use_frozen_registered_names_and_fact_directory():
    from hashlib import sha256
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.workflow.checkpoint import FileIdentity
    from smart_reporting.reporting.workflow.runtime.sections import RuntimeSectionsMixin

    analysis, context, result = analysis_inputs()
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True).encode()
    identity = FileIdentity(path='facts.json', size=len(content), sha256=sha256(content).hexdigest())
    harness = SimpleNamespace(_scope=lambda _: {'threadId': 'thread'}, _state=lambda _: {},
        _read_identity_bytes=AsyncMock(return_value=content))
    tables, traces, directory, values = await RuntimeSectionsMixin._build_server_tables(harness, None,
        checkpoint=SimpleNamespace(deterministic_fact_files={analysis.analysis_id: identity}),
        outline=SimpleNamespace(sections=(SimpleNamespace(code='budget', analysis_ids=(analysis.analysis_id,)),)))
    assert len(tables) == len(traces) == 1
    assert tables[0].section_code == 'budget' and context.metrics[0].name in tables[0].markdown
    assert directory[result.fact_id] == (analysis.analysis_id, '/metricContext/calculations/0/results/0')
    assert values[result.fact_id] == (str(result.value), result.unit)


@pytest.mark.parametrize('value', [Decimal(0), Decimal('-1.123456789123456789'), Decimal('1E+40')])
def test_registered_table_preserves_zero_negative_and_large_decimal_values(value):
    from types import SimpleNamespace

    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.table_builder import build_analysis_tables
    from smart_reporting.reporting.trace.table_quality import evaluate_table_quality

    analysis, context, result = analysis_inputs()
    calculation = context.calculations[0].model_copy(update={'results': (result.model_copy(update={'value': value}),)})
    context = context.model_copy(update={'calculations': (calculation,)})
    bundle = build_registered_analysis_bundle(analysis, context, ())
    resource = 'trf-' + 'a' * 20
    trace, markdown = build_analysis_tables(bundle, fact_file_resource_id=resource)[0]
    assert format(value, 'f') in markdown
    index = SimpleNamespace(report_basis_id=context.basis_id, tables=(trace,), fact_files=(SimpleNamespace(file_resource_id=resource, analysis_id=analysis.analysis_id),))
    assert evaluate_table_quality(index, markdown, {resource: bundle.model_dump(mode='json', by_alias=True)})[trace.table_id].status == 'verified'


def test_registered_table_partitions_large_grouped_results_without_aggregation():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.semantics.models import DimensionValue
    from smart_reporting.reporting.trace.table_builder import build_analysis_tables

    analysis, context, result = analysis_inputs()
    results = tuple(result.model_copy(update={'fact_id': f'fact-group-{i}', 'value': Decimal(i),
        'dimensions': (DimensionValue(dimension_id='project', value=f'P{i}'),)}) for i in range(1001))
    context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': results}),)})
    built = build_analysis_tables(build_registered_analysis_bundle(analysis, context, ()), fact_file_resource_id='trf-' + 'a' * 20)
    assert [len(trace.cells) for trace, _ in built] == [500, 500, 1]
    assert {cell.fact_refs[0].fact_key for trace, _ in built for cell in trace.cells} == {result.fact_id for result in results}
    assert built[-1][0].cells[0].fact_refs[0].json_pointer.endswith('/results/1000')
    assert 'P1000' in built[-1][1]


@pytest.mark.parametrize('fault', ['basis', 'unit', 'duplicate_fact'])
def test_registered_table_rejects_inconsistent_formal_identity(fault):
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.table_builder import build_analysis_tables

    analysis, context, result = analysis_inputs()
    if fault == 'basis':
        results = (result.model_copy(update={'basis_id': 'foreign-basis'}),)
    elif fault == 'unit':
        results = (result.model_copy(update={'unit': '%'}),)
    else:
        results = (result, result)
    context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': results}),)})
    with pytest.raises(ReportingError, match='正式指标表'):
        build_analysis_tables(build_registered_analysis_bundle(analysis, context, ()), fact_file_resource_id='trf-' + 'a' * 20)


def test_registered_numbers_reach_actual_section_catalog_and_rendering():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.numeric_text import (
        format_fact_value,
        render_frozen_numbers,
    )
    from smart_reporting.reporting.workflow.runtime.sections import _section_number_context

    analysis, context, result = analysis_inputs()
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    catalog, guide = _section_number_context((content,), {}, allowed_fact_ids={result.fact_id})
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    assert catalog[token] == format_fact_value(result.value, result.unit)
    item, = guide
    assert item['factId'] == result.fact_id
    assert item['metricVersion'] == result.metric_version.model_dump(by_alias=True)
    assert item['period'] == result.period.model_dump(mode='json', by_alias=True)
    assert item['issueCodes'] == list(result.issue_codes)
    assert item['references']['value'] == catalog[token]
    assert '数值待核实' not in render_frozen_numbers('预算为' + token, catalog)


def test_registered_number_conflict_revokes_same_id_even_when_rounded_values_match():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.numeric_text import frozen_number_catalog

    analysis, context, result = analysis_inputs()
    original = build_registered_analysis_bundle(analysis, context, ())
    changed = result.model_copy(update={'unit': '%', 'metric_version': result.metric_version.model_copy(update={'revision': 2})})
    context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': (changed,)}),)})
    other = original.model_copy(update={'analysis_id': 'analysis_002', 'metric_context': context})
    catalog = frozen_number_catalog((original.model_dump_json(by_alias=True), other.model_dump_json(by_alias=True)))
    assert catalog and set(catalog.values()) == {'数值待核实'}


def test_unavailable_registered_number_has_guide_reason_and_no_numeric_placeholder():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.numeric_text import (
        frozen_number_catalog,
        frozen_number_guide,
    )

    analysis, _, _ = analysis_inputs()
    context = selection_context()
    view = build_metric_planning_context(context, receipts(context), report_revision='initial')
    content = build_registered_analysis_bundle(analysis, view, ()).model_dump_json(by_alias=True)
    catalog = frozen_number_catalog((content,))
    assert catalog == {}
    guide, = frozen_number_guide((content,), catalog)
    assert guide['status'] == 'unavailable' and guide['issueCodes'] == ['missing_data']
    assert guide['references']['value'] is None


def test_registered_reference_resolver_keeps_decimal_and_original_result_schema():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.semantic_bindings import (
        NumberReferenceResolver,
        resolve_number_references,
    )

    analysis, context, result = analysis_inputs()
    result = result.model_copy(update={'fact_id': 'fact-' + 'b' * 16})
    context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': (result,)}),)})
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    resolver = NumberReferenceResolver((content,))
    resolved = resolver.resolve(token)
    assert resolved is not None
    assert resolved['value'] == result.value and isinstance(resolved['value'], Decimal)
    assert resolved['entry'] == result.model_dump(mode='json', by_alias=True)
    assert resolved['period'] == result.period.model_dump(mode='json', by_alias=True)
    assert 'total' not in resolved['entry'] and 'profileHash' not in resolved['entry']
    selected = resolve_number_references((), (content,), selectors=((result.fact_id, 'value'),))
    assert selected[result.fact_id + ':value']['value'] == result.value
    assert resolver.resolve(token.replace(':value:', ':total:')) is None


def test_registered_number_rendering_signs_reference_using_original_fact():
    from smart_reporting.reporting.semantics.analysis_facts import build_registered_analysis_bundle
    from smart_reporting.reporting.trace.semantic_bindings import render_bound_numbers

    analysis, context, result = analysis_inputs()
    result = result.model_copy(update={'fact_id': 'fact-' + 'b' * 16})
    context = context.model_copy(update={'calculations': (context.calculations[0].model_copy(update={'results': (result,)}),)})
    content = build_registered_analysis_bundle(analysis, context, ()).model_dump_json(by_alias=True)
    token = '{{value:' + result.fact_id + ':value:' + result.unit + '}}'
    markdown, references, notices = render_bound_numbers('预算为' + token + '。', (content,), key='registered-budget')
    assert '300.12' in markdown and '数值待核实' not in markdown
    assert not notices and references[0].token == token
