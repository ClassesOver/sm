from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from ..reporting.delivery.publishing import content_disposition
from ..reporting.models import ReportingError
from ._api_helpers import (
    read_editor_json,
    reporting_editor_error,
    reporting_http_error,
    require_editor_csrf,
)
from .office_refresh import (
    OfficeRefreshRequest,
    office_refresh_capability,
    office_refresh_delivery,
    office_refresh_status,
    start_office_refresh,
)
from .service import ReportEditorGrantService

SLIDES_SESSION_COOKIE = "report_slides_session"
SLIDES_CSRF_COOKIE = "report_slides_csrf"


def create_report_slides_editor_router(
    grants: ReportEditorGrantService,
    *,
    slides: object,
    slides_ai: object | None = None,
    slides_images: object | None = None,
    slides_charts: object | None = None,
    static_dir: str | Path,
    cookie_secure: bool = True,
) -> APIRouter:
    router = APIRouter()
    root = Path(static_dir).resolve()

    async def require_context(request: Request, report_id: str, revision: int, *, verify_file: bool = True):
        try:
            session = await grants.lookup_session(
                request.cookies.get(SLIDES_SESSION_COOKIE, "")
            )
            if session.report_id != report_id or session.revision != revision:
                raise ReportingError(
                    "report_slides_scope_mismatch", "幻灯片编辑会话作用域不一致。"
                )
            context = (await slides.context_for_session(session) if verify_file else
                await slides.refresh_context_for_session(session))
            return session, context
        except ReportingError as error:
            status = 403 if "permission_denied" in error.code else 404
            raise reporting_http_error(error, status_code=status) from None

    def require_csrf(request: Request) -> None:
        require_editor_csrf(
            request, grants, session_cookie=SLIDES_SESSION_COOKIE,
            csrf_cookie=SLIDES_CSRF_COOKIE, error_code="report_slides_csrf_invalid",
        )

    async def read_json(request: Request) -> object:
        return await read_editor_json(
            request, error_code="report_slides_payload_invalid",
            message="请求内容不是有效的 JSON。",
        )

    def require_ai_service():
        if slides_ai is None:
            raise HTTPException(status_code=503, detail={"code": "report_slides_ai_unavailable"})
        return slides_ai

    def require_image_service():
        if slides_images is None:
            raise HTTPException(status_code=503, detail={"code": "report_slides_image_unavailable"})
        return slides_images

    def require_chart_service():
        if slides_charts is None:
            raise HTTPException(status_code=503, detail={"code": "report_slides_chart_unavailable", "message": "图表 AI 编辑暂不可用。",
            })
        return slides_charts

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
            raise reporting_http_error(error, status_code=status) from None
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
        response.set_cookie(
            SLIDES_CSRF_COOKIE,
            grants.csrf_token(raw_session),
            httponly=False,
            secure=cookie_secure,
            samesite="lax",
            max_age=max(0, int((session.expires_at - datetime.now(UTC)).total_seconds())),
            path=path,
        )
        return response

    @router.get("/reports/v1/slides/download/{raw_grant}", include_in_schema=False)
    async def download_slides(raw_grant: str) -> Response:
        try:
            _raw_session, session = await grants.exchange(raw_grant)
            context, content = await slides.download_for_session(session)
        except ReportingError as error:
            status = 403 if "permission_denied" in error.code else 404
            raise reporting_http_error(error, status_code=status) from None
        return Response(
            content,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            headers={
                "Cache-Control": "no-store",
                # 报告标题通常含中文；响应头只能是 latin-1，需 ASCII 回退名 + RFC 5987 原名。
                "Content-Disposition": content_disposition(context.pptx_path or "report.pptx", artifact="pptx"),
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/reports/v1/slides/assets/{asset_path:path}", include_in_schema=False)
    async def read_slides_static(asset_path: str) -> FileResponse:
        assets_root = (root / "assets").resolve()
        target = (assets_root / asset_path).resolve()
        if not target.is_relative_to(assets_root) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    @router.get("/reports/v1/slides/{report_id}/{revision}", include_in_schema=False)
    async def read_slides_editor_page(
        report_id: str, revision: int, request: Request
    ) -> FileResponse:
        await require_context(request, report_id, revision, verify_file=False)
        index = root / "slides.html"
        if not index.is_file():
            raise HTTPException(status_code=503, detail={"code": "slides_editor_unbuilt"})
        response = FileResponse(index, media_type="text/html")
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/deck", include_in_schema=False)
    async def read_slides_deck(report_id: str, revision: int, request: Request):
        _session, _context = await require_context(request, report_id, revision)
        try:
            return await slides.deck_for_session(_session)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/render-tree", include_in_schema=False)
    async def read_slides_render_tree(report_id: str, revision: int, request: Request):
        session, _context = await require_context(request, report_id, revision)
        try:
            return await slides.render_tree_for_session(session)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/render-tree", include_in_schema=False)
    async def preview_slides_render_tree(report_id: str, revision: int, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        try:
            return await slides.render_tree_for_session(session, await read_json(request))
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/preview.pdf", include_in_schema=False)
    async def preview_slides_pdf(report_id: str, revision: int, request: Request) -> Response:
        _session, _context = await require_context(request, report_id, revision)
        try:
            content = await slides.preview_pdf(_session)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=503) from None
        return Response(
            content,
            media_type="application/pdf",
            headers={"Cache-Control": "no-store", "Content-Disposition": "inline; filename=slides-preview.pdf"},
        )

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/save", include_in_schema=False)
    async def save_slides_revision(report_id: str, revision: int, request: Request):
        _session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        try:
            payload = await read_json(request)
            if not isinstance(payload, dict):
                raise ReportingError("report_slides_edit_invalid", "幻灯片修改内容无效。")
            image_edits = payload.pop("imageEdits", [])
            chart_edits = payload.pop("chartEdits", [])
            replacements = []
            if chart_edits:
                chart_service = require_chart_service()
                replacements = await chart_service.resolve_for_session(_session, chart_edits)
            image_records = []
            if image_edits:
                image_service = require_image_service()
                image_records = await image_service.resolve_for_session(_session, image_edits)
            result = await slides.save_revision(
                _session, payload, **({"images": image_records} if image_records else {}),
                **({"chart_replacements": replacements} if replacements else {}),
            )
            if replacements:
                try:
                    await chart_service.discard_candidates(
                        _session, [item['candidateId'] for item in replacements]
                    )
                except Exception:  # noqa: BLE001 - 清理失败不影响已保存修订
                    pass
            if image_records:
                try:
                    await image_service.discard_candidates(
                        _session, [image["candidateId"] for image in image_records]
                    )
                except Exception:  # noqa: BLE001 - saved PPTX must not be failed by cache cleanup
                    pass
            return result
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/charts", include_in_schema=False)
    async def list_slide_charts(report_id: str, revision: int, request: Request):
        session, _context = await require_context(request, report_id, revision)
        try:
            return await require_chart_service().list_charts(session)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/charts/start", include_in_schema=False)
    async def start_slide_chart(report_id: str, revision: int, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        try:
            payload = await read_json(request)
            if not isinstance(payload, dict):
                raise ReportingError('report_slides_chart_edit_invalid', '图表编辑请求无效。')
            return await require_chart_service().start_edit(
                session, payload.get('slideIndex'), payload.get('elementId'), payload.get('instruction'),
            )
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/charts/{candidate_id}", include_in_schema=False)
    async def read_slide_chart(
        report_id: str, revision: int, candidate_id: str, request: Request,
        wait_ms: int = Query(default=0, ge=0, le=1500),
    ):
        session, _context = await require_context(request, report_id, revision)
        try:
            return await require_chart_service().edit_status(session, candidate_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/charts/{candidate_id}/cancel", include_in_schema=False)
    async def cancel_slide_chart(report_id: str, revision: int, candidate_id: str, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        try:
            return await require_chart_service().cancel_edit(session, candidate_id)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/ai/start", include_in_schema=False)
    async def start_slides_ai_edit(report_id: str, revision: int, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        service = require_ai_service()
        try:
            payload = await read_json(request)
            instruction = payload.get("instruction") if isinstance(payload, dict) else None
            return await service.start_edit(session, instruction)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/ai/{edit_id}", include_in_schema=False)
    async def read_slides_ai_status(
        report_id: str,
        revision: int,
        edit_id: str,
        request: Request,
        wait_ms: int = Query(default=0, ge=0, le=20_000),
    ):
        session, _context = await require_context(request, report_id, revision)
        service = require_ai_service()
        try:
            return await service.wait_edit_status(session, edit_id, wait_ms=wait_ms)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/ai/{edit_id}/cancel", include_in_schema=False)
    async def cancel_slides_ai_edit(report_id: str, revision: int, edit_id: str, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        service = require_ai_service()
        try:
            return await service.cancel_edit(session, edit_id)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/ai/{edit_id}/accept", include_in_schema=False)
    async def accept_slides_ai_edit(report_id: str, revision: int, edit_id: str, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        service = require_ai_service()
        try:
            return await service.mark_accepted(session, edit_id)
        except ReportingError as error:
            raise reporting_editor_error(error) from None

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/ai/image", include_in_schema=False)
    async def generate_slides_image(report_id: str, revision: int, request: Request):
        session, _context = await require_context(request, report_id, revision)
        require_csrf(request)
        service = require_image_service()
        try:
            payload = await read_json(request)
            prompt = payload.get("prompt") if isinstance(payload, dict) else None
            return await service.generate_candidate(session, prompt)
        except ReportingError as error:
            raise reporting_editor_error(error) from None


    @router.get("/reports/v1/slides/{report_id}/{revision}/api/context", include_in_schema=False)
    async def refresh_context(report_id: str, revision: int, request: Request):
        _session, context = await require_context(request, report_id, revision, verify_file=False)
        return {"reportId": context.report_id, "revision": context.revision,
            "contextSha256": context.digest(),
            "sha256": getattr(context, context.delivery_format + '_sha256'),
            "dataRefresh": await office_refresh_capability(slides, context)}

    @router.post("/reports/v1/slides/{report_id}/{revision}/api/recalculations", include_in_schema=False)
    async def submit_refresh(report_id: str, revision: int, request: Request, payload: OfficeRefreshRequest):
        _session, context = await require_context(request, report_id, revision, verify_file=False)
        require_csrf(request)
        try:
            return await start_office_refresh(slides, context, payload)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=503 if error.code == 'report_editor_recalculation_unavailable' else 409) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/recalculations/by-request/{request_id}", include_in_schema=False)
    async def refresh_request_status(report_id: str, revision: int, request_id: str, request: Request):
        _session, context = await require_context(request, report_id, revision, verify_file=False)
        try:
            return await office_refresh_status(slides, context, request_id=request_id)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/recalculations/{task_id}", include_in_schema=False)
    async def refresh_task_status(report_id: str, revision: int, task_id: str, request: Request):
        _session, context = await require_context(request, report_id, revision, verify_file=False)
        try:
            return await office_refresh_status(slides, context, task_id=task_id)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    @router.get("/reports/v1/slides/{report_id}/{revision}/api/recalculations/{task_id}/delivery", include_in_schema=False)
    async def refresh_task_delivery(report_id: str, revision: int, task_id: str, request: Request):
        _session, context = await require_context(request, report_id, revision, verify_file=False)
        try:
            return await office_refresh_delivery(slides, context, task_id)
        except ReportingError as error:
            raise reporting_http_error(error, status_code=409) from None

    return router
