"""Editor commits and re-exports the actual successful formats only."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smart_reporting.report_editor import ReportEditorContext
from smart_reporting.reporting.delivery.publishing import ReportDownloadGrant
from smart_reporting.reporting.workflow.state import ReportingRunState
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY

from .test_report_editor_history_restore import _setup
from .test_report_editor_lineage_export import _StateRepository


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize(
    ("formats", "persistence_failure"),
    [
        (("pdf",), None),
        (("word",), None),
        (("pdf", "word"), None),
        (("pdf",), "word"),
        (("word",), "pdf"),
        (("pdf", "word"), "pdf"),
        (("pdf", "word"), "word"),
        (("pdf",), "all"),
        (("word",), "all"),
        (("pdf", "word"), "all"),
    ],
)
@pytest.mark.parametrize("asset_copy_failure", [False, True])
async def test_editor_commits_only_readable_formats_and_can_export_again(
    tmp_path: Path,
    formats: tuple[str, ...],
    asset_copy_failure: bool,
    persistence_failure: str | None,
):
    if persistence_failure in formats and len(formats) == 1:
        pytest.skip(
            "No successful format remains; handled by artifact persistence failure contracts"
        )
    available_formats = set(formats) - {persistence_failure}
    editor, grants, _, current, _ = await _setup(tmp_path)
    old_state = await editor.state_repository.get(current.workflow_run_id)
    durable = ReportingRunState.initial(
        report_run_id=current.workflow_run_id,
        external_run_id="external-1",
        thread_id="caller-thread",
        owner_user_id="user-1",
        payload=old_state.payload,
    )
    repository = _StateRepository(durable, failure=None)
    editor.state_repository = repository
    thread = current.scope["threadId"]
    persisted = []
    issued = []

    class Tools:
        async def _render_report_pair(
            self, job_id, markdown_path, output_path, *, artifact_manifest, run_context
        ):
            source, _ = await editor.workspace.afile_bytes(thread, markdown_path)
            record = {
                "markdown": {
                    "path": markdown_path,
                    "size": len(source),
                    "sha256": hashlib.sha256(source).hexdigest(),
                },
                "images": [],
            }
            for label in formats:
                path = (
                    output_path if label == "pdf" else str(Path(output_path).with_suffix(".docx"))
                )
                raw = b"pdf" if label == "pdf" else b"word"
                await editor.workspace.awrite_bytes(thread, path, raw)
                record[label] = {
                    "path": path,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            run_context.session_state[REPORT_JOBS_STATE_KEY][job_id]["render"] = record
            return {
                "status": "validated" if len(formats) == 2 else "validation_failed",
                "validation": {
                    "ok": len(formats) == 2,
                    "issues": [] if len(formats) == 2 else [{"code": "one_format_failed"}],
                },
            }

    class Persistence:
        async def persist(self, **values):
            persisted.append(values["artifacts"])

    class PartialPersistence(Persistence):
        async def persist_available(self, **values):
            stored = tuple(
                spec
                for spec in values["artifacts"]
                if persistence_failure != "all" and spec.artifact != persistence_failure
            )
            persisted.append(stored)
            return stored

    class DownloadGrants:
        async def issue(self, **values):
            issued.append(values)
            empty = {
                f"{label}_{field}": None
                for label in ("pdf", "word")
                for field in ("path", "size", "sha256")
            }
            return "download-raw", ReportDownloadGrant(
                grant_hash="a" * 64,
                expires_at=datetime(2030, 1, 1, tzinfo=UTC),
                **{**empty, **values},
            )

    editor.report_tools = Tools()
    editor.artifact_persistence = (
        PartialPersistence() if persistence_failure is not None else Persistence()
    )
    editor.download_grants = DownloadGrants()
    editor.editor_grants = grants
    editor.public_base_url = "https://reports.example.com"
    if asset_copy_failure:

        async def fail_copy(*_args, **_kwargs):
            raise OSError("source disappeared after render")

        editor._copy_revision_assets = fail_copy
    document = await editor.read_document(current)
    if persistence_failure == "all":
        from smart_reporting.reporting.models import ReportingError

        with pytest.raises(ReportingError, match="下载副本保存失败") as error:
            await editor.export_revision(current, expected_sha256=document.sha256)
        assert error.value.code == "report_artifact_persistence_failed"
        retained = ReportEditorContext.model_validate(
            repository.durable.payload["reportEditorContexts"]["3"]
        )
        assert retained.job["validation"]["ok"] is False
        assert retained.job["validation"]["issues"]
        assert (
            await editor.workspace.aread_text(thread, retained.markdown_path) == document.markdown
        )
        for label in formats:
            path = retained.job["render"][label]["path"]
            assert (await editor.workspace.afile_bytes(thread, path))[0]
        assert not issued
        # A retry from the original editor link rebases onto the retained context.
        persistence_failure = None
        recovered = await editor.export_revision(current, expected_sha256=document.sha256)
        assert recovered["revision"] == 4
        assert {label for label in ("pdf", "word") if label in recovered} == set(formats)
        assert not list(tmp_path.rglob(".export-*.md"))
        return
    result = await editor.export_revision(current, expected_sha256=document.sha256)
    assert {label for label in ("pdf", "word") if label in result} == available_formats
    assert result["validation"]["ok"] is (len(available_formats) == 2 and not asset_copy_failure)
    context = ReportEditorContext.model_validate(
        repository.durable.payload["reportEditorContexts"]["3"]
    )
    assert {
        label for label in ("pdf", "word") if label in context.job["render"]
    } == available_formats
    assert context.job["validation"]["ok"] == result["validation"]["ok"]
    assert await editor.workspace.aread_text(thread, context.markdown_path) == document.markdown
    assert {spec.artifact for spec in persisted[0]} == available_formats
    assert {label for label in ("pdf", "word") if f"{label}_path" in issued[0]} == available_formats
    second = await editor.export_revision(context, expected_sha256=document.sha256)
    assert second["revision"] == 4
    assert {label for label in ("pdf", "word") if label in second} == available_formats
    assert not list(tmp_path.rglob(".export-*.md"))
