"""版本保留策略独立于下载授权，使用真实耐久 reducer 验证。"""

import asyncio
import hashlib
import io
import json
import multiprocessing
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor import ReportEditorService
from smart_reporting.report_editor.trace_retention import SourceFileResponse, source_lifecycle_lock
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.lineage_fixtures.manifest import register_trace_manifest
from smart_reporting.reporting.tests.test_report_editor_lineage_export import _StateRepository
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.trace.contracts_v1 import (
    ChartTraceV1,
    TraceFileRefV1,
    derive_resource_id,
)
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.workflow.state import (
    ReportingCommand,
    ReportingPhase,
    ReportingRunState,
    ReportingStateError,
)
from smart_reporting.workspace import WorkspaceError


def _hold_source_lock_in_process(root, connection):
    async def restore(expected):
        return expected

    async def run():
        service = SimpleNamespace(_restore=restore, _source_lifecycle_locks={},
            workspace_registry=SimpleNamespace(get=lambda _: SimpleNamespace(root=root)))
        async with source_lifecycle_lock(service, SimpleNamespace(scope={"threadId": "worker"})):
            connection.send("locked")
            await asyncio.to_thread(connection.recv)
        connection.send("released")

    try:
        asyncio.run(run())
    finally:
        connection.close()


@pytest.mark.anyio
async def test_revision_retention_is_durable_identity_bound_and_reversible(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path)
    existing = await editor.state_repository.get(context.workflow_run_id)
    repository = _StateRepository(ReportingRunState.initial(
        report_run_id=context.workflow_run_id, external_run_id="external-1",
        thread_id="caller-thread", owner_user_id="user-1", payload=existing.payload,
    ), failure=None)
    editor.state_repository = repository
    assert "reportEditorRetention" not in repository.durable.payload
    await repository.apply(context.workflow_run_id, ReportingCommand(
        name="set_report_editor_context", commandId="existing-context",
        payload={"context": context.model_dump(mode="json", by_alias=True)},
    ), expected_version=repository.durable.state_version)
    digest = context.digest()
    deadline = datetime(2026, 11, 1, tzinfo=UTC)
    await editor.set_revision_retention(context, expires_at=deadline)
    record = {"contextSha256": digest, "expiresAt": deadline.isoformat()}
    assert repository.durable.payload["reportEditorRetention"]["1"] == record
    restarted = ReportEditorService(state_repository=repository,
        workspace_registry=editor.workspace_registry, workspace=editor.workspace)
    assert (await restarted.read_document(context)).markdown
    await restarted.set_revision_retention(context, expires_at=None)
    await restarted.set_revision_retention(context, expires_at=deadline + timedelta(days=1))
    await restarted.set_revision_retention(context, expires_at=None)
    assert repository.durable.payload["reportEditorRetention"]["1"] == {
        "contextSha256": digest, "expiresAt": None,
    }
    assert (await restarted._restore(context)).digest() == digest
    before = repository.durable
    with pytest.raises(ReportingError, match="时区"):
        await restarted.set_revision_retention(context, expires_at=datetime(2026, 11, 1))
    assert repository.durable == before
    with pytest.raises(ReportingStateError, match="保留策略"):
        await repository.apply(context.workflow_run_id, ReportingCommand(
            name="set_report_editor_retention", commandId="missing-deadline",
            payload={"context": context.model_dump(mode="json", by_alias=True)},
        ), expected_version=before.state_version)
    for expires_at in ("bad", "2026-11-01T00:00:00"):
        with pytest.raises(ReportingStateError):
            await repository.apply(context.workflow_run_id, ReportingCommand(
                name="set_report_editor_retention", commandId="invalid-" + expires_at,
                payload={"context": context.model_dump(mode="json", by_alias=True), "expiresAt": expires_at},
            ), expected_version=before.state_version)
        assert repository.durable == before
    altered = context.model_copy(update={"note": "other identity"})
    with pytest.raises(ReportingStateError, match="身份"):
        await repository.apply(context.workflow_run_id, ReportingCommand(
            name="set_report_editor_retention", commandId="wrong-context",
            payload={"context": altered.model_dump(mode="json", by_alias=True), "expiresAt": None},
        ), expected_version=before.state_version)
    assert repository.durable == before


async def _replace_registered_index(editor, context, index):
    manifest = await editor.trace.load_manifest(context)
    content = encode_trace_index(index)
    index_identity = manifest.trace_index.model_copy(update={
        "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
    })
    thread = context.scope["threadId"]
    await editor.workspace.awrite_bytes(thread, index_identity.path, content, overwrite=True)
    content = manifest.model_copy(update={"trace_index": index_identity}).model_dump_json(by_alias=True).encode()
    await editor.workspace.awrite_bytes(thread, context.artifact_manifest.path, content, overwrite=True)
    return ArtifactFile(path=context.artifact_manifest.path, mediaType="application/json",
        size=len(content), sha256=hashlib.sha256(content).hexdigest())


async def _make_shared_revisions(tmp_path):
    editor, _, context = await _make_editor_with_subject(tmp_path)
    existing = await editor.state_repository.get(context.workflow_run_id)
    repository = _StateRepository(ReportingRunState.initial(
        report_run_id=context.workflow_run_id, external_run_id="external-1",
        thread_id="caller-thread", owner_user_id="user-1", payload=existing.payload,
    ), failure=None)
    editor.state_repository = repository
    index = await editor.trace.load_index(context)
    thread = context.scope["threadId"]
    markdown = (await editor.read_document(context)).markdown + "\n第二版正文\n"
    path = "reports/revision-2/report.md"
    await editor.workspace.awrite_text(thread, path, markdown)
    original = next(item for item in index.files if item.path == context.markdown_path)
    new_markdown = original.model_copy(update={
        "path": path, "resource_id": derive_resource_id(path),
        "size": len(markdown.encode()), "sha256": hashlib.sha256(markdown.encode()).hexdigest(),
    })
    # 第一版独有中间结果，第二版仍共享原 CSV/facts。
    extra_path = "reports/revision-1/intermediate.json"
    content = b'{"value":3600}'
    await editor.workspace.awrite_bytes(thread, extra_path, content)
    extra = TraceFileRefV1(resourceId=derive_resource_id(extra_path), path=extra_path,
        mediaType="application/json", size=len(content), sha256=hashlib.sha256(content).hexdigest())
    first_index = index.model_copy(update={"files": (*index.files, extra)})
    first_manifest = await _replace_registered_index(editor, context, first_index)
    context = context.model_copy(update={"artifact_manifest": first_manifest})
    second_index = index.model_copy(update={"revision": 2,
        "markdown_file_resource_id": new_markdown.resource_id,
        "files": tuple(new_markdown if item == original else item for item in index.files)})
    await editor.workspace.awrite_bytes(thread, "reports/revision-2/trace-index-v1.json",
        encode_trace_index(second_index))
    second_manifest = await register_trace_manifest(editor.workspace, thread, second_index)
    second = context.model_copy(update={"revision": 2, "markdown_path": path,
        "artifact_manifest": second_manifest})
    repository.durable = repository.durable.model_copy(update={"payload": {
        **repository.durable.payload, "reportEditorContexts": {
            str(item.revision): item.model_dump(mode="json", by_alias=True) for item in (context, second)
        },
    }})
    return editor, repository, context, second, extra_path


@pytest.mark.anyio
async def test_cleanup_preview_protects_shared_sources_and_restored_draft(tmp_path):
    editor, repository, first, second, extra_path = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    await editor.set_revision_retention(first, expires_at=now)
    before = repository.durable
    result = await editor.preview_revision_source_cleanup(second, now=now)
    assert result["dryRun"] is True
    assert result["expiredRevisions"] == [1]
    assert result["protectedRevisions"] == [2]
    assert [item["path"] for item in result["candidateFiles"]] == [extra_path]
    assert any(path.endswith(".csv") for path in result["protectedPaths"])
    assert any(path.endswith("analysis_001.json") for path in result["protectedPaths"])
    assert repository.durable == before
    assert await editor.workspace.apath_exists(first.scope["threadId"], extra_path)

    await editor.set_revision_retention(second, expires_at=now)
    result = await editor.preview_revision_source_cleanup(second, now=now)
    assert result["protectedRevisions"] == []
    assert result["protectedPaths"] == []
    assert len(result["candidateFiles"]) == 3
    await editor.set_revision_retention(second, expires_at=None)

    document = await editor.read_document(second)
    await editor.restore_history(second, revision=1, expected_sha256=document.sha256)
    result = await editor.preview_revision_source_cleanup(second, now=now)
    assert result["protectedRevisions"] == [1, 2]
    assert result["candidateFiles"] == []
    assert (await editor.read_document(second)).source_revision == 1


@pytest.mark.anyio
@pytest.mark.parametrize("damage", ["context", "policy", "scope", "shared_identity", "index", "draft"])
async def test_cleanup_preview_fails_closed_on_incomplete_authority(tmp_path, damage):
    editor, repository, first, second, _ = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    await editor.set_revision_retention(first, expires_at=now)
    payload = repository.durable.payload
    if damage == "context":
        payload["reportEditorContexts"]["broken"] = {}
    elif damage == "policy":
        payload["reportEditorRetention"]["1"]["contextSha256"] = "0" * 64
    elif damage == "scope":
        payload["reportEditorContexts"]["1"]["reportId"] = "other-report"
    elif damage in {"index", "shared_identity"}:
        index = await editor.trace.load_index(first)
        if damage == "index":
            manifest = await editor.trace.load_manifest(first)
            content = manifest.model_copy(update={"trace_index": None}).model_dump_json(by_alias=True).encode()
            path = first.artifact_manifest.path
            await editor.workspace.awrite_bytes(first.scope["threadId"], path, content, overwrite=True)
            identity = first.artifact_manifest.model_copy(update={"size": len(content),
                "sha256": hashlib.sha256(content).hexdigest()})
        else:
            files = tuple(item.model_copy(update={"sha256": "0" * 64})
                if item.path.endswith(".csv") else item for item in index.files)
            changed = index.model_copy(update={"files": files})
            identity = await _replace_registered_index(editor, first, changed)
        changed_context = first.model_copy(update={"artifact_manifest": identity})
        payload["reportEditorContexts"]["1"] = changed_context.model_dump(mode="json", by_alias=True)
        payload["reportEditorRetention"]["1"]["contextSha256"] = changed_context.digest()
    else:
        await editor.workspace.awrite_text(first.scope["threadId"],
            "reports/revision-2/draft/.report.md.origin.json", "{}")
    before = repository.durable.model_copy(deep=True)
    with pytest.raises(ReportingError):
        await editor.preview_revision_source_cleanup(second, now=now)
    assert repository.durable == before


@pytest.mark.anyio
async def test_cleanup_preview_rejects_state_changed_during_scan(tmp_path, monkeypatch):
    editor, _, first, second, _ = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    load_index = editor.trace.load_index

    async def changing_load_index(context):
        await editor.set_revision_retention(first, expires_at=now)
        return await load_index(context)

    monkeypatch.setattr(editor.trace, "load_index", changing_load_index)
    with pytest.raises(ReportingError, match="状态已变化"):
        await editor.preview_revision_source_cleanup(second, now=now)


@pytest.mark.anyio
async def test_cleanup_deletes_only_last_reference_and_preserves_metadata(tmp_path):
    editor, repository, first, second, extra_path = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    await editor.set_revision_retention(first, expires_at=now)
    with pytest.raises(ReportingError, match="工作流未完成"):
        await editor.cleanup_revision_sources(second, now=now)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    result = await editor.cleanup_revision_sources(second, now=now)
    assert result["deletedPaths"] == [extra_path]
    assert not await editor.workspace.apath_exists(first.scope["threadId"], extra_path)
    session = SimpleNamespace(capabilities={})
    sources = await editor.trace_sources(first, session)
    assert sources["available"] is False
    assert sources["reason"] == "snapshot_expired"
    assert sources["datasets"][0]["rowCount"] == 1
    assert (await editor.trace_sources(second, session))["available"] is True
    with pytest.raises(ReportingError, match="明细不可用"):
        await editor.trace_fact_detail(first, session, "analysis_001", "fact-" + "a" * 16)
    assert (await editor.read_document(first)).markdown
    assert len(await editor.list_history(second)) == 2
    assert (await editor.cleanup_revision_sources(second, now=now))["deletedPaths"] == []
    await editor.set_revision_retention(second, expires_at=now)
    result = await editor.cleanup_revision_sources(second, now=now)
    assert len(result["deletedPaths"]) == 2
    assert any(path.endswith(".csv") for path in result["deletedPaths"])
    assert (await editor.trace_sources(second, session))["datasets"]
    assert repository.durable.payload["reportEditorSourceCleanup"]["status"] == "completed"
    with pytest.raises(ReportingStateError, match="已回收"):
        await editor.set_revision_retention(first, expires_at=None)


@pytest.mark.anyio
async def test_cleanup_failure_is_durable_and_restart_retry_safe(tmp_path, monkeypatch):
    editor, repository, first, second, _ = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    await editor.set_revision_retention(first, expires_at=now)
    await editor.set_revision_retention(second, expires_at=now)
    delete = editor.workspace.adelete_registered_file
    calls = 0

    async def failing_delete(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected deletion failure")
        return await delete(*args, **kwargs)

    monkeypatch.setattr(editor.workspace, "adelete_registered_file", failing_delete)
    with pytest.raises(ReportingError, match="回收未完成"):
        await editor.cleanup_revision_sources(second, now=now)
    pending = repository.durable.payload["reportEditorSourceCleanup"]
    assert pending["status"] == "pending"
    assert len(repository.durable.payload["reportEditorRetiredSources"]) == 2
    monkeypatch.setattr(editor.workspace, "adelete_registered_file", delete)
    restarted = ReportEditorService(state_repository=repository,
        workspace_registry=editor.workspace_registry, workspace=editor.workspace)
    result = await restarted.cleanup_revision_sources(second, now=now)
    assert result["cleanupId"] == pending["cleanupId"]
    assert len(result["deletedPaths"]) == 3
    assert (await restarted.cleanup_revision_sources(second, now=now))["deletedPaths"] == []


@pytest.mark.anyio
async def test_cleanup_waits_for_source_reader_and_rechecks_policy(tmp_path):
    editor, repository, first, second, extra = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    await editor.set_revision_retention(first, expires_at=now)
    async with source_lifecycle_lock(editor, first):
        task = asyncio.create_task(editor.cleanup_revision_sources(second, now=now))
        await asyncio.sleep(0.1)
        assert not task.done()
        assert "reportEditorRetiredSources" not in repository.durable.payload
        assert await editor.workspace.apath_exists(first.scope["threadId"], extra)
    assert (await task)["deletedPaths"] == [extra]


@pytest.mark.anyio
async def test_cleanup_rejects_changed_registered_bytes_before_retirement(tmp_path):
    editor, repository, first, second, extra = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    await editor.set_revision_retention(first, expires_at=now)
    await editor.workspace.awrite_bytes(first.scope["threadId"], extra, b"changed", overwrite=True)
    with pytest.raises(ReportingError, match="登记身份"):
        await editor.cleanup_revision_sources(second, now=now)
    assert "reportEditorRetiredSources" not in repository.durable.payload
    assert await editor.workspace.apath_exists(first.scope["threadId"], extra)


@pytest.mark.anyio
async def test_file_response_holds_source_lock_through_body_and_revalidates(tmp_path):
    editor, repository, first, second, extra = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    await editor.set_revision_retention(first, expires_at=now)
    path = editor.workspace.workspace(first.scope["threadId"]).paths.to_host_path(extra)

    async def validate():
        await editor._ensure_sources_retained(first)
        return path, "intermediate.json", path.stat().st_size

    response = SourceFileResponse(path, service=editor, context=first, validate=validate)
    sending = asyncio.Event()
    finish = asyncio.Event()
    messages = []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            sending.set()
            await finish.wait()

    async def receive():
        return {"type": "http.request", "body": b""}

    transfer = asyncio.create_task(response({"type": "http", "method": "GET", "headers": [],
        "extensions": {"http.response.pathsend": {}}}, receive, send))
    await asyncio.wait_for(sending.wait(), timeout=3)
    cleanup = asyncio.create_task(editor.cleanup_revision_sources(second, now=now))
    await asyncio.sleep(0.1)
    assert not cleanup.done()
    assert path.exists()
    finish.set()
    await transfer
    assert (await cleanup)["deletedPaths"] == [extra]
    assert b"3600" in b"".join(item.get("body", b"") for item in messages)
    messages.clear()
    await response({"type": "http", "method": "GET", "headers": []}, receive, send)
    assert messages[0]["status"] == 410
    assert b"snapshot_expired" in messages[1]["body"]


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["hash", "symlink"])
async def test_registered_delete_refuses_replaced_resource(tmp_path, change):
    editor, _, first, _, extra = await _make_shared_revisions(tmp_path)
    workspace = editor.workspace.workspace(first.scope["threadId"])
    path = workspace.paths.to_host_path(extra)
    original = path.read_bytes()
    if change == "hash":
        await workspace.awrite_bytes(first.scope["threadId"], extra, b"x" * len(original), overwrite=True)
    else:
        target = tmp_path / "external-evidence.json"
        target.write_bytes(original)
        path.unlink()
        path.symlink_to(target)
    with pytest.raises((OSError, WorkspaceError)):
        await workspace.adelete_registered_file(first.scope["threadId"], extra,
            size=len(original), sha256=hashlib.sha256(original).hexdigest())
    assert path.exists()
    if change == "symlink":
        assert target.read_bytes() == original


@pytest.mark.anyio
async def test_cleanup_finish_commit_failure_can_retry_without_source_bytes(tmp_path, monkeypatch):
    editor, repository, first, second, extra = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    await editor.set_revision_retention(first, expires_at=now)
    apply = repository.apply

    async def failing_finish(run_id, command, **kwargs):
        if command.name == "finish_report_editor_source_cleanup":
            raise RuntimeError("injected finish commit failure")
        return await apply(run_id, command, **kwargs)

    monkeypatch.setattr(repository, "apply", failing_finish)
    with pytest.raises(RuntimeError, match="finish commit"):
        await editor.cleanup_revision_sources(second, now=now)
    assert not await editor.workspace.apath_exists(first.scope["threadId"], extra)
    assert repository.durable.payload["reportEditorSourceCleanup"]["status"] == "pending"
    monkeypatch.setattr(repository, "apply", apply)
    assert (await editor.cleanup_revision_sources(second, now=now))["deletedPaths"] == [extra]
    assert repository.durable.payload["reportEditorSourceCleanup"]["status"] == "completed"


@pytest.mark.anyio
async def test_cleanup_waits_for_reader_in_independent_process(tmp_path):
    editor, repository, first, second, extra = await _make_shared_revisions(tmp_path)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED})
    await editor.set_revision_retention(first, expires_at=now)
    root = editor.workspace_registry.get(first.scope["threadId"]).root
    process_context = multiprocessing.get_context("spawn")
    parent, child = process_context.Pipe()
    process = process_context.Process(target=_hold_source_lock_in_process, args=(root, child))
    process.start()
    child.close()
    cleanup = None
    try:
        assert await asyncio.to_thread(parent.poll, 30), "reader did not start"
        assert parent.recv() == "locked"
        cleanup = asyncio.create_task(editor.cleanup_revision_sources(second, now=now))
        await asyncio.sleep(0.2)
        assert not cleanup.done()
        assert "reportEditorRetiredSources" not in repository.durable.payload
        assert await editor.workspace.apath_exists(first.scope["threadId"], extra)
        parent.send("release")
        assert (await asyncio.wait_for(cleanup, timeout=10))["deletedPaths"] == [extra]
        assert await asyncio.to_thread(parent.poll, 5)
        assert parent.recv() == "released"
        await asyncio.to_thread(process.join, 5)
        assert process.exitcode == 0
    finally:
        if cleanup is not None and not cleanup.done():
            cleanup.cancel()
            await asyncio.gather(cleanup, return_exceptions=True)
        if process.is_alive():
            process.terminate()
            await asyncio.to_thread(process.join, 5)
        parent.close()


@pytest.mark.anyio
async def test_shared_chart_image_and_plot_data_survive_until_last_revision_expires(tmp_path):
    from PIL import Image

    editor, repository, first, second, extra = await _make_shared_revisions(tmp_path)
    thread = first.scope["threadId"]
    image_path = "reports/revision-1/chart.png"
    plot_path = "reports/revision-1/chart.chart-input.json"
    image = Image.new("RGB", (100, 60), "white")
    for x in range(20, 80):
        for y in range(20, 40):
            image.putpixel((x, y), (0, 100, 150))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    image_bytes = buffer.getvalue()
    plot_bytes = json.dumps({"schema": "chart-input/v1", "chartId": "chart_001", "role": "measure",
        "source": {"analysisId": "analysis_001"}, "columns": ["period", "revenue"],
        "rows": [["2025-09", 3600]], "rowCount": 1}).encode()
    resources = []
    for path, content, media_type in ((image_path, image_bytes, "image/png"),
        (plot_path, plot_bytes, "application/json")):
        await editor.workspace.awrite_bytes(thread, path, content)
        resources.append(TraceFileRefV1(resourceId=derive_resource_id(path), path=path,
            mediaType=media_type, size=len(content), sha256=hashlib.sha256(content).hexdigest()))
    updated = []
    for context in (first, second):
        index = await editor.trace.load_index(context)
        chart = ChartTraceV1(chartId="chart_001", imageFileResourceId=resources[0].resource_id,
            plotDataFileResourceIds=(resources[1].resource_id,), datasetIds=(index.datasets[0].dataset_id,))
        index = type(index).model_validate({**index.model_dump(),
            "files": (*index.files, *resources), "chart_traces": (chart,)})
        identity = await _replace_registered_index(editor, context, index)
        updated.append(context.model_copy(update={"artifact_manifest": identity}))
    first, second = updated
    repository.durable = repository.durable.model_copy(update={"phase": ReportingPhase.COMPLETED,
        "payload": {**repository.durable.payload, "reportEditorContexts": {
            str(item.revision): item.model_dump(mode="json", by_alias=True) for item in updated}}})
    now = datetime.now(UTC)
    await editor.set_revision_retention(first, expires_at=now)
    assert (await editor.cleanup_revision_sources(second, now=now))["deletedPaths"] == [extra]
    session = SimpleNamespace(capabilities={})
    chart_source = await editor.trace_chart_source(second, session, "chart_001")
    assert chart_source["plotData"][0]["rows"] == [["2025-09", 3600]]
    assert chart_source["image"]["sha256"] == hashlib.sha256(image_bytes).hexdigest()
    await editor.set_revision_retention(second, expires_at=now)
    deleted = (await editor.cleanup_revision_sources(second, now=now))["deletedPaths"]
    assert image_path in deleted and plot_path in deleted
    assert not await editor.workspace.apath_exists(thread, image_path)
    assert not await editor.workspace.apath_exists(thread, plot_path)
    with pytest.raises(ReportingError, match="明细不可用"):
        await editor.trace_chart_source(second, session, "chart_001")


@pytest.mark.anyio
@pytest.mark.parametrize(("code", "status"), [("snapshot_integrity_failed", 409), ("dataset_access_denied", 403)])
async def test_download_revalidation_preserves_trace_http_error_contract(tmp_path, code, status):
    editor, _, first = await _make_editor_with_subject(tmp_path)

    async def validate():
        raise ReportingError(code, "拒绝下载")

    response = SourceFileResponse(tmp_path / "unused.csv", service=editor, context=first, validate=validate)
    messages = []

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    await response({"type": "http", "method": "GET", "headers": []}, receive, send)
    assert messages[0]["status"] == status
    assert code.encode() in messages[1]["body"]
