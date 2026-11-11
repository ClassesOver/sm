"""真实隔离PG+合成SQL/CSV回归记录；不代替真实StarRocks或业务签认。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from smart_reporting.tests.test_report_issue_reviews import accepted_fix, publish_fix, submission
from smart_reporting.tests.test_report_issue_reviews import auth_context as auth_context
from smart_reporting.tests.test_report_issue_reviews import basis_context as basis_context
from smart_reporting.tests.test_report_issue_reviews import document_context as document_context
from smart_reporting.tests.test_report_issue_reviews import index_context as index_context
from smart_reporting.tests.test_report_issue_reviews import issue_context as issue_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def regression_context(issue_context, tmp_path, request):
    import duckdb
    from agno.run import RunContext
    from sqlglot import parse_one

    from smart_reporting.reporting.data_source.materialization import CsvMaterializer
    from smart_reporting.reporting.data_sources import ReportDatasetStore
    from smart_reporting.reporting.host_workspace import (
        ReportingWorkspaceRegistry,
        ReportingWorkspaceRouter,
    )
    from smart_reporting.reporting.semantics.compiler import compile_metric
    from smart_reporting.reporting.semantics.execution import execute_metric
    from smart_reporting.reporting.semantics.models import MetricRequest
    from smart_reporting.reporting.workflow.scope import (
        ReportingWorkflowScope,
        reporting_scope_keys,
    )
    from smart_reporting.tests.test_report_basis_persistence import build_identity, request_summary

    ctx, service, binding = issue_context
    await service.submit(**binding, allowed_object_refs=('fact-rate',), payload=submission())
    await publish_fix(ctx)
    await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix())
    target_run, target_thread = 'fixed-run', 'fixed-thread'
    if getattr(request, 'param', None) == 'adopted':
        target_thread = binding['thread_id']
        preview = await service.bases.preview_policy_adoption(binding['run_id'], ctx['scope'], user_id='7',
            thread_id=target_thread, policy_version={'policyId': 'monthly-budget', 'revision': 2})
        adoption = await service.bases.register_policy_adoption(binding['run_id'], ctx['scope'], user_id='7', thread_id=target_thread,
            confirmation={'requestId': 'issue-fix-adoption', 'targetPolicyVersion': {'policyId': 'monthly-budget', 'revision': 2},
                'previewHash': preview.digest(), 'questionChoices': [{'questionId': 'q-rate',
                    'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '明确采用修复后的预算合计指标；执行率仍需另行核验。'}]},
            build_identity=build_identity())
        target_run = adoption.target_run_id
        basis = await service.bases.load_report_basis(target_run, ctx['scope'], user_id='7', thread_id=target_thread)
    else:
        await ctx['provider'].register_run(target_run, ctx['scope'], user_id='7', thread_id=target_thread, entrypoint='cli')
        basis = await service.bases.register_report_basis(target_run, ctx['scope'], user_id='7', thread_id=target_thread,
            request_summary=request_summary(ctx['scope_id']), build_identity=build_identity(),
            policy_version={'policyId': 'monthly-budget', 'revision': 2})
    execution = await service.bases.load_execution_context(target_run, ctx['scope'], user_id='7', thread_id=target_thread, vault=ctx['vault'])
    keys = reporting_scope_keys(database=ctx['scope'].database, company_id=ctx['scope'].company_id,
        user_id='7', thread_id=target_thread, run_id=target_run)
    scope = ReportingWorkflowScope(run_id=target_run, external_run_id=target_run, session_id='fixed-session',
        caller_thread_id=target_thread, user_id='7', database=ctx['scope'].database, company_id=ctx['scope'].company_id,
        thread_lease_key=keys.thread_lease_key, workspace_key=keys.workspace_key)
    registry = ReportingWorkspaceRegistry(tmp_path / 'workspaces', secret='synthetic-regression-secret-32bytes')
    registry.resolve(scope)
    datasets = ReportDatasetStore(ReportingWorkspaceRouter(registry))
    context = RunContext(run_id=target_run, session_id=keys.workspace_key, session_state={})
    request = MetricRequest(metricVersion={'metricId': 'budget', 'revision': 2}, basisId=basis.id, period=basis.request_summary.period)
    plan = compile_metric(request, execution.policy, execution.metrics, execution.metadata['warehouse'].tables)
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.budget(amount DECIMAL(18,2), period DATE, project_id VARCHAR)')
        connection.execute("INSERT INTO test.budget VALUES (100,'2026-11-01','A'),(200,'2026-11-20','B')")
        class Source:
            config = execution.sources['warehouse']
            async def materialize_bound(self, sql, parameters, *, max_bytes=None):
                cursor = connection.execute(parse_one(sql, read='mysql').sql(dialect='duckdb'), parameters)
                writer = CsvMaterializer(tuple(column[0] for column in cursor.description), max_bytes=max_bytes)
                writer.append(tuple(cursor.fetchall()))
                return writer.finish()
        actual = await execute_metric(plan, {'warehouse': Source()}, datasets=datasets, run_context=context, calculation_id='fixed-calculation')
    calculation = await service.bases.append_basis_receipt(target_run, ctx['scope'], user_id='7', thread_id=target_thread,
        receipt_id='fixed-calculation', report_revision='initial', request=request, results=actual.results,
        readiness=actual.readiness, dataset_handles=actual.datasets, dataset_store=datasets, run_context=context, workflow_scope=scope)
    payload = {'requestId': 'verify-counterexample', 'expectedIssueVersion': 2, 'caseId': 'budget-total',
        'targetRunId': target_run, 'targetReportRevision': 'initial', 'calculationReceiptId': 'fixed-calculation',
        'expectationReason': '独立原始两行100和200合计应为300，尚未代表执行率C02关闭。',
        'assertions': [{'factId': calculation.results[0].fact_id, 'expectedStatus': 'computed', 'expectedValue': '300', 'unit': 'CNY'}]}
    return ctx, service, binding, payload, SimpleNamespace(datasets=datasets, configuration_provider=SimpleNamespace(vault=ctx['vault']),
        report_build_identity=build_identity(), test_workflow_scope=scope, business_evidence_service=ctx['policy_service'].evidence), calculation


async def test_regression_persists_actual_snapshot_replay_and_expected_values_without_resolving(regression_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_regressions import (
        read_regression,
        verify_regression,
    )
    from smart_reporting.management.repository import report_basis_receipts

    ctx, service, binding, payload, runtime, calculation = regression_context
    result = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    assert result.status == 'passed'
    assert result.comparisons[0].actual == calculation.results[0]
    assert result.snapshot_files == tuple(item.file for item in calculation.datasets)
    assert result.verifier_build == runtime.report_build_identity
    assert result.business_approval == 'not_performed'
    assert await read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', result.receipt_id) == result
    assert await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime) == result
    with pytest.raises(ManagementError) as changed:
        await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', {**payload, 'expectationReason': '改变原请求内容'}, runtime=runtime)
    assert changed.value.status == 409
    original = (await service.report_list(**binding))['items'][0]
    assert original['version'] == 2 and original['review']['status'] == 'accepted'
    assert original['review']['regressionCaseIds'] == []
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(report_basis_receipts)
            .where(report_basis_receipts.c.receipt_id == result.receipt_id)) == 1


async def test_failed_expectation_is_persisted_as_failed_and_cannot_be_rewritten(regression_context):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_regressions import (
        read_regression,
        verify_regression,
    )

    ctx, service, binding, payload, runtime, _ = regression_context
    request = {**payload, 'assertions': [{**payload['assertions'][0], 'expectedValue': '310'}]}
    result = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', request, runtime=runtime)
    assert result.status == 'failed' and not result.comparisons[0].matches
    assert result.comparisons[0].actual.value == 300
    assert (await read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', result.receipt_id)).status == 'failed'
    with pytest.raises(ManagementError) as overwrite:
        await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    assert overwrite.value.status == 409
    assert (await service.report_list(**binding))['items'][0]['review']['status'] == 'accepted'


async def test_regression_targets_bind_real_calculations_without_prefilling_expected_values(regression_context):
    import httpx
    from agno.run import RunContext
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router
    from smart_reporting.management.settings import ManagementSettings

    ctx, service, _, payload, runtime, calculation = regression_context
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example'), report_runtime=runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/regression-targets'
    params = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id, 'limit': 1}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(path, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        first = await client.get(path, params=params)
        assert first.status_code == 200 and first.headers['cache-control'] == 'no-store'
        result = first.json()
        assert result['issueVersion'] == 2
        assert result['items'][0]['targetRunId'] == payload['targetRunId']
        assert result['items'][0]['calculationReceiptId'] == calculation.receipt_id
        assert result['items'][0]['available'] is True
        facts = result['items'][0]['facts']
        assert facts == [{'factId': calculation.results[0].fact_id, 'unit': 'CNY', 'dimensions': []}]
        assert 'value' not in facts[0] and 'expectedValue' not in facts[0]
        assert (await client.get(path, params={**params, 'q': 'no-match'})).json()['items'] == []
        assert (await client.get(path, params={**params, 'after': 'invalid'})).status_code == 422
        assert (await client.get(path, params={**params, 'companyId': ctx['other_scope'].company_id})).status_code == 404
        await service.bases.append_basis_receipt('fixed-run', ctx['scope'], user_id='7', thread_id='fixed-thread',
            receipt_id='fixed-calculation-2', report_revision='initial', request=calculation.request, results=calculation.results,
            readiness=calculation.readiness, dataset_handles=tuple(item.to_handle() for item in calculation.datasets),
            dataset_store=runtime.datasets,
            run_context=RunContext(run_id='fixed-run', session_id=calculation.workspace.workspace_key),
            workflow_scope=runtime.test_workflow_scope)
        first = (await client.get(path, params=params)).json()
        assert first['nextCursor']
        second = (await client.get(path, params={**params, 'after': first['nextCursor']})).json()
        assert second['items'][0]['calculationReceiptId'] == 'fixed-calculation-2'
        assert second['nextCursor'] is None
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', {
            'expectedVersion': 2, 'status': 'needs_evidence', 'decisionReason': '回归前须补独立预期依据'})
        assert (await client.get(path, params=params)).status_code == 409


async def test_resolution_regressions_replay_current_files_and_never_treat_history_as_current_proof(regression_context):
    from smart_reporting.management.report_issue_regression_checks import check_regression_evidence
    from smart_reporting.management.report_issue_regressions import (
        read_regression,
        verify_regression,
    )

    ctx, service, binding, payload, runtime, calculation = regression_context
    saved = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    request = {'expectedIssueVersion': 2, 'regressionReceiptIds': [saved.receipt_id]}
    good = await check_regression_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', request, runtime=runtime)
    assert good['regressionEvidenceReady'] is True and good['issues'] == []
    assert good['businessApproval'] == 'not_performed'
    assert good['checks'][0]['receiptId'] == saved.receipt_id
    assert good['checks'][0]['status'] == 'passed'
    failed = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', {
        **payload, 'requestId': 'known-failed', 'assertions': [{**payload['assertions'][0], 'expectedValue': '310'}]}, runtime=runtime)
    bad = await check_regression_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', {
        **request, 'regressionReceiptIds': [failed.receipt_id]}, runtime=runtime)
    assert bad['regressionEvidenceReady'] is False
    assert bad['checks'][0]['issues'][0]['code'] == 'management_issue_regression_failed'
    await runtime.datasets.service.adelete_file(calculation.workspace.workspace_key, calculation.datasets[0].file.path)
    missing = await check_regression_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', request, runtime=runtime)
    assert missing['regressionEvidenceReady'] is False
    assert missing['checks'][0]['issues'][0]['code'] == 'metric_snapshot_invalid'
    assert await read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', saved.receipt_id) == saved
    issue = (await service.report_list(**binding))['items'][0]
    assert issue['review']['status'] == 'accepted' and issue['version'] == 2


async def test_current_regression_check_rejects_stale_receipts_and_changes_during_replay(regression_context, monkeypatch):
    import smart_reporting.management.report_issue_regressions as module
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_regression_checks import check_regression_evidence

    ctx, service, _, payload, runtime, _ = regression_context
    saved = await module.verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    request = {'expectedIssueVersion': 2, 'regressionReceiptIds': [saved.receipt_id]}
    replay = module.replay_metric_calculation
    async def change_during_replay(*args, **kwargs):
        result = await replay(*args, **kwargs)
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(expectedVersion=2, decisionReason='补充预期后须重新核验'))
        return result
    with monkeypatch.context() as fault:
        fault.setattr(module, 'replay_metric_calculation', change_during_replay)
        with pytest.raises(ManagementError) as conflict:
            await check_regression_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', request, runtime=runtime)
        assert conflict.value.code == 'management_version_conflict'
    stale = await check_regression_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', {
        **request, 'expectedIssueVersion': 3}, runtime=runtime)
    assert stale['regressionEvidenceReady'] is False
    assert stale['checks'][0]['issues'][0]['code'] == 'management_issue_regression_stale'


async def test_current_regression_check_http_is_read_only_scoped_csrf_and_strict(regression_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.management.settings import ManagementSettings

    ctx, service, _, payload, runtime, _ = regression_context
    saved = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example'), report_runtime=runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/regression-evidence-check'
    body = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
        'expectedIssueVersion': 2, 'regressionReceiptIds': [saved.receipt_id]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.post(path, json=body)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        assert (await client.post(path, json=body)).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(ctx['token'])}
        assert (await client.post(path, json={**body, 'regressionEvidenceReady': True}, headers=headers)).status_code == 422
        assert (await client.post(path, json={**body, 'regressionReceiptIds': [saved.receipt_id, saved.receipt_id]}, headers=headers)).status_code == 422
        assert (await client.post(path, json={**body, 'companyId': ctx['other_scope'].company_id}, headers=headers)).status_code == 404
        result = await client.post(path, json=body, headers=headers)
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert result.json()['regressionEvidenceReady'] is True and result.json()['issueClosed'] is False
        missing = await client.post(path, json={**body, 'regressionReceiptIds': ['foreign-regression']}, headers=headers)
        assert missing.json()['regressionEvidenceReady'] is False
        assert missing.json()['checks'][0]['issues'][0]['code'] == 'management_issue_regression_not_found'


@pytest.mark.parametrize('regression_context', ['adopted'], indirect=True)
async def test_resolution_evidence_checks_native_parent_and_actual_business_originals(regression_context):
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.management.report_issue_resolution_evidence import (
        check_resolution_evidence,
    )
    from smart_reporting.management.repository import business_document_revisions

    ctx, service, binding, payload, runtime, _ = regression_context
    regression = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    request = {'expectedIssueVersion': 2, 'regressionReceiptIds': [regression.receipt_id]}
    result = await check_resolution_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', request, runtime=runtime)
    assert result['regressionEvidenceReady'] is True and result['originalEvidenceReady'] is True
    assert result['reportRelationships'][0]['status'] == 'verified'
    assert result['reportRelationships'][0]['parentBasisId'] == binding['basis_id']
    assert result['reportRelationships'][0]['targetRunId'] == payload['targetRunId']
    assert result['reportRelationships'][0]['deliveryVerified'] is False
    assert result['deliveryReady'] is False
    assert result['reportRelationships'][0]['deliveryIssues'][0]['code'] == 'management_issue_delivery_check_unavailable'
    assert result['originalChecks'][0]['documentId'] == 'budget-rules'
    assert result['originalChecks'][0]['title']
    assert result['originalChecks'][0]['status'] == 'readable'
    async with ctx['repository'].transaction() as connection:
        original = (await connection.execute(select(business_document_revisions).where(
            business_document_revisions.c.scope_id == ctx['scope_id'], business_document_revisions.c.document_id == 'budget-rules',
            business_document_revisions.c.revision == 1))).mappings().one()
    await runtime.business_evidence_service.documents.originals.discard(ctx['scope_id'], original['original_resource_id'])
    unavailable = await check_resolution_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', request, runtime=runtime)
    assert unavailable['originalEvidenceReady'] is False and unavailable['regressionEvidenceReady'] is True
    assert unavailable['originalChecks'][0]['issues'][0]['code'] == 'management_document_original_unavailable'
    assert unavailable['issueClosed'] is False and unavailable['businessApproval'] == 'not_performed'
    assert (await service.report_list(**binding))['items'][0]['review']['status'] == 'accepted'


async def test_resolution_evidence_never_accepts_an_independent_run_as_original_report_child(regression_context):
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.management.report_issue_resolution_evidence import (
        check_resolution_evidence,
    )

    ctx, service, _, payload, runtime, _ = regression_context
    regression = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    result = await check_resolution_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', {
        'expectedIssueVersion': 2, 'regressionReceiptIds': [regression.receipt_id]}, runtime=runtime)
    assert result['regressionEvidenceReady'] is True
    assert result['reportRelationships'][0]['status'] == 'unverified'
    assert result['reportRelationships'][0]['issues']
    assert result['issueClosed'] is False


async def test_resolution_evidence_rejects_review_changes_during_original_read(regression_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.management.report_issue_resolution_evidence import (
        check_resolution_evidence,
    )

    ctx, service, _, payload, runtime, _ = regression_context
    regression = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    documents = runtime.business_evidence_service.documents
    read = documents.read_original
    async def changed_review(*args, **kwargs):
        content = await read(*args, **kwargs)
        detail = await documents.get_document(ctx['token'], ctx['scope'], 'budget-rules')
        version = next(item['stateVersion'] for item in detail['revisions'] if item['revision'] == 1)
        await documents.review_revision(ctx['token'], ctx['scope'], 'budget-rules', 1,
            decision='approved', reason='复核读取期间原件审核变动', expected_version=version)
        return content
    monkeypatch.setattr(documents, 'read_original', changed_review)
    with pytest.raises(ManagementError) as conflict:
        await check_resolution_evidence(service, ctx['token'], ctx['scope'], 'issue-C02', {
            'expectedIssueVersion': 2, 'regressionReceiptIds': [regression.receipt_id]}, runtime=runtime)
    assert conflict.value.code == 'management_version_conflict'


async def test_resolution_evidence_http_auth_csrf_scope_and_missing_original_service(regression_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.report_issue_regressions import verify_regression
    from smart_reporting.management.settings import ManagementSettings

    ctx, service, _, payload, runtime, _ = regression_context
    regression = await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example'), report_runtime=runtime))
    path = '/management/api/v1/report-issue-reviews/issue-C02/resolution-evidence-check'
    body = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id,
        'expectedIssueVersion': 2, 'regressionReceiptIds': [regression.receipt_id]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.post(path, json=body)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        assert (await client.post(path, json=body)).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(ctx['token'])}
        assert (await client.post(path, json={**body, 'companyId': ctx['other_scope'].company_id}, headers=headers)).status_code == 404
        result = await client.post(path, json=body, headers=headers)
        assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
        assert result.json()['originalEvidenceReady'] is True and result.json()['issueClosed'] is False
        assert result.json()['deliveryReady'] is False
        runtime.business_evidence_service = None
        assert (await client.post(path, json=body, headers=headers)).status_code == 503


async def test_regression_checks_organization_and_complete_assertions_before_accepting(regression_context, monkeypatch):
    from smart_reporting.management.models import ManagementError
    from smart_reporting.management.report_issue_regressions import verify_regression

    ctx, service, _, payload, runtime, _ = regression_context
    async def no_files(*args, **kwargs):
        pytest.fail('跨组织请求不得读取快照文件')
    with monkeypatch.context() as fault:
        fault.setattr(runtime.datasets.service, 'ahash_file', no_files)
        with pytest.raises(ManagementError) as foreign:
            await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', {**payload, 'targetRunId': 'run-other'}, runtime=runtime)
        assert foreign.value.status == 403
    for assertion in ({**payload['assertions'][0], 'factId': 'foreign-fact'},):
        with pytest.raises(ManagementError) as incomplete:
            await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', {**payload, 'assertions': [assertion]}, runtime=runtime)
        assert incomplete.value.code == 'management_issue_regression_incomplete'


async def test_issue_change_during_replay_prevents_stale_regression_registration(regression_context, monkeypatch):
    from smart_reporting.management import report_issue_regressions as module
    from smart_reporting.management.models import ManagementError
    from smart_reporting.reporting.semantics.issue_regression import regression_receipt_id

    ctx, service, binding, payload, runtime, _ = regression_context
    replay = module.replay_metric_calculation
    async def concurrent_change(*args, **kwargs):
        result = await replay(*args, **kwargs)
        await service.decide(ctx['token'], ctx['scope'], 'issue-C02', accepted_fix(expectedVersion=2, decisionReason='补充反例后重新核对'))
        return result
    monkeypatch.setattr(module, 'replay_metric_calculation', concurrent_change)
    with pytest.raises(ManagementError) as stale:
        await module.verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    assert stale.value.code == 'management_version_conflict'
    identity = regression_receipt_id(binding['basis_id'], 'issue-C02', payload['requestId'])
    assert await module.read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', identity) is None


async def test_management_http_regression_uses_auth_csrf_exact_get_and_real_snapshots(regression_context):
    import httpx
    from fastapi import FastAPI

    from smart_reporting.management.api import SESSION_COOKIE, create_management_router, csrf_token
    from smart_reporting.management.settings import ManagementSettings
    from smart_reporting.reporting.semantics.issue_regression import regression_receipt_id

    ctx, _, binding, payload, runtime, _ = regression_context
    app = FastAPI()
    app.include_router(create_management_router(ctx['scopes'].auth, ManagementSettings(public_origin='https://reports.example'), report_runtime=runtime))
    params = {'scopeDatabase': ctx['scope'].database, 'companyId': ctx['scope'].company_id}
    path = '/management/api/v1/report-issue-reviews/issue-C02/regressions'
    receipt = regression_receipt_id(binding['basis_id'], 'issue-C02', payload['requestId'])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='https://reports.example') as client:
        assert (await client.get(path, params=params)).status_code == 401
        assert (await client.get(path + '/' + receipt, params=params)).status_code == 401
        client.cookies.set(SESSION_COOKIE, ctx['token'], path='/management')
        assert (await client.get(path + '/' + receipt, params=params)).status_code == 404
        assert (await client.post(path, json={**params, **payload})).status_code == 403
        headers = {'origin': 'https://reports.example', 'x-csrf-token': csrf_token(ctx['token'])}
        assert (await client.post(path, json={**params, **payload, 'status': 'passed'}, headers=headers)).status_code == 422
        result = await client.post(path, json={**params, **payload}, headers=headers)
        assert result.status_code == 200 and result.json()['status'] == 'passed'
        assert result.headers['cache-control'] == 'no-store'
        recovered = await client.get(path + '/' + receipt, params=params)
        assert recovered.json() == result.json()
        assert recovered.headers['cache-control'] == 'no-store'
        assert (await client.get(path + '/' + receipt, params={**params, 'companyId': ctx['other_scope'].company_id})).status_code == 404
        history = await client.get(path, params=params)
        assert history.status_code == 200
        assert history.json()['items'] == [result.json()]
        assert history.headers['cache-control'] == 'no-store'
        assert (await client.get(path, params={**params, 'companyId': ctx['other_scope'].company_id})).status_code == 404
        assert (await client.get(path, params={**params, 'limit': 0})).status_code == 422
        assert (await client.get(path, params={**params, 'limit': 101})).status_code == 422
        second = await client.post(path, json={**params, **payload, 'requestId': 'second-case',
            'assertions': [{**payload['assertions'][0], 'expectedValue': '310'}]}, headers=headers)
        assert second.status_code == 200 and second.json()['status'] == 'failed'
        exact = await client.get(path, params={**params, 'requestId': payload['requestId']})
        assert exact.json() == {'items': [result.json()], 'nextCursor': None}
        assert (await client.get(path, params={**params, 'requestId': 'unknown-request'})).json()['items'] == []
        first_page = await client.get(path, params={**params, 'limit': 1})
        cursor = first_page.json()['nextCursor']
        assert cursor
        second_page = await client.get(path, params={**params, 'limit': 1, 'after': cursor})
        assert {first_page.json()['items'][0]['receiptId'], second_page.json()['items'][0]['receiptId']} == {
            result.json()['receiptId'], second.json()['receiptId']}
        assert second_page.json()['nextCursor'] is None


async def test_regression_audit_rollback_and_commit_response_loss_preserve_exact_record(regression_context, monkeypatch):
    from contextlib import asynccontextmanager

    from sqlalchemy import update
    from sqlalchemy.exc import IntegrityError

    from smart_reporting.management.report_issue_regressions import (
        read_regression,
        verify_regression,
    )
    from smart_reporting.management.repository import audit_events, report_basis_receipts
    from smart_reporting.reporting.semantics.issue_regression import regression_receipt_id

    ctx, service, binding, payload, runtime, _ = regression_context
    receipt_id = regression_receipt_id(binding['basis_id'], 'issue-C02', payload['requestId'])
    original_audit = ctx['scopes'].audit
    async def audit_failure(connection, actor, action, details):
        if action == 'report_issue_regression_verified':
            raise RuntimeError('regression audit failed')
        return await original_audit(connection, actor, action, details)
    with monkeypatch.context() as fault:
        fault.setattr(ctx['scopes'], 'audit', audit_failure)
        with pytest.raises(RuntimeError, match='regression audit failed'):
            await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    assert await read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', receipt_id) is None
    transaction = ctx['scopes'].write_transaction
    @asynccontextmanager
    async def lost_response(actor):
        async with transaction(actor) as connection:
            yield connection
            committed_proof = await connection.scalar(select(func.count()).select_from(report_basis_receipts)
                .where(report_basis_receipts.c.receipt_id == receipt_id))
        if committed_proof:
            raise ConnectionError('regression response lost after commit')
    with monkeypatch.context() as fault:
        fault.setattr(ctx['scopes'], 'write_transaction', lost_response)
        with pytest.raises(ConnectionError):
            await verify_regression(service, ctx['token'], ctx['scope'], 'issue-C02', payload, runtime=runtime)
    saved = await read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', receipt_id)
    assert saved.status == 'passed' and saved.request.request_id == payload['requestId']
    async with ctx['repository'].transaction() as connection:
        assert await connection.scalar(select(func.count()).select_from(audit_events)
            .where(audit_events.c.action == 'report_issue_regression_verified')) == 1
    with pytest.raises(IntegrityError):
        async with ctx['repository'].engine.begin() as connection:
            await connection.execute(update(report_basis_receipts).where(report_basis_receipts.c.receipt_id == receipt_id)
                .values(content_hash='0' * 64))
    assert await read_regression(service, ctx['token'], ctx['scope'], 'issue-C02', receipt_id) == saved


@pytest.mark.parametrize('regression_context', ['adopted'], indirect=True)
async def test_resolution_delivery_never_treats_registered_basis_as_finished_report(regression_context):
    from smart_reporting.management.report_issue_delivery_checks import check_adopted_delivery

    ctx, service, _, payload, runtime, _ = regression_context
    adoption = await service.bases.read_policy_adoption('run-basis', ctx['scope'], user_id='7',
        thread_id='thread-basis', request_id='issue-fix-adoption')
    result = await check_adopted_delivery(runtime, adoption, ctx['scope'],
        parent_run_id='run-basis', user_id='7', thread_id='thread-basis')
    assert result['deliveryVerified'] is False and result['deliveryArtifacts'] == []
    assert result['deliveryIssues'][0]['code'] == 'management_issue_delivery_check_unavailable'
