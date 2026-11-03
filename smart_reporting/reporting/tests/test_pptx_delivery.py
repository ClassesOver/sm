from __future__ import annotations

import asyncio
import threading
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pptx import Presentation

from smart_reporting.reporting.delivery.pptx import PptxBuildResult, build_editable_pptx
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

from .test_trace_claim_gate import _checkpoint


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


def test_pptx_chart_does_not_cover_editable_conclusions(tmp_path) -> None:
    from PIL import Image

    chart = tmp_path / "chart.png"
    Image.new("RGB", (460, 320), "#b8d8da").save(chart)
    bullets = [f"第{number}条经营结论：收入结构需要持续关注。" for number in range(1, 6)]
    result = build_editable_pptx(
        output_path=tmp_path / "chart-report.pptx", title="运营分析", period="2025年",
        theme="executive", slides=({
            "title": "经营结论", "bullets": bullets, "chartPath": str(chart),
            "evidenceIds": ["analysis_001"],
        },),
    )
    slide = Presentation(result.path).slides[1]
    picture = next(shape for shape in slide.shapes if shape.shape_type == 13)
    texts = {shape.text: shape for shape in slide.shapes if getattr(shape, "has_text_frame", False)}
    for bullet in bullets:
        shape = texts[bullet]
        assert (shape.left + shape.width <= picture.left
                or shape.left >= picture.left + picture.width
                or shape.top + shape.height <= picture.top
                or shape.top >= picture.top + picture.height)
    assert "analysis_001" in slide.notes_slide.notes_text_frame.text
    assert not any("Overlap:" in str(issue) for issue in result.issues)


@pytest.mark.anyio
@pytest.mark.parametrize("cancel", [False, True])
async def test_pptx_render_keeps_loop_responsive_and_worker_owns_temp_files(monkeypatch, cancel):
    from smart_reporting.reporting.workflow.runtime import publication

    checkpoint = _checkpoint({}).model_dump(mode="json", by_alias=True)
    checkpoint["evidenceManifest"] = {
        "evidence": [{
            "analysisId": "analysis_001", "summary": "收入保持增长。", "datasetIds": ["d1"],
            "evidenceFiles": [{"path": "facts.json", "size": 1, "sha256": "a" * 64}],
            "citationIds": ["citation_001"],
        }],
        "datasetSemantics": [{"datasetId": "d1", "rowGrain": "row", "duplicateResolution": "resolved"}],
    }
    state = {
        publication.REPORT_ANALYSIS_PLAN_STATE_KEY: [],
        publication.REPORT_ARTIFACTS_STATE_KEY: {"draft": {
            "reportId": "report-1", "revision": 1, "codingTaskKey": "task-1",
            "datasetSnapshotHash": "a" * 64, "effectiveProfileHash": "b" * 64,
            "markdown": {"path": "report.md", "mediaType": "text/markdown", "size": 1, "sha256": "a" * 64},
            "citations": [{"citationId": "citation_001", "datasetId": "d1", "requirementId": "r1", "snapshotHash": "a" * 64}],
            "sections": ["section_001"], "sectionNumbers": ["1"],
            "headingNumbers": [{"level": 2, "number": "1", "title": "经营", "sectionCode": "section_001", "anchor": "report-section-section_001"}],
        }},
    }
    publication.ReportingCheckpoint.model_validate(checkpoint)
    publication.ReportArtifactManifest.model_validate(state[publication.REPORT_ARTIFACTS_STATE_KEY]["draft"])
    files, local = {}, {}
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def build(*, output_path, **_kwargs):
        local["path"] = output_path
        started.set()
        try:
            assert release.wait(2)
            output_path.write_bytes(b"pptx")
            return PptxBuildResult(str(output_path), 4, sha256(b"pptx").hexdigest(), 2, ())
        finally:
            finished.set()

    async def write(_thread, path, content):
        files[path] = content

    async def identity(_thread, path):
        content = files.get(path)
        return {"missing": True} if content is None else {"size": len(content), "sha256": sha256(content).hexdigest()}

    runtime = SimpleNamespace(
        _state=lambda _context: state,
        _envelope=lambda _context: SimpleNamespace(period=publication.ReportPeriod(start="2025-01-01", end="2025-12-31")),
        _scope=lambda _context: {"threadId": "thread", "externalRunId": "run"},
        state_repository=SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(payload={"workflowCheckpoint": checkpoint}))),
        workspace_service=SimpleNamespace(awrite_bytes=write, ahash_file=identity),
        _apply_durable_command=AsyncMock(),
    )
    monkeypatch.setattr(publication, "build_editable_pptx", build)
    # 看门狗只避免旧同步实现卡住；通过条件是构建尚未结束时协程已获得执行机会。
    watchdog = threading.Timer(1, release.set)
    watchdog.start()
    task = asyncio.create_task(publication.RuntimePublicationMixin._render_pptx(
        runtime, SimpleNamespace(run_id="run"), {}, SimpleNamespace(title="经营报告"),
    ))
    try:
        did_start = await asyncio.to_thread(started.wait, 3)
        assert did_start, task.result() if task.done() else "构建未启动"
        assert not task.done()
        path = local["path"]
        assert path.parent.is_dir()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert path.parent.is_dir()
        release.set()
        if not cancel:
            result = await task
            assert result["status"] == "validated"
            assert files[result["pptxPath"]] == b"pptx"
        assert await asyncio.to_thread(finished.wait, 3)
        async with asyncio.timeout(3):
            while path.parent.exists():
                await asyncio.sleep(0)
    finally:
        release.set()
        watchdog.cancel()
        await asyncio.gather(task, return_exceptions=True)
