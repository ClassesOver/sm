"""Destructive isolated PostgreSQL tests for private Word binding and candidate CAS."""
import asyncio
import hashlib
import os
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution.models import (
    AttemptOutcome,
    TaskExecutionScope,
    TaskState,
)
from smart_reporting.task_execution.native_word_contracts import word_finish_reference
from smart_reporting.task_execution.repository import (
    TaskExecutionRepository,
    TaskExecutionRepositoryError,
)
from smart_reporting.task_execution.tests.test_native_word_contracts import word_input

pytestmark = pytest.mark.integration
INSTRUCTION = 'synthetic instruction'
PROPOSAL = {'summary': 'Synthetic candidate', 'operations': [{'kind': 'replaceParagraph',
    'arguments': {'blockId': 'p1', 'text': 'Synthetic replacement'}}]}


@pytest.fixture
async def word_repository():
    url = os.getenv('REPORTING_TEST_DB_URL', '').strip()
    if not url:
        pytest.skip('REPORTING_TEST_DB_URL must point to a disposable PostgreSQL database')
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


async def prepare(repository, task_id='word-task', *, ttl=timedelta(minutes=1)):
    scope = TaskExecutionScope(task_id, 'user', 'thread', 'synthetic-workspace', 'native-word-candidate')
    payload = word_input(task_id)
    payload['instructionSha256'] = hashlib.sha256(INSTRUCTION.encode()).hexdigest()
    task = await repository.create_native_word_task(scope, INSTRUCTION, payload)
    lease = await repository.claim_lease(task_id, 'worker-a', ttl=ttl)
    task, attempt = await repository.open_initial(task_id, lease, task.state_version)
    async with repository.db.db_engine.connect() as connection:
        digest = (await connection.execute(select(repository.tasks.c.native_word_input_sha256)
                  .where(repository.tasks.c.external_run_id == task_id))).scalar_one()
    args = dict(scope=scope, lease=lease, internal_run_id=attempt.internal_run_id, attempt_no=attempt.attempt_no,
                expected_input_sha256=digest, native_scope=payload['binding']['scope'])
    return task, args


async def commit(repository, args, proposal=PROPOSAL, registered=None):
    return await repository.commit_native_word_candidate(**args, proposal=proposal,
                registered_proposal=proposal if registered is None else registered)


@pytest.mark.anyio
async def test_native_word_input_is_atomic_immutable_private_and_idempotent(word_repository):
    repository, _database = word_repository
    task, args = await prepare(repository)
    private = await repository.read_native_word_input(**args)
    assert private['selectedParagraphs'][0]['text'] == 'Synthetic paragraph'
    assert not hasattr(task, 'native_word_input')
    assert 'Synthetic paragraph' not in repr(task)
    payload = word_input()
    payload['instructionSha256'] = hashlib.sha256(INSTRUCTION.encode()).hexdigest()
    await repository.create_native_word_task(args['scope'], INSTRUCTION, payload)
    payload['binding']['documentId'] = 'other-document'
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.create_native_word_task(args['scope'], INSTRUCTION, payload)


@pytest.mark.anyio
async def test_native_word_concurrent_commit_exact_retry_and_mismatch(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    receipts = await asyncio.gather(commit(repository, args), commit(repository, args))
    assert receipts[0] == receipts[1]
    assert receipts[0]['originCommit']['leaseOwner'] == 'worker-a'
    assert await commit(repository, args) == receipts[0]
    other = {'summary': 'Other candidate', 'operations': PROPOSAL['operations']}
    with pytest.raises(TaskExecutionRepositoryError, match='conflict'):
        await commit(repository, args, other)
    with pytest.raises(TaskExecutionRepositoryError, match='registered'):
        await commit(repository, args, PROPOSAL, other)


@pytest.mark.anyio
async def test_native_word_foreign_scope_digest_attempt_and_unregistered_target_rejected(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    for field, value in [('expected_input_sha256', '0' * 64), ('attempt_no', 99),
                         ('internal_run_id', 'other-run'),
                         ('native_scope', {**args['native_scope'], 'companyId': 'other-company'})]:
        with pytest.raises(TaskExecutionRepositoryError):
            await commit(repository, {**args, field: value})
    foreign = {'summary': 'outside', 'operations': [{'kind': 'replaceParagraph',
               'arguments': {'blockId': 'foreign', 'text': 'bad'}}]}
    with pytest.raises((TaskExecutionRepositoryError, ValueError)):
        await commit(repository, args, foreign)


@pytest.mark.anyio
async def test_native_word_lease_takeover_blocks_old_retry_but_new_claim_recovers_origin(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    receipt = await commit(repository, args)
    await repository.release_lease(args['scope'].external_run_id, args['lease'].owner)
    new_lease = await repository.claim_lease(args['scope'].external_run_id, 'worker-b')
    snapshot = await repository.get_task_snapshot(args['scope'].external_run_id)
    snapshot, _attempt = await repository.resume_current(args['scope'].external_run_id, new_lease, snapshot.state_version)
    with pytest.raises(TaskExecutionRepositoryError):
        await commit(repository, args)
    recovered = await repository.recover_native_word_candidate(**{**args, 'lease': new_lease})
    assert recovered == receipt
    assert recovered['originCommit']['leaseEpoch'] != new_lease.epoch


@pytest.mark.anyio
async def test_native_word_new_attempt_recovers_without_replacing_origin(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    receipt = await commit(repository, args)
    task = await repository.get_task_snapshot(args['scope'].external_run_id)
    snapshot = await repository.close_and_decide(args['scope'].external_run_id, args['lease'], task.state_version,
                            outcome=AttemptOutcome.NO_FINISH, agno_status=None, create_next=True)
    snapshot, attempt = await repository.resume_current(args['scope'].external_run_id, args['lease'], snapshot.state_version)
    recovered = await repository.recover_native_word_candidate(**{**args,
                'internal_run_id': attempt.internal_run_id, 'attempt_no': attempt.attempt_no})
    assert recovered == receipt
    assert recovered['originCommit']['attemptNo'] == 0


@pytest.mark.anyio
async def test_native_word_lock_wait_uses_fresh_database_time(word_repository):
    repository, database = word_repository
    _task, args = await prepare(repository, ttl=timedelta(milliseconds=300))
    async with database.async_engine.begin() as connection:
        await connection.execute(select(repository.tasks).where(
            repository.tasks.c.external_run_id == args['scope'].external_run_id).with_for_update())
        pending = asyncio.create_task(commit(repository, args))
        await asyncio.sleep(0.45)
    with pytest.raises(TaskExecutionRepositoryError):
        await pending


@pytest.mark.anyio
async def test_native_word_cancelled_task_never_exposes_committed_candidate(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    await commit(repository, args)
    await repository.cancel_and_reject(args['scope'], lease=args['lease'])
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.recover_native_word_candidate(**args)
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.get_completed_native_word_candidate(args['scope'],
            expected_input_sha256=args['expected_input_sha256'], native_scope=args['native_scope'])


@pytest.mark.anyio
async def test_native_word_completed_receipt_ignores_expired_old_lease_but_not_scope(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    receipt = await commit(repository, args)
    task = await repository.get_task_snapshot(args['scope'].external_run_id)
    finishing = await repository.request_finish(args['scope'].external_run_id, args['lease'], task.state_version,
            word_finish_reference(receipt), result_text='Candidate ready; not accepted',
            retained_execution_ids=[])
    await repository.finalize_finish(args['scope'].external_run_id, args['lease'], finishing.state_version, agno_status='COMPLETED')
    current = await repository.cancel_and_reject(args['scope'])
    assert current.state is TaskState.COMPLETED
    assert await repository.get_completed_native_word_candidate(args['scope'],
        expected_input_sha256=args['expected_input_sha256'], native_scope=args['native_scope']) == receipt
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.get_completed_native_word_candidate(args['scope'],
            expected_input_sha256=args['expected_input_sha256'], native_scope={**args['native_scope'], 'database': 'other'})


@pytest.mark.anyio
async def test_native_word_column_pair_constraints_and_legacy_null_task(word_repository):
    repository, database = word_repository
    scope = TaskExecutionScope('legacy', 'user', 'thread', 'synthetic-workspace', 'native-word-candidate')
    task = await repository.create_task_with_initial_attempt(scope, INSTRUCTION)
    lease = await repository.claim_lease('legacy', 'worker')
    task, attempt = await repository.open_initial('legacy', lease, task.state_version)
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.read_native_word_input(scope=scope, lease=lease, internal_run_id=attempt.internal_run_id,
            attempt_no=0, expected_input_sha256='0' * 64, native_scope=word_input()['binding']['scope'])
    with pytest.raises(IntegrityError):
        async with database.async_engine.begin() as connection:
            await connection.execute(update(repository.tasks).where(repository.tasks.c.external_run_id == 'legacy')
                .values(native_word_input_sha256='a' * 64))
    async with database.async_engine.connect() as connection:
        columns = await connection.run_sync(lambda sync: {column['name'] for column in
            inspect(sync).get_columns(repository.tasks.name, schema=repository.metadata.schema)})
    assert {'native_word_input', 'native_word_input_sha256', 'native_word_candidate_receipt',
            'native_word_candidate_sha256'} <= columns


@pytest.mark.anyio
async def test_native_word_finishing_new_owner_recovers_history_without_run_epoch_rewrite(word_repository):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    receipt = await commit(repository, args)
    task = await repository.get_task_snapshot(args['scope'].external_run_id)
    finishing = await repository.request_finish(args['scope'].external_run_id, args['lease'], task.state_version,
        word_finish_reference(receipt), result_text='Candidate ready', retained_execution_ids=[])
    await repository.release_lease(args['scope'].external_run_id, args['lease'].owner)
    new_lease = await repository.claim_lease(args['scope'].external_run_id, 'finishing-worker')
    assert await repository.recover_native_word_candidate(**{**args, 'lease': new_lease}) == receipt
    with pytest.raises(TaskExecutionRepositoryError):
        await commit(repository, {**args, 'lease': new_lease})
    await repository.finalize_finish(args['scope'].external_run_id, new_lease, finishing.state_version, agno_status='COMPLETED')


@pytest.mark.anyio
async def test_native_word_commit_rollback_leaves_no_receipt(word_repository):
    from sqlalchemy import event

    repository, database = word_repository
    _task, args = await prepare(repository)
    def crash_after_write(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith('UPDATE') and 'native_word_candidate_receipt=' in statement:
            raise RuntimeError('synthetic crash after update before transaction commit')
    event.listen(database.async_engine.sync_engine, 'after_cursor_execute', crash_after_write)
    try:
        with pytest.raises(RuntimeError, match='synthetic crash'):
            await commit(repository, args)
    finally:
        event.remove(database.async_engine.sync_engine, 'after_cursor_execute', crash_after_write)
    assert await repository.recover_native_word_candidate(**args) is None
    assert (await commit(repository, args))['proposal']['summary'] == 'Synthetic candidate'


@pytest.mark.anyio
async def test_native_word_corruption_and_new_instruction_cannot_reinterpret_receipt(word_repository):
    repository, database = word_repository
    _task, args = await prepare(repository)
    await commit(repository, args)
    await repository.submit_instruction(args['scope'], 'new-request', 'Changed goal; requires successor')
    with pytest.raises(TaskExecutionRepositoryError):
        await repository.recover_native_word_candidate(**args)
    # Raw SQL corruption simulates storage damage, never a supported mutation API.
    async with database.async_engine.begin() as connection:
        await connection.execute(update(repository.tasks).where(repository.tasks.c.external_run_id == 'word-task')
            .values(instruction_sequence=1, native_word_candidate_sha256='0' * 64))
    with pytest.raises(TaskExecutionRepositoryError, match='receipt_invalid'):
        await repository.recover_native_word_candidate(**args)


@pytest.mark.anyio
async def test_native_word_migration_preserves_legacy_null_row_and_serializes_initializers(word_repository):
    repository, database = word_repository
    scope = TaskExecutionScope('old-schema-task', 'user', 'thread', 'workspace', 'legacy')
    await repository.create_task_with_initial_attempt(scope, INSTRUCTION)
    async with database.async_engine.begin() as connection:
        await connection.execute(text('ALTER TABLE agentos_coding.agentos_coding_tasks '
            'DROP COLUMN native_word_input, DROP COLUMN native_word_input_sha256, '
            'DROP COLUMN native_word_candidate_receipt, DROP COLUMN native_word_candidate_sha256'))
        await connection.execute(text("UPDATE agentos_coding.agentos_coding_schema_versions SET version='2.1.0'"))
    first = TaskExecutionRepository(database.async_db)
    second = TaskExecutionRepository(database.async_db)
    await asyncio.gather(first.initialize(), second.initialize())
    assert (await first.get_task_snapshot('old-schema-task')).scope == scope
    async with database.async_engine.connect() as connection:
        row = (await connection.execute(select(first.tasks.c.native_word_input,
            first.tasks.c.native_word_input_sha256, first.tasks.c.native_word_candidate_receipt,
            first.tasks.c.native_word_candidate_sha256).where(first.tasks.c.external_run_id == 'old-schema-task'))).one()
        assert tuple(row) == (None, None, None, None)
        checks = await connection.run_sync(lambda sync: {item['name'] for item in inspect(sync)
            .get_check_constraints(first.tasks.name, schema=first.metadata.schema)})
    assert {'ck_coding_tasks_word_input_pair', 'ck_coding_tasks_word_receipt_pair',
            'ck_coding_tasks_word_receipt_input'} <= checks


@pytest.mark.anyio
@pytest.mark.parametrize('finish', [{}, {'nativeWordReceiptVersion': 1,
    'nativeWordCandidateSha256': '0' * 64, 'nativeWordInputSha256': '0' * 64}])
async def test_native_word_wrong_or_missing_finish_pointer_rejected(word_repository, finish):
    repository, _database = word_repository
    _task, args = await prepare(repository)
    await commit(repository, args)
    task = await repository.get_task_snapshot(args['scope'].external_run_id)
    finishing = await repository.request_finish(args['scope'].external_run_id, args['lease'], task.state_version,
        finish, result_text='Not proven', retained_execution_ids=[])
    with pytest.raises(TaskExecutionRepositoryError, match='finish_reference'):
        await repository.recover_native_word_candidate(**args)
    await repository.finalize_finish(args['scope'].external_run_id, args['lease'], finishing.state_version, agno_status='COMPLETED')
    with pytest.raises(TaskExecutionRepositoryError, match='finish_reference'):
        await repository.get_completed_native_word_candidate(args['scope'],
            expected_input_sha256=args['expected_input_sha256'], native_scope=args['native_scope'])


@pytest.mark.anyio
async def test_native_word_legacy_completion_does_not_prove_candidate_completion(word_repository):
    repository, database = word_repository
    _task, args = await prepare(repository)
    receipt = await commit(repository, args)
    task = await repository.get_task_snapshot(args['scope'].external_run_id)
    suspended = await repository.close_and_decide(args['scope'].external_run_id, args['lease'], task.state_version,
        outcome=AttemptOutcome.NO_FINISH, agno_status=None, create_next=False)
    await repository.complete_task(args['scope'].external_run_id,
        expected_mutation_sequence=suspended.mutation_sequence, expected_lease_owner=args['lease'].owner,
        result_text='Legacy finish cannot authorize Word', finish_payload={}, retained_execution_ids=[])
    with pytest.raises(TaskExecutionRepositoryError, match='finish_reference'):
        await repository.get_completed_native_word_candidate(args['scope'],
            expected_input_sha256=args['expected_input_sha256'], native_scope=args['native_scope'])
    # Even a matching pointer alone is insufficient without CLOSED/FINISH_ACCEPTED.
    async with database.async_engine.begin() as connection:
        await connection.execute(update(repository.tasks).where(repository.tasks.c.external_run_id == 'word-task')
            .values(finish_receipt=word_finish_reference(receipt)))
    with pytest.raises(TaskExecutionRepositoryError, match='completion_unproven'):
        await repository.get_completed_native_word_candidate(args['scope'],
            expected_input_sha256=args['expected_input_sha256'], native_scope=args['native_scope'])


async def wait_for_pg_block(database, blocker_pid):
    async def observe():
        while True:
            async with database.async_engine.connect() as connection:
                blocked = (await connection.execute(text('SELECT count(*) FROM pg_stat_activity '
                    "WHERE datname=current_database() AND wait_event_type='Lock' "
                    'AND :blocker = ANY(pg_blocking_pids(pid))'), {'blocker': blocker_pid})).scalar_one()
            if blocked:
                return
            await asyncio.sleep(0.01)
    await asyncio.wait_for(observe(), timeout=5)


def pause_first_word_lock(repository, monkeypatch):
    ready, release = asyncio.Event(), asyncio.Event()
    state = {}
    original = repository._word_current
    async def paused(connection, **kwargs):
        result = await original(connection, **kwargs)
        if not ready.is_set():
            state['pid'] = (await connection.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            ready.set()
            await release.wait()
        return result
    monkeypatch.setattr(repository, '_word_current', paused)
    return ready, release, state


@pytest.mark.anyio
async def test_native_word_different_proposals_race_has_one_immutable_winner(word_repository, monkeypatch):
    repository, database = word_repository
    _task, args = await prepare(repository)
    ready, release, state = pause_first_word_lock(repository, monkeypatch)
    first = asyncio.create_task(commit(repository, args))
    actors = [first]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        different = {'summary': 'Second concurrent candidate', 'operations': PROPOSAL['operations']}
        second = asyncio.create_task(commit(repository, args, different))
        actors.append(second)
        await wait_for_pg_block(database, state['pid'])
        release.set()
        receipts = await asyncio.gather(*actors, return_exceptions=True)
        assert isinstance(receipts[0], dict)
        assert isinstance(receipts[1], TaskExecutionRepositoryError)
        assert receipts[1].code == 'native_word_candidate_conflict'
        assert await repository.recover_native_word_candidate(**args) == receipts[0]
    finally:
        release.set()
        await asyncio.gather(*actors, return_exceptions=True)


@pytest.mark.anyio
async def test_native_word_cancel_race_detects_conflict_then_explicit_retry_cancels(word_repository, monkeypatch):
    repository, database = word_repository
    _task, args = await prepare(repository)
    ready, release, state = pause_first_word_lock(repository, monkeypatch)
    first = asyncio.create_task(commit(repository, args))
    actors = [first]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        cancellation = asyncio.create_task(repository.cancel_and_reject(args['scope'], lease=args['lease']))
        actors.append(cancellation)
        await wait_for_pg_block(database, state['pid'])
        release.set()
        results = await asyncio.gather(*actors, return_exceptions=True)
        assert isinstance(results[0], dict)
        assert isinstance(results[1], TaskExecutionRepositoryError)
        cancelled = await repository.cancel_and_reject(args['scope'], lease=args['lease'])
        assert cancelled.state is TaskState.CANCELLED
        with pytest.raises(TaskExecutionRepositoryError):
            await repository.recover_native_word_candidate(**args)
    finally:
        release.set()
        await asyncio.gather(*actors, return_exceptions=True)


@pytest.mark.anyio
async def test_native_word_expiry_and_takeover_race_fences_prevalidated_old_commit(word_repository, monkeypatch):
    repository, database = word_repository
    _task, args = await prepare(repository)
    ready, release, state = pause_first_word_lock(repository, monkeypatch)
    # Shorten persisted lease before validation; Lease DTO's timestamp is not trusted.
    async with database.async_engine.begin() as connection:
        await connection.execute(text("UPDATE agentos_coding.agentos_coding_tasks "
            "SET lease_expires_at=clock_timestamp()+interval '300 milliseconds' WHERE external_run_id='word-task'"))
    first = asyncio.create_task(commit(repository, args))
    actors = [first]
    try:
        await asyncio.wait_for(ready.wait(), 5)
        async def expired_in_database():
            while True:
                async with database.async_engine.connect() as connection:
                    expired = (await connection.execute(text('SELECT lease_expires_at <= clock_timestamp() '
                        "FROM agentos_coding.agentos_coding_tasks WHERE external_run_id='word-task'"))).scalar_one()
                if expired:
                    return
                await asyncio.sleep(0.01)
        await asyncio.wait_for(expired_in_database(), 5)
        takeover = asyncio.create_task(repository.claim_lease('word-task', 'worker-b'))
        actors.append(takeover)
        await wait_for_pg_block(database, state['pid'])
        release.set()
        results = await asyncio.gather(*actors, return_exceptions=True)
        assert isinstance(results[0], TaskExecutionRepositoryError)
        new_lease = results[1]
        assert new_lease.owner == 'worker-b' and new_lease.epoch > args['lease'].epoch
        snapshot = await repository.get_task_snapshot('word-task')
        await repository.resume_current('word-task', new_lease, snapshot.state_version)
        assert await repository.recover_native_word_candidate(**{**args, 'lease': new_lease}) is None
    finally:
        release.set()
        await asyncio.gather(*actors, return_exceptions=True)


@pytest.mark.anyio
async def test_native_word_waiting_commit_uses_registered_snapshot_not_mutated_caller_dict(word_repository):
    repository, database = word_repository
    _task, args = await prepare(repository)
    proposal = deepcopy(PROPOSAL)
    registered = deepcopy(PROPOSAL)
    pending = None
    try:
        async with database.async_engine.begin() as connection:
            await connection.execute(select(repository.tasks).where(
                repository.tasks.c.external_run_id == 'word-task').with_for_update())
            blocker = (await connection.execute(text('SELECT pg_backend_pid()'))).scalar_one()
            pending = asyncio.create_task(commit(repository, args, proposal, registered))
            await wait_for_pg_block(database, blocker)
            # The real commit has passed its preflight and is waiting on the DB row.
            # Mutation of caller-owned memory must never change the registered edit.
            proposal['operations'][0]['arguments']['text'] = 'Caller changed while waiting'
        receipt = await pending
        assert receipt['proposal']['operations'][0]['arguments']['text'] == 'Synthetic replacement'
        recovered = await repository.recover_native_word_candidate(**args)
        assert recovered['proposal']['operations'][0]['arguments']['text'] == 'Synthetic replacement'
    finally:
        if pending is not None:
            await asyncio.gather(pending, return_exceptions=True)
