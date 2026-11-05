from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.ai_tasks import AITaskService, AITaskStartRequest
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.report_editor.slides_api import (
    SLIDES_CSRF_COOKIE,
    create_report_slides_editor_router,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor_ai import _context
from smart_reporting.reporting.tests.test_slides_editor_api import (
    SlidesService,
)
from smart_reporting.reporting.tests.test_slides_editor_api import (
    _context as slides_context,
)


class Rewrite:
    def __init__(self):
        self.selections = []

    async def stream_rewrite(self, _context, *, selection, action, instruction):
        self.selections.append(selection)
        assert action == "custom" and instruction == "润色"
        yield selection.replace("旧", "新")


@pytest.mark.anyio
async def test_document_task_preserves_markers_is_idempotent_and_accepts_without_saving():
    rewrite = Rewrite()
    service = AITaskService(**{"document-selection": rewrite})
    context = _context()
    request = AITaskStartRequest(
        kind="document-selection",
        instruction="润色",
        idempotencyKey="same",
        snapshot={"selection": "旧正文[[citation:c1]]。"},
    )
    first, repeated = await asyncio.gather(
        service.start(None, context, request), service.start(None, context, request)
    )
    assert first["taskId"] == repeated["taskId"]
    task_id = first["taskId"]
    await service.tasks[task_id].worker
    result = await service.status(None, context, task_id)
    assert result["state"] == "ready"
    assert result["proposal"]["markdown"] == "新正文[[citation:c1]]。"
    assert rewrite.selections == ["旧正文"]
    with pytest.raises(ReportingError, match="内容已变化"):
        await service.transition(None, context, task_id, "accept", {"selection": "changed"})
    for _ in range(2):
        assert (await service.transition(None, context, task_id, "accept", request.snapshot))[
            "state"
        ] == "accepted"
    with pytest.raises(ReportingError, match="内容已变化"):
        await service.transition(None, context, task_id, "accept", {})
    with pytest.raises(ReportingError, match="已采纳"):
        await service.transition(None, context, task_id, "reject", {})
    await service.close()


@pytest.mark.anyio
async def test_document_cancel_expiry_scope_and_restart():
    blocked = asyncio.Event()

    class Slow:
        async def stream_rewrite(self, *_args, **_kwargs):
            await blocked.wait()
            yield "late"

    service = AITaskService(**{"document-selection": Slow()})
    context = _context()
    request = AITaskStartRequest(
        kind="document-selection", instruction="润色", snapshot={"selection": "原文"}
    )
    task_id = (await service.start(None, context, request))["taskId"]
    with pytest.raises(ReportingError):
        await service.status(None, context.model_copy(update={"revision": 99}), task_id)
    assert (await service.transition(None, context, task_id, "cancel", {}))["state"] == "cancelled"
    blocked.set()
    assert (await service.status(None, context, task_id))["state"] == "cancelled"
    service.tasks[task_id].created -= 3601
    with pytest.raises(ReportingError, match="已失效"):
        await service.status(None, context, task_id)
    with pytest.raises(ReportingError, match="已失效"):
        await AITaskService().status(None, context, task_id)
    await service.close()


@pytest.mark.anyio
async def test_domain_status_cannot_resurrect_cancelled_task():
    started, release = asyncio.Event(), asyncio.Event()

    async def status(*_args, **_kwargs):
        started.set()
        await release.wait()
        return {"status": "succeeded", "proposal": {"summary": "late"}}

    ai = SimpleNamespace(
        start_edit=AsyncMock(return_value={"editId": "native"}),
        wait_edit_status=status,
        cancel_edit=AsyncMock(),
    )
    service = AITaskService(**{"slides-edit": ai, "slides_snapshot": AsyncMock(return_value={})})
    context = slides_context()
    task_id = (
        await service.start(
            None, context, AITaskStartRequest(kind="slides-edit", instruction="改写")
        )
    )["taskId"]
    pending = asyncio.create_task(service.status(None, context, task_id))
    await started.wait()
    # Cancellation publishes a terminal state while an earlier read is still in flight.
    service.tasks[task_id].state = "cancelled"
    release.set()
    assert (await pending)["state"] == "cancelled"


@pytest.mark.anyio
async def test_workbook_adapter_recomputes_snapshot_and_keeps_native_identity():
    context = _context().model_copy(update={"delivery_format": "xlsx", "xlsx_sha256": "a" * 64})
    ai = SimpleNamespace(
        start_edit=AsyncMock(return_value={"editId": "native-workbook"}),
        wait_edit_status=AsyncMock(
            return_value={
                "editId": "native-workbook",
                "status": "succeeded",
                "proposal": {"operations": []},
            }
        ),
        mark_accepted=AsyncMock(),
    )
    workbooks = SimpleNamespace(
        snapshot_for_session=AsyncMock(return_value={"snapshotSha256": "server-hash"})
    )
    service = AITaskService(**{"workbook-edit": ai, "workbooks": workbooks})
    snapshot = {"expectedSha256": "a" * 64, "operations": [{"kind": "applyCellEdits", "edits": []}]}
    started = await service.start(
        None,
        context,
        AITaskStartRequest(kind="workbook-edit", instruction="改写", snapshot=snapshot),
    )
    assert started["nativeId"] == "native-workbook" and started["taskId"] != started["nativeId"]
    await service.transition(None, context, started["taskId"], "accept", snapshot)
    workbooks.snapshot_for_session.assert_awaited_once_with(None, snapshot["operations"])
    ai.mark_accepted.assert_awaited_once_with(
        None, "native-workbook", snapshot_sha256="server-hash"
    )


@pytest.mark.anyio
async def test_task_routes_reuse_office_csrf_scope_and_snapshot_adapter(tmp_path):
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(slides_context(), capabilities={"pptx_editor": True})
    slides = SlidesService()
    slides.draft_deck_for_session = AsyncMock(return_value={"slides": [{"text": "未保存内容"}]})
    ai = SimpleNamespace(
        start_edit=AsyncMock(return_value={"editId": "native"}),
        wait_edit_status=AsyncMock(
            return_value={"status": "succeeded", "proposal": {"summary": "ok"}}
        ),
        mark_accepted=AsyncMock(),
        cancel_edit=AsyncMock(),
    )
    app = FastAPI()
    app.include_router(
        create_report_slides_editor_router(
            grants, slides=slides, slides_ai=ai, static_dir=tmp_path, cookie_secure=False
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://report.test"
    ) as client:
        opened = await client.get("/reports/v1/slides/open/" + raw)
        base = opened.headers["location"]
        snapshot = {
            "expectedSha256": "a" * 64,
            "edits": [{"slideIndex": 0, "elementId": "title", "text": "未保存内容"}],
        }
        payload = {
            "kind": "slides-edit",
            "instruction": "润色",
            "snapshot": snapshot,
            "idempotencyKey": "same",
        }
        assert (await client.post(base + "/api/ai/tasks", json=payload)).status_code == 403
        headers = {"X-CSRF-Token": client.cookies.get(SLIDES_CSRF_COOKIE)}
        response = await client.post(base + "/api/ai/tasks", json=payload, headers=headers)
        assert response.status_code == 202
        task_id = response.json()["taskId"]
        assert (await client.get(base + "/api/ai/tasks/" + task_id)).json()["state"] == "ready"
        assert (
            await client.post(
                base + "/api/ai/tasks/" + task_id + "/accept", json={"snapshot": snapshot}
            )
        ).status_code == 403
        assert (
            await client.post(
                base + "/api/ai/tasks/" + task_id + "/accept",
                json={"snapshot": snapshot},
                headers=headers,
            )
        ).status_code == 200
        assert (
            await client.get(base.replace("slides-1", "other") + "/api/ai/tasks/" + task_id)
        ).status_code != 200
        assert (await client.get(base + "/api/ai/tasks/unknown")).status_code == 404
    assert slides.draft_deck_for_session.await_args.args[1] == snapshot
    assert ai.start_edit.await_args.kwargs["deck"]["slides"][0]["text"] == "未保存内容"


@pytest.mark.anyio
async def test_document_routes_keep_origin_csrf_and_restricted_session_checks():
    from smart_reporting.report_editor.api import create_report_editor_router
    from smart_reporting.reporting.tests.test_report_editor import _context as document_context

    context = document_context()
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    editor = SimpleNamespace(
        context_for_session=AsyncMock(return_value=context),
        read_document=AsyncMock(
            return_value=SimpleNamespace(
                path=context.markdown_path, markdown="正文", sha256="a" * 64
            )
        ),
    )
    app = FastAPI()
    app.include_router(
        create_report_editor_router(grants, editor=editor, ai=Rewrite(), cookie_secure=False)
    )
    payload = {
        "kind": "document-selection",
        "instruction": "润色",
        "snapshot": {"selection": "旧正文"},
    }
    for capabilities in [None, {"download_original": True}]:
        raw, _ = await grants.issue(
            context, **({"capabilities": capabilities} if capabilities else {})
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://reports.test"
        ) as client:
            await client.get("/reports/v1/editor/open/" + raw)
            base = f"/reports/v1/editor/{context.report_id}/{context.revision}"
            loaded = await client.get(base + "/api/document")
            csrf = loaded.json()["csrfToken"]
            assert (
                await client.post(
                    base + "/api/ai/tasks", json=payload, headers={"X-CSRF-Token": csrf}
                )
            ).status_code == 403
            response = await client.post(
                base + "/api/ai/tasks",
                json=payload,
                headers={"Origin": "http://reports.test", "X-CSRF-Token": csrf},
            )
            assert response.status_code == (403 if capabilities else 202)


@pytest.mark.anyio
async def test_slides_draft_snapshot_uses_unsaved_content_without_revision_writes(monkeypatch):
    from smart_reporting.report_editor.slides import ReportSlidesEditorService
    from smart_reporting.reporting.delivery.office_engine import run_office_engine
    from smart_reporting.reporting.tests.test_slides_engine_bridge import FIXTURE

    service = ReportSlidesEditorService.__new__(ReportSlidesEditorService)
    context = slides_context()
    content = FIXTURE.read_bytes()
    monkeypatch.setattr(service, "context_for_session", AsyncMock(return_value=context))
    monkeypatch.setattr(service, "_read_verified_pptx", AsyncMock(return_value=content))
    original = await run_office_engine(service._run_engine, content, "inspect")
    slide, element = next(
        (slide, element)
        for slide in original["slides"]
        for element in slide["elements"]
        if element["editable"] and element["text"].strip()
    )
    order = list(reversed(range(len(original["slides"]))))
    snapshot = {
        "expectedSha256": context.pptx_sha256,
        "order": order,
        "edits": [
            {
                "slideIndex": slide["slideIndex"],
                "elementId": element["id"],
                "text": "未保存的新标题",
            }
        ],
        "backgrounds": [{"slideIndex": 0, "color": "#123456"}],
        "textBoxes": [
            {
                "slideIndex": 0,
                "text": "草稿新增文本",
                "geometry": {"x": 5, "y": 5, "width": 100, "height": 40},
                "fontSize": 18,
                "fontFamily": "Arial",
                "color": "#000000",
            }
        ],
    }
    result = await service.draft_deck_for_session(None, snapshot)
    assert [item["slideIndex"] for item in result["slides"]] == order
    changed = next(item for item in result["slides"] if item["slideIndex"] == slide["slideIndex"])
    assert (
        next(item for item in changed["elements"] if item["id"] == element["id"])["text"].strip()
        == "未保存的新标题"
    )
    added = next(
        item
        for slide in result["slides"]
        for item in slide["elements"]
        if "草稿新增文本" in item["text"]
    )
    assert added["editable"] is False
    assert result["sha256"] == context.pptx_sha256
    # The service has no workspace/repository: snapshot generation cannot persist a revision.
    assert not hasattr(service, "workspace")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,resource_key,resource,snapshot",
    [
        (
            "chart-edit",
            "chartId",
            "chart_001",
            {
                "baseImagePath": "reports/chart.png",
                "previousEditId": "cedit-12345678",
                "expectedSha256": "b" * 64,
            },
        ),
        (
            "table-edit",
            "tableId",
            "tbl-1",
            {
                "baseBody": "| A |\n|---|\n| 1 |",
                "previousEditId": "tedit-12345678",
                "expectedSha256": "b" * 64,
            },
        ),
    ],
)
async def test_asset_adapter_retains_native_identity_and_domain_snapshot(
    kind, resource_key, resource, snapshot
):
    native = {
        "editId": "native-12345678",
        "status": "succeeded",
        "warnings": ["保留告警"],
        "imagePath": "generated/chart.png",
    }
    domain = SimpleNamespace(
        start_edit=AsyncMock(return_value={"editId": native["editId"]}),
        edit_status=lambda *_args: native,
        cancel_edit=lambda *_args: {"status": "cancelled"},
    )
    service = AITaskService(**{kind: domain})
    request = AITaskStartRequest(
        kind=kind, instruction="调整", target={resource_key: resource}, snapshot=snapshot
    )
    result = await service.start(None, _context(), request)
    task_id = result["taskId"]
    status = await service.status(None, _context(), task_id)
    assert status["state"] == "ready"
    assert status["proposal"]["editId"] == native["editId"]
    assert status["native"]["warnings"] == ["保留告警"]
    assert domain.start_edit.await_args.args[-1].previous_edit_id == snapshot["previousEditId"]
    rejected = await service.transition(None, _context(), task_id, "reject", {})
    assert rejected["state"] == "cancelled" and rejected["reason"] == "rejected"


@pytest.mark.anyio
async def test_slides_chart_adapter_retains_candidate_identity():
    domain = SimpleNamespace(
        start_edit=AsyncMock(return_value={"candidateId": "cedit-native"}),
        edit_status=AsyncMock(
            return_value={
                "candidateId": "cedit-native",
                "status": "succeeded",
                "previewDataUrl": "data:image/png;base64,AA==",
            }
        ),
        cancel_edit=AsyncMock(),
    )
    service = AITaskService(**{"chart-edit": domain})
    context = slides_context()
    result = await service.start(
        None,
        context,
        AITaskStartRequest(
            kind="chart-edit",
            instruction="调整颜色",
            target={"slideIndex": 0, "elementId": "picture-1"},
        ),
    )
    status = await service.status(None, context, result["taskId"])
    assert status["proposal"]["candidateId"] == "cedit-native"
    assert (await service.transition(None, context, result["taskId"], "accept", {}))[
        "state"
    ] == "accepted"
    domain.start_edit.assert_awaited_once_with(None, 0, "picture-1", "调整颜色")


@pytest.mark.anyio
async def test_finished_unpolled_native_jobs_do_not_exhaust_task_capacity():
    domain = SimpleNamespace(
        start_edit=AsyncMock(return_value={"editId": "native"}),
        wait_edit_status=AsyncMock(
            return_value={"status": "succeeded", "proposal": {"summary": "done"}}
        ),
    )
    service = AITaskService(
        **{"slides-edit": domain, "slides_snapshot": AsyncMock(return_value={})}
    )
    for _ in range(9):
        await service.start(
            None, slides_context(), AITaskStartRequest(kind="slides-edit", instruction="调整")
        )
    assert len(service.tasks) == 9
    assert sum(task.state == "running" for task in service.tasks.values()) == 1
