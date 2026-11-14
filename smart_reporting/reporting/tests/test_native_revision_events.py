"""Durable revision events reuse the real PostgreSQL revision transaction.

SQLite exercises real transaction rollback without concurrency claims. PostgreSQL
requires an explicitly disposable NATIVE_TEST_DATABASE_URL. Neither backend
claims AgentEventLog/SSE or document-object synchronization.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from copy import copy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from smart_reporting.report_editor.native_repository import (
    NativeDocumentRepository,
    NativeRepositoryConflict,
    NativeRepositoryNotFound,
    _metadata,
)
from smart_reporting.reporting.tests.test_native_repository_postgres_integration import (
    completion,
    opened,
    reserve,
)
from smart_reporting.reporting.tests.test_native_repository_postgres_integration import (
    postgres_repositories as postgres_repositories,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(params=['sqlite', 'postgresql'])
def event_repositories(request, tmp_path):
    if request.param == 'postgresql':
        return request.getfixturevalue('postgres_repositories')
    # Production construction still rejects SQLite. Only this SQL/rollback fixture
    # adapts synchronous execution; it does not simulate SQL statements or results.
    @compiles(JSONB, 'sqlite')
    def sqlite_json(_type, _compiler, **_kwargs):
        return 'JSON'

    engine = create_engine(f"sqlite:///{tmp_path / 'revision-events.sqlite'}")
    _metadata.create_all(engine)

    class Adapter:
        @asynccontextmanager
        async def begin(self):
            with engine.begin() as connection:
                yield SimpleNamespace(execute=lambda statement: self.execute(connection, statement))

        connect = begin

        async def execute(self, connection, statement):
            return connection.execute(statement)

    repos = []
    for _ in range(2):
        repo = object.__new__(NativeDocumentRepository)
        repo.engine = Adapter()
        repos.append(repo)
    request.addfinalizer(engine.dispose)
    return repos


async def test_initial_revision_and_rebuild_replay_exactly_once(event_repositories):
    repo, other = event_repositories
    scope, source, doc = await opened(repo)
    initial = await repo.revision_events_after(doc.document_id, scope=scope)
    assert initial['nextSequence'] == initial['latestSequence'] == 1
    assert [(e['revision'], e['status']) for e in initial['events']] == [(1, 'saved')]
    assert await other.create_from_source(source, scope=scope, request_id='open') == doc
    rebuilt = copy(other)  # New repository instance, same durable database.
    assert await rebuilt.revision_events_after(doc.document_id, scope=scope) == initial


async def test_revision_commit_event_atomic_and_retry_idempotent(event_repositories):
    repo, other = event_repositories
    scope, source, doc = await opened(repo)
    reservation = await reserve(repo, doc, scope)
    assert (await repo.revision_events_after(doc.document_id, scope=scope, after=1))['events'] == []
    completed = await repo.complete_revision(reservation, **completion(reservation, source))
    assert await other.complete_revision(reservation, **completion(reservation, source)) == completed
    page = await other.revision_events_after(doc.document_id, scope=scope, after=1)
    assert page['nextSequence'] == page['latestSequence'] == 2
    assert [(e['revision'], e['status']) for e in page['events']] == [(2, 'saved')]


async def test_event_insert_failure_rolls_back_revision_and_sequence(event_repositories, monkeypatch):
    repo, other = event_repositories
    scope, source, doc = await opened(repo)
    reservation = await reserve(repo, doc, scope)
    append = repo._append_revision_event

    async def fail_after_insert(connection, revision):
        await append(connection, revision)
        raise RuntimeError('injected event transaction failure')

    monkeypatch.setattr(repo, '_append_revision_event', fail_after_insert)
    with pytest.raises(RuntimeError, match='injected'):
        await repo.complete_revision(reservation, **completion(reservation, source))
    assert (await other.get_revision(doc.document_id, 2, scope=scope)).status == 'reserved'
    page = await other.revision_events_after(doc.document_id, scope=scope)
    assert page['latestSequence'] == 1 and len(page['events']) == 1


async def test_failed_revision_recovery_appends_but_retries_do_not(event_repositories):
    repo, other = event_repositories
    scope, source, doc = await opened(repo)
    reservation = await reserve(repo, doc, scope)
    await repo.fail_revision(reservation, code='engine_failed')
    await other.fail_revision(reservation, code='engine_failed')
    await other.complete_revision(reservation, **completion(reservation, source))
    page = await repo.revision_events_after(doc.document_id, scope=scope)
    assert [e['status'] for e in page['events']] == ['saved', 'failed', 'saved']
    assert [e['sequence'] for e in page['events']] == [1, 2, 3]
    assert len({e['event_id'] for e in page['events']}) == 3


async def test_commit_order_not_reservation_order_and_page_cursor(event_repositories):
    repo, other = event_repositories
    scope, source, doc = await opened(repo)
    first = await reserve(repo, doc, scope, request_id='first')
    second = await reserve(other, doc, scope, request_id='second')
    await other.complete_revision(second, **completion(second, source))
    await repo.complete_revision(first, **completion(first, source))
    page = await repo.revision_events_after(doc.document_id, scope=scope, after=1, limit=1)
    assert page['events'][0]['revision'] == 3
    assert page['nextSequence'] == 2 and page['latestSequence'] == 3
    last = await other.revision_events_after(doc.document_id, scope=scope, after=page['nextSequence'])
    assert last['events'][0]['revision'] == 2
    assert last['nextSequence'] == 3


@pytest.mark.parametrize('field', ['database', 'company_id', 'user_id', 'thread_id'])
async def test_event_replay_rechecks_complete_scope(event_repositories, field):
    repo, _ = event_repositories
    scope, _, doc = await opened(repo)
    with pytest.raises(NativeRepositoryNotFound):
        await repo.revision_events_after(doc.document_id, scope=scope.model_copy(update={field: 'foreign'}))


async def test_cursor_validation_and_legacy_schema_upgrade(event_repositories, request):
    repo, _ = event_repositories
    scope, _, doc = await opened(repo)
    for after, limit in [(-1, 100), (True, 100), (0, 0), (0, 1001), (0, True)]:
        with pytest.raises(ValueError):
            await repo.revision_events_after(doc.document_id, scope=scope, after=after, limit=limit)
    with pytest.raises(NativeRepositoryConflict):
        await repo.revision_events_after(doc.document_id, scope=scope, after=2)
    if request.node.callspec.params['event_repositories'] == 'sqlite':
        return  # PostgreSQL ALTER migration is covered by the opt-in backend.
    # Model a legacy document with no event counter and no historical event rows.
    async with repo.engine.begin() as connection:
        await connection.execute(text('DELETE FROM report_native_revision_events_v1'))
        await connection.execute(text('ALTER TABLE report_native_documents_v1 DROP COLUMN event_sequence'))
    await repo.create_schema()
    await repo.create_schema()
    page = await repo.revision_events_after(doc.document_id, scope=scope)
    assert page == {'events': [], 'nextSequence': 0, 'latestSequence': 0}
    assert (await repo.get_revision(doc.document_id, 1, scope=scope)).status == 'saved'


async def test_initial_event_failure_does_not_leave_document(event_repositories, monkeypatch):
    from sqlalchemy import func, select

    from smart_reporting.report_editor.native_repository import _documents, _events, _revisions

    repo, _ = event_repositories
    append = repo._append_revision_event

    async def fail_after_insert(connection, revision):
        await append(connection, revision)
        raise RuntimeError('injected initial event failure')

    monkeypatch.setattr(repo, '_append_revision_event', fail_after_insert)
    with pytest.raises(RuntimeError, match='injected'):
        await opened(repo)
    async with repo.engine.connect() as connection:
        for table in (_documents, _revisions, _events):
            assert (await connection.execute(select(func.count()).select_from(table))).scalar_one() == 0


async def test_postgres_concurrent_completions_have_distinct_commit_sequence(event_repositories, request):
    import asyncio

    if request.node.callspec.params['event_repositories'] == 'sqlite':
        pytest.skip('SQLite adapter is not a two-connection concurrency proof')
    repo, other = event_repositories
    scope, source, doc = await opened(repo)
    first = await reserve(repo, doc, scope, request_id='one')
    second = await reserve(other, doc, scope, request_id='two')
    await asyncio.gather(
        repo.complete_revision(first, **completion(first, source)),
        other.complete_revision(second, **completion(second, source)),
    )
    page = await repo.revision_events_after(doc.document_id, scope=scope, after=1)
    assert [event['sequence'] for event in page['events']] == [2, 3]
    assert {event['revision'] for event in page['events']} == {2, 3}
