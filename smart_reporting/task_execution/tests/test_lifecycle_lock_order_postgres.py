"""Bounded, real PG contention for task-before-child lifecycle lock ordering."""
import asyncio

import pytest
from sqlalchemy import select, text

from smart_reporting.task_execution.models import AttemptOutcome, AttemptState, TaskState
from smart_reporting.task_execution.repository import TaskExecutionRepositoryError
from smart_reporting.task_execution.tests.test_lifecycle_expiry_postgres import (
    blocked_statement,
    prepare_transition,
)
from smart_reporting.task_execution.tests.test_lifecycle_expiry_postgres import (
    expiry_repository as expiry_repository,
)

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_request_finish_then_cancel_has_no_cross_table_deadlock(expiry_repository, monkeypatch):
    repository, database = expiry_repository
    scope, task, lease = await prepare_transition(repository, 'request_finish')
    ready, release = asyncio.Event(), asyncio.Event()
    state = {}
    original = repository._locked_task
    async def hold_real_task_lock(connection, *args, **kwargs):
        row = await original(connection, *args, **kwargs)
        state['pid'] = (await connection.execute(text('SELECT pg_backend_pid()'))).scalar_one()
        ready.set()
        await release.wait()
        return row
    monkeypatch.setattr(repository, '_locked_task', hold_real_task_lock)
    actors = [asyncio.create_task(repository.request_finish(scope.external_run_id, lease, task.state_version,
        {'synthetic': True}, result_text='Prepared result', retained_execution_ids=[]))]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        actors.append(asyncio.create_task(repository.cancel_and_reject(scope, lease=lease)))
        await blocked_statement(database, state['pid'])
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*actors, return_exceptions=True), 5)
        assert results[0].state is TaskState.FINISHING
        assert isinstance(results[1], TaskExecutionRepositoryError)
        current = await repository.get_task_snapshot(scope.external_run_id)
        assert current.state is TaskState.FINISHING
        run = await repository.get_attempt(current.current_internal_run_id)
        assert run.state is AttemptState.FINISH_REQUESTED and run.outcome is None
        # Cancellation did not silently succeed with stale state; a fresh explicit
        # retry may cancel the still-uncompleted task without changing this contract.
        cancelled = await repository.cancel_and_reject(scope, lease=lease)
        assert cancelled.state is TaskState.CANCELLED
    finally:
        release.set()
        for actor in actors:
            actor.cancel()
        await asyncio.gather(*actors, return_exceptions=True)


@pytest.mark.anyio
async def test_cancel_then_request_finish_has_no_run_task_deadlock_or_partial_finish(expiry_repository):
    repository, database = expiry_repository
    scope, task, lease = await prepare_transition(repository, 'request_finish')
    actors = []
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.tasks.c.external_run_id).where(
                repository.tasks.c.external_run_id == scope.external_run_id).with_for_update())
            holder = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            actors.append(asyncio.create_task(repository.cancel_and_reject(scope, lease=lease)))
            await blocked_statement(database, holder)
            async with database.async_engine.connect() as observer:
                cancellation_pid = (await observer.execute(text('SELECT pid FROM pg_stat_activity '
                    "WHERE datname=current_database() AND wait_event_type='Lock' "
                    'AND :holder = ANY(pg_blocking_pids(pid))'), {'holder': holder})).scalar_one()
            actors.append(asyncio.create_task(repository.request_finish(scope.external_run_id, lease, task.state_version,
                {'synthetic': True}, result_text='Prepared result', retained_execution_ids=[])))
            await blocked_statement(database, cancellation_pid)
        results = await asyncio.wait_for(asyncio.gather(*actors, return_exceptions=True), 5)
        assert results[0].state is TaskState.CANCELLED
        assert isinstance(results[1], TaskExecutionRepositoryError)
        current = await repository.get_task_snapshot(scope.external_run_id)
        assert current.state is TaskState.CANCELLED and current.finish_receipt is None
        run = await repository.get_attempt(current.current_internal_run_id)
        assert run.state is AttemptState.CLOSED and run.outcome is AttemptOutcome.CANCELLED
    finally:
        for actor in actors:
            actor.cancel()
        await asyncio.gather(*actors, return_exceptions=True)


@pytest.mark.anyio
async def test_run_wait_expiry_rolls_back_new_attempt_and_pending_instruction_application(expiry_repository):
    from smart_reporting.task_execution.models import Lease
    from smart_reporting.task_execution.tests.test_lifecycle_expiry_postgres import (
        database_lease_expired,
        read_rows,
        transition,
    )

    repository, database = expiry_repository
    scope, _task, old_lease = await prepare_transition(repository, 'close')
    await repository.submit_instruction(scope, 'pending-followup', 'Synthetic follow-up')
    task = await repository.get_task_snapshot(scope.external_run_id)
    async with database.async_engine.begin() as connection:
        expiry = (await connection.execute(text('UPDATE agentos_coding.agentos_coding_tasks '
            "SET lease_expires_at=clock_timestamp()+interval '1 second' "
            'WHERE external_run_id=:run RETURNING lease_expires_at'), {'run': scope.external_run_id})).scalar_one()
    lease = Lease(old_lease.owner, old_lease.epoch, expiry)
    before = await read_rows(repository, database, scope.external_run_id)
    pending = None
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.runs.c.internal_run_id).where(
                repository.runs.c.internal_run_id == task.current_internal_run_id).with_for_update())
            holder = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(transition(repository, scope, task, lease, 'close'))
            await blocked_statement(database, holder)
            await database_lease_expired(repository, database, scope.external_run_id)
        result = (await asyncio.wait_for(asyncio.gather(pending, return_exceptions=True), 5))[0]
        assert isinstance(result, TaskExecutionRepositoryError)
        assert await read_rows(repository, database, scope.external_run_id) == before
        assert await repository.pending_instructions(scope.external_run_id) == [(2, 'Synthetic follow-up')]
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
