from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, NoReturn
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from ..reporting.models import ReportingError
from .service import ReportEditorGrantService

EDITOR_SESSION_COOKIE = "report_editor_session"
_LEGACY_SESSION_COOKIE_PATH = "/reports/v1/editor"


class EditorWritePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    markdown: str = Field(max_length=10 * 1024 * 1024)
    expected_sha256: str = Field(alias="expectedSha256", pattern=r"^[0-9a-f]{64}$")


class EditorExportSettings(BaseModel):
    cover: StrictBool = False
    toc: StrictBool = True
    header_footer: StrictBool = Field(True, alias="headerFooter")
    page_numbers: StrictBool = Field(True, alias="pageNumbers")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class EditorExportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    expected_sha256: str = Field(alias="expectedSha256", pattern=r"^[0-9a-f]{64}$")
    settings: EditorExportSettings | None = None
    note: str | None = Field(default=None, max_length=200)


class EditorAIRewritePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selection: str = Field(max_length=12_000)
    action: str = Field(min_length=1, max_length=32)


class EditorEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    event: Literal[
        "document_loaded",
        "save_succeeded",
        "save_failed",
        "export_succeeded",
        "export_failed",
    ]
    duration_ms: int | None = Field(default=None, alias="durationMs", ge=0, le=3_600_000)
    format: Literal["pdf", "word"] | None = None
    error_code: str | None = Field(default=None, alias="errorCode", max_length=128)


def create_report_editor_router(
    grants: ReportEditorGrantService,
    *,
    editor: Any | None = None,
    ai: Any | None = None,
    cookie_secure: bool = True,
    allowed_origin: str | None = None,
    static_dir: str | Path | None = None,
) -> APIRouter:
    router = APIRouter()
    frontend_static = Path(static_dir) if static_dir else Path(__file__).with_name("static")

    @router.get("/reports/v1/editor/assets/{asset_path:path}", include_in_schema=False)
    async def read_editor_static(asset_path: str) -> FileResponse:
        root = frontend_static.resolve()
        target = (root / asset_path).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(target)

    @router.get("/reports/v1/editor/open/{raw_grant}", include_in_schema=False)
    async def open_report_editor(raw_grant: str) -> RedirectResponse:
        try:
            raw_session, session = await grants.exchange(raw_grant)
        except ReportingError as error:
            status = 410 if error.code == "report_editor_grant_expired" else 404
            raise HTTPException(
                status_code=status,
                detail={"code": error.code, "message": error.message},
            ) from None
        editor_path = f"/reports/v1/editor/{session.report_id}/{session.revision}"
        response = RedirectResponse(editor_path, status_code=303)
        # 编辑链接通常从聊天或邮件等其他站点点开；Strict cookie 在跨站发起的重定向链上
        # 不会随后续页面请求发送，首次打开会失败。Lax 仅放行顶层 GET 导航，写操作仍由
        # Origin + CSRF 令牌保护。cookie 按报告 revision 限定路径，多个报告/修订可在不同
        # 标签页并存，不会互相覆盖会话。
        response.set_cookie(
            EDITOR_SESSION_COOKIE,
            raw_session,
            httponly=True,
            secure=cookie_secure,
            samesite="lax",
            max_age=max(0, int((session.expires_at - datetime.now(UTC)).total_seconds())),
            path=editor_path,
        )
        # 旧版本在共享路径上签发的会话会与按路径限定的新会话同名并存，且可能在解析时
        # 覆盖新会话，打开链接时一并清除。
        response.delete_cookie(
            EDITOR_SESSION_COOKIE,
            path=_LEGACY_SESSION_COOKIE_PATH,
            secure=cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return response

    if editor is not None:

        @router.get(
            "/reports/v1/editor/{report_id}/{revision}",
            include_in_schema=False,
        )
        async def read_report_editor_page(
            report_id: str, revision: int, request: Request
        ) -> FileResponse:
            await _read_context(grants, editor, request, report_id=report_id, revision=revision)
            index = frontend_static / "index.html"
            if not index.is_file():
                raise HTTPException(status_code=503, detail={"code": "report_editor_unbuilt"})
            response = FileResponse(index, media_type="text/html")
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; font-src 'self' data:; connect-src 'self'; "
                "object-src 'none'; base-uri 'self'; form-action 'none'; "
                "frame-ancestors 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            response.headers["Cache-Control"] = "no-store"
            return response

        @router.get(
            "/reports/v1/editor/{report_id}/{revision}/api/document",
            include_in_schema=False,
        )
        async def read_report_document(
            report_id: str, revision: int, request: Request
        ) -> dict[str, Any]:
            raw_session, context = await _read_context(
                grants, editor, request, report_id=report_id, revision=revision
            )
            try:
                document = await editor.read_document(context)
            except ReportingError as error:
                _editor_http_error(error)
            result: dict[str, Any] = {
                "path": document.path,
                "markdown": document.markdown,
                "sha256": document.sha256,
                "csrfToken": grants.csrf_token(raw_session),
            }
            chart_reader = getattr(editor, "interactive_charts", None)
            interactive_charts = await chart_reader(context) if callable(chart_reader) else {}
            if interactive_charts:
                result["interactiveCharts"] = interactive_charts
            return result

        @router.get(
            "/reports/v1/editor/{report_id}/{revision}/asset/{asset_path:path}",
            include_in_schema=False,
        )
        async def read_report_asset(
            report_id: str,
            revision: int,
            asset_path: str,
            request: Request,
        ) -> Response:
            _raw_session, context = await _read_context(
                grants, editor, request, report_id=report_id, revision=revision
            )
            try:
                content, media_type = await editor.read_asset(context, asset_path)
            except ReportingError as error:
                _editor_http_error(error)
            return Response(
                content,
                media_type=media_type,
                headers={
                    "Cache-Control": "private, no-store",
                    "Content-Security-Policy": "default-src 'none'",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        @router.get(
            "/reports/v1/editor/{report_id}/{revision}/api/history",
            include_in_schema=False,
        )
        async def read_report_history(
            report_id: str,
            revision: int,
            request: Request,
            limit: int = Query(default=20, ge=1, le=100),
            offset: int = Query(default=0, ge=0),
        ) -> dict[str, object]:
            _raw_session, context = await _read_context(
                grants, editor, request, report_id=report_id, revision=revision
            )
            try:
                return await editor.history_page(context, limit=limit, offset=offset)
            except ReportingError as error:
                _editor_http_error(error)

        @router.get(
            "/reports/v1/editor/{report_id}/{revision}/api/history/{history_revision}",
            include_in_schema=False,
        )
        async def read_report_history_revision(
            report_id: str,
            revision: int,
            history_revision: int,
            request: Request,
        ) -> dict[str, object]:
            _raw_session, context = await _read_context(
                grants, editor, request, report_id=report_id, revision=revision
            )
            try:
                return await editor.read_history_revision(context, history_revision)
            except ReportingError as error:
                _editor_http_error(error)

        @router.put(
            "/reports/v1/editor/{report_id}/{revision}/api/document",
            include_in_schema=False,
        )
        async def write_report_document(
            report_id: str,
            revision: int,
            payload: EditorWritePayload,
            request: Request,
        ) -> dict[str, str]:
            context = await _write_context(
                grants,
                editor,
                request,
                report_id=report_id,
                revision=revision,
                allowed_origin=allowed_origin,
            )
            try:
                document = await editor.save_draft(
                    context,
                    markdown=payload.markdown,
                    expected_sha256=payload.expected_sha256,
                )
            except ReportingError as error:
                _editor_http_error(error)
            return {
                "path": document.path,
                "markdown": document.markdown,
                "sha256": document.sha256,
            }

        @router.post(
            "/reports/v1/editor/{report_id}/{revision}/api/export",
            include_in_schema=False,
        )
        async def export_report_revision(
            report_id: str,
            revision: int,
            payload: EditorExportPayload,
            request: Request,
        ) -> dict[str, object]:
            context = await _write_context(
                grants,
                editor,
                request,
                report_id=report_id,
                revision=revision,
                allowed_origin=allowed_origin,
            )
            request_id = _request_id(request.headers.get("x-request-id"))
            try:
                export_options: dict[str, object] = {
                    "expected_sha256": payload.expected_sha256,
                    "request_id": request_id,
                }
                if payload.settings is not None:
                    export_options["settings"] = payload.settings.model_dump(by_alias=True)
                if payload.note is not None:
                    export_options["note"] = payload.note
                # 渲染与验收可能持续数分钟，改为后台任务并立即返回，由编辑器轮询状态，
                # 避免同步请求被网关读超时切断。
                started = await editor.start_export(context, **export_options)
            except ReportingError as error:
                _editor_http_error(error, request_id=request_id)
            return JSONResponse(started, status_code=202)

        @router.get(
            "/reports/v1/editor/{report_id}/{revision}/api/export/{export_id}",
            include_in_schema=False,
        )
        async def read_report_export(
            report_id: str,
            revision: int,
            export_id: str,
            request: Request,
        ) -> dict[str, object]:
            _raw_session, context = await _read_context(
                grants, editor, request, report_id=report_id, revision=revision
            )
            try:
                status = editor.export_status(context, export_id)
            except ReportingError as error:
                _editor_http_error(error)
            error = status.get("error")
            if isinstance(error, dict):
                # 与同步错误响应使用同一状态码映射，编辑器据此选择提示文案。
                status = {
                    **status,
                    "error": {**error, "status": _editor_error_status(error["code"])},
                }
            return status

        @router.post(
            "/reports/v1/editor/{report_id}/{revision}/api/events",
            include_in_schema=False,
            status_code=204,
        )
        async def record_report_editor_event(
            report_id: str,
            revision: int,
            payload: EditorEventPayload,
            request: Request,
        ) -> Response:
            context = await _write_context(
                grants,
                editor,
                request,
                report_id=report_id,
                revision=revision,
                allowed_origin=allowed_origin,
            )
            logger.info(
                "report_editor_event report_id={} revision={} user_id={} event={} "
                "duration_ms={} format={} error_code={}",
                context.report_id,
                context.revision,
                context.scope["userId"],
                payload.event,
                payload.duration_ms,
                payload.format,
                payload.error_code,
            )
            return Response(status_code=204)

        if ai is not None:

            @router.post(
                "/reports/v1/editor/{report_id}/{revision}/api/ai/rewrite",
                include_in_schema=False,
            )
            async def rewrite_report_selection(
                report_id: str,
                revision: int,
                payload: EditorAIRewritePayload,
                request: Request,
            ) -> StreamingResponse:
                context = await _write_context(
                    grants,
                    editor,
                    request,
                    report_id=report_id,
                    revision=revision,
                    allowed_origin=allowed_origin,
                )
                try:
                    stream = ai.stream_rewrite(
                        context,
                        selection=payload.selection,
                        action=payload.action,
                    )
                except ReportingError as error:
                    _editor_http_error(error)
                return StreamingResponse(stream, media_type="text/markdown")

    return router


async def _write_context(
    grants: ReportEditorGrantService,
    editor: Any,
    request: Request,
    *,
    report_id: str,
    revision: int,
    allowed_origin: str | None,
) -> Any:
    raw_session = request.cookies.get(EDITOR_SESSION_COOKIE, "")
    origin = request.headers.get("origin", "")
    expected_origin = _origin(allowed_origin) if allowed_origin else _origin(str(request.base_url))
    supplied_csrf = request.headers.get("x-csrf-token", "")
    if origin != expected_origin or not secrets.compare_digest(
        supplied_csrf, grants.csrf_token(raw_session)
    ):
        raise HTTPException(status_code=403, detail={"code": "report_editor_csrf_invalid"})
    try:
        session = await grants.lookup_session(raw_session)
        if session.report_id != report_id or session.revision != revision:
            raise ReportingError("report_editor_scope_mismatch", "报告编辑会话作用域不一致。")
        return await editor.context_for_session(session)
    except ReportingError as error:
        _editor_http_error(error)


async def _read_context(
    grants: ReportEditorGrantService,
    editor: Any,
    request: Request,
    *,
    report_id: str,
    revision: int,
) -> tuple[str, Any]:
    raw_session = request.cookies.get(EDITOR_SESSION_COOKIE, "")
    try:
        session = await grants.lookup_session(raw_session)
        if session.report_id != report_id or session.revision != revision:
            raise ReportingError("report_editor_scope_mismatch", "报告编辑会话作用域不一致。")
        return raw_session, await editor.context_for_session(session)
    except ReportingError as error:
        _editor_http_error(error)


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}"


def _request_id(value: str | None) -> str:
    try:
        return str(UUID(value)) if value else str(uuid4())
    except ValueError:
        return str(uuid4())


def _editor_error_status(code: str) -> int:
    if code in {
        "report_editor_conflict",
        "report_editor_revision_conflict",
        "report_editor_revision_stale",
        "report_editor_export_running",
    }:
        return 409
    if code == "report_editor_export_busy":
        return 429
    if code == "report_editor_export_timeout":
        return 504
    if code == "report_editor_session_expired":
        return 410
    if code.startswith("report_editor_ai_"):
        return 400
    if code in {"report_artifact_validation_failed", "report_editor_export_failed"}:
        return 422
    return 404


def _editor_http_error(error: ReportingError, *, request_id: str | None = None) -> NoReturn:
    status = _editor_error_status(error.code)
    raise HTTPException(
        status_code=status,
        detail={
            "code": error.code,
            "message": error.message,
            **({"requestId": request_id} if request_id else {}),
        },
    ) from None
