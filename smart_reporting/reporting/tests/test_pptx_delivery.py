from __future__ import annotations

from hashlib import sha256

import pytest
from pptx import Presentation

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
