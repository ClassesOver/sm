"""Historical restoration: atomic draft CAS, recoverable provenance, and authorization."""
from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import (
    ReportEditorContext,
    ReportEditorService,
    create_report_editor_router,
)
from smart_reporting.reporting.delivery.publishing import ReportDownloadGrant
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_report_editor_lineage_export import _StateRepository
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.contracts_v1 import (
    DrilldownDimensionV1,
    DrilldownMetricV1,
)
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.state import ReportingRunState
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY


async def _setup(tmp_path: Path):
    editor, grants, historical = await _make_editor_with_subject(tmp_path)
    workspace = editor.workspace
    thread = historical.scope["threadId"]
    historical_index = await editor.trace.load_index(historical)
    assert historical_index is not None
    historical_index = historical_index.model_copy(
        update={
            "drilldown_metrics": (
                DrilldownMetricV1(
                    metricCode="income_total",
                    datasetId="dataset-url-abc0001",
                    aggregation="sum",
                    valueField="revenue",
                    dimensions=(
                        DrilldownDimensionV1(
                            code="period", field="period", label="期间"
                        ),
                    ),
                    expectedValue=3600.0,
                    unit="万元",
                    factKeys=("fact-" + "a" * 16,),
                ),
            )
        }
    )
    await workspace.awrite_bytes(
        thread,
        "reports/revision-1/trace-index-v1.json",
        encode_trace_index(historical_index),
        overwrite=True,
    )
    await workspace.adelete_file(thread, historical.artifact_manifest.path)
    manifest_identity = await register_trace_manifest(
        workspace, thread, historical_index
    )
    historical = historical.model_copy(
        update={"artifact_manifest": manifest_identity}
    )
    old = await workspace.aread_text(thread, historical.markdown_path)
    current = historical.model_copy(update={
        "revision": 2, "markdown_path": "reports/revision-2/report.md",
        "artifact_manifest": None,
        "job": {"jobId": historical.job_id, "render": {
            "pdf": {"path": "reports/revision-2/report.pdf"}}},
    })
    await workspace.awrite_text(thread, current.markdown_path, "# Current report\n")
    state = SimpleNamespace(payload={"reportEditorContexts": {
        "1": historical.model_dump(mode="json", by_alias=True),
        "2": current.model_dump(mode="json", by_alias=True),
    }})
    editor.state_repository = SimpleNamespace(get=AsyncMock(return_value=state))
    return editor, grants, historical, current, old


@pytest.mark.anyio
async def test_restore_frozen_history_survives_restart_save_and_conflict(tmp_path: Path):
    editor, grants, historical, current, old = await _setup(tmp_path)
    thread = current.scope["threadId"]
    await editor.workspace.awrite_text(thread, "reports/revision-1/draft/report.md", "wrong historical draft")
    before = await editor.read_document(current)
    digest = current.digest()
    restored = await editor.restore_history(current, 1, expected_sha256=before.sha256)
    assert restored.markdown == old
    assert restored.source_revision == 1
    assert current.digest() == digest
    assert (await editor.read_history_revision(current, 1))["markdown"] == old
    restarted = ReportEditorService(
        state_repository=editor.state_repository, workspace_registry=editor.workspace_registry,
        workspace=editor.workspace,
    )
    assert (await restarted.read_document(current)).source_revision == 1
    raw, _ = await grants.issue(current)
    _, session = await grants.exchange(raw)
    assert (await restarted.context_for_session(session)) == current
    assert (await restarted.trace_sources(current, session))["revision"] == 1
    drilldown = await restarted.trace_drilldown_metric(
        current,
        session,
        "income_total",
        dataset_id="dataset-url-abc0001",
        dimension_code="period",
    )
    assert drilldown["rows"] == [{"group": "2025-09", "value": 3600.0}]
    assert drilldown["reconciliation"]["passed"] is True
    validation = await restarted.trace_validate(current, session, old, restored.sha256)
    assert validation["draftSha256"] == restored.sha256
    saved = await restarted.save_draft(current, markdown=old + "\nEdited\n", expected_sha256=restored.sha256)
    assert saved.source_revision == 1
    origin_path = "reports/revision-2/draft/.report.md.origin.json"
    origin = await editor.workspace.aread_text(thread, origin_path)
    with pytest.raises(ReportingError) as error:
        await restarted.restore_history(current, 2, expected_sha256=before.sha256)
    assert error.value.code == "report_editor_conflict"
    assert await editor.workspace.aread_text(thread, origin_path) == origin
    assert (await restarted.read_document(current)).sha256 == saved.sha256
    with pytest.raises(ReportingError) as error:
        await restarted.restore_history(current, 999, expected_sha256=saved.sha256)
    assert error.value.code == "report_editor_history_missing"


@pytest.mark.anyio
async def test_restore_integrity_failure_does_not_write_draft(tmp_path: Path):
    editor, _, historical, current, _ = await _setup(tmp_path)
    before = await editor.read_document(current)
    await editor.workspace.awrite_text(current.scope["threadId"], historical.markdown_path, "tampered", overwrite=True)
    with pytest.raises(ReportingError) as error:
        await editor.restore_history(current, 1, expected_sha256=before.sha256)
    assert error.value.code == "snapshot_integrity_failed"
    assert await editor.read_document(current) == before
    assert not await editor.workspace.apath_exists(current.scope["threadId"], "reports/revision-2/draft/.report.md.origin.json")


@pytest.mark.anyio
async def test_restore_http_contract_uses_current_session_origin_csrf_and_cas(tmp_path: Path):
    editor, grants, _, current, old = await _setup(tmp_path)
    raw, _ = await grants.issue(current)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    base = "/reports/v1/editor/report-1/2/api"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        loaded = (await client.get(base + "/document")).json()
        payload = {"expectedSha256": loaded["sha256"]}
        endpoint = base + "/history/1/restore"
        assert (await client.post(endpoint, json=payload)).status_code == 403
        headers = {"Origin": "http://reports.test", "X-CSRF-Token": loaded["csrfToken"]}
        assert (await client.post(endpoint, json=payload, headers={**headers, "Origin": "http://other.test"})).status_code == 403
        response = await client.post(endpoint, json=payload, headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["markdown"] == old and body["sourceRevision"] == 1
        assert body["csrfToken"] == loaded["csrfToken"]
        assert body["sha256"] == hashlib.sha256(old.encode()).hexdigest()
        assert (await client.get(base + "/document")).json()["sourceRevision"] == 1
        edited = old + "\nEdited through HTTP\n"
        saved = await client.put(base + "/document", json={
            "markdown": edited, "expectedSha256": body["sha256"],
        }, headers=headers)
        assert saved.status_code == 200
        assert saved.json()["sourceRevision"] == 1
        assert saved.json()["markdown"] == edited
        assert saved.json()["sha256"] == hashlib.sha256(edited.encode()).hexdigest()
        assert (await client.get(base + "/document")).json()["sha256"] == saved.json()["sha256"]
        assert (await client.post(endpoint, json=payload, headers=headers)).status_code == 409
        assert (await client.get("/reports/v1/editor/report-1/1/api/sources")).status_code == 404


@pytest.mark.anyio
async def test_restore_then_export_uses_historical_lineage_for_target_revision(tmp_path: Path):
    editor, grants, historical, current, old = await _setup(tmp_path)
    thread = current.scope["threadId"]
    before = await editor.read_document(current)
    restored = await editor.restore_history(current, 1, expected_sha256=before.sha256)
    assert restored.source_revision == 1

    editor.state_repository = _StateRepository(ReportingRunState.initial(
        report_run_id=current.workflow_run_id, external_run_id="external-1",
        thread_id="caller-thread", owner_user_id="user-1",
        payload=(await editor.state_repository.get(current.workflow_run_id)).payload,
    ), failure=None)
    rendered: list[str] = []

    class Tools:
        async def _render_report_pair(self, job_id, markdown_path, output_path, *, artifact_manifest, run_context):
            rendered.append(output_path)
            assert job_id == current.job_id
            assert markdown_path.startswith("reports/revision-1/.export-")
            assert artifact_manifest["revision"] == 3
            assert artifact_manifest["citations"]
            assert artifact_manifest["markdown"]["sha256"] == restored.sha256
            await editor.workspace.awrite_bytes(thread, output_path, b"pdf")
            await editor.workspace.awrite_bytes(thread, output_path.replace(".pdf", ".docx"), b"word")
            stored = run_context.session_state[REPORT_JOBS_STATE_KEY][job_id]
            stored["render"] = {"markdown": {"path": markdown_path, "size": len(old.encode()),
                                               "sha256": restored.sha256},
                                "pdf": {"path": output_path, "size": 3, "sha256": hashlib.sha256(b"pdf").hexdigest()},
                                "word": {"path": output_path.replace(".pdf", ".docx"), "size": 4,
                                         "sha256": hashlib.sha256(b"word").hexdigest()}, "images": []}
            return {"validation": {"ok": True}}

    class Persistence:
        async def persist(self, **_kwargs): return None

    class Downloads:
        async def issue(self, **kwargs):
            return "download", ReportDownloadGrant(
                grant_hash="d" * 64, expires_at=datetime(2026, 10, 15, tzinfo=UTC), **kwargs
            )

    class EditorGrants:
        async def issue(self, _context): return "editor", datetime(2026, 10, 15, tzinfo=UTC)

    editor.report_tools = Tools()
    editor.artifact_persistence = Persistence()
    editor.download_grants = Downloads()
    editor.editor_grants = EditorGrants()
    editor.public_base_url = "https://reports.example.com"
    result = await editor.export_revision(current, expected_sha256=restored.sha256)
    assert result["revision"] == 3
    assert rendered == ["reports/revision-3/report.pdf"]
    stored = await editor.state_repository.get(current.workflow_run_id)
    next_context = ReportEditorContext.model_validate(stored.payload["reportEditorContexts"]["3"])
    next_index = await editor.trace.load_index(next_context)
    historical_index = await editor.trace.load_index(historical)
    assert next_index.revision == 3
    assert next_index.drilldown_metrics == historical_index.drilldown_metrics
    assert [item.model_dump(exclude={"file_resource_id"}) for item in next_index.datasets] == [
        item.model_dump(exclude={"file_resource_id"}) for item in historical_index.datasets
    ]
    files = {item.resource_id: item for item in next_index.files}
    old_files = {item.resource_id: item for item in historical_index.files}
    for new, prior in zip(next_index.datasets, historical_index.datasets, strict=True):
        new_file, old_file = files[new.file_resource_id], old_files[prior.file_resource_id]
        assert new_file.sha256 == old_file.sha256
        assert new_file.path.startswith("reports/revision-3/")
        assert (await editor.workspace.afile_bytes(thread, new_file.path))[0] == (
            await editor.workspace.afile_bytes(thread, old_file.path)
        )[0]
    assert [(item.subject_id, item.subject_sha256) for item in next_index.subject_bindings] == [
        (item.subject_id, item.subject_sha256) for item in historical_index.subject_bindings
    ]
    assert next_context.job_id == current.job_id
    assert next_context.artifact_manifest is not None
    assert await editor.workspace.aread_text(thread, "reports/revision-3/report.md") == old
    drilldown = await editor.trace.drilldown_metric(
        next_context,
        None,
        "income_total",
        dataset_id="dataset-url-abc0001",
        dimension_code="period",
    )
    assert drilldown["rows"] == [{"group": "2025-09", "value": 3600.0}]
    assert drilldown["reconciliation"]["passed"] is True

@pytest.mark.anyio
async def test_pending_origin_recovers_before_or_after_markdown_commit(tmp_path: Path):
    editor, _, historical, current, old = await _setup(tmp_path)
    before = await editor.read_document(current)
    record = {"contextSha256": current.digest(), "active": {
        "sha256": before.sha256, "sourceRevision": 2, "sourceContextSha256": current.digest(),
    }, "pending": {"sha256": hashlib.sha256(old.encode()).hexdigest(),
                   "sourceRevision": 1, "sourceContextSha256": historical.digest()}}
    thread = current.scope["threadId"]
    await editor.workspace.awrite_text(thread, "reports/revision-2/draft/.report.md.origin.json", json.dumps(record))
    assert (await editor.read_document(current)).source_revision == 2
    await editor.workspace.awrite_text(thread, "reports/revision-2/draft/report.md", old)
    assert (await editor.read_document(current)).source_revision == 1


def _save_in_worker(root, context_payload, state_payload, expected_sha, markdown, ready, finished, results):
    async def run():
        registry = ReportingWorkspaceRegistry(root, secret="s" * 32)
        service = ReportEditorService(
            state_repository=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(payload=state_payload))),
            workspace_registry=registry, workspace=ReportingWorkspaceRouter(registry),
        )
        context = ReportEditorContext.model_validate(context_payload)
        ready.set()
        try:
            saved = await service.save_draft(context, markdown=markdown, expected_sha256=expected_sha)
            results.put(("saved", saved.sha256, saved.source_revision))
        except ReportingError as error:
            results.put(("error", error.code, None))
        finally:
            finished.set()

    asyncio.run(run())


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_process_workers_serialize_restored_draft_and_provenance(tmp_path: Path):
    """独立进程等待同一锁，CAS 失败者不能覆盖获胜者的来源 sidecar。"""
    editor, _, _, current, old = await _setup(tmp_path)
    before = await editor.read_document(current)
    restored = await editor.restore_history(current, 1, expected_sha256=before.sha256)
    state = (await editor.state_repository.get(current.workflow_run_id)).payload
    processes = multiprocessing.get_context("spawn")
    results = processes.Queue()
    workers = []
    try:
        async with editor._draft_lock(current):
            for suffix in ("worker A", "worker B"):
                ready, finished = processes.Event(), processes.Event()
                process = processes.Process(target=_save_in_worker, args=(
                    tmp_path, current.model_dump(mode="json", by_alias=True), state,
                    restored.sha256, old + f"\n{suffix}\n", ready, finished, results,
                ))
                workers.append((process, ready, finished))
                process.start()
            for _process, ready, finished in workers:
                assert await asyncio.to_thread(ready.wait, 30)
                assert not await asyncio.to_thread(finished.wait, 0.2)
        outcomes = [await asyncio.to_thread(results.get, True, 30) for _ in workers]
        assert sorted(item[0] for item in outcomes) == ["error", "saved"]
        assert next(item[1] for item in outcomes if item[0] == "error") == "report_editor_conflict"
        saved = await editor.read_document(current)
        assert saved.source_revision == 1
        assert saved.sha256 == next(item[1] for item in outcomes if item[0] == "saved")
        assert saved.markdown in (old + "\nworker A\n", old + "\nworker B\n")
        for process, _ready, _finished in workers:
            await asyncio.to_thread(process.join, 10)
            assert process.exitcode == 0
    finally:
        for process, _ready, _finished in workers:
            if process.is_alive():
                process.terminate()
                await asyncio.to_thread(process.join, 5)
        results.close()
        results.join_thread()


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_cancelled_cross_service_lock_wait_does_not_block_next_save(tmp_path: Path):
    editor, _, _, current, _ = await _setup(tmp_path)
    before = await editor.read_document(current)
    other = ReportEditorService(
        state_repository=editor.state_repository, workspace_registry=editor.workspace_registry,
        workspace=editor.workspace,
    )
    async with editor._draft_lock(current):
        pending = asyncio.create_task(other.save_draft(
            current, markdown="# cancelled\n", expected_sha256=before.sha256,
        ))
        await asyncio.sleep(0.1)
        assert not pending.done()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    saved = await asyncio.wait_for(other.save_draft(
        current, markdown="# next save\n", expected_sha256=before.sha256,
    ), timeout=5)
    assert saved.markdown == "# next save\n"
    assert (await editor.read_document(current)).sha256 == saved.sha256
