"""表题来源使用当前导出/预览快照；故障仅降级该渲染材料。"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.render_preparation import prepare_editor_render
from smart_reporting.reporting.delivery.artifacts_v1 import ReportArtifactManifest
from smart_reporting.reporting.tests.test_trace_subject_validate import _make_editor_with_subject
from smart_reporting.reporting.workflow.scope import resolve_reporting_workflow_scope
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY


async def _prepare(tmp_path, *, prefix="export", sources=False, monkeypatch=None, fault=None):
    editor, _grants, context = await _make_editor_with_subject(tmp_path)
    thread = context.scope["threadId"]
    markdown = await editor.workspace.aread_text(thread, context.markdown_path)
    markdown += "\n当前草稿补充说明。\n"
    snapshot = str(PurePosixPath(context.markdown_path).with_name(f".{prefix}-snapshot-test.md"))
    await editor.workspace.awrite_text(thread, snapshot, markdown)
    source_index = await editor.trace.load_index(context)
    source_identity = await editor.workspace.ahash_file(thread, context.artifact_manifest.path)
    index_path = "reports/revision-1/trace-index-v1.json"
    source_index_identity = await editor.workspace.ahash_file(thread, index_path)
    if fault:
        method = "awrite_bytes" if fault == "write" else "read_limited_regular_file"
        original = getattr(editor.workspace, method)

        async def failing_operation(thread_id, path, *args, **kwargs):
            if "/.export-lineage-" in path and path.endswith("trace-index-v1.json"):
                raise OSError("injected caption snapshot " + fault)
            return await original(thread_id, path, *args, **kwargs)

        monkeypatch.setattr(editor.workspace, method, failing_operation)
    state = {REPORT_JOBS_STATE_KEY: {context.job_id: copy.deepcopy(context.job)}}
    scope = resolve_reporting_workflow_scope(
        run_id=context.workflow_run_id, session_id=context.scope["sessionId"],
        user_id=context.scope["userId"], stored_scope=context.scope,
    )
    prepared = await prepare_editor_render(
        editor, context=context, source_context=context,
        document=SimpleNamespace(markdown=markdown, sha256=hashlib.sha256(markdown.encode()).hexdigest()),
        snapshot_path=snapshot, scope=scope, session_state=state,
        next_revision=2 if prefix == "export" else 1,
        export_settings={"sources": sources}, public_base_url="https://reports.example.com",
    )
    assert await editor.workspace.ahash_file(thread, context.artifact_manifest.path) == source_identity
    assert await editor.workspace.ahash_file(thread, index_path) == source_index_identity
    assert not await editor.workspace.apath_exists(thread, "reports/revision-2")
    return editor, context, snapshot, markdown, source_index, prepared, state


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("prefix,sources", [("export", False), ("preview", True)])
async def test_render_manifest_registers_current_snapshot_and_cleans_only_its_directory(
    tmp_path: Path, prefix: str, sources: bool,
) -> None:
    editor, context, snapshot, markdown, source_index, prepared, _state = await _prepare(
        tmp_path, prefix=prefix, sources=sources,
    )
    manifest = ReportArtifactManifest.model_validate(prepared[2])
    assert manifest.trace_index is not None
    assert manifest.trace_index.path == "reports/revision-1/.export-lineage-snapshot-test/trace-index-v1.json"
    assert manifest.markdown.path == snapshot
    assert manifest.markdown.sha256 == hashlib.sha256(markdown.encode()).hexdigest()
    revision = 2 if prefix == "export" else 1
    render_context = context.model_copy(update={"revision": revision, "markdown_path": snapshot})
    index = await editor.trace.index_for_manifest(render_context, manifest)
    assert index.revision == revision
    assert index.workflow_run_id == context.workflow_run_id
    current = next(item for item in index.files if item.resource_id == index.markdown_file_resource_id)
    assert current.path == snapshot
    assert current.sha256 == manifest.markdown.sha256
    assert current.size == len(markdown.encode())
    assert len(index.tables) == len(source_index.tables) == 1
    assert index.tables[0].model_dump(exclude={"origin_markdown"}) == source_index.tables[0].model_dump(
        exclude={"origin_markdown"},
    )
    # 旧表仅补协议块，不能从当前草稿的邻段捏造登记表题。
    assert index.tables[0].origin_markdown.startswith("[[table:tbl-1]]")
    assert "当前草稿补充说明" not in index.tables[0].origin_markdown
    assert prepared[0] is not None and prepared[1] is not None and prepared[3] is not None
    assert prepared[4] == []
    await editor._delete_export_snapshot(context.scope["threadId"], snapshot)
    assert not await editor.workspace.apath_exists(context.scope["threadId"], snapshot)
    assert not await editor.workspace.apath_exists(
        context.scope["threadId"], "reports/revision-1/.export-lineage-snapshot-test",
    )
    assert await editor.workspace.apath_exists(context.scope["threadId"], context.markdown_path)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["write", "read"])
async def test_caption_snapshot_failure_retains_other_lineage_and_source_appendix(
    tmp_path: Path, fault: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    editor, context, snapshot, _markdown, source_index, prepared, state = await _prepare(
        tmp_path, sources=True, monkeypatch=monkeypatch, fault=fault,
    )
    assert prepared[0] is not None and prepared[1] == source_index and prepared[3] is not None
    assert prepared[2] is not None and prepared[2]["traceIndex"] is None
    issues = prepared[4]
    assert any(issue["code"] == "report_editor_table_caption_snapshot_unavailable" for issue in issues)
    assert state[REPORT_JOBS_STATE_KEY][context.job_id]["_traceSourcePresentations"]
    await editor._delete_export_snapshot(context.scope["threadId"], snapshot)
    assert not await editor.workspace.apath_exists(
        context.scope["threadId"], "reports/revision-1/.export-lineage-snapshot-test",
    )
