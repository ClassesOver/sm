from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput
from sqlalchemy.ext.asyncio import create_async_engine

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
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.delivery_fakes import (
    InMemoryDownloadGrantRepository,
    InMemoryReportArtifactRepository,
)
from smart_reporting.reporting.workflow import runtime as runtime_module
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime
from smart_reporting.workspace import WorkspaceService


async def _chunks(*values: bytes):
    for value in values:
        yield value


async def _content(stream) -> bytes:
    return b"".join([chunk async for chunk in stream])


def _scope() -> ReportDownloadScope:
    return ReportDownloadScope(
        database="odoo",
        user_id="7",
        company_id="3",
        session_id="session",
        thread_id="thread",
        workflow_run_id="workflow-run",
    )


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

    async def adestroy(self, thread_id: str) -> bool:
        self.destroyed.append(thread_id)
        self.sandbox = None
        return True


@pytest.mark.anyio
async def test_sql_artifact_repository_streams_chunks_and_rolls_back_invalid_replacement(
    tmp_path,
) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'artifacts.db'}")
    schema = SqlAlchemyDownloadGrantRepository(engine)
    repository = SqlAlchemyReportArtifactRepository(engine)
    content = b"persistent-report"
    artifact = StoredReportArtifact(
        artifact_key="a" * 64,
        scope=_scope(),
        report_id="report-1",
        revision=2,
        artifact="pdf",
        path="reports/report.pdf",
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        created_at=datetime.now(UTC),
    )
    try:
        await schema.create_schema()
        await repository.put(artifact, _chunks(content[:4], content[4:]))

        assert await repository.get(artifact.artifact_key) == artifact
        assert await _content(repository.stream(artifact.artifact_key)) == content

        with pytest.raises(ReportingError) as raised:
            await repository.put(artifact, _chunks(b"changed"))
        assert raised.value.code == "report_artifact_changed"
        assert await _content(repository.stream(artifact.artifact_key)) == content
    finally:
        await engine.dispose()


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
            report_worker=object(),  # type: ignore[arg-type]
            task_runner=object(),  # type: ignore[arg-type]
            workspace_service=object(),  # type: ignore[arg-type]
            registry=object(),  # type: ignore[arg-type]
            profiles=object(),  # type: ignore[arg-type]
            planner_enable_thinking=False,
            download_grants=download_grants,  # type: ignore[arg-type]
            artifact_persistence=artifact_persistence,  # type: ignore[arg-type]
            state_repository=object(),  # type: ignore[arg-type]
        )


@pytest.mark.anyio
async def test_http_publication_persists_and_issues_grant_before_destroying_sandbox() -> None:
    events: list[str] = []
    pdf = b"pdf"
    word = b"word"
    content = {
        "reportId": "report-1",
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

    class Persistence:
        async def persist(self, **_values: Any) -> None:
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

    class Workspace:
        async def adestroy(self, thread_id: str) -> bool:
            assert thread_id == "thread"
            events.append("destroy")
            return True

    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.artifact_persistence = Persistence()
    runtime.download_grants = Grants()
    runtime.workspace_service = Workspace()
    result = await runtime.issue_http_publication(
        thread_id="thread",
        user_id="7",
        workflow_session_id="workflow-session",
        workflow_run_id="workflow-run",
        output=content,
    )

    assert events == ["persist", "grant", "destroy"]
    assert result["pdf"]["downloadUrl"] == "/reports/v1/download/raw"


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
    runtime.workspace_service = Workspace()
    content = b"report"
    output = {
        "reportId": "report-1",
        "revision": 1,
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
            user_id="7",
            workflow_session_id="workflow-session",
            workflow_run_id="workflow-run",
            output=output,
        )

    assert raised.value.code == "report_artifact_changed"
    assert events == ["persist"]


@pytest.mark.anyio
async def test_workflow_publication_uses_http_links_when_service_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf = b"pdf"
    word = b"word"
    output = {
        "reportId": "report-1",
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

    assert result.content["pdf"]["downloadUrl"] == "/reports/v1/download/raw"
    runtime.issue_http_publication.assert_awaited_once_with(
        thread_id="thread",
        user_id="native",
        workflow_session_id="thread",
        workflow_run_id="workflow-run",
        output=output,
    )
    runtime.issue_workspace_publication.assert_not_awaited()


@pytest.mark.anyio
async def test_workflow_publication_keeps_workspace_paths_without_http_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = {
        "reportId": "report-1",
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
        thread_id="thread",
        output=output,
    )
    runtime.issue_http_publication.assert_not_awaited()
