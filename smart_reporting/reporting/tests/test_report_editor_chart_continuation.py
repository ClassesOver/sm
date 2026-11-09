"""Only verified adopted edit groups retain settings in a new revision."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.chart_continuation import migrate_chart_edit_records
from smart_reporting.report_editor.chart_edits import (
    ChartEditFileRef,
    ChartEditRecord,
    append_chart_edit_record,
    chart_edit_page_chart_id,
    chart_edits_registry_path,
    load_chart_edit_records,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ChartArtifact
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_chart_pages import paged_record
from smart_reporting.reporting.trace.contracts_v1 import (
    ChartTraceV1,
    TraceFileRefV1,
    derive_resource_id,
)

SOURCE = "reports/revision-1/report.md"
TARGET = "reports/revision-2/report.md"


class Workspace:
    def __init__(self):
        self.files = {}

    async def apath_exists(self, _thread, path):
        return path in self.files

    async def afile_bytes(self, _thread, path):
        return self.files[path], "application/json"

    async def awrite_bytes(self, _thread, path, content, *, overwrite):
        assert overwrite or path not in self.files
        self.files[path] = content

    async def ahash_file(self, _thread, path):
        if path not in self.files:
            return {"missing": True}
        content = self.files[path]
        return {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


async def fixture():
    workspace = Workspace()
    record = paged_record()

    def ref(path, content):
        workspace.files[path] = content
        return ChartEditFileRef(path=path, size=len(content), sha256=hashlib.sha256(content).hexdigest())

    pages = tuple(page.model_copy(update={
        "image": ref(page.image.path, f"image{page.page_number}".encode()),
        "visual_inspection_receipt": {"sourcePath": page.image.path,
            "sha256": hashlib.sha256(f"image{page.page_number}".encode()).hexdigest(), "reviewed": True},
    }) for page in record.pages)
    record = ChartEditRecord.model_validate(record.model_copy(update={
        "pages": pages, "image": pages[0].image,
        "visual_inspection_receipt": pages[0].visual_inspection_receipt,
        "script": ref(record.script.path, b"# chart script"),
        "plot_data_files": tuple(ref(f"reports/revision-1/data-{n}.json", f"data{n}".encode()) for n in (1, 2)),
        "data_origin": "rebound", "level": ("L2",),
        "standard_parameters": {"standardPagination": {"pageSize": 1}, "standardStyle": {"palette": "viridis"}},
    }).model_dump())
    await append_chart_edit_record(workspace, "thread", SOURCE, record)
    identities = [record.script, *record.plot_data_files, *(page.image for page in pages)]
    path_map = {ref.path: ref.path.replace("revision-1", "revision-2") for ref in identities}
    for old, new in path_map.items():
        workspace.files[new] = workspace.files[old]
    files = tuple(TraceFileRefV1(
        resourceId=derive_resource_id(ref.path), path=ref.path, size=ref.size, sha256=ref.sha256,
        mediaType="application/json",
    ) for ref in identities)
    traces = tuple(ChartTraceV1(
        chartId=chart_edit_page_chart_id(record, page.page_number),
        imageFileResourceId=derive_resource_id(page.image.path),
        plotDataFileResourceIds=tuple(derive_resource_id(ref.path) for ref in record.plot_data_files),
        scriptFileResourceId=derive_resource_id(record.script.path), datasetIds=record.chart.dataset_ids,
    ) for page in pages)
    manifest = SimpleNamespace(charts=tuple(ChartArtifact(
        chartId=trace.chart_id, path=path_map[page.image.path], size=page.image.size,
        sha256=page.image.sha256, mediaType="image/png", datasetIds=page.chart.dataset_ids,
    ) for page, trace in zip(pages, traces, strict=True)))
    index = SimpleNamespace(files=files, chart_traces=traces)
    return workspace, record, path_map, manifest, index


async def migrate(workspace, path_map, manifest, index):
    await migrate_chart_edit_records(workspace, "thread", source_markdown_path=SOURCE,
        target_markdown_path=TARGET, path_map=path_map, manifest=manifest, index=index)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("remapped_index", [False, True])
async def test_adopted_groups_keep_complete_metadata_against_source_or_target_index(remapped_index):
    workspace, record, path_map, manifest, index = await fixture()
    if remapped_index:
        mapping = {file.resource_id: derive_resource_id(path_map[file.path]) for file in index.files}
        index.files = tuple(file.model_copy(update={"path": path_map[file.path], "resource_id": mapping[file.resource_id]}) for file in index.files)
        index.chart_traces = tuple(trace.model_copy(update={
            "image_file_resource_id": mapping[trace.image_file_resource_id],
            "script_file_resource_id": mapping[trace.script_file_resource_id],
            "plot_data_file_resource_ids": tuple(mapping[ref] for ref in trace.plot_data_file_resource_ids),
        }) for trace in index.chart_traces)
    await migrate(workspace, path_map, manifest, index)
    await migrate(workspace, path_map, manifest, index)  # Safe retry is idempotent.
    records = await load_chart_edit_records(workspace, "thread", TARGET)
    assert len(records) == 1
    copied = records[0]
    assert copied.edit_id == record.edit_id and copied.chart_id == record.chart_id
    assert copied.standard_parameters == record.standard_parameters
    assert copied.data_origin == "original" and copied.level == ("L1",) and copied.data_bindings == ()
    assert copied.base_image_path == copied.image.path == path_map[record.image.path]
    assert copied.base_image_sha256 == copied.image.sha256
    assert copied.plot_data_files == tuple(ref.model_copy(update={"path": path_map[ref.path]}) for ref in record.plot_data_files)
    assert len(copied.pages) == 2
    assert copied.pages[1].chart == record.pages[1].chart
    assert copied.pages[1].visual_inspection_receipt["sourcePath"] == copied.pages[1].image.path
    assert copied.pages[1].visual_inspection_receipt["sha256"] == record.pages[1].image.sha256
    assert copied.visual_inspection_receipt == {
        "sourcePath": copied.image.path, "sha256": record.image.sha256, "reviewed": True,
    }
    assert copied.warnings == record.warnings


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["path", "hash", "missing_path", "missing_hash"])
@pytest.mark.parametrize("location", ["record", "page"])
async def test_revision_drops_stale_visual_receipts_without_losing_adopted_pages(fault, location):
    workspace, record, path_map, manifest, index = await fixture()
    image = record.image if location == "record" else record.pages[1].image
    receipt = {"sourcePath": image.path, "sha256": image.sha256, "reviewed": True}
    if fault == "path":
        receipt["sourcePath"] = "reports/revision-0/old.png"
    elif fault == "hash":
        receipt["sha256"] = "0" * 64
    else:
        receipt.pop("sourcePath" if fault == "missing_path" else "sha256")
    if location == "record":
        record = record.model_copy(update={"visual_inspection_receipt": receipt})
    else:
        page = record.pages[1].model_copy(update={"visual_inspection_receipt": receipt})
        record = record.model_copy(update={"pages": (record.pages[0], page)})
    source_payload = json.dumps({"version": 1, "records": [record.model_dump(mode="json", by_alias=True)]}).encode()
    workspace.files[chart_edits_registry_path(SOURCE)] = source_payload

    await migrate(workspace, path_map, manifest, index)
    copied, = await load_chart_edit_records(workspace, "thread", TARGET)

    assert len(copied.pages) == 2
    assert copied.pages[0].image.sha256 == record.pages[0].image.sha256
    assert copied.pages[1].image.sha256 == record.pages[1].image.sha256
    assert copied.pages[0].visual_inspection_receipt["sha256"] == record.pages[0].image.sha256
    assert (copied.visual_inspection_receipt if location == "record"
            else copied.pages[1].visual_inspection_receipt) == {}
    assert any("视觉回执" in warning for warning in copied.warnings)
    assert workspace.files[chart_edits_registry_path(SOURCE)] == source_payload
    # 同一迁移重试不能生成不同登记，也不能恢复被丢弃的回执。
    await migrate(workspace, path_map, manifest, index)
    assert (await load_chart_edit_records(workspace, "thread", TARGET)) == (copied,)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("receipt", [{}, {"reviewed": True}])
async def test_revision_receipt_warning_does_not_overflow_existing_warnings(receipt):
    workspace, record, path_map, manifest, index = await fixture()
    warnings = tuple(f"已有告警 {n}" for n in range(100))
    record = record.model_copy(update={"visual_inspection_receipt": receipt, "warnings": warnings})
    workspace.files[chart_edits_registry_path(SOURCE)] = json.dumps({
        "version": 1, "records": [record.model_dump(mode="json", by_alias=True)],
    }).encode()

    await migrate(workspace, path_map, manifest, index)
    copied, = await load_chart_edit_records(workspace, "thread", TARGET)

    assert len(copied.pages) == 2
    assert copied.visual_inspection_receipt == {}
    assert len(copied.warnings) == 100
    if receipt:
        assert any("视觉回执" in warning for warning in copied.warnings)
    else:
        assert copied.warnings == warnings


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["partial", "wrong_chart_id", "image_identity", "script", "plot_order", "datasets", "noncanonical", "missing_trace_file"])
async def test_unadopted_partial_or_unproven_groups_are_not_migrated(fault):
    workspace, record, path_map, manifest, index = await fixture()
    chart = manifest.charts[1]
    trace = index.chart_traces[1]
    if fault == "partial":
        manifest.charts = manifest.charts[:1]
    elif fault == "wrong_chart_id":
        manifest.charts = (manifest.charts[0], chart.model_copy(update={"chart_id": "other-chart"}))
    elif fault == "image_identity":
        manifest.charts = (manifest.charts[0], chart.model_copy(update={"sha256": "0" * 64}))
    elif fault == "script":
        index.chart_traces = (index.chart_traces[0], trace.model_copy(update={"script_file_resource_id": None}))
    elif fault == "plot_order":
        index.chart_traces = (index.chart_traces[0], trace.model_copy(update={"plot_data_file_resource_ids": trace.plot_data_file_resource_ids[::-1]}))
    elif fault == "datasets":
        manifest.charts = (manifest.charts[0], chart.model_copy(update={"dataset_ids": ("foreign",)}))
    elif fault == "missing_trace_file":
        index.files = index.files[1:]
    else:
        old = record.pages[1].image.path
        path_map[old] = "reports/revision-2/other.png"
        manifest.charts = (manifest.charts[0], chart.model_copy(update={"path": path_map[old]}))
    await migrate(workspace, path_map, manifest, index)
    assert not await load_chart_edit_records(workspace, "thread", TARGET)
    assert chart_edits_registry_path(TARGET) not in workspace.files


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", ["changed", "missing"])
async def test_target_identity_is_checked_before_any_group_is_registered(fault):
    workspace, record, path_map, manifest, index = await fixture()
    path = path_map[record.pages[1].image.path]
    if fault == "changed":
        workspace.files[path] = b"tampered"
    else:
        workspace.files.pop(path)
    with pytest.raises(ReportingError, match="跨版本改图文件身份已变化"):
        await migrate(workspace, path_map, manifest, index)
    assert chart_edits_registry_path(TARGET) not in workspace.files


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_absent_source_registry_requires_no_target_registry():
    workspace = Workspace()
    await migrate(workspace, {}, SimpleNamespace(charts=()), SimpleNamespace(files=(), chart_traces=()))
    assert not workspace.files
