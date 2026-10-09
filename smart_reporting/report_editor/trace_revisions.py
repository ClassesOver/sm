"""Verified revision snapshots shared by publication and manual exports."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any

from ..reporting.delivery.artifacts_v1 import (
    ArtifactFile,
    ChartArtifact,
    ReportArtifactManifest,
    _markdown_image_bindings,
    _markdown_table_artifacts,
    _TABLE_BLOCK,
)
from ..reporting.models import ReportingError
from ..workspace import WorkspaceError, WorkspacePathConflict
from ..reporting.trace.contracts_v1 import (
    RevisionTraceIndexV1,
    canonical_json_bytes,
    derive_resource_id,
)
from ..reporting.trace.index_builder import encode_trace_index, trace_index_path_for


async def write_registered_json(workspace: Any, thread_id: str, path: str, content: bytes) -> ArtifactFile:
    try:
        await workspace.awrite_bytes(thread_id, path, content)
    except WorkspacePathConflict:
        stored = await workspace.read_limited_regular_file(thread_id, path, max_bytes=len(content))
        if stored != content:
            raise ReportingError("snapshot_integrity_failed", "Revision snapshot conflicts with existing content.") from None
    stored = await workspace.read_limited_regular_file(thread_id, path, max_bytes=len(content))
    if stored != content:
        raise ReportingError("snapshot_integrity_failed", "Revision snapshot changed after writing.")
    return ArtifactFile(path=path, mediaType="application/json", size=len(content), sha256=hashlib.sha256(content).hexdigest())


def _remap_references(value: Any, resource_ids: Mapping[str, str]) -> Any:
    """Only typed reference fields change; parameters and frozen facts are untouched."""
    singular = {"fileResourceId", "imageFileResourceId", "scriptFileResourceId", "markdownFileResourceId"}
    plural = {"plotDataFileResourceIds", "intermediateFileResourceIds"}
    if isinstance(value, list):
        return [_remap_references(item, resource_ids) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in singular and isinstance(item, str):
            result[key] = resource_ids.get(item, item)
        elif key in plural and isinstance(item, list):
            result[key] = [resource_ids.get(ref, ref) for ref in item]
        elif key in {"parameters", "environment", "locator"}:
            result[key] = item
        else:
            result[key] = _remap_references(item, resource_ids)
    return result


def _lineage_identities(
    manifest: ReportArtifactManifest, index: RevisionTraceIndexV1 | None
) -> dict[str, Any]:
    """新 revision 需要随迁的全部登记文件（图表、交互图规格与索引登记文件）。"""
    identities: dict[str, Any] = {chart.path: chart for chart in manifest.charts}
    identities.update({chart.interactive_spec.path: chart.interactive_spec for chart in manifest.charts if chart.interactive_spec})
    if index is not None:
        identities.update({file.path: file for file in index.files if file.resource_id != index.markdown_file_resource_id})
    return identities


async def verify_revision_lineage_files(
    workspace: Any,
    thread_id: str,
    *,
    manifest: ReportArtifactManifest,
    index: RevisionTraceIndexV1 | None,
) -> None:
    """渲染前核对随迁文件身份；缺失或变化时由调用方在渲染前放弃追溯，避免成品
    附录指向一个最终未登记索引的新 revision。"""
    for path, identity in _lineage_identities(manifest, index).items():
        try:
            current = await workspace.ahash_file(thread_id, path)
        except (OSError, WorkspaceError):
            current = {"missing": True}
        if current.get("missing") or current.get("size") != identity.size or current.get("sha256") != identity.sha256:
            raise ReportingError("snapshot_integrity_failed", f"来源文件缺失或已变化：{path}")


async def snapshot_revision_lineage(
    workspace: Any,
    thread_id: str,
    *,
    manifest: ReportArtifactManifest,
    index: RevisionTraceIndexV1 | None,
    markdown_file: ArtifactFile,
    target_revision: int,
    path_map: Mapping[str, str],
    manifest_path: str,
) -> tuple[ReportArtifactManifest, ArtifactFile]:
    """Copy explicit moved resources, rebind IDs, and register the new manifest.

    markdown_file must already exist at its final path. Unmoved resources keep
    their frozen identities. Subject fingerprints remain generation-time facts.
    The caller owns rollback of the target directory until its durable commit.
    """
    identities = _lineage_identities(manifest, index)
    for source, identity in identities.items():
        target = path_map.get(source, source)
        content, _media = await workspace.afile_bytes(thread_id, source)
        if len(content) != identity.size or hashlib.sha256(content).hexdigest() != identity.sha256:
            raise ReportingError("snapshot_integrity_failed", "Frozen source file identity changed.")
        if target != source:
            if await workspace.apath_exists(thread_id, target):
                current = await workspace.ahash_file(thread_id, target)
                if current.get("size") != identity.size or current.get("sha256") != identity.sha256:
                    raise ReportingError("snapshot_integrity_failed", "Copied source file identity changed.")
            else:
                await workspace.awrite_bytes(thread_id, target, content)
            copied = await workspace.ahash_file(thread_id, target)
            if copied.get("size") != identity.size or copied.get("sha256") != identity.sha256:
                raise ReportingError("snapshot_integrity_failed", "Copied source file identity changed.")
    current = await workspace.ahash_file(thread_id, markdown_file.path)
    if current.get("size") != markdown_file.size or current.get("sha256") != markdown_file.sha256:
        raise ReportingError("snapshot_integrity_failed", "Frozen markdown identity changed.")
    trace_identity = None
    if index is not None:
        if (any(chart.presentation_sha256 is None for chart in index.chart_traces)
                or any(table.origin_markdown is None for table in index.tables)):
            from ..reporting.trace.chart_subjects import freeze_chart_presentations

            original = next(file for file in index.files if file.resource_id == index.markdown_file_resource_id)
            content = await workspace.read_limited_regular_file(thread_id, original.path, max_bytes=16 * 1024 * 1024)
            if len(content) != original.size or hashlib.sha256(content).hexdigest() != original.sha256:
                raise ReportingError("snapshot_integrity_failed", "冻结图注正文身份已变化。")
            index = freeze_chart_presentations(index, content.decode("utf-8"))
            blocks = list(_TABLE_BLOCK.finditer(content.decode("utf-8")))
            tables = []
            for table in index.tables:
                if table.origin_markdown is None:
                    matches = [match.group(0) for match in blocks if match.group(1) == table.table_id]
                    # 重复或缺失的表格不能借新修订的位置重新绑定。
                    table = table.model_copy(update={
                        "origin_markdown": matches[0] if len(matches) == 1 else "",
                    })
                tables.append(table)
            index = index.model_copy(update={"tables": tuple(tables)})
        resource_ids = {file.resource_id: derive_resource_id(path_map.get(file.path, file.path)) for file in index.files}
        resource_ids[index.markdown_file_resource_id] = derive_resource_id(markdown_file.path)
        payload = _remap_references(index.model_dump(mode="json", by_alias=True), resource_ids)
        payload["revision"] = target_revision
        for file in payload["files"]:
            if file["resourceId"] == index.markdown_file_resource_id:
                file.update(markdown_file.model_dump(mode="json", by_alias=True))
            else:
                file["path"] = path_map.get(file["path"], file["path"])
            file["resourceId"] = derive_resource_id(file["path"])
        rebound = RevisionTraceIndexV1.model_validate(payload)
        trace_identity = await write_registered_json(workspace, thread_id, trace_index_path_for(manifest_path), encode_trace_index(rebound))
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload.update(revision=target_revision, markdown=markdown_file.model_dump(mode="json", by_alias=True), traceIndex=trace_identity.model_dump(mode="json", by_alias=True) if trace_identity else None)
    for chart in payload["charts"]:
        chart["path"] = path_map.get(chart["path"], chart["path"])
        if chart["interactiveSpec"]:
            spec = chart["interactiveSpec"]
            spec["path"] = path_map.get(spec["path"], spec["path"])
    rebound_manifest = ReportArtifactManifest.model_validate(payload)
    identity = await write_registered_json(workspace, thread_id, manifest_path, canonical_json_bytes(rebound_manifest.model_dump(mode="json", by_alias=True)))
    return rebound_manifest, identity


async def rebuild_edited_manifest(
    workspace: Any,
    thread_id: str,
    *,
    manifest: ReportArtifactManifest,
    index: RevisionTraceIndexV1 | None,
    markdown_path: str,
    markdown: str,
    target_revision: int,
) -> ReportArtifactManifest:
    """Rebuild edited structure using authoritative marker/image/table parsers."""
    current = await workspace.ahash_file(thread_id, markdown_path)
    markdown_file = ArtifactFile(path=markdown_path, mediaType="text/markdown", size=current["size"], sha256=current["sha256"])
    bindings = _markdown_image_bindings(
        markdown, markdown_path,
        {citation.citation_id: citation.dataset_id for citation in manifest.citations},
        # 编辑把图片与 citation 标记拆到不同段落时，已登记图表沿用登记的 Dataset。
        registered_datasets={chart.path: chart.dataset_ids for chart in manifest.charts},
    )
    known = {chart.path: chart for chart in manifest.charts}
    charts = []
    for path in sorted(bindings):
        chart = known.get(path)
        if chart is None:
            raise ReportingError("report_artifact_chart_invalid", "Edited chart is not registered.")
        for identity in (chart, chart.interactive_spec):
            if identity is not None:
                current = await workspace.ahash_file(thread_id, identity.path)
                if current.get("size") != identity.size or current.get("sha256") != identity.sha256:
                    raise ReportingError("snapshot_integrity_failed", "Frozen chart identity changed.")
        payload = chart.model_dump(mode="json", by_alias=True)
        payload.update(datasetIds=bindings[path])
        charts.append(ChartArtifact.model_validate(payload))
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload.update(
        revision=target_revision,
        markdown=markdown_file.model_dump(mode="json", by_alias=True),
        tables=[table.model_dump(mode="json", by_alias=True) for table in _markdown_table_artifacts(markdown)],
        charts=[chart.model_dump(mode="json", by_alias=True) for chart in charts],
        analysisIds=list(dict.fromkeys(re.findall(r"\[\[analysis:([^\]\r\n]+)\]\]", markdown))),
        traceIndex=None,
    )
    return ReportArtifactManifest.model_validate(payload)
