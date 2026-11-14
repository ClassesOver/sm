"""Lifecycle lease expiry at real PostgreSQL row-lock boundaries; disposable DB only."""
import asyncio
import os
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution.models import (
    AttemptOutcome,
    Lease,
    TaskExecutionScope,
    TaskState,
)
from smart_reporting.task_execution.repository import (
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def expiry_repository():
    url = os.getenv('REPORTING_TEST_DB_URL', '').strip()
    if not url:
        pytest.skip('REPORTING_TEST_DB_URL must refer to a disposable PostgreSQL database')
    database = create_agent_database(url)
    repository = TaskExecutionRepository(database.async_db)
    await repository.initialize()
    async with database.async_engine.begin() as connection:
        await connection.execute(text('TRUNCATE agentos_coding.agentos_coding_tasks CASCADE'))
    try:
        yield repository, database
    finally:
        async with database.async_engine.begin() as connection:
            await connection.execute(text('TRUNCATE agentos_coding.agentos_coding_tasks CASCADE'))
        await database.async_engine.dispose()
        database.sync_engine.dispose()


async def prepare_transition(repository, action):
    scope = TaskExecutionScope('expiry-' + action, 'user', 'thread', 'workspace', 'test-executor')
    task = await repository.create_task_with_initial_attempt(scope, 'Synthetic lifecycle goal')
    lease = await repository.claim_lease(scope.external_run_id, 'expiry-worker')
    if action != 'open':
        task, _attempt = await repository.open_initial(scope.external_run_id, lease, task.state_version)
    if action == 'finalize_finish':
        task = await repository.request_finish(scope.external_run_id, lease, task.state_version,
            {'synthetic': True}, result_text='Prepared result', retained_execution_ids=[])
    return scope, task, lease


async def transition(repository, scope, task, lease, action):
    if action == 'open':
        return await repository.open_initial(scope.external_run_id, lease, task.state_version)
    if action == 'resume':
        return await repository.resume_current(scope.external_run_id, lease, task.state_version)
    if action == 'close':
        return await repository.close_and_decide(scope.external_run_id, lease, task.state_version,
            outcome=AttemptOutcome.ERROR, agno_status='ERROR', create_next=True)
    if action == 'request_finish':
        return await repository.request_finish(scope.external_run_id, lease, task.state_version,
            {'synthetic': True}, result_text='Prepared result', retained_execution_ids=[])
    return await repository.finalize_finish(scope.external_run_id, lease, task.state_version,
                                             agno_status='COMPLETED')


async def read_rows(repository, database, external_run_id):
    async with database.async_engine.connect() as connection:
        task = (await connection.execute(select(repository.tasks).where(
            repository.tasks.c.external_run_id == external_run_id))).mappings().one()
        runs = (await connection.execute(select(repository.runs).where(
            repository.runs.c.external_run_id == external_run_id).order_by(
                repository.runs.c.continuation_index))).mappings().all()
        instructions = (await connection.execute(select(repository.instructions).where(
            repository.instructions.c.external_run_id == external_run_id).order_by(
                repository.instructions.c.sequence))).mappings().all()
    return dict(task), [dict(row) for row in runs], [dict(row) for row in instructions]


async def blocked_statement(database, blocker_pid):
    async def observe():
        while True:
            async with database.async_engine.connect() as connection:
                row = (await connection.execute(text('SELECT query, query_start FROM pg_stat_activity '
                    "WHERE datname=current_database() AND wait_event_type='Lock' "
                    'AND :blocker = ANY(pg_blocking_pids(pid))'), {'blocker': blocker_pid})).first()
            if row is not None:
                return row
            await asyncio.sleep(0.01)
    return await asyncio.wait_for(observe(), 5)


async def database_lease_expired(repository, database, external_run_id):
    async def observe():
        while True:
            async with database.async_engine.connect() as connection:
                expired = (await connection.execute(select(
                    repository.tasks.c.lease_expires_at <= text('clock_timestamp()')).where(
                    repository.tasks.c.external_run_id == external_run_id))).scalar_one()
            if expired:
                return
            await asyncio.sleep(0.01)
    await asyncio.wait_for(observe(), 5)


@pytest.mark.anyio
@pytest.mark.parametrize('action', ['open', 'resume', 'close', 'request_finish', 'finalize_finish'])
async def test_lifecycle_task_only_lock_expiry_rolls_back_task_run_and_instructions(expiry_repository, action):
    repository, database = expiry_repository
    scope, task, old_lease = await prepare_transition(repository, action)
    # Fixture setup commits the expiry BEFORE the blocker starts. The blocker
    # itself only SELECTs/FOR UPDATEs: no tuple change can trigger an EPQ recheck.
    async with database.async_engine.begin() as connection:
        expiry = (await connection.execute(update(repository.tasks).where(
            repository.tasks.c.external_run_id == scope.external_run_id).values(
                lease_expires_at=text("clock_timestamp() + interval '1 second'"))
                .returning(repository.tasks.c.lease_expires_at))).scalar_one()
    lease = Lease(old_lease.owner, old_lease.epoch, expiry)
    before = await read_rows(repository, database, scope.external_run_id)
    pending = None
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.tasks.c.external_run_id).where(
                repository.tasks.c.external_run_id == scope.external_run_id).with_for_update())
            pid = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(transition(repository, scope, task, lease, action))
            blocked = await blocked_statement(database, pid)
            assert blocked.query_start < expiry, 'operation must reach the DB before lease expiry'
            await database_lease_expired(repository, database, scope.external_run_id)
        result = (await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 5))[0]
        after = await read_rows(repository, database, scope.external_run_id)
        assert isinstance(result, TaskExecutionRepositoryError), (
            f'lease expired while task-only lock blocked SQL={blocked.query}; got {result!r}')
        assert result.code == 'task_cas_conflict'
        assert after == before, 'task/run/instruction writes must all roll back, not just task status'
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.anyio
async def test_generic_finalization_preserves_existing_deadline_budget_contract(expiry_repository):
    """Generic FINISHING bookkeeping does not invent a new hard deadline rule."""
    repository, database = expiry_repository
    scope, task, lease = await prepare_transition(repository, 'finalize_finish')
    async with database.async_engine.begin() as connection:
        await connection.execute(update(repository.tasks).where(
            repository.tasks.c.external_run_id == scope.external_run_id).values(
                deadline_at=text("clock_timestamp() - interval '1 second'")))
    completed = await repository.finalize_finish(scope.external_run_id, lease, task.state_version,
                                                agno_status='COMPLETED')
    assert completed.state is TaskState.COMPLETED


@pytest.mark.anyio
@pytest.mark.parametrize('action', ['open', 'resume', 'close', 'request_finish', 'finalize_finish'])
async def test_lifecycle_run_lock_expiry_rolls_back_all_prior_writes(expiry_repository, action):
    repository, database = expiry_repository
    scope, task, old_lease = await prepare_transition(repository, action)
    async with database.async_engine.begin() as connection:
        expiry = (await connection.execute(update(repository.tasks).where(
            repository.tasks.c.external_run_id == scope.external_run_id).values(
                lease_expires_at=text("clock_timestamp() + interval '1 second'"))
                .returning(repository.tasks.c.lease_expires_at))).scalar_one()
    lease = Lease(old_lease.owner, old_lease.epoch, expiry)
    before = await read_rows(repository, database, scope.external_run_id)
    pending = None
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.runs.c.internal_run_id).where(
                repository.runs.c.internal_run_id == task.current_internal_run_id).with_for_update())
            pid = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(transition(repository, scope, task, lease, action))
            blocked = await blocked_statement(database, pid)
            assert blocked.query_start < expiry
            await database_lease_expired(repository, database, scope.external_run_id)
        result = (await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 5))[0]
        assert isinstance(result, TaskExecutionRepositoryError), f'blocked SQL={blocked.query}; got {result!r}'
        assert result.code == 'task_cas_conflict'
        assert await read_rows(repository, database, scope.external_run_id) == before
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.anyio
async def test_heartbeat_task_only_lock_cannot_resurrect_expired_same_epoch(expiry_repository):
    repository, database = expiry_repository
    scope, _task, old_lease = await prepare_transition(repository, 'resume')
    async with database.async_engine.begin() as connection:
        expiry = (await connection.execute(update(repository.tasks).where(
            repository.tasks.c.external_run_id == scope.external_run_id).values(
                lease_expires_at=text("clock_timestamp() + interval '1 second'"))
                .returning(repository.tasks.c.lease_expires_at))).scalar_one()
    lease = Lease(old_lease.owner, old_lease.epoch, expiry)
    before = await read_rows(repository, database, scope.external_run_id)
    pending = None
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.tasks.c.external_run_id).where(
                repository.tasks.c.external_run_id == scope.external_run_id).with_for_update())
            pid = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(repository.heartbeat_lease(scope.external_run_id, lease, ttl=timedelta(seconds=10)))
            blocked = await blocked_statement(database, pid)
            assert blocked.query_start < expiry
            await database_lease_expired(repository, database, scope.external_run_id)
        result = (await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 5))[0]
        assert isinstance(result, TaskExecutionRepositoryError), (
            f'expired heartbeat was renewed after pure task lock wait; SQL={blocked.query}; got {result!r}')
        assert result.code == 'task_lease_lost'
        assert await read_rows(repository, database, scope.external_run_id) == before
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.anyio
async def test_heartbeat_short_wait_ttl_starts_after_lock_without_advancing_epoch_or_version(expiry_repository):
    repository, database = expiry_repository
    scope, task, lease = await prepare_transition(repository, 'resume')
    pending = None
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.tasks.c.external_run_id).where(
                repository.tasks.c.external_run_id == scope.external_run_id).with_for_update())
            pid = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(repository.heartbeat_lease(scope.external_run_id, lease, ttl=timedelta(seconds=2)))
            await blocked_statement(database, pid)
            await blocker.execute(text('SELECT pg_sleep(0.2)'))
            release_not_before = (await blocker.execute(text('SELECT clock_timestamp()'))).scalar_one()
        refreshed = await asyncio.wait_for(pending, 5)
        assert refreshed.expires_at >= release_not_before + timedelta(seconds=2)
        current = await repository.get_task_snapshot(scope.external_run_id)
        assert current.lease_expires_at == refreshed.expires_at
        assert current.lease_owner == lease.owner and current.lease_epoch == lease.epoch
        assert current.state_version == task.state_version
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize('invalid', ['owner', 'epoch', 'terminal'])
async def test_heartbeat_rejects_stale_identity_and_terminal_state(expiry_repository, invalid):
    repository, database = expiry_repository
    scope, _task, lease = await prepare_transition(repository, 'resume')
    if invalid == 'owner':
        lease = Lease('stale-worker', lease.epoch, lease.expires_at)
    elif invalid == 'epoch':
        lease = Lease(lease.owner, lease.epoch + 1, lease.expires_at)
    else:
        # Isolate the status check even if a legacy row retains owner/epoch.
        async with database.async_engine.begin() as connection:
            await connection.execute(update(repository.tasks).where(
                repository.tasks.c.external_run_id == scope.external_run_id).values(status=TaskState.COMPLETED))
    before = await read_rows(repository, database, scope.external_run_id)
    with pytest.raises(TaskExecutionRepositoryError) as rejected:
        await repository.heartbeat_lease(scope.external_run_id, lease)
    assert rejected.value.code == 'task_lease_lost'
    assert await read_rows(repository, database, scope.external_run_id) == before
