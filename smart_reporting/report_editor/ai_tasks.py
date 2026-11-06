"""编辑器会话内的统一 AI 任务；领域服务继续拥有产物及溯源身份。"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from loguru import logger
from pydantic import Field, ValidationError

from ..reporting.contract import StrictModel
from ..reporting.models import ReportingError
from .ai import _PROTOCOL_MARKER, MAX_AI_SELECTION_CHARS, _contains_protocol_marker
from .capabilities import EditorCapabilities
from .chart_ai import ChartAIEditRequest, ChartStandardEditRequest, ChartTemplateApplyRequest
from .table_ai import TableAIEditRequest, TableTemplateApplyRequest

AITaskKind = Literal[
    "document-selection", "slides-edit", "workbook-edit", "chart-edit", "table-edit"
]


class AITaskStartRequest(StrictModel):
    kind: AITaskKind
    instruction: str = Field(min_length=1, max_length=2000)
    idempotencyKey: str | None = Field(default=None, min_length=1, max_length=128)
    target: dict[str, Any] = Field(default_factory=dict)
    snapshot: dict[str, Any] = Field(default_factory=dict)


class DocumentSnapshot(StrictModel):
    selection: str = Field(min_length=1, max_length=MAX_AI_SELECTION_CHARS)


class WorkbookSnapshot(StrictModel):
    expectedSha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=1000)


class SlideChartTarget(StrictModel):
    slideIndex: int = Field(ge=0, strict=True)
    elementId: str = Field(min_length=1, max_length=200)


class AITaskAcceptRequest(StrictModel):
    snapshot: dict[str, Any] = Field(default_factory=dict)


@dataclass
class _Task:
    task_id: str
    request: AITaskStartRequest
    owner: str
    native_id: str = ""
    slides_chart: bool = False
    created: float = field(default_factory=time.monotonic)
    state: str = "running"
    result: dict[str, Any] = field(default_factory=dict)
    worker: asyncio.Task[None] | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


class AITaskService:
    """协议适配层；accept 仅确认候选，绝不保存正文或发布产物。"""

    def __init__(self, **services: Any) -> None:
        self.services = services
        self.tasks: dict[str, _Task] = {}
        self.start_lock = asyncio.Lock()

    def _service(self, kind: str) -> Any:
        service = self.services.get(kind)
        if service is None:
            raise ReportingError("report_editor_ai_unavailable", "该类型 AI 编辑暂不可用。")
        return service

    def _get(self, context: Any, task_id: str) -> _Task:
        task = self.tasks.get(task_id)
        if (
            task is None
            or task.owner != context.digest()
            or time.monotonic() - task.created >= 3600
        ):
            raise ReportingError("report_editor_ai_task_missing", "AI 任务不存在或已失效。")
        return task

    async def close(self) -> None:
        workers = [
            task.worker for task in self.tasks.values() if task.worker and not task.worker.done()
        ]
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        self.tasks.clear()

    async def start(
        self, session: Any, context: Any, request: AITaskStartRequest
    ) -> dict[str, Any]:
        async with self.start_lock:
            if request.idempotencyKey:
                for prior in self.tasks.values():
                    if (
                        prior.owner == context.digest()
                        and prior.request.idempotencyKey == request.idempotencyKey
                        and time.monotonic() - prior.created < 3600
                    ):
                        if prior.request != request:
                            raise ReportingError(
                                "report_editor_ai_idempotency_conflict", "请求标识已用于其他修改。"
                            )
                        return self._serialize(prior)
            return await self._start(session, context, request)

    async def _start(
        self, session: Any, context: Any, request: AITaskStartRequest
    ) -> dict[str, Any]:
        if not request.instruction.strip():
            raise ReportingError("report_editor_ai_instruction_invalid", "请输入修改要求。")
        if len(json.dumps(request.snapshot, ensure_ascii=False)) > 500_000:
            raise ReportingError(
                "report_editor_ai_snapshot_too_large", "当前草稿过大，请缩小修改范围。"
            )
        service = self._service(request.kind)
        now = time.monotonic()
        self.tasks = {
            key: item
            for key, item in self.tasks.items()
            if now - item.created < 3600 or (item.worker is not None and not item.worker.done())
        }
        # A tab may stop polling after a native job finishes. Refresh those jobs
        # before counting capacity, otherwise completed work can exhaust the limit.
        for item in tuple(self.tasks.values()):
            if (
                item.owner == context.digest()
                and item.native_id
                and item.state in {"running", "queued"}
            ):
                try:
                    await self.status(session, context, item.task_id)
                except ReportingError as error:
                    item.state = "failed"
                    item.result = {"issues": [{"code": error.code, "message": error.message}]}
        if (
            sum(
                item.owner == context.digest() and item.state in {"running", "queued"}
                for item in self.tasks.values()
            )
            >= 8
        ):
            raise ReportingError("report_editor_ai_busy", "当前任务过多，请等待已有任务完成。")
        task = _Task(uuid4().hex, request, context.digest())
        if request.kind == "document-selection":
            selection = DocumentSnapshot.model_validate(request.snapshot).selection
            if (
                not isinstance(selection, str)
                or not selection.strip()
                or len(selection) > MAX_AI_SELECTION_CHARS
            ):
                raise ReportingError("report_editor_ai_selection_invalid", "请先选择适量正文。")
            if any(
                match.group().startswith(("[[section:", "[[table:", "[[/table:"))
                for match in _PROTOCOL_MARKER.finditer(selection)
            ):
                raise ReportingError(
                    "report_editor_ai_protocol_marker", "请在同一正文段落内选择内容。"
                )
            task.worker = asyncio.create_task(self._rewrite(task, service, context, selection))
        elif request.kind == "slides-edit":
            if set(request.snapshot) - {
                "expectedSha256",
                "edits",
                "order",
                "theme",
                "imageEdits",
                "chartEdits",
                "transitions",
                "animations",
                "slideLayouts",
                "backgrounds",
                "textBoxes",
                "deletions",
            }:
                raise ReportingError(
                    "report_editor_ai_snapshot_invalid", "幻灯片草稿包含未知操作。"
                )
            deck = await self.services["slides_snapshot"](session, request.snapshot)
            started = await service.start_edit(session, request.instruction, deck=deck)
            task.native_id = started["editId"]
        elif request.kind == "workbook-edit":
            snapshot = WorkbookSnapshot.model_validate(request.snapshot)
            if snapshot.expectedSha256 != context.xlsx_sha256:
                raise ReportingError(
                    "report_editor_ai_snapshot_changed", "工作簿文件身份已变化，请重新载入。"
                )
            started = await service.start_edit(
                session, request.instruction, request.snapshot.get("operations", [])
            )
            task.native_id = started["editId"]
        elif request.kind == "chart-edit" and context.delivery_format == "pptx":
            target = SlideChartTarget.model_validate(request.target)
            started = await service.start_edit(
                session, target.slideIndex, target.elementId, request.instruction
            )
            task.native_id = started["candidateId"]
            task.slides_chart = True
        else:
            resource = request.target.get("chartId" if request.kind == "chart-edit" else "tableId")
            if not isinstance(resource, str) or not resource:
                raise ReportingError(
                    "report_editor_ai_target_invalid", "请选择要编辑的图表或表格。"
                )
            payload = {**request.snapshot, "instruction": request.instruction}
            mode = request.target.get("mode")
            if (
                mode not in {None, "template", "standard"}
                or mode == "standard"
                and request.kind != "chart-edit"
            ):
                raise ReportingError("report_editor_ai_target_invalid", "不支持的候选生成方式。")
            if mode == "template":
                if request.target.get("instructionProvided") is False:
                    payload.pop("instruction")
                payload["templateId"] = request.target.get("templateId")
                model = (
                    ChartTemplateApplyRequest
                    if request.kind == "chart-edit"
                    else TableTemplateApplyRequest
                )
                started = await service.start_template(
                    context, session, resource, model.model_validate(payload)
                )
            elif mode == "standard" and request.kind == "chart-edit":
                started = await service.start_standard_edit(
                    context,
                    session,
                    resource,
                    ChartStandardEditRequest.model_validate(request.snapshot),
                )
            else:
                model = ChartAIEditRequest if request.kind == "chart-edit" else TableAIEditRequest
                started = await service.start_edit(
                    context, session, resource, model.model_validate(payload)
                )
            task.native_id = started["editId"]
        self.tasks[task.task_id] = task
        return self._serialize(task)

    async def _rewrite(self, task: _Task, service: Any, context: Any, selection: str) -> None:
        try:
            async with asyncio.timeout(180):
                await self._rewrite_content(task, service, context, selection)
        except asyncio.CancelledError:
            task.state = "cancelled"
            raise
        except Exception as error:
            logger.warning(
                "report_editor_ai_task_failed task_id={} error_type={}",
                task.task_id,
                type(error).__name__,
            )
            task.state = "failed"
            task.result = {
                "issues": [
                    {"code": "report_editor_ai_failed", "message": "候选生成失败，原稿已保留。"}
                ]
            }

    async def _rewrite_content(
        self, task: _Task, service: Any, context: Any, selection: str
    ) -> None:
        pieces: list[str] = []
        cursor = 0
        for marker in [*_PROTOCOL_MARKER.finditer(selection), None]:
            end = marker.start() if marker else len(selection)
            text = selection[cursor:end]
            if any(char.isalnum() for char in text):
                chunks = []
                async for chunk in service.stream_rewrite(
                    context, selection=text, action="custom", instruction=task.request.instruction
                ):
                    chunks.append(chunk)
                    if sum(map(len, chunks)) > MAX_AI_SELECTION_CHARS * 4:
                        raise ValueError("rewrite_too_large")
                rewritten = "".join(chunks)
                if not rewritten.strip() or _contains_protocol_marker(rewritten):
                    raise ValueError("invalid_rewrite")
                pieces.append(rewritten)
            else:
                pieces.append(text)
            if marker:
                pieces.append(marker.group())
                cursor = marker.end()
        task.result = {"proposal": {"markdown": "".join(pieces)}, "summary": "正文改写候选"}
        task.state = "ready"

    async def status(
        self, session: Any, context: Any, task_id: str, *, wait_ms: int = 0
    ) -> dict[str, Any]:
        task = self._get(context, task_id)
        if task.request.kind != "document-selection" and task.state not in {
            "accepted",
            "cancelled",
            "failed",
        }:
            service = self._service(task.request.kind)
            if task.request.kind in {"slides-edit", "workbook-edit"}:
                status = await service.wait_edit_status(session, task.native_id, wait_ms=wait_ms)
            elif task.slides_chart:
                status = await service.edit_status(session, task.native_id, wait_ms=wait_ms)
            else:
                resource = task.request.target[
                    "chartId" if task.request.kind == "chart-edit" else "tableId"
                ]
                if wait_ms and task.request.kind == "chart-edit":
                    status = await service.wait_edit_status(
                        context, resource, task.native_id, wait_ms=wait_ms
                    )
                else:
                    status = service.edit_status(context, resource, task.native_id)
            if task.state in {"accepted", "cancelled", "failed"}:
                return self._serialize(task)
            task.state = {
                "queued": "queued",
                "pending": "queued",
                "succeeded": "ready",
                "running": "running",
                "cancelled": "cancelled",
                "failed": "failed",
            }.get(status["status"], "failed")
            task.result = {
                "proposal": status.get("proposal", status),
                "summary": status.get("proposal", {}).get("summary"),
                "issues": status.get("issues", []),
                "native": status,
            }
            if status.get("error"):
                task.result["issues"] = [status["error"]]
        return self._serialize(task)

    async def transition(
        self, session: Any, context: Any, task_id: str, action: str, snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        task = self._get(context, task_id)
        async with task.lock:
            await self.status(session, context, task_id)
            if action == "accept":
                if snapshot != task.request.snapshot:
                    raise ReportingError(
                        "report_editor_ai_snapshot_changed", "内容已变化，请重新生成候选。"
                    )
                if task.state == "accepted":
                    return self._serialize(task)
                if task.state != "ready":
                    raise ReportingError("report_editor_ai_not_ready", "候选尚不可采纳。")
                service = self._service(task.request.kind)
                if task.request.kind == "slides-edit":
                    await service.mark_accepted(session, task.native_id)
                elif task.request.kind == "workbook-edit":
                    current = await self.services["workbooks"].snapshot_for_session(
                        session, snapshot.get("operations", [])
                    )
                    await service.mark_accepted(
                        session, task.native_id, snapshot_sha256=current["snapshotSha256"]
                    )
                task.state = "accepted"
            else:
                if task.state == "accepted":
                    raise ReportingError(
                        "report_editor_ai_already_accepted", "候选已采纳，请在草稿中撤销。"
                    )
                if task.state == "cancelled":
                    return self._serialize(task)
                if task.worker:
                    task.worker.cancel()
                    await asyncio.gather(task.worker, return_exceptions=True)
                else:
                    service = self._service(task.request.kind)
                    if task.request.kind in {"slides-edit", "workbook-edit"}:
                        await service.cancel_edit(session, task.native_id)
                    elif task.slides_chart:
                        await service.cancel_edit(session, task.native_id)
                    else:
                        resource = task.request.target[
                            "chartId" if task.request.kind == "chart-edit" else "tableId"
                        ]
                        await _await(service.cancel_edit(context, resource, task.native_id))
                task.state = "cancelled"
                task.result = {"reason": "rejected" if action == "reject" else "cancelled"}
            return self._serialize(task)

    @staticmethod
    def _serialize(task: _Task) -> dict[str, Any]:
        return {
            "taskId": task.task_id,
            "kind": task.request.kind,
            "state": task.state,
            "nativeId": task.native_id or None,
            **task.result,
        }


def register_ai_task_routes(
    router: APIRouter, *, prefix: str, authorize: Any, service: AITaskService
) -> None:
    router.add_event_handler("shutdown", service.close)

    async def access(request: Request, report_id: str, revision: int, write: bool) -> Any:
        session, context = await authorize(request, report_id, revision, write)
        capabilities = getattr(session, "capabilities", None)
        if context.delivery_format == "document" and EditorCapabilities.of(capabilities).restricted:
            raise HTTPException(403, detail={"code": "report_editor_permission_denied"})
        return session, context

    def error_response(error: Exception) -> HTTPException:
        if isinstance(error, ValidationError):
            return HTTPException(
                422,
                detail={"code": "report_editor_ai_payload_invalid", "message": "AI 请求内容无效。"},
            )
        assert isinstance(error, ReportingError)
        return HTTPException(
            404 if error.code == "report_editor_ai_task_missing" else 409,
            detail={"code": error.code, "message": error.message},
        )

    @router.post(prefix + "/api/ai/tasks", include_in_schema=False, status_code=202)
    async def start_task(
        report_id: str, revision: int, request: Request, payload: AITaskStartRequest
    ):
        session, context = await access(request, report_id, revision, True)
        try:
            return await service.start(session, context, payload)
        except (ReportingError, ValidationError) as error:
            raise error_response(error) from None

    @router.get(prefix + "/api/ai/tasks/{task_id}", include_in_schema=False)
    async def read_task(
        report_id: str,
        revision: int,
        task_id: str,
        request: Request,
        wait_ms: int = Query(0, alias="waitMs", ge=0, le=1500),
    ):
        session, context = await access(request, report_id, revision, False)
        try:
            return await service.status(session, context, task_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise error_response(error) from None

    @router.post(prefix + "/api/ai/tasks/{task_id}/{action}", include_in_schema=False)
    async def update_task(
        report_id: str,
        revision: int,
        task_id: str,
        action: Literal["accept", "reject", "cancel"],
        request: Request,
        payload: AITaskAcceptRequest | None = None,
    ):
        session, context = await access(request, report_id, revision, True)
        try:
            return await service.transition(
                session, context, task_id, action, payload.snapshot if payload else {}
            )
        except ReportingError as error:
            raise error_response(error) from None
