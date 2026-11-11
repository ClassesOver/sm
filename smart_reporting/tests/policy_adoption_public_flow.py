"""公开确认、准备登记故障及显式续跑至原生交付；仅模型和业务查询端口受控。"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.run import RunStatus
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.management.report_bases import ReportBasisService
from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
from smart_reporting.report_editor.policy_recovery import create_policy_recovery_workflow
from smart_reporting.report_editor.recalculation import (
    create_policy_adoption_workflow,
    read_recalculation_run,
    read_task,
    recalculation_queue_config,
)
from smart_reporting.report_editor.slides import ReportSlidesEditorService
from smart_reporting.report_editor.slides_api import (
    SLIDES_SESSION_COOKIE,
    create_report_slides_editor_router,
)
from smart_reporting.report_editor.workbook import ReportWorkbookEditorService
from smart_reporting.report_editor.workbook_api import (
    WORKBOOK_SESSION_COOKIE,
    create_report_workbook_editor_router,
)
from smart_reporting.reporting.code_agent.lsp_process import ReportingLspProcessManager
from smart_reporting.reporting.code_mode import ScriptProcessResult
from smart_reporting.reporting.delivery.publishing import (
    ReportDownloadHttpService,
    create_report_download_router,
)
from smart_reporting.reporting.delivery.settings import ReportDeliverySettings
from smart_reporting.reporting.hospital_operation.narrative_outline import NarrativeOutlineCandidate
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import ToolkitRuntime
from smart_reporting.reporting.workflow.execution import ReportingTaskCoordinator
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime import sections as section_runtime
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
    AnalysisSummaryDraft,
)
from smart_reporting.reporting.workflow.runtime.models import AnalysisBundle, DataUnderstandingPlan
from smart_reporting.reporting.workflow.runtime.phase_models import SectionSemanticReview
from smart_reporting.reporting.workspace import WorkspaceReportService
from smart_reporting.task_execution import TaskExecutionKernel, TaskExecutionRepository
from smart_reporting.tests.test_report_basis_persistence import build_identity


class LocalWorkbookRuntime(ToolkitRuntime):
    """执行原生生成器给出的脚本，不用预制工作簿替代产物。"""

    def __init__(self):
        super().__init__()
        self.executions = []

    async def execute_script_process(self, session_id, host, path, **kwargs):
        self.executions.append(session_id)
        process = subprocess.run([sys.executable, path], cwd=host.identity.root, capture_output=True, text=True)
        return ScriptProcessResult(SimpleNamespace(status='ok' if process.returncode == 0 else 'error',
            stdout=process.stdout, stderr=process.stderr, traceback=None), process.returncode)


async def exercise_public_policy_adoption(parent_runtime, database, management, source_editor, engine, queries, monkeypatch, *,
        recover_preparation=False):
    source = ReportEditorContext.model_validate(source_editor)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_basis_service = ReportBasisService(management['scopes'])
    runtime.report_build_identity = build_identity()
    runtime.configuration_provider = SimpleNamespace(vault=management['vault'])
    runtime.datasets = parent_runtime.datasets
    runtime.workspace_service = parent_runtime.workspace_service
    runtime.workspace_registry = runtime.workspace_service.registry
    runtime.state_repository = ReportingStateRepository(database.async_db)
    runtime._durable_command_lock = asyncio.Lock()
    runtime._checkpoint_persist_lock = asyncio.Lock()
    runtime.delivery_settings = ReportDeliverySettings()
    runtime.report_tools = WorkspaceReportService(runtime.workspace_service, data_sources=runtime.datasets)
    runtime.business_evidence_service = management['policy_service'].evidence
    runtime.artifact_persistence = parent_runtime.artifact_persistence
    runtime.download_grants = parent_runtime.download_grants
    runtime.editor_grants = parent_runtime.editor_grants
    runtime.report_public_base_url = 'https://reports.test'
    runtime._data_understanding_agent = SimpleNamespace(id='adoption-scope')
    runtime._analysis_agent = SimpleNamespace(id='adoption-analysis')
    runtime._analysis_evidence_agent = SimpleNamespace(model=None)
    runtime._analysis_summary_agent = SimpleNamespace(model=None)
    runtime._narrative_outline_agent = SimpleNamespace(model=None)
    runtime._analysis_thinking_enabled = False
    runtime._analysis_thinking_budget_cap = 1024
    def no_supplemental_script(*args, **kwargs):
        raise AssertionError('本用例只核对正式预算，不允许补证脚本扩大数据范围')
    runtime._analysis_script_agent_factory = no_supplemental_script
    runtime.coding_task_registry = None
    runtime.section_generator = SimpleNamespace(model=None)
    runtime.section_recovery = None
    runtime.section_whole_generation = True
    runtime._planner_reasoning_effort = None
    local = LocalWorkbookRuntime()
    runtime.code_mode_runtime = local
    manager = ReportingLspProcessManager(command=('false',), request_timeout_seconds=0.2)
    runtime.lsp_manager = manager
    model_stages, native_tasks = [], []
    downloaded_files = {}

    async def planner(agent, payload, context, **kwargs):
        assert context.run_id != source.workflow_run_id
        if agent is runtime._data_understanding_agent:
            model_stages.append('scope')
            return DataUnderstandingPlan.model_validate({'tables': [{'sourceId': 'warehouse', 'table': 'test.budget',
                'periodColumn': 'period', 'periodGranularity': 'date', 'role': '预算期间'}]})
        if agent is runtime._analysis_agent:
            model_stages.append('analysis')
            calculation, = payload['metricContext']['calculations']
            assert Decimal(calculation['results'][0]['value']) == 200
            return AnalysisBundle.model_validate({'analyses': [{'code': 'new_budget', 'domain': 'budget',
                'description': '新口径预算值核对', 'managementQuestion': '新口径预算是多少？',
                'primaryMetricFamily': '预算', 'requirementIds': ['new-budget-details'],
                'analysisName': '新口径预算核对', 'periodRoles': ['current'], 'seriesGranularity': None}],
                'requirements': [{'requirementId': 'new-budget-details', 'sourceId': 'warehouse',
                    'tables': [{'table': 'test.budget', 'periodColumn': 'period',
                        'periodGranularity': 'date', 'measureColumns': ['amount']}],
                    'dimensionColumns': ['period', 'project_id'], 'grainColumns': ['period', 'project_id'], 'relations': []}]})
        if agent is runtime._analysis_evidence_agent:
            model_stages.append('evidence')
            return AnalysisEvidenceDecision(requiresSupplementalEvidence=False,
                reason='仅核对正式预算，不推断缺少实际额的执行率。', missingFacts=(), codingRequirements=())
        if agent is runtime._analysis_summary_agent:
            model_stages.append('summary')
            return AnalysisSummaryDraft(summary='新口径预算额为200，缺少实际发生额，执行率尚未回答。',
                warnings=('不代表业务批准。',))
        assert agent is runtime._narrative_outline_agent
        model_stages.append('narrative')
        planning = payload['planningContext']
        return NarrativeOutlineCandidate(title='新口径预算分析', snapshotHash=planning['snapshotHash'],
            sections=[{'title': '预算核对与证据限制',
                'findingIds': [item['findingId'] for item in planning['findings']],
                'objective': '解释新预算及执行率缺项', 'groupingReason': '同一问题的事实与限制'}])

    runtime._run_planner = planner
    tasks = TaskExecutionRepository(database.async_db)
    await tasks.initialize()
    coordinator = ReportingTaskCoordinator(tasks, TaskExecutionKernel(runtime.workspace_service, tasks),
        model_profiles=DEFAULT_MODEL_PROFILES)

    async def run_task(scope, *, parent_run_id, executor):
        assert parent_run_id != source.workflow_run_id
        async def invoke(invocation):
            native_tasks.append(scope.external_run_id)
            return await executor(invocation)
        return await coordinator.run(scope, parent_run_id=parent_run_id, executor=invoke)

    runtime.task_runner = SimpleNamespace(repository=tasks, start=coordinator.start, run=run_task)

    async def stage(_agent, schema, name, payload, **kwargs):
        model_stages.append('section-' + name)
        if name == 'semantics':
            return SectionSemanticReview(interpretations=())
        if name == 'plan':
            fact, = payload['factCatalog']
            assert Decimal(fact['value']) == 200
            return schema.model_validate({'kind': 'render', 'sectionCode': payload['sectionGoal']['sectionCode'],
                'blocks': [{'blockId': 'new-budget', 'objective': '新预算与限制', 'claimIds': ['new-budget']}],
                'claims': [{'claimId': 'new-budget', 'metricCode': 'budget', 'value': '200',
                    'managementQuestionRef': 'analysis_001', 'currentPeriod': '[2026-11-01, 2026-12-01)',
                    'citationIds': ['citation_001'], 'factIds': [fact['factId']],
                    'findingIds': list(payload['sectionWorkItem']['findingIds'])}]})
        assert name == 'content'
        fact_id = payload['sectionPlan']['claims'][0]['factIds'][0]
        return schema.model_validate({'blocks': [{'blockId': 'new-budget',
            'markdown': '新口径预算额为{{value:' + fact_id + ':value:CNY}}；缺少实际额，执行率尚未回答。'}]})

    policies = management['policy_service']
    current = await policies.get(management['token'], management['scope'], 'monthly-budget')
    changed = {key: value for key, value in current['draft']['document'].items() if key not in ('scopeId', 'revision')}
    editor = ReportEditorService(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service,
        report_basis_service=runtime.report_basis_service, recalculation_runtime=runtime,
        recalculation_database=database.async_db)
    editor.recalculation_durable = True
    config = recalculation_queue_config()
    config.poll_interval = 0.05
    def resolve_component(kind, component_id):
        if kind != 'workflow':
            return None
        if component_id == 'report-editor-policy-adoption':
            return create_policy_adoption_workflow(editor, runtime=runtime, database=database.async_db)
        if component_id == 'report-editor-policy-recovery':
            return create_policy_recovery_workflow(editor, runtime=runtime, database=database.async_db)
        return None

    worker = QueueWorker(store=resolve_queue_store(config, database.async_db), config=config,
        resolve_component=resolve_component)
    editor.recalculation_queue_worker = worker
    app = FastAPI()
    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.settings import ManagementSettings
    app.include_router(create_management_router(management['scopes'].auth,
        ManagementSettings(public_origin='https://reports.test'), report_runtime=runtime))
    app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor, cookie_secure=False))
    native_options = dict(state_repository=runtime.state_repository,
        workspace_registry=runtime.workspace_registry, workspace=runtime.workspace_service)
    slides = ReportSlidesEditorService(**native_options)
    workbooks = ReportWorkbookEditorService(**native_options)
    static_dir = Path(__file__).resolve().parents[1] / 'report_editor' / 'static'
    app.include_router(create_report_slides_editor_router(runtime.editor_grants, slides=slides,
        static_dir=static_dir, cookie_secure=False))
    app.include_router(create_report_workbook_editor_router(runtime.editor_grants, workbooks=workbooks,
        static_dir=static_dir, cookie_secure=False))
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants,
        runtime.artifact_persistence.repository)))
    prefix = f'/reports/v1/editor/{source.report_id}/{source.revision}/api'
    request_id = 'first-public-policy-adoption'
    apply_command = runtime._apply_durable_command
    preparation_fault = {}
    async def fail_before_preparation_registration(context, command, **kwargs):
        prefix = 'adoption-document-job:' if source.delivery_format == 'document' else 'adoption-analysis-preparation:'
        if not preparation_fault and command.command_id.startswith(prefix):
            preparation_fault['identity'] = command.payload['artifact']
            raise OSError('preparation file written but registration response unavailable')
        return await apply_command(context, command, **kwargs)

    before_queries = len(queries)
    before_source = await runtime.state_repository.get(source.workflow_run_id)
    original_document = await editor.read_document(source)
    assert '300' in original_document.markdown
    assert await read_task(editor, source, request_id) is None
    assert not any(item.get('request', {}).get('operation') == 'adopt_policy'
        for item in before_source.payload.get('reportEditorRecalculations', {}).values())
    await worker.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(section_runtime, '_run_section_stage', stage)
            if recover_preparation:
                patch.setattr(runtime, '_apply_durable_command', fail_before_preparation_registration)
            async with AsyncClient(transport=ASGITransport(app=app), base_url='https://reports.test') as client:
                grant, _ = await runtime.editor_grants.issue(source)
                await client.get('/reports/v1/editor/open/' + grant, follow_redirects=False)
                headers = {'origin': 'https://reports.test',
                    'x-csrf-token': runtime.editor_grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
                issue = await client.post(prefix + '/issue-reviews', headers=headers,
                    json={'issueId': 'issue-policy-scope', 'objectRefs': [(await editor.trace.require_index(source)).report_basis_id],
                        'category': 'policy', 'description': '本次只应核对项目A，不能将项目B并入预算总额。'})
                assert issue.status_code == 200 and issue.json()['review']['status'] == 'open', issue.text
                client.cookies.set(SESSION_COOKIE, management['token'], path='/management')
                admin_headers = {'origin': 'https://reports.test', 'x-csrf-token': csrf_token(management['token'])}
                admin_scope = {'scopeDatabase': management['scope'].database, 'companyId': management['scope'].company_id}
                issue_path = '/management/api/v1/report-issue-reviews/issue-policy-scope'
                proposal = {'changeSummary': '明确限定项目A预算范围',
                    'counterexample': '原始A=100、B=200，原总体300不代表A；翻倍后A应为200而非600。'}
                accepted = await client.post(issue_path + '/decision', headers=admin_headers, json={**admin_scope,
                    'expectedVersion': 1, 'status': 'accepted', 'proposal': proposal, 'decisionReason': '采纳项目范围纠错；独立核对原始项目A行，不代表C02执行率关闭。'})
                assert accepted.status_code == 200, accepted.text
                await policies.save_draft(management['token'], management['scope'], {**changed, 'name': '连续验收新口径',
                    'filters': [{'fieldRef': 'warehouse.test.budget.project_id', 'operator': 'eq', 'values': ['A']}]}, expected_version=1)
                await policies.publish(management['token'], management['scope'], 'monthly-budget', expected_version=2)
                linked = await client.post(issue_path + '/decision', headers=admin_headers, json={**admin_scope,
                    'expectedVersion': 2, 'status': 'accepted', 'proposal': proposal, 'decisionReason': '正式范围口径已显式发布，等待回归和新报告核验。',
                    'correctedVersions': [{'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 2}]})
                assert linked.status_code == 200 and linked.json()['version'] == 3, linked.text
                with engine.begin() as connection:
                    connection.exec_driver_sql('UPDATE test.budget SET amount=amount*2')
                preview_response = await client.post(prefix + '/policy-adoption-preview', headers=headers,
                    json={'parentRevision': source.revision, 'expectedSha256': original_document.sha256,
                        'policyVersion': {'policyId': 'monthly-budget', 'revision': 2}})
                assert preview_response.status_code == 200, preview_response.text
                preview = preview_response.json()
                request = {'requestId': request_id, 'parentRevision': source.revision,
                    'expectedSha256': original_document.sha256, 'operation': 'adopt_policy',
                    'confirmation': {'requestId': request_id,
                        'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
                        'previewHash': preview['previewHash'], 'questionChoices': [{'questionId': 'q-rate',
                            'metricVersion': {'metricId': 'budget', 'revision': 1},
                            'reason': '仅核对预算额，缺少实际额时不认为执行率已回答。'}]}}
                response = await client.post(prefix + '/recalculations', headers=headers, json=request)
                assert response.status_code == 202, response.text
                submitted = response.json()
                task_id = submitted['taskId']

                async def wait_delivery():
                    while True:
                        run = await read_recalculation_run(editor, source, task_id, database=database.async_db)
                        assert run.run_id == submitted['execution']['runId']
                        assert run.status not in {RunStatus.error, RunStatus.cancelled}, run
                        if run.status == RunStatus.completed:
                            return
                        await asyncio.sleep(0.05)

                await asyncio.wait_for(wait_delivery(), timeout=180)
                completed = await read_task(editor, source, request_id)
                if recover_preparation:
                    assert preparation_fault and completed.status == 'pending', completed
                    # 未补登记前不自动重跑；公开核对必须能看见真实落盘候选。
                    preparation_path = prefix + f'/recalculations/{task_id}/preparation'
                    inspected_response = await client.get(preparation_path)
                    assert inspected_response.status_code == 200, inspected_response.text
                    inspected = inspected_response.json()
                    kind = 'document' if source.delivery_format == 'document' else 'analysis'
                    candidate = inspected[kind]
                    assert candidate['status'] == 'awaiting_confirmation', inspected
                    assert candidate['identity'] == preparation_fault['identity']
                    assert len(queries) == before_queries + 1
                    # 原生执行终态与票据终态独立，等待票据完成后才明确恢复。
                    async def original_ticket_ended():
                        while True:
                            ticket = await worker.store.get_job(submitted['execution']['runId'])
                            if ticket['status'] in {'completed', 'failed', 'cancelled'}:
                                return ticket
                            await asyncio.sleep(0.05)
                    original_ticket = await asyncio.wait_for(original_ticket_ended(), timeout=10)
                    await worker.stop()
                    runtime.state_repository = ReportingStateRepository(database.async_db)
                    editor.state_repository = runtime.state_repository
                    runtime.report_basis_service = ReportBasisService(management['scopes'])
                    runtime.report_tools = WorkspaceReportService(runtime.workspace_service, data_sources=runtime.datasets)
                    worker = QueueWorker(store=resolve_queue_store(config, database.async_db), config=config,
                        resolve_component=resolve_component)
                    editor.recalculation_queue_worker = worker
                    resume_payload = {'kind': kind, 'identity': candidate['identity'],
                        'expectedStateVersion': inspected['stateVersion']}
                    resume = editor.resume_recalculation_preparation
                    async def lose_resume_response(*args, **kwargs):
                        from smart_reporting.reporting.models import ReportingError

                        await resume(*args, **kwargs)
                        raise ReportingError('report_editor_recalculation_unavailable', '续跑已接受但HTTP响应丢失，请先读原票据。')
                    if source.delivery_format == 'pptx':
                        with monkeypatch.context() as lost:
                            lost.setattr(editor, 'resume_recalculation_preparation', lose_resume_response)
                            resumed = await client.post(preparation_path + '/resume', headers=headers, json=resume_payload)
                        assert resumed.status_code == 503, resumed.text
                    else:
                        resumed = await client.post(preparation_path + '/resume', headers=headers, json=resume_payload)
                        assert resumed.status_code == 202, resumed.text
                        assert resumed.json()['recoveryId'] == candidate['recoveryId']
                    recovery_id = candidate['recoveryId']
                    recovered_state = await client.get(preparation_path + '/recoveries/' + recovery_id)
                    assert recovered_state.status_code == 200
                    await worker.start()
                    async def recovered_delivery():
                        while True:
                            response = await client.get(preparation_path + '/recoveries/' + recovery_id)
                            assert response.status_code == 200, response.text
                            ticket = response.json()
                            assert ticket['status'] not in {'error', 'cancelled', 'paused'}, ticket
                            loaded = await read_task(editor, source, request_id)
                            if loaded.status == 'completed' and ticket['status'] == 'completed':
                                return loaded
                            assert not (ticket['status'] == 'completed' and loaded.status != 'completed'), ticket
                            await asyncio.sleep(0.05)
                    completed = await asyncio.wait_for(recovered_delivery(), timeout=180)
                    assert (await worker.store.get_job(submitted['execution']['runId'])) == original_ticket
                assert completed.status == 'completed', completed
                execution = completed.result.execution
                assert execution.parent_basis_id == completed.basis_id
                assert execution.basis_id != completed.basis_id and execution.scope.run_id != source.workflow_run_id
                assert completed.result.business_approval == 'not_performed'
                assert len(queries) == before_queries + 1
                assert model_stages[:5] == ['scope', 'analysis', 'evidence', 'summary', 'narrative']
                assert all(model_stages.count(name) == 1 for name in ('scope', 'analysis', 'evidence', 'summary', 'narrative'))
                child = await runtime.state_repository.get(execution.scope.run_id)
                child_before = child.payload
                receipt = await runtime.report_basis_service.read_policy_adoption(source.workflow_run_id,
                    management['scope'], user_id=source.scope['userId'], thread_id=source.scope['callerThreadId'],
                    request_id=task_id)
                assert receipt.basis_id == execution.basis_id and receipt.target_run_id == execution.scope.run_id
                assert len(native_tasks) == (2 if set(execution.requested_outputs) <= {'pdf', 'docx'} else 1)
                recovered = await client.get(prefix + f'/recalculations/{task_id}/delivery')
                assert recovered.status_code == 200, recovered.text
                delivery = recovered.json()['delivery']
                for output in execution.requested_outputs:
                    label = 'word' if output == 'docx' else output
                    downloaded = await client.get(delivery[label]['downloadUrl'])
                    assert downloaded.status_code == 200
                    actual = next(file for file in completed.result.artifacts if file.path.endswith('.' + output))
                    assert hashlib.sha256(downloaded.content).hexdigest() == actual.sha256
                    verify_actual_output(output, downloaded.content, execution.basis_id)
                    downloaded_files[output] = downloaded.content
                from smart_reporting.management.report_issue_delivery_checks import (
                    check_adopted_delivery,
                )
                from smart_reporting.reporting.semantics.basis import BasisCalculationReceipt
                target_receipts = await runtime.report_basis_service.load_basis_receipts(execution.scope.run_id,
                    management['scope'], user_id=source.scope['userId'], thread_id=source.scope['callerThreadId'],
                    report_revision='initial')
                calculation = next(item for item in target_receipts if isinstance(item, BasisCalculationReceipt))
                regression_request = {**admin_scope, 'requestId': 'verify-project-A', 'expectedIssueVersion': 3,
                    'caseId': 'project-A-budget', 'targetRunId': execution.scope.run_id, 'targetReportRevision': 'initial',
                    'calculationReceiptId': calculation.receipt_id,
                    'expectationReason': '独立合成原始行项目A预算100，经本次明确翻倍后为200；项目B排除，不代表执行率。',
                    'assertions': [{'factId': calculation.results[0].fact_id, 'expectedStatus': 'computed', 'expectedValue': '200', 'unit': 'CNY'}]}
                regression = await client.post(issue_path + '/regressions', headers=admin_headers, json=regression_request)
                assert regression.status_code == 200 and regression.json()['status'] == 'passed', regression.text
                resolution = await client.post(issue_path + '/resolution-evidence-check', headers=admin_headers, json={**admin_scope,
                    'expectedIssueVersion': 3, 'regressionReceiptIds': [regression.json()['receiptId']]})
                assert resolution.status_code == 200, resolution.text
                evidence = resolution.json()
                assert evidence['regressionEvidenceReady'] and evidence['originalEvidenceReady'] and evidence['deliveryReady'], evidence
                assert evidence['factPresentationReady'] is True, evidence
                assert evidence['businessApproval'] == 'not_performed' and evidence['issueClosed'] is False
                read_issue = await client.get(prefix + '/issue-reviews', params={'issueId': 'issue-policy-scope'})
                assert read_issue.status_code == 200 and read_issue.json()['items'][0]['review']['status'] == 'accepted'
                assert (await client.post(issue_path + '/decision', headers=admin_headers, json={**admin_scope,
                    'expectedVersion': 3, 'status': 'resolved', 'decisionReason': '只有机械证据，不得伪造业务签认'})).status_code == 409
                delivery_state_version = (await runtime.state_repository.get(execution.scope.run_id)).state_version
                delivery_check = await check_adopted_delivery(runtime, receipt, management['scope'],
                    parent_run_id=source.workflow_run_id, user_id=source.scope['userId'], thread_id=source.scope['callerThreadId'], calculation=calculation)
                assert delivery_check['deliveryVerified'] is True, delivery_check
                assert delivery_check['factPresentationVerified'] is True, delivery_check
                assert delivery_check['coveredFactIds'] == [calculation.results[0].fact_id]
                assert not delivery_check['contentIssues']
                assert {item['format'] for item in delivery_check['deliveryArtifacts']} == set(execution.requested_outputs)
                assert delivery_check['outputRevision'] == execution.output_revision
                assert delivery_check['validationPassed'] == completed.result.validation_passed
                other = calculation.model_copy(update={'receipt_id': 'not-the-published-calculation'})
                unrelated = await check_adopted_delivery(runtime, receipt, management['scope'],
                    parent_run_id=source.workflow_run_id, user_id=source.scope['userId'],
                    thread_id=source.scope['callerThreadId'], calculation=other)
                assert unrelated['deliveryVerified'] is True and unrelated['factPresentationVerified'] is False
                assert unrelated['contentIssues'][0]['code'] == 'management_issue_report_fact_uncovered'
                from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
                from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
                from smart_reporting.reporting.workflow.checkpoint import FileIdentity
                saved_manifest = await runtime._read_identity_model(execution.scope.workspace_key,
                    FileIdentity.model_validate(child.payload['result']['manifest']), ReportArtifactManifest)
                trace_file = saved_manifest.trace_index
                trace_index = await runtime._read_identity_model(execution.scope.workspace_key,
                    FileIdentity(path=trace_file.path, size=trace_file.size, sha256=trace_file.sha256), RevisionTraceIndexV1)
                fact_file = next(file for file in trace_index.files if file.resource_id == trace_index.fact_files[0].file_resource_id)
                fact_identity = FileIdentity(path=fact_file.path, size=fact_file.size, sha256=fact_file.sha256)
                fact_bytes = await runtime._read_identity_bytes(execution.scope.workspace_key, fact_identity, max_bytes=fact_identity.size)
                await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, fact_file.path, b'changed', overwrite=True)
                try:
                    changed_fact = await check_adopted_delivery(runtime, receipt, management['scope'],
                        parent_run_id=source.workflow_run_id, user_id=source.scope['userId'],
                        thread_id=source.scope['callerThreadId'], calculation=calculation)
                    assert changed_fact['deliveryVerified'] is True and changed_fact['factPresentationVerified'] is False
                    assert changed_fact['contentIssues'][0]['code'] == 'management_issue_report_content_unavailable'
                    assert len(changed_fact['deliveryArtifacts']) == len(execution.requested_outputs)
                finally:
                    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, fact_file.path, fact_bytes, overwrite=True)
                file = completed.result.artifacts[0]
                original_bytes = await runtime._read_identity_bytes(execution.scope.workspace_key, file, max_bytes=file.size)
                await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, file.path, b'changed', overwrite=True)
                try:
                    changed = await check_adopted_delivery(runtime, receipt, management['scope'],
                        parent_run_id=source.workflow_run_id, user_id=source.scope['userId'], thread_id=source.scope['callerThreadId'])
                    assert changed['deliveryVerified'] is False
                    assert changed['deliveryIssues'][0]['code'] == 'management_issue_delivery_file_unavailable'
                    assert len(changed['deliveryArtifacts']) == len(execution.requested_outputs) - 1
                finally:
                    await runtime.workspace_service.awrite_bytes(execution.scope.workspace_key, file.path, original_bytes, overwrite=True)
                assert len(queries) == before_queries + 1
                assert (await runtime.state_repository.get(execution.scope.run_id)).state_version == delivery_state_version
                frozen_stages, frozen_tasks = list(model_stages), list(native_tasks)
                repeated = await client.post(prefix + '/recalculations', headers=headers, json=request)
                assert repeated.status_code == 200, repeated.text
                assert repeated.json()['taskId'] == task_id
                assert model_stages == frozen_stages and native_tasks == frozen_tasks
                if recover_preparation:
                    resumed_again = await client.post(preparation_path + '/resume', headers=headers, json=resume_payload)
                    assert resumed_again.status_code == 200, resumed_again.text
                    assert resumed_again.json()['recoveryId'] == recovery_id
                    assert resumed_again.json()['deliveryStatus'] == 'completed'
                    assert not resumed_again.json()['issueCodes']
                    assert model_stages == frozen_stages and native_tasks == frozen_tasks
                opened = await client.get(delivery['editor']['openUrl'], follow_redirects=False)
                assert opened.status_code == 303, opened.text
                cookie_name, new_editor = (SLIDES_SESSION_COOKIE, slides) if execution.requested_outputs == ('pptx',) else (
                    (WORKBOOK_SESSION_COOKIE, workbooks) if execution.requested_outputs == ('xlsx',) else (EDITOR_SESSION_COOKIE, editor))
                raw_session = client.cookies.get(cookie_name, path=opened.headers['location'])
                session = await runtime.editor_grants.lookup_session(raw_session)
                new_context = await new_editor.context_for_session(session)
                assert new_context.workflow_run_id == execution.scope.run_id
                assert new_context.revision == execution.output_revision
                assert (await editor.trace.require_index(new_context)).report_basis_id == execution.basis_id
                assert '200' in (await editor.read_document(new_context)).markdown
                assert (await runtime.state_repository.get(source.workflow_run_id)).payload['workflowCheckpoint'] == (
                    before_source.payload['workflowCheckpoint'])
                assert (await editor.read_document(source)).sha256 == original_document.sha256
                assert (await runtime.state_repository.get(execution.scope.run_id)).payload['workflowCheckpoint'] == (
                    child_before['workflowCheckpoint'])
                assert len(queries) == before_queries + 1
                assert len(local.executions) == (1 if execution.requested_outputs == ('xlsx',) else 0)
                # 下载字节另存到本次进程的证据目录，避免随pytest临时工作区回收。
                mode = 'policy-recovery-public' if recover_preparation else 'policy-adoption-public'
                evidence_dir = Path(tempfile.gettempdir()) / f'smart-reporting-{mode}-{os.getpid()}'
                evidence_dir.mkdir(exist_ok=True)
                files = []
                for fmt, raw in downloaded_files.items():
                    filename = 'budget-policy-adoption.' + fmt
                    (evidence_dir / filename).write_bytes(raw)
                    files.append({'file': filename, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
                evidence = {'deliveryFormat': new_context.delivery_format, 'runId': execution.scope.run_id,
                    'basisId': execution.basis_id, 'parentBasisId': execution.parent_basis_id,
                    'revision': execution.output_revision, 'businessQueries': len(queries) - before_queries,
                    **({'recoveryId': recovery_id, 'originalQueueRunId': submitted['execution']['runId'],
                        'preparationFaultKind': kind} if recover_preparation else {}),
                    'nativeTasks': len(native_tasks), 'modelStages': model_stages,
                    'budgetValue': '200', 'businessApproval': 'not_performed', 'files': files,
                    'issueEvidence': evidence, 'regressionReceiptId': regression.json()['receiptId']}
                (evidence_dir / (new_context.delivery_format + '.json')).write_text(
                    json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
    finally:
        await worker.stop()
        await manager.aclose()


def verify_actual_output(output, content, basis_id):
    """读取文件内部的实际值，不以链接或文件后缀作为生成成功证据。"""
    if output == 'pdf':
        from pypdf import PdfReader
        pages = PdfReader(BytesIO(content)).pages
        assert pages and any('200' in page.extract_text() for page in pages)
    elif output == 'docx':
        from docx import Document
        assert any('200' in cell.text for table in Document(BytesIO(content)).tables for row in table.rows for cell in row.cells)
    elif output == 'pptx':
        with ZipFile(BytesIO(content)) as package:
            slides = ''.join(package.read(name).decode() for name in package.namelist()
                if name.startswith('ppt/slides/slide') and name.endswith('.xml'))
        assert '200' in slides and '预算' in slides
    else:
        from openpyxl import load_workbook
        book = load_workbook(BytesIO(content), data_only=True)
        try:
            assert book['汇总']['D2'].value == 200 and book.worksheets[1]['C2'].value == 200
        finally:
            book.close()
        with ZipFile(BytesIO(content)) as package:
            cells = json.loads(package.read('smart-reporting/source-mapping.json'))['sources']['cells']
        assert cells and {cell['basisId'] for cell in cells} == {basis_id}
