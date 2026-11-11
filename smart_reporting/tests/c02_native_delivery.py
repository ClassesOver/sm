"""C02正式纠错计算进入原生交付；父状态为夹具，不冒充首次Editor反馈或业务签认。"""

import asyncio
import hashlib
import json
import os
import tempfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from agno.run import RunContext

from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
from smart_reporting.reporting.hospital_operation.narrative_outline import NarrativeOutlineCandidate
from smart_reporting.reporting.hospital_operation.outline import ReportOutline, ReportOutlineSection
from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
from smart_reporting.reporting.workflow.policy_adoption import prepare_policy_adoption_execution
from smart_reporting.reporting.workflow.policy_adoption_analysis import (
    continue_policy_adoption_delivery,
)
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime import sections as section_runtime
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.base import REPORT_WORKFLOW_SCOPE_STATE_KEY
from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle, DataUnderstandingPlan
from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview
from smart_reporting.reporting.workflow.state import ReportingRunState
from smart_reporting.reporting.workspace import WorkspaceReportService
from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution import TaskExecutionKernel, TaskExecutionRepository
from smart_reporting.tests.policy_adoption_public_flow import LocalWorkbookRuntime
from smart_reporting.tests.test_report_basis_persistence import build_identity


async def exercise_c02_native_delivery(ctx, bases, store, source, adoption, calculation, monkeypatch, *,
    expected_value='63.33', after_report=None, section_stage=None, summary_text=None, initial_pipeline=False):
    """错误来源、旧70与新63.33混绑、比率重复乘100均应使实际交付断言失败。"""
    database = create_agent_database(os.environ['REPORTING_MANAGEMENT_TEST_DB_URL'])
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_basis_service, runtime.report_build_identity = bases, build_identity()
    runtime.configuration_provider = SimpleNamespace(vault=ctx['vault'])
    runtime.datasets, runtime.workspace_service = store, store.service
    runtime.workspace_registry = store.service.registry
    runtime.state_repository = ReportingStateRepository(database.async_db)
    runtime._durable_command_lock, runtime._checkpoint_persist_lock = asyncio.Lock(), asyncio.Lock()
    runtime.delivery_settings = ReportDeliverySettings()
    runtime.report_tools = WorkspaceReportService(store.service, data_sources=store)
    runtime.business_evidence_service = ctx['policy_service'].evidence
    runtime._data_understanding_agent = SimpleNamespace(id='c02-scope')
    runtime._analysis_agent = SimpleNamespace(id='c02-analysis')
    runtime._analysis_evidence_agent = SimpleNamespace(model=None)
    runtime._analysis_summary_agent = SimpleNamespace(model=None)
    runtime._narrative_outline_agent = SimpleNamespace(model=None)
    runtime._analysis_thinking_enabled, runtime._analysis_thinking_budget_cap = False, 1024
    runtime.section_generator = SimpleNamespace(model=None)
    runtime.section_recovery, runtime.section_whole_generation = None, True
    runtime._planner_reasoning_effort, runtime.coding_task_registry = None, None
    runtime.code_mode_runtime = LocalWorkbookRuntime()
    manager = ReportingLspProcessManager(command=('false',), request_timeout_seconds=0.2)
    runtime.lsp_manager = manager

    def forbid_supplemental(*args, **kwargs):
        raise AssertionError('C02只用正式计算，不允许模型脚本换算结果。')

    runtime._analysis_script_agent_factory = forbid_supplemental
    root = next(item for item in calculation.results if item.metric_version == calculation.request.metric_version)
    assert root.value.quantize(Decimal('0.01')) == Decimal(expected_value)
    roots = {root.fact_id: root}

    async def planner(agent, payload, context, **kwargs):
        view = await runtime._metric_planning_context(context)
        current_calculation, = view.calculations
        current_root = next(item for item in current_calculation.results if item.metric_version == current_calculation.request.metric_version)
        assert current_root.metric_version.metric_id == 'rate'
        assert current_root.value.quantize(Decimal('0.01')) == {1: Decimal('70'), 2: Decimal('63.33')}[current_root.metric_version.revision]
        roots[current_root.fact_id] = current_root
        original = current_root.metric_version.revision == 1
        if agent is runtime._data_understanding_agent:
            return DataUnderstandingPlan.model_validate({'tables': [
                {'sourceId': 'warehouse', 'table': 'test.' + table, 'periodColumn': 'period',
                    'periodGranularity': 'date', 'role': '预算期间'} for table in (('project_rates',) if original else ('budget', 'actual'))]})
        if agent is runtime._analysis_agent:
            actual_calculation, = payload['metricContext']['calculations']
            assert actual_calculation['receiptId'] == current_calculation.receipt_id
            return AnalysisBundle.model_validate({'analyses': [{'code': 'execution_rate', 'domain': 'budget',
                'description': '正式总体执行率核对', 'managementQuestion': '总体预算执行率是多少？',
                'primaryMetricFamily': '预算执行率', 'requirementIds': ['c02-details'],
                'analysisName': '总体执行率', 'periodRoles': ['current'], 'seriesGranularity': None}],
                'requirements': [{'requirementId': 'c02-details', 'sourceId': 'warehouse',
                    'tables': [{'table': 'test.project_rates' if original else 'test.budget', 'periodColumn': 'period',
                        'periodGranularity': 'date', 'measureColumns': ['fraction' if original else 'amount']}],
                    'dimensionColumns': ['period', 'project_id'], 'grainColumns': ['period', 'project_id'], 'relations': []}]})
        if agent is runtime._analysis_evidence_agent:
            return AnalysisEvidenceDecision(requiresSupplementalEvidence=False,
                reason='总体比率使用已登记合计计算，不推断未取数的项目趋势。', missingFacts=(), codingRequirements=())
        if agent is runtime._analysis_summary_agent:
            return AnalysisSummaryDraft(summary=summary_text or ('按项目比率均值计算，本报告执行率为70%。' if original else '实际合计190元、预算合计300元，总体执行率为63.33%。'),
                warnings=('机械核验不代表业务签认。',))
        assert agent is runtime._narrative_outline_agent
        planning = payload['planningContext']
        return NarrativeOutlineCandidate(title='C02项目均值原报告' if original else 'C02总体执行率纠错', snapshotHash=planning['snapshotHash'],
            sections=[{'title': '总体执行率与计算依据',
                'findingIds': [item['findingId'] for item in planning['findings']],
                'objective': '核对合计比率及计算依据', 'groupingReason': '同一正式比率的依据'}])

    runtime._run_planner = planner
    tasks = TaskExecutionRepository(database.async_db)
    await tasks.initialize()
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(store.service, tasks),
        model_profiles=DEFAULT_MODEL_PROFILES)
    runtime.task_runner = SimpleNamespace(repository=tasks, start=coordinator.start, run=coordinator.run)

    async def stage(_agent, schema, name, payload, **kwargs):
        if name == 'semantics':
            return SectionSemanticReview(interpretations=())
        if name == 'plan':
            fact = next(item for item in payload['factCatalog'] if item['factId'] in roots)
            selected_root = roots[fact['factId']]
            return schema.model_validate({'kind': 'render', 'sectionCode': payload['sectionGoal']['sectionCode'],
                'blocks': [{'blockId': 'c02-rate', 'objective': '正式总体执行率', 'claimIds': ['c02-rate']}],
                'claims': [{'claimId': 'c02-rate', 'metricCode': 'rate', 'value': str(selected_root.value),
                    'managementQuestionRef': 'analysis_001', 'currentPeriod': '[2026-11-01, 2026-12-01)',
                    'citationIds': ['citation_001'], 'factIds': [fact['factId']],
                    'findingIds': list(payload['sectionWorkItem']['findingIds'])}]})
        assert name == 'content'
        fact_id = payload['sectionPlan']['claims'][0]['factIds'][0]
        description = '按项目完成比率的均值计算。' if roots[fact_id].metric_version.revision == 1 else '按实际合计除以预算合计计算。'
        return schema.model_validate({'blocks': [{'blockId': 'c02-rate',
            'markdown': '本报告执行率为{{value:' + fact_id + ':value:%}}。' + description}]})

    context = RunContext(run_id=source.run_id, session_id=source.session_id, user_id='7',
        session_state={REPORT_WORKFLOW_SCOPE_STATE_KEY: source.as_state()})
    repository = runtime.state_repository
    try:
        await repository.register_run(report_run_id=source.run_id, external_run_id=source.external_run_id,
            agno_session_id=source.session_id, agno_run_id=source.run_id, thread_id=source.caller_thread_id,
            owner_user_id=source.user_id, database=source.database, company_id=source.company_id, entrypoint='agentos')
        outline = ReportOutline(reportType='topic', title='C02原报告类型夹具', sections=(ReportOutlineSection(
            code='section_001', sectionNumber='1', title='执行率', analysisIds=('analysis_001',)),))
        await repository.create(ReportingRunState.initial(report_run_id=source.run_id,
            external_run_id=source.external_run_id, thread_id=source.caller_thread_id, owner_user_id=source.user_id,
            payload={'approvedOutline': outline.model_dump(mode='json', by_alias=True)}))
        execution = await prepare_policy_adoption_execution(runtime, context, request_id=adoption.confirmation.request_id)
        with monkeypatch.context() as patch:
            patch.setattr(section_runtime, '_run_section_stage', section_stage or stage)
            if initial_pipeline:
                from agno.workflow.types import StepInput

                from smart_reporting.reporting.structured_output.execution import (
                    ReportingStructuredOutputExecutor,
                )
                from smart_reporting.reporting.workflow.policy_adoption_analysis import (
                    prepare_policy_adoption_narrative,
                    run_policy_adoption_evidence,
                )
                from smart_reporting.reporting.workflow.runtime.phase_models import (
                    VisualizationPlanDraft,
                )

                # 仅借用既有 fixture 准备已登记分析；装配、渲染、发布实际走 execution=None。
                await run_policy_adoption_evidence(runtime, context, execution)
                initial_context = await prepare_policy_adoption_narrative(runtime, context, execution)
                initial_context.session_state['report_request_context']['deliveryFormat'] = 'xlsx'
                result = initial_context.session_state['report_workflow_result']
                prepared = await runtime.report_tools.report_prepare_dataset(
                    [item['datasetId'] for item in result['datasets']], run_context=runtime._tool_context(initial_context))
                await runtime.report_tools.bind_page_layout(prepared['jobId'],
                    runtime.delivery_settings.page_layout.model_dump(mode='json', by_alias=True),
                    run_context=runtime._tool_context(initial_context))
                result.update(jobId=prepared['jobId'], revision=execution.output_revision - 1)
                runtime._vision_enabled = False
                runtime.vision_reviewer = None
                runtime.visualization_generator = SimpleNamespace(model=None)

                async def no_chart_plan(executor, *args, **kwargs):
                    assert executor.agent is runtime.visualization_generator
                    return VisualizationPlanDraft(charts=(), warnings=('本例只验工作簿声明，不验图表。',))

                patch.setattr(ReportingStructuredOutputExecutor, 'run', no_chart_plan)
                await runtime.run_report_draft(StepInput(input='首次工作簿成稿'), initial_context)
                await runtime.assemble_report(StepInput(input='装配首次工作簿'), initial_context)
                await runtime._render_and_validate(initial_context)
                published = await runtime.publish_report(StepInput(input='发布首次工作簿'), initial_context)
            else:
                published = await continue_policy_adoption_delivery(runtime, context, execution)
        content = published.content
        if initial_pipeline:
            assert content['deliveryFormat'] == 'xlsx' and content['xlsxPath']
            assert content['revision'] == execution.output_revision
        from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
        from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
        from smart_reporting.reporting.trace.issue_content import evaluate_calculation_content
        from smart_reporting.reporting.workflow.checkpoint import FileIdentity

        child = await repository.get(execution.scope.run_id)
        manifest = await runtime._read_identity_model(execution.scope.workspace_key,
            FileIdentity.model_validate(child.payload['result']['manifest']), ReportArtifactManifest)
        assert manifest.report_basis_id == calculation.basis_id == execution.basis_id
        markdown = (await runtime._read_identity_bytes(execution.scope.workspace_key,
            FileIdentity(path=manifest.markdown.path, size=manifest.markdown.size, sha256=manifest.markdown.sha256))).decode()
        trace = manifest.trace_index
        assert trace is not None
        trace_raw = await runtime._read_identity_bytes(execution.scope.workspace_key,
            FileIdentity(path=trace.path, size=trace.size, sha256=trace.sha256))
        index = RevisionTraceIndexV1.model_validate_json(trace_raw)
        sources = {}
        for entry in index.fact_files:
            file = next(item for item in index.files if item.resource_id == entry.file_resource_id)
            sources[file.resource_id] = await runtime._read_identity_bytes(execution.scope.workspace_key,
                FileIdentity(path=file.path, size=file.size, sha256=file.sha256))
        presentation = evaluate_calculation_content(index, markdown, sources, calculation, report_revision='initial')
        assert presentation['factPresentationVerified'] and presentation['coveredFactIds'] == [root.fact_id], presentation
        from urllib.parse import urlsplit

        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from smart_reporting.report_editor import (
            InMemoryReportEditorRepository,
            ReportEditorGrantService,
            ReportEditorService,
        )
        from smart_reporting.reporting.delivery.publishing import (
            ReportArtifactPersistenceService,
            ReportDownloadGrantService,
            ReportDownloadHttpService,
            create_report_download_router,
        )
        from smart_reporting.reporting.tests.delivery_fakes import (
            InMemoryDownloadGrantRepository,
            InMemoryReportArtifactRepository,
        )
        from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY

        artifacts = InMemoryReportArtifactRepository()
        runtime.artifact_persistence = ReportArtifactPersistenceService(artifacts, store.service)
        runtime.download_grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
        runtime.editor_grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
        runtime.report_public_base_url = 'https://reports.test'
        scope = execution.scope.as_state()
        delivery = await runtime.issue_http_publication(thread_id=scope['threadId'],
            caller_thread_id=scope['callerThreadId'], user_id=scope['userId'], workflow_session_id=scope['sessionId'],
            workflow_run_id=execution.scope.run_id, output=published,
            dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {**scope, 'threadId': scope['callerThreadId']}})
        grant = urlsplit(delivery['editor']['openUrl']).path.rsplit('/', 1)[-1]
        _, session = await runtime.editor_grants.exchange(grant)
        editor = ReportEditorService(state_repository=repository, workspace_registry=store.service.registry,
            workspace=store.service, report_basis_service=bases, recalculation_runtime=runtime,
            business_evidence_service=runtime.business_evidence_service)
        editor_context = await editor.context_for_session(session)
        assert editor_context.workflow_run_id == execution.scope.run_id and editor_context.revision == execution.output_revision
        assert (await editor.trace.require_index(editor_context)).report_basis_id == execution.basis_id
        assert (await editor.read_document(editor_context)).markdown == markdown
        app = FastAPI()
        app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts)))
        files = []
        evidence_dir = Path(tempfile.gettempdir()) / f'smart-reporting-c02-native-{os.getpid()}-{"-".join(execution.requested_outputs)}'
        evidence_dir.mkdir(exist_ok=True)
        (evidence_dir / 'trace-index.json').write_bytes(trace_raw)
        (evidence_dir / 'report.md').write_text(markdown)
        for resource_id, raw in sources.items():
            (evidence_dir / (resource_id + '.json')).write_bytes(raw)
        (evidence_dir / 'calculation.json').write_text(calculation.model_dump_json(by_alias=True, indent=2) + '\n')
        (evidence_dir / 'execution.json').write_text(execution.model_dump_json(by_alias=True, indent=2) + '\n')
        (evidence_dir / 'artifact-manifest.json').write_bytes(await runtime._read_identity_bytes(
            execution.scope.workspace_key, FileIdentity.model_validate(child.payload['result']['manifest'])))
        for fmt in execution.requested_outputs:
            label = 'word' if fmt == 'docx' else fmt
            identity = {'path': content[label + 'Path'], 'sha256': content[label + 'Sha256'], 'size': content[label + 'Size']}
            raw, _ = await store.service.afile_bytes(execution.scope.workspace_key, identity['path'])
            assert hashlib.sha256(raw).hexdigest() == identity['sha256'] and len(raw) == identity['size']
            async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
                response = await client.get(delivery[label]['downloadUrl'])
                assert response.status_code == 200 and response.content == raw
            verify_c02_output(fmt, raw, root, expected_value=expected_value)
            name = 'c02-corrected.' + fmt
            (evidence_dir / name).write_bytes(raw)
            files.append({'file': name, **identity})
        (evidence_dir / 'evidence.json').write_text(json.dumps({'caseId': 'C02',
            'basisId': execution.basis_id, 'calculationReceiptId': calculation.receipt_id,
            'rootFactId': root.fact_id, 'expectedValue': expected_value, 'files': files,
            'factPresentation': presentation,
            'newEditorVerified': True, 'httpDownloadsVerified': True,
            'businessApproval': 'not_performed', 'parentEditorFlowVerified': False}, ensure_ascii=False, indent=2) + '\n')
        if after_report is not None:
            return await after_report(SimpleNamespace(runtime=runtime, database=database, editor=editor,
                context=editor_context, stage=stage, calculation=calculation, delivery=delivery,
                evidence_dir=evidence_dir, content=content, execution=execution, manifest=manifest, download_app=app))
    finally:
        await manager.aclose()
        await database.async_engine.dispose()
        database.sync_engine.dispose()


def verify_c02_output(fmt, raw, root, *, expected_value='63.33'):
    """检查实际文件内的63.33，不用生成成功状态或下载链接替代。"""
    if fmt == 'pptx':
        with ZipFile(BytesIO(raw)) as package:
            text = ''.join(package.read(name).decode() for name in package.namelist()
                if name.startswith('ppt/slides/slide') and name.endswith('.xml'))
        assert expected_value in text and '执行率' in text
    elif fmt == 'pdf':
        from pypdf import PdfReader
        assert any(expected_value in page.extract_text() for page in PdfReader(BytesIO(raw)).pages)
    elif fmt == 'docx':
        from docx import Document
        document = Document(BytesIO(raw))
        assert any(expected_value in item.text for item in document.paragraphs) or any(
            expected_value in cell.text for table in document.tables for row in table.rows for cell in row.cells)
    else:
        from openpyxl import load_workbook
        with ZipFile(BytesIO(raw)) as package:
            cells = json.loads(package.read('smart-reporting/source-mapping.json'))['sources']['cells']
        selected = [cell for cell in cells if cell['factId'] == root.fact_id]
        assert len(selected) == 1  # 现有映射登记专题页；汇总页另核对实际对应行。
        book = load_workbook(BytesIO(raw), data_only=True)
        try:
            for source in selected:
                assert source['basisId'] == root.basis_id and source['metricVersion'] == root.metric_version.model_dump(mode='json', by_alias=True)
                assert source['exactValue'] == str(root.value)
                cell = book[source['sheet']][source['cell']]
                assert Decimal(str(cell.value)).quantize(Decimal('0.01')) == Decimal(expected_value)
                assert Decimal(str(cell.value)) == root.value and cell.offset(column=1).value == '%'
                summary = [row for row in book['汇总'].iter_rows(values_only=True)
                    if row[:3] == (source['sheet'], source['analysisId'], cell.offset(column=-1).value)]
                assert len(summary) == 1 and Decimal(str(summary[0][3])) == root.value and summary[0][4] == '%'
        finally:
            book.close()
