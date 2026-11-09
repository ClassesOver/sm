from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

from smart_reporting.reporting.delivery.pptx import build_editable_pptx
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime


def test_pptx_generation_failure_can_return_without_downloadable_artifact() -> None:
    content = {
        "reportId": "report-1",
        "revision": 1,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1"},
        "markdownPath": "reports/report.md",
        "deliveryFormat": "pptx",
        "validation": {"ok": False, "issues": [{"code": "pptx_generation_failed"}]},
        "validationIssues": [{"code": "pptx_generation_failed"}],
    }

    result = ReportWorkflowRuntime._publication_content(content)

    assert result["deliveryFormat"] == "pptx"
    assert result["pptxPath"] is None


def test_document_publication_still_requires_a_generated_format() -> None:
    content = {
        "reportId": "report-1",
        "revision": 1,
        "jobId": "job-1",
        "editorJob": {"jobId": "job-1"},
        "markdownPath": "reports/report.md",
        "validation": {"ok": False, "issues": []},
    }

    with pytest.raises(ReportingError, match="没有可发布的报告格式"):
        ReportWorkflowRuntime._publication_content(content)


def test_pptx_generation_keeps_text_editable_and_binds_slide_evidence(tmp_path) -> None:
    destination = tmp_path / "hospital-report.pptx"

    result = build_editable_pptx(
        output_path=destination,
        title="2025年医院收入分析",
        period="2025年",
        theme="executive",
        slides=(
            {
                "title": "收入变化",
                "bullets": ["医疗收入同比增长 5.2%"],
                "evidenceIds": ["analysis_001", "analysis_004"],
            },
        ),
    )

    presentation = Presentation(destination)
    texts = [
        shape.text
        for slide in presentation.slides
        for shape in slide.shapes
        if getattr(shape, "has_text_frame", False)
    ]
    notes = [slide.notes_slide.notes_text_frame.text for slide in presentation.slides]
    content = destination.read_bytes()
    assert len(presentation.slides) == 2
    assert any("医疗收入同比增长 5.2%" in text for text in texts)
    assert "analysis_001" in notes[1]
    assert "analysis_004" in notes[1]
    assert result.size == len(content)
    assert result.sha256 == sha256(content).hexdigest()
    assert result.slide_count == 2
    assert result.issues == ()


def test_pptx_generation_accepts_each_business_theme(tmp_path) -> None:
    for theme in ("executive", "clinical", "modern"):
        result = build_editable_pptx(
            output_path=tmp_path / f"{theme}.pptx",
            title="运营分析",
            period="2025年",
            theme=theme,
            slides=({"title": "结论", "bullets": ["收入保持增长"]},),
        )

        assert result.slide_count == 2


def test_pptx_chart_slide_uses_separate_columns_and_fits_long_bullets(tmp_path) -> None:
    chart = tmp_path / "chart.png"
    Image.new("RGB", (460, 320), "white").save(chart)
    bullets = [
        f"结论{index}：医疗服务收入保持增长，需要结合门诊量、住院量与次均费用的变化持续观察经营质量，并跟踪重点科室的服务结构。"
        for index in range(1, 5)
    ] + ["最后一项结论完整保留"]
    destination = tmp_path / "columns.pptx"
    result = build_editable_pptx(
        output_path=destination, title="经营分析", period="2025年", theme="executive",
        slides=(
            {"title": "图文分析", "bullets": bullets, "chartPath": str(chart)},
            {"title": "普通结论", "bullets": ["非图表页保持原布局"]},
        ),
    )
    presentation = Presentation(destination)
    slide = presentation.slides[1]
    picture = next(shape for shape in slide.shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    text_boxes = [next(shape for shape in slide.shapes if getattr(shape, "text", None) == bullet) for bullet in bullets]

    for shape in text_boxes:
        assert shape.left + shape.width <= picture.left
        assert shape.top + shape.height < presentation.slide_height * 660 / 720
        assert shape.text_frame.paragraphs[0].runs[0].font.size.pt == 17
    for previous, following in zip(text_boxes, text_boxes[1:]):
        assert previous.top + previous.height <= following.top
    plain = next(shape for shape in presentation.slides[2].shapes if getattr(shape, "text", None) == "非图表页保持原布局")
    assert plain.left == round(presentation.slide_width * 140 / 1280)
    assert plain.width == round(presentation.slide_width * 1020 / 1280)
    assert plain.top == round(presentation.slide_height * 174 / 720)
    assert plain.height == round(presentation.slide_height * 54 / 720)
    assert result.issues == ()


def test_pptx_audit_exception_keeps_generated_artifact_and_returns_warning(tmp_path, monkeypatch) -> None:
    engine = Path(__file__).parents[1] / "slides_engine"
    isolated = tmp_path / "engine"
    (isolated / "bridge").mkdir(parents=True)
    for name in ("node_modules", "packages", "package.json"):
        (isolated / name).symlink_to(engine / name, target_is_directory=(engine / name).is_dir())
    source = (engine / "bridge/build-pptx.ts").read_text(encoding="utf-8")
    source = source.replace(
        "import { auditDeck } from '../packages/pipelines/src/slides/audit-deck.ts'",
        "const auditDeck = async (_bytes: Uint8Array): Promise<never> => { await readFile(input.output); throw new Error('injected audit failure') }",
    )
    (isolated / "bridge/build-pptx.ts").write_text(source, encoding="utf-8")
    monkeypatch.setenv("AGENT_REPORTING_SLIDES_ENGINE_DIR", str(isolated))
    destination = tmp_path / "audited.pptx"

    result = build_editable_pptx(
        output_path=destination, title="经营分析", period="2025年", theme="executive",
        slides=({"title": "结论", "bullets": ["内容仍然可下载"]},),
    )

    assert len(Presentation(destination).slides) == 2
    assert result.sha256 == sha256(destination.read_bytes()).hexdigest()
    assert result.issues == ({"page": 0, "message": "PPTX layout audit failed: injected audit failure"},)


@pytest.mark.parametrize(("dimensions", "suffix"), [((640, 360), "png"), ((320, 640), "jpeg")])
def test_pptx_chart_keeps_original_proportions_and_bytes(tmp_path, dimensions, suffix) -> None:
    chart = tmp_path / (f"图表 #1.{suffix}" if suffix == "jpeg" else f"图表.{suffix}")
    Image.new("RGB", dimensions, "white").save(chart)
    destination = tmp_path / "report.pptx"
    result = build_editable_pptx(
        output_path=destination, title="经营分析", period="2025年", theme="executive",
        slides=({"title": "收入", "bullets": ["营业收入"], "chartPath": str(chart)},),
    )
    presentation = Presentation(destination)
    picture = next(shape for shape in presentation.slides[1].shapes if shape.shape_type == MSO_SHAPE_TYPE.PICTURE)
    assert picture.width / picture.height == pytest.approx(dimensions[0] / dimensions[1], rel=1e-5)
    assert picture.image.blob == chart.read_bytes()
    assert picture.left >= presentation.slide_width * 700 / 1280 - 1
    assert picture.left + picture.width <= presentation.slide_width * 1160 / 1280 + 1
    assert picture.top >= presentation.slide_height * 220 / 720 - 1
    assert picture.top + picture.height <= presentation.slide_height * 540 / 720 + 1
    assert not result.issues


def test_pptx_chart_slide_retains_excess_content_and_reports_layout_warning(tmp_path) -> None:
    chart = tmp_path / "chart.png"
    Image.new("RGB", (460, 320), "white").save(chart)
    bullets = [f"结论{index}：" + "需要结合门诊量与住院量持续观察经营质量。" * 6 for index in range(7)]
    destination = tmp_path / "excess-content.pptx"

    result = build_editable_pptx(
        output_path=destination, title="经营分析", period="2025年", theme="executive",
        slides=({"title": "完整内容", "bullets": bullets, "chartPath": str(chart)},),
    )

    slide = Presentation(destination).slides[1]
    texts = [shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False)]
    assert all(bullet in texts for bullet in bullets)
    assert result.issues
    assert all(issue["page"] == 2 for issue in result.issues)
    assert result.size == destination.stat().st_size
