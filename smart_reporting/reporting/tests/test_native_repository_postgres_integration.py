"""Opt-in repository acceptance against an explicitly isolated PostgreSQL instance."""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.report_editor.native_models import (
    NativeArtifacts,
    NativeEditorContext,
    NativeScope,
    NativeSource,
    NativeValidation,
)
from smart_reporting.report_editor.native_repository import (
    NativeDocumentRepository,
    NativeRepositoryConflict,
    NativeRepositoryNotFound,
)

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def postgres_repositories():
    # No fallback to application/user database configuration is permitted.
    dsn = os.environ.get("NATIVE_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("Set NATIVE_TEST_DATABASE_URL to a disposable PostgreSQL instance")
    url = make_url(dsn)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Acceptance requires the async psycopg PostgreSQL driver")
    schema = "native_acceptance_" + uuid4().hex
    admin = create_async_engine(url)
    engines = [
        create_async_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        for _ in range(2)
    ]
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        repositories = [NativeDocumentRepository(engine) for engine in engines]
        await repositories[0].create_schema()
        yield repositories
    finally:
        for engine in engines:
            await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def opened(repo):
    scope = NativeScope(database="acceptance", company_id="company", user_id="user", thread_id="t")
    source = NativeSource(
        format="docx", origin="upload",
        source_file={"path": "acceptance/source.docx", "size": 5, "sha256": "a" * 64,
                     "mediaType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    )
    doc = await repo.create_from_source(source, scope=scope, request_id="open")
    return scope, source, doc


async def reserve(repo, doc, scope, request_id="edit", **changes):
    values = dict(parent_revision=1, request_id=request_id, request_sha256="b" * 64,
                  scope=scope, note="acceptance")
    values.update(changes)
    return await repo.reserve_revision(doc.document_id, **values)


def completion(reservation, source):
    return dict(
        context=NativeEditorContext(
            document_id=reservation.document_id, revision=reservation.revision,
            parent_revision=reservation.parent_revision, scope=reservation.scope,
            format=source.format, origin=source.origin, source_file=source.source_file,
        ),
        artifacts=NativeArtifacts(word=source.source_file),
        validation=NativeValidation(ok=False),
    )


async def database_state(repo, document_id):
    async with repo.engine.connect() as connection:
        row = (await connection.execute(text(
            "SELECT next_revision, (SELECT count(*) FROM report_native_revisions_v1 r "
            "WHERE r.document_id = d.document_id) AS revisions "
            "FROM report_native_documents_v1 d WHERE document_id = :id"
        ), {"id": document_id})).one()
    return tuple(row)


async def simultaneously(calls):
    barrier = asyncio.Barrier(len(calls))

    async def invoke(call):
        await barrier.wait()
        return await call()

    return await asyncio.wait_for(asyncio.gather(*(invoke(call) for call in calls)), timeout=30)


async def test_same_request_competition_commits_one_row_and_one_counter_increment(postgres_repositories):
    repo, other = postgres_repositories
    scope, source, doc = await opened(repo)
    attempts = await simultaneously([
        lambda i=i: reserve(postgres_repositories[i % 2], doc, scope) for i in range(16)
    ])
    assert all(item == attempts[0] for item in attempts)
    assert attempts[0].revision == 2
    assert await database_state(other, doc.document_id) == (3, 2)
    saved = await other.complete_revision(attempts[0], **completion(attempts[0], source))
    assert await reserve(repo, doc, scope) == saved
    assert await database_state(repo, doc.document_id) == (3, 2)


async def test_distinct_requests_commit_gapless_unique_revisions_across_connections(postgres_repositories):
    repo, other = postgres_repositories
    scope, _, doc = await opened(repo)
    attempts = await simultaneously([
        lambda i=i: reserve(postgres_repositories[i % 2], doc, scope, f"edit-{i}")
        for i in range(16)
    ])
    assert sorted(item.revision for item in attempts) == list(range(2, 18))
    assert {item.request_id for item in attempts} == {f"edit-{i}" for i in range(16)}
    assert await database_state(other, doc.document_id) == (18, 17)
    for item in attempts:
        assert await other.get_revision(doc.document_id, item.revision, scope=scope) == item


async def test_each_scope_dimension_blocks_reads_reserve_complete_and_fail(postgres_repositories):
    repo, other = postgres_repositories
    scope, source, doc = await opened(repo)
    reservation = await reserve(repo, doc, scope)
    for field in ("database", "company_id", "user_id", "thread_id"):
        foreign = scope.model_copy(update={field: "foreign"})
        assert await other.get_document(doc.document_id, scope=foreign) is None
        assert await other.get_revision(doc.document_id, 2, scope=foreign) is None
        with pytest.raises(NativeRepositoryNotFound):
            await reserve(other, doc, foreign)
        forged = reservation.model_copy(update={"scope": foreign})
        with pytest.raises(NativeRepositoryNotFound):
            await other.complete_revision(forged, **completion(forged, source))
        with pytest.raises(NativeRepositoryNotFound):
            await other.fail_revision(forged, code="foreign_failure")
    assert await other.get_revision(doc.document_id, 2, scope=scope) == reservation
    assert await database_state(repo, doc.document_id) == (3, 2)


async def test_conflicts_leave_reservation_and_counter_unchanged(postgres_repositories):
    repo, other = postgres_repositories
    scope, source, doc = await opened(repo)
    reservation = await reserve(repo, doc, scope)
    for changes in ({"request_sha256": "c" * 64}, {"parent_revision": 99}, {"note": "changed"}):
        with pytest.raises(NativeRepositoryConflict):
            await reserve(other, doc, scope, **changes)
    for changes in ({"request_sha256": "c" * 64}, {"parent_revision": 99}, {"note": "changed"}):
        forged = reservation.model_copy(update=changes)
        with pytest.raises(NativeRepositoryConflict):
            await other.complete_revision(forged, **completion(reservation, source))
    values = completion(reservation, source)
    with pytest.raises(NativeRepositoryConflict):
        await other.complete_revision(reservation, **{**values, "artifacts": NativeArtifacts()})
    with pytest.raises(NativeRepositoryNotFound):
        await reserve(other, doc, scope, "missing-parent", parent_revision=99)
    with pytest.raises(NativeRepositoryConflict):
        await reserve(other, doc, scope, "unsaved-parent", parent_revision=2)
    assert await other.get_revision(doc.document_id, 2, scope=scope) == reservation
    assert await database_state(repo, doc.document_id) == (3, 2)
    assert (await reserve(other, doc, scope, "after-rejection")).revision == 3


async def test_failed_retry_recovers_same_row_and_saved_payload_is_immutable(postgres_repositories):
    repo, other = postgres_repositories
    scope, source, doc = await opened(repo)
    reservation = await reserve(repo, doc, scope)
    failed = await repo.fail_revision(reservation, code="engine_timeout")
    assert await other.fail_revision(reservation, code="engine_timeout") == failed
    assert await reserve(other, doc, scope) == failed
    with pytest.raises(NativeRepositoryConflict):
        await other.fail_revision(reservation, code="different_failure")
    with pytest.raises(NativeRepositoryConflict):
        await reserve(other, doc, scope, "failed-parent", parent_revision=2)
    values = completion(reservation, source)
    saved = await other.complete_revision(reservation, **values)
    assert saved.status == "saved" and saved.failure_code is None
    assert saved.validation.ok is False
    assert await repo.complete_revision(reservation, **values) == saved
    with pytest.raises(NativeRepositoryConflict):
        await repo.complete_revision(reservation, **{**values, "validation": NativeValidation(ok=True)})
    changed_file = source.source_file.model_copy(update={"sha256": "f" * 64})
    with pytest.raises(NativeRepositoryConflict):
        await repo.complete_revision(reservation, **{
            **values, "context": values["context"].model_copy(update={"source_file": changed_file}),
            "artifacts": NativeArtifacts(word=changed_file),
        })
    with pytest.raises(NativeRepositoryConflict):
        await repo.fail_revision(reservation, code="late_failure")
    assert await other.get_revision(doc.document_id, 2, scope=scope) == saved
    assert await database_state(repo, doc.document_id) == (3, 2)
    assert (await reserve(repo, doc, scope, "recovered-parent", parent_revision=2)).revision == 3


@pytest.mark.parametrize("format", ["docx", "pdf", "xlsx", "pptx"])
async def test_http_ribbon_roundtrip_persists_real_postgres(
    postgres_repositories, monkeypatch, tmp_path, format,
):
    from smart_reporting.reporting.tests import test_native_ribbon_http_roundtrip as http_acceptance

    repo, other = postgres_repositories
    # Reuse the HTTP/file acceptance unchanged, replacing only its native repository.
    # Artifact and editor grant repositories retain that acceptance's test doubles.
    monkeypatch.setattr(http_acceptance, "Repository", lambda: repo)
    await http_acceptance.test_ribbon_operations_use_real_http_save_download_and_reopen(tmp_path, format)
    async with other.engine.connect() as connection:
        documents = (await connection.execute(text(
            "SELECT document_id, database, company_id, user_id, thread_id, format, "
            "next_revision FROM report_native_documents_v1"
        ))).mappings().all()
        rows = (await connection.execute(text(
            "SELECT revision, status, validation FROM report_native_revisions_v1 ORDER BY revision"
        ))).mappings().all()
    assert len(documents) == 1
    document = documents[0]
    assert document["format"] == format and document["next_revision"] == 3
    assert [(row["revision"], row["status"]) for row in rows] == [(1, "saved"), (2, "saved")]
    assert rows[1]["validation"]["ok"] is False
    assert "native_validation_failed" in {
        issue["code"] for issue in rows[1]["validation"]["issues"]
    }
    scope = NativeScope(**{field: document[field] for field in (
        "database", "company_id", "user_id", "thread_id",
    )})
    stored_document = await other.get_document(document["document_id"], scope=scope)
    stored_revision = await other.get_revision(document["document_id"], 2, scope=scope)
    assert stored_document.source.format == format and stored_document.next_revision == 3
    assert stored_revision.status == "saved" and stored_revision.parent_revision == 1
    assert stored_revision.request_id == f"ribbon-save-{format}"
    assert stored_revision.context.scope == scope
    assert stored_revision.validation.ok is False
