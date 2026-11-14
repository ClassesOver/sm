"""真实PostgreSQL运行/状态行依赖见证，不使用业务批准替身证明行锁。"""

import asyncio
from uuid import uuid4

import pytest
from agno.db.postgres import AsyncPostgresDb
from sqlalchemy import Column, MetaData, String, Table, update
from sqlalchemy.exc import SQLAlchemyError

from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.state import ReportingStateError
from smart_reporting.tests.test_management_persistence import auth_context as auth_context

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def states(auth_context):
    repository = ReportingStateRepository(AsyncPostgresDb(db_engine=auth_context[1].engine))
    run_id = 'read-guard-' + uuid4().hex
    state = await repository.get_or_create(report_run_id=run_id, external_run_id='external-' + run_id,
        thread_id='thread-' + run_id, owner_user_id='fixture-owner', payload={'flag': True})
    return repository, state


async def test_all_four_read_entrypoints_capture_original_rows_and_aliases(states):
    repository, state = states
    async with repository.capture_read_dependencies() as guard:
        first = await repository.get(state.report_run_id)
        first.payload['flag'] = 'local caller mutation'
        assert (await repository.get_by_external_run_id(state.external_run_id)).payload['flag'] is True
        run = await repository.get_run(state.report_run_id)
        run['database'] = 'local caller mutation'
        assert (await repository.get_run_by_external(state.external_run_id))['database'] == 'default'
        assert len(guard.rows) == 2
        await guard.lock()
    assert repository._read_guard.get() is None


@pytest.mark.parametrize('fault', ['missing', 'repeated', 'boolean_number', 'read_error', 'child_task', 'no_reads'])
async def test_incomplete_or_changed_reads_stay_invalid_even_when_caller_handles_failure(states, monkeypatch, fault):
    repository, state = states
    async with repository.capture_read_dependencies() as guard:
        if fault != 'no_reads':
            await repository.get(state.report_run_id)
            await repository.get_run(state.report_run_id)
        if fault == 'missing':
            assert await repository.get('not-registered-' + uuid4().hex) is None
        elif fault in ('repeated', 'boolean_number'):
            async with repository.db.db_engine.begin() as connection:
                await connection.execute(update(repository.states).where(
                    repository.states.c.report_run_id == state.report_run_id).values(payload={'flag': 1}))
            if fault == 'repeated':
                await repository.get(state.report_run_id)
                async with repository.db.db_engine.begin() as connection:
                    await connection.execute(update(repository.states).where(
                        repository.states.c.report_run_id == state.report_run_id).values(payload={'flag': True}))
        elif fault == 'read_error':
            actual = repository.states
            monkeypatch.setattr(repository, 'states', Table('absent_' + uuid4().hex, MetaData(),
                Column('report_run_id', String, primary_key=True)))
            with pytest.raises(SQLAlchemyError):
                await repository.get(state.report_run_id)
            monkeypatch.setattr(repository, 'states', actual)
        elif fault == 'child_task':
            with pytest.raises(ReportingStateError):
                await asyncio.create_task(repository.get(state.report_run_id))
        with pytest.raises(ReportingStateError, match='批准依赖'):
            await guard.lock()
    assert repository._read_guard.get() is None


async def test_sealed_guard_rejects_new_reads_before_acquiring_another_connection(states, monkeypatch):
    repository, state = states
    async with repository.capture_read_dependencies() as guard:
        await repository.get(state.report_run_id)
        await guard.lock()

        def unexpected_connection(*args, **kwargs):
            raise AssertionError('sealed guard must not acquire another connection')

        with monkeypatch.context() as patch:
            patch.setattr(type(repository.db.db_engine), 'connect', unexpected_connection)
            with pytest.raises(ReportingStateError):
                await repository.get(state.report_run_id)


async def test_model_read_failure_cannot_be_swallowed_into_a_complete_guard(states):
    repository, state = states
    async with repository.db.db_engine.begin() as connection:
        await connection.execute(update(repository.states).where(
            repository.states.c.report_run_id == state.report_run_id).values(schema_version=999))
    async with repository.capture_read_dependencies() as guard:
        await repository.get_run(state.report_run_id)
        with pytest.raises(ReportingStateError):
            await repository.get(state.report_run_id)
        with pytest.raises(ReportingStateError):
            await guard.lock()


@pytest.mark.parametrize('target', ['states', 'runs'])
async def test_row_updates_wait_until_guard_releases(states, target):
    repository, state = states
    started = asyncio.Event()
    table = getattr(repository, target)

    async def writer():
        async with repository.db.db_engine.begin() as connection:
            started.set()
            await connection.execute(update(table).where(table.c.report_run_id == state.report_run_id).values(
                **({'payload': {'flag': 'after-release'}} if target == 'states' else {'database': 'after-release'})))

    writing = None
    try:
        async with repository.capture_read_dependencies() as guard:
            await repository.get(state.report_run_id)
            await repository.get_run(state.report_run_id)
            await guard.lock()
            writing = asyncio.create_task(writer())
            await asyncio.wait_for(started.wait(), 5)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(writing), .2)
        await asyncio.wait_for(writing, 5)
    finally:
        if writing is not None:
            await asyncio.gather(writing, return_exceptions=True)
