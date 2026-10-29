import hashlib
import json

import pytest
from pydantic import ValidationError

from smart_reporting.report_editor.chart_edits import (
    ChartEditFileRef,
    ChartEditPage,
    ChartEditRecord,
    append_chart_edit_record,
    chart_edit_page_chart_id,
    chart_edit_page_src,
    chart_edit_pages,
    parse_chart_edit_records,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_edit_registry import _chart_record
from smart_reporting.workspace import WorkspaceError


def paged_record():
    base = _chart_record()
    parent = f"reports/revision-1/chart-edits/{base.edit_id}"
    image = base.image.model_copy(update={"path": f"{parent}/chart.png"})
    first = ChartEditPage(pageNumber=1, image=image, chart=base.chart)
    second = ChartEditPage(pageNumber=2,
        image=image.model_copy(update={"path": f"{parent}/chart--page-2.png"}),
        chart=base.chart.model_copy(update={"title": "图（第2/2页）"}))
    return ChartEditRecord.model_validate(base.model_copy(update={
        "image": image, "script": base.script.model_copy(update={"path": f"{parent}/chart_edit.py"}),
        "pages": (first, second),
    }).model_dump())


def test_old_chart_records_normalize_to_one_page_without_changing_identity():
    record = _chart_record()
    pages = chart_edit_pages(record)
    assert len(pages) == 1 and pages[0].image == record.image and pages[0].chart == record.chart
    assert chart_edit_page_chart_id(record, 1) == record.chart_id


def test_page_registry_roundtrip_keeps_all_identities_and_unique_chart_ids():
    record = paged_record()
    raw = json.dumps({"version": 1, "records": [record.model_dump(mode="json", by_alias=True)]}).encode()
    assert parse_chart_edit_records(raw) == (record,)
    assert len({chart_edit_page_chart_id(record, i) for i in (1, 2)}) == 2
    assert chart_edit_page_src("reports/revision-1/report.md", record.edit_id, 2).endswith("/chart--page-2.png")


@pytest.mark.parametrize("fault", ["gap", "duplicate", "foreign", "first_image", "first_meta", "dataset", "bool"])
def test_page_registry_rejects_incomplete_or_foreign_page_declarations(fault):
    payload = paged_record().model_dump(mode="json", by_alias=True)
    page = payload["pages"][1]
    if fault == "gap":
        page["pageNumber"] = 3
    elif fault == "duplicate":
        page["image"]["path"] = payload["image"]["path"]
    elif fault == "foreign":
        page["image"]["path"] = "other/chart--page-2.png"
    elif fault == "first_image":
        payload["pages"][0]["image"]["sha256"] = "a" * 64
    elif fault == "first_meta":
        payload["pages"][0]["chart"]["title"] = "其他图"
    elif fault == "dataset":
        page["chart"]["datasetIds"] = ["foreign"]
    else:
        page["pageNumber"] = True
    with pytest.raises(ValidationError):
        ChartEditRecord.model_validate(payload)


def test_registry_standard_parameters_cannot_introduce_file_identities():
    payload = _chart_record().model_dump(mode="json", by_alias=True)
    payload["standardParameters"] = {"sourcePath": "other.png"}
    with pytest.raises(ValidationError):
        ChartEditRecord.model_validate(payload)


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
@pytest.mark.parametrize("fault", [None, "second_changed", "second_missing", "partial"])
async def test_all_chart_pages_are_authorized_and_atomically_added_to_export_lineage(tmp_path, fault):
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _make_editor_with_chart

    fixture = await _make_editor_with_chart(tmp_path)
    editor, workspace, context = fixture.editor, fixture.workspace, fixture.context
    record = paged_record()
    image = ChartEditFileRef(path=record.image.path, size=len(fixture.chart_bytes),
        sha256=hashlib.sha256(fixture.chart_bytes).hexdigest())
    script = b"# reads bound chart input"
    pages = tuple(page.model_copy(update={
        "image": image.model_copy(update={"path": page.image.path}),
        "chart": page.chart.model_copy(update={"dataset_ids": fixture.chart.dataset_ids}),
    }) for page in record.pages)
    record = ChartEditRecord.model_validate(record.model_copy(update={
        "chart_id": fixture.chart.chart_id, "base_image_path": fixture.chart.path,
        "base_image_sha256": fixture.chart.sha256, "image": image, "chart": pages[0].chart,
        "pages": pages, "script": ChartEditFileRef(path=record.script.path, size=len(script), sha256=hashlib.sha256(script).hexdigest()),
        "plot_data_files": (ChartEditFileRef(path=fixture.plot_path, size=len(fixture.plot_bytes), sha256=hashlib.sha256(fixture.plot_bytes).hexdigest()),),
    }).model_dump())
    for page in record.pages:
        await workspace.awrite_bytes(fixture.thread_id, page.image.path, fixture.chart_bytes)
    await workspace.awrite_bytes(fixture.thread_id, record.script.path, script)
    await append_chart_edit_record(workspace, fixture.thread_id, context.markdown_path, record)
    for page in record.pages:
        assert await editor._chart_edit_asset(context, page.image.path) == page.image.as_identity()
    manifest = await editor.trace.load_manifest(context)
    index = await editor.trace.load_index(context)
    assert manifest and index
    selected = record.pages[:1] if fault == "partial" else record.pages
    markdown = "# Report\n\n" + "\n\n".join(
        f"![{page.chart.title}]({chart_edit_page_src(context.markdown_path, record.edit_id, page.page_number)}) [[citation:citation_001]]\n\n图表：{page.chart.title}"
        for page in selected
    )
    if fault == "second_changed":
        await workspace.awrite_bytes(fixture.thread_id, record.pages[1].image.path, b"changed", overwrite=True)
    elif fault == "second_missing":
        await workspace.adelete_file(fixture.thread_id, record.pages[1].image.path)
    call = editor._chart_edit_lineage(context, markdown=markdown, markdown_path=context.markdown_path, manifest=manifest, index=index)
    if fault:
        with pytest.raises((ReportingError, WorkspaceError)):
            await call
        return
    charts, augmented = await call
    assert set(charts) == {page.image.path for page in record.pages}
    assert len({chart.chart_id for chart in charts.values()}) == 2
    assert {trace.chart_id for trace in augmented.chart_traces} == {chart.chart_id for chart in charts.values()}
    assert all(trace.plot_data_file_resource_ids == index.chart_traces[0].plot_data_file_resource_ids for trace in augmented.chart_traces)
    history = await editor.trace._chart_edit_summaries(context)
    assert len(history[record.chart_id]["history"][0]["pages"]) == 2
