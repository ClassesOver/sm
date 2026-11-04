from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from ..reporting.delivery.publishing import content_disposition
from ..reporting.models import ReportingError
from .service import ReportEditorGrantService

WORKBOOK_SESSION_COOKIE = "report_workbook_session"
WORKBOOK_CSRF_COOKIE = "report_workbook_csrf"
_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def create_report_workbook_editor_router(
    grants: ReportEditorGrantService, *, workbooks: object, workbook_ai: object | None = None,
    static_dir: str | Path, cookie_secure: bool = True,
) -> APIRouter:
    router = APIRouter()
    root = Path(static_dir).resolve()

    def fail(error: ReportingError) -> HTTPException:
        return HTTPException(status_code=403 if "permission_denied" in error.code else 409,
                             detail={"code": error.code, "message": error.message})

    async def require_session(request: Request, report_id: str, revision: int):
        try:
            session = await grants.lookup_session(request.cookies.get(WORKBOOK_SESSION_COOKIE, ""))
            if session.report_id != report_id or session.revision != revision:
                raise ReportingError("report_workbook_scope_mismatch", "工作簿编辑会话作用域不一致。")
            await workbooks.context_for_session(session)
            return session
        except ReportingError as error:
            raise fail(error) from None

    def require_csrf(request: Request) -> None:
        token = grants.csrf_token(request.cookies.get(WORKBOOK_SESSION_COOKIE, ""))
        if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), token) or not secrets.compare_digest(request.cookies.get(WORKBOOK_CSRF_COOKIE, ""), token):
            raise HTTPException(status_code=403, detail={"code": "report_workbook_csrf_invalid"})

    def ai_service():
        if workbook_ai is None:
            raise HTTPException(status_code=503, detail={"code": "report_workbook_ai_unavailable"})
        return workbook_ai

    async def payload_for(request: Request):
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail={"code": "report_workbook_payload_invalid"}) from None
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail={"code": "report_workbook_payload_invalid"})
        return payload

    @router.get("/reports/v1/workbooks/open/{raw_grant}", include_in_schema=False)
    async def open_workbook(raw_grant: str):
        try:
            raw_session, session = await grants.exchange(raw_grant)
            context = await workbooks.context_for_session(session)
        except ReportingError as error:
            raise fail(error) from None
        path = f"/reports/v1/workbooks/{quote(context.report_id, safe='')}/{context.revision}"
        response = RedirectResponse(path, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
        max_age = max(0, int((session.expires_at - datetime.now(UTC)).total_seconds()))
        response.set_cookie(WORKBOOK_SESSION_COOKIE, raw_session, httponly=True, secure=cookie_secure, samesite="lax", max_age=max_age, path=path)
        response.set_cookie(WORKBOOK_CSRF_COOKIE, grants.csrf_token(raw_session), httponly=False, secure=cookie_secure, samesite="lax", max_age=max_age, path=path)
        return response

    @router.get("/reports/v1/workbooks/download/{raw_grant}", include_in_schema=False)
    async def download_workbook(raw_grant: str):
        try:
            _, session = await grants.exchange(raw_grant)
            context, content = await workbooks.download_for_session(session)
        except ReportingError as error:
            raise fail(error) from None
        return Response(content, media_type=_XLSX_TYPE, headers={"Cache-Control": "no-store", "Content-Disposition": content_disposition(context.xlsx_path or "report.xlsx", artifact="xlsx"), "X-Content-Type-Options": "nosniff"})

    @router.get("/reports/v1/workbooks/{report_id}/{revision}", include_in_schema=False)
    async def workbook_page(report_id: str, revision: int, request: Request):
        await require_session(request, report_id, revision)
        index = root / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail={"code": "report_workbook_editor_unbuilt"})
        return FileResponse(index, media_type="text/html", headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
            "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
        })

    @router.get("/reports/v1/workbooks/{report_id}/{revision}/api/file", include_in_schema=False)
    async def workbook_file(report_id: str, revision: int, request: Request):
        session = await require_session(request, report_id, revision)
        try:
            context = await workbooks.context_for_session(session)
            content = await workbooks._read_verified(context)
            return Response(content, media_type=_XLSX_TYPE, headers={"Cache-Control": "no-store", "X-Workbook-Sha256": context.xlsx_sha256})
        except ReportingError as error:
            raise fail(error) from None

    @router.post("/reports/v1/workbooks/{report_id}/{revision}/api/snapshot", include_in_schema=False)
    async def snapshot_workbook(report_id: str, revision: int, request: Request):
        session = await require_session(request, report_id, revision)
        require_csrf(request)
        payload = await payload_for(request)
        try:
            return await workbooks.snapshot_for_session(session, payload.get("operations", []))
        except ReportingError as error:
            raise fail(error) from None

    @router.post("/reports/v1/workbooks/{report_id}/{revision}/api/save", include_in_schema=False)
    async def save_workbook(report_id: str, revision: int, request: Request):
        session = await require_session(request, report_id, revision)
        require_csrf(request)
        try:
            return await workbooks.save_revision(session, await payload_for(request))
        except ReportingError as error:
            raise fail(error) from None

    @router.post("/reports/v1/workbooks/{report_id}/{revision}/api/ai/start", include_in_schema=False)
    async def start_workbook_ai(report_id: str, revision: int, request: Request):
        session = await require_session(request, report_id, revision)
        require_csrf(request)
        payload = await payload_for(request)
        try:
            return await ai_service().start_edit(session, payload.get("instruction"), payload.get("operations", []))
        except ReportingError as error:
            raise fail(error) from None

    @router.get("/reports/v1/workbooks/{report_id}/{revision}/api/ai/{edit_id}", include_in_schema=False)
    async def workbook_ai_status(report_id: str, revision: int, edit_id: str, request: Request, wait_ms: int = Query(default=0, ge=0, le=20_000)):
        session = await require_session(request, report_id, revision)
        try:
            return await ai_service().wait_edit_status(session, edit_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise fail(error) from None

    @router.post("/reports/v1/workbooks/{report_id}/{revision}/api/ai/{edit_id}/accept", include_in_schema=False)
    async def accept_workbook_ai(report_id: str, revision: int, edit_id: str, request: Request):
        session = await require_session(request, report_id, revision)
        require_csrf(request)
        payload = await payload_for(request)
        try:
            snapshot = await workbooks.snapshot_for_session(session, payload.get("operations", []))
            return await ai_service().mark_accepted(session, edit_id, snapshot_sha256=snapshot["snapshotSha256"])
        except ReportingError as error:
            raise fail(error) from None

    @router.post("/reports/v1/workbooks/{report_id}/{revision}/api/ai/{edit_id}/cancel", include_in_schema=False)
    async def cancel_workbook_ai(report_id: str, revision: int, edit_id: str, request: Request):
        session = await require_session(request, report_id, revision)
        require_csrf(request)
        try:
            return await ai_service().cancel_edit(session, edit_id)
        except ReportingError as error:
            raise fail(error) from None

    return router
