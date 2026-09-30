"""Revision lineage rebinding preserves frozen evidence and registered identities."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage, write_registered_json
from smart_reporting.reporting.trace.contracts_v1 import canonical_json_bytes
from smart_reporting.reporting.trace.index_builder import encode_trace_index
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.models import ReportingError
from .test_trace_subject_validate import _make_editor_with_subject


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_revision_snapshot_preserves_claim_fingerprint_and_replays(tmp_path: Path) -> None:
    editor, _grants, context = await _make_editor_with_subject(tmp_path)
    manifest = await editor.trace.load_manifest(context)
    index = await editor.trace.load_index(context)
    assert manifest is not None and index is not None
    markdown = "收入 3800 万元[[claim:claim-1]]"
    target_path = "reports/revision-2/report.md"
    thread = context.scope["threadId"]
    await editor.workspace.awrite_text(thread, target_path, markdown)
    markdown_file = ArtifactFile(path=target_path, mediaType="text/markdown", size=len(markdown.encode()), sha256=hashlib.sha256(markdown.encode()).hexdigest())
    path_map = {file.path: f"reports/revision-2/resources/{file.path}" for file in index.files if file.resource_id != index.markdown_file_resource_id}
    arguments = dict(manifest=manifest, index=index, markdown_file=markdown_file, target_revision=2, path_map=path_map, manifest_path="reports/revision-2/artifact-manifest.json")
    _manifest, identity = await snapshot_revision_lineage(editor.workspace, thread, **arguments)
    _replay_manifest, replay_identity = await snapshot_revision_lineage(editor.workspace, thread, **arguments)
    assert identity == replay_identity
    next_context = context.model_copy(update={"revision": 2, "markdown_path": target_path, "artifact_manifest": identity})
    next_index = await editor.trace.load_index(next_context)
    assert next_index is not None
    assert next_index.subject_bindings[0].subject_sha256 == index.subject_bindings[0].subject_sha256
    assert next_index.subject_bindings[0].fact_refs[0].file_resource_id != index.subject_bindings[0].fact_refs[0].file_resource_id
    result = await editor.trace.validate(next_context, markdown, markdown_file.sha256)
    assert result["summary"]["stale"] == 1
    assert (await editor.trace.sources(context))["revision"] == 1
    assert (await editor.trace.sources(next_context))["revision"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_registered_index_tampering_is_rejected_and_unregistered_sidecar_ignored(tmp_path: Path) -> None:
    editor, _grants, context = await _make_editor_with_subject(tmp_path)
    legacy = context.model_copy(update={"artifact_manifest": None})
    assert await editor.trace.load_index(legacy) is None
    manifest = await editor.trace.load_manifest(context)
    assert manifest is not None and manifest.trace_index is not None
    thread = context.scope["threadId"]
    await editor.workspace.adelete_file(thread, manifest.trace_index.path)
    await editor.workspace.awrite_bytes(thread, manifest.trace_index.path, b"{}")
    with pytest.raises(ReportingError) as error:
        await editor.trace.load_index(context)
    assert error.value.code == "snapshot_integrity_failed"


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_manifest_and_index_must_register_the_same_markdown(tmp_path: Path) -> None:
    editor, _grants, context = await _make_editor_with_subject(tmp_path)
    manifest = await editor.trace.load_manifest(context)
    index = await editor.trace.load_index(context)
    assert manifest is not None and index is not None
    files = tuple(
        file.model_copy(update={"sha256": "f" * 64})
        if file.resource_id == index.markdown_file_resource_id else file
        for file in index.files
    )
    mismatched = index.model_copy(update={"files": files})
    thread = context.scope["threadId"]
    identity = await write_registered_json(editor.workspace, thread, "reports/revision-1/mismatched-index.json", encode_trace_index(mismatched))
    changed = manifest.model_copy(update={"trace_index": identity})
    manifest_identity = await write_registered_json(editor.workspace, thread, "reports/revision-1/mismatched-manifest.json", canonical_json_bytes(changed.model_dump(mode="json", by_alias=True)))
    changed_context = context.model_copy(update={"artifact_manifest": manifest_identity})
    with pytest.raises(ReportingError) as error:
        await editor.trace.load_index(changed_context)
    assert error.value.code == "snapshot_integrity_failed"
