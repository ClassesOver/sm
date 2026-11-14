"""Direct PG evidence for initializer contention, each CHECK and private projections."""
import asyncio
import json
import os
from dataclasses import asdict

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution.models import TaskExecutionScope
from smart_reporting.task_execution.native_word_contracts import word_finish_reference
from smart_reporting.task_execution.repository import TaskExecutionRepository
from smart_reporting.task_execution.tests.test_native_word_repository import (
    INSTRUCTION,
    commit,
    prepare,
)
from smart_reporting.task_execution.tests.test_native_word_repository import (
    word_repository as word_repository,
)

pytestmark = pytest.mark.integration


@pytest.mark.anyio
async def test_independent_database_initializers_contend_on_real_pg_advisory_lock(word_repository, monkeypatch):
    _repository, observer_database = word_repository
    first_database = create_agent_database(os.environ['REPORTING_TEST_DB_URL'])
    second_database = create_agent_database(os.environ['REPORTING_TEST_DB_URL'])
    first = TaskExecutionRepository(first_database.async_db)
    second = TaskExecutionRepository(second_database.async_db)
    ready, release = asyncio.Event(), asyncio.Event()
    state = {}
    original = first._migrate_schema
    async def hold_after_real_migration(connection):
        await original(connection)
        state['pid'] = (await connection.execute(text('SELECT pg_backend_pid()'))).scalar_one()
        ready.set()
        await release.wait()
    monkeypatch.setattr(first, '_migrate_schema', hold_after_real_migration)
    actors = []
    try:
        actors.append(asyncio.create_task(first.initialize()))
        await asyncio.wait_for(ready.wait(), 5)
        actors.append(asyncio.create_task(second.initialize()))
        async def advisory_wait_observed():
            while True:
                async with observer_database.async_engine.connect() as connection:
                    waiting = (await connection.execute(text('SELECT EXISTS(SELECT 1 FROM pg_locks l '
                        "WHERE l.pid=a.pid AND l.locktype='advisory' AND NOT l.granted) "
                        'FROM pg_stat_activity a WHERE :holder = ANY(pg_blocking_pids(a.pid))'),
                        {'holder': state['pid']})).scalar_one_or_none()
                if waiting:
                    return
                await asyncio.sleep(0.01)
        await asyncio.wait_for(advisory_wait_observed(), 5)
        release.set()
        await asyncio.wait_for(asyncio.gather(*actors), 5)
        assert first._initialized and second._initialized
    finally:
        release.set()
        await asyncio.gather(*actors, return_exceptions=True)
        for database in (first_database, second_database):
            await database.async_engine.dispose()
            database.sync_engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize('invalid', ['input_without_hash', 'receipt_without_hash', 'hash_without_receipt', 'receipt_without_input'])
async def test_each_private_column_check_rejects_invalid_storage_atomically(word_repository, invalid):
    repository, database = word_repository
    if invalid in {'receipt_without_hash', 'hash_without_receipt'}:
        _task, args = await prepare(repository)
        external_run_id = args['scope'].external_run_id
    else:
        external_run_id = 'legacy-check'
        await repository.create_task_with_initial_attempt(
            TaskExecutionScope(external_run_id, 'user', 'thread', 'workspace', 'legacy'), INSTRUCTION)
    columns = [repository.tasks.c.native_word_input, repository.tasks.c.native_word_input_sha256,
               repository.tasks.c.native_word_candidate_receipt, repository.tasks.c.native_word_candidate_sha256]
    async with database.async_engine.connect() as connection:
        before = (await connection.execute(select(*columns).where(
            repository.tasks.c.external_run_id == external_run_id))).one()
    values = {
        'input_without_hash': {'native_word_input': {'synthetic': True}},
        'receipt_without_hash': {'native_word_candidate_receipt': {'synthetic': True}},
        'hash_without_receipt': {'native_word_candidate_sha256': 'a' * 64},
        'receipt_without_input': {'native_word_candidate_receipt': {'synthetic': True},
                                  'native_word_candidate_sha256': 'a' * 64},
    }[invalid]
    with pytest.raises(IntegrityError):
        async with database.async_engine.begin() as connection:
            await connection.execute(update(repository.tasks).where(
                repository.tasks.c.external_run_id == external_run_id).values(**values))
    async with database.async_engine.connect() as connection:
        after = (await connection.execute(select(*columns).where(
            repository.tasks.c.external_run_id == external_run_id))).one()
    assert tuple(after) == tuple(before)


@pytest.mark.anyio
async def test_private_input_and_candidate_do_not_enter_generic_task_projections(word_repository):
    repository, _database = word_repository
    task, args = await prepare(repository)
    private_input = await repository.read_native_word_input(**args)
    assert private_input['selectedParagraphs'][0]['text'] == 'Synthetic paragraph'
    receipt = await commit(repository, args)
    task = await repository.get_task_snapshot(args['scope'].external_run_id)
    await repository.request_finish(args['scope'].external_run_id, args['lease'], task.state_version,
        word_finish_reference(receipt), result_text='Candidate ready', retained_execution_ids=[])
    for model in [await repository.get_task(args['scope'].external_run_id),
                  await repository.get_task_snapshot(args['scope'].external_run_id)]:
        projection = asdict(model)
        assert {'native_word_input', 'native_word_input_sha256', 'native_word_candidate_receipt',
                'native_word_candidate_sha256'}.isdisjoint(projection)
        rendered = json.dumps(projection, default=str) + repr(model)
        for private in ['Synthetic paragraph', 'Synthetic replacement', 'selectedParagraphs', 'f' * 64, 'synthetic-db']:
            assert private not in rendered


@pytest.mark.anyio
async def test_terminal_task_retention_deletes_private_payloads_with_the_same_row(word_repository):
    repository, database = word_repository
    _task, args = await prepare(repository)
    await commit(repository, args)
    await repository.cancel_and_reject(args['scope'], lease=args['lease'])
    async with database.async_engine.begin() as connection:
        await connection.execute(update(repository.tasks).where(
            repository.tasks.c.external_run_id == args['scope'].external_run_id).values(
                completed_at=text("clock_timestamp()-interval '8 days'")))
    await repository.cleanup_expired(lease_owner='synthetic-cleaner')
    assert await repository.get_task(args['scope'].external_run_id) is None
    async with database.async_engine.connect() as connection:
        assert (await connection.execute(select(repository.tasks).where(
            repository.tasks.c.external_run_id == args['scope'].external_run_id))).first() is None
        assert (await connection.execute(select(repository.runs).where(
            repository.runs.c.external_run_id == args['scope'].external_run_id))).first() is None
        assert (await connection.execute(select(repository.instructions).where(
            repository.instructions.c.external_run_id == args['scope'].external_run_id))).first() is None


@pytest.mark.anyio
async def test_word_hard_deadline_survives_task_row_lock_wait(word_repository):
    repository, database = word_repository
    _task, args = await prepare(repository)
    async with database.async_engine.begin() as connection:
        deadline = (await connection.execute(update(repository.tasks).where(
            repository.tasks.c.external_run_id == args['scope'].external_run_id).values(
                deadline_at=text("clock_timestamp()+interval '1 second'"))
                .returning(repository.tasks.c.deadline_at))).scalar_one()
    from smart_reporting.task_execution.repository import TaskExecutionRepositoryError
    from smart_reporting.task_execution.tests.test_native_word_repository import wait_for_pg_block

    pending = None
    try:
        async with database.async_engine.begin() as blocker:
            await blocker.execute(select(repository.tasks.c.external_run_id).where(
                repository.tasks.c.external_run_id == args['scope'].external_run_id).with_for_update())
            pid = (await blocker.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(commit(repository, args))
            await wait_for_pg_block(database, pid)
            async def passed_deadline():
                while True:
                    async with database.async_engine.connect() as connection:
                        current = (await connection.execute(text('SELECT clock_timestamp()'))).scalar_one()
                    if current >= deadline:
                        return
                    await asyncio.sleep(0.01)
            await asyncio.wait_for(passed_deadline(), 5)
        with pytest.raises(TaskExecutionRepositoryError) as rejected:
            await asyncio.wait_for(pending, 5)
        assert rejected.value.code == 'native_word_execution_fenced'
        async with database.async_engine.connect() as connection:
            assert (await connection.execute(select(repository.tasks.c.native_word_candidate_receipt).where(
                repository.tasks.c.external_run_id == args['scope'].external_run_id))).scalar_one() is None
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
