"""Carry adopted edit presentation settings across a verified revision snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from ..reporting.delivery.artifacts_v1 import ReportArtifactManifest
from ..reporting.models import ReportingError
from ..reporting.trace.contracts_v1 import RevisionTraceIndexV1
from .chart_edits import (
    ChartEditFileRef,
    ChartEditRecord,
    append_chart_edit_record,
    chart_edit_output_dir,
    chart_edit_page_chart_id,
    chart_edit_pages,
    load_chart_edit_records,
)


def _mapped_ref(identity: Any, path_map: Mapping[str, str]) -> ChartEditFileRef:
    return ChartEditFileRef(
        path=path_map.get(identity.path, identity.path),
        size=identity.size,
        sha256=identity.sha256,
    )


def _mapped_receipt(receipt: dict[str, Any], path_map: Mapping[str, str]) -> dict[str, Any]:
    mapped = dict(receipt)
    path = mapped.get("sourcePath")
    if isinstance(path, str):
        mapped["sourcePath"] = path_map.get(path, path)
    return mapped


async def migrate_chart_edit_records(
    workspace: Any,
    thread_id: str,
    *,
    source_markdown_path: str,
    target_markdown_path: str,
    path_map: Mapping[str, str],
    manifest: ReportArtifactManifest,
    index: RevisionTraceIndexV1,
) -> None:
    """Preserve only fully adopted groups backed by authoritative snapshot refs.

    ``index`` may be the verified source index or its already-remapped snapshot;
    ``manifest`` is the target manifest. No data bytes or new lineage are created.
    The caller owns the target revision lock/rollback and nonblocking error policy.
    """

    records = await load_chart_edit_records(workspace, thread_id, source_markdown_path)
    if not records:
        return
    charts = {chart.chart_id: chart for chart in manifest.charts}
    traces = {trace.chart_id: trace for trace in index.chart_traces}
    files = {file.resource_id: file for file in index.files}
    accepted: list[ChartEditRecord] = []
    identities: dict[str, ChartEditFileRef] = {}
    for record in records:
        pages = chart_edit_pages(record)
        mapped_pages = []
        expected_plot = tuple(_mapped_ref(ref, path_map) for ref in record.plot_data_files)
        expected_script = _mapped_ref(record.script, path_map)
        canonical_dir = PurePosixPath(chart_edit_output_dir(target_markdown_path, record.edit_id))
        for page in pages:
            chart_id = chart_edit_page_chart_id(record, page.page_number)
            chart, trace = charts.get(chart_id), traces.get(chart_id)
            if chart is None or trace is None or trace.script_file_resource_id is None:
                break
            image = _mapped_ref(page.image, path_map)
            canonical = canonical_dir / ("chart.png" if page.page_number == 1 else f"chart--page-{page.page_number}.png")
            if image.path != canonical.as_posix() or image != _mapped_ref(chart, {}):
                break
            if tuple(chart.dataset_ids) != record.chart.dataset_ids or tuple(trace.dataset_ids) != record.chart.dataset_ids:
                break
            try:
                traced_image = _mapped_ref(files[trace.image_file_resource_id], path_map)
                traced_script = _mapped_ref(files[trace.script_file_resource_id], path_map)
                traced_plot = tuple(_mapped_ref(files[ref], path_map) for ref in trace.plot_data_file_resource_ids)
            except KeyError:
                break
            if traced_image != image or traced_script != expected_script or traced_plot != expected_plot:
                break
            mapped_pages.append(page.model_copy(update={
                "image": image,
                "visual_inspection_receipt": _mapped_receipt(page.visual_inspection_receipt, path_map),
            }))
        if len(mapped_pages) != len(pages):
            continue
        first = mapped_pages[0]
        # The new revision now owns these files as its original registered inputs.
        # L2 is a historical action, not a fresh rebind in the new revision.
        migrated = record.model_copy(update={
            "base_image_path": first.image.path,
            "base_image_sha256": first.image.sha256,
            "image": first.image,
            "chart": first.chart,
            "pages": tuple(mapped_pages) if record.pages else (),
            "script": expected_script,
            "plot_data_files": expected_plot,
            "data_origin": "original",
            "level": ("L1",),
            "data_bindings": (),
            "visual_inspection_receipt": _mapped_receipt(record.visual_inspection_receipt, path_map),
        })
        migrated = ChartEditRecord.model_validate(migrated.model_dump(mode="json", by_alias=True))
        accepted.append(migrated)
        for ref in (migrated.script, *migrated.plot_data_files, *(page.image for page in mapped_pages)):
            previous_identity = identities.setdefault(ref.path, ref)
            if previous_identity != ref:
                raise ReportingError("snapshot_integrity_failed", "跨版本改图登记文件身份冲突。")
    # Verify the entire accepted set before writing even the first record.
    for ref in identities.values():
        actual = await workspace.ahash_file(thread_id, ref.path)
        if actual.get("missing") or actual.get("size") != ref.size or actual.get("sha256") != ref.sha256:
            raise ReportingError("snapshot_integrity_failed", f"跨版本改图文件身份已变化：{ref.path}")
    existing = {record.edit_id: record for record in await load_chart_edit_records(workspace, thread_id, target_markdown_path)}
    for record in accepted:
        previous_record = existing.get(record.edit_id)
        if previous_record is not None:
            if previous_record != record:
                raise ReportingError("snapshot_integrity_failed", "跨版本改图登记与已保存记录不一致。")
            continue
        await append_chart_edit_record(workspace, thread_id, target_markdown_path, record)
