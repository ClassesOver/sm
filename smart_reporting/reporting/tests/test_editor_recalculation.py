"""原快照复核请求的持久幂等与报告身份边界。"""

import asyncio
import hashlib

import pytest

from smart_reporting.report_editor import ReportEditorContext, ReportEditorService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_office_revision_safety import ConcurrentRepository
from smart_reporting.reporting.tests.test_registered_claim_support import native_quality_inputs


async def native_editor(tmp_path):
    runtime, arguments, scope, durable, _, _, contents, index = await native_quality_inputs(tmp_path, publication_fixture=True)
    await runtime.issue_http_publication(**arguments)
    runtime.workspace_registry.resolve(scope)
    context = ReportEditorContext.model_validate(durable.payload['reportEditorContexts']['2'])
    repository = ConcurrentRepository(context)
    repository.state = repository.state.model_copy(update={'payload': durable.payload})
    editor = ReportEditorService(state_repository=repository, workspace_registry=runtime.workspace_registry,
        workspace=runtime.workspace_service)
    file = next(item for item in index.files if item.resource_id == index.markdown_file_resource_id)
    markdown = contents[file.path].decode()
    return editor, repository, context, markdown


def test_policy_adoption_execution_import_does_not_require_editor_first():
    import subprocess
    import sys

    subprocess.run([sys.executable, '-c',
        'from smart_reporting.reporting.workflow.policy_adoption import PolicyAdoptionExecution; '
        'from smart_reporting.report_editor.recalculation import PolicyAdoptionDeliveryResult; '
        'assert PolicyAdoptionExecution is not None and PolicyAdoptionDeliveryResult is not None'], check=True)


@pytest.mark.anyio
async def test_duplicate_snapshot_requests_read_back_durable_result_without_rechecking(tmp_path, monkeypatch):
    from smart_reporting.report_editor.recalculation import RecalculationRequest

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='verify-1', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    validate = editor.trace.validate
    calls = []

    async def counted(*args, **kwargs):
        calls.append(1)
        await asyncio.sleep(0)
        return await validate(*args, **kwargs)

    monkeypatch.setattr(editor.trace, 'validate', counted)
    first, repeated = await asyncio.gather(editor.start_recalculation(context, request),
        editor.start_recalculation(context, request))
    assert first == repeated
    assert first['status'] == 'completed'
    assert first['result']['calculationStatus'] == 'not_recalculated'
    assert first['result']['businessApproval'] == 'not_performed'
    assert len(calls) == 1
    recreated = ReportEditorService(state_repository=repository, workspace_registry=editor.workspace_registry,
        workspace=editor.workspace)
    assert await recreated.recalculation_status(context, 'verify-1') == first
    assert await recreated.start_recalculation(context, request) == first
    assert len(calls) == 1


@pytest.mark.anyio
async def test_same_request_with_different_input_conflicts_and_keeps_original(tmp_path):
    from smart_reporting.report_editor.recalculation import RecalculationRequest

    editor, _, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='verify-1', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    first = await editor.start_recalculation(context, request)
    changed = request.model_copy(update={'expected_sha256': '0' * 64})
    with pytest.raises(ReportingError, match='report_editor_conflict'):
        await editor.start_recalculation(context, changed)
    assert await editor.recalculation_status(context, request.request_id) == first


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['revision', 'draft', 'refresh_data', 'adopt_policy'])
async def test_invalid_or_unimplemented_request_does_not_create_a_fake_task(tmp_path, fault):
    from smart_reporting.report_editor.recalculation import RecalculationRequest

    editor, repository, context, markdown = await native_editor(tmp_path)
    values = dict(requestId='request', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    if fault == 'revision':
        values['parentRevision'] += 1
    elif fault == 'draft':
        values['expectedSha256'] = '0' * 64
    else:
        values['operation'] = fault
    if fault == 'adopt_policy':
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            RecalculationRequest(**values)
        assert not repository.state.payload.get('reportEditorRecalculations')
        return
    with pytest.raises(ReportingError):
        await editor.start_recalculation(context, RecalculationRequest(**values))
    assert not repository.state.payload.get('reportEditorRecalculations')


@pytest.mark.anyio
async def test_verification_exception_is_a_durable_failed_task_without_changing_original(tmp_path, monkeypatch):
    from smart_reporting.report_editor.recalculation import RecalculationRequest

    editor, repository, context, markdown = await native_editor(tmp_path)
    before = repository.state.payload['reportEditorContexts'].copy()
    request = RecalculationRequest(requestId='verify-failure', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')

    async def unavailable(*args, **kwargs):
        raise OSError('no private path in receipt')

    monkeypatch.setattr(editor.trace, 'validate', unavailable)
    result = await editor.start_recalculation(context, request)
    assert result['status'] == 'failed'
    assert result['errorCode'] == 'snapshot_verification_unavailable'
    assert 'private' not in str(result)
    assert await editor.start_recalculation(context, request) == result
    assert repository.state.payload['reportEditorContexts'] == before


@pytest.mark.anyio
async def test_recalculation_http_requires_session_csrf_and_matching_report(tmp_path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
    from smart_reporting.report_editor.service import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )

    editor, repository, context, markdown = await native_editor(tmp_path)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/recalculations'
    payload = dict(requestId='http-verify', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        assert (await client.get(base + '/http-verify')).status_code == 404
        assert (await client.get(base + '/http-verify/delivery')).status_code == 404
        await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
        sources = await client.get(base.replace('/recalculations', '/sources'))
        assert sources.json()['dataRefresh'] == {'available': False, 'parentRevision': context.revision}
        assert (await client.post(base, json=payload)).status_code == 403
        assert not repository.state.payload.get('reportEditorRecalculations')
        headers = {'origin': 'http://reports.test',
            'x-csrf-token': grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
        response = await client.post(base, json=payload, headers=headers)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        result = response.json()
        assert result['status'] == 'completed'
        task_readback = await client.get(base + '/' + result['taskId'])
        assert task_readback.status_code == 200 and task_readback.json() == result
        assert task_readback.headers['cache-control'] == 'no-store'
        assert (await client.get(base + '/http-verify')).status_code == 404
        assert (await client.get(base.replace('/recalculations', '/recalculation-requests') + '/http-verify')).json() == result
        conflict = await client.post(base, json={**payload, 'expectedSha256': '0' * 64}, headers=headers)
        assert conflict.status_code == 409
        unsupported = await client.post(base, json={**payload, 'requestId': 'refresh', 'operation': 'refresh_data'}, headers=headers)
        assert unsupported.status_code == 503
        unavailable_delivery = await client.get(base + '/' + result['taskId'] + '/delivery')
        assert unavailable_delivery.status_code == 503
        assert unavailable_delivery.json()['detail']['code'] == 'report_editor_recalculation_unavailable'
        for wrong in (base.replace(context.report_id, 'foreign-report'), base.replace(f'/{context.revision}/api', '/999/api')):
            denied = await client.get(wrong + '/' + result['taskId'], headers={
                'cookie': EDITOR_SESSION_COOKIE + '=' + client.cookies.get(EDITOR_SESSION_COOKIE)})
            assert denied.status_code == 404
            assert denied.json()['detail']['code'] == 'report_editor_scope_mismatch'
            assert result['taskId'] not in denied.text
            delivery_denied = await client.get(wrong + '/' + result['taskId'] + '/delivery', headers={
                'cookie': EDITOR_SESSION_COOKIE + '=' + client.cookies.get(EDITOR_SESSION_COOKIE)})
            assert delivery_denied.status_code == 404
            assert delivery_denied.json()['detail']['code'] == 'report_editor_scope_mismatch'


@pytest.mark.anyio
@pytest.mark.integration
async def test_snapshot_receipt_survives_real_postgres_repository_restart(tmp_path, monkeypatch):
    import os

    from smart_reporting.report_editor.recalculation import RecalculationRequest
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    database = create_agent_database(url)
    repository = ReportingStateRepository(database.async_db)
    try:
        await repository.initialize()
        await repository.create(memory.state)
        editor.state_repository = repository
        request = RecalculationRequest(requestId='pg-verify', parentRevision=context.revision,
            expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
        concurrent = ReportEditorService(state_repository=ReportingStateRepository(database.async_db),
            workspace_registry=editor.workspace_registry, workspace=editor.workspace)
        first, repeated = await asyncio.gather(editor.start_recalculation(context, request),
            concurrent.start_recalculation(context, request))
        assert first == repeated
        restarted = ReportingStateRepository(database.async_db)
        editor.state_repository = restarted

        async def no_repeat(*args, **kwargs):
            pytest.fail('持久任务读回不能重新执行复核')

        monkeypatch.setattr(editor.trace, 'validate', no_repeat)
        assert await editor.start_recalculation(context, request) == first
        stored = await restarted.get(context.workflow_run_id)
        assert stored.payload['reportEditorRecalculations'][first['taskId']] == first
    finally:
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('lost_stage', ['pending', 'completed'])
async def test_lost_commit_response_can_be_read_back_and_pending_verification_resumed(tmp_path, monkeypatch, lost_stage):
    from smart_reporting.report_editor.recalculation import RecalculationRequest

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='lost-response', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    apply = repository.apply
    injected = []

    async def lose_response(run, command, **kwargs):
        result = await apply(run, command, **kwargs)
        if (command.name == 'record_report_editor_recalculation'
                and command.payload['task']['status'] == lost_stage and not injected):
            injected.append(True)
            raise OSError('response lost after durable commit')
        return result

    monkeypatch.setattr(repository, 'apply', lose_response)
    with pytest.raises(OSError):
        await editor.start_recalculation(context, request)
    readback = await editor.recalculation_status(context, request.request_id)
    assert readback['status'] == lost_stage
    resumed = await editor.start_recalculation(context, request)
    assert resumed['taskId'] == readback['taskId']
    assert resumed['status'] == 'completed'
    assert resumed['createdAt'] == readback['createdAt']
    if lost_stage == 'completed':
        assert resumed == readback


@pytest.mark.anyio
@pytest.mark.parametrize('tamper', ['basis', 'request', 'result', 'report', 'draft_identity'])
async def test_durable_terminal_receipt_cannot_be_overwritten_or_rebound(tmp_path, tamper):
    from smart_reporting.report_editor.recalculation import RecalculationRequest
    from smart_reporting.reporting.workflow.state import ReportingCommand, ReportingStateError

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='immutable', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    result = await editor.start_recalculation(context, request)
    import copy

    forged = copy.deepcopy(result)
    if tamper == 'basis':
        forged['basisId'] = 'foreign-basis'
    elif tamper == 'request':
        forged['request']['expectedSha256'] = '0' * 64
    elif tamper == 'report':
        forged['reportId'] = 'foreign-report'
    elif tamper == 'draft_identity':
        forged['result']['draftSha256'] = '0' * 64
    else:
        forged['result']['issueCodes'] = ['fabricated-success']
    with pytest.raises(ReportingStateError):
        await repository.apply(context.workflow_run_id, ReportingCommand(name='record_report_editor_recalculation',
            payload={'task': forged}, commandId='forged-terminal'), expected_version=repository.state.state_version)
    assert await editor.recalculation_status(context, request.request_id) == result


@pytest.mark.anyio
async def test_damaged_frozen_source_records_specific_issue_without_approving_business(tmp_path):
    from smart_reporting.report_editor.recalculation import RecalculationRequest

    editor, _, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    fact_file = next(item for item in index.files if item.resource_id == index.fact_files[0].file_resource_id)
    original, _ = await editor.workspace.afile_bytes(context.scope['threadId'], fact_file.path)
    await editor.workspace.awrite_bytes(context.scope['threadId'], fact_file.path, original + b'\n', overwrite=True)
    request = RecalculationRequest(requestId='source-integrity', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='verify_snapshot')
    task = await editor.start_recalculation(context, request)
    assert task['status'] == 'completed'
    assert task['result']['sourceIssueCount'] > 0
    assert 'snapshot_integrity_failed' in task['result']['issueCodes']
    assert task['result']['businessApproval'] == 'not_performed'
    assert task['result']['allKeyFactsEvaluated'] is False


@pytest.mark.anyio
async def test_refresh_request_binding_is_durable_immutable_and_distinct_from_delivery_revision(tmp_path):
    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        register_refresh_request,
    )

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='refresh-bound', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await register_refresh_request(editor, context, request, parent_report_revision='semantic-revision-7')
    assert task.status == 'pending' and task.result is None
    assert task.refresh_binding.parent_report_revision == 'semantic-revision-7'
    assert task.refresh_binding.report_revision != str(context.revision)
    assert await register_refresh_request(editor, context, request, parent_report_revision='semantic-revision-7') == task
    readback = await editor.recalculation_status(context, request.request_id)
    assert readback.pop('execution') == {'runId': None, 'status': 'unavailable',
        'issueCodes': ['refresh_status_backend_unavailable']}
    assert readback == task.model_dump(mode='json', by_alias=True)
    with pytest.raises(ReportingError, match='report_editor_conflict'):
        await register_refresh_request(editor, context, request, parent_report_revision='semantic-revision-8')
    assert len(repository.state.payload['reportEditorRecalculations']) == 1


@pytest.mark.anyio
async def test_refresh_binding_response_loss_reads_back_and_rejects_rebound_target(tmp_path, monkeypatch):
    from copy import deepcopy

    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        register_refresh_request,
    )
    from smart_reporting.reporting.workflow.state import ReportingCommand, ReportingStateError

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='refresh-lost', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    apply = repository.apply
    async def lost_response(*args, **kwargs):
        await apply(*args, **kwargs)
        raise OSError('request committed response lost')
    monkeypatch.setattr(repository, 'apply', lost_response)
    with pytest.raises(OSError):
        await register_refresh_request(editor, context, request, parent_report_revision='initial')
    monkeypatch.setattr(repository, 'apply', apply)
    saved = await editor.recalculation_status(context, request.request_id)
    assert (await register_refresh_request(editor, context, request,
        parent_report_revision='initial')).task_id == saved['taskId']
    forged = deepcopy(saved)
    forged['request']['requestId'] = 'foreign'
    forged['refreshBinding']['reportRevision'] = 'editor-refresh-' + 'b' * 32
    # 使用实际派生taskId，让反例只针对目标计算修订的改绑。
    from smart_reporting.report_editor.recalculation import request_hash, task_identity
    forged['taskId'] = task_identity(context, 'foreign')
    forged['inputHash'] = request_hash(context, RecalculationRequest.model_validate(forged['request']))
    with pytest.raises(ReportingStateError):
        await repository.apply(context.workflow_run_id, ReportingCommand(name='record_report_editor_recalculation',
            commandId='forged-refresh-target', payload={'task': forged}), expected_version=repository.state.state_version)


@pytest.mark.anyio
@pytest.mark.integration
async def test_refresh_binding_survives_real_repository_restart(tmp_path):
    import os

    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        register_refresh_request,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    database = create_agent_database(url)
    repository = ReportingStateRepository(database.async_db)
    try:
        await repository.initialize()
        await repository.create(memory.state)
        editor.state_repository = repository
        request = RecalculationRequest(requestId='pg-refresh', parentRevision=context.revision,
            expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
        first = await register_refresh_request(editor, context, request, parent_report_revision='initial')
        restarted = ReportEditorService(state_repository=ReportingStateRepository(database.async_db),
            workspace_registry=editor.workspace_registry, workspace=editor.workspace)
        assert await register_refresh_request(restarted, context, request, parent_report_revision='initial') == first
        readback = await restarted.recalculation_status(context, request.request_id)
        assert readback.pop('execution') == {'runId': None, 'status': 'unavailable',
            'issueCodes': ['refresh_status_backend_unavailable']}
        assert readback == first.model_dump(mode='json', by_alias=True)
        assert first.status == 'pending' and first.result is None
    finally:
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'management_mismatch', 'changed_fact', 'missing_service'])
async def test_refresh_parent_requires_actual_fact_identity_and_matching_management_receipt(tmp_path, fault):
    import json
    from types import SimpleNamespace

    from smart_reporting.report_editor.recalculation import resolve_refresh_parent
    from smart_reporting.reporting.semantics.planning_contracts import MetricPlanningContext

    editor, _, context, _ = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    entry = next(item for item in index.fact_files if item.content_kind == 'deterministic_bundle')
    file = next(item for item in index.files if item.resource_id == entry.file_resource_id)
    raw = await editor.trace._read_registered_file(context, file, max_bytes=16 * 1024 * 1024)
    parent = MetricPlanningContext.model_validate(json.loads(raw)['metricContext'])
    async def load_registered(run_id, scope, **options):
        assert run_id == context.workflow_run_id
        assert options['report_revision'] == parent.report_revision
        if fault == 'management_mismatch':
            return parent.model_copy(update={'report_revision': 'other-calculation-revision'})
        return parent
    editor.trace.report_basis_service = SimpleNamespace(load_registered_revision_planning_context=load_registered)
    if fault == 'missing_service':
        editor.trace.report_basis_service = None
    elif fault == 'changed_fact':
        await editor.workspace.awrite_bytes(context.scope['threadId'], file.path, raw + b' ', overwrite=True)
    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        register_refresh_request,
    )
    document = await editor.read_document(context)
    request = RecalculationRequest(requestId='resolved-parent', parentRevision=context.revision,
        expectedSha256=document.sha256, operation='refresh_data')
    if fault == 'none':
        assert await resolve_refresh_parent(editor, context, vault=object()) == parent
        task = await register_refresh_request(editor, context, request, vault=object())
        assert task.refresh_binding.parent_report_revision == parent.report_revision
        await editor.workspace.awrite_bytes(context.scope['threadId'], file.path, raw + b' ', overwrite=True)
        # 已登记请求的未知响应读回不依赖再次读取来源文件，也不重新绑定父计算。
        assert await register_refresh_request(editor, context, request, vault=object()) == task
    else:
        with pytest.raises(ReportingError):
            await resolve_refresh_parent(editor, context, vault=object())
        with pytest.raises(ReportingError):
            await register_refresh_request(editor, context, request, vault=object())
        assert not editor.state_repository.state.payload.get('reportEditorRecalculations')


@pytest.mark.anyio
@pytest.mark.parametrize('completion_fault', [None, 'before_commit', 'response_lost', 'changed_pdf'])
async def test_refresh_executor_records_actual_delivery_and_replays_without_rendering(tmp_path, monkeypatch, completion_fault):
    from agno.workflow.types import StepOutput

    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        register_refresh_request,
        run_refresh_request,
    )
    from smart_reporting.reporting.trace.contracts_v1 import canonical_sha256
    from smart_reporting.reporting.workflow import revision_execution as execution_module
    from smart_reporting.reporting.workflow.revision_execution import (
        ReportRevisionExecution,
        execution_run_id,
    )
    from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='run-refresh', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await register_refresh_request(editor, context, request, parent_report_revision='initial')
    source_scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id,
        session_id=context.scope['sessionId'], user_id=context.scope['userId'], stored_scope=context.scope)
    planning_hash = canonical_sha256({'fixture': 'trusted-bound-input'})
    execution = ReportRevisionExecution(sourceScope=source_scope,
        executionRunId=execution_run_id(source_scope, task.basis_id, task.refresh_binding.report_revision, planning_hash),
        basisId=task.basis_id, parentReportRevision='initial', reportRevision=task.refresh_binding.report_revision,
        planningHash=planning_hash, outputRevision=context.revision + 1, requestedOutputs=('pdf', 'docx'))
    root = f'报表/智能分析/{execution.execution_run_id}/document-render/revision-{execution.output_revision}'
    raw = b'identity-checked-output-fixture'
    output = {'revision': execution.output_revision, 'validation': {'ok': False,
        'issues': [{'code': 'business_review_incomplete', 'message': '尚未完成业务核对。'}]},
        'formalReleaseAllowed': False}
    for label, suffix in [('pdf', 'pdf'), ('word', 'docx')]:
        path = f'{root}/report.{suffix}'
        await editor.workspace.awrite_bytes(context.scope['threadId'], path, raw)
        output.update({f'{label}Path': path, f'{label}Size': len(raw), f'{label}Sha256': hashlib.sha256(raw).hexdigest()})
    calls = []
    async def prepare(runtime, run_context, **kwargs):
        assert run_context.run_id == context.workflow_run_id
        assert kwargs['report_revision'] == task.refresh_binding.report_revision
        assert kwargs['parent_report_revision'] == 'initial'
        calls.append('prepare')
        return execution
    async def deliver(runtime, run_context, selected):
        assert selected == execution
        calls.append('deliver')
        return StepOutput(content=output)
    monkeypatch.setattr(execution_module, 'prepare_refresh_delivery', prepare)
    monkeypatch.setattr(execution_module, 'continue_revision_delivery', deliver)
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = editor.workspace
    apply = repository.apply
    if completion_fault == 'changed_pdf':
        await editor.workspace.awrite_bytes(context.scope['threadId'], output['pdfPath'], b'changed', overwrite=True)
    if completion_fault in {'before_commit', 'response_lost'}:
        async def fail_completion(run_id, command, **kwargs):
            if command.name == 'record_report_editor_recalculation' and command.payload['task']['status'] == 'completed':
                if completion_fault == 'response_lost':
                    await apply(run_id, command, **kwargs)
                raise OSError('completion storage unavailable')
            return await apply(run_id, command, **kwargs)
        monkeypatch.setattr(repository, 'apply', fail_completion)
    completed, published = await run_refresh_request(editor, context, task.task_id, runtime=runtime)
    monkeypatch.setattr(repository, 'apply', apply)
    if completion_fault in {'before_commit', 'response_lost'}:
        assert completed.status == 'pending'
        assert published.content['pdfSha256'] == hashlib.sha256(raw).hexdigest()
        assert 'refresh_completion_record_unavailable' in {
            issue['code'] for issue in published.content['validation']['issues']}
        completed, published = await run_refresh_request(editor, context, task.task_id, runtime=runtime)
    assert completed.status == 'completed'
    assert completed.result.calculation_status == 'refreshed'
    assert completed.result.business_approval == 'not_performed'
    assert completed.result.validation_passed is False
    if completion_fault == 'changed_pdf':
        assert 'refresh_pdf_artifact_unavailable' in completed.result.issue_codes
        assert len(completed.result.artifacts) == 1
        assert 'pdfPath' not in published.content
    else:
        assert completed.result.issue_codes == ('business_review_incomplete',)
        assert len(completed.result.artifacts) == 2
        assert published.content['pdfSha256'] == hashlib.sha256(raw).hexdigest()
    if completion_fault is None:
        assert calls == ['prepare', 'deliver']
    before_replay = tuple(calls)
    repeated, recovered = await run_refresh_request(editor, context, task.task_id, runtime=runtime)
    assert repeated == completed and recovered.content['wordSha256'] == published.content['wordSha256']
    assert tuple(calls) == (*before_replay, 'deliver')
    assert (await editor.recalculation_status(context, request.request_id))['status'] == 'completed'


@pytest.mark.anyio
async def test_refresh_delivery_read_before_execution_does_not_start_calculation(tmp_path):
    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        read_refresh_delivery,
        register_refresh_request,
    )

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='read-before-execution', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await register_refresh_request(editor, context, request, parent_report_revision='initial')
    before = repository.state.model_dump(mode='json')
    with pytest.raises(ReportingError, match='report_editor_recalculation_unavailable'):
        await read_refresh_delivery(editor, context, task.task_id, runtime=object())
    assert repository.state.model_dump(mode='json') == before


@pytest.mark.anyio
@pytest.mark.parametrize('operation', ['refresh_data', 'adopt_policy'])
async def test_public_refresh_registers_and_dispatches_native_task_with_csrf(tmp_path, monkeypatch, operation):
    from types import SimpleNamespace

    from agno.db.sqlite import SqliteDb
    from agno.workflow.types import StepOutput
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import recalculation
    from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
    from smart_reporting.report_editor.service import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )

    editor, repository, context, markdown = await native_editor(tmp_path)
    editor.recalculation_database = SqliteDb(db_file=str(tmp_path / 'public-refresh.sqlite'))
    vault = object()
    editor.recalculation_runtime = SimpleNamespace(configuration_provider=SimpleNamespace(vault=vault))
    index = await editor.trace.require_index(context)
    async def preview(*args, **kwargs):
        return SimpleNamespace(parent_basis_id=index.report_basis_id, digest=lambda: 'a' * 64)
    service = SimpleNamespace(preview_policy_adoption=preview)
    editor.trace.report_basis_service = service
    editor.recalculation_runtime.report_basis_service = service
    async def parent(selected_editor, selected_context, *, vault):
        assert selected_editor is editor and selected_context == context
        assert vault is editor.recalculation_runtime.configuration_provider.vault
        return SimpleNamespace(basis_id=index.report_basis_id, report_revision='initial')
    monkeypatch.setattr(recalculation, 'resolve_refresh_parent', parent)
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def execute(selected_editor, selected_context, task_id, *, runtime):
        calls.append(task_id)
        entered.set()
        await finish.wait()
        task = await recalculation.read_task_by_id(editor, context, task_id)
        return task, StepOutput(content={'fixture': 'dispatch-contract-only'})
    executor = 'run_policy_adoption_request' if operation == 'adopt_policy' else 'run_refresh_request'
    monkeypatch.setattr(recalculation, executor, execute)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/recalculations'
    payload = {'requestId': 'public-refresh', 'parentRevision': context.revision,
        'expectedSha256': hashlib.sha256(markdown.encode()).hexdigest(), 'operation': operation}
    if operation == 'adopt_policy':
        payload['confirmation'] = {'requestId': payload['requestId'],
            'targetPolicyVersion': {'policyId': 'budget', 'revision': 2}, 'previewHash': 'a' * 64,
            'questionChoices': [{'questionId': 'q-budget', 'metricVersion': {'metricId': 'budget', 'revision': 2},
                'reason': '逐题确认采用新口径'}]}
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
            await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
            sources = await client.get(base.replace('/recalculations', '/sources'))
            assert sources.json()['dataRefresh'] == {'available': True, 'parentRevision': context.revision}
            assert (await client.post(base, json=payload)).status_code == 403
            assert not repository.state.payload.get('reportEditorRecalculations')
            headers = {'origin': 'http://reports.test',
                'x-csrf-token': grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
            response = await client.post(base, json=payload, headers=headers)
            assert response.status_code == 202
            result = response.json()
            assert result['status'] == 'pending' and result['execution']['runId']
            assert response.headers['cache-control'] == 'no-store'
            await asyncio.wait_for(entered.wait(), timeout=5)
            repeated = await client.post(base, json=payload, headers=headers)
            assert repeated.status_code == 202
            assert repeated.json()['execution']['runId'] == result['execution']['runId']
            assert calls == [result['taskId']]
            readback = await client.get(base + '/' + result['taskId'])
            assert readback.json()['execution']['runId'] == result['execution']['runId']
            conflict = await client.post(base, json={**payload, 'expectedSha256': '0' * 64}, headers=headers)
            assert conflict.status_code == 409
            if operation == 'adopt_policy':
                missing_confirmation = {key: value for key, value in payload.items() if key != 'confirmation'}
                assert (await client.post(base, json=missing_confirmation, headers=headers)).status_code == 422
                stale = {**payload, 'requestId': 'stale-preview', 'confirmation': {
                    **payload['confirmation'], 'requestId': 'stale-preview', 'previewHash': 'b' * 64}}
                assert (await client.post(base, json=stale, headers=headers)).status_code == 409
                assert await recalculation.read_task(editor, context, 'stale-preview') is None
                from smart_reporting.management.models import ManagementError
                async def retired(*args, **kwargs):
                    raise ManagementError('policy_retired', '目标口径已退役。', status=409)
                service.preview_policy_adoption = retired
                retired_request = {**payload, 'requestId': 'retired-policy', 'confirmation': {
                    **payload['confirmation'], 'requestId': 'retired-policy'}}
                rejected = await client.post(base, json=retired_request, headers=headers)
                assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'policy_retired'
                assert await recalculation.read_task(editor, context, 'retired-policy') is None
    finally:
        finish.set()
        if calls:
            for _ in range(100):
                run = await recalculation.read_recalculation_run(editor, context, calls[0], database=editor.recalculation_database)
                if str(getattr(run.status, 'value', run.status)).lower() == 'completed':
                    break
                await asyncio.sleep(0.02)


@pytest.mark.anyio
@pytest.mark.parametrize('backend', ['sqlite', pytest.param('postgres', marks=pytest.mark.integration)])
async def test_native_refresh_background_reuses_registered_run_and_survives_dispatch_return(tmp_path, monkeypatch, backend):
    from agno.db.sqlite import SqliteDb
    from agno.workflow.types import StepOutput

    from smart_reporting.report_editor import recalculation
    from smart_reporting.report_editor.recalculation import (
        RecalculationRequest,
        register_refresh_request,
    )

    editor, _, context, markdown = await native_editor(tmp_path)
    request = RecalculationRequest(requestId='background-refresh', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await register_refresh_request(editor, context, request, parent_report_revision='initial')
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    async def execute(selected_editor, selected_context, task_id, *, runtime):
        assert selected_editor is editor and selected_context == context and task_id == task.task_id
        from smart_reporting.report_editor.trace_retention import source_lifecycle_lock
        async with source_lifecycle_lock(editor, context, exclusive=True):
            calls.append(task_id)
            entered.set()
            await finish.wait()
        return task, StepOutput(content={'fixture': 'background-only-contract'})
    monkeypatch.setattr(recalculation, 'run_refresh_request', execute)
    agent_database = None
    if backend == 'postgres':
        import os

        from smart_reporting.runtime.database import create_agent_database
        url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
        if not url:
            pytest.skip('需要隔离PostgreSQL测试数据库')
        agent_database = create_agent_database(url)
        database = agent_database.async_db
    else:
        database = SqliteDb(db_file=str(tmp_path / 'refresh-background.sqlite'))
    editor.recalculation_database = database
    from types import SimpleNamespace
    editor.recalculation_runtime = SimpleNamespace(configuration_provider=SimpleNamespace(vault=object()))
    try:
        assert await recalculation.read_recalculation_run(editor, context, task.task_id, database=database) is None
        assert calls == []
        before_dispatch = await editor.recalculation_task_status(context, task.task_id)
        assert before_dispatch['execution'] == {'runId': None, 'status': 'not_dispatched', 'issueCodes': []}
        from agno.workflow import Workflow
        native_arun = Workflow.arun
        async def dispatch_response_lost(workflow, *args, **kwargs):
            await native_arun(workflow, *args, **kwargs)
            raise OSError('native dispatch response lost after durable registration')
        monkeypatch.setattr(Workflow, 'arun', dispatch_response_lost)
        with pytest.raises(OSError, match='dispatch response lost'):
            await recalculation.dispatch_recalculation_request(editor, context, task.task_id,
                runtime=object(), database=database)
        monkeypatch.setattr(Workflow, 'arun', native_arun)
        first = await recalculation.read_recalculation_run(editor, context, task.task_id, database=database)
        await asyncio.wait_for(entered.wait(), timeout=5)
        from agno.run import RunStatus
        assert first.status in {RunStatus.pending, RunStatus.running}
        repeated = await asyncio.wait_for(recalculation.dispatch_recalculation_request(
            editor, context, task.task_id, runtime=object(), database=database), timeout=1)
        assert repeated.run_id == first.run_id
        polled = await asyncio.wait_for(recalculation.read_recalculation_run(
            editor, context, task.task_id, database=database), timeout=1)
        assert polled.run_id == first.run_id
        status = await asyncio.wait_for(editor.recalculation_task_status(context, task.task_id), timeout=1)
        assert status['execution']['runId'] == first.run_id
        assert status['execution']['status'] in {'pending', 'running'}
        repeated_request = await asyncio.wait_for(editor.start_recalculation(context, request), timeout=1)
        assert repeated_request['taskId'] == task.task_id
        assert repeated_request['execution']['runId'] == first.run_id
        with pytest.raises(ReportingError, match='report_editor_conflict'):
            await editor.start_recalculation(context, request.model_copy(update={'expected_sha256': '0' * 64}))
        assert calls == [task.task_id]
        finish.set()
        for _ in range(100):
            recovered = await recalculation.read_recalculation_run(editor, context, task.task_id, database=database)
            if recovered.status == RunStatus.completed:
                break
            await asyncio.sleep(0.02)
        assert recovered.status == RunStatus.completed
        assert recovered.run_id == first.run_id and calls == [task.task_id]
        recovered_task = await editor.recalculation_status(context, request.request_id)
        assert recovered_task['status'] == 'pending'
        assert recovered_task['execution']['status'] == 'completed'
        assert recovered_task['execution']['issueCodes'] == ['refresh_completion_record_unavailable']
        workflow = Workflow(id='report-editor-refresh', db=database)
        session = await workflow.aget_session(session_id='report-editor-' + task.task_id,
            user_id=context.scope['userId'])
        run = session.runs[0]
        for native_status, expected_status in [('ERROR', 'error'), ('CANCELLED', 'cancelled'),
                ('PAUSED', 'paused'), ('unexpected-provider-status', 'unknown')]:
            run.status = native_status
            if agent_database:
                await database.upsert_run(run, session_id=session.session_id)
            else:
                database.upsert_run(run, session_id=session.session_id)
            selected = await editor.recalculation_task_status(context, task.task_id)
            assert selected['status'] == 'pending'
            assert selected['execution']['status'] == expected_status
            assert selected['execution']['issueCodes'] == ['refresh_execution_' + expected_status]
            repeated = await editor.start_recalculation(context, request)
            assert repeated['execution']['runId'] == first.run_id and calls == [task.task_id]
        run.status = 'COMPLETED'
        async def unavailable_run(*args, **kwargs):
            raise OSError('native run storage unavailable')
        with monkeypatch.context() as unavailable:
            unavailable.setattr(recalculation, 'read_recalculation_run', unavailable_run)
            unreadable = await editor.recalculation_task_status(context, task.task_id)
            assert unreadable['status'] == 'pending'
            assert unreadable['execution'] == {'runId': None, 'status': 'unavailable',
                'issueCodes': ['refresh_status_unavailable']}
        for field, forged in [('input', {**run.input, 'inputHash': 'f' * 64}),
                ('workflow_id', 'foreign-workflow'), ('session_id', 'foreign-session'),
                ('user_id', 'foreign-user')]:
            original = getattr(run, field)
            setattr(run, field, forged)
            if agent_database:
                await database.upsert_run(run, session_id=session.session_id)
            else:
                database.upsert_run(run, session_id=session.session_id)
            with pytest.raises(ReportingError, match='report_editor_scope_mismatch'):
                await recalculation.read_recalculation_run(editor, context, task.task_id, database=database)
            setattr(run, field, original)
    finally:
        finish.set()
        if agent_database:
            await agent_database.async_engine.dispose()
            agent_database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('tamper', [None, 'input_hash', 'context', 'user', 'session', 'missing_context', 'executor_unknown'])
async def test_rebuilt_refresh_workflow_restores_only_registered_request(tmp_path, monkeypatch, tamper):
    from agno.db.sqlite import SqliteDb
    from agno.run import RunContext
    from agno.workflow.types import StepInput, StepOutput

    from smart_reporting.report_editor import recalculation

    editor, repository, context, markdown = await native_editor(tmp_path)
    request = recalculation.RecalculationRequest(requestId='rebuilt-refresh', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await recalculation.register_refresh_request(editor, context, request, parent_report_revision='initial')
    inputs = recalculation.recalculation_run_input(context, task)
    selected = RunContext(run_id='native-run', session_id='report-editor-' + task.task_id,
        user_id=context.scope['userId'])
    if tamper == 'input_hash':
        inputs['inputHash'] = '0' * 64
    elif tamper == 'context':
        inputs['contextSha256'] = '0' * 64
    elif tamper == 'user':
        selected.user_id = 'foreign-user'
    elif tamper == 'session':
        selected.session_id = 'foreign-session'
    elif tamper == 'missing_context':
        repository.state.payload['reportEditorContexts'] = {}
    calls = []
    async def execute(restored_editor, restored_context, restored_task, *, runtime):
        assert restored_context == context and restored_task == task.task_id
        calls.append(restored_task)
        if tamper == 'executor_unknown':
            raise OSError('交付执行结果未知')
        return task, StepOutput(content={})
    monkeypatch.setattr(recalculation, 'run_refresh_request', execute)
    rebuilt_editor = ReportEditorService(state_repository=repository, workspace_registry=editor.workspace_registry,
        workspace=editor.workspace)
    workflow = recalculation.create_refresh_workflow(rebuilt_editor, runtime=object(),
        database=SqliteDb(db_file=str(tmp_path / 'rebuilt.sqlite')))
    if tamper == 'executor_unknown':
        await workflow.arun(input=inputs, session_id=selected.session_id, user_id=selected.user_id)
        assert calls == [task.task_id]
        assert (await recalculation.read_task(editor, context, request.request_id)).status == 'pending'
    elif tamper:
        with pytest.raises(ReportingError, match='report_editor_scope_mismatch'):
            await workflow.steps[0].executor(StepInput(input=inputs), run_context=selected)
        assert calls == []
    else:
        output = await workflow.steps[0].executor(StepInput(input=inputs), run_context=selected)
        assert output.content == task.model_dump(mode='json', by_alias=True)
        assert calls == [task.task_id]


@pytest.mark.anyio
@pytest.mark.integration
async def test_native_shutdown_persists_cancelled_refresh_and_never_redispatches(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    from agno.os.app import _drain_cancel_persist_tasks
    from agno.run import RunStatus

    from smart_reporting.report_editor import recalculation
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, _, context, markdown = await native_editor(tmp_path)
    request = recalculation.RecalculationRequest(requestId='shutdown-refresh', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await recalculation.register_refresh_request(editor, context, request, parent_report_revision='initial')
    database = create_agent_database(url)
    entered, cancelled = asyncio.Event(), asyncio.Event()
    calls = []
    async def execute(*args, **kwargs):
        from smart_reporting.report_editor.trace_retention import source_lifecycle_lock
        async with source_lifecycle_lock(editor, context, exclusive=True):
            calls.append(task.task_id)
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
    monkeypatch.setattr(recalculation, 'run_refresh_request', execute)
    editor.recalculation_database = database.async_db
    editor.recalculation_runtime = SimpleNamespace(configuration_provider=SimpleNamespace(vault=object()))
    try:
        started = await editor.start_recalculation(context, request)
        await asyncio.wait_for(entered.wait(), timeout=5)
        await _drain_cancel_persist_tasks(timeout=0)
        assert cancelled.is_set()
        run = await recalculation.read_recalculation_run(editor, context, task.task_id, database=database.async_db)
        assert run.status == RunStatus.cancelled
        assert run.run_id == started['execution']['runId']
        restarted_database = create_agent_database(url)
        try:
            restarted = ReportEditorService(state_repository=editor.state_repository,
                workspace_registry=editor.workspace_registry, workspace=editor.workspace,
                recalculation_database=restarted_database.async_db, recalculation_runtime=editor.recalculation_runtime)
            readback = await restarted.recalculation_status(context, request.request_id)
            assert readback['status'] == 'pending'
            assert readback['execution']['status'] == 'cancelled'
            assert readback['execution']['issueCodes'] == ['refresh_execution_cancelled']
            repeated = await restarted.start_recalculation(context, request)
            assert repeated['execution']['runId'] == run.run_id
            assert calls == [task.task_id]
        finally:
            await restarted_database.async_engine.dispose()
            restarted_database.sync_engine.dispose()
    finally:
        await _drain_cancel_persist_tasks(timeout=0)
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize('interrupt', [False, True])
@pytest.mark.parametrize('operation', ['refresh_data', 'adopt_policy'])
async def test_native_queue_acceptance_survives_database_and_workflow_rebuild(tmp_path, monkeypatch, interrupt, operation):
    import os
    from types import SimpleNamespace

    from agno.os.job_queue import QueueWorker, resolve_queue_store
    from agno.run import RunStatus
    from agno.workflow.types import StepOutput
    from sqlalchemy import delete

    from smart_reporting.report_editor import recalculation
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    values = dict(requestId=f'queued-{operation}-{interrupt}', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation=operation)
    if operation == 'adopt_policy':
        index = await editor.trace.require_index(context)
        async def preview(*args, **kwargs):
            return SimpleNamespace(parent_basis_id=index.report_basis_id, digest=lambda: 'a' * 64)
        editor.trace.report_basis_service = SimpleNamespace(preview_policy_adoption=preview)
        request = recalculation.PolicyAdoptionRequest(**values, confirmation={
            'requestId': values['requestId'], 'targetPolicyVersion': {'policyId': 'budget', 'revision': 2},
            'previewHash': 'a' * 64, 'questionChoices': [{'questionId': 'q-budget',
                'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '采用新口径'}]})
        factory, executor = recalculation.create_policy_adoption_workflow, 'run_policy_adoption_request'
        chosen_component = 'report-editor-policy-adoption'
    else:
        request = recalculation.RecalculationRequest(**values)
        factory, executor = recalculation.create_refresh_workflow, 'run_refresh_request'
        chosen_component = 'report-editor-refresh'
    first_db = create_agent_database(url)
    repository = ReportingStateRepository(first_db.async_db)
    await repository.initialize()
    async with first_db.async_engine.begin() as connection:
        for table in (repository.command_receipts, repository.states, repository.runs):
            await connection.execute(delete(table).where(table.c.report_run_id == context.workflow_run_id))
    await repository.create(memory.state)
    editor.state_repository = repository
    task = (await recalculation.register_policy_adoption_request(editor, context, request) if operation == 'adopt_policy'
        else await recalculation.register_refresh_request(editor, context, request, parent_report_revision='initial'))
    config = recalculation.recalculation_queue_config()
    config.poll_interval = 0.05
    store = resolve_queue_store(config, first_db.async_db)
    editor.recalculation_durable = True
    editor.recalculation_queue_worker = SimpleNamespace(config=config, store=store)
    accepted = await recalculation.dispatch_recalculation_request(editor, context, task.task_id,
        runtime=object(), database=first_db.async_db)
    run_id = accepted.run_id
    assert run_id == recalculation.recalculation_queue_run_id(task)
    await first_db.async_engine.dispose()
    first_db.sync_engine.dispose()
    second_db = create_agent_database(url)
    restarted = ReportEditorService(state_repository=ReportingStateRepository(second_db.async_db),
        workspace_registry=editor.workspace_registry, workspace=editor.workspace, recalculation_durable=True,
        recalculation_database=second_db.async_db)
    calls = []
    entered = asyncio.Event()
    async def execute(selected_editor, selected_context, selected_id, *, runtime):
        assert selected_editor is restarted and selected_context == context
        calls.append(selected_id)
        entered.set()
        if interrupt:
            await asyncio.Event().wait()
        loaded = await recalculation.read_task_by_id(restarted, selected_context, selected_id)
        return loaded, StepOutput(content={})
    monkeypatch.setattr(recalculation, executor, execute)
    rebuilt = factory(restarted, runtime=object(), database=second_db.async_db)
    worker = QueueWorker(store=resolve_queue_store(config, second_db.async_db), config=config,
        stop_timeout=0,
        resolve_component=lambda kind, component_id: rebuilt if (kind, component_id) == (
            'workflow', chosen_component) else None)
    try:
        await worker.start()
        if interrupt:
            await asyncio.wait_for(entered.wait(), timeout=10)
            await worker.stop()
            failed = await recalculation.read_recalculation_run(restarted, context, task.task_id, database=second_db.async_db)
            assert failed.run_id == run_id and failed.status == RunStatus.error
            repeated = await recalculation.dispatch_recalculation_request(restarted, context, task.task_id,
                runtime=object(), database=second_db.async_db)
            assert repeated.run_id == run_id and calls == [task.task_id]
            response = await recalculation.task_response(restarted, context, task)
            prefix = 'policy_adoption' if operation == 'adopt_policy' else 'refresh'
            assert response['execution'] == {'runId': run_id, 'status': 'error',
                'issueCodes': [prefix + '_execution_error']}
            return
        async def finished():
            while True:
                run = await recalculation.read_recalculation_run(restarted, context, task.task_id, database=second_db.async_db)
                assert run.status not in {RunStatus.error, RunStatus.cancelled}
                if run.status == RunStatus.completed:
                    return run
                await asyncio.sleep(0.05)
        run = await asyncio.wait_for(finished(), timeout=10)
        assert run.run_id == run_id and calls == [task.task_id]
        assert run.content == task.model_dump(mode='json', by_alias=True)
        response = await recalculation.task_response(restarted, context, task)
        prefix = 'policy_adoption' if operation == 'adopt_policy' else 'refresh'
        assert response['execution'] == {'runId': run_id, 'status': 'completed',
            'issueCodes': [prefix + '_completion_record_unavailable']}
    finally:
        await worker.stop()
        await second_db.async_engine.dispose()
        second_db.sync_engine.dispose()

@pytest.mark.anyio
async def test_durable_refresh_recovers_accepted_ticket_without_run_row(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    from agno.os.job_queue import resolve_queue_store

    from smart_reporting.report_editor import recalculation
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, _, context, markdown = await native_editor(tmp_path)
    database = create_agent_database(url)
    editor.recalculation_durable = True
    config = recalculation.recalculation_queue_config()
    editor.recalculation_queue_worker = SimpleNamespace(config=config,
        store=resolve_queue_store(config, database.async_db))
    request = recalculation.RecalculationRequest(requestId='durable-ticket', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await recalculation.register_refresh_request(editor, context, request, parent_report_revision='initial')
    async def lost_prepare(*args, **kwargs):
        raise ConnectionError('accepted response lost')
    monkeypatch.setattr('agno.os.job_queue.aprepare_accepted_or_abort', lost_prepare)
    try:
        with pytest.raises(ConnectionError):
            await recalculation.dispatch_recalculation_request(editor, context, task.task_id,
                runtime=object(), database=database.async_db)
        # 服务重建后即使没有worker引用，GET也应读回已提交票据，不能另建运行。
        editor.recalculation_queue_worker = None
        run = await recalculation.read_recalculation_run(editor, context, task.task_id, database=database.async_db)
        assert run is not None and str(run.status.value).lower() == 'pending'
        queued = await recalculation.read_recalculation_run(editor, context, task.task_id,
            database=database.async_db, queue_only=True)
        assert queued.run_id == run.run_id and str(queued.status.value).lower() == 'pending'
        from agno.workflow import Workflow

        async def stale_session(*_args, **_kwargs):
            return SimpleNamespace(session_id='report-editor-' + task.task_id,
                workflow_id='report-editor-refresh', runs=[SimpleNamespace(
                    input=recalculation.recalculation_run_input(context, task),
                    workflow_id='report-editor-refresh', session_id='report-editor-' + task.task_id,
                    user_id=context.scope['userId'], status='error')])
        with monkeypatch.context() as patch:
            patch.setattr(Workflow, 'aget_session', stale_session)
            with pytest.raises(ReportingError, match='report_editor_conflict'):
                await recalculation.require_recalculation_ended(editor, context, task.task_id, database=database.async_db)
        repeated = await recalculation.dispatch_recalculation_request(editor, context, task.task_id,
            runtime=object(), database=database.async_db)
        assert repeated.run_id == run.run_id
        editor.recalculation_queue_worker = SimpleNamespace(config=config,
            store=resolve_queue_store(config, database.async_db))
        job = await editor.recalculation_queue_worker.store.get_job(run.run_id)
        job['payload']['input']['inputHash'] = '0' * 64
        async def forged_ticket(*args, **kwargs):
            return job
        monkeypatch.setattr(editor.recalculation_queue_worker.store, 'get_job', forged_ticket)
        with pytest.raises(ReportingError, match='票据'):
            await recalculation.read_recalculation_run(editor, context, task.task_id, database=database.async_db)
        with pytest.raises(ReportingError, match='票据'):
            await recalculation.read_recalculation_run(editor, context, task.task_id,
                database=database.async_db, queue_only=True)
    finally:
        # 本例刻意保留未执行票据验证未知响应；结束时仅取消自己的票据，避免后续worker领取。
        await resolve_queue_store(config, database.async_db).cancel_job(recalculation.recalculation_queue_run_id(task))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


def _hold_native_refresh_worker(database_url, signal_path):
    """独立进程中的受控执行端口；只标记已进入，不查询业务库。"""
    from pathlib import Path

    from agno.os.job_queue import QueueWorker, resolve_queue_store
    from agno.workflow import Step, Workflow

    from smart_reporting.report_editor.recalculation import recalculation_queue_config
    from smart_reporting.runtime.database import create_agent_database

    async def serve():
        database = create_agent_database(database_url)
        config = recalculation_queue_config()
        config.lock_grace_seconds = 1
        config.poll_interval = 0.05
        async def hold(step_input):
            Path(signal_path).write_text(step_input.input['taskId'])
            await asyncio.Event().wait()
        workflow = Workflow(id='report-editor-refresh', db=database.async_db,
            steps=[Step(name='controlled-refresh', executor=hold)])
        worker = QueueWorker(store=resolve_queue_store(config, database.async_db), config=config,
            stop_timeout=0, resolve_component=lambda kind, component_id: workflow if (
                kind, component_id) == ('workflow', 'report-editor-refresh') else None)
        await worker.start()
        await asyncio.Event().wait()
    asyncio.run(serve())


@pytest.mark.anyio
async def test_durable_refresh_sigkill_is_swept_without_second_execution(tmp_path, monkeypatch):
    import multiprocessing
    import os
    import signal
    from types import SimpleNamespace

    from agno.os.job_queue import QueueWorker, resolve_queue_store
    from agno.run import RunStatus

    from smart_reporting.report_editor import recalculation
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    database = create_agent_database(url)
    repository = ReportingStateRepository(database.async_db)
    await repository.initialize()
    await repository.create(memory.state)
    editor.state_repository = repository
    editor.recalculation_database = database.async_db
    editor.recalculation_durable = True
    config = recalculation.recalculation_queue_config()
    config.lock_grace_seconds = 1
    config.poll_interval = 0.05
    store = resolve_queue_store(config, database.async_db)
    editor.recalculation_queue_worker = SimpleNamespace(config=config, store=store)
    request = recalculation.RecalculationRequest(requestId='sigkill-refresh', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='refresh_data')
    task = await recalculation.register_refresh_request(editor, context, request, parent_report_revision='initial')
    accepted = await recalculation.dispatch_recalculation_request(editor, context, task.task_id,
        runtime=object(), database=database.async_db)
    marker = tmp_path / 'worker-entered.txt'
    process = multiprocessing.get_context('spawn').Process(target=_hold_native_refresh_worker,
        args=(url, str(marker)))
    process.start()
    recovery = None
    try:
        async def wait_for_started():
            while not marker.exists():
                assert process.is_alive(), f'原生worker提前退出: {process.exitcode}'
                await asyncio.sleep(0.05)
        await asyncio.wait_for(wait_for_started(), timeout=30)
        assert marker.read_text() == task.task_id
        running = await store.get_job(accepted.run_id)
        assert running['status'] == 'running' and running['attempt'] == 1
        process.kill()
        await asyncio.to_thread(process.join, 5)
        assert process.exitcode == -signal.SIGKILL
        # 真正硬退出后未执行原生stop；票据仍running，由另一个worker按实际租约回收。
        abandoned = await store.get_job(accepted.run_id)
        assert abandoned['status'] == 'running' and abandoned['attempt'] == 1
        executions_after_restart = []
        async def must_not_execute(*args, **kwargs):
            executions_after_restart.append(True)
            pytest.fail('最多一次的中断刷新不得再次进入取数/交付执行器')
        monkeypatch.setattr(recalculation, 'run_refresh_request', must_not_execute)
        recovery = QueueWorker(store=store, config=config, stop_timeout=0,
            resolve_component=lambda kind, component_id: recalculation.create_refresh_workflow(editor,
                runtime=object(), database=database.async_db) if (kind, component_id) == (
                    'workflow', 'report-editor-refresh') else None)
        editor.recalculation_queue_worker = recovery
        await recovery.start()
        async def wait_for_failure():
            while True:
                run = await recalculation.read_recalculation_run(editor, context, task.task_id, database=database.async_db)
                if run.status == RunStatus.error:
                    return run
                await asyncio.sleep(0.05)
        failed = await asyncio.wait_for(wait_for_failure(), timeout=15)
        assert failed.run_id == accepted.run_id
        async def wait_for_ticket():
            while True:
                job = await store.get_job(accepted.run_id)
                if job['status'] == 'failed':
                    return job
                await asyncio.sleep(0.05)
        settled = await asyncio.wait_for(wait_for_ticket(), timeout=5)
        assert settled['attempt'] == 1
        repeated = await recalculation.dispatch_recalculation_request(editor, context, task.task_id,
            runtime=object(), database=database.async_db)
        assert repeated.run_id == accepted.run_id and repeated.status == RunStatus.error
        status = await recalculation.task_response(editor, context, task)
        assert status['status'] == 'pending'
        assert status['execution']['issueCodes'] == ['refresh_execution_error']
        assert marker.read_text() == task.task_id
        assert executions_after_restart == []
    finally:
        if process.is_alive():
            process.kill()
            await asyncio.to_thread(process.join, 5)
        if recovery is not None:
            await recovery.stop()
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
async def test_policy_adoption_preview_http_uses_editor_identity_and_never_dispatches(tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.management.models import ManagementError
    from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router
    from smart_reporting.report_editor.service import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )

    editor, repository, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    calls = []
    mode = None
    class BasisService:
        async def policy_adoption_options(self, run_id, scope, **options):
            assert run_id == context.workflow_run_id
            assert (scope.database, scope.company_id) == (context.scope['database'], context.scope['companyId'])
            assert options == {'user_id': context.scope['userId'], 'thread_id': context.scope['callerThreadId'],
                'limit': 50, 'after': 'previous-policy'}
            return {'parentBasisId': index.report_basis_id, 'items': [{
                'policyVersion': {'policyId': 'monthly-budget', 'revision': 2}, 'name': '月度预算'}], 'nextCursor': None}
        async def preview_policy_adoption(self, run_id, scope, **options):
            calls.append((run_id, scope, options))
            if mode == 'retired':
                raise ManagementError('management_semantic_asset_retired', '所选精确版本已退役。', 409)
            return SimpleNamespace(parent_basis_id='foreign-basis' if mode == 'foreign' else index.report_basis_id,
                model_dump=lambda **kwargs: {'parentBasisId': index.report_basis_id,
                    'calculationStatus': 'not_recalculated', 'requiresQuestionConfirmation': True},
                digest=lambda: 'a' * 64)
    editor.trace.report_basis_service = BasisService()
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    url = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/policy-adoption-preview'
    payload = {'parentRevision': context.revision, 'expectedSha256': hashlib.sha256(markdown.encode()).hexdigest(),
        'policyVersion': {'policyId': 'monthly-budget', 'revision': 2}}
    before = repository.state.model_dump(mode='json')
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        options_url = url.replace('policy-adoption-preview', 'policy-adoption-options') + '?after=previous-policy'
        assert (await client.get(options_url)).status_code == 404
        await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
        options_result = await client.get(options_url)
        assert options_result.status_code == 200
        assert options_result.headers['cache-control'] == 'no-store'
        assert options_result.json()['items'][0]['policyVersion'] == payload['policyVersion']
        assert (await client.post(url, json=payload)).status_code == 403
        assert calls == []
        headers = {'origin': 'http://reports.test',
            'x-csrf-token': grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
        response = await client.post(url, json=payload, headers=headers)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['previewHash'] == 'a' * 64
        run_id, scope, options = calls[0]
        assert run_id == context.workflow_run_id
        assert (scope.database, scope.company_id) == (context.scope['database'], context.scope['companyId'])
        assert options == {'user_id': context.scope['userId'], 'thread_id': context.scope['callerThreadId'],
            'policy_version': payload['policyVersion']}
        assert (await client.post(url, json={**payload, 'expectedSha256': '0' * 64}, headers=headers)).status_code == 409
        assert (await client.post(url, json={**payload, 'parentRevision': context.revision + 1}, headers=headers)).status_code == 409
        assert (await client.post(url, json={**payload, 'basisId': 'forged'}, headers=headers)).status_code == 422
        assert len(calls) == 1
        mode = 'foreign'
        rejected = await client.post(url, json=payload, headers=headers)
        assert rejected.json()['detail']['code'] == 'report_editor_scope_mismatch'
        mode = 'retired'
        rejected = await client.post(url, json=payload, headers=headers)
        assert rejected.status_code == 409 and rejected.json()['detail']['code'] == 'management_semantic_asset_retired'
        editor.trace.report_basis_service = None
        assert (await client.post(url, json=payload, headers=headers)).status_code == 503
    assert repository.state.model_dump(mode='json') == before


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize('case', ['normal', 'draft', 'parent', 'preview', 'basis', 'lost_response', 'concurrent'])
async def test_policy_adoption_request_freezes_confirmation_and_recovers_without_resubmission(tmp_path, monkeypatch, case):
    import os
    from types import SimpleNamespace

    from sqlalchemy import delete

    from smart_reporting.report_editor.recalculation import (
        PolicyAdoptionRequest,
        read_task,
        register_policy_adoption_request,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    database = create_agent_database(url)
    repository = ReportingStateRepository(database.async_db)
    calls = []
    async def preview(run_id, scope, **options):
        calls.append((run_id, scope, options))
        return SimpleNamespace(parent_basis_id='foreign' if case == 'basis' else index.report_basis_id,
            digest=lambda: 'b' * 64 if case == 'preview' else 'a' * 64)
    editor.trace.report_basis_service = SimpleNamespace(preview_policy_adoption=preview)
    request = PolicyAdoptionRequest(requestId='adopt-confirmed', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), operation='adopt_policy',
        confirmation={'requestId': 'adopt-confirmed', 'targetPolicyVersion': {'policyId': 'budget-policy', 'revision': 2},
            'previewHash': 'a' * 64, 'questionChoices': [
                {'questionId': 'q-budget', 'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '采用明确的新版本'},
                {'questionId': 'q-rate', 'metricVersion': None, 'reason': '缺少实际发生额，保持未回答'}]})
    async def cleanup():
        async with database.async_engine.begin() as connection:
            for table in (repository.command_receipts, repository.states, repository.runs):
                await connection.execute(delete(table).where(table.c.report_run_id == context.workflow_run_id))
    try:
        await repository.initialize()
        await cleanup()
        await repository.create(memory.state)
        editor.state_repository = repository
        if case in {'draft', 'parent'}:
            request = request.model_copy(update={'expected_sha256': '0' * 64} if case == 'draft' else {
                'parent_revision': context.revision + 1})
        if case in {'draft', 'parent', 'preview', 'basis'}:
            with pytest.raises(ReportingError):
                await register_policy_adoption_request(editor, context, request)
            assert not (await repository.get(context.workflow_run_id)).payload.get('reportEditorRecalculations')
            return
        apply = repository.apply
        injected = []
        if case == 'lost_response':
            async def lose_response(run, command, **options):
                result = await apply(run, command, **options)
                if command.name == 'record_report_editor_recalculation' and not injected:
                    injected.append(True)
                    raise OSError('confirmation request committed but response lost')
                return result
            monkeypatch.setattr(repository, 'apply', lose_response)
            with pytest.raises(OSError, match='committed but response lost'):
                await register_policy_adoption_request(editor, context, request)
            monkeypatch.setattr(repository, 'apply', apply)
        elif case == 'concurrent':
            other = ReportEditorService(state_repository=ReportingStateRepository(database.async_db),
                workspace_registry=editor.workspace_registry, workspace=editor.workspace)
            other.trace.report_basis_service = editor.trace.report_basis_service
            first, second = await asyncio.gather(register_policy_adoption_request(editor, context, request),
                register_policy_adoption_request(other, context, request))
            assert first == second
        else:
            await register_policy_adoption_request(editor, context, request)
        frozen = await read_task(editor, context, request.request_id)
        assert frozen.status == 'pending' and frozen.result is None and frozen.refresh_binding is None
        assert frozen.request == request and frozen.basis_id == index.report_basis_id
        # 已登记请求读回不依赖正文或预检仍可用，也不能再次登记依据、发SQL或派发。
        rebuilt = ReportEditorService(state_repository=ReportingStateRepository(database.async_db),
            workspace_registry=editor.workspace_registry, workspace=editor.workspace)
        await editor.workspace.awrite_bytes(context.scope['threadId'], context.markdown_path, b'changed', overwrite=True)
        assert await register_policy_adoption_request(rebuilt, context, request) == frozen
        assert await read_task(rebuilt, context, request.request_id) == frozen
        changed = request.model_copy(update={'confirmation': request.confirmation.model_copy(update={
            'preview_hash': 'c' * 64})})
        with pytest.raises(ReportingError, match='report_editor_conflict'):
            await register_policy_adoption_request(rebuilt, context, changed)
        assert len(calls) == 1
        run_id, scope, options = calls[0]
        assert run_id == context.workflow_run_id
        assert (scope.database, scope.company_id) == (context.scope['database'], context.scope['companyId'])
        assert options == {'user_id': context.scope['userId'], 'thread_id': context.scope['callerThreadId'],
            'policy_version': {'policyId': 'budget-policy', 'revision': 2}}
    finally:
        await cleanup()
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.parametrize('fault', ['request_id', 'duplicate_question', 'operation', 'extra_field'])
def test_policy_adoption_request_requires_explicit_unique_confirmation(fault):
    from pydantic import ValidationError

    from smart_reporting.report_editor.recalculation import PolicyAdoptionRequest

    payload = {'requestId': 'confirm-1', 'parentRevision': 2, 'expectedSha256': 'a' * 64,
        'operation': 'adopt_policy', 'confirmation': {'requestId': 'confirm-1',
            'targetPolicyVersion': {'policyId': 'budget', 'revision': 2}, 'previewHash': 'b' * 64,
            'questionChoices': [{'questionId': 'q-budget', 'metricVersion': None, 'reason': '未选择指标'}]}}
    if fault == 'request_id':
        payload['confirmation']['requestId'] = 'other-confirmation'
    elif fault == 'duplicate_question':
        payload['confirmation']['questionChoices'] *= 2
    elif fault == 'operation':
        payload['operation'] = 'verify_snapshot'
    else:
        payload['basisId'] = 'foreign-basis'
    with pytest.raises(ValidationError):
        PolicyAdoptionRequest.model_validate(payload)


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize('fault', ['none', 'completion_response', 'changed_pdf', 'native_workflow', 'pending_delivery'])
async def test_policy_adoption_task_records_verified_new_execution_and_preserves_other_outputs(tmp_path, monkeypatch, fault):
    import os
    from types import SimpleNamespace

    from agno.workflow.types import StepOutput
    from sqlalchemy import delete

    from smart_reporting.report_editor.recalculation import (
        PolicyAdoptionRequest,
        read_task,
        register_policy_adoption_request,
        run_policy_adoption_request,
    )
    from smart_reporting.reporting.workflow import policy_adoption, policy_adoption_analysis
    from smart_reporting.reporting.workflow.policy_adoption import (
        PolicyAdoptionExecution,
        _target_scope,
    )
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
    from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope
    from smart_reporting.runtime.database import create_agent_database
    from smart_reporting.tests.test_report_basis_persistence import build_identity

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    database = create_agent_database(url)
    repository = ReportingStateRepository(database.async_db)
    confirmations, generations, recoveries = [], [], []
    source_scope = resolve_reporting_workflow_scope(run_id=context.workflow_run_id,
        session_id=context.scope['sessionId'], user_id=context.scope['userId'], stored_scope=context.scope)
    target_scope = _target_scope(source_scope, 'new-policy-task-run')
    editor.workspace_registry.resolve(target_scope)
    root = f'报表/智能分析/{target_scope.run_id}/document-render/revision-3'
    content = {'reportId': target_scope.run_id, 'revision': 3, 'deliveryFormat': 'document',
        'validation': {'ok': False, 'issues': [{'code': 'document_validation_receipt_unavailable', 'message': '验收回执待核对'}]}}
    for label, output in (('pdf', 'pdf'), ('word', 'docx')):
        raw = ('new-policy-' + label).encode()
        path = f'{root}/report.{output}'
        await editor.workspace.awrite_bytes(target_scope.workspace_key, path, raw)
        content.update({f'{label}Path': path, f'{label}Size': len(raw), f'{label}Sha256': hashlib.sha256(raw).hexdigest()})
    async def preview(*args, **kwargs):
        return SimpleNamespace(parent_basis_id=index.report_basis_id, digest=lambda: 'a' * 64)
    async def confirm(run_id, scope, **options):
        confirmations.append(options['confirmation'])
        assert options['build_identity'] == build_identity()
        return SimpleNamespace(parent_basis_id=index.report_basis_id, basis_id='new-basis', target_run_id=target_scope.run_id)
    service = SimpleNamespace(preview_policy_adoption=preview, register_policy_adoption=confirm)
    editor.trace.report_basis_service = service
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.report_basis_service, runtime.report_build_identity = service, build_identity()
    runtime.workspace_service = editor.workspace
    request = PolicyAdoptionRequest(requestId='adopt-task', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), confirmation={
            'requestId': 'adopt-task', 'targetPolicyVersion': {'policyId': 'budget-policy', 'revision': 2},
            'previewHash': 'a' * 64, 'questionChoices': [{'questionId': 'q-budget',
                'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '明确选择新指标'}]})
    async def cleanup():
        async with database.async_engine.begin() as connection:
            for table in (repository.command_receipts, repository.states, repository.runs):
                await connection.execute(delete(table).where(table.c.report_run_id.in_(
                    (context.workflow_run_id, target_scope.run_id))))
    try:
        await repository.initialize()
        await cleanup()
        await repository.create(memory.state)
        editor.state_repository = repository
        task = await register_policy_adoption_request(editor, context, request)
        execution = PolicyAdoptionExecution(requestId=task.task_id,
            sourceScope=source_scope, scope=target_scope, parentBasisId=index.report_basis_id,
            basisId='new-basis', registrationSha256='b' * 64, outputRevision=3, requestedOutputs=['pdf', 'docx'])
        inspections = []
        from smart_reporting.reporting.workflow import policy_adoption_recovery

        async def inspect(_runtime, source_context, actual):
            assert actual == execution and source_context.run_id == context.workflow_run_id
            assert source_context.session_state['report_workflow_scope'] == context.scope
            inspections.append(actual.scope.run_id)
            return {'analysis': {'status': 'registered', 'identity': {
                'path': 'analysis/preparation.json', 'size': 8, 'sha256': 'a' * 64}},
                'document': {'status': 'awaiting_confirmation'}, 'stateVersion': 8}

        monkeypatch.setattr(policy_adoption_recovery, 'inspect_policy_adoption_preparation', inspect)
        editor.recalculation_runtime = runtime
        if fault == 'none':
            from dataclasses import replace
            from datetime import UTC, datetime

            from smart_reporting.report_editor.recalculation import (
                PolicyAdoptionDeliveryResult,
                record_task,
            )
            from smart_reporting.reporting.workflow.state import ReportingStateError

            foreign_execution = execution.model_copy(update={'source_scope': replace(source_scope, company_id='foreign-company')})
            forged = task.model_copy(update={'status': 'completed', 'checked_at': datetime.now(UTC),
                'result': PolicyAdoptionDeliveryResult(execution=foreign_execution, artifacts=[{
                    'path': content['wordPath'], 'size': content['wordSize'], 'sha256': content['wordSha256']}],
                    validationPassed=False, issueCodes=[])})
            with pytest.raises(ReportingStateError):
                await record_task(editor, context, forged)
        async def prepare(_runtime, source_context, *, request_id):
            assert request_id == task.task_id and source_context.run_id == context.workflow_run_id
            return execution
        async def generate(_runtime, source_context, actual):
            assert actual == execution and source_context.run_id == context.workflow_run_id
            generations.append(actual.scope.run_id)
            return StepOutput(content=dict(content))
        async def recover(source_context, actual):
            assert actual == execution
            recoveries.append(actual.scope.run_id)
            return StepOutput(content=dict(content))
        monkeypatch.setattr(policy_adoption, 'prepare_policy_adoption_execution', prepare)
        monkeypatch.setattr(policy_adoption_analysis, 'continue_policy_adoption_delivery', generate)
        monkeypatch.setattr(runtime, '_publish_revision_report', recover)
        if fault == 'pending_delivery':
            from smart_reporting.report_editor.recalculation import read_policy_adoption_delivery
            from smart_reporting.reporting.workflow.state import ReportingCommand, ReportingRunState

            with pytest.raises(ReportingError, match='report_editor_recalculation_unavailable'):
                await read_policy_adoption_delivery(editor, context, task.task_id, runtime=runtime)
            await repository.apply(context.workflow_run_id, ReportingCommand(name='reserve_report_editor_revision',
                commandId=target_scope.run_id, payload={'minimumRevision': context.revision,
                    'reservationKey': target_scope.run_id}), expected_version=(await repository.get(context.workflow_run_id)).state_version)
            await repository.create(ReportingRunState.initial(report_run_id=target_scope.run_id,
                external_run_id=target_scope.external_run_id, thread_id=target_scope.caller_thread_id,
                owner_user_id=target_scope.user_id, revision=execution.output_revision,
                payload={'reportPolicyAdoptionExecution': execution.model_dump(mode='json', by_alias=True)}))
            editor.state_repository = ReportingStateRepository(database.async_db)
            returned, output, restored = await read_policy_adoption_delivery(editor, context, task.task_id, runtime=runtime)
            assert returned == task and restored == execution and returned.status == 'pending'
            assert output.content['wordPath'] == content['wordPath']
            assert output.content['validation']['ok'] is False
            assert 'policy_adoption_completion_record_unavailable' in {
                item['code'] for item in output.content['validationIssues']}
            assert not confirmations and not generations and recoveries == [target_scope.run_id]
            assert await read_task(editor, context, request.request_id) == task
            before_inspection = (await editor.state_repository.get(context.workflow_run_id)).model_dump()
            inspected = await editor.recalculation_preparation(context, task.task_id)
            assert inspected['runId'] == execution.scope.run_id
            assert inspected['document']['status'] == 'awaiting_confirmation'
            from smart_reporting.report_editor import recalculation
            from smart_reporting.report_editor.policy_recovery import (
                recovery_run_id,
                recovery_run_input,
            )

            expected_recovery = recalculation.PreparationConfirmationRequest(kind='analysis', expectedStateVersion=8,
                identity=inspected['analysis']['identity'])
            assert inspected['analysis']['recoveryId'] == recovery_run_id(recovery_run_input(context, task, expected_recovery))
            assert (await editor.state_repository.get(context.workflow_run_id)).model_dump() == before_inspection
            assert inspections == [execution.scope.run_id]
            assert not confirmations and not generations and recoveries == [target_scope.run_id]
            from smart_reporting.report_editor import recalculation
            from smart_reporting.report_editor.recalculation import PreparationConfirmationRequest

            confirmation_calls = []
            async def confirmed(_runtime, source_context, actual, **values):
                assert actual == execution and source_context.run_id == context.workflow_run_id
                confirmation_calls.append(values)
                return {'stateVersion': 9, 'executionResumed': False}
            monkeypatch.setattr(policy_adoption_recovery, 'confirm_policy_adoption_preparation', confirmed)
            editor.recalculation_database = database.async_db
            editor.recalculation_durable = True
            confirmation_request = PreparationConfirmationRequest(kind='analysis', expectedStateVersion=8,
                identity={'path': 'analysis/preparation.json', 'size': 8, 'sha256': 'a' * 64})
            async def busy(*_args, **_kwargs):
                return SimpleNamespace(status='running')
            monkeypatch.setattr(recalculation, 'read_recalculation_run', busy)
            with pytest.raises(ReportingError, match='report_editor_conflict'):
                await editor.confirm_recalculation_preparation(context, task.task_id, confirmation_request)
            assert not confirmation_calls
            async def ended(*_args, **_kwargs):
                return SimpleNamespace(status='error')
            monkeypatch.setattr(recalculation, 'read_recalculation_run', ended)
            response = await editor.confirm_recalculation_preparation(context, task.task_id, confirmation_request)
            assert response['executionResumed'] is False and response['runId'] == execution.scope.run_id
            assert confirmation_calls == [{'kind': 'analysis', 'identity': confirmation_request.identity,
                'expected_state_version': 8}]
            assert (await editor.state_repository.get(context.workflow_run_id)).model_dump() == before_inspection
            assert not confirmations and not generations
            async def unknown_confirmation(*_args, **_kwargs):
                raise OSError('confirmation response lost')
            monkeypatch.setattr(policy_adoption_recovery, 'confirm_policy_adoption_preparation', unknown_confirmation)
            with pytest.raises(ReportingError, match='report_editor_recalculation_unavailable'):
                await editor.confirm_recalculation_preparation(context, task.task_id, confirmation_request)
            assert not confirmations and not generations
            return
        if fault == 'changed_pdf':
            await editor.workspace.awrite_bytes(target_scope.workspace_key, content['pdfPath'], b'changed', overwrite=True)
        apply = repository.apply
        if fault == 'completion_response':
            async def lose_completion(run_id, command, **options):
                result = await apply(run_id, command, **options)
                if command.name == 'record_report_editor_recalculation' and command.payload['task']['status'] == 'completed':
                    raise OSError('adoption task completion committed but response lost')
                return result
            monkeypatch.setattr(repository, 'apply', lose_completion)
        if fault == 'native_workflow':
            from smart_reporting.report_editor.recalculation import (
                RecalculationTask,
                create_policy_adoption_workflow,
                recalculation_run_input,
            )

            workflow = create_policy_adoption_workflow(editor, runtime=runtime, database=database.async_db)
            output = await workflow.arun(input=recalculation_run_input(context, task),
                session_id='report-editor-' + task.task_id, user_id=context.scope['userId'])
            returned = RecalculationTask.model_validate(output.content)
            assert returned.status == 'completed'
            assert returned.result.execution == execution
            saved = await workflow.aget_session(session_id='report-editor-' + task.task_id,
                user_id=context.scope['userId'])
            assert saved.runs[0].input == recalculation_run_input(context, task)
            assert saved.runs[0].content == output.content
        else:
            returned, published = await run_policy_adoption_request(editor, context, task.task_id, runtime=runtime)
        if fault == 'completion_response':
            assert returned.status == 'pending'
            assert 'policy_adoption_completion_record_unavailable' in {issue['code'] for issue in published.content['validationIssues']}
            monkeypatch.setattr(repository, 'apply', apply)
        else:
            assert returned.status == 'completed'
        frozen = await read_task(editor, context, request.request_id)
        assert frozen.status == 'completed' and frozen.result.execution == execution
        assert frozen.result.calculation_status == 'adopted_policy' and frozen.result.business_approval == 'not_performed'
        assert frozen.result.validation_passed is False
        inspected = await editor.recalculation_preparation(context, task.task_id)
        assert inspected['taskId'] == task.task_id and inspected['runId'] == execution.scope.run_id
        assert inspections == [execution.scope.run_id]
        expected_count = 1 if fault == 'changed_pdf' else 2
        assert len(frozen.result.artifacts) == expected_count
        if fault == 'changed_pdf':
            assert not published.content.get('pdfPath') and published.content['wordPath']
            assert 'policy_adoption_pdf_artifact_unavailable' in frozen.result.issue_codes
        runtime.state_repository = ReportingStateRepository(database.async_db)
        editor.state_repository = runtime.state_repository
        repeated, published_again = await run_policy_adoption_request(editor, context, task.task_id, runtime=runtime)
        assert repeated == frozen and published_again.content['wordPath']
        assert len(generations) == 1 and len(recoveries) == 1 and len(confirmations) == 1
        assert confirmations[0].request_id == task.task_id
        assert confirmations[0].question_choices == request.confirmation.question_choices
        issued = []
        async def issue(**arguments):
            assert arguments['workflow_run_id'] == execution.scope.run_id
            assert arguments['workflow_session_id'] == execution.scope.session_id
            assert arguments['thread_id'] == execution.scope.workspace_key
            assert arguments['caller_thread_id'] == context.scope['callerThreadId']
            assert arguments['user_id'] == context.scope['userId']
            assert arguments['output'].content['reportId'] == execution.scope.run_id
            issued.append(arguments)
            return {'deliveryFormat': 'document', 'formalReleaseAllowed': False}
        monkeypatch.setattr(runtime, 'issue_http_publication', issue)
        editor.recalculation_runtime = runtime
        delivery = await editor.recalculation_delivery(context, task.task_id)
        assert delivery['task'] == frozen.model_dump(mode='json', by_alias=True)
        assert delivery['delivery']['formalReleaseAllowed'] is False
        assert len(issued) == 1 and len(recoveries) == 2
        assert len(confirmations) == len(generations) == 1
    finally:
        await cleanup()
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('tamper', [None, 'input_hash', 'context', 'user', 'session', 'missing_context', 'wrong_operation', 'executor_unknown'])
async def test_rebuilt_policy_adoption_workflow_restores_only_confirmed_request(tmp_path, monkeypatch, tamper):
    from types import SimpleNamespace

    from agno.db.sqlite import SqliteDb
    from agno.run import RunContext
    from agno.workflow.types import StepInput, StepOutput

    from smart_reporting.report_editor import recalculation

    editor, repository, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    async def preview(*args, **kwargs):
        return SimpleNamespace(parent_basis_id=index.report_basis_id, digest=lambda: 'a' * 64)
    editor.trace.report_basis_service = SimpleNamespace(preview_policy_adoption=preview)
    request = recalculation.PolicyAdoptionRequest(requestId='native-adoption', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), confirmation={
            'requestId': 'native-adoption', 'targetPolicyVersion': {'policyId': 'budget-policy', 'revision': 2},
            'previewHash': 'a' * 64, 'questionChoices': [{'questionId': 'q-budget',
                'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '采用新指标'}]})
    if tamper == 'wrong_operation':
        task = await recalculation.register_refresh_request(editor, context,
            recalculation.RecalculationRequest(requestId=request.request_id, parentRevision=context.revision,
                expectedSha256=request.expected_sha256, operation='refresh_data'), parent_report_revision='initial')
    else:
        task = await recalculation.register_policy_adoption_request(editor, context, request)
    inputs = recalculation.recalculation_run_input(context, task)
    selected = RunContext(run_id='native-adoption-run', session_id='report-editor-' + task.task_id,
        user_id=context.scope['userId'])
    if tamper == 'input_hash':
        inputs['inputHash'] = '0' * 64
    elif tamper == 'context':
        inputs['contextSha256'] = '0' * 64
    elif tamper == 'user':
        selected.user_id = 'foreign-user'
    elif tamper == 'session':
        selected.session_id = 'foreign-session'
    elif tamper == 'missing_context':
        repository.state.payload['reportEditorContexts'] = {}
    calls = []
    async def execute(restored_editor, restored_context, restored_task, *, runtime):
        assert restored_context == context and restored_task == task.task_id
        calls.append(restored_task)
        if tamper == 'executor_unknown':
            raise OSError('交付执行结果未知')
        return task, StepOutput(content={})
    monkeypatch.setattr(recalculation, 'run_policy_adoption_request', execute)
    rebuilt = ReportEditorService(state_repository=repository, workspace_registry=editor.workspace_registry,
        workspace=editor.workspace)
    workflow = recalculation.create_policy_adoption_workflow(rebuilt, runtime=object(),
        database=SqliteDb(db_file=str(tmp_path / 'adoption.sqlite')))
    assert workflow.id == 'report-editor-policy-adoption'
    if tamper == 'executor_unknown':
        await workflow.arun(input=inputs, session_id=selected.session_id, user_id=selected.user_id)
        assert calls == [task.task_id]
        assert (await recalculation.read_task(editor, context, request.request_id)).status == 'pending'
    elif tamper:
        with pytest.raises(ReportingError, match='report_editor_scope_mismatch'):
            await workflow.steps[0].executor(StepInput(input=inputs), run_context=selected)
        assert calls == []
    else:
        # 通过原生Workflow执行，确认输入/输出和会话可持久读回。
        output = await workflow.arun(input=inputs, session_id=selected.session_id, user_id=selected.user_id)
        assert output.content == task.model_dump(mode='json', by_alias=True)
        saved = await workflow.aget_session(session_id=selected.session_id, user_id=selected.user_id)
        assert saved.runs[0].input == inputs and saved.runs[0].content == output.content
        assert calls == [task.task_id]


@pytest.mark.anyio
async def test_preparation_inspection_http_requires_matching_editor_session(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )
    from smart_reporting.report_editor.api import create_report_editor_router

    editor, repository, context, _ = await native_editor(tmp_path)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    calls = []

    async def inspect(expected, task_id):
        assert expected == context
        calls.append(task_id)
        return {'taskId': task_id, 'analysis': {'status': 'awaiting_confirmation'}}

    monkeypatch.setattr(editor, 'recalculation_preparation', inspect, raising=False)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/recalculations/task/preparation'
    before = repository.state.model_dump()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        assert (await client.get(base)).status_code == 404
        assert calls == []
        await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
        response = await client.get(base)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['analysis']['status'] == 'awaiting_confirmation'
        for wrong in (base.replace(context.report_id, 'foreign-report'),
                base.replace(f'/{context.revision}/api', '/999/api')):
            assert (await client.get(wrong)).status_code == 404
    assert calls == ['task']
    assert repository.state.model_dump() == before


@pytest.mark.anyio
async def test_preparation_confirmation_http_requires_csrf_and_explicit_identity(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )
    from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router

    editor, repository, context, _ = await native_editor(tmp_path)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    calls = []
    async def confirm(expected, task_id, payload):
        assert expected == context and task_id == 'task'
        calls.append(payload)
        return {'executionResumed': False, 'stateVersion': 9}
    monkeypatch.setattr(editor, 'confirm_recalculation_preparation', confirm, raising=False)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/recalculations/task/preparation/confirm'
    payload = {'kind': 'analysis', 'expectedStateVersion': 8,
        'identity': {'path': 'report/analysis-preparation.json', 'size': 8, 'sha256': 'a' * 64}}
    before = repository.state.model_dump()
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        assert (await client.post(base, json=payload)).status_code == 403
        await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
        assert (await client.post(base, json=payload)).status_code == 403
        headers = {'origin': 'http://reports.test',
            'x-csrf-token': grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
        response = await client.post(base, json=payload, headers=headers)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'no-store'
        assert response.json()['executionResumed'] is False
        for invalid in ({'kind': 'automatic'}, {'expectedStateVersion': -1}, {'extra': True}):
            assert (await client.post(base, json={**payload, **invalid}, headers=headers)).status_code == 422
        for wrong in (base.replace(context.report_id, 'foreign-report'),
                base.replace(f'/{context.revision}/api', '/999/api')):
            assert (await client.post(wrong, json=payload, headers=headers)).status_code == 403
    assert len(calls) == 1
    assert calls[0].model_dump(mode='json', by_alias=True) == payload
    assert repository.state.model_dump() == before


@pytest.mark.anyio
@pytest.mark.parametrize('queue_status', ['pending', 'running', 'paused', 'unknown', None, 'read_error', 'error'])
async def test_confirmation_checks_queue_even_when_session_is_terminal(monkeypatch, queue_status):
    from types import SimpleNamespace

    from smart_reporting.report_editor import recalculation

    reads = []
    async def read(editor, context, task_id, *, database, queue_only=False):
        reads.append(queue_only)
        status = queue_status if queue_only else 'error'
        if status == 'read_error':
            raise OSError('queue observation unavailable')
        return SimpleNamespace(status=status) if status is not None else None
    monkeypatch.setattr(recalculation, 'read_recalculation_run', read)
    operation = recalculation.require_recalculation_ended(SimpleNamespace(recalculation_durable=True),
        object(), 'task', database=object())
    if queue_status == 'error':
        await operation
    else:
        with pytest.raises(ReportingError, match=(
                'report_editor_recalculation_unavailable' if queue_status == 'read_error' else 'report_editor_conflict')):
            await operation
    assert reads == [False, True]


@pytest.mark.anyio
@pytest.mark.parametrize('fault', ['none', 'identity', 'unregistered', 'user', 'session', 'unknown'])
async def test_policy_recovery_workflow_restores_confirmed_input_without_automatic_retry(tmp_path, monkeypatch, fault):
    from types import SimpleNamespace

    from agno.db.sqlite import SqliteDb
    from agno.workflow.types import StepOutput

    from smart_reporting.report_editor import policy_recovery, recalculation

    editor, _, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    async def preview(*_args, **_kwargs):
        return SimpleNamespace(parent_basis_id=index.report_basis_id, digest=lambda: 'a' * 64)
    editor.trace.report_basis_service = SimpleNamespace(preview_policy_adoption=preview)
    request = recalculation.PolicyAdoptionRequest(requestId='recover-policy', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), confirmation={
            'requestId': 'recover-policy', 'targetPolicyVersion': {'policyId': 'budget', 'revision': 2},
            'previewHash': 'a' * 64, 'questionChoices': [{'questionId': 'q-budget',
                'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '明确选择'}]})
    task = await recalculation.register_policy_adoption_request(editor, context, request)
    confirmation = recalculation.PreparationConfirmationRequest(kind='analysis', expectedStateVersion=8,
        identity={'path': 'analysis/preparation.json', 'size': 8, 'sha256': 'a' * 64})
    inputs = policy_recovery.recovery_run_input(context, task, confirmation)
    recovery_id = policy_recovery.recovery_run_id(inputs)
    calls = []
    async def inspect(selected_editor, selected_context, selected_task_id, *, runtime):
        assert selected_context == context and selected_task_id == task.task_id
        return {'analysis': {'status': 'awaiting_confirmation' if fault == 'unregistered' else 'registered',
            'identity': confirmation.identity.model_dump(mode='json')}, 'document': {'status': 'not_applicable'}}
    async def ended(*_args, **_kwargs):
        return None
    async def execute(selected_editor, selected_context, selected_task_id, *, runtime):
        assert selected_context == context and selected_task_id == task.task_id
        calls.append(selected_task_id)
        if fault == 'unknown':
            raise OSError('recovery execution outcome unknown')
        return task, StepOutput(content={})
    monkeypatch.setattr(recalculation, 'read_policy_adoption_preparation', inspect)
    monkeypatch.setattr(recalculation, 'require_recalculation_ended', ended)
    monkeypatch.setattr(recalculation, 'run_policy_adoption_request', execute)
    database = SqliteDb(db_file=str(tmp_path / 'policy-recovery.db'))
    workflow = policy_recovery.create_policy_recovery_workflow(editor, runtime=object(), database=database)
    if fault == 'identity':
        inputs = {**inputs, 'identity': {**inputs['identity'], 'sha256': 'b' * 64}}
        recovery_id = policy_recovery.recovery_run_id(inputs)
    if fault in {'identity', 'unregistered', 'user', 'session'}:
        from agno.run import RunContext
        from agno.workflow.types import StepInput

        with pytest.raises(ReportingError):
            await workflow.steps[0].executor(StepInput(input=inputs), RunContext(run_id=recovery_id,
                user_id='foreign' if fault == 'user' else context.scope['userId'],
                session_id='foreign' if fault == 'session' else 'report-editor-recovery-' + recovery_id))
        assert calls == []
        return
    output = await workflow.arun(input=inputs, run_id=recovery_id,
        session_id='foreign' if fault == 'session' else 'report-editor-recovery-' + recovery_id,
        user_id='foreign' if fault == 'user' else context.scope['userId'])
    if fault == 'none':
        assert output.content['taskId'] == task.task_id
        assert calls == [task.task_id]
    elif fault == 'unknown':
        assert calls == [task.task_id]
        assert (await recalculation.read_task_by_id(editor, context, task.task_id)).status == 'pending'


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.parametrize('lost_response', [False, True])
async def test_confirmed_policy_recovery_queue_survives_rebuild_without_restarting_original(tmp_path, monkeypatch, lost_response):
    import os
    from types import SimpleNamespace

    from agno.db.schemas.jobs import QueuedJob
    from agno.os.job_queue import QueueWorker, resolve_queue_store
    from agno.workflow.types import StepOutput
    from sqlalchemy import delete

    from smart_reporting.report_editor import policy_recovery, recalculation
    from smart_reporting.reporting.workflow.repository import ReportingStateRepository
    from smart_reporting.runtime.database import create_agent_database

    url = os.getenv('REPORTING_MANAGEMENT_TEST_DB_URL')
    if not url:
        pytest.skip('需要隔离PostgreSQL测试数据库')
    editor, memory, context, markdown = await native_editor(tmp_path)
    index = await editor.trace.require_index(context)
    async def preview(*_args, **_kwargs):
        return SimpleNamespace(parent_basis_id=index.report_basis_id, digest=lambda: 'a' * 64)
    editor.trace.report_basis_service = SimpleNamespace(preview_policy_adoption=preview)
    database = create_agent_database(url)
    repository = ReportingStateRepository(database.async_db)
    await repository.initialize()
    async with database.async_engine.begin() as connection:
        for table in (repository.command_receipts, repository.states, repository.runs):
            await connection.execute(delete(table).where(table.c.report_run_id == context.workflow_run_id))
    await repository.create(memory.state)
    editor.state_repository = repository
    request = recalculation.PolicyAdoptionRequest(requestId=f'recover-queue-{lost_response}', parentRevision=context.revision,
        expectedSha256=hashlib.sha256(markdown.encode()).hexdigest(), confirmation={
            'requestId': f'recover-queue-{lost_response}', 'targetPolicyVersion': {'policyId': 'budget', 'revision': 2},
            'previewHash': 'a' * 64, 'questionChoices': [{'questionId': 'q-budget',
                'metricVersion': {'metricId': 'budget', 'revision': 2}, 'reason': '明确选择'}]})
    task = await recalculation.register_policy_adoption_request(editor, context, request)
    confirmation = recalculation.PreparationConfirmationRequest(kind='analysis', expectedStateVersion=8,
        identity={'path': 'analysis/preparation.json', 'size': 8, 'sha256': 'a' * 64})
    inputs = policy_recovery.recovery_run_input(context, task, confirmation)
    recovery_id = policy_recovery.recovery_run_id(inputs)
    config = recalculation.recalculation_queue_config()
    config.poll_interval = 0.05
    store = resolve_queue_store(config, database.async_db)
    editor.recalculation_durable = True
    editor.recalculation_queue_worker = SimpleNamespace(config=config, store=store)
    original_id = recalculation.recalculation_queue_run_id(task)
    await store.enqueue_job(QueuedJob(id=original_id, status='failed',
        component_type='workflow', component_id='report-editor-policy-adoption',
        session_id='report-editor-' + task.task_id, user_id=context.scope['userId'],
        payload={'input': recalculation.recalculation_run_input(context, task), 'stream': False},
        deployment_id=config.deployment_id, max_attempts=1, idempotency_key=original_id).to_dict())
    original = await store.get_job(original_id)
    confirmations, executions = [], []
    inspected = {'analysis': {'status': 'registered', 'identity': confirmation.identity.model_dump(mode='json')},
        'document': {'status': 'not_applicable'}}
    async def confirm(*_args, **_kwargs):
        confirmations.append(1)
        return inspected
    async def inspect(*_args, **_kwargs):
        return inspected
    async def execute(selected_editor, selected_context, selected_task_id, *, runtime):
        assert selected_context == context and selected_task_id == task.task_id
        executions.append(selected_task_id)
        return await recalculation.read_task_by_id(selected_editor, context, task.task_id), StepOutput(content={})
    monkeypatch.setattr(recalculation, 'confirm_policy_adoption_preparation_request', confirm)
    monkeypatch.setattr(recalculation, 'read_policy_adoption_preparation', inspect)
    monkeypatch.setattr(recalculation, 'run_policy_adoption_request', execute)
    enqueue = store.enqueue_job
    if lost_response:
        async def lost(*args, **kwargs):
            await enqueue(*args, **kwargs)
            raise OSError('recovery accepted but response lost')
        monkeypatch.setattr(store, 'enqueue_job', lost)
        with pytest.raises(ReportingError, match='report_editor_recalculation_unavailable'):
            await policy_recovery.dispatch_policy_recovery(editor, context, task.task_id, confirmation,
                runtime=object(), database=database.async_db)
        monkeypatch.setattr(store, 'enqueue_job', enqueue)
    else:
        accepted = await policy_recovery.dispatch_policy_recovery(editor, context, task.task_id, confirmation,
            runtime=object(), database=database.async_db)
        assert accepted['recoveryId'] == recovery_id and accepted['status'] == 'pending'
    await database.async_engine.dispose()
    database.sync_engine.dispose()
    rebuilt_db = create_agent_database(url)
    editor.state_repository = ReportingStateRepository(rebuilt_db.async_db)
    new_store = resolve_queue_store(config, rebuilt_db.async_db)
    worker = QueueWorker(store=new_store, config=config, stop_timeout=0,
        resolve_component=lambda kind, component: policy_recovery.create_policy_recovery_workflow(editor,
            runtime=object(), database=rebuilt_db.async_db) if (kind, component) == (
                'workflow', 'report-editor-policy-recovery') else None)
    editor.recalculation_queue_worker = worker
    try:
        status = await policy_recovery.read_policy_recovery(editor, context, task.task_id, recovery_id, database=rebuilt_db.async_db)
        assert status['status'] == 'pending' and not executions
        repeated = await policy_recovery.dispatch_policy_recovery(editor, context, task.task_id, confirmation,
            runtime=object(), database=rebuilt_db.async_db)
        assert repeated == status and confirmations == [1]
        document = recalculation.PreparationConfirmationRequest(kind='document', expectedStateVersion=9,
            identity={'path': 'analysis/document-job.json', 'size': 9, 'sha256': 'b' * 64})
        async def confirm_document(*_args, **_kwargs):
            return {**inspected, 'document': {'status': 'registered', 'identity': document.identity.model_dump(mode='json')}}
        with monkeypatch.context() as patch:
            patch.setattr(recalculation, 'confirm_policy_adoption_preparation_request', confirm_document)
            with pytest.raises(ReportingError, match='report_editor_conflict'):
                await policy_recovery.dispatch_policy_recovery(editor, context, task.task_id, document,
                    runtime=object(), database=rebuilt_db.async_db)
        document_id = policy_recovery.recovery_run_id(policy_recovery.recovery_run_input(context, task, document))
        assert await new_store.get_job(document_id) is None
        await worker.start()
        async def finished():
            while True:
                state = await policy_recovery.read_policy_recovery(editor, context, task.task_id, recovery_id,
                    database=rebuilt_db.async_db)
                if state['status'] == 'completed':
                    return
                assert state['status'] in {'pending', 'running'}, state
                await asyncio.sleep(0.05)
        await asyncio.wait_for(finished(), timeout=10)
        assert executions == [task.task_id] and confirmations == [1]
        assert (await new_store.get_job(original_id)) == original
        job = await new_store.get_job(recovery_id)
        assert job['attempt'] == 1 and job['max_attempts'] == 1
        delivered = await policy_recovery.read_policy_recovery(editor, context, task.task_id, recovery_id,
            database=rebuilt_db.async_db)
        assert delivered['deliveryStatus'] == 'pending'
        assert delivered['issueCodes'] == ['policy_recovery_completion_unconfirmed']
        for field in ('user_id', 'session_id', 'deployment_id'):
            with monkeypatch.context() as patch:
                async def foreign(*_args, **_kwargs):
                    return {**job, field: 'foreign'}
                patch.setattr(new_store, 'get_job', foreign)
                with pytest.raises(ReportingError, match='report_editor_scope_mismatch'):
                    await policy_recovery.read_policy_recovery(editor, context, task.task_id, recovery_id,
                        database=rebuilt_db.async_db)
    finally:
        await worker.stop()
        await rebuilt_db.async_engine.dispose()
        rebuilt_db.sync_engine.dispose()


@pytest.mark.anyio
async def test_policy_recovery_http_dispatch_and_poll_use_editor_session(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
    )
    from smart_reporting.report_editor.api import EDITOR_SESSION_COOKIE, create_report_editor_router

    editor, _, context, _ = await native_editor(tmp_path)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret='s' * 32)
    raw, _ = await grants.issue(context)
    calls = []
    state = {'recoveryId': 'recovery', 'taskId': 'task', 'status': 'pending', 'deliveryStatus': 'pending', 'issueCodes': []}
    async def resume(expected, task_id, payload):
        assert expected == context and task_id == 'task'
        calls.append(payload)
        return state
    async def read(expected, task_id, recovery_id):
        assert expected == context and task_id == 'task' and recovery_id == 'recovery'
        return state
    monkeypatch.setattr(editor, 'resume_recalculation_preparation', resume, raising=False)
    monkeypatch.setattr(editor, 'recalculation_recovery_status', read, raising=False)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base = f'/reports/v1/editor/{context.report_id}/{context.revision}/api/recalculations/task/preparation'
    payload = {'kind': 'analysis', 'expectedStateVersion': 8,
        'identity': {'path': 'report/preparation.json', 'size': 8, 'sha256': 'a' * 64}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://reports.test') as client:
        assert (await client.get(base + '/recoveries/recovery')).status_code == 404
        await client.get(f'/reports/v1/editor/open/{raw}', follow_redirects=False)
        assert (await client.post(base + '/resume', json=payload)).status_code == 403
        headers = {'origin': 'http://reports.test',
            'x-csrf-token': grants.csrf_token(client.cookies.get(EDITOR_SESSION_COOKIE))}
        response = await client.post(base + '/resume', json=payload, headers=headers)
        assert response.status_code == 202 and response.json() == state
        assert response.headers['cache-control'] == 'no-store'
        readback = await client.get(base + '/recoveries/recovery')
        assert readback.status_code == 200 and readback.json() == state
        assert readback.headers['cache-control'] == 'no-store'
        wrong = base.replace(context.report_id, 'foreign')
        assert (await client.post(wrong + '/resume', json=payload, headers=headers)).status_code == 403
        assert (await client.get(wrong + '/recoveries/recovery')).status_code == 404
        assert len(calls) == 1
