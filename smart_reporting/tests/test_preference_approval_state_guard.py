"""原生Reporting SQL依赖与管理批准提交窗口，合同字段证据仍为测试替身。"""

import asyncio
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from agno.db.postgres import AsyncPostgresDb
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.management.models import ManagementError
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.tests.test_management_persistence import auth_context as auth_context
from smart_reporting.tests.test_preference_approval_apply import approved as approved
from smart_reporting.tests.test_preference_approval_apply import count_publications
from smart_reporting.tests.test_preference_verification_handoff import case as case

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.mark.parametrize('target', ['state', 'run'])
async def test_apply_rejects_workflow_rows_changed_after_material_readback(case, approved, monkeypatch, target):
    service, request, _, _ = approved
    repository = service.handoff.bound.editor.state_repository
    session = await case[8].lookup_session(case[6])
    original = service.evidence._current_artifacts

    async def mutate_after_material_check(*args):
        result = await original(*args)
        async with repository.db.db_engine.begin() as connection:
            if target == 'state':
                state = await repository.get(session.workflow_run_id)
                payload = deepcopy(state.payload)
                payload['reportEditorContexts']['1']['job']['_documentContext']['title'] = '核验后变更标题'
                await connection.execute(update(repository.states).where(
                    repository.states.c.report_run_id == session.workflow_run_id).values(payload=payload))
            else:
                await connection.execute(update(repository.runs).where(
                    repository.runs.c.report_run_id == session.workflow_run_id).values(database='changed-after-readback'))
        return result

    monkeypatch.setattr(service.evidence, '_current_artifacts', mutate_after_material_check)
    with pytest.raises(ManagementError):
        await service.preferences.apply_approved(case[5], **request)
    assert await count_publications(case) == (0, 0)


@pytest.mark.parametrize('storage', ['same_engine', 'shared_pool', 'separate_pool', 'separate_database'])
async def test_state_dependency_lock_survives_until_management_commit_with_single_connection_pool(case, approved, monkeypatch, storage):
    service, request, _, _ = approved
    editor, grants = service.handoff.bound.editor, case[8]
    initial = editor.state_repository
    original = case[7].engine
    session = await grants.lookup_session(case[6])
    state = await initial.get(session.workflow_run_id)
    registered = await initial.get_run(session.workflow_run_id)
    management = create_async_engine(original.url, pool_size=1, max_overflow=0, pool_timeout=.5)
    source = worker_engine = None
    database_name = None
    applying = writing = None
    checked, release, writer_started = (asyncio.Event() for _ in range(3))
    audit = service.preferences._audit

    async def paused(connection, action, **details):
        result = await audit(connection, action, **details)
        if action == 'format_preferences_published':
            checked.set()
            await release.wait()
        return result

    try:
        if storage == 'same_engine':
            source = management
        elif storage == 'shared_pool':
            source = management.execution_options(logging_token='approval-state-source')
        elif storage == 'separate_pool':
            source = create_async_engine(original.url, pool_size=1, max_overflow=0)
        else:
            name = 'approval_guard_' + uuid4().hex
            async with original.connect() as connection:
                connection = await connection.execution_options(isolation_level='AUTOCOMMIT')
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
            database_name = name
            source = create_async_engine(original.url.set(database=name), pool_size=1, max_overflow=0)
        native = ReportingStateRepository(AsyncPostgresDb(db_engine=source))
        await native.initialize()
        if storage == 'separate_database':
            await native.register_run(**registered)
            await native.create(state)
        editor.state_repository = native
        case[7].engine = grants.repository.engine = management
        worker_engine = create_async_engine(source.url, pool_size=1, max_overflow=0)

        async def writer():
            # 独立pool已取到物理连接后才握手，阻塞不能由management单连接排队冒充。
            async with worker_engine.begin() as connection:
                writer_started.set()
                await connection.execute(update(native.states).where(
                    native.states.c.report_run_id == state.report_run_id).values(payload={
                        **state.payload, 'changedAfterApproval': True}))

        monkeypatch.setattr(service.preferences, '_audit', paused)
        applying = asyncio.create_task(service.preferences.apply_approved(case[5], **request))
        await asyncio.wait_for(checked.wait(), 25)
        writing = asyncio.create_task(writer())
        await asyncio.wait_for(writer_started.wait(), 5)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(writing), .2)
        release.set()
        assert (await asyncio.wait_for(applying, 15))['revision'] == 1
        await asyncio.wait_for(writing, 5)
        assert await count_publications(case) == (1, 1)
    finally:
        release.set()
        await asyncio.gather(*([applying] if applying else []), *([writing] if writing else []), return_exceptions=True)
        editor.state_repository = initial
        case[7].engine = grants.repository.engine = original
        if worker_engine is not None:
            await worker_engine.dispose()
        if source is not None and storage in ('separate_pool', 'separate_database'):
            await source.dispose()
        await management.dispose()
        if database_name is not None:
            async with original.connect() as connection:
                connection = await connection.execution_options(isolation_level='AUTOCOMMIT')
                await connection.execute(text(f'DROP DATABASE "{database_name}"'))


async def test_approval_refuses_a_repository_without_stable_dependency_support(case, approved, monkeypatch):
    service, request, _, _ = approved
    monkeypatch.setattr(service.handoff.bound.editor.state_repository, 'capture_read_dependencies', None)
    with pytest.raises(ManagementError) as error:
        await service.preferences.apply_approved(case[5], **request)
    assert error.value.code == 'management_preference_state_unavailable'
    assert await count_publications(case) == (0, 0)


def test_executor_identity_contains_both_state_guard_implementation_files():
    from hashlib import sha256

    from smart_reporting.management.preference_executor import executor_manifest

    files = {entry['path']: entry for entry in executor_manifest()['files']}
    for name in ('smart_reporting/reporting/workflow/repository.py', 'smart_reporting/reporting/workflow/read_guard.py'):
        assert files[name]['sha256'] == sha256(Path(name).read_bytes()).hexdigest()


async def test_actual_native_approval_task_bridge_uses_sql_dependency_guard(case, monkeypatch):
    from smart_reporting.tests import test_preference_native_approval_task_lifecycle as native

    output = Path('output/system-config-preferences/approval-state-read-guard/native-task-bridge')
    output.mkdir(exist_ok=False)
    monkeypatch.setattr(native, 'OUTPUT', output)
    await native.test_actual_native_evidence_applies_then_freezes_new_restart_and_derived_tasks(case, monkeypatch)
