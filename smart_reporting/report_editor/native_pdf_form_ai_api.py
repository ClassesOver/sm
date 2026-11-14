"""PDF 表单填写复用原生会话、来源范围和同源 CSRF。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..office.contract import SHA256_PATTERN
from ..reporting.models import ReportingError
from .native_ai_api import _ai_error
from .native_api import NATIVE_SESSION_COOKIE, _csrf


class NativePDFFormSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fieldId: str = Field(pattern=SHA256_PATTERN)


class NativePDFFormStartPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    client_request_id: str = Field(alias="clientRequestId", pattern=r"^[a-zA-Z0-9_-]{1,128}$")
    expected_sha256: str = Field(alias="expectedSha256", pattern=SHA256_PATTERN)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    instruction: str = Field(min_length=1, max_length=2000)
    selection: list[NativePDFFormSelection] = Field(min_length=1, max_length=100)


class NativePDFFormAcceptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    expected_sha256: str = Field(alias="expectedSha256", pattern=SHA256_PATTERN)
    snapshot_sha256: str = Field(alias="snapshotSha256", pattern=SHA256_PATTERN)
    operations: list[dict[str, Any]] = Field(max_length=500)


class NativePDFFormCancelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    client_request_id: str = Field(alias="clientRequestId", pattern=r"^[a-zA-Z0-9_-]{1,128}$")


def create_native_pdf_form_ai_router(grants, *, editor, forms, allowed_origin=None):
    router = APIRouter()
    base = "/reports/v1/native/{document_id}/{revision}/api/ai/forms"

    async def session_for(request, document_id, revision, *, write=False):
        if write:
            _csrf(request, grants, NATIVE_SESSION_COOKIE, allowed_origin)
        session = await grants.lookup_session(request.cookies.get(NATIVE_SESSION_COOKIE, ""))
        if session.report_id != document_id or session.revision != revision:
            raise ReportingError("native_permission_denied", "原生会话与请求版本不一致。")
        await editor.context_for_session(session)
        if forms is None:
            raise ReportingError("native_ai_disabled", "PDF 表单填写尚未开放。")
        return session

    @router.post(base + "/start")
    async def start(
        document_id: str, revision: int, request: Request, payload: NativePDFFormStartPayload
    ):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await forms.start(session, **payload.model_dump())
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/cancel")
    async def cancel(
        document_id: str, revision: int, request: Request, payload: NativePDFFormCancelPayload
    ):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await forms.cancel_request(session, payload.client_request_id)
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
            return await forms.status(session, edit_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.get(base + "/{edit_id}/events")
    async def events(document_id: str, revision: int, edit_id: str, request: Request,
                     after: int = Query(default=0, ge=0)):
        try:
            session = await session_for(request, document_id, revision)
            return await forms.event_stream(session, edit_id, after)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/{edit_id}/accept")
    async def accept(
        document_id: str,
        revision: int,
        edit_id: str,
        request: Request,
        payload: NativePDFFormAcceptPayload,
    ):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await forms.accept(session, edit_id, **payload.model_dump())
        except ReportingError as error:
            raise _ai_error(error) from None

    return router
