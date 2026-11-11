"""原生 AI 候选使用真实 Word/PDF 桥接，采纳只更新草稿。"""

from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from docx import Document

from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.docx_native import inspect_docx
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError


@pytest.fixture
async def sample(tmp_path):
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret="w" * 32))
    scope = NativeScope(database="db", companyId="company", userId="user", threadId="thread")
    key = bind_native_workspace(workspace, scope)
    document = Document()
    document.add_paragraph("第一段原文")
    document.add_paragraph("未经选择的机密段落")
    document.add_table(rows=1, cols=1).cell(0, 0).text = "表格原文"
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    await workspace.awrite_bytes(key, "native/source.docx", content)
    context = NativeEditorContext(
        documentId="doc",
        revision=1,
        format="docx",
        origin="report",
        scope=scope,
        sourceFile=ArtifactFile(
            path="native/source.docx",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mediaType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    )
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="g" * 32)
    editor = NativeEditorService(
        workspace,
        SimpleNamespace(
            get_revision=AsyncMock(return_value=SimpleNamespace(status="saved", context=context))
        ),
        grants,
        report_editor=None,
        docx_enabled=True,
    )
    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await grants.exchange(raw)
    model = inspect_docx(content)
    return editor, context, session, model, content


def replacement(block, text):
    return {
        "kind": "replaceParagraph",
        "blockId": block["blockId"],
        "expectedObjectSha256": block["expectedObjectSha256"],
        "text": text,
    }


@pytest.mark.anyio
async def test_word_ai_sees_unsaved_selection_and_keeps_original_anchors(sample):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, original = sample
    target = model["blocks"][0]
    seen = []

    async def planner(prompt, **kwargs):
        seen.append(prompt)
        return NativeAIProposal(
            summary="润色所选段落",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        "blockId": target["blockId"],
                        "expectedObjectSha256": target["expectedObjectSha256"],
                        "text": "候选最终文字",
                    },
                }
            ],
        )

    ai = NativeAIService(editor, planner=planner, enabled=True)
    base = [replacement(target, "人工未保存文字")]
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=base,
        selection=[{"blockId": target["blockId"]}],
    )
    result = await ai.wait_edit_status(session, started["editId"])
    assert result["status"] == "succeeded", result
    assert "人工未保存文字" in seen[0]
    assert "未经选择的机密段落" not in seen[0]
    assert result["proposal"]["operations"][0]["blockId"] == target["blockId"]
    accepted = await ai.accept_edit(
        session,
        started["editId"],
        expected_sha256=context.source_file.sha256,
        operations=base,
        snapshot_sha256=result["snapshotSha256"],
    )
    assert accepted["operations"] == [*base, replacement(target, "候选最终文字")]
    assert accepted["needsVerification"] is True
    assert await editor.read_file(context) == original
    await ai.aclose()


@pytest.mark.anyio
async def test_candidate_cannot_edit_outside_selected_objects(sample):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, _ = sample
    foreign = model["blocks"][1]
    planner = AsyncMock(
        return_value=NativeAIProposal(
            summary="不合法跨选区",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        k: v for k, v in replacement(foreign, "不得改写").items() if k != "kind"
                    },
                }
            ],
        )
    )
    ai = NativeAIService(editor, planner=planner, enabled=True)
    job = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": model["blocks"][0]["blockId"]}],
    )
    result = await ai.wait_edit_status(session, job["editId"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == "native_ai_selection_mismatch"
    await ai.aclose()


@pytest.mark.anyio
async def test_accept_rechecks_entire_draft_not_only_client_snapshot(sample):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, _ = sample
    target = model["blocks"][0]
    planner = AsyncMock(
        return_value=NativeAIProposal(
            summary="候选",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        k: v for k, v in replacement(target, "AI").items() if k != "kind"
                    },
                }
            ],
        )
    )
    ai = NativeAIService(editor, planner=planner, enabled=True)
    job = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": target["blockId"]}],
    )
    result = await ai.wait_edit_status(session, job["editId"])
    with pytest.raises(ReportingError) as error:
        await ai.accept_edit(
            session,
            job["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[replacement(model["blocks"][1], "别处改动")],
            snapshot_sha256=result["snapshotSha256"],
        )
    assert error.value.code == "native_ai_snapshot_changed"
    await ai.aclose()


@pytest.mark.anyio
async def test_cancel_and_timeout_keep_manual_draft(sample):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, original = sample

    async def planner(*args, **kwargs):
        await asyncio.sleep(10)

    ai = NativeAIService(editor, planner=planner, enabled=True, timeout_seconds=0.01)
    kwargs = dict(
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": model["blocks"][0]["blockId"]}],
    )
    job = await ai.start_edit(session, **kwargs)
    result = await ai.wait_edit_status(session, job["editId"])
    assert result["status"] == "failed" and result["error"]["code"] == "native_ai_timeout"
    ai.timeout_seconds = 30
    second = await ai.start_edit(session, **kwargs)
    assert (await ai.cancel_edit(session, second["editId"]))["status"] == "cancelled"
    assert await editor.read_file(context) == original
    await ai.aclose()


@pytest.mark.anyio
async def test_cell_selection_uses_original_cell_hash_with_unsaved_text(sample):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, _ = sample
    table = model["blocks"][2]
    cell = table["cells"][0][0]
    op = {
        "kind": "replaceCellText",
        "blockId": table["blockId"],
        "cellId": cell["cellId"],
        "expectedObjectSha256": cell["expectedObjectSha256"],
        "text": "人工表格",
    }

    async def planner(prompt, **kwargs):
        assert "人工表格" in prompt
        return NativeAIProposal(
            summary="表格润色",
            operations=[
                {
                    "kind": "replaceCellText",
                    "arguments": {
                        k: v for k, v in {**op, "text": "候选表格"}.items() if k != "kind"
                    },
                }
            ],
        )

    ai = NativeAIService(editor, planner=planner, enabled=True)
    job = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[op],
        selection=[{"blockId": table["blockId"], "cellId": cell["cellId"]}],
    )
    assert (await ai.wait_edit_status(session, job["editId"]))["status"] == "succeeded"
    await ai.aclose()


@pytest.mark.anyio
async def test_ai_routes_require_native_cookie_csrf_and_keep_candidate_in_draft(sample):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService
    from smart_reporting.report_editor.native_ai_api import create_native_ai_router
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE

    editor, context, session, model, original = sample
    block = model["blocks"][0]
    planner = AsyncMock(
        return_value=NativeAIProposal(
            summary="润色",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        k: v for k, v in replacement(block, "候选").items() if k != "kind"
                    },
                }
            ],
        )
    )
    ai = NativeAIService(editor, planner=planner, enabled=True)
    app = FastAPI()
    app.include_router(
        create_native_ai_router(editor.grants, editor=editor, ai=ai, allowed_origin="http://test")
    )
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    root = f"/reports/v1/native/{context.document_id}/{context.revision}/api/ai"
    payload = {
        "instruction": "润色",
        "expectedSha256": context.source_file.sha256,
        "operations": [],
        "selection": [{"blockId": block["blockId"]}],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set(
            NATIVE_SESSION_COOKIE,
            token,
            path=f"/reports/v1/native/{context.document_id}/{context.revision}",
        )
        assert (await client.post(root + "/start", json=payload)).status_code == 403
        headers = {"Origin": "http://test", "X-CSRF-Token": editor.grants.csrf_token(token)}
        started = await client.post(root + "/start", json=payload, headers=headers)
        assert started.status_code == 200, started.text
        edit_id = started.json()["editId"]
        status = await client.get(root + "/" + edit_id)
        assert status.json()["status"] == "succeeded"
        progress = await client.get(root + "/" + edit_id + "/events")
        assert progress.headers["content-type"].startswith("text/event-stream")
        assert '"kind":"terminal"' in progress.text
        changed = {
            "expectedSha256": context.source_file.sha256,
            "operations": [replacement(block, "changed")],
            "snapshotSha256": status.json()["snapshotSha256"],
        }
        assert (
            await client.post(root + "/" + edit_id + "/accept", json=changed, headers=headers)
        ).status_code == 409
        changed["operations"] = []
        accepted = await client.post(
            root + "/" + edit_id + "/accept", json=changed, headers=headers
        )
        assert accepted.status_code == 200 and accepted.json()["needsVerification"]
        assert await editor.read_file(context) == original
    await ai.aclose()


def test_proposal_schema_rejects_unapproved_kind_and_limit():
    from pydantic import ValidationError

    from smart_reporting.report_editor.native_ai import NativeAIProposal

    with pytest.raises(ValidationError):
        NativeAIProposal(summary="x", operations=[{"kind": "replaceImage", "arguments": {}}])
    with pytest.raises(ValidationError):
        NativeAIProposal(
            summary="x", operations=[{"kind": "replaceParagraph", "arguments": {}}] * 101
        )


@pytest.mark.anyio
async def test_cancel_while_accept_preview_runs_cannot_return_adoptable_operations(
    sample, monkeypatch
):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, _ = sample
    block = model["blocks"][0]
    planner = AsyncMock(
        return_value=NativeAIProposal(
            summary="候选",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        k: v for k, v in replacement(block, "候选").items() if k != "kind"
                    },
                }
            ],
        )
    )
    ai = NativeAIService(editor, planner=planner, enabled=True)
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": block["blockId"]}],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    entered, release = asyncio.Event(), asyncio.Event()
    preview = editor.preview

    async def paused_preview(*args, **kwargs):
        entered.set()
        await release.wait()
        return await preview(*args, **kwargs)

    monkeypatch.setattr(editor, "preview", paused_preview)
    accepting = asyncio.create_task(
        ai.accept_edit(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[],
            snapshot_sha256=ready["snapshotSha256"],
        )
    )
    await entered.wait()
    await ai.cancel_edit(session, started["editId"])
    release.set()
    with pytest.raises(ReportingError) as error:
        await accepting
    assert error.value.code == "native_ai_not_ready"
    await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "output, expected",
    [
        (None, "native_ai_output_empty"),
        ({"summary": "missing operations"}, "native_ai_schema_invalid"),
    ],
)
async def test_invalid_structured_outputs_have_specific_failure_reasons(sample, output, expected):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, original = sample
    ai = NativeAIService(editor, planner=AsyncMock(return_value=output), enabled=True)
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": model["blocks"][0]["blockId"]}],
    )
    result = await ai.wait_edit_status(session, started["editId"])
    assert result["status"] == "failed"
    assert result["error"]["code"] == expected
    assert await editor.read_file(context) == original
    await ai.aclose()


@pytest.mark.anyio
async def test_agno_planner_uses_shared_structured_executor_and_two_call_budget(monkeypatch):
    from smart_reporting.report_editor import native_ai as module
    from smart_reporting.report_editor.native_ai import AgnoNativeProposalPlanner, NativeAIProposal

    agent = object()
    execute = AsyncMock(
        return_value=SimpleNamespace(
            content={
                "summary": "候选",
                "operations": [
                    {
                        "kind": "replaceParagraph",
                        "arguments": {
                            "blockId": "b",
                            "expectedObjectSha256": "a" * 64,
                            "text": "x",
                        },
                    }
                ],
            }
        )
    )
    executor = SimpleNamespace(execute=execute)
    factory = AsyncMock()
    monkeypatch.setattr(
        module,
        "ReportingStructuredOutputExecutor",
        lambda passed: executor if passed is agent else factory,
    )
    planned = await AgnoNativeProposalPlanner(agent)("prompt", session_id="s", user_id="u")
    assert isinstance(planned, NativeAIProposal)
    assert execute.await_args.kwargs["call_budget"].max_model_calls == 2
    assert execute.await_args.kwargs["session_id"] == "s"


@pytest.mark.anyio
async def test_same_snapshot_accept_is_repeatable_without_duplicate_operations(sample):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, original = sample
    target = model["blocks"][0]
    planner = AsyncMock(
        return_value=NativeAIProposal(
            summary="候选",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        k: v for k, v in replacement(target, "候选").items() if k != "kind"
                    },
                }
            ],
        )
    )
    ai = NativeAIService(editor, planner=planner, enabled=True)
    base = [replacement(target, "人工草稿")]
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=base,
        selection=[{"blockId": target["blockId"]}],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    kwargs = {
        "expected_sha256": context.source_file.sha256,
        "operations": base,
        "snapshot_sha256": ready["snapshotSha256"],
    }
    first, second = await asyncio.gather(
        ai.accept_edit(session, started["editId"], **kwargs),
        ai.accept_edit(session, started["editId"], **kwargs),
    )
    assert first["operations"] == second["operations"] == [*base, replacement(target, "候选")]
    assert await editor.read_file(context) == original
    await ai.aclose()


@pytest.mark.anyio
async def test_disabled_or_foreign_session_cannot_generate_or_read_ai_job(sample):
    from dataclasses import replace

    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, _ = sample
    planner = AsyncMock()
    ai = NativeAIService(editor, planner=planner)
    kwargs = dict(
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": model["blocks"][0]["blockId"]}],
    )
    with pytest.raises(ReportingError) as error:
        await ai.start_edit(session, **kwargs)
    assert error.value.code == "native_ai_disabled"
    planner.assert_not_awaited()
    ai.enabled = True
    with pytest.raises(ReportingError) as error:
        await ai.wait_edit_status(replace(session, context_sha256="0" * 64), "nonexistent")
    assert error.value.code == "native_permission_denied"
    await ai.aclose()


@pytest.mark.anyio
async def test_poll_returns_cancelled_when_job_is_cancelled_concurrently(sample, monkeypatch):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, _ = sample
    planner_started = asyncio.Event()

    async def planner(*args, **kwargs):
        planner_started.set()
        await asyncio.Event().wait()

    ai = NativeAIService(editor, planner=planner, enabled=True)
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": model["blocks"][0]["blockId"]}],
    )
    await planner_started.wait()
    poll_started = asyncio.Event()
    original_job = ai._job

    async def observed_job(*args):
        result = await original_job(*args)
        poll_started.set()
        return result

    monkeypatch.setattr(ai, "_job", observed_job)
    poll = asyncio.create_task(ai.wait_edit_status(session, started["editId"]))
    await poll_started.wait()
    await ai.cancel_edit(session, started["editId"])
    result = await poll
    assert result["status"] == "cancelled"
    assert "proposal" not in result
    await ai.aclose()


@pytest.mark.anyio
async def test_cancelled_poll_request_stays_cancelled_without_cancelling_job(sample, monkeypatch):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, _ = sample
    planner_started = asyncio.Event()

    async def planner(*args, **kwargs):
        planner_started.set()
        await asyncio.Event().wait()

    ai = NativeAIService(editor, planner=planner, enabled=True)
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": model["blocks"][0]["blockId"]}],
    )
    await planner_started.wait()
    poll_started = asyncio.Event()
    original_job = ai._job

    async def observed_job(*args):
        result = await original_job(*args)
        poll_started.set()
        return result

    monkeypatch.setattr(ai, "_job", observed_job)
    poll = asyncio.create_task(ai.wait_edit_status(session, started["editId"]))
    await poll_started.wait()
    poll.cancel()
    with pytest.raises(asyncio.CancelledError):
        await poll
    assert (await ai.wait_edit_status(session, started["editId"], wait_ms=0))["status"] == "running"
    await ai.aclose()


@pytest.mark.anyio
async def test_ai_cache_evicts_oldest_completed_and_keeps_running_job(sample, monkeypatch):
    from smart_reporting.report_editor.native_ai import NativeAIProposal, NativeAIService

    editor, context, session, model, _ = sample
    target = model["blocks"][0]
    # 缓存策略与引擎解析无关；真实编辑器仍执行会话及来源权限检查。
    monkeypatch.setattr(
        editor, "preview", AsyncMock(return_value={"model": model, "draftSha256": "a" * 64})
    )
    first_started = asyncio.Event()
    calls = 0

    async def planner(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_started.set()
            await asyncio.Event().wait()
        return NativeAIProposal(
            summary="候选",
            operations=[
                {
                    "kind": "replaceParagraph",
                    "arguments": {
                        k: v for k, v in replacement(target, "候选").items() if k != "kind"
                    },
                }
            ],
        )

    ai = NativeAIService(editor, planner=planner, enabled=True)
    kwargs = dict(
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[{"blockId": target["blockId"]}],
    )
    running = await ai.start_edit(session, **kwargs)
    await first_started.wait()
    completed = []
    try:
        for _ in range(128):
            job = await ai.start_edit(session, **kwargs)
            assert (await ai.wait_edit_status(session, job["editId"]))["status"] == "succeeded"
            completed.append(job["editId"])
        with pytest.raises(ReportingError) as missing:
            await ai.wait_edit_status(session, completed[0], wait_ms=0)
        assert missing.value.code == "native_ai_job_missing"
        assert (await ai.wait_edit_status(session, completed[1], wait_ms=0))[
            "status"
        ] == "succeeded"
        assert (await ai.wait_edit_status(session, running["editId"], wait_ms=0))[
            "status"
        ] == "running"
        assert len(ai._jobs) == 128
    finally:
        await ai.aclose()


@pytest.fixture
async def pdf_sample(tmp_path):
    from reportlab.pdfgen.canvas import Canvas

    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf

    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret="w" * 32))
    scope = NativeScope(database="db", companyId="company", userId="user", threadId="thread")
    key = bind_native_workspace(workspace, scope)
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(400, 300))
    canvas.drawString(30, 230, "Amount due 500")
    canvas.drawString(30, 160, "UNSELECTED SECRET")
    canvas.showPage()
    canvas.showPage()
    canvas.save()
    content = stream.getvalue()
    await workspace.awrite_bytes(key, "native/source.pdf", content)
    context = NativeEditorContext(
        documentId="pdf",
        revision=1,
        format="pdf",
        origin="report",
        scope=scope,
        sourceFile=ArtifactFile(
            path="native/source.pdf",
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            mediaType="application/pdf",
        ),
    )
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="g" * 32)
    editor = NativeEditorService(
        workspace,
        SimpleNamespace(
            get_revision=AsyncMock(return_value=SimpleNamespace(status="saved", context=context))
        ),
        grants,
        report_editor=None,
        pdf_enabled=True,
        pdf_text_enabled=True,
    )
    raw, _ = await grants.issue(context, capabilities=editor.capabilities(context))
    _, session = await grants.exchange(raw)
    model = inspect_pdf(content, include_text=True)
    return editor, context, session, model, content


def pdf_ai_selection(model, index=0):
    page = model["pages"][0]
    return {"pageId": page["pageId"], "objectId": page["textObjects"][index]["objectId"]}


def pdf_ai_plan(selection, new_text):
    return {
        "summary": "润色所选 PDF 文字",
        "operations": [{"kind": "replaceText", "arguments": {**selection, "newText": new_text}}],
    }


@pytest.mark.anyio
async def test_pdf_ai_uses_only_selected_draft_and_server_rebuilds_identity(pdf_sample):
    from pypdf import PdfReader

    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, source = pdf_sample
    selection = pdf_ai_selection(model)
    target = model["pages"][0]["textObjects"][0]
    base = [
        {
            "kind": "replaceText",
            **selection,
            "expectedTextSha256": target["expectedTextSha256"],
            "newText": "人工金额七百",
        }
    ]
    prompts = []

    async def planner(prompt, **kwargs):
        prompts.append(prompt)
        return pdf_ai_plan(selection, "调整金额七百")

    ai = NativeAIService(editor, planner=planner, enabled=True)
    started = await ai.start_edit(
        session,
        instruction="润色但不改金额",
        expected_sha256=context.source_file.sha256,
        operations=base,
        selection=[selection],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    assert ready["status"] == "succeeded", ready
    assert "人工金额七百" in prompts[0] and "UNSELECTED SECRET" not in prompts[0]
    operation = ready["proposal"]["operations"][0]
    assert operation["expectedTextSha256"] == target["expectedTextSha256"]
    assert operation["sourceSha256"] == context.source_file.sha256
    assert ready["proposal"]["skippedOperations"] == []
    accepted = await ai.accept_edit(
        session,
        started["editId"],
        expected_sha256=context.source_file.sha256,
        operations=base,
        snapshot_sha256=ready["snapshotSha256"],
    )
    assert accepted["operations"] == [operation]
    assert accepted["needsVerification"] is True
    actual = await editor.preview_file(
        context,
        expected_sha256=context.source_file.sha256,
        operations=accepted["operations"],
        expected_preview_digest=ready["proposal"]["previewDigest"],
    )
    text = PdfReader(BytesIO(actual["content"])).pages[0].extract_text()
    assert "调整金额七百" in text and "UNSELECTED SECRET" in text and "Amount due 500" not in text
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "candidate, expected",
    [
        ("foreign", "native_ai_selection_mismatch"),
        ("page-delete", "native_ai_schema_invalid"),
        ("bbox", "native_ai_schema_invalid"),
        ("forged-hash", "native_ai_schema_invalid"),
        ("too-long", "native_ai_schema_invalid"),
        ("duplicate", "native_ai_schema_invalid"),
    ],
)
async def test_pdf_ai_rejects_unselected_objects_and_model_geometry(
    pdf_sample, candidate, expected
):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, source = pdf_sample
    selection = pdf_ai_selection(model)
    proposal = pdf_ai_plan(
        pdf_ai_selection(model, 1) if candidate == "foreign" else selection, "候选文字"
    )
    if candidate == "page-delete":
        proposal["operations"][0] = {"kind": "deleteParagraph", "arguments": selection}
    if candidate == "bbox":
        proposal["operations"][0]["arguments"]["rect"] = [0, 0, 300, 300]
    if candidate == "forged-hash":
        proposal["operations"][0]["arguments"]["expectedTextSha256"] = "0" * 64
    if candidate == "too-long":
        proposal["operations"][0]["arguments"]["newText"] = "X" * 4001
    if candidate == "duplicate":
        proposal["operations"] *= 2
    ai = NativeAIService(editor, planner=AsyncMock(return_value=proposal), enabled=True)
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[selection],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    assert ready["status"] == "failed" and ready["error"]["code"] == expected, ready
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_ai_skipped_candidate_keeps_original_and_returns_specific_warnings(pdf_sample):
    from pypdf import PdfReader

    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, source = pdf_sample
    selection = pdf_ai_selection(model)
    ai = NativeAIService(
        editor, planner=AsyncMock(return_value=pdf_ai_plan(selection, "X" * 1000)), enabled=True
    )
    started = await ai.start_edit(
        session,
        instruction="改写",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[selection],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    assert ready["status"] == "succeeded", ready
    assert ready["proposal"]["skippedOperations"][0]["operationIndex"] == 0
    assert ready["proposal"]["issues"][0]["code"] == "native_ai_pdf_text_skipped"
    accepted = await ai.accept_edit(
        session,
        started["editId"],
        expected_sha256=context.source_file.sha256,
        operations=[],
        snapshot_sha256=ready["snapshotSha256"],
    )
    assert accepted["proposal"]["skippedOperations"] == ready["proposal"]["skippedOperations"]
    actual = await editor.preview_file(
        context,
        expected_sha256=context.source_file.sha256,
        operations=accepted["operations"],
        expected_preview_digest=ready["proposal"]["previewDigest"],
    )
    assert actual["content"] == source
    assert "Amount due 500" in PdfReader(BytesIO(actual["content"])).pages[0].extract_text()
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_ai_rejects_changed_draft_and_expired_job_before_accept(pdf_sample):
    from datetime import UTC, datetime, timedelta

    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, _ = pdf_sample
    selection = pdf_ai_selection(model)
    ai = NativeAIService(
        editor, planner=AsyncMock(return_value=pdf_ai_plan(selection, "调整金额七百")), enabled=True
    )
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[selection],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    with pytest.raises(ReportingError) as changed:
        await ai.accept_edit(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[{"kind": "rotatePage", "pageId": selection["pageId"], "delta": 90}],
            snapshot_sha256=ready["snapshotSha256"],
        )
    assert changed.value.code == "native_ai_snapshot_changed"
    ai._jobs[started["editId"]].created_at = datetime.now(UTC) - timedelta(hours=2)
    with pytest.raises(ReportingError) as expired:
        await ai.accept_edit(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[],
            snapshot_sha256=ready["snapshotSha256"],
        )
    assert expired.value.code == "native_ai_job_missing"
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_ai_cancel_during_accept_preserves_original(pdf_sample, monkeypatch):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, source = pdf_sample
    selection = pdf_ai_selection(model)
    ai = NativeAIService(
        editor, planner=AsyncMock(return_value=pdf_ai_plan(selection, "调整金额七百")), enabled=True
    )
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[selection],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    entered, release = asyncio.Event(), asyncio.Event()
    original_preview = editor.preview

    async def paused_preview(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original_preview(*args, **kwargs)

    monkeypatch.setattr(editor, "preview", paused_preview)
    accepting = asyncio.create_task(
        ai.accept_edit(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[],
            snapshot_sha256=ready["snapshotSha256"],
        )
    )
    await entered.wait()
    await ai.cancel_edit(session, started["editId"])
    release.set()
    with pytest.raises(ReportingError) as cancelled:
        await accepting
    assert cancelled.value.code == "native_ai_not_ready"
    assert await editor.read_file(context) == source
    await ai.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("disabled", ["ai", "pdf-text"])
async def test_pdf_ai_requires_both_feature_flags(pdf_sample, disabled):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, _ = pdf_sample
    editor.pdf_text_enabled = disabled != "pdf-text"
    planner = AsyncMock()
    ai = NativeAIService(editor, planner=planner, enabled=disabled != "ai")
    with pytest.raises(ReportingError) as error:
        await ai.start_edit(
            session,
            instruction="润色",
            expected_sha256=context.source_file.sha256,
            operations=[],
            selection=[pdf_ai_selection(model)],
        )
    assert error.value.code == (
        "native_ai_disabled" if disabled == "ai" else "native_ai_pdf_text_disabled"
    )
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_ai_deleted_or_bbox_selection_is_rejected_before_planning(pdf_sample):
    from smart_reporting.report_editor.native_ai import NativeAIService

    editor, context, session, model, _ = pdf_sample
    selection = pdf_ai_selection(model)
    planner = AsyncMock()
    ai = NativeAIService(editor, planner=planner, enabled=True)
    for selected, operations in [
        ([{**selection, "rect": "0,0,300,300"}], []),
        ([selection], [{"kind": "deletePage", "pageId": selection["pageId"]}]),
    ]:
        with pytest.raises(ReportingError) as error:
            await ai.start_edit(
                session,
                instruction="润色",
                expected_sha256=context.source_file.sha256,
                operations=operations,
                selection=selected,
            )
        assert error.value.code == "native_ai_selection_invalid"
    planner.assert_not_awaited()
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_ai_accept_rechecks_actual_font_runtime_digest(pdf_sample, tmp_path, monkeypatch):
    from smart_reporting.report_editor.native_ai import NativeAIService
    from smart_reporting.reporting.delivery.office_engine import engine_dir

    editor, context, session, model, _ = pdf_sample
    selection = pdf_ai_selection(model)
    ai = NativeAIService(
        editor, planner=AsyncMock(return_value=pdf_ai_plan(selection, "调整金额七百")), enabled=True
    )
    started = await ai.start_edit(
        session,
        instruction="润色",
        expected_sha256=context.source_file.sha256,
        operations=[],
        selection=[selection],
    )
    ready = await ai.wait_edit_status(session, started["editId"])
    modules = engine_dir("pdf") / "node_modules"
    (tmp_path / "pdfium.wasm").write_bytes(
        (modules / "@embedpdf/pdfium/dist/pdfium.wasm").read_bytes()
    )
    (tmp_path / "hb-subset.wasm").write_bytes(
        (modules / "harfbuzzjs/hb-subset.wasm").read_bytes() + b"\x00\x01\x00"
    )
    monkeypatch.setenv("AGENT_REPORTING_PDF_WASM_DIR", str(tmp_path))
    with pytest.raises(ReportingError) as error:
        await ai.accept_edit(
            session,
            started["editId"],
            expected_sha256=context.source_file.sha256,
            operations=[],
            snapshot_sha256=ready["snapshotSha256"],
        )
    assert error.value.code == "native_ai_preview_changed"
    await ai.aclose()


@pytest.mark.anyio
async def test_pdf_ai_routes_keep_cookie_csrf_and_return_preview_contract(pdf_sample):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_ai import NativeAIService
    from smart_reporting.report_editor.native_ai_api import create_native_ai_router
    from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE

    editor, context, session, model, source = pdf_sample
    selection = pdf_ai_selection(model)
    ai = NativeAIService(
        editor, planner=AsyncMock(return_value=pdf_ai_plan(selection, "调整金额七百")), enabled=True
    )
    app = FastAPI()
    app.include_router(
        create_native_ai_router(editor.grants, editor=editor, ai=ai, allowed_origin="http://test")
    )
    raw, _ = await editor.grants.issue(context, capabilities=editor.capabilities(context))
    token, _ = await editor.grants.exchange(raw)
    base = "/reports/v1/native/pdf/1/api/ai"
    payload = {
        "instruction": "润色",
        "expectedSha256": context.source_file.sha256,
        "operations": [],
        "selection": [selection],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path="/reports/v1/native/pdf/1")
        assert (await client.post(base + "/start", json=payload)).status_code == 403
        headers = {"Origin": "http://test", "X-CSRF-Token": editor.grants.csrf_token(token)}
        started = await client.post(base + "/start", json=payload, headers=headers)
        assert started.status_code == 200, started.text
        edit_id = started.json()["editId"]
        ready = await client.get(base + "/" + edit_id)
        assert ready.json()["status"] == "succeeded", ready.text
        assert ready.json()["proposal"]["previewDigest"]
        accept = {
            "expectedSha256": context.source_file.sha256,
            "operations": [],
            "snapshotSha256": ready.json()["snapshotSha256"],
        }
        accepted = await client.post(base + "/" + edit_id + "/accept", json=accept, headers=headers)
        assert accepted.status_code == 200 and accepted.json()["needsVerification"]
        assert accepted.json()["operations"][0]["expectedTextSha256"]
        assert await editor.read_file(context) == source
    await ai.aclose()
