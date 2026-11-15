"""真实 PostgreSQL + 授权 Host 工作区的原生候选任务重建与围栏。"""
from __future__ import annotations

import asyncio
import hashlib
import os
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import delete

from smart_reporting.report_editor.native_models import NativeArtifacts
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_native_pdf_extract import extract_fixture
from smart_reporting.reporting.tests.test_workbook_native_ai import proposal
from smart_reporting.runtime.database import create_agent_database
from smart_reporting.runtime.settings import AgentSettings
from smart_reporting.task_execution.models import TaskState
from smart_reporting.task_execution.repository import TaskExecutionRepository

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
async def durable(tmp_path):
    if os.getenv('NATIVE_AI_TEST_POSTGRES') != '1':
        pytest.skip('需显式 NATIVE_AI_TEST_POSTGRES=1 才连接当前 PostgreSQL')
    database = create_agent_database(AgentSettings.from_environment().database_url)
    repository = TaskExecutionRepository(database.async_db)
    await repository.initialize()
    fixture = await extract_fixture(tmp_path)
    book = Workbook(); book.active.title = 'Sheet'; book.active['A1'] = '来源'
    stream = BytesIO(); book.save(stream); content = stream.getvalue()
    identity = ArtifactFile(path='native/source.xlsx', size=len(content),
        sha256=hashlib.sha256(content).hexdigest(), mediaType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    await fixture.workspace.awrite_bytes(fixture.thread, identity.path, content)
    context = fixture.parent.model_copy(update={'format': 'xlsx', 'source_file': identity})
    old = fixture.repository.revisions[context.document_id]
    fixture.repository.revisions[context.document_id] = old.model_copy(update={
        'context': context, 'artifacts': NativeArtifacts(xlsx=identity)})
    fixture.editor.office_enabled = True
    token, _ = await fixture.editor.grants.issue(context, capabilities=fixture.editor.capabilities(context))
    _, session = await fixture.editor.grants.exchange(token)
    request = dict(client_request_id=uuid4().hex, instruction='改为候选', expected_sha256=identity.sha256,
        operations=[], selection={'sheetName': 'Sheet', 'startRow': 0, 'endRow': 0, 'startColumn': 0, 'endColumn': 0})
    services = []
    async def planner(*_args, **_kwargs):
        return proposal()
    def service(model=planner):
        ai = NativeWorkbookAIService(fixture.editor, planner=model, enabled=True, task_repository=repository)
        services.append(ai)
        return ai
    state = dict(repository=repository, database=database, fixture=fixture, context=context,
                 session=session, request=request, service=service)
    try:
        yield state
    finally:
        for ai in services:
            await ai.aclose()
        async with database.async_engine.begin() as connection:
            await connection.execute(delete(repository.tasks).where(
                repository.tasks.c.thread_id == context.scope.thread_id,
                repository.tasks.c.sandbox_id.like('native-workspace-%'),
                repository.tasks.c.agent_id == 'native-workbook-ai'))
        await fixture.workspace.registry.aclose()
        await database.async_engine.dispose()
        database.sync_engine.dispose()


async def never_call(*_args, **_kwargs):
    raise AssertionError('恢复终态不得重新调用模型')


async def test_candidate_and_acceptance_survive_service_rebuild(durable):
    d=durable; first=d['service'](); job=await first.start_edit(d['session'], **d['request'])
    result=await first.wait_edit_status(d['session'], job['editId'])
    assert result['status']=='succeeded', result
    await first.aclose()
    second=d['service'](never_call)
    assert await second.wait_edit_status(d['session'], job['editId']) == result
    accepted=await second.accept_edit(d['session'], job['editId'], expected_sha256=d['request']['expected_sha256'],
        operations=[], snapshot_sha256=result['snapshotSha256'])
    assert accepted['accepted'] is True
    third=d['service'](never_call)
    restored=await third.wait_edit_status(d['session'], job['editId'])
    assert restored['accepted'] and restored['proposal']==result['proposal']


async def test_cancel_before_start_is_durable_tombstone(durable):
    d=durable; first=d['service'](never_call)
    cancelled=await first.cancel_request(d['session'], d['request']['client_request_id'])
    await first.aclose()
    second=d['service'](never_call)
    late=await second.start_edit(d['session'], **d['request'])
    assert late['editId']==cancelled['editId'] and late['status']=='cancelled'
    response=await second.event_stream(d['session'], late['editId'])
    frames=[frame async for frame in response.body_iterator]
    assert 'cancelled' in ''.join(frames)


async def test_same_request_conflict_and_foreign_context_are_rejected(durable):
    d=durable; first=d['service'](); job=await first.start_edit(d['session'], **d['request'])
    await first.wait_edit_status(d['session'], job['editId'])
    second=d['service'](never_call)
    with pytest.raises(ReportingError):
        await second.start_edit(d['session'], **{**d['request'], 'instruction':'另一要求'})
    old=d['fixture'].editor.context_for_session
    async def foreign(_session):
        return d['context'].model_copy(update={'revision':d['context'].revision+1})
    d['fixture'].editor.context_for_session=foreign
    try:
        with pytest.raises(ReportingError):
            await second.wait_edit_status(d['session'], job['editId'])
    finally:
        d['fixture'].editor.context_for_session=old


async def test_two_instances_only_one_planner_owns_request(durable):
    d=durable; gate=asyncio.Event(); entered=asyncio.Event(); calls=[]
    async def blocked(*_args, **_kwargs):
        calls.append(True); entered.set(); await gate.wait(); return proposal()
    first=d['service'](blocked); second=d['service'](blocked)
    one,two=await asyncio.gather(first.start_edit(d['session'], **d['request']), second.start_edit(d['session'], **d['request']))
    assert one['editId']==two['editId']
    await asyncio.wait_for(entered.wait(),5)
    assert len(calls)==1
    gate.set()
    result=await second.wait_edit_status(d['session'], one['editId'])
    assert result['status']=='succeeded',result
    assert len(calls)==1


async def test_shutdown_releases_lease_and_rebuild_resumes_same_task(durable):
    d=durable; entered=asyncio.Event()
    async def blocked(*_args, **_kwargs):
        entered.set(); await asyncio.Event().wait()
    first=d['service'](blocked); job=await first.start_edit(d['session'], **d['request'])
    await asyncio.wait_for(entered.wait(),5)
    await first.aclose()
    second=d['service'](); restored=await second.start_edit(d['session'], **d['request'])
    assert restored['editId']==job['editId']
    result=await second.wait_edit_status(d['session'], job['editId'])
    assert result['status']=='succeeded',result
    task=await d['repository'].get_task_snapshot('native-workbook-ai:'+job['editId'])
    attempt=await d['repository'].get_attempt(task.current_internal_run_id)
    assert task.state==TaskState.COMPLETED and attempt.resume_count==1


async def test_cross_instance_cancel_fences_late_model_result(durable):
    d=durable; entered=asyncio.Event(); release=asyncio.Event()
    async def blocked(*_args, **_kwargs):
        entered.set(); await release.wait(); return proposal()
    first=d['service'](blocked); job=await first.start_edit(d['session'], **d['request'])
    await asyncio.wait_for(entered.wait(),5)
    second=d['service'](never_call)
    cancelled=await asyncio.wait_for(second.cancel_request(d['session'],d['request']['client_request_id']),1)
    assert cancelled['status']=='cancelled'
    release.set()
    await first.wait_edit_status(d['session'],job['editId'])
    restored=await second.wait_edit_status(d['session'],job['editId'])
    assert restored['status']=='cancelled' and 'proposal' not in restored
    with pytest.raises(ReportingError):
        await first.accept_edit(d['session'],job['editId'],expected_sha256=d['request']['expected_sha256'],
            operations=[],snapshot_sha256=job['snapshotSha256'])

async def test_workbook_task_registration_is_atomic_and_keeps_digest_private(durable):
    from smart_reporting.task_execution.models import TaskExecutionScope
    from smart_reporting.task_execution.repository import TaskExecutionRepositoryError

    repository = durable['repository']
    context = durable['context']
    task_id = 'native-workbook-ai:' + uuid4().hex
    scope = TaskExecutionScope(task_id, context.scope.user_id, context.scope.thread_id,
                               'native-workspace-registration', 'native-workbook-ai')
    one, two = await asyncio.gather(*(
        repository.create_native_workbook_task(scope, 'Change selected range', 'a' * 64)
        for _ in range(2)
    ))
    assert one == two
    assert one.state is TaskState.NEW
    assert one.scope == scope
    assert await repository.attempt_instruction(task_id, 0) == 'Change selected range'
    assert 'a' * 64 not in repr(await repository.get_task_snapshot(task_id))

    with pytest.raises(TaskExecutionRepositoryError) as mismatch:
        await repository.create_native_workbook_task(scope, 'Change selected range', 'b' * 64)
    assert mismatch.value.code == 'native_workbook_input_conflict'
    with pytest.raises(TaskExecutionRepositoryError) as generic_retry:
        await repository.create_task_with_initial_attempt(scope, 'Change selected range')
    assert generic_retry.value.code == 'native_workbook_input_conflict'

async def test_workbook_candidate_finish_is_fenced_and_recoverable(durable):
    from dataclasses import replace
    from smart_reporting.task_execution.models import TaskExecutionScope
    from smart_reporting.task_execution.repository import TaskExecutionRepositoryError

    repository = durable['repository']
    context = durable['context']
    task_id = 'native-workbook-ai:' + uuid4().hex
    scope = TaskExecutionScope(task_id, context.scope.user_id, context.scope.thread_id,
                               'native-workspace-candidate', 'native-workbook-ai')
    request_sha256 = 'a' * 64
    task = await repository.create_native_workbook_task(scope, 'Change selected range', request_sha256)
    lease = await repository.claim_lease(task_id, 'candidate-worker')
    task, _ = await repository.open_initial(task_id, lease, task.state_version)
    receipt = {'contextSha256': context.digest(), 'snapshotSha256': 'b' * 64,
               'clientRequestId': 'original-request',
               'proposal': {'summary': 'Private workbook candidate', 'operations': proposal().engine_operations(),
                            'previewSha256': 'c' * 64}}

    with pytest.raises(TaskExecutionRepositoryError):
        await repository.request_native_workbook_finish(
            scope, replace(lease, epoch=lease.epoch + 1), task.state_version, request_sha256, receipt,
        )
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.request_native_workbook_finish(scope, lease, task.state_version, 'd' * 64, receipt)
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.request_finish(task_id, lease, task.state_version, {'invalid': True},
                                        result_text='control', retained_execution_ids=[])
    task = await repository.request_native_workbook_finish(scope, lease, task.state_version, request_sha256, receipt)
    assert task.state is TaskState.FINISHING
    assert 'Private workbook candidate' not in repr(task)
    assert await repository.get_completed_native_workbook_candidate(scope, context.digest()) is None

    await repository.release_lease(task_id, lease.owner)
    recovered_lease = await repository.claim_lease(task_id, 'recovery-worker')
    completed = await repository.finalize_finish(task_id, recovered_lease, task.state_version, agno_status='recovered')
    assert completed.state is TaskState.COMPLETED
    assert await repository.get_completed_native_workbook_candidate(scope, context.digest()) == {**receipt, "accepted": False}
    assert not await repository.accept_native_workbook_candidate(scope, {**receipt, "snapshotSha256": "f" * 64})
    assert not await repository.accept_native_workbook_candidate(replace(scope, owner_user_id="foreign"), receipt)
    assert await repository.accept_native_workbook_candidate(scope, receipt)
    assert await repository.accept_native_workbook_candidate(scope, receipt)
    assert await repository.get_completed_native_workbook_candidate(scope, context.digest()) == {**receipt, "accepted": True}
    assert await repository.get_completed_native_workbook_candidate(scope, 'f' * 64) is None
    assert await repository.get_completed_native_workbook_candidate(
        replace(scope, owner_user_id='foreign'), context.digest(),
    ) is None
