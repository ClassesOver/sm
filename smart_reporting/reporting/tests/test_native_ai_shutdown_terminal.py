"""服务关闭必须先取消任务身份，再等待不合作的预览依赖。"""

import asyncio

import pytest

from smart_reporting.report_editor.slides_ai import SlidesAIProposal
from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_slides_native_ai import Editor as SlidesEditor
from smart_reporting.reporting.tests.test_workbook_native_ai import (
    Editor as WorkbookEditor,
)
from smart_reporting.reporting.tests.test_workbook_native_ai import proposal


@pytest.mark.anyio
@pytest.mark.parametrize("format", ["pptx", "xlsx"])
@pytest.mark.parametrize("raise_after_cancel", [False, True])
async def test_native_ai_shutdown_cannot_publish_late_candidate(
    format, raise_after_cancel
):
    entered = asyncio.Event()
    editor = SlidesEditor() if format == "pptx" else WorkbookEditor()
    original_preview = editor.preview
    planner_calls = []
    preview_calls = []

    async def controlled_preview(*args, **kwargs):
        preview_calls.append(True)
        if len(preview_calls) == 1:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if raise_after_cancel:
                    raise RuntimeError(
                        "synthetic shutdown dependency failure"
                    ) from None
        return await original_preview(*args, **kwargs)

    async def planner(*_args, **_kwargs):
        planner_calls.append(True)
        return (
            SlidesAIProposal(
                summary="候选",
                edits=[{"slideIndex": 0, "elementId": "title", "text": "候选"}],
                order=[0, 1],
            )
            if format == "pptx"
            else proposal()
        )

    editor.preview = controlled_preview
    ai = (NativeSlidesAIService if format == "pptx" else NativeWorkbookAIService)(
        editor, planner=planner, enabled=True
    )
    selection = (
        [{"slideIndex": 0, "elementId": "title"}]
        if format == "pptx"
        else {
            "sheetName": "Sheet",
            "startRow": 0,
            "endRow": 0,
            "startColumn": 0,
            "endColumn": 0,
        }
    )
    started = await ai.start_edit(
        None,
        client_request_id="shutdown",
        instruction="修改选区",
        expected_sha256="a" * 64,
        operations=[],
        selection=selection,
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await ai.aclose()
        current = await ai.wait_edit_status(None, started["editId"])
        assert (
            current["status"] == "cancelled"
            and "proposal" not in current
            and "error" not in current
        )
        assert planner_calls == [] and len(preview_calls) == 1
        with pytest.raises(ReportingError):
            await ai.accept_edit(
                None,
                started["editId"],
                expected_sha256="a" * 64,
                operations=[],
                snapshot_sha256=started["snapshotSha256"],
            )
    finally:
        await ai.aclose()
