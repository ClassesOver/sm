"""Frozen revision identities come from visible Markdown, not comments/code."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage
from smart_reporting.reporting.delivery.artifacts_v1 import _TABLE_BLOCK, ArtifactFile
from smart_reporting.reporting.trace.quality_bundle import evaluate_quality_bundle

from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("hidden_only", [False, True])
@pytest.mark.parametrize("wrapper", ["<!--\n{}\n-->", "```markdown\n{}\n```"])
async def test_revision_snapshot_freezes_only_the_unique_visible_table(
    tmp_path: Path, hidden_only, wrapper
):
    editor, _, context = await _make_editor_with_subject(tmp_path, period_table=True)
    index = await editor.trace.require_index(context)
    manifest = await editor.trace.load_manifest(context)
    thread = context.scope["threadId"]
    visible = await editor.workspace.aread_text(thread, context.markdown_path)
    table = _TABLE_BLOCK.search(visible)[0]
    hidden = wrapper.format(table)
    source = visible.replace(table, hidden) if hidden_only else visible + "\n\n" + hidden
    await editor.workspace.awrite_text(thread, context.markdown_path, source, overwrite=True)
    source_file = ArtifactFile(
        path=context.markdown_path,
        mediaType="text/markdown",
        size=len(source.encode()),
        sha256=hashlib.sha256(source.encode()).hexdigest(),
    )
    index = index.model_copy(
        update={
            "files": tuple(
                file.model_copy(update={"size": source_file.size, "sha256": source_file.sha256})
                if file.resource_id == index.markdown_file_resource_id
                else file
                for file in index.files
            )
        }
    )
    manifest = manifest.model_copy(update={"markdown": source_file})
    target = "reports/revision-2/report.md"
    await editor.workspace.awrite_text(thread, target, visible)
    target_file = ArtifactFile(
        path=target,
        mediaType="text/markdown",
        size=len(visible.encode()),
        sha256=hashlib.sha256(visible.encode()).hexdigest(),
    )
    _, identity = await snapshot_revision_lineage(
        editor.workspace,
        thread,
        manifest=manifest,
        index=index,
        markdown_file=target_file,
        target_revision=2,
        path_map={},
        manifest_path="reports/revision-2/artifact-manifest.json",
    )
    copied_context = context.model_copy(
        update={"revision": 2, "markdown_path": target, "artifact_manifest": identity}
    )
    rebound = await editor.trace.require_index(copied_context)
    assert bool(rebound.tables[0].origin_markdown) is not hidden_only
    sources = {
        file.resource_id: await editor.trace._read_registered_file(
            copied_context, file, max_bytes=16 * 1024 * 1024
        )
        for file in rebound.files
        if file.media_type == "application/json"
    }
    quality = evaluate_quality_bundle(rebound, visible, sources, authorization_scope_hash="c" * 64)
    assert quality.table_checks["tbl-1"].status == ("unknown" if hidden_only else "verified")
