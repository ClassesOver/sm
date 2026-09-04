from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.workflow import Step, Workflow
from daytona.common.errors import DaytonaNotFoundError

from smart_reporting.database import create_agent_database
from smart_reporting.reporting.contract import ReportingWorkflowInput
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.controller import ReportWorkflowController
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.runtime.base import _ReportWorkflowRuntimeBase
from smart_reporting.reporting.workspace import WorkspaceReportService
from smart_reporting.workspace import WorkspaceError


def _integration_database_url() -> str:
    value = os.getenv("REPORTING_TEST_DB_URL", "").strip()
    if not value:
        pytest.skip("未设置 REPORTING_TEST_DB_URL，跳过 PostgreSQL/Agno 集成测试。")
    return value


@pytest.mark.anyio
async def test_report_job_status_tracks_html_artifact_identity() -> None:
    class FakeWorkspace:
        async def ahash_file(self, _thread_id: str, path: str) -> dict[str, object]:
            identities = {
                "reports/report.md": {"size": 1, "sha256": "m"},
                "reports/report.pdf": {"size": 2, "sha256": "p"},
                "reports/report.docx": {"size": 3, "sha256": "w"},
                "reports/report.html": {"size": 4, "sha256": "h-current"},
            }
            return dict(identities[path])

    service = WorkspaceReportService(FakeWorkspace())  # type: ignore[arg-type]
    context = RunContext(run_id="run", session_id="thread", session_state={})
    job = {
        "jobId": "job",
        "sources": [{"path": "reports/report.md", "size": 1, "sha256": "m"}],
        "render": {
            "markdown": {"path": "reports/report.md", "size": 1, "sha256": "m"},
            "pdf": {"path": "reports/report.pdf", "size": 2, "sha256": "p"},
            "word": {"path": "reports/report.docx", "size": 3, "sha256": "w"},
            "html": {"path": "reports/report.html", "size": 4, "sha256": "h-old"},
            "images": [],
        },
    }
    result = await service._job_status(job, context)

    assert result["artifacts"]["html"]["size"] == 4
    assert result["status"] == "artifact_changed"


def test_publication_content_requires_html_identity() -> None:
    payload = {
        "reportId": "report",
        "revision": 1,
        "pdfPath": "reports/report.pdf",
        "pdfSize": 1,
        "pdfSha256": "a" * 64,
        "wordPath": "reports/report.docx",
        "wordSize": 1,
        "wordSha256": "b" * 64,
        "sourceWarnings": [],
        "codingReceipts": [],
    }

    with pytest.raises(ReportingError, match="报表发布产物无效"):
        _ReportWorkflowRuntimeBase._publication_content(payload)


def test_publication_artifact_identity_checks_html_size_and_hash() -> None:
    expected = {
        "htmlSize": 4,
        "htmlSha256": "h" * 64,
    }

    with pytest.raises(ReportingError, match="PDF、Word 或 HTML"):
        _ReportWorkflowRuntimeBase._require_artifact_identity(
            expected, {"size": 5, "sha256": expected["htmlSha256"]}, artifact="html"
        )

    with pytest.raises(ReportingError, match="PDF、Word 或 HTML"):
        _ReportWorkflowRuntimeBase._require_artifact_identity(
            expected, {"size": 4, "sha256": "x" * 64}, artifact="html"
        )


class _ReportPairProcess:
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def exec(self, command: str, **_kwargs: object) -> SimpleNamespace:
        self.commands.append(command)
        return SimpleNamespace(exit_code=0)


class _ReportPairService:
    def __init__(self, identities: dict[str, dict[str, object]]) -> None:
        self.identities = identities
        self.process = _ReportPairProcess()

    def normalize_path(self, path: str, *, allow_root: bool) -> tuple[str, str]:
        assert not allow_root
        return path, f"/home/daytona/workspace/{path}"

    def _shell_command(self, command: str) -> str:
        return command

    @asynccontextmanager
    async def _async_client(self):
        yield object()

    async def _asandbox_for(self, _client: object, _thread_id: str) -> SimpleNamespace:
        return SimpleNamespace(process=self.process)

    async def _aensure_directory(self, _sandbox: object, _path: str) -> None:
        return None

    async def _ainfo(self, _sandbox: object, _path: str) -> None:
        raise DaytonaNotFoundError("missing")

    async def ahash_file(self, _thread_id: str, path: str) -> dict[str, object]:
        return dict(self.identities[path])


def _report_pair_identities(*, staged_html_sha256: str = "html") -> dict[str, dict[str, object]]:
    return {
        "reports/.revision-1.test.tmp/report.pdf": {"size": 1, "sha256": "pdf"},
        "reports/.revision-1.test.tmp/report.docx": {"size": 2, "sha256": "word"},
        "reports/.revision-1.test.tmp/report.html": {
            "size": 3,
            "sha256": staged_html_sha256,
        },
        "reports/revision-1/report.pdf": {"size": 1, "sha256": "pdf"},
        "reports/revision-1/report.docx": {"size": 2, "sha256": "word"},
        "reports/revision-1/report.html": {"size": 3, "sha256": "html"},
    }


@pytest.mark.anyio
async def test_render_report_pair_validates_and_atomically_publishes_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _ReportPairService(_report_pair_identities())
    report_service = WorkspaceReportService(service)  # type: ignore[arg-type]
    context = RunContext(run_id="run", session_id="thread", session_state={})
    job = {"jobId": str(uuid4()), "sources": [{"path": "source.csv"}]}
    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="test"))
    monkeypatch.setattr(report_service, "_load_job", lambda *_args: job)
    monkeypatch.setattr(report_service, "_job_status", AsyncMock(return_value={}))
    monkeypatch.setattr(report_service, "_store_job", Mock())
    monkeypatch.setattr(report_service, "_delete_report_path", AsyncMock())

    async def run_runtime(
        action: str, payload: dict[str, object], _run_context: RunContext
    ) -> dict[str, object]:
        calls.append((action, payload))
        if action == "render_markdown":
            return {
                "status": "rendered",
                "render": {
                    "pdf": {"path": "reports/revision-1/report.pdf", "size": 1, "sha256": "pdf"},
                    "word": {
                        "path": "reports/revision-1/report.docx",
                        "size": 2,
                        "sha256": "word",
                    },
                    "html": {
                        "path": "reports/revision-1/report.html",
                        "size": 3,
                        "sha256": "html",
                    },
                },
            }
        return {
            "ok": True,
            "pdfSha256": "pdf",
            "wordSha256": "word",
            "htmlSha256": "html",
            "htmlSize": 3,
        }

    monkeypatch.setattr(report_service, "_run_report_runtime", run_runtime)

    result = await report_service._render_report_pair(
        job["jobId"],
        "report.md",
        "reports/revision-1/report.pdf",
        artifact_manifest=None,
        run_context=context,
    )

    assert calls[0][1]["html_output_path"] == "reports/revision-1/report.html"
    assert calls[1][1]["html_path"] == "reports/.revision-1.test.tmp/report.html"
    assert any(command.startswith("mv -T --") for command in service.process.commands)
    assert result["htmlPath"] == "reports/revision-1/report.html"
    assert result["htmlSize"] == 3
    assert result["htmlSha256"] == "html"


@pytest.mark.anyio
async def test_render_report_pair_html_hash_mismatch_does_not_publish_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _ReportPairService(_report_pair_identities(staged_html_sha256="changed"))
    report_service = WorkspaceReportService(service)  # type: ignore[arg-type]
    context = RunContext(run_id="run", session_id="thread", session_state={})
    job = {"jobId": str(uuid4()), "sources": [{"path": "source.csv"}]}
    store_job = Mock()

    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="test"))
    monkeypatch.setattr(report_service, "_load_job", lambda *_args: job)
    monkeypatch.setattr(report_service, "_job_status", AsyncMock(return_value={}))
    monkeypatch.setattr(report_service, "_store_job", store_job)
    monkeypatch.setattr(report_service, "_delete_report_path", AsyncMock())
    monkeypatch.setattr(
        report_service,
        "_run_report_runtime",
        AsyncMock(
            return_value={
                "status": "rendered",
                "render": {
                    "pdf": {"path": "reports/revision-1/report.pdf", "size": 1, "sha256": "pdf"},
                    "word": {
                        "path": "reports/revision-1/report.docx",
                        "size": 2,
                        "sha256": "word",
                    },
                    "html": {
                        "path": "reports/revision-1/report.html",
                        "size": 3,
                        "sha256": "html",
                    },
                },
            }
        ),
    )

    with pytest.raises(WorkspaceError, match="三格式报告暂存身份校验失败"):
        await report_service._render_report_pair(
            job["jobId"],
            "report.md",
            "reports/revision-1/report.pdf",
            artifact_manifest=None,
            run_context=context,
        )

    assert not any(command.startswith("mv -T --") for command in service.process.commands)
    store_job.assert_not_called()


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_mcp_request_fingerprint_is_immutable() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    external_run_id = f"integration-mcp-request-{suffix}"
    values = {
        "external_run_id": external_run_id,
        "request_fingerprint": "a" * 64,
        "thread_id": f"integration-thread-{suffix}",
        "owner_user_id": "integration-user",
        "database": "integration-db",
        "company_id": "11",
    }

    created = await first.register_external_request(**values)
    replayed = await second.register_external_request(**{**values, "request_fingerprint": "b" * 64})

    assert created == values
    assert replayed == values


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_owner_claim_release_matrix() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-thread-{suffix}"
    first_run_id = f"integration-run-a-{suffix}"
    second_run_id = f"integration-run-b-{suffix}"

    assert await first.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert not await second.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert not await second.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    assert await second.ensure_workflow_thread_owner(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert not await second.ensure_workflow_thread_owner(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    owner = await second.get_workflow_thread_owner(thread_id)
    assert owner is not None
    assert owner["external_run_id"] == first_run_id

    assert not await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    assert await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=first_run_id,
        owner_user_id="integration-user",
    )
    assert await second.claim_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )
    assert await second.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=second_run_id,
        owner_user_id="integration-user",
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_concurrent_owner_claim_has_single_winner() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-thread-race-{suffix}"
    run_ids = (f"integration-run-a-{suffix}", f"integration-run-b-{suffix}")

    results = await asyncio.gather(
        first.claim_workflow_thread(
            thread_id=thread_id,
            external_run_id=run_ids[0],
            owner_user_id="integration-user",
        ),
        second.claim_workflow_thread(
            thread_id=thread_id,
            external_run_id=run_ids[1],
            owner_user_id="integration-user",
        ),
    )

    assert sorted(results) == [False, True]
    owner = await first.get_workflow_thread_owner(thread_id)
    assert owner is not None
    winner = run_ids[results.index(True)]
    assert owner["external_run_id"] == winner
    assert await first.release_workflow_thread(
        thread_id=thread_id,
        external_run_id=winner,
        owner_user_id="integration-user",
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_execution_lock_matrix() -> None:
    database = create_agent_database(_integration_database_url())
    first = ReportingStateRepository(database.async_db)
    second = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    first_run_id = f"integration-lock-a-{suffix}"
    second_run_id = f"integration-lock-b-{suffix}"

    async with first.workflow_execution_lock(first_run_id):
        assert await second.is_workflow_run_active(first_run_id)
        assert not await second.is_workflow_run_active(second_run_id)
        async with second.workflow_execution_lock(second_run_id):
            assert await first.is_workflow_run_active(second_run_id)

    assert not await second.is_workflow_run_active(first_run_id)
    assert not await first.is_workflow_run_active(second_run_id)


@pytest.mark.integration
@pytest.mark.anyio
async def test_reporting_postgres_controller_releases_owner_after_deferred_sandbox_cleanup() -> (
    None
):
    database = create_agent_database(_integration_database_url())
    repository = ReportingStateRepository(database.async_db)
    suffix = uuid4().hex
    thread_id = f"integration-deferred-cleanup-{suffix}"
    run_calls = 0

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *_args, **_kwargs):
            nonlocal run_calls
            run_calls += 1
            if run_calls == 1:
                raise RuntimeError("materialize failed")
            return SimpleNamespace(status=RunStatus.completed)

    async def cleanup(*_args, **_kwargs) -> None:
        raise ReportingError(
            "report_sandbox_cleanup_failed",
            "失败运行环境已隔离并转入后台清理。",
        )

    controller = ReportWorkflowController(
        lambda: Workflow(),
        thread_ownership=repository,
        terminal_cleanup=cleanup,
    )
    first_context = RunContext(
        run_id=f"integration-run-a-{suffix}",
        session_id=thread_id,
        user_id="integration-user",
        session_state={},
    )
    second_context = RunContext(
        run_id=f"integration-run-b-{suffix}",
        session_id=thread_id,
        user_id="integration-user",
        session_state={},
    )

    try:
        with pytest.raises(RuntimeError, match="materialize failed"):
            await controller.start(ReportingWorkflowInput(prompt="第一次运行"), first_context)
        assert await repository.get_workflow_thread_owner(thread_id) is None

        result = await controller.start(ReportingWorkflowInput(prompt="第二次运行"), second_context)

        assert result["status"] == "completed"
        assert run_calls == 2
        assert await repository.get_workflow_thread_owner(thread_id) is None
    finally:
        await repository.release_workflow_thread(
            thread_id=thread_id,
            external_run_id=str(first_context.run_id),
            owner_user_id="integration-user",
        )
        await repository.release_workflow_thread(
            thread_id=thread_id,
            external_run_id=str(second_context.run_id),
            owner_user_id="integration-user",
        )
        await database.async_engine.dispose()
        database.sync_engine.dispose()


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_agno_workflow_persists_and_reads_reporting_run() -> None:
    database = create_agent_database(_integration_database_url())
    session_id = f"integration-session-{uuid4().hex}"
    run_id = f"integration-run-{uuid4().hex}"

    async def execute(step_input):
        return f"ok:{step_input.input}"

    workflow = Workflow(
        id="enterprise-reporting-workflow-v1",
        name="集成测试报表工作流",
        db=database.async_db,
        steps=[Step(name="integration-step", executor=execute)],
    )
    output = await workflow.arun(
        "integration",
        run_id=run_id,
        session_id=session_id,
        user_id="integration-user",
        stream=False,
    )
    restored = await workflow.aget_run(run_id, session_id=session_id)

    assert output.status.value == "COMPLETED"
    assert restored is not None
    assert restored.run_id == run_id
    assert getattr(restored.status, "value", restored.status) == "COMPLETED"
