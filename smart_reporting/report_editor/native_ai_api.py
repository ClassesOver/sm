"""原生 AI 路由复用编辑会话与同源 CSRF，不提供独立文件访问入口。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..reporting.contract import SHA256_PATTERN
from ..reporting.models import ReportingError
from .native_ai import NativeAIService
from .native_api import NATIVE_SESSION_COOKIE, _csrf, _error
from .service import ReportEditorGrantService


class _DraftPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    expected_sha256: str = Field(alias="expectedSha256", pattern=SHA256_PATTERN)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=500)


class NativeAIStartPayload(_DraftPayload):
    instruction: str = Field(min_length=1, max_length=2000)
    selection: list[dict[str, str]] = Field(min_length=1, max_length=100)


class NativePDFReadPayload(_DraftPayload):
    client_request_id: str = Field(alias="clientRequestId", pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    action: Literal["ask", "summarize", "keyPoints", "reviewSummary"] = "ask"
    instruction: str = Field(default="", max_length=2000)
    selection: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class NativePDFReadCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    client_request_id: str = Field(alias="clientRequestId", pattern=r"^[a-zA-Z0-9_-]{1,128}$")


class NativeAIAcceptPayload(_DraftPayload):
    snapshot_sha256: str = Field(alias="snapshotSha256", pattern=SHA256_PATTERN)


def _ai_error(error: ReportingError) -> HTTPException:
    if error.code in {"native_ai_snapshot_changed", "native_ai_preview_changed"}:
        status = 409
    elif error.code in ("native_ai_job_missing",):
        status = 404
    elif error.code in ("native_ai_disabled", "native_ai_pdf_text_disabled", "native_ai_busy"):
        status = 503
    elif error.code.startswith("native_ai_"):
        status = 422
    else:
        return _error(error)
    return HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def create_native_ai_router(
    grants: ReportEditorGrantService,
    *,
    editor: Any,
    ai: NativeAIService,
    pdf_read: Any = None,
    allowed_origin: str | None = None,
) -> APIRouter:
    router = APIRouter()
    base = "/reports/v1/native/{document_id}/{revision}/api/ai"

    async def session_for(
        request: Request, document_id: str, revision: int, *, write: bool = False
    ):
        if write:
            _csrf(request, grants, NATIVE_SESSION_COOKIE, allowed_origin)
        session = await grants.lookup_session(request.cookies.get(NATIVE_SESSION_COOKIE, ""))
        if session.report_id != document_id or session.revision != revision:
            raise ReportingError("native_permission_denied", "原生会话与请求版本不一致。")
        await editor.context_for_session(session)
        return session

    def reader():
        if pdf_read is None:
            raise ReportingError("native_ai_disabled", "PDF AI 阅读尚未开放。")
        return pdf_read

    @router.post(base + "/read/start")
    async def read_start(document_id: str, revision: int, request: Request,
                         payload: NativePDFReadPayload):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await reader().start(session, **payload.model_dump())
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/read/cancel")
    async def read_cancel(document_id: str, revision: int, request: Request,
                          payload: NativePDFReadCancelPayload):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await reader().cancel_request(session, payload.client_request_id)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.get(base + "/read/{task_id}")
    async def read_status(document_id: str, revision: int, task_id: str, request: Request,
                          wait_ms: int = Query(default=20000, alias="waitMs", ge=0, le=20000)):
        try:
            session = await session_for(request, document_id, revision)
            return await reader().status(session, task_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.get(base + "/read/{task_id}/events")
    async def read_events(document_id: str, revision: int, task_id: str, request: Request,
                          after: int = Query(default=0, ge=0)):
        try:
            session = await session_for(request, document_id, revision)
            return await reader().event_stream(session, task_id, after)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/start")
    async def start(
        document_id: str, revision: int, request: Request, payload: NativeAIStartPayload
    ):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await ai.start_edit(
                session,
                instruction=payload.instruction,
                expected_sha256=payload.expected_sha256,
                operations=payload.operations,
                selection=payload.selection,
            )
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.get(base + "/{edit_id}")
    async def status(
        document_id: str,
        revision: int,
        edit_id: str,
        request: Request,
        wait_ms: int = Query(default=20000, alias="waitMs", ge=0, le=20000),
    ):
        try:
            session = await session_for(request, document_id, revision)
            return await ai.wait_edit_status(session, edit_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/{edit_id}/accept")
    async def accept(
        document_id: str,
        revision: int,
        edit_id: str,
        request: Request,
        payload: NativeAIAcceptPayload,
    ):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await ai.accept_edit(
                session,
                edit_id,
                expected_sha256=payload.expected_sha256,
                operations=payload.operations,
                snapshot_sha256=payload.snapshot_sha256,
            )
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/{edit_id}/cancel")
    async def cancel(document_id: str, revision: int, edit_id: str, request: Request):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await ai.cancel_edit(session, edit_id)
        except ReportingError as error:
            raise _ai_error(error) from None

    return router
