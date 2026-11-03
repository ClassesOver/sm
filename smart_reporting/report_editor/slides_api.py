from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from ..reporting.models import ReportingError
from .api import _editor_error_status, _origin
from .service import ReportEditorGrantService

SLIDES_SESSION_COOKIE = "report_slides_session"


class SlidesExportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_sha256: str = Field(alias="expectedSha256", pattern=r"^[0-9a-f]{64}$")


class SlidesWritePayload(SlidesExportPayload):
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=500)


def _slides_http_error(error: ReportingError) -> NoReturn:
    if error.code == "report_slides_conflict":
        status = 409
    elif error.code in {"report_slides_dependency_missing", "report_artifact_persistence_failed"}:
        status = 503
    elif error.code == "report_slides_engine_unavailable":
        status = 502
    elif error.code == "report_slides_operation_invalid":
        status = 422
    elif "permission_denied" in error.code:
        status = 403
    else:
        status = _editor_error_status(error.code)
    raise HTTPException(status_code=status, detail={"code": error.code, "message": error.message})


def create_report_slides_editor_router(
    grants: ReportEditorGrantService,
    *,
    slides: object,
    static_dir: str | Path,
    cookie_secure: bool = True,
    allowed_origin: str | None = None,
) -> APIRouter:
    router = APIRouter()
    root = Path(static_dir).resolve()

    async def require_context(request: Request, report_id: str, revision: int):
        try:
            session = await grants.lookup_session(
                request.cookies.get(SLIDES_SESSION_COOKIE, "")
            )
            if session.report_id != report_id or session.revision != revision:
                raise ReportingError(
                    "report_slides_scope_mismatch", "幻灯片编辑会话作用域不一致。"
                )
            return session, await slides.context_for_session(session)
        except ReportingError as error:
            _slides_http_error(error)

    async def require_write_context(request: Request, report_id: str, revision: int):
        raw_session = request.cookies.get(SLIDES_SESSION_COOKIE, "")
        origins = {_origin(str(request.base_url))}
        if allowed_origin:
            origins.add(_origin(allowed_origin))
        if request.headers.get("origin", "") not in origins or not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), grants.csrf_token(raw_session),
        ):
            raise HTTPException(status_code=403, detail={"code": "report_editor_csrf_invalid"})
        return await require_context(request, report_id, revision)

    def document_response(request: Request, document: dict[str, Any]) -> JSONResponse:
        return JSONResponse(
            {**document, "csrfToken": grants.csrf_token(request.cookies.get(SLIDES_SESSION_COOKIE, ""))},
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/reports/v1/slides/open/{raw_grant}", include_in_schema=False)
    async def open_slides_editor(raw_grant: str) -> RedirectResponse:
        try:
            raw_session, session = await grants.exchange(raw_grant)
            context = await slides.context_for_session(session)
        except ReportingError as error:
            status = (
                403
                if "permission_denied" in error.code
                else 410 if error.code == "report_editor_grant_expired" else 404
            )
            raise HTTPException(
                status_code=status,
                detail={"code": error.code, "message": error.message},
            ) from None
        path = f"/reports/v1/slides/{quote(context.report_id, safe='')}/{context.revision}"
        response = RedirectResponse(path, status_code=303)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.set_cookie(
            SLIDES_SESSION_COOKIE,
            raw_session,
            httponly=True,
            secure=cookie_secure,
            samesite="lax",
            max_age=max(0, int((session.expires_at - datetime.now(UTC)).total_seconds())),
            path=path,
        )
        return response

    @router.get("/reports/v1/slides/{report_id}/{revision:int}", include_in_schema=False)
    async def read_slides_editor_page(
        report_id: str, revision: int, request: Request
    ) -> FileResponse:
        await require_context(request, report_id, revision)
        index = root / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail={"code": "slides_editor_unbuilt"})
        response = FileResponse(index, media_type="text/html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; style-src-attr 'unsafe-inline'; "
            "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/reports/v1/slides/{report_id}/{revision:int}/document", include_in_schema=False)
    async def read_slides_document(report_id: str, revision: int, request: Request) -> JSONResponse:
        session, _ = await require_context(request, report_id, revision)
        try:
            return document_response(request, await slides.document_for_session(session))
        except ReportingError as error:
            _slides_http_error(error)

    @router.put("/reports/v1/slides/{report_id}/{revision:int}/draft", include_in_schema=False)
    async def save_slides_draft(
        report_id: str, revision: int, payload: SlidesWritePayload, request: Request,
    ) -> JSONResponse:
        session, _ = await require_write_context(request, report_id, revision)
        try:
            document = await slides.save_draft_for_session(
                session, expected_sha256=payload.expected_sha256, operations=payload.operations,
            )
            return document_response(request, document)
        except ReportingError as error:
            _slides_http_error(error)

    @router.post("/reports/v1/slides/{report_id}/{revision:int}/export", include_in_schema=False)
    async def export_slides(
        report_id: str, revision: int, payload: SlidesExportPayload, request: Request,
    ) -> JSONResponse:
        session, _ = await require_write_context(request, report_id, revision)
        try:
            result = await slides.export_for_session(
                session, expected_sha256=payload.expected_sha256,
                base_url=str(request.base_url).rstrip("/"),
            )
            return JSONResponse(result, headers={"Cache-Control": "no-store"})
        except ReportingError as error:
            _slides_http_error(error)

    @router.get("/reports/v1/slides/assets/{asset_path:path}", include_in_schema=False)
    async def read_slides_static(asset_path: str) -> FileResponse:
        target = (root / asset_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    return router
