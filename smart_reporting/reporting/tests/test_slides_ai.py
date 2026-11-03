from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from smart_reporting.report_editor.service import ReportEditorContext, ReportEditorSession
from smart_reporting.report_editor.slides_ai import ReportSlidesAIService


def _context() -> ReportEditorContext:
    return ReportEditorContext(
        reportId="ai-report",
        revision=2,
        jobId="job-ai",
        workflowRunId="run-ai",
        markdownPath="reports/report.md",
        job={"jobId": "job-ai"},
        scope={"database": "db", "companyId": "company", "userId": "user", "sessionId": "session", "threadId": "thread"},
        deliveryFormat="pptx",
        pptxPath="reports/report.pptx",
        pptxSize=10,
        pptxSha256="a" * 64,
    )


def _session(context: ReportEditorContext) -> ReportEditorSession:
    return ReportEditorSession(
        report_id=context.report_id,
        revision=context.revision,
        workflow_run_id=context.workflow_run_id,
        context_sha256=context.digest(),
        expires_at=datetime.now(UTC),
        capabilities={"pptx_editor": True},
    )


class FakeSlides:
    async def context_for_session(self, _session):
        return _context()

    async def deck_for_session(self, _session):
        return {
            "size": {"cx": 9144000, "cy": 5143500},
            "slides": [{"slideIndex": 0, "elements": [
                {"id": "title", "type": "shape", "text": "收入", "editable": True,
                 "geometry": {"x": 10, "y": 10, "width": 100, "height": 30}},
                {"id": "chart", "type": "picture", "text": "", "editable": False,
                 "geometry": {"x": 10, "y": 60, "width": 100, "height": 100}},
            ]}, {"slideIndex": 1, "elements": []}],
        }


class FakeAgent:
    def __init__(self, output: str):
        self.output = output
        self.prompts = []

    async def arun(self, prompt, **_kwargs):
        self.prompts.append(prompt)
        return SimpleNamespace(content=self.output)


@pytest.mark.anyio
async def test_slides_ai_runs_background_task_and_returns_validated_preview():
    proposal = {
        "summary": "突出收入结论",
        "edits": [{"slideIndex": 0, "elementId": "title", "text": "收入保持增长"}],
        "order": [1, 0],
        "theme": "modern",
    }
    agent = FakeAgent(json.dumps(proposal, ensure_ascii=False))
    service = ReportSlidesAIService(FakeSlides(), agent=agent)

    started = await service.start_edit(_session(_context()), "突出收入结论并把结论页放到前面")
    result = await service.wait_edit_status(_session(_context()), started["editId"])

    assert result["status"] == "succeeded"
    assert result["proposal"] == proposal
    assert "收入" in agent.prompts[0]
    assert result["accepted"] is False


@pytest.mark.anyio
async def test_slides_ai_discards_operations_that_target_uneditable_objects():
    agent = FakeAgent(json.dumps({
        "summary": "编辑图像",
        "edits": [{"slideIndex": 0, "elementId": "chart", "text": "伪造图中文字"}],
        "order": [0, 1],
    }))
    service = ReportSlidesAIService(FakeSlides(), agent=agent)

    started = await service.start_edit(_session(_context()), "改图上的文字")
    result = await service.wait_edit_status(_session(_context()), started["editId"])

    assert result["status"] == "failed"
    assert result["error"]["code"] == "report_slides_ai_proposal_invalid"
    assert "proposal" not in result


@pytest.mark.anyio
async def test_slides_ai_cancel_stops_an_unfinished_task():
    entered = asyncio.Event()
    release = asyncio.Event()

    class WaitingAgent:
        async def arun(self, _prompt, **_kwargs):
            entered.set()
            await release.wait()
            return SimpleNamespace(content='{"summary":"x","edits":[],"order":[0,1]}')

    service = ReportSlidesAIService(FakeSlides(), agent=WaitingAgent())
    session = _session(_context())
    started = await service.start_edit(session, "调整布局")
    await entered.wait()
    await service.cancel_edit(session, started["editId"])
    result = await service.edit_status(session, started["editId"])

    assert result["status"] == "cancelled"
