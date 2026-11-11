"""共享 Word/PDF 候选发布不得覆盖用户取消终态。"""

import asyncio

import pytest

from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService
from smart_reporting.reporting.tests import test_native_ai

sample = test_native_ai.sample


@pytest.mark.anyio
@pytest.mark.parametrize("raise_after_cancel", [False, True])
async def test_native_ai_candidate_preview_cannot_overwrite_cancelled(
    sample, monkeypatch, raise_after_cancel
):
    editor, context, session, model, _ = sample
    target = model["blocks"][0]
    entered = asyncio.Event()

    async def planner(*_args, **_kwargs):
        return NativeAIProposal(
            summary="候选",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        "blockId": target["blockId"],
                        "expectedObjectSha256": target["expectedObjectSha256"],
                        "text": "候选",
                    },
                }
            ],
        )

    async def preview(_context, *, expected_sha256, operations):
        if operations:
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if raise_after_cancel:
                    raise RuntimeError(
                        "synthetic cancelled dependency failure"
                    ) from None
        return {"model": model, "draftSha256": "b" * 64}

    monkeypatch.setattr(editor, "preview", preview)
    ai = NativeAIService(editor, planner=planner, enabled=True)
    try:
        started = await ai.start_edit(
            session,
            instruction="润色",
            expected_sha256=context.source_file.sha256,
            operations=[],
            selection=[{"blockId": target["blockId"]}],
        )
        await asyncio.wait_for(entered.wait(), timeout=2)
        result = await ai.cancel_edit(session, started["editId"])
        assert (
            result["status"] == "cancelled"
            and "proposal" not in result
            and "error" not in result
        )
        assert (await ai.wait_edit_status(session, started["editId"]))[
            "status"
        ] == "cancelled"
    finally:
        await ai.aclose()
