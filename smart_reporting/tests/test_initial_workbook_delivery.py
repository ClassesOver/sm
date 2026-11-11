"""空报告经原生工作流首次交付；模型与查询端口受控，不借用口径采用修订。"""

import asyncio
import hashlib
import json
import os
import re
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid4
from zipfile import ZipFile

import duckdb
import pytest
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunStatus
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlglot import parse_one

from smart_reporting.management.report_bases import ReportBasisService
from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
from smart_reporting.report_editor import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    ReportEditorService,
)
from smart_reporting.reporting.business_knowledge.retrieval import DocumentRevisionRef
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.data_source.materialization import CsvMaterializer
from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable, QueryResult
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    create_report_download_router,
)
from smart_reporting.reporting.hospital_operation.narrative_outline import NarrativeOutlineCandidate
from smart_reporting.reporting.semantics.basis import BasisCalculationReceipt
from smart_reporting.reporting.semantics.selection import MetricSelectionProposal
from smart_reporting.reporting.structured_output.execution import ReportingStructuredOutputExecutor
from smart_reporting.reporting.tests.delivery_fakes import (
    InMemoryDownloadGrantRepository,
    InMemoryReportArtifactRepository,
)
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
from smart_reporting.reporting.workflow.identity import (
    VerifiedReportingIdentity,
    bind_verified_reporting_identity,
)
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime import sections as section_runtime
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.models import (
    AnalysisBundle,
    DataUnderstandingPlan,
    GeneratedQueryBatch,
    NormalizedReportPrompt,
)
from smart_reporting.reporting.workflow.runtime.phase_models import VisualizationPlanDraft
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    reporting_scope_keys,
)
from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution import TaskExecutionKernel, TaskExecutionRepository
from smart_reporting.tests.policy_adoption_public_flow import LocalWorkbookRuntime
from smart_reporting.tests.test_business_document_ingestion import metadata, register
from smart_reporting.tests.test_report_basis_persistence import auth_context as auth_context
from smart_reporting.tests.test_report_basis_persistence import basis_context as basis_context
from smart_reporting.tests.test_report_basis_persistence import build_identity
from smart_reporting.tests.test_report_basis_persistence import document_context as document_context
from smart_reporting.tests.test_report_basis_persistence import index_context as index_context
from smart_reporting.tests.test_report_basis_persistence import receipt_snapshot as receipt_snapshot
from smart_reporting.tests.test_report_issue_c02 import publish_c02_definitions

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


class _OfflinePlanningModel(OpenAIChat):
    """离线字节上界计数，不让合成模型名触发 tokenizer 网络请求。"""

    def count_tokens(self, messages, *, output_schema=None, **kwargs):
        return len(json.dumps({'messages': [item.to_dict() for item in messages],
            'schema': output_schema.model_json_schema() if output_schema else None},
            ensure_ascii=False, default=str).encode())


async def exercise_initial_workbook_delivery(
    basis_context, document_context, receipt_snapshot, monkeypatch, *, fact_read_failure=False,
    entry_runner=None, delivery_format='xlsx', knowledge_registration_failure=False,
    narrative_parsing_failure=False,
):
    """丢失首次摘要登记、重复递增编号或借用采用回执均应使本例失败。"""
    ctx = basis_context
    await publish_c02_definitions(ctx)
    documents, token, scope = document_context[:3]
    now = documents.clock()
    statement = '建议核对采购付款安排，解释本期预算执行率时区分支付时点与计算公式'
    original_clock = documents.clock
    documents.clock = lambda: now - timedelta(minutes=2)
    try:
        await register(document_context, 'initial-context', body=(statement + '。').encode(),
            details=metadata(id='initial-context', title='首次报告合成背景', kind='background',
                eventTime='2026-11-03', appliesTo=[{'kind': 'metric', 'id': 'rate'}]))
        await documents.ingest_revision(await documents.claim_next())
        detail = await documents.get_document(token, scope, 'initial-context')
        await documents.review_revision(token, scope, 'initial-context', 1, decision='approved',
            reason='隔离夹具核对原文，不代表业务签认', expected_version=detail['revisions'][0]['stateVersion'])
    finally:
        documents.clock = original_clock
    release = await ctx['policy_service'].evidence.publish(token, scope, request_id='initial-context',
        kind='background', revision_ids=(DocumentRevisionRef(document_id='initial-context', revision=1),))
    await ctx['policy_service'].set_default(token, scope, 'budget_execution',
        policy_version={'policyId': 'monthly-budget', 'revision': 2}, expected_version=2,
        background_release_id=release.release_id)

    store = receipt_snapshot[0]['dataset_store']
    database = create_agent_database(os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    repository = ReportingStateRepository(database.async_db)
    tasks = TaskExecutionRepository(database.async_db)
    await tasks.initialize()
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(store.service, tasks),
        model_profiles=DEFAULT_MODEL_PROFILES)
    artifacts = InMemoryReportArtifactRepository()
    agent = Agent(model=_OfflinePlanningModel(id='isolated-unused-model', api_key='isolated-unused-key'), telemetry=False)
    manager = ReportingLspProcessManager(command=('false',), request_timeout_seconds=0.2)
    runtime = ReportWorkflowRuntime(db=database.async_db, reporting_agent_template=agent,
        task_runner=SimpleNamespace(repository=tasks, start=coordinator.start, run=coordinator.run),
        visualization_generator=agent, section_generator=agent, vision_enabled=False,
        code_mode_runtime=LocalWorkbookRuntime(), lsp_manager=manager,
        workspace_service=store.service, workspace_registry=store.service.registry,
        registry=None, profiles=None, planner_enable_thinking=False, state_repository=repository,
        configuration_provider=ctx['provider'], business_evidence_service=ctx['policy_service'].evidence,
        report_build_identity=build_identity(),
        download_grants=ReportDownloadGrantService(InMemoryDownloadGrantRepository()),
        artifact_persistence=ReportArtifactPersistenceService(artifacts, store.service),
        editor_grants=ReportEditorGrantService(InMemoryReportEditorRepository(), secret='i' * 32),
        report_public_base_url='https://reports.test')
    bases = runtime.report_basis_service
    assert isinstance(bases, ReportBasisService)
    fault_calls = []
    knowledge_fault_calls = []
    narrative_fault_calls = []
    if narrative_parsing_failure:
        from smart_reporting.reporting.workflow.runtime import publication

        render_slides = runtime._render_pptx

        def unavailable_paragraphs(block):
            narrative_fault_calls.append(block.block_id)
            raise OSError('injected slide narrative paragraph parsing failure')

        async def render_with_parsing_fault(*args, **kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(publication, 'narrative_paragraphs', unavailable_paragraphs)
                return await render_slides(*args, **kwargs)

        monkeypatch.setattr(runtime, '_render_pptx', render_with_parsing_fault)
    if knowledge_registration_failure:
        from smart_reporting.reporting.workflow.runtime import business_evidence
        from smart_reporting.reporting.workflow.runtime.slides import SlideOutline

        registration = business_evidence.register_section_knowledge
        read_model = runtime._read_identity_model

        async def unreadable_outline(thread_id, file, model):
            if model is SlideOutline:
                knowledge_fault_calls.append(file.path)
                raise OSError('injected slide knowledge registration failure')
            return await read_model(thread_id, file, model)

        async def registration_with_fault(*args, **kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(runtime, '_read_identity_model', unreadable_outline)
                return await registration(*args, **kwargs)

        monkeypatch.setattr(business_evidence, 'register_section_knowledge', registration_with_fault)
    if fact_read_failure:
        from smart_reporting.reporting.workflow.runtime import publication

        verify = runtime._verify_claim_fact_bindings

        def unreadable(raw):
            fault_calls.append('read_fact_document')
            raise OSError('injected initial publication fact read failure')

        async def verify_with_fault(*args, **kwargs):
            with monkeypatch.context() as patch:
                patch.setattr(publication, 'read_fact_document', unreadable)
                return await verify(*args, **kwargs)

        monkeypatch.setattr(runtime, '_verify_claim_fact_bindings', verify_with_fault)
    run_id, thread_id = 'first-' + delivery_format + '-' + uuid4().hex, 'thread-basis'
    assert await repository.get(run_id) is None
    queries, planner_inputs, roots = [], [], {}

    async def planner(current_agent, payload, context, **kwargs):
        planner_inputs.append({'agent': current_agent.id, 'payload': payload})
        if current_agent is runtime._request_normalizer:
            return NormalizedReportPrompt(reportType='topic', domains=['budget'], scenario='budget_execution',
                deliveryFormat=delivery_format, displayUnit='%', period={'start': '2026-11-01', 'end': '2026-11-30'},
                questions=[{'id': 'q-rate', 'text': '执行率及当期背景是什么？'}])
        if current_agent is runtime._metric_selection_agent:
            return MetricSelectionProposal.model_validate({'questions': [{'questionId': 'q-rate',
                'candidates': [{'metricVersion': {'metricId': 'rate', 'revision': 1},
                    'reason': '问题要求核对已发布项目完成比率口径。'}]}]})
        view = await runtime._metric_planning_context(context)
        calculation, = [item for item in view.calculations if item.request.period == view.request.period]
        root = next(item for item in calculation.results if item.metric_version == calculation.request.metric_version)
        assert root.value == Decimal('70')
        roots[root.fact_id] = root
        if current_agent is runtime._data_understanding_agent:
            return DataUnderstandingPlan.model_validate({'tables': [{'sourceId': 'warehouse',
                'table': 'test.project_rates', 'periodColumn': 'period', 'periodGranularity': 'date', 'role': '预算期间'}]})
        if current_agent is runtime._analysis_agent:
            return AnalysisBundle.model_validate({'analyses': [{'code': 'execution_rate', 'domain': 'budget',
                'description': '核对正式执行率及来源依据', 'managementQuestion': '执行率及当期背景是什么？',
                'primaryMetricFamily': '预算执行率', 'requirementIds': ['initial-details'],
                'analysisName': '执行率', 'periodRoles': ['current'], 'seriesGranularity': None}],
                'requirements': [{'requirementId': 'initial-details', 'sourceId': 'warehouse',
                    'tables': [{'table': 'test.project_rates', 'periodColumn': 'period', 'periodGranularity': 'date',
                        'measureColumns': ['fraction']}], 'dimensionColumns': ['period', 'project_id'],
                    'grainColumns': ['period', 'project_id'], 'relations': []}]})
        if current_agent is runtime._sql_agent:
            return GeneratedQueryBatch.model_validate({'queries': [{'requirementId': 'initial-details',
                'sourceId': 'warehouse', 'periodRole': 'current',
                'sql': "SELECT period, project_id, fraction FROM test.project_rates WHERE period >= '2026-11-01' AND period < '2026-12-01'"}]})
        if current_agent is runtime._analysis_evidence_agent:
            return AnalysisEvidenceDecision(requiresSupplementalEvidence=False,
                reason='登记指标已足以回答比率问题，不补造因果观察。', missingFacts=(), codingRequirements=())
        if current_agent is runtime._analysis_summary_agent:
            return AnalysisSummaryDraft(summary=statement + '。', warnings=('合成夹具，不代表业务批准。',))
        assert current_agent is runtime._narrative_outline_agent
        planning = payload['planningContext']
        return NarrativeOutlineCandidate(title='首次工作簿执行率与依据', snapshotHash=planning['snapshotHash'],
            sections=[{'title': '执行率与当期背景', 'findingIds': [item['findingId'] for item in planning['findings']],
                'objective': '核对执行率并区别解释支持', 'groupingReason': '同一问题的计算与解释依据'}])

    async def stage(_agent, schema, name, payload, **kwargs):
        if name == 'semantics':
            evidence, = [item for item in payload['knowledgeEvidence'] if item['documentId'] == 'initial-context']
            return schema.model_validate({'interpretations': [{'claimId': ref['claimId'],
                'claimKind': 'recommendation', 'kindEvidence': ['建议'],
                'metricVersion': {'metricId': 'rate', 'revision': 1},
                'knowledgeRelations': [{'evidenceId': evidence['evidenceId'], 'relationship': 'supports',
                    'explanationType': 'recommendation', 'sourceEvidence': [statement], 'claimEvidence': [statement]}]}
                for ref in payload['references'] if ref.get('referenceKind') == 'narrative']})
        root, = roots.values()
        if name == 'plan':
            return schema.model_validate({'kind': 'render', 'sectionCode': payload['sectionGoal']['sectionCode'],
                'blocks': [{'blockId': 'first-rate', 'objective': '核对正式比率', 'claimIds': ['first-rate']},
                    {'blockId': 'analysis_001', 'objective': '说明背景', 'claimIds': ['first-rate']}],
                'claims': [{'claimId': 'first-rate', 'metricCode': 'rate', 'value': str(root.value),
                    'managementQuestionRef': 'analysis_001', 'currentPeriod': '[2026-11-01, 2026-12-01)',
                    'citationIds': ['citation_001'], 'factIds': [root.fact_id],
                    'findingIds': list(payload['sectionWorkItem']['findingIds'])}]})
        assert name == 'content'
        return schema.model_validate({'blocks': [{'blockId': 'first-rate',
            'markdown': '本报告执行率为{{value:' + root.fact_id + ':value:%}}。'},
            {'blockId': 'analysis_001', 'markdown': statement + '。'}]})

    async def no_chart_plan(executor, *args, **kwargs):
        assert executor.agent is runtime.visualization_generator
        return VisualizationPlanDraft(charts=(), warnings=('本例仅验首次知识工作簿，不验图表。',))

    monkeypatch.setattr(runtime, '_run_planner', planner)
    monkeypatch.setattr(section_runtime, '_run_section_stage', stage)
    monkeypatch.setattr(ReportingStructuredOutputExecutor, 'run', no_chart_plan)
    connection = duckdb.connect()
    # 画像使用 StarRocks 函数名；仅在隔离查询端口映射其分位数语义。
    connection.execute('CREATE MACRO percentile_approx(x, p) AS approx_quantile(CAST(x AS DOUBLE), p)')
    connection.execute('CREATE SCHEMA test')
    connection.execute('CREATE TABLE test.project_rates(project_id VARCHAR, fraction DECIMAL(18,8), period DATE)')
    connection.execute("INSERT INTO test.project_rates VALUES ('A',0.9,'2026-11-01'),('B',0.5,'2026-11-20')")

    async def catalog(adapter):
        context = await bases.load_execution_context(run_id, scope, user_id='7', thread_id=thread_id, vault=ctx['vault'])
        return tuple(CatalogTable(source_id=table.source_id, database=table.database, name=table.name,
            columns=tuple(CatalogColumn(column.name, column.data_type, column.nullable, column.description)
                for column in table.columns), description=table.description)
            for table in context.metadata[adapter.config.id].tables)

    def execute(adapter, sql, parameters=None):
        from smart_reporting.reporting.data_source.sql_validation import (
            validate_starrocks_read_only_sql,
        )

        normalized = (adapter._bound_sql(sql, parameters) if parameters is not None else
            validate_starrocks_read_only_sql(sql, database=adapter.config.database, allowed_tables=adapter.allowed_tables))
        queries.append(normalized)
        cursor = connection.cursor()
        cursor.execute(parse_one(normalized, read='starrocks').sql(dialect='duckdb'), parameters or {})
        return tuple(item[0] for item in cursor.description), tuple(cursor.fetchall())

    async def query(adapter, sql):
        columns, rows = execute(adapter, sql)
        return QueryResult(columns=columns, rows=rows, byte_count=len(repr(rows).encode()))

    async def query_bound(adapter, sql, parameters):
        columns, rows = execute(adapter, sql, parameters)
        return QueryResult(columns=columns, rows=rows, byte_count=len(repr(rows).encode()))

    async def bound(adapter, sql, parameters, *, max_bytes=None):
        columns, rows = execute(adapter, sql, parameters)
        writer = CsvMaterializer(columns, max_bytes=max_bytes)
        writer.append(rows)
        return writer.finish()

    async def materialize(adapter, sql, *, max_bytes=None):
        columns, rows = execute(adapter, sql)
        writer = CsvMaterializer(columns, max_bytes=max_bytes)
        writer.append(rows)
        return writer.finish()

    monkeypatch.setattr(StarRocksDataSourceAdapter, 'catalog', catalog)
    monkeypatch.setattr(StarRocksDataSourceAdapter, 'query', query)
    monkeypatch.setattr(StarRocksDataSourceAdapter, 'query_bound', query_bound)
    monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', bound)
    monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize', materialize)
    entry_label = 'http-' if entry_runner is not None else ''
    format_label = 'slides' if delivery_format == 'pptx' else 'workbook'
    mode = ('narrative-fault' if narrative_parsing_failure else 'knowledge-fault' if knowledge_registration_failure
        else 'fault' if fact_read_failure else 'normal')
    output_dir = Path('/tmp') / f'smart-reporting-first-{entry_label}{format_label}-{os.getpid()}-{mode}'
    output_dir.mkdir(exist_ok=True)
    try:
        entry_evidence = {'entrypoint': 'native-workflow-with-verified-cli-identity'}
        if entry_runner is not None:
            output, entry_evidence = await entry_runner(runtime, run_id, thread_id, scope, queries)
        else:
            with bind_verified_reporting_identity(VerifiedReportingIdentity(scope.database, scope.company_id, '7', thread_id, 'cli')):
                workflow = runtime.workflow()
                output = await asyncio.wait_for(workflow.arun(f'生成2026年11月预算执行{delivery_format}报告，核对执行率及当期背景',
                    run_id=run_id, session_id=thread_id, user_id='7', stream=False,
                    dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {'database': scope.database,
                        'companyId': scope.company_id, 'threadId': thread_id, 'userId': '7'}}), timeout=90)
        (output_dir / 'workflow-output.json').write_text(json.dumps(output.to_dict(), ensure_ascii=False, indent=2, default=str))
        assert output.status is RunStatus.completed, output.to_dict()
        content = output.content
        assert content['revision'] == 1 and content['deliveryFormat'] == delivery_format
        gate_codes = {item['code'] for item in content['publicationGate']['issues']}
        if fact_read_failure:
            assert fault_calls == ['read_fact_document']
            assert {'report_claim_fact_file_unreadable', 'report_claim_fact_unknown'} <= gate_codes
            assert not content['publicationGate']['formalReleaseAllowed']
        else:
            assert 'report_claim_fact_unknown' not in gate_codes
        if narrative_parsing_failure:
            assert narrative_fault_calls == ['analysis_001']
            assert not content['validation']['ok']
            assert 'pptx_narrative_paragraphs_unavailable' in {item['code'] for item in content['validation']['issues']}
        durable = await repository.get(run_id)
        workspace_key = reporting_scope_keys(database=scope.database, company_id=scope.company_id,
            user_id='7', thread_id=thread_id, run_id=run_id).workspace_key
        basis = await bases.load_report_basis(run_id, scope, user_id='7', thread_id=thread_id)
        assert basis.background_release_id == release.release_id
        assert await bases.load_basis_receipts(run_id, scope, user_id='7', thread_id=thread_id,
            report_revision='policy-adoption-registration') == ()
        receipts = await bases.load_basis_receipts(run_id, scope, user_id='7', thread_id=thread_id, report_revision='initial')
        calculation, = [item for item in receipts if isinstance(item, BasisCalculationReceipt)
            and item.request.period == basis.request_summary.period]
        grant = urlsplit(content['editor']['openUrl']).path.rsplit('/', 1)[-1]
        _, session = await runtime.editor_grants.exchange(grant)
        editor = ReportEditorService(state_repository=repository, workspace_registry=store.service.registry,
            workspace=store.service, report_basis_service=bases, business_evidence_service=runtime.business_evidence_service)
        editor_context = await editor.context_for_session(session)
        assert editor_context.revision == 1
        manifest = await runtime._read_identity_model(workspace_key,
            FileIdentity.model_validate(durable.payload['result']['manifest']), ReportArtifactManifest)
        assert manifest.revision == content['revision'] == 1
        assert manifest.report_basis_id == basis.id
        document = await editor.read_document(editor_context)
        index = await editor.trace.require_index(editor_context)
        subject, = [item for item in index.subject_bindings if item.narrative_reference is not None
            and item.narrative_reference.analysis_id == 'analysis_001']
        validation = await editor.trace.validate(editor_context, document.markdown, document.sha256)
        support, = [item for item in validation['quality']['claimSupport'] if item['subjectId'] == subject.subject_id]
        expected_support = 'unverified' if knowledge_registration_failure else 'supported'
        assert support['supportStatus'] == expected_support
        delivered = [item for item in content['validation']['claimSupport']
            if item['support'].get('subjectId') == subject.subject_id]
        assert delivered and all(item['support']['supportStatus'] == expected_support for item in delivered)
        if knowledge_registration_failure:
            assert len(knowledge_fault_calls) == 1
            assert index.knowledge_registration_status == 'unavailable'
        app = FastAPI()
        app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
        async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
            response = await client.get(content[delivery_format]['downloadUrl'])
            assert response.status_code == 200
            raw = response.content
        assert hashlib.sha256(raw).hexdigest() == content[delivery_format]['sha256']
        assert len(raw) == content[delivery_format]['size']
        with ZipFile(BytesIO(raw)) as package:
            assert package.testzip() is None
            if delivery_format == 'xlsx':
                source_mapping = json.loads(package.read('smart-reporting/source-mapping.json'))
                assert source_mapping['sources']['claims'] == content['validation']['claimSupport']
        if delivery_format == 'xlsx':
            book = load_workbook(BytesIO(raw), data_only=True)
            try:
                summary = '\n'.join(str(cell.value or '') for row in book['汇总'] for cell in row)
            finally:
                book.close()
        else:
            from pptx import Presentation

            deck = Presentation(BytesIO(raw))
            summary = '\n'.join(shape.text for slide in deck.slides for shape in slide.shapes if shape.has_text_frame)
            assert any(Decimal(value) == Decimal('70')
                for value in re.findall(r'(?<![\d.])(\d+(?:\.\d+)?)\s*%', summary))
        label = '（建议，待核实）' if knowledge_registration_failure else '（建议）'
        assert statement + '。' + label in summary
        assert '（建议）' not in document.markdown
        detail = await documents.get_document(token, scope, 'initial-context')
        await documents.review_revision(token, scope, 'initial-context', 1, decision='revoked',
            reason='首次报告来源撤销合成测试', expected_version=detail['revisions'][0]['stateVersion'])
        withdrawn = await editor.trace.validate(editor_context, document.markdown, document.sha256)
        support, = [item for item in withdrawn['quality']['claimSupport'] if item['subjectId'] == subject.subject_id]
        assert support['supportStatus'] == 'unverified' and not support['evidenceRefs']
        assert await editor.read_document(editor_context) == document
        async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
            after = await client.get(content[delivery_format]['downloadUrl'])
            assert after.status_code == 200 and after.content == raw
        (output_dir / f'report.{delivery_format}').write_bytes(raw)
        (output_dir / 'report.md').write_text(document.markdown)
        (output_dir / 'summary.txt').write_text(summary)
        (output_dir / 'manifest.json').write_text(manifest.model_dump_json(by_alias=True, indent=2))
        (output_dir / 'trace-index.json').write_text(index.model_dump_json(by_alias=True, indent=2))
        (output_dir / 'basis.json').write_text(basis.model_dump_json(by_alias=True, indent=2))
        (output_dir / 'calculation.json').write_text(calculation.model_dump_json(by_alias=True, indent=2))
        (output_dir / 'receipts.json').write_text(json.dumps(
            [item.model_dump(mode='json', by_alias=True) for item in receipts], ensure_ascii=False, indent=2))
        checkpoint = durable.payload['workflowCheckpoint']
        (output_dir / 'checkpoint.json').write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2))
        files_dir = output_dir / 'registered-files'
        files_dir.mkdir(exist_ok=True)
        for file in index.files:
            identity = FileIdentity(path=file.path, size=file.size, sha256=file.sha256)
            (files_dir / file.resource_id).write_bytes(await runtime._read_identity_bytes(workspace_key, identity))
        for position, file in enumerate(checkpoint['workbookSummaryFiles']):
            (output_dir / f'summary-registration-{position}.json').write_bytes(
                await runtime._read_identity_bytes(workspace_key, FileIdentity.model_validate(file)))
        if delivery_format == 'pptx':
            (output_dir / 'slide-outline.json').write_bytes(await runtime._read_identity_bytes(
                workspace_key, FileIdentity.model_validate(checkpoint['slideOutlineFile'])))
        (output_dir / 'evidence.json').write_text(json.dumps({**entry_evidence,
            'revision': 1, 'deliveryFormat': delivery_format, 'noAdoptionReceipts': True, 'queries': queries, 'plannerInputs': planner_inputs,
            'factReadFailure': fact_read_failure, 'faultCalls': fault_calls,
            'knowledgeRegistrationFailure': knowledge_registration_failure,
            'knowledgeFaultCalls': knowledge_fault_calls, 'knowledgeRegistrationStatus': index.knowledge_registration_status,
            'narrativeParsingFailure': narrative_parsing_failure, 'narrativeFaultCalls': narrative_fault_calls,
            'beforeRevocation': validation, 'afterRevocation': withdrawn,
            'sha256': hashlib.sha256(raw).hexdigest(), 'historicalDownloadUnchanged': True,
            'realModel': False, 'realStarRocks': False, 'businessApproval': 'not_performed'},
            ensure_ascii=False, indent=2, default=str))
    finally:
        connection.close()
        await manager.aclose()
        await database.async_engine.dispose()
        database.sync_engine.dispose()


async def test_first_native_workflow_creates_revision_one_workbook_with_knowledge(
    basis_context, document_context, receipt_snapshot, monkeypatch,
):
    await exercise_initial_workbook_delivery(basis_context, document_context, receipt_snapshot, monkeypatch)
