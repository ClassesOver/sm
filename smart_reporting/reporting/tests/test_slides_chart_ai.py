from __future__ import annotations

import hashlib
import io
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.util import Inches

from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_chart_ai import (
    FakeRunner,
    _make_editor_with_chart,
    _service,
)


def _deck(chart: bytes) -> bytes:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_picture(io.BytesIO(chart), Inches(1), Inches(1), Inches(4), Inches(3))
    image = Image.new("RGB", (12, 12), "red")
    output = io.BytesIO()
    image.save(output, format="PNG")
    slide.shapes.add_picture(
        io.BytesIO(output.getvalue()), Inches(6), Inches(1), Inches(1), Inches(1)
    )
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(3), Inches(1)).text = "保留原页"
    output = io.BytesIO()
    presentation.save(output)
    return output.getvalue()


async def _fixture(tmp_path: Path, *, published_chart_id: str | None = None):
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    from smart_reporting.report_editor.slides_chart_ai import ReportSlidesChartAIService

    fixture = await _make_editor_with_chart(tmp_path)
    if published_chart_id is not None:
        manifest = await fixture.editor.trace.load_manifest(fixture.context)
        manifest = manifest.model_copy(update={
            "charts": (manifest.charts[0].model_copy(update={"chart_id": published_chart_id}),),
        })
        content = manifest.model_dump_json(by_alias=True).encode()
        identity = fixture.context.artifact_manifest
        await fixture.workspace.awrite_bytes(
            fixture.thread_id, identity.path, content, overwrite=True
        )
        fixture.context = fixture.context.model_copy(update={
            "artifact_manifest": identity.model_copy(update={
                "size": len(content), "sha256": hashlib.sha256(content).hexdigest(),
            }),
        })
    content = _deck(fixture.chart_bytes)
    context = fixture.context.model_copy(
        update={
            "delivery_format": "pptx",
            "pptx_path": "reports/revision-1/report.pptx",
            "pptx_size": len(content),
            "pptx_sha256": hashlib.sha256(content).hexdigest(),
        }
    )
    await fixture.workspace.awrite_bytes(fixture.thread_id, context.pptx_path, content)
    fixture.editor.state_repository.durable.payload["reportEditorContexts"]["1"] = (
        context.model_dump(mode="json", by_alias=True)
    )
    fixture.context = context
    fixture.content = content
    fixture.session = ReportEditorSession(
        report_id=context.report_id,
        revision=context.revision,
        workflow_run_id=context.workflow_run_id,
        context_sha256=context.digest(),
        expires_at=datetime.now(UTC),
        capabilities={"pptx_editor": True},
    )
    fixture.slides = ReportSlidesEditorService(
        state_repository=fixture.editor.state_repository,
        workspace_registry=fixture.editor.workspace_registry,
        workspace=fixture.workspace,
    )
    image = Image.open(io.BytesIO(fixture.chart_bytes)).convert("RGB")
    image.putpixel((0, 0), (200, 10, 20))
    output = io.BytesIO()
    image.save(output, format="PNG")
    fixture.replacement = output.getvalue()
    fixture.chart_ai = _service(fixture, FakeRunner(fixture.replacement))
    fixture.service = ReportSlidesChartAIService(fixture.slides, chart_ai=fixture.chart_ai)
    return fixture


@pytest.mark.anyio
async def test_pptx_chart_edit_uses_trace_identity_when_publication_renumbers_chart(tmp_path):
    fixture = await _fixture(tmp_path, published_chart_id="published_099")
    chart = (await fixture.service.list_charts(fixture.session))["charts"][0]
    assert chart["chartId"] == "chart_001"
    assert chart["available"] is True
    started = await fixture.service.start_edit(
        fixture.session, chart["slideIndex"], chart["elementId"], "改为横向条形图"
    )
    await fixture.chart_ai._jobs[started["editId"]].task
    replacements = await fixture.service.resolve_for_session(
        fixture.session, [{"candidateId": started["editId"]}]
    )
    assert replacements[0]["binding"]["chartId"] == "chart_001"
    assert replacements[0]["bytes"] == fixture.replacement
    assert fixture.content == await fixture.slides._read_verified_pptx(fixture.context)


@pytest.mark.anyio
async def test_pptx_chart_candidate_reuses_registered_data_and_replaces_only_bound_picture(
    tmp_path,
):
    from smart_reporting.report_editor.slides_chart_ai import (
        inspect_pptx_pictures,
        replace_pptx_pictures,
    )

    fixture = await _fixture(tmp_path)
    listing = await fixture.service.list_charts(fixture.session)
    assert len(listing["charts"]) == 1
    chart = listing["charts"][0]
    assert chart["chartId"] == "chart_001"
    assert chart["baseImagePath"] == fixture.chart_path
    started = await fixture.service.start_edit(
        fixture.session, chart["slideIndex"], chart["elementId"], "改为横向条形图"
    )
    await fixture.chart_ai._jobs[started["editId"]].task
    status = await fixture.service.edit_status(fixture.session, started["editId"])
    assert status["status"] == "succeeded"
    assert status["previewDataUrl"].startswith("data:image/png;base64,")
    assert status["accepted"] is False
    replacements = await fixture.service.resolve_for_session(
        fixture.session, [{"candidateId": started["editId"]}]
    )
    assert len(replacements) == 1
    assert replacements[0]["bytes"] == fixture.replacement
    assert replacements[0]["binding"]["chartId"] == "chart_001"
    assert replacements[0]["binding"]["plotDataFiles"]
    revised = replace_pptx_pictures(fixture.content, replacements)
    pictures = inspect_pptx_pictures(revised)
    assert pictures[0]["sha256"] == hashlib.sha256(fixture.replacement).hexdigest()
    assert pictures[1]["sha256"] == inspect_pptx_pictures(fixture.content)[1]["sha256"]
    with ZipFile(io.BytesIO(fixture.content)) as before, ZipFile(io.BytesIO(revised)) as after:
        assert after.read("ppt/slides/slide2.xml") == before.read("ppt/slides/slide2.xml")
    assert fixture.content == await fixture.slides._read_verified_pptx(fixture.context)
    await fixture.service.discard_candidates(fixture.session, [started["editId"]])
    with pytest.raises(ReportingError, match="候选"):
        await fixture.service.resolve_for_session(
            fixture.session, [{"candidateId": started["editId"]}]
        )


@pytest.mark.anyio
async def test_pptx_chart_rejects_decoration_and_changed_candidate_without_touching_pptx(tmp_path):
    from smart_reporting.report_editor.slides_chart_ai import inspect_pptx_pictures

    fixture = await _fixture(tmp_path)
    pictures = inspect_pptx_pictures(fixture.content)
    with pytest.raises(ReportingError):
        await fixture.service.start_edit(fixture.session, 0, pictures[1]["elementId"], "改颜色")
    chart = (await fixture.service.list_charts(fixture.session))["charts"][0]
    started = await fixture.service.start_edit(fixture.session, 0, chart["elementId"], "改颜色")
    await fixture.chart_ai._jobs[started["editId"]].task
    status = await fixture.service.edit_status(fixture.session, started["editId"])
    await fixture.workspace.awrite_bytes(
        fixture.thread_id, status["imagePath"], b"changed", overwrite=True
    )
    with pytest.raises(ReportingError):
        await fixture.service.resolve_for_session(
            fixture.session, [{"candidateId": started["editId"]}]
        )
    assert fixture.content == await fixture.slides._read_verified_pptx(fixture.context)
    with pytest.raises(ReportingError):
        await fixture.service.edit_status(
            replace(fixture.session, context_sha256="0" * 64), started["editId"]
        )


@pytest.mark.anyio
async def test_failed_chart_generation_retains_original_picture(tmp_path):
    fixture = await _fixture(tmp_path)

    async def fail(*_args, **_kwargs):
        raise RuntimeError("drawing failed")

    fixture.chart_ai.runner.run = fail
    chart = (await fixture.service.list_charts(fixture.session))["charts"][0]
    started = await fixture.service.start_edit(fixture.session, 0, chart["elementId"], "改颜色")
    with pytest.raises(ReportingError):
        await fixture.chart_ai._jobs[started["editId"]].task
    result = await fixture.service.edit_status(fixture.session, started["editId"])
    assert result["status"] == "failed"
    assert "previewDataUrl" not in result
    assert fixture.content == await fixture.slides._read_verified_pptx(fixture.context)
    with pytest.raises(ReportingError):
        await fixture.service.resolve_for_session(
            fixture.session, [{"candidateId": started["editId"]}]
        )


async def _accepted_revision(fixture):
    from smart_reporting.report_editor.slides_chart_ai import replace_pptx_pictures

    chart = (await fixture.service.list_charts(fixture.session))["charts"][0]
    started = await fixture.service.start_edit(fixture.session, 0, chart["elementId"], "改颜色")
    await fixture.chart_ai._jobs[started["editId"]].task
    replacement = (
        await fixture.service.resolve_for_session(
            fixture.session, [{"candidateId": started["editId"]}]
        )
    )[0]
    content = replace_pptx_pictures(fixture.content, [replacement])
    context = fixture.context.model_copy(
        update={
            "revision": 2,
            "pptx_path": "reports/revision-1/report-r2.pptx",
            "pptx_size": len(content),
            "pptx_sha256": hashlib.sha256(content).hexdigest(),
            "job": {
                **fixture.context.job,
                "pptxChartEdits": [
                    {
                        "slidePath": replacement["slidePath"],
                        "shapeId": replacement["shapeId"],
                        **replacement["binding"],
                    }
                ],
            },
        }
    )
    await fixture.workspace.awrite_bytes(fixture.thread_id, context.pptx_path, content)
    fixture.editor.state_repository.durable.payload["reportEditorContexts"]["2"] = (
        context.model_dump(mode="json", by_alias=True)
    )
    session = replace(fixture.session, revision=2, context_sha256=context.digest())
    return context, session, started["editId"]


@pytest.mark.anyio
@pytest.mark.parametrize("published_chart_id", [None, "published_099"])
async def test_saved_chart_reopens_and_continues_from_registered_candidate_data(tmp_path, published_chart_id):
    from smart_reporting.report_editor.slides_chart_ai import ReportSlidesChartAIService

    fixture = await _fixture(tmp_path, published_chart_id=published_chart_id)
    _, session, previous_id = await _accepted_revision(fixture)
    # 重启服务后仍从持久化作用域与登记中恢复，不能依赖内存候选。
    service = ReportSlidesChartAIService(fixture.slides, chart_ai=fixture.chart_ai)
    chart = (await service.list_charts(session))["charts"][0]
    assert chart["previousEditId"] == previous_id
    assert chart["sha256"] == hashlib.sha256(fixture.replacement).hexdigest()
    assert chart["baseImagePath"].endswith("/chart.png")
    started = await service.start_edit(session, 0, chart["elementId"], "继续调整标题")
    await fixture.chart_ai._jobs[started["editId"]].task
    status = await service.edit_status(session, started["editId"])
    assert status["status"] == "succeeded"
    assert (await service.resolve_for_session(session, [{"candidateId": started["editId"]}]))[0][
        "binding"
    ]["sourceRevision"] == 1


@pytest.mark.anyio
async def test_chart_save_reorders_pages_and_reopens_the_replaced_object(tmp_path, monkeypatch):
    from smart_reporting.report_editor.slides_chart_ai import (
        ReportSlidesChartAIService,
        inspect_pptx_pictures,
    )

    fixture = await _fixture(tmp_path)
    chart = (await fixture.service.list_charts(fixture.session))["charts"][0]
    started = await fixture.service.start_edit(fixture.session, 0, chart["elementId"], "调整颜色")
    await fixture.chart_ai._jobs[started["editId"]].task
    replacements = await fixture.service.resolve_for_session(
        fixture.session, [{"candidateId": started["editId"]}],
    )
    monkeypatch.setattr(fixture.slides, "_render_pdf", lambda _content: b"%PDF-preview")
    result = await fixture.slides.save_revision(
        fixture.session, {"expectedSha256": fixture.context.pptx_sha256, "order": [1, 0]},
        chart_replacements=replacements,
    )
    context = ReportEditorContext.model_validate(
        fixture.editor.state_repository.durable.payload["reportEditorContexts"]["2"],
    )
    session = replace(fixture.session, revision=result["revision"], context_sha256=context.digest())
    content = await fixture.slides._read_verified_pptx(context)
    pictures = inspect_pptx_pictures(content)
    assert pictures[0]["slideIndex"] == 1
    assert pictures[0]["sha256"] == hashlib.sha256(fixture.replacement).hexdigest()
    assert Presentation(io.BytesIO(content)).slides[0].shapes[0].text == "保留原页"
    reopened = ReportSlidesChartAIService(fixture.slides, chart_ai=fixture.chart_ai)
    saved = (await reopened.list_charts(session))["charts"][0]
    assert saved["slideIndex"] == 1
    assert saved["previousEditId"] == started["editId"]


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["context", "record", "plot"])
async def test_saved_chart_binding_fault_only_disables_editing_and_retains_pptx(tmp_path, fault):
    fixture = await _fixture(tmp_path)
    context, session, _ = await _accepted_revision(fixture)
    if fault == "plot":
        path = context.job["pptxChartEdits"][0]["plotDataFiles"][0]["path"]
        await fixture.workspace.awrite_bytes(fixture.thread_id, path, b"changed", overwrite=True)
    else:
        job = {**context.job, "pptxChartEdits": [dict(context.job["pptxChartEdits"][0])]}
        if fault == "context":
            job["pptxChartEdits"][0]["sourceContextSha256"] = "0" * 64
        else:
            job["pptxChartEdits"][0]["record"] = {
                **job["pptxChartEdits"][0]["record"],
                "userId": "foreign-user",
            }
        context = context.model_copy(update={"job": job})
        fixture.editor.state_repository.durable.payload["reportEditorContexts"]["2"] = (
            context.model_dump(mode="json", by_alias=True)
        )
        session = replace(session, context_sha256=context.digest())
    assert (await fixture.service.list_charts(session))["charts"] == []
    assert await fixture.slides._read_verified_pptx(context)


@pytest.mark.anyio
async def test_ambiguous_registered_image_identity_is_not_editable(tmp_path):
    from smart_reporting.reporting.delivery.artifacts_v1 import ChartArtifact
    from smart_reporting.reporting.trace.contracts_v1 import derive_resource_id

    fixture = await _fixture(tmp_path)
    manifest, index = await fixture.editor.trace.load_manifest_and_index(fixture.context)
    second = ChartArtifact.model_validate(
        {
            **fixture.chart.model_dump(mode="json", by_alias=True),
            "chartId": "chart_002",
            "path": "reports/revision-1/another-chart.png",
        }
    )
    image_ref = next(
        ref
        for ref in index.files
        if ref.resource_id == index.chart_traces[0].image_file_resource_id
    )
    second_ref = image_ref.model_copy(
        update={"path": second.path, "resource_id": derive_resource_id(second.path)}
    )
    second_trace = index.chart_traces[0].model_copy(
        update={"chart_id": second.chart_id, "image_file_resource_id": second_ref.resource_id}
    )

    async def ambiguous(_context):
        return manifest.model_copy(update={"charts": (*manifest.charts, second)}), index.model_copy(
            update={
                "files": (*index.files, second_ref),
                "chart_traces": (*index.chart_traces, second_trace),
            }
        )

    fixture.editor.trace.load_manifest_and_index = ambiguous
    assert (await fixture.service.list_charts(fixture.session))["charts"] == []
    assert fixture.content == await fixture.slides._read_verified_pptx(fixture.context)


def test_picture_bridge_rejects_stale_source_identity_without_modifying_input():
    from smart_reporting.report_editor.slides_chart_ai import (
        inspect_pptx_pictures,
        replace_pptx_pictures,
    )
    from smart_reporting.reporting.tests.test_report_editor_chart_ai import _png_bytes

    png = _png_bytes()
    content = _deck(png)
    picture = inspect_pptx_pictures(content)[0]
    replacement = {
        **picture,
        "expectedSha256": "0" * 64,
        "expectedSize": picture["size"],
        "bytes": png,
        "extension": "png",
    }
    with pytest.raises(ReportingError):
        replace_pptx_pictures(content, [replacement])
    assert inspect_pptx_pictures(content)[0]["sha256"] == hashlib.sha256(png).hexdigest()


@pytest.mark.anyio
@pytest.mark.parametrize("instruction", [None, "", " " * 10, "x" * 2001])
async def test_invalid_chart_instruction_returns_editor_error(tmp_path, instruction):
    fixture = await _fixture(tmp_path)
    chart = (await fixture.service.list_charts(fixture.session))["charts"][0]
    with pytest.raises(ReportingError) as error:
        await fixture.service.start_edit(fixture.session, 0, chart["elementId"], instruction)
    assert error.value.code.startswith("report_slides_chart_instruction_")
