"""原生修订使用独立 PostgreSQL schema 验证真实并发与幂等。"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


def test_native_repository_rejects_non_postgresql():
    from types import SimpleNamespace

    from smart_reporting.report_editor.native_repository import NativeDocumentRepository

    with pytest.raises(ValueError, match="PostgreSQL"):
        NativeDocumentRepository(SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))


@pytest.fixture
async def repositories():
    from smart_reporting.report_editor.native_repository import NativeDocumentRepository

    url = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not url:
        pytest.skip("未设置 REPORTING_TEST_DB_URL。")
    schema = "native_test_" + uuid4().hex
    url = make_url(url).set(drivername="postgresql+psycopg")
    admin = create_async_engine(url)
    engines = [
        create_async_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        for _ in range(2)
    ]
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        repos = [NativeDocumentRepository(engine) for engine in engines]
        await repos[0].create_schema()
        await repos[0].create_schema()
        yield repos
    finally:
        for engine in engines:
            await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


def inputs():
    from smart_reporting.report_editor.native_models import NativeScope, NativeSource
    from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile

    scope = NativeScope(database="db", company_id="c", user_id="u", thread_id="t")
    source = NativeSource(
        format="docx",
        origin="report",
        source_file=ArtifactFile(
            path="reports/source.docx",
            size=5,
            sha256="a" * 64,
            mediaType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        report_id="report",
        workflow_run_id="workflow",
        revision=2,
    )
    return scope, source


@pytest.mark.anyio
async def test_revision_note_survives_retry_and_existing_schema_upgrade(repositories):
    from smart_reporting.report_editor.native_repository import NativeRepositoryConflict

    repo, other = repositories
    # 模拟上一版已初始化的表；启动升级必须保留旧数据并补默认值。
    scope, source = inputs()
    doc = await repo.create_from_source(source, scope=scope, request_id="open-note")
    async with repo.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE report_native_revisions_v1 DROP COLUMN IF EXISTS note"))
    await repo.create_schema()
    initial = await repo.get_revision(doc.document_id, 1, scope=scope)
    assert initial.note == ""
    reservation = await repo.reserve_revision(
        doc.document_id, scope=scope, parent_revision=1, request_id="noted-save",
        request_sha256="b" * 64, note="调整第三段说明",
    )
    retry = await other.reserve_revision(
        doc.document_id, scope=scope, parent_revision=1, request_id="noted-save",
        request_sha256="b" * 64, note="调整第三段说明",
    )
    assert retry == reservation
    assert (await other.get_revision(doc.document_id, reservation.revision, scope=scope)).note == "调整第三段说明"
    with pytest.raises(NativeRepositoryConflict):
        await repo.reserve_revision(
            doc.document_id, scope=scope, parent_revision=1, request_id="noted-save",
            request_sha256="b" * 64, note="另一份说明",
        )


@pytest.mark.anyio
async def test_concurrent_reservations_are_unique_idempotent_and_allow_historical_parent(
    repositories,
):
    from smart_reporting.report_editor.native_repository import NativeRepositoryConflict

    repo, other = repositories
    scope, source = inputs()
    doc = await repo.create_from_source(source, scope=scope, request_id="open")
    assert (
        await other.create_from_source(source, scope=scope, request_id="open")
    ).document_id == doc.document_id
    reservations = await asyncio.gather(
        *[
            repositories[i % 2].reserve_revision(
                doc.document_id,
                parent_revision=1,
                request_id=f"save-{i}",
                request_sha256="b" * 64,
                scope=scope,
            )
            for i in range(12)
        ]
    )
    assert sorted(item.revision for item in reservations) == list(range(2, 14))
    assert {item.parent_revision for item in reservations} == {1}
    retries = await asyncio.gather(
        *[
            repositories[i % 2].reserve_revision(
                doc.document_id,
                parent_revision=1,
                request_id="retry",
                request_sha256="c" * 64,
                scope=scope,
            )
            for i in range(8)
        ]
    )
    assert {item.revision for item in retries} == {14}
    with pytest.raises(NativeRepositoryConflict):
        await repo.reserve_revision(
            doc.document_id,
            parent_revision=1,
            request_id="retry",
            request_sha256="d" * 64,
            scope=scope,
        )
    with pytest.raises(NativeRepositoryConflict):
        await repo.reserve_revision(
            doc.document_id,
            parent_revision=2,
            request_id="retry",
            request_sha256="c" * 64,
            scope=scope,
        )


@pytest.mark.anyio
async def test_scope_isolation_completion_and_failed_reservation(repositories):
    from smart_reporting.report_editor.native_models import NativeArtifacts, NativeValidation
    from smart_reporting.report_editor.native_repository import (
        NativeRepositoryConflict,
        NativeRepositoryNotFound,
    )

    repo, other = repositories
    scope, source = inputs()
    doc = await repo.create_from_source(source, scope=scope, request_id="open")
    for field in ("database", "company_id", "user_id", "thread_id"):
        foreign = scope.model_copy(update={field: "foreign"})
        assert await repo.get_document(doc.document_id, scope=foreign) is None
        assert await repo.get_revision(doc.document_id, 1, scope=foreign) is None
        with pytest.raises(NativeRepositoryNotFound):
            await repo.reserve_revision(
                doc.document_id,
                parent_revision=1,
                request_id="bad",
                request_sha256="b" * 64,
                scope=foreign,
            )
        assert (
            await repo.create_from_source(source, scope=foreign, request_id="open")
        ).document_id != doc.document_id
    original = await repo.get_revision(doc.document_id, 1, scope=scope)
    assert original.validation.ok is False
    assert original.validation.issues[0].code == "native_validation_pending"
    reserved = await repo.reserve_revision(
        doc.document_id, parent_revision=1, request_id="save", request_sha256="b" * 64, scope=scope
    )
    context = original.context.model_copy(
        update={"revision": reserved.revision, "parent_revision": 1}
    )
    completed = await repo.complete_revision(
        reserved,
        context=context,
        artifacts=NativeArtifacts(word=source.source_file),
        validation=NativeValidation(ok=False),
    )
    assert completed.status == "saved"
    assert completed.validation.ok is False
    assert (await other.get_revision(doc.document_id, 2, scope=scope)).context == context
    assert (
        await repo.complete_revision(
            reserved,
            context=context,
            artifacts=completed.artifacts,
            validation=completed.validation,
        )
    ) == completed
    with pytest.raises(NativeRepositoryConflict):
        await repo.complete_revision(
            reserved,
            context=context.model_copy(update={"revision": 3}),
            artifacts=completed.artifacts,
            validation=completed.validation,
        )
    failed = await repo.reserve_revision(
        doc.document_id, parent_revision=1, request_id="fail", request_sha256="c" * 64, scope=scope
    )
    assert (await repo.fail_revision(failed, code="engine_failed")).status == "failed"
    assert (
        await repo.reserve_revision(
            doc.document_id,
            parent_revision=1,
            request_id="fail",
            request_sha256="c" * 64,
            scope=scope,
        )
    ).revision == failed.revision
    with pytest.raises(NativeRepositoryConflict):
        await repo.reserve_revision(
            doc.document_id,
            parent_revision=failed.revision,
            request_id="bad-parent",
            request_sha256="d" * 64,
            scope=scope,
        )


def test_native_context_has_independent_digest_and_validates_source():
    from pydantic import ValidationError

    from smart_reporting.report_editor.native_models import NativeEditorContext, NativeSource

    scope, source = inputs()
    context = NativeEditorContext(
        document_id="doc",
        format="docx",
        revision=1,
        scope=scope,
        source_file=source.source_file,
        origin="report",
    )
    assert context.report_id == "doc"
    assert context.workflow_run_id == "native:doc"
    assert context.digest() != context.model_copy(update={"origin": "upload"}).digest()
    with pytest.raises(ValidationError):
        NativeSource(format="docx", origin="report", source_file=source.source_file)
    with pytest.raises(ValidationError):
        NativeSource(format="pdf", origin="upload", source_file=source.source_file)


@pytest.mark.anyio
async def test_saved_revision_is_immutable_and_failed_retry_recovers_same_reservation(repositories):
    from smart_reporting.report_editor.native_models import NativeArtifacts, NativeValidation
    from smart_reporting.report_editor.native_repository import (
        NativeRepositoryConflict,
        NativeRepositoryNotFound,
    )

    repo = repositories[0]
    scope, source = inputs()
    doc = await repo.create_from_source(source, scope=scope, request_id="open")
    first = await repo.get_revision(doc.document_id, 1, scope=scope)
    reservation = await repo.reserve_revision(
        doc.document_id, scope=scope, parent_revision=1, request_id="save", request_sha256="b" * 64
    )
    await repo.fail_revision(reservation, code="engine_timeout")
    # 服务层重新核验已有文件后，可用同预约恢复，数据库不生成另一个修订。
    context = first.context.model_copy(update={"revision": 2, "parent_revision": 1})
    artifacts = NativeArtifacts(word=source.source_file)
    with pytest.raises(NativeRepositoryConflict):
        await repo.complete_revision(
            reservation,
            context=context,
            artifacts=NativeArtifacts(),
            validation=NativeValidation(ok=False),
        )
    foreign = reservation.model_copy(
        update={"scope": scope.model_copy(update={"user_id": "other"})}
    )
    with pytest.raises(NativeRepositoryNotFound):
        await repo.fail_revision(foreign, code="bad")
    saved = await repo.complete_revision(
        reservation, context=context, artifacts=artifacts, validation=NativeValidation(ok=False)
    )
    assert saved.revision == 2 and saved.status == "saved"
    with pytest.raises(NativeRepositoryConflict):
        await repo.fail_revision(reservation, code="late_failure")
    with pytest.raises(NativeRepositoryConflict):
        await repo.complete_revision(
            reservation, context=context, artifacts=artifacts, validation=NativeValidation(ok=True)
        )
    assert (await repo.get_revision(doc.document_id, 2, scope=scope)) == saved


def test_legacy_context_digest_remains_unchanged():
    import hashlib
    import json

    from smart_reporting.report_editor.service import ReportEditorContext

    context = ReportEditorContext(
        reportId="r",
        revision=1,
        jobId="j",
        job={"jobId": "j"},
        workflowRunId="w",
        markdownPath="r/report.md",
        scope={"database": "db"},
    )
    payload = {
        "reportId": "r",
        "revision": 1,
        "jobId": "j",
        "job": {"jobId": "j"},
        "workflowRunId": "w",
        "markdownPath": "r/report.md",
        "scope": {"database": "db"},
    }
    expected = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert context.digest() == expected


@pytest.mark.anyio
async def test_source_identity_scopes_open_retries_and_upload_starts_pending(repositories):
    from smart_reporting.report_editor.native_models import NativeSource

    repo, other = repositories
    scope, source = inputs()
    docs = await asyncio.gather(
        *[
            repositories[i % 2].create_from_source(source, scope=scope, request_id="open")
            for i in range(8)
        ]
    )
    assert len({doc.document_id for doc in docs}) == 1
    changed = source.model_copy(
        update={"source_file": source.source_file.model_copy(update={"sha256": "f" * 64})}
    )
    assert (
        await repo.create_from_source(changed, scope=scope, request_id="open")
    ).document_id != docs[0].document_id
    upload = NativeSource(
        format="pdf",
        origin="upload",
        sourceFile={
            "path": "native/upload.pdf",
            "size": 5,
            "sha256": "a" * 64,
            "mediaType": "application/pdf",
        },
    )
    doc = await other.create_from_source(upload, scope=scope, request_id="upload")
    initial = await repo.get_revision(doc.document_id, 1, scope=scope)
    assert initial.context.workflow_run_id == f"native:{doc.document_id}"
    assert initial.context.origin == "upload"
    assert initial.artifacts.pdf == upload.source_file
    assert initial.validation.ok is False
    assert initial.validation.issues[0].code == "native_validation_pending"


@pytest.mark.anyio
async def test_two_processes_reserve_distinct_revisions(repositories):
    import json
    import sys

    repo = repositories[0]
    scope, source = inputs()
    doc = await repo.create_from_source(source, scope=scope, request_id="open")
    async with repo.engine.connect() as connection:
        schema = (await connection.execute(text("SELECT current_schema()"))).scalar_one()
    script = """
import asyncio, json, os, sys
from sqlalchemy.ext.asyncio import create_async_engine
from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.report_editor.native_repository import NativeDocumentRepository
async def main():
    engine = create_async_engine(os.environ["REPORTING_TEST_DB_URL"],
        connect_args={"options": "-csearch_path=" + os.environ["NATIVE_TEST_SCHEMA"]})
    try:
        item = await NativeDocumentRepository(engine).reserve_revision(sys.argv[1],
            parent_revision=1, request_id=sys.argv[2], request_sha256="b"*64,
            scope=NativeScope.model_validate_json(sys.argv[3]))
        print(json.dumps({"revision": item.revision}))
    finally:
        await engine.dispose()
asyncio.run(main())
"""
    environment = {
        **os.environ,
        "REPORTING_TEST_DB_URL": repo.engine.url.render_as_string(hide_password=False),
        "NATIVE_TEST_SCHEMA": schema,
    }
    processes = [
        await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            doc.document_id,
            f"process-{index}",
            scope.model_dump_json(),
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        for index in range(2)
    ]
    results = await asyncio.gather(*(process.communicate() for process in processes))
    assert [process.returncode for process in processes] == [0, 0]
    assert sorted(json.loads(stdout)["revision"] for stdout, _ in results) == [2, 3]
