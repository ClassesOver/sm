"""C02实际旧报告到公开反馈、正式修复和Agno耐久队列的连续验收。"""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

import duckdb
import pytest
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.run import RunContext, RunStatus
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlglot import parse_one

from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
from smart_reporting.management.metrics_api import create_metrics_router
from smart_reporting.management.models import ManagementError
from smart_reporting.management.report_bases import ReportBasisService
from smart_reporting.management.settings import ManagementSettings
from smart_reporting.management.statistical_policy_api import create_statistical_policy_router
from smart_reporting.report_editor import ReportEditorService
from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
from smart_reporting.report_editor.recalculation import (
    create_policy_adoption_workflow,
    read_recalculation_run,
    read_task,
    recalculation_queue_config,
)
from smart_reporting.reporting.data_source.materialization import CsvMaterializer
from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
from smart_reporting.reporting.delivery.publishing import (
    ReportDownloadHttpService,
    create_report_download_router,
)
from smart_reporting.reporting.semantics.basis import BasisCalculationReceipt
from smart_reporting.reporting.tests.semantic_fixtures.oracle import execution_ratio
from smart_reporting.reporting.tests.test_semantic_models import ratio_payload
from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1
from smart_reporting.reporting.trace.issue_content import evaluate_calculation_content
from smart_reporting.reporting.workflow.checkpoint import FileIdentity
from smart_reporting.reporting.workflow.runtime import sections as section_runtime
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    resolve_reporting_workflow_scope,
)
from smart_reporting.tests.c02_native_delivery import (
    exercise_c02_native_delivery,
    verify_c02_output,
)
from smart_reporting.tests.test_report_basis_persistence import build_identity, request_summary
from smart_reporting.tests.test_report_issue_c02 import publish_c02_definitions


async def exercise_c02_public_flow(ctx, snapshot, monkeypatch, *, outputs, close_issue=False, browser_close=False, browser_history=False, browser_feedback=False, browser_adoption=False, browser_repair=False, browser_decisions=False, browser_regressions=False):
    metrics, policy = await publish_c02_definitions(ctx)
    bases, store = ReportBasisService(ctx['scopes']), snapshot['dataset_store']
    # 仅启动种子运行的类型；真正提交问题的70报告由原生执行器实际生成。
    await bases.register_report_basis('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
        request_summary=request_summary(ctx['scope_id'], displayUnit='%', domains=['budget'], requestedOutputs=outputs),
        build_identity=build_identity(), policy_version={'policyId': 'monthly-budget', 'revision': 1})
    preview = await bases.preview_policy_adoption('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
        policy_version={'policyId': 'monthly-budget', 'revision': 2})
    original_adoption = await bases.register_policy_adoption('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis',
        confirmation={'requestId': 'C02-original-report', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
            'previewHash': preview.digest(), 'questionChoices': [{'questionId': 'q-rate',
                'metricVersion': {'metricId': 'rate', 'revision': 1}, 'reason': '按原正式项目均值规则生成待核对报告。'}]},
        build_identity=build_identity())
    queries = []
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.budget(project_id VARCHAR, amount DECIMAL(18,2), period DATE)')
        connection.execute('CREATE TABLE test.actual(project_id VARCHAR, amount DECIMAL(18,2), period DATE)')
        connection.execute("INSERT INTO test.budget VALUES ('A',100,'2026-11-01'),('B',200,'2026-11-20')")
        connection.execute("INSERT INTO test.actual VALUES ('A',60,'2026-11-01'),('A',30,'2026-11-02'),('B',100,'2026-11-20')")
        connection.execute('CREATE VIEW test.project_rates AS SELECT b.project_id,b.period, '
            'CAST(a.amount/b.amount AS DECIMAL(18,8)) AS fraction FROM test.budget b JOIN '
            '(SELECT project_id,SUM(amount) AS amount FROM test.actual GROUP BY project_id) a USING(project_id)')
        budget_rows = connection.execute('SELECT project_id,amount FROM test.budget').fetchall()
        actual_rows = connection.execute('SELECT project_id,amount FROM test.actual').fetchall()
        raw_rows = {table: [[project, str(value), period.isoformat()] for project, value, period in
            connection.execute(f'SELECT project_id,amount,period FROM test.{table} ORDER BY project_id,period').fetchall()]
            for table in ('budget', 'actual')}
        budgets = dict(budget_rows)
        actuals = {key: sum(value for project, value in actual_rows if project == key) for key in budgets}
        assert execution_ratio(actuals, budgets) == Decimal('63.33')
        assert sum(actuals[key] / budgets[key] * 100 for key in budgets) / len(budgets) == Decimal('70')

        async def materialize(_adapter, sql, parameters, *, max_bytes=None):
            queries.append(sql)
            cursor = connection.execute(parse_one(sql, read='mysql').sql(dialect='duckdb'), parameters)
            writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
            writer.append(tuple(cursor.fetchall()))
            return writer.finish()

        monkeypatch.setattr(StarRocksDataSourceAdapter, 'materialize_bound', materialize)
        await bases.register_adoption_selections('run-basis', ctx['scope'], user_id='7', thread_id='thread-basis', request_id='C02-original-report')
        target = resolve_reporting_workflow_scope(run_id=original_adoption.target_run_id,
            session_id=original_adoption.target_run_id, user_id='7', dependencies={REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                'database': ctx['scope'].database, 'companyId': ctx['scope'].company_id, 'threadId': 'thread-basis', 'userId': '7'}})
        store.service.registry.resolve(target)
        original, = await bases.calculate_adoption_metrics(original_adoption.target_run_id, ctx['scope'],
            user_id='7', thread_id='thread-basis', vault=ctx['vault'], dataset_store=store,
            run_context=RunContext(run_id=target.run_id, session_id=target.workspace_key, session_state={}), workflow_scope=target)

        async def continue_from_original(report):
            return await _feedback_and_fix(report, ctx, metrics, policy, queries, monkeypatch, raw_rows, close_issue=close_issue, browser_close=browser_close, browser_history=browser_history, browser_feedback=browser_feedback, browser_adoption=browser_adoption, browser_repair=browser_repair, browser_decisions=browser_decisions, browser_regressions=browser_regressions)

        return await exercise_c02_native_delivery(ctx, bases, store, snapshot['workflow_scope'], original_adoption,
            original, monkeypatch, expected_value='70', after_report=continue_from_original)


async def _feedback_and_fix(report, ctx, metrics, policy, queries, monkeypatch, raw_rows, *, close_issue=False, browser_close=False, browser_history=False, browser_feedback=False, browser_adoption=False, browser_repair=False, browser_decisions=False, browser_regressions=False):
    runtime, database, source = report.runtime, report.database, report.context
    bases = runtime.report_basis_service
    editor = ReportEditorService(state_repository=runtime.state_repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service, report_basis_service=bases, recalculation_runtime=runtime,
        recalculation_database=database.async_db)
    editor.recalculation_durable = True
    config = recalculation_queue_config()
    config.poll_interval = 0.05
    worker = QueueWorker(store=resolve_queue_store(config, database.async_db), config=config,
        resolve_component=lambda kind, component_id: create_policy_adoption_workflow(editor,
            runtime=runtime, database=database.async_db) if (kind, component_id) == ('workflow', 'report-editor-policy-adoption') else None)
    editor.recalculation_queue_worker = worker
    app = FastAPI()
    settings = ManagementSettings(public_origin='https://reports.test')
    app.include_router(create_management_router(ctx['scopes'].auth, settings, report_runtime=runtime))
    app.include_router(create_metrics_router(metrics, settings))
    app.include_router(create_statistical_policy_router(ctx['policy_service'], settings))
    app.include_router(create_report_editor_router(runtime.editor_grants, editor=editor, cookie_secure=False))
    app.include_router(create_report_download_router(ReportDownloadHttpService(runtime.download_grants,
        runtime.artifact_persistence.repository)))
    if browser_repair:
        from smart_reporting.management.business_evidence_api import create_business_evidence_router

        app.include_router(create_business_evidence_router(ctx['policy_service'].evidence, settings))
    if browser_close:
        from smart_reporting.management.business_documents_api import (
            create_business_documents_router,
        )

        app.include_router(create_business_documents_router(runtime.business_evidence_service.documents, settings))
    original_document = await editor.read_document(source)
    parent_before = await runtime.state_repository.get(source.workflow_run_id)
    before_queries = len(queries)
    assert before_queries == 2 and '70' in original_document.markdown
    original_basis = await bases.load_report_basis(source.workflow_run_id, ctx['scope'], user_id='7', thread_id='thread-basis')
    assert original_basis.policy_version.revision == 2
    original_root = next(item for item in report.calculation.results if item.metric_version == report.calculation.request.metric_version)
    original_index = await editor.trace.require_index(source)
    original_subject = next(item for item in original_index.subject_bindings
        if any(ref.fact_key == original_root.fact_id for ref in item.fact_refs))
    prefix = f'/reports/v1/editor/{source.report_id}/{source.revision}/api'
    issue_id = 'C02-public-ratio'
    issue_path = '/management/api/v1/report-issue-reviews/' + issue_id
    admin_scope = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id}
    await worker.start()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(section_runtime, '_run_section_stage', report.stage)
            async with AsyncClient(transport=ASGITransport(app), base_url='https://reports.test') as client:
                grant, _ = await runtime.editor_grants.issue(source)
                opened = await client.get('/reports/v1/editor/open/' + grant, follow_redirects=False)
                assert opened.status_code == 303, opened.text
                headers = {'origin': 'https://reports.test',
                    'x-csrf-token': runtime.editor_grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
                if browser_feedback:
                    from smart_reporting.tests.report_issue_browser_flow import (
                        run_management_browser,
                    )

                    feedback_dir = Path(tempfile.gettempdir()) / f'smart-reporting-c36-feedback-{os.getpid()}'
                    feedback_dir.mkdir(exist_ok=True)
                    feedback_grant, _ = await runtime.editor_grants.issue(source)
                    feedback = await run_management_browser(app, {
                        'grant': feedback_grant, 'reportId': source.report_id, 'revision': source.revision,
                        'feedback': True, 'subjectId': original_subject.subject_id,
                    }, feedback_dir, script='smoke/report-historical-retirement-postgres-smoke.mjs')
                    issue_id = feedback['issueId']
                    issue_path = '/management/api/v1/report-issue-reviews/' + issue_id
                    readback = await client.get(prefix + '/issue-reviews', params={'issueId': issue_id})
                    assert readback.status_code == 200 and readback.json()['items'][0]['review']['status'] == 'open'
                else:
                    issue = await client.post(prefix + '/issue-reviews', headers=headers, json={'issueId': 'C02-public-ratio',
                        'objectRefs': [original_subject.subject_id], 'category': 'calculation',
                        'description': '本报告项目比率均值70%不代表总体190/300=63.33%，请核对统计方式。'})
                    assert issue.status_code == 200 and issue.json()['review']['status'] == 'open', issue.text
                client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
                admin_headers = {'origin': 'https://reports.test', 'x-csrf-token': csrf_token(ctx['token'])}
                proposal = {'changeSummary': '总体执行率改用实际合计除以预算合计',
                    'counterexample': 'A预算100实际60+30，B预算200实际100；平均90%和50%是70%，总体190/300是63.33%。'}
                if not browser_decisions:
                    accepted = await client.post(issue_path + '/decision', headers=admin_headers, json={**admin_scope,
                        'expectedVersion': 1, 'status': 'accepted', 'proposal': proposal, 'decisionReason': '采纳原始行反例，待正式修复和独立回归。'})
                    assert accepted.status_code == 200, accepted.text
                if browser_repair:
                    from smart_reporting.tests.report_issue_browser_flow import (
                        run_management_browser,
                    )

                    repair_dir = Path(tempfile.gettempdir()) / f'smart-reporting-c36-repair-{os.getpid()}'
                    repair_dir.mkdir(exist_ok=True)
                    repair = await run_management_browser(app, {
                        'token': ctx['token'], 'database': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
                        'decisions': browser_decisions, 'issueId': issue_id,
                    }, repair_dir, script='smoke/management-c02-repair-postgres-smoke.mjs')
                    metric_current = await client.get('/management/api/v1/metrics/rate', params=admin_scope)
                    policy_current = await client.get('/management/api/v1/statistical-policies/monthly-budget', params=admin_scope)
                    assert metric_current.json()['published']['revision'] == 2
                    assert policy_current.json()['published']['revision'] == 3
                else:
                    fixed = {key: value for key, value in ratio_payload(name='预算执行率（合计比率）').items() if key not in ('scopeId', 'revision')}
                    metric_saved = await client.put('/management/api/v1/metrics/rate/draft', headers=admin_headers,
                        json={**admin_scope, 'expectedVersion': 1, 'definition': fixed})
                    assert metric_saved.status_code == 200, metric_saved.text
                    metric_published = await client.post('/management/api/v1/metrics/rate/publish', headers=admin_headers,
                        json={**admin_scope, 'expectedVersion': 2})
                    assert metric_published.status_code == 200, metric_published.text
                    policy_saved = await client.put('/management/api/v1/statistical-policies/monthly-budget/draft', headers=admin_headers,
                        json={**admin_scope, 'expectedVersion': 2, 'definition': {**policy, 'name': 'C02合计执行率',
                            'metricVersions': [{'metricId': 'rate', 'revision': 2}]}})
                    assert policy_saved.status_code == 200, policy_saved.text
                    policy_published = await client.post('/management/api/v1/statistical-policies/monthly-budget/publish', headers=admin_headers,
                        json={**admin_scope, 'expectedVersion': 3})
                    assert policy_published.status_code == 200, policy_published.text
                if not browser_decisions:
                    linked = await client.post(issue_path + '/decision', headers=admin_headers, json={**admin_scope,
                        'expectedVersion': 2, 'status': 'accepted', 'proposal': proposal, 'decisionReason': '已正式发布精确修复版本，等待新报告和回归。',
                        'correctedVersions': [{'assetType': 'metric', 'assetId': 'rate', 'revision': 2},
                            {'assetType': 'statistical_policy', 'assetId': 'monthly-budget', 'revision': 3}]})
                    assert linked.status_code == 200, linked.text
                if browser_adoption:
                    from smart_reporting.tests.report_issue_browser_flow import (
                        run_management_browser,
                    )

                    adoption_dir = Path(tempfile.gettempdir()) / f'smart-reporting-c36-adoption-{os.getpid()}'
                    adoption_dir.mkdir(exist_ok=True)
                    adoption_grant, _ = await runtime.editor_grants.issue(source)
                    adoption = await run_management_browser(app, {
                        'grant': adoption_grant, 'reportId': source.report_id, 'revision': source.revision,
                        'adoption': True,
                    }, adoption_dir, script='smoke/report-historical-retirement-postgres-smoke.mjs')
                    request = adoption['request']
                    submitted = await client.get(prefix + '/recalculation-requests/' + request['requestId'])
                    assert submitted.status_code == 200, submitted.text
                else:
                    preview = await client.post(prefix + '/policy-adoption-preview', headers=headers, json={
                        'parentRevision': source.revision, 'expectedSha256': original_document.sha256,
                        'policyVersion': {'policyId': 'monthly-budget', 'revision': 3}})
                    assert preview.status_code == 200, preview.text
                    request = {'requestId': 'C02-public-fix', 'parentRevision': source.revision,
                        'expectedSha256': original_document.sha256, 'operation': 'adopt_policy',
                        'confirmation': {'requestId': 'C02-public-fix', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 3},
                            'previewHash': preview.json()['previewHash'], 'questionChoices': [{'questionId': 'q-rate',
                                'metricVersion': {'metricId': 'rate', 'revision': 2}, 'reason': '使用合计比率，拒绝项目比率均值。'}]}}
                    submitted = await client.post(prefix + '/recalculations', headers=headers, json=request)
                    assert submitted.status_code == 202, submitted.text
                task_id = submitted.json()['taskId']

                async def wait_delivery():
                    while True:
                        run = await read_recalculation_run(editor, source, task_id, database=database.async_db)
                        assert run.status not in {RunStatus.error, RunStatus.cancelled}, run
                        if run.status == RunStatus.completed:
                            return await read_task(editor, source, request['requestId'])
                        await asyncio.sleep(0.05)

                completed = await asyncio.wait_for(wait_delivery(), timeout=180)
                assert completed.status == 'completed', completed
                execution = completed.result.execution
                assert execution.parent_basis_id == original_basis.id and execution.basis_id != original_basis.id
                receipts = await bases.load_basis_receipts(execution.scope.run_id, ctx['scope'], user_id='7', thread_id='thread-basis', report_revision='initial')
                calculation, = [item for item in receipts if isinstance(item, BasisCalculationReceipt)]
                root = next(item for item in calculation.results if item.metric_version == calculation.request.metric_version)
                assert root.value == Decimal(190) / Decimal(300) * 100
                assert len(queries) == before_queries + 2
                regression_input = {**admin_scope, 'expectedIssueVersion': 3, 'caseId': 'C02', 'targetRunId': execution.scope.run_id,
                    'targetReportRevision': 'initial', 'calculationReceiptId': calculation.receipt_id,
                    'expectationReason': '独立原始预算100+200=300、实际60+30+100=190，合计比率保留两位为63.33%。',
                    'assertions': [{'factId': root.fact_id, 'expectedStatus': 'computed', 'expectedValue': '63.33', 'decimalPlaces': 2, 'unit': '%'}]}
                if browser_regressions:
                    from smart_reporting.tests.report_issue_browser_flow import (
                        run_management_browser,
                    )

                    regression_dir = Path(tempfile.gettempdir()) / f'smart-reporting-c36-regressions-{os.getpid()}'
                    regression_dir.mkdir(exist_ok=True)
                    regression = await run_management_browser(app, {
                        'token': ctx['token'], 'database': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
                        'issueId': issue_id, 'targetRunId': execution.scope.run_id,
                        'calculationReceiptId': calculation.receipt_id,
                    }, regression_dir, script='smoke/management-c02-regressions-postgres-smoke.mjs')
                    records = []
                    for receipt in regression['receipts']:
                        read = await client.get(issue_path + '/regressions', params={**admin_scope, 'requestId': receipt['request']['requestId']})
                        assert read.status_code == 200 and read.json()['items'] == [receipt], read.text
                        records.append(read.json()['items'][0])
                    wrong_record, passed_record = records
                else:
                    wrong = await client.post(issue_path + '/regressions', headers=admin_headers, json={**regression_input,
                        'requestId': 'C02-public-wrong-mean', 'assertions': [{**regression_input['assertions'][0], 'expectedValue': '70'}]})
                    assert wrong.status_code == 200, wrong.text
                    passed = await client.post(issue_path + '/regressions', headers=admin_headers,
                        json={**regression_input, 'requestId': 'C02-public-independent-ratio'})
                    assert passed.status_code == 200, passed.text
                    wrong_record, passed_record = wrong.json(), passed.json()
                assert wrong_record['status'] == 'failed' and passed_record['status'] == 'passed'
                resolution = await client.post(issue_path + '/resolution-evidence-check', headers=admin_headers,
                    json={**admin_scope, 'expectedIssueVersion': 3, 'regressionReceiptIds': [passed_record['receiptId']]})
                assert resolution.status_code == 200, resolution.text
                readiness = resolution.json()
                assert readiness['regressionEvidenceReady'] and readiness['originalEvidenceReady'], readiness
                assert readiness['deliveryReady'] and readiness['factPresentationReady'], readiness
                assert readiness['businessApproval'] == 'not_performed' and readiness['issueClosed'] is False
                delivery = await client.get(prefix + f'/recalculations/{task_id}/delivery')
                assert delivery.status_code == 200, delivery.text
                new_grant = urlsplit(delivery.json()['delivery']['editor']['openUrl']).path.rsplit('/', 1)[-1]
                _, new_session = await runtime.editor_grants.exchange(new_grant)
                new_context = await editor.context_for_session(new_session)
                assert new_context.workflow_run_id == execution.scope.run_id and new_context.revision == execution.output_revision
                assert (await editor.trace.require_index(new_context)).report_basis_id == execution.basis_id
                assert '63.33' in (await editor.read_document(new_context)).markdown
                out = Path(tempfile.gettempdir()) / f'smart-reporting-c02-public-{os.getpid()}-{"-".join(execution.requested_outputs)}'
                out.mkdir(exist_ok=True)
                shutil.copytree(report.evidence_dir, out/'original', dirs_exist_ok=True)
                files = []
                for fmt in execution.requested_outputs:
                    label = 'word' if fmt == 'docx' else fmt
                    download = await client.get(delivery.json()['delivery'][label]['downloadUrl'])
                    assert download.status_code == 200
                    identity = next(item for item in completed.result.artifacts if item.path.endswith('.'+fmt))
                    assert len(download.content) == identity.size and hashlib.sha256(download.content).hexdigest() == identity.sha256
                    verify_c02_output(fmt, download.content, root)
                    name = 'c02-corrected.'+fmt
                    (out/name).write_bytes(download.content)
                    files.append({'file': name, 'size': identity.size, 'sha256': identity.sha256})
                again = await client.post(prefix + '/recalculations', headers=headers, json=request)
                assert again.status_code == 200 and again.json()['taskId'] == task_id, again.text
                assert len(queries) == before_queries + 2
                assert (await editor.read_document(source)).sha256 == original_document.sha256
                assert await bases.load_report_basis(source.workflow_run_id, ctx['scope'], user_id='7', thread_id='thread-basis') == original_basis
                after = await runtime.state_repository.get(source.workflow_run_id)
                assert after.payload['workflowCheckpoint'] == parent_before.payload['workflowCheckpoint']
                for file in json.loads((report.evidence_dir/'evidence.json').read_text())['files']:
                    raw, _ = await runtime.workspace_service.afile_bytes(source.scope['threadId'], file['path'])
                    assert len(raw) == file['size'] and hashlib.sha256(raw).hexdigest() == file['sha256']
                assert (await client.get(prefix + '/issue-reviews', params={'issueId': issue_id})).json()['items'][0]['review']['status'] == 'accepted'
                assert (await client.post(issue_path + '/decision', headers=admin_headers, json={**admin_scope,
                    'expectedVersion': 3, 'status': 'resolved', 'decisionReason': '只有机械证据，不能冒充业务签认。'})).status_code == 409
                closure = None
                if close_issue:
                    from smart_reporting.reporting.business_knowledge.retrieval import (
                        DocumentRevisionRef,
                    )
                    from smart_reporting.tests.test_business_document_ingestion import metadata

                    # 合成原始行及人工签认操作只证明工程链路，不冒充真实业务专家结论。
                    documents = runtime.business_evidence_service.documents
                    original = '独立合成对账：预算A100、B200，实际A60+30、B100；190/300×100保留两位为63.33%。'
                    doc = await documents.register_document(ctx['token'], ctx['scope'], original.encode(), filename='c02-expected.txt',
                        metadata=metadata(id='c02-independent-expectation', title='C02独立原始行对账'), request_id='c02-expected', expected_version=0)
                    await documents.ingest_revision(await documents.claim_next())
                    detail = await documents.get_document(ctx['token'], ctx['scope'], doc.document_id)
                    await documents.review_revision(ctx['token'], ctx['scope'], doc.document_id, 1, decision='approved',
                        reason='合成原始行独立算术对照', expected_version=detail['revisions'][0]['stateVersion'])
                    await runtime.business_evidence_service.publish(ctx['token'], ctx['scope'], request_id='c02-independent-published',
                        kind='rule_evidence', revision_ids=(DocumentRevisionRef(document_id=doc.document_id, revision=1),))
                    detail = await documents.get_document(ctx['token'], ctx['scope'], doc.document_id)
                    signing = {**admin_scope, 'requestId': 'C02-public-business-signoff', 'expectedIssueVersion': 3,
                        'decision': 'approve_expected_values', 'regressionReceiptIds': [passed_record['receiptId']],
                        'approvalReason': '独立原始行合计190/300，拒绝项目比率均值70；本操作为合成签认。',
                        'sources': [{'regressionReceiptId': passed_record['receiptId'], 'documentId': doc.document_id,
                            'revision': 1, 'locator': detail['revisions'][0]['parseReceipt']['fragments'][0]['locator'], 'quote': original}]}
                    if browser_close:
                        from smart_reporting.tests.report_issue_browser_flow import (
                            run_management_browser,
                        )

                        browser_dir = out / 'browser'
                        browser_dir.mkdir()
                        browser = await run_management_browser(app, {
                            'token': ctx['token'], 'database': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
                            'issueId': issue_id, 'sourceTitle': 'C02独立原始行对账', 'caseId': 'C02',
                            'mode': 'recalculated', 'apiOriginHeader': 'https://reports.test',
                            'approvalReason': signing['approvalReason'],
                        }, browser_dir)
                        approved = await client.get(issue_path + '/business-approvals/' + browser['approvalRequestId'], params=admin_scope)
                        closed = await client.get(issue_path + '/resolutions/' + browser['closureRequestId'], params=admin_scope)
                        assert approved.status_code == closed.status_code == 200
                        closure = closed.json()
                    else:
                        approved = await client.post(issue_path + '/business-approvals', headers=admin_headers, json=signing)
                        assert approved.status_code == 200, approved.text
                        closing = {**admin_scope, 'requestId': 'C02-public-closed', 'expectedIssueVersion': 3,
                            'regressionReceiptIds': [passed_record['receiptId']], 'businessApprovalRequestId': signing['requestId'],
                            'mode': 'recalculated', 'decisionReason': '正式修复、独立预期、新报告交付和精确事实已核对，结束本次纠错。',
                            'originalReportUnchanged': True}
                        closed = await client.post(issue_path + '/resolutions', headers=admin_headers, json=closing)
                        assert closed.status_code == 200, closed.text
                        closure = closed.json()
                        assert (await client.get(issue_path + '/resolutions/C02-public-closed', params=admin_scope)).json() == closure
                        assert (await client.post(issue_path + '/resolutions', headers=admin_headers, json=closing)).json() == closure
                    assert (await client.get(prefix + '/issue-reviews', params={'issueId': issue_id})).json()['items'][0]['review']['status'] == 'resolved'
                    assert (await editor.read_document(source)).sha256 == original_document.sha256
                    assert len(queries) == 4
                    (out/'business-approval.json').write_text(json.dumps(approved.json(), ensure_ascii=False, indent=2))
                    (out/'resolution.json').write_text(json.dumps(closure, ensure_ascii=False, indent=2))
                    (out/'independent-expectation.txt').write_text(original)
                impact = await client.get('/management/api/v1/statistical-policies/monthly-budget/impact',
                    params={**admin_scope, 'revision': 2})
                assert impact.status_code == 200, impact.text
                assert any(item['kind'] == 'report' and item['referenceId'] == source.workflow_run_id for item in impact.json()['items'])
                assert not any(item['kind'] == 'report' and item['referenceId'] == execution.scope.run_id for item in impact.json()['items'])
                retired = await client.post('/management/api/v1/metrics/rate/versions/1/retire', headers=admin_headers,
                    json={**admin_scope, 'reason': '原始行反例已确认总体执行率不得平均项目比率。',
                        'replacement': {'metricId': 'rate', 'revision': 2}})
                assert retired.status_code == 200, retired.text
                default = await client.get('/management/api/v1/report-policy-defaults/budget_execution', params=admin_scope)
                assert default.status_code == 200 and default.json()['policyVersion'] == {'policyId': 'monthly-budget', 'revision': 2}
                assert any(item['code'] == 'semantic_asset_retired' and item['impact'] == 'unavailable' for item in default.json()['issues'])
                new_run_id = 'C37-public-new-' + source.workflow_run_id
                await ctx['provider'].register_run(new_run_id, ctx['scope'], user_id='7', thread_id='C37-public-thread', entrypoint='cli')
                with pytest.raises(ManagementError) as unavailable:
                    await bases.register_report_basis(new_run_id, ctx['scope'], user_id='7', thread_id='C37-public-thread',
                        request_summary=request_summary(ctx['scope_id']), build_identity=build_identity())
                assert unavailable.value.code == 'management_semantic_asset_retired'
                assert (await editor.read_document(source)).sha256 == original_document.sha256
                assert '63.33' in (await editor.read_document(new_context)).markdown
                assert len(queries) == 4
                evidence = {'caseId': 'C02', 'originalValue': '70', 'correctedValue': '63.33',
                    'originalRunId': source.workflow_run_id, 'targetRunId': execution.scope.run_id,
                    'originalBasisId': original_basis.id, 'targetBasisId': execution.basis_id, 'taskId': task_id,
                    'originalMarkdownSha256': original_document.sha256, 'businessQueries': len(queries), 'files': files,
                    'resolution': readiness, 'businessApproval': 'not_performed', 'issueClosed': False}
                if browser_regressions:
                    evidence['regressionBrowser'] = regression
                    shutil.copytree(regression_dir, out / 'regression-browser', dirs_exist_ok=True)
                if browser_repair:
                    evidence['repairBrowser'] = repair
                    shutil.copytree(repair_dir, out / 'repair-browser', dirs_exist_ok=True)
                if browser_adoption:
                    evidence['adoptionBrowser'] = adoption
                    shutil.copytree(adoption_dir, out / 'adoption-browser', dirs_exist_ok=True)
                if browser_feedback:
                    evidence['issueId'] = issue_id
                    evidence['feedbackBrowser'] = feedback
                    shutil.copytree(feedback_dir, out / 'feedback-browser', dirs_exist_ok=True)
                if browser_history:
                    from smart_reporting.tests.report_issue_browser_flow import (
                        run_management_browser,
                    )

                    history_dir = out / 'historical-browser'
                    history_dir.mkdir(exist_ok=True)
                    history_grant, _ = await runtime.editor_grants.issue(source)
                    old_files = json.loads((report.evidence_dir / 'evidence.json').read_text())['files']
                    evidence['historicalBrowser'] = await run_management_browser(app, {
                        'grant': history_grant, 'reportId': source.report_id, 'revision': source.revision,
                        'basisId': original_basis.id, 'factId': original_root.fact_id,
                        'downloads': [{**file, 'format': file['file'].rsplit('.', 1)[1],
                            'url': report.delivery['word' if file['file'].endswith('.docx') else file['file'].rsplit('.', 1)[1]]['downloadUrl']}
                            for file in old_files],
                    }, history_dir, script='smoke/report-historical-retirement-postgres-smoke.mjs')
                    assert len(queries) == 4
                if browser_close:
                    evidence['browser'] = browser
                if closure is not None:
                    evidence.update(closure=closure, businessApproval='explicitly_approved', issueClosed=True)
                child = await runtime.state_repository.get(execution.scope.run_id)
                manifest_raw = await runtime._read_identity_bytes(execution.scope.workspace_key,
                    FileIdentity.model_validate(child.payload['result']['manifest']))
                manifest = ReportArtifactManifest.model_validate_json(manifest_raw)
                trace = manifest.trace_index
                assert trace is not None
                trace_raw = await runtime._read_identity_bytes(execution.scope.workspace_key,
                    FileIdentity(path=trace.path, size=trace.size, sha256=trace.sha256))
                index = RevisionTraceIndexV1.model_validate_json(trace_raw)
                markdown_raw = await runtime._read_identity_bytes(execution.scope.workspace_key,
                    FileIdentity(path=manifest.markdown.path, size=manifest.markdown.size, sha256=manifest.markdown.sha256))
                sources = {}
                for entry in index.fact_files:
                    file = next(item for item in index.files if item.resource_id == entry.file_resource_id)
                    sources[file.resource_id] = await runtime._read_identity_bytes(execution.scope.workspace_key,
                        FileIdentity(path=file.path, size=file.size, sha256=file.sha256))
                    (out/(file.resource_id+'.json')).write_bytes(sources[file.resource_id])
                presentation = evaluate_calculation_content(index, markdown_raw.decode(), sources, calculation, report_revision='initial')
                assert presentation['factPresentationVerified'] and presentation['coveredFactIds'] == [root.fact_id]
                (out/'artifact-manifest.json').write_bytes(manifest_raw)
                (out/'trace-index.json').write_bytes(trace_raw)
                (out/'report.md').write_bytes(markdown_raw)
                (out/'child-state.json').write_text(child.model_dump_json(by_alias=True, indent=2)+'\n')
                (out/'original-calculation.json').write_text(report.calculation.model_dump_json(by_alias=True, indent=2)+'\n')
                for name, run_id in [('original', source.workflow_run_id), ('corrected', execution.scope.run_id)]:
                    formal = await bases.load_execution_context(run_id, ctx['scope'], user_id='7', thread_id='thread-basis', vault=ctx['vault'])
                    rules = {'basis': formal.basis.model_dump(mode='json', by_alias=True),
                        'policy': formal.policy.model_dump(mode='json', by_alias=True),
                        'metrics': [item.model_dump(mode='json', by_alias=True) for item in formal.metrics]}
                    (out/(name+'-rules.json')).write_text(json.dumps(rules, ensure_ascii=False, indent=2)+'\n')
                for name, value in [('original', report.calculation), ('corrected', calculation)]:
                    for i, dataset in enumerate(value.datasets, 1):
                        raw = await runtime.workspace_service.afile_bytes(value.workspace.workspace_key, dataset.file.path)
                        assert hashlib.sha256(raw[0]).hexdigest() == dataset.file.sha256 and len(raw[0]) == dataset.file.size
                        (out/f'{name}-{i}.csv').write_bytes(raw[0])
                for name, value in [('evidence', evidence), ('failed-70', wrong_record), ('passed-63.33', passed_record),
                        ('completed-task', completed.model_dump(mode='json', by_alias=True)), ('submitted', submitted.json()),
                        ('retirement', {'impact': impact.json(), 'retirement': retired.json(), 'default': default.json(),
                            'newDefaultRunError': unavailable.value.code}),
                        ('issue', (await client.get(prefix + '/issue-reviews', params={'issueId': issue_id})).json()),
                        ('raw-rows', {'columns': ['project_id', 'amount', 'period'], **raw_rows}), ('queries', queries)]:
                    (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
                (out/'calculation.json').write_text(calculation.model_dump_json(by_alias=True,indent=2)+'\n')
                return evidence
    finally:
        await worker.stop()
