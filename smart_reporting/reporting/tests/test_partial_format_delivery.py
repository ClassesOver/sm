"""Partial format delivery preserves actual identities, never an unavailable link."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.reporting.delivery.publishing import (
    ReportDownloadHttpService,
    create_report_download_router,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin
from smart_reporting.reporting.workspace import WorkspaceReportService
from smart_reporting.workspace import WorkspaceError

from .test_http_publication_lineage import _publication_fixture
from .test_reporting_integration import _report_pair_identities, _ReportPairService


@pytest.mark.anyio
@pytest.mark.parametrize("available", ["pdf", "word"])
async def test_partial_format_is_persisted_and_downloadable_after_workspace_release(
    tmp_path, available
):
    runtime, arguments, scope, _, artifacts, _, files, _ = await _publication_fixture(tmp_path)
    missing = "word" if available == "pdf" else "pdf"
    for suffix in ("Path", "Size", "Sha256"):
        arguments["output"].pop(f"{missing}{suffix}")
    result = await runtime.issue_http_publication(**arguments)
    assert available in result and missing not in result
    assert {artifact.artifact for artifact in artifacts.records.values()} == {available}
    app = FastAPI()
    app.include_router(
        create_report_download_router(ReportDownloadHttpService(runtime.download_grants, artifacts))
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(result[available]["downloadUrl"])
        assert response.status_code == 200
        assert (
            response.content == files[f"reports/report.{'pdf' if available == 'pdf' else 'docx'}"]
        )
        token = result[available]["downloadUrl"].split("/download/")[1].split("/")[0]
        missing_url = f"/reports/v1/download/{token}" + ("/word" if missing == "word" else "")
        response = await client.get(missing_url)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "report_artifact_unavailable"


@pytest.mark.anyio
@pytest.mark.parametrize("available", ["pdf", "word"])
async def test_workspace_pair_promotes_only_identity_checked_successful_format(
    monkeypatch, available
):
    import uuid

    service = _ReportPairService(_report_pair_identities())
    report = WorkspaceReportService(service)
    context = RunContext(run_id="run", session_id="thread", session_state={})
    job = {"jobId": "job-1", "sources": []}
    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="test"))
    monkeypatch.setattr(report, "_load_job", lambda *_args: job)
    monkeypatch.setattr(report, "_job_status", AsyncMock(return_value={}))
    monkeypatch.setattr(report, "_delete_report_path", AsyncMock())
    identity = service.identities[
        f"reports/.revision-1.test.tmp/report.{'pdf' if available == 'pdf' else 'docx'}"
    ]
    staged_path = f"reports/.revision-1.test.tmp/report.{'pdf' if available == 'pdf' else 'docx'}"
    render = {
        "markdown": {"path": "report.md", "size": 1, "sha256": "markdown"},
        "images": [],
        available: {**identity, "path": staged_path},
        "renderIssues": [{"code": "report_format_unavailable", "message": "injected"}],
    }
    report._run_report_runtime = AsyncMock(
        return_value={"status": "partial_rendered", "render": render}
    )
    result = await report._render_report_pair(
        "job-1",
        "report.md",
        "reports/revision-1/report.pdf",
        artifact_manifest=None,
        run_context=context,
    )
    assert result["validation"]["ok"] is False
    assert result["status"] == "validation_failed"
    assert result[f"{available}Path"].startswith("reports/revision-1/")
    assert f"{'word' if available == 'pdf' else 'pdf'}Path" not in result
    report._run_report_runtime.assert_awaited_once()
    assert service.fs.moves
    report._delete_report_path.assert_any_await(
        "reports/.revision-1.test.tmp", context, recursive=True
    )


@pytest.mark.anyio
@pytest.mark.parametrize("failed", ["pdf", "word"])
async def test_workspace_pair_retains_other_format_when_final_identity_fails(
    monkeypatch: pytest.MonkeyPatch, failed: str,
) -> None:
    import uuid

    identities = _report_pair_identities()
    final_paths = {
        "pdf": "reports/revision-1/report.pdf",
        "word": "reports/revision-1/report.docx",
    }
    identities[final_paths[failed]]["sha256"] = "changed"
    service = _ReportPairService(identities)
    service.adelete_file = AsyncMock()
    report = WorkspaceReportService(service)
    context = RunContext(run_id="run", session_id="thread", session_state={})
    job = {"jobId": "job-1", "sources": []}
    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="test"))
    monkeypatch.setattr(report, "_load_job", lambda *_args: job)
    monkeypatch.setattr(report, "_job_status", AsyncMock(return_value={}))
    monkeypatch.setattr(report, "_delete_report_path", AsyncMock())
    staged_paths = {
        "pdf": "reports/.revision-1.test.tmp/report.pdf",
        "word": "reports/.revision-1.test.tmp/report.docx",
    }
    render = {
        "markdown": {"path": "report.md", "size": 1, "sha256": "markdown"},
        "images": [],
        **{
            label: {**identities[path], "path": path}
            for label, path in staged_paths.items()
        },
    }
    report._run_report_runtime = AsyncMock(side_effect=[
        {"status": "rendered", "render": render},
        {
            "ok": True,
            "status": "validated",
            "issues": [],
            "pdfPath": staged_paths["pdf"],
            "pdfSha256": "pdf",
            "wordPath": staged_paths["word"],
            "wordSha256": "word",
        },
    ])

    result = await report._render_report_pair(
        "job-1",
        "report.md",
        final_paths["pdf"],
        artifact_manifest=None,
        run_context=context,
    )

    available = "word" if failed == "pdf" else "pdf"
    assert result["status"] == "validation_failed"
    assert result["validation"]["ok"] is False
    assert result["validation"]["status"] == "validation_failed"
    assert [item["code"] for item in result["validation"]["issues"]] == [
        f"report_{failed}_artifact_unavailable"
    ]
    assert result[f"{available}Path"] == final_paths[available]
    assert f"{failed}Path" not in result
    assert f"{failed}Path" not in result["validation"]
    assert f"{failed}Sha256" not in result["validation"]
    assert result["validation"][f"{available}Path"] == final_paths[available]
    stored_job = context.session_state["report_jobs"]["job-1"]
    assert available in stored_job["render"] and failed not in stored_job["render"]
    service.adelete_file.assert_awaited_once_with("thread", final_paths[failed])
    assert not any(
        call.args[0] == "reports/revision-1"
        for call in report._delete_report_path.await_args_list
    )


@pytest.mark.anyio
async def test_workspace_pair_cleans_revision_when_all_final_identities_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    identities = _report_pair_identities()
    final_paths = {
        "pdf": "reports/revision-1/report.pdf",
        "word": "reports/revision-1/report.docx",
    }
    for path in final_paths.values():
        identities[path]["sha256"] = "changed"
    service = _ReportPairService(identities)
    service.adelete_file = AsyncMock()
    report = WorkspaceReportService(service)
    context = RunContext(run_id="run", session_id="thread", session_state={})
    job = {"jobId": "job-1", "sources": []}
    monkeypatch.setattr(uuid, "uuid4", lambda: SimpleNamespace(hex="test"))
    monkeypatch.setattr(report, "_load_job", lambda *_args: job)
    monkeypatch.setattr(report, "_job_status", AsyncMock(return_value={}))
    monkeypatch.setattr(report, "_delete_report_path", AsyncMock())
    staged_paths = {
        "pdf": "reports/.revision-1.test.tmp/report.pdf",
        "word": "reports/.revision-1.test.tmp/report.docx",
    }
    report._run_report_runtime = AsyncMock(side_effect=[
        {
            "status": "rendered",
            "render": {
                label: {**identities[path], "path": path}
                for label, path in staged_paths.items()
            },
        },
        {"ok": True, "issues": []},
    ])

    with pytest.raises(WorkspaceError, match="没有可读取身份的格式"):
        await report._render_report_pair(
            "job-1",
            "report.md",
            final_paths["pdf"],
            artifact_manifest=None,
            run_context=context,
        )

    assert {call.args[1] for call in service.adelete_file.await_args_list} == set(
        final_paths.values()
    )
    report._delete_report_path.assert_any_await(
        "reports/revision-1", context, recursive=True
    )


@pytest.mark.anyio
@pytest.mark.parametrize("available", ["pdf", "word", None])
async def test_failed_validation_retains_independent_identity_and_clears_missing_format(available):
    runtime = object.__new__(RuntimePublicationMixin)
    state = {}
    runtime._state = lambda _: state
    runtime._scope = lambda _: {"threadId": "thread"}

    async def identity(_, path):
        if available is not None and path.endswith("pdf" if available == "pdf" else "docx"):
            return {"path": path, "size": 3, "sha256": "a" * 64}
        raise OSError("missing format")

    runtime.workspace_service = SimpleNamespace(ahash_file=identity)
    result = {
        "pdfPath": "stale.pdf",
        "pdfSize": 99,
        "pdfSha256": "b" * 64,
        "wordPath": "stale.docx",
        "wordSize": 99,
        "wordSha256": "b" * 64,
    }
    if available is None:
        with pytest.raises(ReportingError, match="没有可读取"):
            await runtime._retain_rendered_report(
                None,
                result,
                "reports/report.pdf",
                "reports/report.docx",
                {"ok": False, "issues": []},
            )
    else:
        result = await runtime._retain_rendered_report(
            None, result, "reports/report.pdf", "reports/report.docx", {"ok": False, "issues": []}
        )
        assert result["validation"]["ok"] is False
        assert result[f"{available}Sha256"] == "a" * 64
        assert f"{'word' if available == 'pdf' else 'pdf'}Path" not in result
