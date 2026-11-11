"""幻灯片候选工具的完整读取、并发提交和预览回执边界。"""

import json
from unittest.mock import AsyncMock

import anyio
import pytest

from smart_reporting.report_editor.slides_ai_tools import SlidesAIToolkit


def _deck(text="原始标题"):
    return {
        "size": {"cx": 9525000, "cy": 5715000},
        "slides": [{"slideIndex": 0, "elements": [{
            "id": "title", "editable": True, "text": text,
            "geometry": {"x": 10, "y": 10, "width": 100, "height": 40},
        }]}],
    }


def _proposal():
    return {
        "summary": "调整标题",
        "edits": [{"slideIndex": 0, "elementId": "title", "text": "候选标题"}],
        "order": [0],
    }


@pytest.mark.anyio
async def test_paginated_slide_requires_all_characters_even_after_reading_the_tail():
    text = "需要完整阅读的原始文字" * 3000
    preview = AsyncMock(return_value={"draftSha256": "a" * 64})
    tools = SlidesAIToolkit(deck=_deck(text), scope="selection", current_order=[0], preview=preview)

    # 先读尾页，再补首页，仍刻意留下一个字符的空洞。
    tail = tools.read_slide(0, offset=24001)
    assert tail["nextOffset"] is None
    assert tail["readComplete"] is False
    with pytest.raises(ValueError, match="read_required"):
        await tools.propose_operations(_proposal())

    first = tools.read_slide(0)
    assert first["nextOffset"] == 24000
    assert first["readComplete"] is False
    with pytest.raises(ValueError, match="read_required"):
        await tools.propose_operations(_proposal())
    preview.assert_not_awaited()
    assert tools.proposal is None

    continuation = tools.read_slide(0, offset=first["nextOffset"])
    assert continuation["readComplete"] is True
    assert json.loads(first["content"] + continuation["content"])[0]["text"] == text
    result = await tools.propose_operations(_proposal())
    assert result["status"] == "previewed"
    preview.assert_awaited_once()


@pytest.mark.anyio
async def test_concurrent_submissions_run_preview_once_and_register_only_the_first_candidate():
    entered = anyio.Event()
    release = anyio.Event()
    results = []

    async def preview_candidate(candidate):
        entered.set()
        await release.wait()
        return {"draftSha256": "b" * 64}

    preview = AsyncMock(side_effect=preview_candidate)
    tools = SlidesAIToolkit(deck=_deck(), scope="selection", current_order=[0], preview=preview)
    tools.read_slide(0)

    async def submit_first():
        results.append(await tools.propose_operations(_proposal()))

    with anyio.fail_after(5):
        async with anyio.create_task_group() as group:
            group.start_soon(submit_first)
            await entered.wait()
            try:
                assert tools.proposal is None
                second = {**_proposal(), "summary": "第二个候选"}
                with pytest.raises(ValueError, match="already_submitted"):
                    await tools.propose_operations(second)
                preview.assert_awaited_once()
            finally:
                release.set()

    assert len(results) == 1
    assert results[0]["previewSha256"] == "b" * 64
    assert tools.proposal.summary == "调整标题"
    preview.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("receipt", [
    None,
    {},
    {"draftSha256": None},
    {"draftSha256": ""},
    {"draftSha256": 123},
    {"draftSha256": "a" * 63},
    {"draftSha256": "z" * 64},
], ids=["null", "missing_hash", "null_hash", "empty_hash", "nonstring_hash", "short_hash", "nonhex_hash"])
async def test_invalid_preview_receipt_never_registers_candidate_and_allows_retry(receipt):
    preview = AsyncMock(side_effect=[receipt, {"draftSha256": "c" * 64}])
    tools = SlidesAIToolkit(deck=_deck(), scope="selection", current_order=[0], preview=preview)
    tools.read_slide(0)

    with pytest.raises(ValueError):
        await tools.propose_operations(_proposal())
    assert tools.proposal is None

    result = await tools.propose_operations(_proposal())
    assert result["previewSha256"] == "c" * 64
    assert tools.proposal.summary == "调整标题"
    assert preview.await_count == 2
