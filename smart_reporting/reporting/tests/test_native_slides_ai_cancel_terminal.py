"""依赖吞取消时仍保留原生 AI 的取消终态。"""

import asyncio

import pytest

from smart_reporting.report_editor.slides_ai import SlidesAIProposal
from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
from smart_reporting.reporting.tests.test_slides_native_ai import Editor


@pytest.mark.anyio
@pytest.mark.parametrize(
    "phase", ["original-preview", "draft-preview", "candidate-preview"]
)
@pytest.mark.parametrize("raise_after_cancel", [False, True])
async def test_slides_cancel_is_terminal_before_waiting_for_uncooperative_preview(
    phase, raise_after_cancel
):
    entered = asyncio.Event()
    editor = Editor()
    preview = editor.preview
    calls = []
    observed = []
    planner_calls = []
    base = [{"kind": "editSlides", "order": [0, 1]}] if phase == "draft-preview" else []
    target = {"original-preview": 1, "draft-preview": 2, "candidate-preview": 2}[phase]

    async def controlled_preview(context, **kwargs):
        calls.append(kwargs["operations"])
        if len(calls) == target:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                observed.append(ai._jobs[started["editId"]].status)
                if raise_after_cancel:
                    raise RuntimeError(
                        "synthetic cancelled dependency failure"
                    ) from None
        return await preview(context, **kwargs)

    async def planner(*_args, **_kwargs):
        planner_calls.append(True)
        return SlidesAIProposal(
            summary="候选",
            edits=[{"slideIndex": 0, "elementId": "title", "text": "候选"}],
            order=[0, 1],
        )

    editor.preview = controlled_preview
    ai = NativeSlidesAIService(editor, planner=planner, enabled=True)
    try:
        started = await ai.start_edit(
            None,
            client_request_id="cancel-terminal",
            instruction="润色",
            expected_sha256="a" * 64,
            operations=base,
            selection=[{"slideIndex": 0, "elementId": "title"}],
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        result = await ai.cancel_edit(None, started["editId"])
        assert observed == ["cancelled"]
        assert (
            result["status"] == "cancelled"
            and "proposal" not in result
            and "error" not in result
        )
        assert len(calls) == target
        assert len(planner_calls) == (1 if phase == "candidate-preview" else 0)
        current = await ai.wait_edit_status(None, started["editId"])
        assert current["status"] == "cancelled" and "proposal" not in current
    finally:
        await ai.aclose()
