"""B6 图题/图注软校验及跨版本生成时指纹继承。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.trace_revisions import snapshot_revision_lineage
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.trace.chart_subjects import freeze_chart_presentations

from .test_report_editor_trace import _context, _make_editor

ORIGINAL = "![趋势](chart-001.png)\n\n*图表：收入趋势*"


@pytest.mark.anyio
async def test_chart_duplicate_registered_filenames_do_not_bind_both_charts(tmp_path: Path) -> None:
    editor, _grants, _workspace = await _make_editor(tmp_path, with_chart_trace=True)
    await editor.read_document(_context())
    index = await editor.trace.load_index(_context())
    assert index is not None
    trace = index.chart_traces[0]
    image = next(file for file in index.files if file.resource_id == trace.image_file_resource_id)
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id

    second_image = image.model_copy(update={"path": "other/chart-001.png", "resource_id": derive_resource_id("other/chart-001.png")})
    second_chart = trace.model_copy(update={"chart_id": "chart_002", "image_file_resource_id": second_image.resource_id})
    ambiguous = index.model_copy(update={"files": (*index.files, second_image), "chart_traces": (trace, second_chart)})
    frozen = freeze_chart_presentations(ambiguous, ORIGINAL)
    assert [chart["status"] for chart in editor.trace._evaluate_charts(frozen, ORIGINAL)] == ["unbound", "unbound"]


@pytest.mark.anyio
async def test_chart_location_source_requires_unique_registered_image(tmp_path: Path) -> None:
    editor, _grants, _workspace = await _make_editor(tmp_path, with_chart_trace=True)
    await editor.read_document(_context())
    index = await editor.trace.load_index(_context())
    for draft, source in (
        (ORIGINAL, "chart-001.png"),
        (ORIGINAL.replace("chart-001.png", "./chart-001.png"), "chart-001.png"),
        (ORIGINAL.replace("收入趋势", "成本趋势"), "chart-001.png"),
        (ORIGINAL.replace("chart-001.png", "reports/revision-1/chart-001.png"), "reports/revision-1/chart-001.png"),
        (ORIGINAL + "\n\n" + ORIGINAL, None),
        (ORIGINAL.replace("chart-001.png", "other/chart-001.png"), None),
        ("已删除图表", None),
    ):
        assert editor.trace._evaluate_charts(index, draft)[0]["locationSource"] == source


@pytest.mark.anyio
async def test_initial_publication_freezes_chart_presentation_before_editing(tmp_path: Path) -> None:
    from smart_reporting.reporting.workflow.runtime.publication import RuntimePublicationMixin

    from .test_trace_index_builder import _handle, _lineage

    editor, _grants, workspace = await _make_editor(tmp_path, with_chart_trace=True)
    await editor.read_document(_context())
    index = await editor.trace.load_index(_context())
    assert index is not None
    files = {file.resource_id: file for file in index.files}
    markdown = files[index.markdown_file_resource_id]
    context = _context()
    frozen_markdown = await workspace.aread_text(context.scope["threadId"], markdown.path)

    async def metrics(**_kwargs):
        return ()

    runtime = SimpleNamespace(
        workspace_service=workspace,
        _scope=lambda _run: context.scope,
        _profile=lambda _run: SimpleNamespace(effective_profile_hash="a" * 64),
        _build_drilldown_metrics=metrics,
    )
    arguments = dict(
        handles=(_handle("dataset-url-abc0001"),), lineage=(_lineage("dataset-url-abc0001"),),
        markdown_artifact=ArtifactFile(path=markdown.path, mediaType=markdown.media_type, size=markdown.size, sha256=markdown.sha256),
        revision=1, run_context=SimpleNamespace(run_id="report-1"),
        chart_trace_files=tuple(files[resource] for resource in (index.chart_traces[0].image_file_resource_id, *index.chart_traces[0].plot_data_file_resource_ids)),
        chart_traces=index.chart_traces, markdown=frozen_markdown,
    )
    identity = await RuntimePublicationMixin._write_trace_index(
        runtime, "reports/publish-proof/artifact-manifest.json", **arguments,
    )
    from smart_reporting.reporting.models import ReportingError

    with pytest.raises(ReportingError, match="report_trace_index_invalid"):
        await RuntimePublicationMixin._write_trace_index(
            runtime, "reports/publish-proof/mismatched-manifest.json",
            **{**arguments, "markdown": "不同正文"},
        )
    from smart_reporting.reporting.trace.contracts_v1 import RevisionTraceIndexV1

    content = await workspace.read_limited_regular_file(context.scope["threadId"], identity.path, max_bytes=identity.size)
    published = RevisionTraceIndexV1.model_validate_json(content)
    assert published.chart_traces[0].presentation_sha256 is not None
    assert editor.trace._evaluate_charts(published, ORIGINAL)[0]["status"] == "valid"
    assert editor.trace._evaluate_charts(published, ORIGINAL.replace("收入趋势", "成本趋势"))[0]["status"] == "stale"


@pytest.mark.anyio
@pytest.mark.parametrize("draft,status", [
    (ORIGINAL, "valid"),
    ("![**趋势**](./chart-001.png)\n\n**图表：收入趋势**", "valid"),
    ("无关段落修改。\n\n" + ORIGINAL, "valid"),
    (ORIGINAL.replace("![趋势]", "![预测]"), "stale"),
    (ORIGINAL.replace("收入趋势*", "成本趋势*"), "stale"),
    ("![趋势](chart-001.png)", "stale"),
    (ORIGINAL.replace("chart-001.png)", 'chart-001.png "新图题")'), "stale"),
    (ORIGINAL.replace("chart-001.png", "other/chart-001.png"), "unbound"),
    (ORIGINAL + "\n\n" + ORIGINAL, "unbound"),
    ("```markdown\n" + ORIGINAL + "\n```", "unbound"),
    ("已删除图表。", "unbound"),
])
async def test_chart_subject_validates_actual_markdown_and_semantic_changes(
    tmp_path: Path, draft: str, status: str,
) -> None:
    editor, _grants, _workspace = await _make_editor(tmp_path, with_chart_trace=True)
    await editor.read_document(_context())
    result = await editor.trace.validate(_context(), draft, hashlib.sha256(draft.encode()).hexdigest())
    assert result["charts"][0]["status"] == status


@pytest.mark.anyio
async def test_chart_caption_original_fingerprint_survives_two_edited_revisions(tmp_path: Path) -> None:
    editor, _grants, workspace = await _make_editor(tmp_path, with_chart_trace=True)
    context = _context()
    await editor.read_document(context)
    original_fingerprint = None
    edited = ORIGINAL.replace("收入趋势", "成本趋势")
    for revision in (2, 3):
        manifest = await editor.trace.load_manifest(context)
        index = await editor.trace.load_index(context)
        assert manifest is not None and index is not None
        path = f"reports/revision-{revision}/report.md"
        await workspace.awrite_text(context.scope["threadId"], path, edited)
        identity = ArtifactFile(path=path, mediaType="text/markdown", size=len(edited.encode()), sha256=hashlib.sha256(edited.encode()).hexdigest())
        # Editor 重建的 manifest 已指向编辑后正文，不能拿它重设生成时基线。
        rebuilt = manifest.model_copy(update={"markdown": identity})
        _manifest, registered = await snapshot_revision_lineage(
            workspace, context.scope["threadId"], manifest=rebuilt, index=index,
            markdown_file=identity, target_revision=revision, path_map={},
            manifest_path=f"reports/revision-{revision}/artifact-manifest.json",
        )
        context = context.model_copy(update={"revision": revision, "markdown_path": path, "artifact_manifest": registered})
        inherited = await editor.trace.load_index(context)
        assert inherited is not None
        fingerprint = inherited.chart_traces[0].presentation_sha256
        assert fingerprint is not None
        if original_fingerprint is None:
            original_fingerprint = fingerprint
        assert fingerprint == original_fingerprint
        changed = await editor.trace.validate(context, edited, identity.sha256)
        assert changed["charts"][0]["status"] == "stale"
        undone = await editor.trace.validate(context, ORIGINAL, hashlib.sha256(ORIGINAL.encode()).hexdigest())
        assert undone["charts"][0]["status"] == "valid"
