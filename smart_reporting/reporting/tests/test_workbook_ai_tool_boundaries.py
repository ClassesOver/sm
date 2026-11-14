"""XLSX 候选登记必须以有效预览回执为准，且同一工具集只能提交一次。"""

from unittest.mock import AsyncMock

import anyio
import pytest

from smart_reporting.report_editor.workbook_ai_tools import WorkbookAIToolkit


def _tools(preview):
    return WorkbookAIToolkit(
        model={"sheets": [{"name": "Sheet", "cells": {"A1": {"value": 1}}}]},
        scope="range",
        selection={
            "sheetName": "Sheet", "startRow": 0, "endRow": 0,
            "startColumn": 0, "endColumn": 0,
        },
        preview=preview,
    )


def _operations(value=2):
    return [{"op": "set_cell", "sheetId": "Sheet", "address": "A1", "value": value}]


@pytest.mark.anyio
@pytest.mark.parametrize("receipt", [
    None, {}, {"draftSha256": None}, {"draftSha256": ""}, {"draftSha256": 123},
    {"draftSha256": "a" * 63}, {"draftSha256": "z" * 64},
], ids=["null", "missing_hash", "null_hash", "empty_hash", "nonstring_hash", "short_hash", "nonhex_hash"])
async def test_invalid_preview_receipt_does_not_freeze_workbook_candidate_and_allows_retry(receipt):
    preview = AsyncMock(side_effect=[receipt, {"draftSha256": "c" * 64}])
    tools = _tools(preview)

    with pytest.raises(ValueError, match="workbook_ai_preview_invalid"):
        await tools.propose_operations(_operations(), "修改选区")
    assert tools.proposal is None

    result = await tools.propose_operations(_operations(3), "修正候选")
    assert result["previewSha256"] == "c" * 64
    assert tools.proposal.summary == "修正候选"
    assert tools.proposal.engine_operations()[0]["edits"][0]["cell"]["value"] == 3
    assert preview.await_count == 2


@pytest.mark.anyio
async def test_concurrent_workbook_submissions_preview_once_and_preserve_first_candidate():
    entered, release = anyio.Event(), anyio.Event()
    results = []

    async def preview_candidate(_candidate):
        entered.set()
        if preview.await_count > 1:
            return {"draftSha256": "d" * 64}
        await release.wait()
        return {"draftSha256": "b" * 64}

    preview = AsyncMock(side_effect=preview_candidate)
    tools = _tools(preview)

    async def submit_first():
        results.append(await tools.propose_operations(_operations(), "首个候选"))

    with anyio.fail_after(2):
        async with anyio.create_task_group() as group:
            group.start_soon(submit_first)
            await entered.wait()
            try:
                assert tools.proposal is None
                with pytest.raises(ValueError, match="already_submitted"):
                    await tools.propose_operations(_operations(3), "第二个候选")
                preview.assert_awaited_once()
            finally:
                release.set()

    assert len(results) == 1
    assert results[0]["previewSha256"] == "b" * 64
    assert tools.proposal.summary == "首个候选"
    preview.assert_awaited_once()


@pytest.mark.anyio
async def test_preview_exception_allows_workbook_candidate_retry():
    preview = AsyncMock(side_effect=[RuntimeError("engine unavailable"), {"draftSha256": "a" * 64}])
    tools = _tools(preview)
    with pytest.raises(RuntimeError, match="engine unavailable"):
        await tools.propose_operations(_operations(), "修改选区")
    assert tools.proposal is None

    assert (await tools.propose_operations(_operations(), "重试候选"))["status"] == "previewed"
    assert tools.proposal.summary == "重试候选"


@pytest.mark.anyio
async def test_successful_workbook_candidate_cannot_be_replaced_by_later_submission():
    preview = AsyncMock(return_value={"draftSha256": "a" * 64})
    tools = _tools(preview)
    result = await tools.propose_operations(_operations(), "首个候选")
    assert result["status"] == "previewed"
    assert result["requiresAcceptance"] is True

    with pytest.raises(ValueError, match="already_submitted"):
        await tools.propose_operations(_operations(3), "替换候选")
    assert tools.proposal.summary == "首个候选"
    preview.assert_awaited_once()


@pytest.mark.anyio
async def test_cancelled_preview_releases_workbook_submission_for_retry():
    entered = anyio.Event()

    async def preview_candidate(_candidate):
        entered.set()
        await anyio.sleep_forever()

    preview = AsyncMock(side_effect=preview_candidate)
    tools = _tools(preview)
    with anyio.fail_after(2):
        async with anyio.create_task_group() as group:
            group.start_soon(tools.propose_operations, _operations(), "取消候选")
            await entered.wait()
            group.cancel_scope.cancel()
    assert tools.proposal is None
    preview.side_effect = None
    preview.return_value = {"draftSha256": "e" * 64}

    result = await tools.propose_operations(_operations(), "重试候选")
    assert result["previewSha256"] == "e" * 64
    assert preview.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize("receipt", [None, {"draftSha256": "invalid"}])
async def test_agno_workbook_loop_corrects_candidate_after_invalid_preview_receipt(receipt):
    from agno.agent import Agent
    from agno.models.response import ModelResponse

    from smart_reporting.report_editor.workbook_ai import AgnoWorkbookProposalPlanner
    from smart_reporting.reporting.tests.test_native_pdf_ai import ScriptedModel
    from smart_reporting.reporting.tests.test_workbook_ai_tools import call

    model = ScriptedModel(id="scripted-workbook-preview-retry", responses=[
        call("propose_operations", {"operations": _operations(), "summary": "初始候选"}, "first"),
        call("propose_operations", {"operations": _operations(3), "summary": "修正候选"}, "retry"),
        ModelResponse(content="候选等待采纳"),
    ])
    preview = AsyncMock(side_effect=[receipt, {"draftSha256": "f" * 64}])
    source = _tools(preview)
    proposal = await AgnoWorkbookProposalPlanner(Agent(model=model)).plan_workbook(
        "修改选中单元格", model=source._model, scope="range", selection=source._selection,
        preview=preview, session_id="preview-retry", user_id="user",
    )

    assert proposal.summary == "修正候选"
    assert proposal.engine_operations()[0]["edits"][0]["cell"]["value"] == 3
    assert preview.await_count == 2
    assert any(
        message.role == "tool" and "workbook_ai_preview_invalid" in str(message.content)
        for turn in model.seen for message in turn
    )
