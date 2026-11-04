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
@pytest.mark.parametrize("extension", ["xlsx", "xls"])
async def test_reference_step_extracts_spreadsheet_sheets_and_cells(extension: str) -> None:
    import io

    if extension == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "收入"
        sheet.append(["指标", "本期"])
        sheet.append(["医疗收入", 125.5])
        stream = io.BytesIO()
        workbook.save(stream)
    else:
        import xlwt

        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("收入")
        for row_index, values in enumerate((("指标", "本期"), ("医疗收入", 125.5))):
            for column_index, value in enumerate(values):
                sheet.write(row_index, column_index, value)
        stream = io.BytesIO()
        workbook.save(stream)

    output = await prepare_reference_materials(
        SimpleNamespace(files=[SimpleNamespace(filename=f"reference.{extension}", content=stream.getvalue())]),
        SimpleNamespace(session_state={}),
    )

    reference = output.content["references"][0]
    assert "医疗收入" in reference["content"]
    assert "125.5" in reference["content"]
    assert reference["layout"]["sheetCount"] == 1
    assert reference["layout"]["sheets"][0]["name"] == "收入"
    assert reference["layout"]["sheets"][0]["rowCount"] == 2
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


@pytest.mark.anyio
async def test_reference_step_adds_multimodal_layout_assessment(monkeypatch) -> None:
    calls = []

    async def analyze(reference, _pages):
        calls.append(reference["filename"])
        return {"style": "深色标题栏，正文采用双栏布局", "confidence": 0.91}

    import smart_reporting.reporting.workflow.runtime.reference_materials as references

    monkeypatch.setattr(references, "_render_visual_pages", lambda _filename, _raw: [b"png-page"])

    import io

    from pptx import Presentation

    presentation = Presentation()
    presentation.slides.add_slide(presentation.slide_layouts[6])
    stream = io.BytesIO()
    presentation.save(stream)
    output = await prepare_reference_materials(
        SimpleNamespace(files=[SimpleNamespace(filename="layout.pptx", content=stream.getvalue())]),
        SimpleNamespace(session_state={}),
        visual_analyzer=analyze,
    )

    assert calls == ["layout.pptx"]
    assert output.content["references"][0]["visualLayout"] == {
        "style": "深色标题栏，正文采用双栏布局",
        "confidence": 0.91,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ["render", "analysis"])
async def test_visual_layout_failure_keeps_parsed_reference_content(
    monkeypatch, tmp_path, failure_stage: str
) -> None:
    from docx import Document

    import smart_reporting.reporting.workflow.runtime.reference_materials as references

    document = Document()
    document.add_paragraph("已解析的参考正文")
    path = tmp_path / "reference.docx"
    document.save(path)

    async def analyze(_reference, _pages):
        raise RuntimeError("视觉识别不可用")

    if failure_stage == "render":
        def render(_filename, _raw):
            raise RuntimeError("页面渲染不可用")

        monkeypatch.setattr(references, "_render_visual_pages", render)
    else:
        monkeypatch.setattr(references, "_render_visual_pages", lambda _filename, _raw: [b"page"])

    output = await prepare_reference_materials(
        SimpleNamespace(files=[SimpleNamespace(filename=path.name, content=path.read_bytes())]),
        SimpleNamespace(session_state={}),
        visual_analyzer=analyze,
    )

    assert len(output.content["references"]) == 1
    assert output.content["references"][0]["content"] == "已解析的参考正文"
    assert "visualLayout" not in output.content["references"][0]
    assert output.content["issues"][0]["code"] == "report_reference_visual_layout_failed"


@pytest.mark.parametrize("extension", ["pptx", "xlsx", "xls"])
def test_office_reference_renders_page_images_for_vision(tmp_path, extension: str) -> None:
    import smart_reporting.reporting.workflow.runtime.reference_materials as references

    if extension == "pptx":
        from pptx import Presentation

        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[6])
        slide.shapes.add_textbox(0, 0, 3_000_000, 500_000).text = "报告标题"
        path = tmp_path / f"visual-reference.{extension}"
        presentation.save(path)
    elif extension == "xlsx":
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active["A1"] = "报告标题"
        path = tmp_path / f"visual-reference.{extension}"
        workbook.save(path)
    else:
        import xlwt

        workbook = xlwt.Workbook()
        workbook.add_sheet("参考").write(0, 0, "报告标题")
        path = tmp_path / f"visual-reference.{extension}"
        workbook.save(str(path))

    pages = references._render_visual_pages(path.name, path.read_bytes())

    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.anyio
async def test_reference_parsing_and_page_rendering_run_off_the_event_loop(monkeypatch) -> None:
    """解析大附件和 LibreOffice 页面渲染不得阻塞事件循环。"""
    import threading

    from smart_reporting.reporting.workflow.runtime import reference_materials as references

    loop_thread = threading.get_ident()
    threads: dict[str, int] = {}

    def parse(file):
        threads["parse"] = threading.get_ident()
        return {"filename": file.filename, "content": "正文", "layout": {}}

    def render(_filename, _raw):
        threads["render"] = threading.current_thread().name
        return [b"page"]

    async def analyze(_reference, pages):
        return {"pages": len(pages)}

    monkeypatch.setattr(references, "_parse", parse)
    monkeypatch.setattr(references, "_render_visual_pages", render)
    output = await prepare_reference_materials(
        SimpleNamespace(files=[SimpleNamespace(filename="reference.docx", content=b"docx")]),
        SimpleNamespace(session_state={}),
        visual_analyzer=analyze,
    )

    assert threads["parse"] != loop_thread
    assert threads["render"].startswith("office-engine")
    assert output.content["references"][0]["visualLayout"] == {"pages": 1}
