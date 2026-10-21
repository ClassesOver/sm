"""Proofs survive authorized revision copies without blessing invalid old proofs."""

import hashlib

import pytest

from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.tests.test_trace_subject_validate import (
    _make_editor_with_table_derivation,
)
from smart_reporting.reporting.trace.contracts_v1 import canonical_sha256
from smart_reporting.reporting.trace.table_sources import resolve_table_derivation


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("format", ["v2", "legacy", "invalid"])
async def test_revision_copy_preserves_proof_and_upgrades_only_valid_legacy(tmp_path, format):
    editor, context, markdown, source_path = await _make_editor_with_table_derivation(tmp_path)
    index = await editor.trace.require_index(context)
    thread = context.scope["threadId"]
    subject = index.subject_bindings[0]
    number = subject.number_reference
    raw, _ = await editor.workspace.afile_bytes(thread, source_path)
    if format != "v2":
        token = (
            "{{tableDerived:"
            + canonical_sha256(
                {
                    "derivation": number.table_derivation.model_dump(mode="json", by_alias=True),
                    "sources": {
                        number.table_derivation.operands[0].file_resource_id: hashlib.sha256(
                            raw
                        ).hexdigest()
                    },
                }
            )
            + "}}"
        )
        if format == "invalid":
            token = "{{tableDerived:" + "0" * 64 + "}}"
        number = number.model_copy(update={"token": token})
        index = index.model_copy(
            update={"subject_bindings": (subject.model_copy(update={"number_reference": number}),)}
        )
    path = "reports/revision-2/report.md"
    await editor.workspace.awrite_text(thread, path, markdown)
    digest = hashlib.sha256(markdown.encode()).hexdigest()
    _, identity = await snapshot_revision_lineage(
        editor.workspace,
        thread,
        manifest=await editor.trace.load_manifest(context),
        index=index,
        markdown_file=ArtifactFile(
            path=path, mediaType="text/markdown", size=len(markdown.encode()), sha256=digest
        ),
        target_revision=2,
        path_map={
            file.path: "reports/revision-2/trace-resources/" + file.path
            for file in index.files
            if file.resource_id != index.markdown_file_resource_id
        },
        manifest_path="reports/revision-2/artifact-manifest.json",
    )
    context = context.model_copy(
        update={"revision": 2, "markdown_path": path, "artifact_manifest": identity}
    )
    rebound = await editor.trace.require_index(context)
    new_number = rebound.subject_bindings[0].number_reference
    assert (
        new_number.table_derivation.operands[0].file_resource_id
        != number.table_derivation.operands[0].file_resource_id
    )
    result = await editor.trace.validate(context, markdown, digest)
    if format == "invalid":
        assert result["subjects"][0]["status"] == "unbound"
        assert result["subjects"][0]["restoreText"] is None
    else:
        assert result["subjects"][0]["status"] == "valid"
        assert result["subjects"][0]["restoreText"] == "600万元"
        assert new_number.token.startswith("{{tableDerived:v2:")
        if format == "v2":
            assert new_number.token == number.token
        assert (
            resolve_table_derivation(
                new_number.token,
                new_number.table_derivation,
                {new_number.table_derivation.operands[0].file_resource_id: raw},
            )
            is not None
        )
