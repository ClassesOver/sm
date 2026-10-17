"""Exercise cleanup's SQL selection without requiring a PostgreSQL server."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, insert, select

from smart_reporting.reporting.delivery import publishing as p


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["pdf", "word"])
async def test_cleanup_skips_active_files_before_applying_batch_limit(monkeypatch, kind):
    engine = create_engine("sqlite://")
    p._metadata.create_all(engine)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    scope = dict(database_name="db", user_id="user", company_id="company",
                 session_id="session", thread_id="thread", workflow_run_id="run")

    def artifact(key):
        return dict(scope, artifact_key=key, report_id=key, revision=1, artifact=kind,
                    path=f"report.{kind}", size=1, sha256="a" * 64,
                    created_at=now - timedelta(days=3))

    def grant(key, **overrides):
        return {
            **scope, "grant_hash": key, "report_id": key, "revision": 1,
            "pdf_path": "report.pdf", "pdf_size": 1, "pdf_sha256": "a" * 64,
            "word_path": "report.word", "word_size": 1, "word_sha256": "a" * 64,
            "expires_at": now + timedelta(days=10), **overrides,
        }

    with engine.begin() as connection:
        for index in range(p.REPORT_ARTIFACT_CLEANUP_BATCH):
            key = f"protected-{index}"
            connection.execute(insert(p.report_artifact_files_v1).values(**artifact(key)))
            connection.execute(insert(p.report_download_grants_v2).values(**grant(key)))
        for index in range(p.REPORT_ARTIFACT_CLEANUP_BATCH + 1):
            key = f"orphan-{index}"
            values = artifact(key)
            values["created_at"] = now - timedelta(days=2)
            connection.execute(insert(p.report_artifact_files_v1).values(**values))
            connection.execute(insert(p.report_artifact_chunks_v1).values(
                artifact_key=key, chunk_index=0, content=b"x"))
        young = artifact("young")
        young["created_at"] = now
        connection.execute(insert(p.report_artifact_files_v1).values(**young))

    class Connection:
        def __init__(self, connection):
            self.connection = connection

        async def execute(self, statement):
            return self.connection.execute(statement)

    class Engine:
        @asynccontextmanager
        async def begin(self):
            with engine.begin() as connection:
                yield Connection(connection)

    async def lock(_connection):
        pass

    # Only the PG advisory lock is stubbed; selection and deletion execute real SQL.
    monkeypatch.setattr(p, "_lock_publication", lock)
    repository = object.__new__(p.SqlAlchemyDownloadGrantRepository)
    repository.engine = Engine()

    def remaining():
        with engine.connect() as connection:
            return set(connection.scalars(select(p.report_artifact_files_v1.c.artifact_key)))

    try:
        await repository.cleanup_expired(now=now)
        assert len(remaining()) == p.REPORT_ARTIFACT_CLEANUP_BATCH + 2
        await repository.cleanup_expired(now=now)
        assert remaining() == {
            *(f"protected-{index}" for index in range(p.REPORT_ARTIFACT_CLEANUP_BATCH)),
            "young",
        }
        with engine.connect() as connection:
            assert list(connection.scalars(select(p.report_artifact_chunks_v1.c.artifact_key))) == []

        # These grants must not protect files: every scope/identity component matters.
        mismatches = [
            {field: "different"} for field in scope
        ] + [
            {"revision": 2}, {"report_id": "other-report"},
            {f"{kind}_path": "other-path"}, {f"{kind}_size": 2},
            {f"{kind}_sha256": "b" * 64}, {"revoked_at": now}, {"expires_at": now},
        ]
        with engine.begin() as connection:
            for index, mismatch in enumerate(mismatches):
                key = f"mismatch-{index}"
                connection.execute(insert(p.report_artifact_files_v1).values(**artifact(key)))
                connection.execute(insert(p.report_download_grants_v2).values(**grant(key, **mismatch)))
        await repository.cleanup_expired(now=now)
        assert not any(key.startswith("mismatch-") for key in remaining())
        assert len(remaining()) == p.REPORT_ARTIFACT_CLEANUP_BATCH + 1
    finally:
        engine.dispose()
