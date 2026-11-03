from __future__ import annotations

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.workflow.runtime.reference_materials import (
    prepare_reference_materials,
)


@pytest.mark.anyio
async def test_reference_step_without_files_continues_with_empty_context() -> None:
    context = SimpleNamespace(session_state={})

    output = await prepare_reference_materials(SimpleNamespace(files=None), context)

    assert output.content == {"references": [], "issues": []}
    assert context.session_state["report_reference_materials"] == []


@pytest.mark.anyio
async def test_reference_step_extracts_docx_content_and_keeps_layout_summary(tmp_path) -> None:
    from docx import Document

    document = Document()
    document.add_heading("月度运营报告", level=1)
    document.add_paragraph("重点关注收入与成本变化。")
    path = tmp_path / "reference.docx"
    document.save(path)
    media = SimpleNamespace(
        filename="reference.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=path.read_bytes(),
    )
    context = SimpleNamespace(session_state={})

    output = await prepare_reference_materials(SimpleNamespace(files=[media]), context)

    assert "月度运营报告" in output.content["references"][0]["content"]
    assert output.content["references"][0]["layout"]
    assert output.content["issues"] == []


@pytest.mark.anyio
async def test_reference_step_reports_invalid_file_as_soft_issue() -> None:
    media = SimpleNamespace(filename="broken.pdf", mime_type="application/pdf", content=b"bad")
    context = SimpleNamespace(session_state={})

    output = await prepare_reference_materials(SimpleNamespace(files=[media]), context)

    assert output.content["references"] == []
    assert output.content["issues"][0]["filename"] == "broken.pdf"
    assert context.session_state["report_reference_issues"] == output.content["issues"]


@pytest.mark.anyio
async def test_reference_step_soft_limits_count_and_size() -> None:
    from pptx import Presentation

    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    import io

    stream = io.BytesIO()
    presentation.save(stream)
    raw = stream.getvalue()
    files = [
        SimpleNamespace(filename=f"reference-{index}.pptx", content=raw)
        for index in range(5)
    ]
    context = SimpleNamespace(session_state={})

    output = await prepare_reference_materials(SimpleNamespace(files=files), context)

    assert len(output.content["references"]) == 4
    assert any(item["code"] == "report_reference_limit_exceeded" for item in output.content["issues"])


@pytest.mark.anyio
async def test_reference_layout_contains_visual_geometry_summary(tmp_path) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_textbox(Inches(1), Inches(1), Inches(5), Inches(1)).text = "标题"
    path = tmp_path / "reference.pptx"
    presentation.save(path)
    context = SimpleNamespace(session_state={})

    output = await prepare_reference_materials(
        SimpleNamespace(files=[SimpleNamespace(filename="reference.pptx", content=path.read_bytes())]),
        context,
    )

    layout = output.content["references"][0]["layout"]
    assert layout["slides"][0]["textBlocks"] == 1
    assert layout["slides"][0]["aspectRatio"] > 1
