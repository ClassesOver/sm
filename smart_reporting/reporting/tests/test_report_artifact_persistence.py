from __future__ import annotations

import hashlib
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from smart_reporting.reporting.delivery.publishing import (
    DOWNLOAD_GRANT_TTL,
    ReportArtifactPersistenceService,
    ReportArtifactSpec,
    ReportDownloadGrant,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    ReportDownloadScope,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
    StoredReportArtifact,
    _artifact_key,
    create_report_download_router,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.delivery_fakes import (
    InMemoryDownloadGrantRepository,
    InMemoryReportArtifactRepository,
)
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.reporting.workflow.runtime import base as runtime_module
from smart_reporting.reporting.workflow.scope import (
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    ReportingWorkflowScope,
    reporting_scope_keys,
)
from smart_reporting.runtime.database import create_agent_database
from smart_reporting.task_execution import TaskState
from smart_reporting.workspace import WorkspaceService


async def _chunks(*values: bytes):
    for value in values:
        yield value


async def _content(stream) -> bytes:
    return b"".join([chunk async for chunk in stream])


def test_sql_publication_repositories_require_postgresql() -> None:
    engine = SimpleNamespace(dialect=SimpleNamespace(name="mysql"))

    for repository_type in (
        SqlAlchemyDownloadGrantRepository,
        SqlAlchemyReportArtifactRepository,
    ):
        with pytest.raises(ValueError, match="只支持 PostgreSQL"):
            repository_type(engine)  # type: ignore[arg-type]


def _scope(database: str = "odoo") -> ReportDownloadScope:
    return ReportDownloadScope(
        database=database,
        user_id="7",
        company_id="3",
        session_id="session",
        thread_id="thread",
        workflow_run_id="workflow-run",
    )


def _scope_state_for_publication() -> dict[str, str]:
    keys = reporting_scope_keys(
        database="database-1",
        company_id="company-1",
        user_id="7",
        thread_id="thread",
        run_id="workflow-run",
    )
    return ReportingWorkflowScope(
        run_id="workflow-run",
        external_run_id="external-1",
        session_id="workflow-session",
        caller_thread_id="thread",
        user_id="7",
        database="database-1",
        company_id="company-1",
        thread_lease_key=keys.thread_lease_key,
        workspace_key=keys.workspace_key,
    ).as_state()


def _integration_database_url() -> str:
    value = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not value:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL 产物持久化集成测试。")
    return value


@pytest.fixture
async def publication_database():
    database = create_agent_database(_integration_database_url())
    engine = database.async_engine
    scope = _scope(f"integration-publication-{uuid4().hex}")
    try:
        yield engine, scope
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "DELETE FROM report_artifact_chunks_v1 WHERE artifact_key IN "
                    "(SELECT artifact_key FROM report_artifact_files_v1 "
                    "WHERE database_name = :database_name)"
                ),
                {"database_name": scope.database},
            )
            await connection.execute(
                text("DELETE FROM report_artifact_files_v1 WHERE database_name = :database_name"),
                {"database_name": scope.database},
            )
            await connection.execute(
                text("DELETE FROM report_download_grants_v2 WHERE database_name = :database_name"),
                {"database_name": scope.database},
            )
        await database.async_engine.dispose()
        database.sync_engine.dispose()


def _checkpoint_with_traces(*traces: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "1",
        "revision": 1,
        "phase": "analysis",
        "outlineHash": "a" * 64,
        "profileCoverage": {
            "version": "1",
            "authorizedDatasetCount": 1,
            "coveredDatasetCount": 1,
            "datasets": [
                {
                    "datasetId": "dataset-1",
                    "datasetPath": "datasets/source.csv",
                    "datasetSize": 1,
                    "datasetSnapshotHash": "b" * 64,
                    "profileFile": {
                        "path": "profiles/source.json",
                        "size": 1,
                        "sha256": "c" * 64,
                    },
                    "rowCount": 1,
                    "fieldCount": 1,
                    "fields": ["amount"],
                }
            ],
        },
        "trace": list(traces),
    }


class _WorkspaceFs:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    async def download_file_stream(self, path: str, timeout: int):
        del timeout
        return _chunks(self.files[path][:2], self.files[path][2:])


class _Workspace:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.sandbox = SimpleNamespace(fs=_WorkspaceFs(files))
        self.destroyed: list[str] = []

    normalize_path = staticmethod(WorkspaceService.normalize_path)

    @asynccontextmanager
    async def _async_client(self):
        yield object()

    async def _asandbox_for(self, _client: object, _thread: str, create: bool = True):
        del create
        return self.sandbox

    async def read_limited_regular_file(
        self,
        _thread: str,
        path: str,
        *,
        max_bytes: int,
    ) -> bytes:
        content = self.sandbox.fs.files[f"/home/daytona/workspace/{path}"]
        if len(content) > max_bytes:
            raise ValueError("file too large")
        return content

    async def adestroy(self, thread_id: str) -> bool:
        self.destroyed.append(thread_id)
        self.sandbox = None
        return True


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_artifact_repository_streams_chunks_and_rolls_back_invalid_replacement(
    publication_database,
) -> None:
    engine, scope = publication_database
    schema = SqlAlchemyDownloadGrantRepository(engine)
    repository = SqlAlchemyReportArtifactRepository(engine)
    content = b"persistent-report"
    artifact = StoredReportArtifact(
        artifact_key=hashlib.sha256(scope.database.encode("utf-8")).hexdigest(),
        scope=scope,
        report_id="report-1",
        revision=2,
        artifact="pdf",
        path="reports/report.pdf",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        created_at=datetime.now(UTC),
    )
    await schema.create_schema()
    await repository.put(artifact, _chunks(content[:4], content[4:]))

    assert await repository.get(artifact.artifact_key) == artifact
    assert await _content(repository.stream(artifact.artifact_key)) == content

    with pytest.raises(ReportingError) as raised:
        await repository.put(artifact, _chunks(b"changed"))
    assert raised.value.code == "report_artifact_changed"
    assert await _content(repository.stream(artifact.artifact_key)) == content


@pytest.mark.anyio
async def test_persisted_report_download_survives_sandbox_deletion() -> None:
    pdf = b"pdf-content"
    word = b"word-content"
    files = {
        "/home/daytona/workspace/reports/report.pdf": pdf,
        "/home/daytona/workspace/reports/report.docx": word,
    }
    workspace = _Workspace(files)
    artifacts = InMemoryReportArtifactRepository()
    persistence = ReportArtifactPersistenceService(artifacts, workspace)  # type: ignore[arg-type]
    scope = _scope()
    specs = (
        ReportArtifactSpec(
            artifact="pdf",
            path="reports/report.pdf",
            size=len(pdf),
            sha256=hashlib.sha256(pdf).hexdigest(),
        ),
        ReportArtifactSpec(
            artifact="word",
            path="reports/report.docx",
            size=len(word),
            sha256=hashlib.sha256(word).hexdigest(),
        ),
    )
    await persistence.persist(scope=scope, report_id="report-1", revision=1, artifacts=specs)

    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    raw_grant, _grant = await grants.issue(
        scope=scope,
        report_id="report-1",
        revision=1,
        pdf_path=specs[0].path,
        pdf_size=specs[0].size,
        pdf_sha256=specs[0].sha256,
        word_path=specs[1].path,
        word_size=specs[1].size,
        word_sha256=specs[1].sha256,
    )
    await workspace.adestroy(scope.thread_id)
    downloads = ReportDownloadHttpService(grants, artifacts)
    _pdf_grant, pdf_stream = await downloads.stream(raw_grant)
    _word_grant, word_stream = await downloads.stream(raw_grant, artifact="word")

    assert workspace.sandbox is None
    assert await _content(pdf_stream) == pdf
    assert await _content(word_stream) == word


@pytest.mark.anyio
async def test_artifact_persistence_reads_host_workspace_without_private_sandbox_api(
    tmp_path,
) -> None:
    registry = ReportingWorkspaceRegistry(
        tmp_path,
        secret="0123456789abcdef0123456789abcdef",
    )
    registry.resolve(
        ReportingWorkflowScope(
            run_id="run-1",
            external_run_id="external-run-1",
            session_id="session-1",
            caller_thread_id="caller-thread-1",
            user_id="user-1",
            database="database-1",
            company_id="company-1",
            thread_lease_key="lease-1",
            workspace_key="workspace-1",
        )
    )
    workspace = ReportingWorkspaceRouter(registry)
    contents = {
        "pdf": b"pdf-content",
        "word": b"word-content",
    }
    suffixes = {"pdf": "pdf", "word": "docx"}
    specs = []
    for artifact, content in contents.items():
        path = f"reports/report.{suffixes[artifact]}"
        await workspace.awrite_bytes("workspace-1", path, content)
        specs.append(
            ReportArtifactSpec(
                artifact=artifact,
                path=path,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    repository = InMemoryReportArtifactRepository()
    persistence = ReportArtifactPersistenceService(repository, workspace)  # type: ignore[arg-type]
    scope = ReportDownloadScope(
        database="database-1",
        user_id="user-1",
        company_id="company-1",
        session_id="session-1",
        thread_id="workspace-1",
        workflow_run_id="run-1",
    )

    await persistence.persist(
        scope=scope,
        report_id="report-1",
        revision=1,
        artifacts=tuple(specs),  # type: ignore[arg-type]
    )

    for spec in specs:
        stored = await repository.resolve(
            scope=scope,
            report_id="report-1",
            revision=1,
            artifact=spec.artifact,
        )
        assert stored is not None
        assert await _content(repository.stream(stored.artifact_key)) == contents[spec.artifact]


@pytest.mark.anyio
async def test_persistence_requires_pdf_and_word() -> None:
    content = b"report"
    workspace = _Workspace(
        {
            "/home/daytona/workspace/reports/report.pdf": content,
            "/home/daytona/workspace/reports/report.docx": content,
        }
    )
    persistence = ReportArtifactPersistenceService(
        InMemoryReportArtifactRepository(),
        workspace,  # type: ignore[arg-type]
    )
    specs = (
        ReportArtifactSpec(
            artifact="pdf",
            path="reports/report.pdf",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        ),
    )

    with pytest.raises(ReportingError) as raised:
        await persistence.persist(scope=_scope(), report_id="report-1", revision=1, artifacts=specs)

    assert raised.value.code == "report_artifact_invalid"


@pytest.mark.anyio
async def test_html_download_route_is_not_registered() -> None:
    scope = _scope()
    artifacts = InMemoryReportArtifactRepository()
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    raw_grant, _grant = await grants.issue(
        scope=scope,
        report_id="report-1",
        revision=1,
        pdf_path="reports/report.pdf",
        pdf_size=3,
        pdf_sha256="a" * 64,
        word_path="reports/report.docx",
        word_size=4,
        word_sha256="b" * 64,
    )
    app = FastAPI()
    app.include_router(create_report_download_router(ReportDownloadHttpService(grants, artifacts)))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/reports/v1/download/{raw_grant}/html")

    assert response.status_code == 404


@pytest.mark.anyio
async def test_download_grant_defaults_to_thirty_days() -> None:
    now = datetime(2026, 8, 21, tzinfo=UTC)
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())

    _raw, grant = await grants.issue(
        scope=_scope(),
        report_id="report-1",
        revision=1,
        pdf_path="reports/report.pdf",
        pdf_size=3,
        pdf_sha256="a" * 64,
        word_path="reports/report.docx",
        word_size=4,
        word_sha256="b" * 64,
        now=now,
    )

    assert DOWNLOAD_GRANT_TTL == timedelta(days=30)
    assert grant.expires_at == now + timedelta(days=30)


@pytest.mark.anyio
async def test_download_grant_replaces_same_revision_and_rejects_stale_revision() -> None:
    repository = InMemoryDownloadGrantRepository()
    grants = ReportDownloadGrantService(repository)
    values = {
        "scope": _scope(),
        "report_id": "report-1",
        "revision": 2,
        "pdf_path": "reports/report.pdf",
        "pdf_size": 3,
        "pdf_sha256": "a" * 64,
        "word_path": "reports/report.docx",
        "word_size": 4,
        "word_sha256": "b" * 64,
    }

    first_raw, _first = await grants.issue(**values)
    second_raw, _second = await grants.issue(**values)

    with pytest.raises(ReportingError, match="下载授权无效"):
        await grants.lookup(first_raw)
    assert await grants.lookup(second_raw)
    with pytest.raises(ReportingError) as raised:
        await grants.issue(**{**values, "revision": 1})
    assert raised.value.code == "report_download_revision_stale"


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_grant_replacement_rolls_back_revocation_when_insert_fails(
    publication_database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, scope = publication_database
    repository = SqlAlchemyDownloadGrantRepository(engine)
    grants = ReportDownloadGrantService(repository)
    monkeypatch.setattr(
        "smart_reporting.reporting.delivery.publishing.secrets.token_urlsafe",
        lambda _size: f"fixed-grant-{scope.database}",
    )
    values = {
        "scope": scope,
        "report_id": "report-1",
        "revision": 1,
        "pdf_path": "reports/report.pdf",
        "pdf_size": 3,
        "pdf_sha256": "a" * 64,
        "word_path": "reports/report.docx",
        "word_size": 4,
        "word_sha256": "b" * 64,
    }
    await repository.create_schema()
    raw, _grant = await grants.issue(**values)

    with pytest.raises(IntegrityError):
        await grants.issue(**values)

    assert await grants.lookup(raw)


@pytest.mark.anyio
@pytest.mark.integration
async def test_sql_cleanup_removes_expired_grant_and_unreferenced_artifacts(
    publication_database,
) -> None:
    engine, scope = publication_database
    grants_repository = SqlAlchemyDownloadGrantRepository(engine)
    artifacts_repository = SqlAlchemyReportArtifactRepository(engine)
    grants = ReportDownloadGrantService(grants_repository)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    specs = (
        ReportArtifactSpec("pdf", "reports/report.pdf", 3, hashlib.sha256(b"pdf").hexdigest()),
        ReportArtifactSpec("word", "reports/report.docx", 4, hashlib.sha256(b"word").hexdigest()),
    )
    await grants_repository.create_schema()
    for spec, content in zip(specs, (b"pdf", b"word"), strict=True):
        artifact = StoredReportArtifact(
            artifact_key=_artifact_key(scope, "report-1", 1, spec),
            scope=scope,
            report_id="report-1",
            revision=1,
            artifact=spec.artifact,
            path=spec.path,
            size=spec.size,
            sha256=spec.sha256,
            created_at=now,
        )
        await artifacts_repository.put(artifact, _chunks(content))
    raw, _grant = await grants.issue(
        scope=scope,
        report_id="report-1",
        revision=1,
        pdf_path=specs[0].path,
        pdf_size=specs[0].size,
        pdf_sha256=specs[0].sha256,
        word_path=specs[1].path,
        word_size=specs[1].size,
        word_sha256=specs[1].sha256,
        now=now,
    )

    await grants_repository.cleanup_expired(now=now + timedelta(days=2))

    assert await grants.lookup(raw, now=now + timedelta(days=2))
    for spec in specs:
        assert await artifacts_repository.get(_artifact_key(scope, "report-1", 1, spec))

    await grants_repository.cleanup_expired(now=now + timedelta(days=32))

    with pytest.raises(ReportingError, match="下载授权无效"):
        await grants.lookup(raw, now=now + timedelta(days=32))
    for spec in specs:
        assert await artifacts_repository.get(_artifact_key(scope, "report-1", 1, spec)) is None


@pytest.mark.parametrize(
    ("download_grants", "artifact_persistence"),
    [(object(), None), (None, object())],
)
def test_runtime_rejects_partial_http_publication_configuration(
    download_grants: object | None,
    artifact_persistence: object | None,
) -> None:
    with pytest.raises(ValueError, match="下载授权和产物持久化服务必须同时配置"):
        ReportWorkflowRuntime(
            db=object(),
            reporting_agent_template=object(),  # type: ignore[arg-type]
            task_runner=object(),  # type: ignore[arg-type]
            workspace_service=object(),  # type: ignore[arg-type]
            registry=object(),  # type: ignore[arg-type]
            profiles=object(),  # type: ignore[arg-type]
            planner_enable_thinking=False,
            download_grants=download_grants,  # type: ignore[arg-type]
            artifact_persistence=artifact_persistence,  # type: ignore[arg-type]
            report_public_base_url="https://reports.example.com",
            state_repository=object(),  # type: ignore[arg-type]
        )


def test_runtime_requires_public_base_url_for_http_publication() -> None:
    with pytest.raises(ValueError, match="公开下载基址"):
        ReportWorkflowRuntime(
            db=object(),
            reporting_agent_template=object(),  # type: ignore[arg-type]
            task_runner=object(),  # type: ignore[arg-type]
            workspace_service=object(),  # type: ignore[arg-type]
            registry=object(),  # type: ignore[arg-type]
            profiles=object(),  # type: ignore[arg-type]
            planner_enable_thinking=False,
            download_grants=object(),  # type: ignore[arg-type]
            artifact_persistence=object(),  # type: ignore[arg-type]
            state_repository=object(),  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_http_publication_persists_and_destroys_sandbox_before_issuing_grant() -> None:
    events: list[str] = []
    markdown_snapshots: list[tuple[str, str]] = []
    persisted_artifacts: tuple[object, ...] = ()
    pdf = b"pdf"
    word = b"word"
    content = {
        "reportId": "report-1",
        "revision": 1,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1", "status": "validated"},
        "markdownPath": "reports/report.md",
        "pdfPath": "reports/report.pdf",
        "pdfSize": len(pdf),
        "pdfSha256": hashlib.sha256(pdf).hexdigest(),
        "wordPath": "reports/report.docx",
        "wordSize": len(word),
        "wordSha256": hashlib.sha256(word).hexdigest(),
        "sourceWarnings": [],
        "codingReceipts": [],
    }

    class Persistence:
        async def persist(self, **values: Any) -> None:
            nonlocal persisted_artifacts
            persisted_artifacts = values["artifacts"]
            events.append("persist")

    class Grants:
        async def issue(self, **values: Any):
            events.append("grant")
            return "raw", ReportDownloadGrant(
                grant_hash="b" * 64,
                scope=values["scope"],
                report_id=values["report_id"],
                revision=values["revision"],
                pdf_path=values["pdf_path"],
                pdf_size=values["pdf_size"],
                pdf_sha256=values["pdf_sha256"],
                word_path=values["word_path"],
                word_size=values["word_size"],
                word_sha256=values["word_sha256"],
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    class EditorGrants:
        async def issue(self, context: Any):
            events.append("editor-grant")
            assert context.markdown_path == "reports/revision-1/report.md"
            assert context.job["jobId"] == "job-1"
            assert context.scope["database"] == "database-1"
            return "editor-raw", datetime(2026, 9, 15, 9, tzinfo=UTC)

    class Workspace:
        async def aread_text(self, thread_id: str, path: str) -> str:
            assert thread_id == "thread"
            assert path == "reports/report.md"
            return "# 报告\n"

        async def apath_exists(self, thread_id: str, path: str) -> bool:
            assert thread_id == "thread"
            assert path == "reports/revision-1/report.md"
            return False

        async def awrite_text(self, thread_id: str, path: str, content: str) -> None:
            assert thread_id == "thread"
            markdown_snapshots.append((path, content))

        async def adestroy(self, thread_id: str) -> bool:
            assert thread_id == "thread"
            events.append("destroy")
            return True

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.editor_grants = EditorGrants()
    runtime.workspace_service = Workspace()
    runtime.report_public_base_url = "http://10.233.32.64:27018"
    durable = SimpleNamespace(
        state_version=3,
        payload={"report_workflow_scope": _scope_state_for_publication()},
    )

    class StateRepository:
        async def get(self, report_run_id: str):
            assert report_run_id == "workflow-run"
            return durable

        async def apply(self, report_run_id: str, command: Any, *, expected_version: int):
            assert report_run_id == "workflow-run"
            assert expected_version == 3
            events.append("editor-context")
            durable.payload["reportEditorContexts"] = {
                "1": command.payload["context"]
            }

    runtime.state_repository = StateRepository()
    result = await runtime.issue_http_publication(
        thread_id="thread",
        caller_thread_id="thread",
        user_id="7",
        workflow_session_id="workflow-session",
        workflow_run_id="workflow-run",
        output=content,
    )

    assert events == ["persist", "editor-context", "destroy", "grant", "editor-grant"]
    assert markdown_snapshots == [("reports/revision-1/report.md", "# 报告\n")]
    assert {item.artifact for item in persisted_artifacts} == {"pdf", "word"}
    assert result["pdf"]["downloadUrl"] == ("http://10.233.32.64:27018/reports/v1/download/raw")
    assert result["word"]["downloadUrl"] == (
        "http://10.233.32.64:27018/reports/v1/download/raw/word"
    )
    assert result["editor"]["openUrl"] == (
        "http://10.233.32.64:27018/reports/v1/editor/open/editor-raw"
    )
    assert "html" not in result


@pytest.mark.anyio
async def test_http_publication_resolves_caller_thread_from_run_dependencies() -> None:
    """生产 durable payload 不固化作用域；caller thread 只能从 run dependencies 恢复。

    回归：AgentOS/MCP 形态发布曾因 durable 无 scope 键、又未向 issue_http_publication
    传入 dependencies，caller_thread_id 回退到 workflow 内部会话 id，与调用方 thread
    不一致，误判 report_editor_scope_mismatch，导致正式发布会 100% 失败关闭。
    """
    pdf = b"%PDF-1.4 fake"
    word = b"PK fake docx"
    content = {
        "reportId": "report-1",
        "revision": 1,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1", "status": "validated"},
        "markdownPath": "reports/report.md",
        "pdfPath": "reports/report.pdf",
        "pdfSize": len(pdf),
        "pdfSha256": hashlib.sha256(pdf).hexdigest(),
        "wordPath": "reports/report.docx",
        "wordSize": len(word),
        "wordSha256": hashlib.sha256(word).hexdigest(),
        "sourceWarnings": [],
        "codingReceipts": [],
    }
    events: list[str] = []

    class Persistence:
        async def persist(self, **values: Any) -> None:
            events.append("persist")

    class Grants:
        async def issue(self, **values: Any):
            events.append("grant")
            return "raw", ReportDownloadGrant(
                grant_hash="b" * 64,
                scope=values["scope"],
                report_id=values["report_id"],
                revision=values["revision"],
                pdf_path=values["pdf_path"],
                pdf_size=values["pdf_size"],
                pdf_sha256=values["pdf_sha256"],
                word_path=values["word_path"],
                word_size=values["word_size"],
                word_sha256=values["word_sha256"],
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )

    class EditorGrants:
        async def issue(self, context: Any):
            events.append("editor-grant")
            assert context.scope["database"] == "database-1"
            assert context.scope["callerThreadId"] == "thread"
            return "editor-raw", datetime(2026, 9, 15, 9, tzinfo=UTC)

    class Workspace:
        async def aread_text(self, thread_id: str, path: str) -> str:
            assert thread_id == "reporting-run-workspace-key"
            return "# 报告\n"

        async def apath_exists(self, thread_id: str, path: str) -> bool:
            assert thread_id == "reporting-run-workspace-key"
            return False

        async def awrite_text(self, thread_id: str, path: str, content: str) -> None:
            assert thread_id == "reporting-run-workspace-key"

        async def adestroy(self, thread_id: str) -> bool:
            events.append("destroy")
            return True

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.editor_grants = EditorGrants()
    runtime.workspace_service = Workspace()
    runtime.report_public_base_url = "http://10.233.32.64:27018"
    # 关键复现条件：durable payload 没有 report_workflow_scope 键（生产行为）。
    durable = SimpleNamespace(state_version=3, payload={})

    class StateRepository:
        async def get(self, report_run_id: str):
            assert report_run_id == "workflow-run"
            return durable

        async def apply(self, report_run_id: str, command: Any, *, expected_version: int):
            assert report_run_id == "workflow-run"
            events.append("editor-context")

    runtime.state_repository = StateRepository()
    dependencies = {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-1",
            "threadId": "thread",
            "userId": "7",
            "database": "database-1",
            "companyId": "company-1",
        }
    }
    result = await runtime.issue_http_publication(
        thread_id="reporting-run-workspace-key",
        caller_thread_id="thread",
        user_id="7",
        workflow_session_id="report-session-internal",
        workflow_run_id="workflow-run",
        dependencies=dependencies,
        output=content,
    )

    assert events == ["persist", "editor-context", "destroy", "grant", "editor-grant"]
    assert result["editor"]["openUrl"] == (
        "http://10.233.32.64:27018/reports/v1/editor/open/editor-raw"
    )

    # 校验仍然失败关闭：dependencies 与 stored 都无法提供 caller thread 时不得签发。
    with pytest.raises(ReportingError, match="report_editor_scope_mismatch"):
        await runtime.issue_http_publication(
            thread_id="reporting-run-workspace-key",
            caller_thread_id="thread",
            user_id="7",
            workflow_session_id="report-session-internal",
            workflow_run_id="workflow-run",
            output=content,
        )


@pytest.mark.anyio
async def test_http_publication_keeps_host_workspace_instead_of_destroying(tmp_path) -> None:
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_registry = registry
    # 生产装配的宿主机路由没有 adestroy/aquarantine；发布后必须保留会话目录供编辑器续写。
    runtime.workspace_service = ReportingWorkspaceRouter(registry)

    await runtime._release_or_destroy_workspace("thread-1", message="m")


@pytest.mark.anyio
async def test_terminal_cleanup_destroys_reporting_sandbox() -> None:
    workspace = SimpleNamespace(adestroy=AsyncMock(return_value=True))
    repository = SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None))
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.task_runner = SimpleNamespace(repository=repository, cancel=AsyncMock())
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=None))

    await runtime.cleanup_terminal({"thread_id": "thread"}, "workflow-session", "workflow-run")

    workspace.adestroy.assert_awaited_once_with("thread")


@pytest.mark.anyio
async def test_terminal_cleanup_fails_closed_when_sandbox_destroy_fails() -> None:
    workspace = SimpleNamespace(
        adestroy=AsyncMock(side_effect=RuntimeError("delete failed")),
        aquarantine=AsyncMock(return_value="old-workspace-label"),
    )
    repository = SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None))
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.task_runner = SimpleNamespace(repository=repository, cancel=AsyncMock())
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=None))

    with pytest.raises(ReportingError) as raised:
        await runtime.cleanup_terminal({"thread_id": "thread"}, "workflow-session", "workflow-run")

    assert raised.value.code == "report_sandbox_cleanup_failed"
    workspace.aquarantine.assert_awaited_once_with("thread")


@pytest.mark.anyio
async def test_terminal_cleanup_fails_closed_when_sandbox_quarantine_fails() -> None:
    workspace = SimpleNamespace(
        adestroy=AsyncMock(side_effect=RuntimeError("delete failed")),
        aquarantine=AsyncMock(side_effect=RuntimeError("quarantine failed")),
    )
    repository = SimpleNamespace(get_task_snapshot=AsyncMock(return_value=None))
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.task_runner = SimpleNamespace(repository=repository, cancel=AsyncMock())
    runtime.state_repository = SimpleNamespace(get=AsyncMock(return_value=None))

    with pytest.raises(ReportingError) as raised:
        await runtime.cleanup_terminal({"thread_id": "thread"}, "workflow-session", "workflow-run")

    assert raised.value.code == "report_sandbox_quarantine_failed"
    workspace.aquarantine.assert_awaited_once_with("thread")


@pytest.mark.anyio
async def test_terminal_cleanup_cancels_phase_tasks_before_destroying_sandbox() -> None:
    events: list[str] = []
    task_ids = ("analysis-task", "visualization-task", "section-task")
    scopes = {task_id: SimpleNamespace(external_run_id=task_id) for task_id in task_ids}

    async def get_task_snapshot(task_id: str):
        return SimpleNamespace(scope=scopes[task_id], state=TaskState.ACTIVE)

    async def cancel(scope: Any) -> None:
        events.append(f"cancel:{scope.external_run_id}")

    async def destroy(thread_id: str) -> bool:
        assert thread_id == "thread"
        events.append("destroy")
        return True

    checkpoint = _checkpoint_with_traces(
        {
            "phase": "analysis",
            "taskId": task_ids[0],
            "workKind": "analysis_item",
            "analysisId": "analysis_001",
        },
        {
            "phase": "analysis",
            "taskId": task_ids[1],
            "workKind": "visualization_section",
            "sectionCode": "section_001",
        },
        {
            "phase": "section",
            "taskId": task_ids[2],
            "workKind": "section",
            "sectionCode": "executive_summary",
        },
    )
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = SimpleNamespace(adestroy=destroy)
    runtime.task_runner = SimpleNamespace(
        repository=SimpleNamespace(get_task_snapshot=get_task_snapshot),
        cancel=cancel,
    )
    runtime.state_repository = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(payload={"workflowCheckpoint": checkpoint}))
    )

    await runtime.cleanup_terminal({"thread_id": "thread"}, "workflow-session", "workflow-run")

    runtime.state_repository.get.assert_awaited_once_with("workflow-run")
    assert events == [*(f"cancel:{task_id}" for task_id in task_ids), "destroy"]


@pytest.mark.anyio
async def test_terminal_cleanup_keeps_sandbox_when_phase_task_cleanup_fails() -> None:
    workspace = SimpleNamespace(adestroy=AsyncMock(return_value=True))
    task_ids = ("analysis-task", "section-task")
    task_scopes = {task_id: SimpleNamespace(external_run_id=task_id) for task_id in task_ids}
    repository = SimpleNamespace(
        get_task_snapshot=AsyncMock(
            side_effect=lambda task_id: SimpleNamespace(
                scope=task_scopes[task_id], state=TaskState.ACTIVE
            )
        )
    )

    async def cancel(scope: Any) -> None:
        if scope.external_run_id == task_ids[0]:
            raise RuntimeError("task cleanup failed")

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.workspace_service = workspace
    runtime.task_runner = SimpleNamespace(
        repository=repository,
        cancel=AsyncMock(side_effect=cancel),
    )
    runtime.state_repository = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                payload={
                    "workflowCheckpoint": _checkpoint_with_traces(
                        {
                            "phase": "analysis",
                            "taskId": task_ids[0],
                            "workKind": "analysis_item",
                            "analysisId": "analysis_001",
                        },
                        {
                            "phase": "section",
                            "taskId": task_ids[1],
                            "workKind": "section",
                            "sectionCode": "executive_summary",
                        },
                    )
                }
            )
        )
    )

    with pytest.raises(RuntimeError, match="task cleanup failed"):
        await runtime.cleanup_terminal({"thread_id": "thread"}, "workflow-session", "workflow-run")

    assert [
        call.args[0].external_run_id for call in runtime.task_runner.cancel.await_args_list
    ] == list(task_ids)
    workspace.adestroy.assert_not_awaited()


@pytest.mark.anyio
async def test_http_publication_keeps_sandbox_when_artifact_persistence_fails() -> None:
    events: list[str] = []

    class Persistence:
        async def persist(self, **_values: Any) -> None:
            events.append("persist")
            raise ReportingError("report_artifact_changed", "报告文件已变化。")

    class Grants:
        async def issue(self, **_values: Any):
            events.append("grant")
            raise AssertionError("持久化失败后不得签发 grant")

    class Workspace:
        async def adestroy(self, _thread_id: str) -> bool:
            events.append("destroy")
            raise AssertionError("持久化失败后不得删除 sandbox")

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.editor_grants = Grants()
    runtime.workspace_service = Workspace()
    runtime.report_public_base_url = "http://10.233.32.64:27018"
    content = b"report"
    output = {
        "reportId": "report-1",
        "revision": 1,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1", "status": "validated"},
        "markdownPath": "reports/revision-1/report.md",
        "pdfPath": "reports/report.pdf",
        "pdfSize": len(content),
        "pdfSha256": hashlib.sha256(content).hexdigest(),
        "wordPath": "reports/report.docx",
        "wordSize": len(content),
        "wordSha256": hashlib.sha256(content).hexdigest(),
        "sourceWarnings": [],
        "codingReceipts": [],
    }
    with pytest.raises(ReportingError) as raised:
        await runtime.issue_http_publication(
            thread_id="thread",
            caller_thread_id="thread",
            user_id="7",
            workflow_session_id="workflow-session",
            workflow_run_id="workflow-run",
            output=output,
        )

    assert raised.value.code == "report_artifact_changed"
    assert events == ["persist"]


@pytest.mark.anyio
async def test_http_publication_does_not_issue_grant_when_sandbox_cleanup_fails() -> None:
    events: list[str] = []

    class Persistence:
        async def persist(self, **_values: Any) -> None:
            events.append("persist")

    class Grants:
        async def issue(self, **_values: Any):
            events.append("grant")
            raise AssertionError("sandbox 删除失败后不得签发 grant")

    class Workspace:
        async def adestroy(self, _thread_id: str) -> bool:
            events.append("destroy")
            raise RuntimeError("cleanup failed")

        async def aquarantine(self, _thread_id: str) -> str:
            events.append("quarantine")
            return "old-workspace-label"

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.editor_grants = Grants()
    runtime.workspace_service = Workspace()
    runtime.report_public_base_url = "http://127.0.0.1:33046"
    runtime.state_repository = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                state_version=1,
                payload={"report_workflow_scope": _scope_state_for_publication()},
            )
        ),
        apply=AsyncMock(),
    )
    content = b"report"
    output = {
        "reportId": "report-1",
        "revision": 1,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1", "status": "validated"},
        "markdownPath": "reports/revision-1/report.md",
        "pdfPath": "reports/report.pdf",
        "pdfSize": len(content),
        "pdfSha256": hashlib.sha256(content).hexdigest(),
        "wordPath": "reports/report.docx",
        "wordSize": len(content),
        "wordSha256": hashlib.sha256(content).hexdigest(),
        "sourceWarnings": [],
        "codingReceipts": [],
    }

    with pytest.raises(ReportingError) as raised:
        await runtime.issue_http_publication(
            thread_id="thread",
            caller_thread_id="thread",
            user_id="7",
            workflow_session_id="workflow-session",
            workflow_run_id="workflow-run",
            output=output,
        )

    assert raised.value.code == "report_sandbox_cleanup_failed"
    assert events == ["persist", "destroy", "quarantine"]


@pytest.mark.anyio
async def test_workflow_publication_uses_http_links_when_service_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = b"pdf"
    word = b"word"
    output = {
        "formalReleaseAllowed": True,
        "publicationGate": {
            "formalReleaseAllowed": True,
            "issues": [],
            "warnings": [
                {
                    "code": "analysis_period_incomparable",
                    "message": "冻结指标包含不可比期间，报告结论需按披露口径谨慎使用。",
                }
            ],
        },
        "reportId": "report-1",
        "reportTitle": "年度运营分析报告",
        "revision": 1,
        "pdfPath": "reports/report.pdf",
        "pdfSize": len(pdf),
        "pdfSha256": hashlib.sha256(pdf).hexdigest(),
        "wordPath": "reports/report.docx",
        "wordSize": len(word),
        "wordSha256": hashlib.sha256(word).hexdigest(),
        "sourceWarnings": [],
        "codingReceipts": [],
    }
    captured: dict[str, Any] = {}

    def capture_workflow(**values: Any) -> object:
        captured.update(values)
        return object()

    monkeypatch.setattr(runtime_module, "create_reporting_workflow", capture_workflow)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.db = object()
    runtime.publish_report = AsyncMock(return_value=StepOutput(content=output))
    runtime.download_grants = object()
    runtime.artifact_persistence = object()
    runtime.issue_workspace_publication = AsyncMock()
    runtime.issue_http_publication = AsyncMock(
        return_value={
            "pdf": {"downloadUrl": "/reports/v1/download/raw"},
            "word": {"downloadUrl": "/reports/v1/download/raw/word"},
        }
    )
    runtime.workflow()
    finalize = captured["finalize_publication"]
    context = RunContext(
        run_id="workflow-run",
        session_id="thread",
        user_id="native",
        session_state={},
    )

    result = await finalize(SimpleNamespace(), context)

    assert result.content["reportTitle"] == "年度运营分析报告"
    assert result.content["pdf"]["downloadUrl"] == "/reports/v1/download/raw"
    assert result.content["publicationGate"] == output["publicationGate"]
    runtime.issue_http_publication.assert_awaited_once_with(
        thread_id=reporting_scope_keys(
            database="default",
            company_id="default",
            user_id="native",
            thread_id="thread",
            run_id="workflow-run",
        ).workspace_key,
        caller_thread_id="thread",
        user_id="native",
        workflow_session_id="thread",
        workflow_run_id="workflow-run",
        dependencies=None,
        output=output,
    )
    runtime.issue_workspace_publication.assert_not_awaited()


@pytest.mark.anyio
async def test_http_workflow_does_not_expose_workspace_paths_when_publication_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = {
        "formalReleaseAllowed": False,
        "reportId": "report-1",
        "revision": 1,
        "pdfPath": "reports/report.pdf",
        "pdfSize": 3,
        "pdfSha256": "a" * 64,
        "wordPath": "reports/report.docx",
        "wordSize": 4,
        "wordSha256": "b" * 64,
        "publicationGate": {
            "formalReleaseAllowed": False,
            "issues": [{"code": "artifact_changed", "message": "报告文件已变化。"}],
        },
        "sourceWarnings": [],
        "codingReceipts": [],
    }
    captured: dict[str, Any] = {}

    def capture_workflow(**values: Any) -> object:
        captured.update(values)
        return object()

    monkeypatch.setattr(runtime_module, "create_reporting_workflow", capture_workflow)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.db = object()
    runtime.download_grants = object()
    runtime.artifact_persistence = object()
    runtime.publish_report = AsyncMock(return_value=StepOutput(content=output))
    runtime.issue_http_publication = AsyncMock()
    runtime.issue_workspace_publication = AsyncMock()
    runtime.workflow()

    with pytest.raises(ReportingError) as raised:
        await captured["finalize_publication"](
            SimpleNamespace(),
            RunContext(
                run_id="workflow-run",
                session_id="thread",
                user_id="native",
                session_state={},
            ),
        )

    assert raised.value.code == "report_publication_blocked"
    assert "artifact_changed" in raised.value.message
    assert "reports/report.pdf" not in raised.value.message
    runtime.issue_http_publication.assert_not_awaited()
    runtime.issue_workspace_publication.assert_not_awaited()


@pytest.mark.anyio
async def test_workflow_publication_keeps_workspace_paths_without_http_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = {
        "reportId": "report-1",
        "reportTitle": "年度运营分析报告",
        "revision": 1,
        "pdfPath": "reports/report.pdf",
        "pdfSize": 3,
        "pdfSha256": "a" * 64,
        "wordPath": "reports/report.docx",
        "wordSize": 4,
        "wordSha256": "b" * 64,
        "sourceWarnings": [],
        "codingReceipts": [],
    }
    captured: dict[str, Any] = {}

    def capture_workflow(**values: Any) -> object:
        captured.update(values)
        return object()

    monkeypatch.setattr(runtime_module, "create_reporting_workflow", capture_workflow)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.db = object()
    runtime.download_grants = None
    runtime.artifact_persistence = None
    runtime.publish_report = AsyncMock(return_value=StepOutput(content=output))
    runtime.issue_http_publication = AsyncMock()
    runtime.issue_workspace_publication = AsyncMock(
        return_value={"path": output["pdfPath"], "word": {"path": output["wordPath"]}}
    )
    runtime.workflow()

    result = await captured["finalize_publication"](
        SimpleNamespace(),
        RunContext(
            run_id="workflow-run",
            session_id="thread",
            user_id="native",
            session_state={},
        ),
    )

    assert result.content["path"] == "reports/report.pdf"
    runtime.issue_workspace_publication.assert_awaited_once_with(
        thread_id=reporting_scope_keys(
            database="default",
            company_id="default",
            user_id="native",
            thread_id="thread",
            run_id="workflow-run",
        ).workspace_key,
        output=output,
    )
    runtime.issue_http_publication.assert_not_awaited()
