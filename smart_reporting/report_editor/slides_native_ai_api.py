"""PPTX 专属候选路由，复用原生会话与 CSRF，不接收文件路径。"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..reporting.models import ReportingError
from .native_ai_api import NativeAIAcceptPayload, _ai_error, _DraftPayload
from .native_api import NATIVE_SESSION_COOKIE, _csrf
from .slides_native_ai import NativeSlidesAIService


class SlidesAISelection(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, strict=True)
    slide_index: int = Field(alias="slideIndex", ge=0)
    element_id: str | None = Field(default=None, alias="elementId", min_length=1, max_length=512)


class SlidesNativeAIStartPayload(_DraftPayload):
    client_request_id: str = Field(alias="clientRequestId", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    instruction: str = Field(min_length=1, max_length=2000)
    selection: list[SlidesAISelection] = Field(default_factory=list, max_length=100)
    scope: Literal["selection", "deck", "notes"] = "selection"


    @model_validator(mode="after")
    def validate_selection_kind(self):
        for item in self.selection:
            if (self.scope == "notes") != (item.element_id is None):
                raise ValueError("备注按页面授权，画布按对象授权，二者不能混用。")
        return self


class SlidesNativeAICancelRequestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    client_request_id: str = Field(alias="clientRequestId", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


def create_native_slides_ai_router(grants: Any, *, editor: Any, ai: NativeSlidesAIService, allowed_origin: str | None = None) -> APIRouter:
    router = APIRouter()
    base = "/reports/v1/native/{document_id}/{revision}/api/slides-ai"

    async def session_for(request, document_id, revision, *, write=False):
        if write:
            _csrf(request, grants, NATIVE_SESSION_COOKIE, allowed_origin)
        session = await grants.lookup_session(request.cookies.get(NATIVE_SESSION_COOKIE, ""))
        if session.report_id != document_id or session.revision != revision:
            raise ReportingError("native_permission_denied", "原生会话与请求版本不一致。")
        await editor.context_for_session(session)
        return session

    @router.post(base + "/start")
    async def start(document_id: str, revision: int, request: Request, payload: SlidesNativeAIStartPayload):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await ai.start_edit(session, client_request_id=payload.client_request_id, instruction=payload.instruction, expected_sha256=payload.expected_sha256,
                operations=payload.operations, selection=[item.model_dump(by_alias=True, exclude_none=True) for item in payload.selection], scope=payload.scope)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/cancel-request")
    async def cancel_request(document_id: str, revision: int, request: Request, payload: SlidesNativeAICancelRequestPayload):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await ai.cancel_request(session, payload.client_request_id)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.get(base + "/{edit_id}")
    async def status(document_id: str, revision: int, edit_id: str, request: Request, wait_ms: int = Query(default=20000, alias="waitMs", ge=0, le=20000)):
        try:
            session = await session_for(request, document_id, revision)
            return await ai.wait_edit_status(session, edit_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.get(base + "/{edit_id}/events")
    async def events(document_id: str, revision: int, edit_id: str, request: Request,
                     after: int = Query(default=0, ge=0)):
        try:
            session = await session_for(request, document_id, revision)
            return await ai.event_stream(session, edit_id, after)
        except ReportingError as error:
            raise _ai_error(error) from None

    @router.post(base + "/{edit_id}/accept")
    async def accept(document_id: str, revision: int, edit_id: str, request: Request, payload: NativeAIAcceptPayload):
        try:
            session = await session_for(request, document_id, revision, write=True)
            return await ai.accept_edit(session, edit_id, expected_sha256=payload.expected_sha256, operations=payload.operations, snapshot_sha256=payload.snapshot_sha256)
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
