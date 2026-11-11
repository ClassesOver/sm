"""原生编辑路由；所有文件路径来自已核验的持久化上下文或签名授权。"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, StrictInt, ValidationError

from ..reporting.contract import SHA256_PATTERN
from ..reporting.delivery.docx_native import inspect_docx
from ..reporting.delivery.office_engine import run_office_engine
from ..reporting.models import ReportingError
from .api import EDITOR_SESSION_COOKIE
from .native import NativeEditorService, bind_native_workspace
from .native_models import NATIVE_ARTIFACT_MEDIA, NativeScope
from .service import ReportEditorGrantService

NATIVE_SESSION_COOKIE = "native_editor_session"


class NativeOpenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    format: Literal["docx", "pdf"]
    request_id: str = Field(alias="requestId", min_length=1, max_length=256)


class NativeSavePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    request_id: str = Field(alias="requestId", min_length=1, max_length=256)
    expected_sha256: str = Field(alias="expectedSha256", pattern=SHA256_PATTERN)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    note: str = Field(default="", max_length=200)
    confirmed_preview_digest: str | None = Field(default=None, alias="confirmedPreviewDigest", pattern=SHA256_PATTERN)


class NativePreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    expected_sha256: str = Field(alias="expectedSha256", pattern=SHA256_PATTERN)
    operations: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    expected_preview_digest: str | None = Field(default=None, alias="expectedPreviewDigest", pattern=SHA256_PATTERN)


class NativeExtractPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    request_id: str = Field(alias="requestId", min_length=1, max_length=256)
    expected_sha256: str = Field(alias="expectedSha256", pattern=SHA256_PATTERN)
    pages: list[StrictInt] = Field(min_length=1, max_length=10000)


class NativeExternalPagesPayload(BaseModel):
    model_config = ConfigDict(extra='forbid',populate_by_name=True)
    request_id: str = Field(alias='requestId',min_length=1,max_length=256)
    expected_sha256: str = Field(alias='expectedSha256',pattern=SHA256_PATTERN)
    action: Literal['insert','replace']
    external_sha256: str = Field(alias='externalSha256',pattern=SHA256_PATTERN)
    bytes_base64: str = Field(alias='bytesBase64',min_length=8,max_length=8*1024*1024)
    after_page: StrictInt | None = Field(default=None,alias='afterPage',ge=0,le=10000)
    pages: list[StrictInt] | None = Field(default=None,min_length=1,max_length=10000)


class NativePdfPermissions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    printing: StrictBool
    modifying: StrictBool
    annotating: StrictBool
    copying: StrictBool


class NativePdfImagesPayload(BaseModel):
    model_config = ConfigDict(extra='forbid',populate_by_name=True)
    expected_sha256: str = Field(alias='expectedSha256',pattern=SHA256_PATTERN)
    pages: list[StrictInt] = Field(min_length=1,max_length=50)
    format: Literal['png','jpeg']
    dpi: StrictInt = Field(default=144,ge=72,le=216)


class NativePdfConvertPayload(BaseModel):
    model_config = ConfigDict(extra='forbid',populate_by_name=True)
    request_id: str = Field(alias='requestId',min_length=1,max_length=256)
    expected_sha256: str = Field(alias='expectedSha256',pattern=SHA256_PATTERN)
    format: Literal['pptx','docx','xlsx']


class NativePdfProtectionPayload(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)
    request_id: str = Field(alias='requestId',min_length=1,max_length=256)
    expected_sha256: str = Field(alias='expectedSha256',pattern=SHA256_PATTERN)
    user_password: SecretStr = Field(alias='userPassword',min_length=1,max_length=127)
    owner_password: SecretStr = Field(alias='ownerPassword',min_length=1,max_length=127)
    permissions: NativePdfPermissions


def _error(error: ReportingError) -> HTTPException:
    code = error.code
    status = 403
    if code in (
        "native_document_not_found",
        "native_source_missing",
        "report_editor_context_missing",
    ):
        status = 404
    elif code == "native_file_too_large":
        status = 413
    elif code in ("native_engine_unavailable", "native_feature_disabled", "native_pdf_text_disabled"):
        status = 503
    elif code in ("native_source_changed", "native_revision_conflict", "report_download_file_changed", "native_pdf_text_preview_changed"):
        status = 409
    elif code in ("native_format_invalid", "native_operations_invalid", "native_pdf_text_confirmation_required", "native_pdf_image_export_invalid"):
        status = 422
    return HTTPException(status_code=status, detail={"code": code, "message": error.message})


def _csrf(
    request: Request, grants: ReportEditorGrantService, cookie: str, allowed_origin: str | None
) -> None:
    def origin(value: str) -> str:
        parsed = urlsplit(value)
        return f"{parsed.scheme}://{parsed.netloc}"

    permitted = {origin(str(request.base_url))}
    if allowed_origin:
        permitted.add(origin(allowed_origin))
    if request.headers.get("origin", "") not in permitted or not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), grants.csrf_token(request.cookies.get(cookie, ""))
    ):
        raise HTTPException(status_code=403, detail={"code": "native_csrf_invalid"})


def create_native_editor_router(
    grants: ReportEditorGrantService,
    *,
    editor: NativeEditorService,
    cookie_secure: bool = True,
    allowed_origin: str | None = None,
    static_dir: str | Path | None = None,
    download_service: Any = None,
    ai_enabled: bool = False,
) -> APIRouter:
    router = APIRouter()
    root = Path(static_dir) if static_dir else Path(__file__).with_name("static")

    async def session_context(
        request: Request, document_id: str, revision: int, *, write: bool = False
    ):
        if write:
            _csrf(request, grants, NATIVE_SESSION_COOKIE, allowed_origin)
        try:
            session = await grants.lookup_session(request.cookies.get(NATIVE_SESSION_COOKIE, ""))
            if session.report_id != document_id or session.revision != revision:
                raise ReportingError("native_permission_denied", "原生会话与请求版本不一致。")
            return session, await editor.context_for_session(session)
        except ReportingError as error:
            raise _error(error) from None

    @router.post("/reports/v1/editor/{report_id}/{revision}/api/native/open")
    async def open_from_report(
        report_id: str, revision: int, request: Request, payload: NativeOpenPayload
    ):
        _csrf(request, grants, EDITOR_SESSION_COOKIE, allowed_origin)
        try:
            session = await grants.lookup_session(request.cookies.get(EDITOR_SESSION_COOKIE, ""))
            if session.report_id != report_id or session.revision != revision:
                raise ReportingError("native_permission_denied", "报告会话与请求版本不一致。")
            return await editor.open_report(
                session, format=payload.format, request_id=payload.request_id
            )
        except ReportingError as error:
            raise _error(error) from None

    @router.get("/reports/v1/native/open/{raw_grant}", include_in_schema=False)
    async def open_native(raw_grant: str):
        try:
            token, session = await grants.exchange(raw_grant)
            context = await editor.context_for_session(session)
        except ReportingError as error:
            raise _error(error) from None
        path = f"/reports/v1/native/{context.document_id}/{context.revision}"
        response = RedirectResponse(
            path,
            status_code=303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )
        response.set_cookie(
            NATIVE_SESSION_COOKIE,
            token,
            httponly=True,
            secure=cookie_secure,
            samesite="lax",
            path=path,
            max_age=max(0, int((session.expires_at - datetime.now(UTC)).total_seconds())),
        )
        return response

    @router.get("/reports/v1/native/download/{raw_grant}/{artifact}", include_in_schema=False)
    async def download_native_fallback(raw_grant: str, artifact: Literal["word", "pdf", "xlsx", "pptx"]):
        try:
            _, session = await grants.exchange(raw_grant)
            content, media = await editor.download(session, artifact)
        except ReportingError as error:
            raise _error(error) from None
        suffix = "docx" if artifact == "word" else artifact
        return Response(
            content,
            media_type=media,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'attachment; filename="report.{suffix}"',
            },
        )

    @router.get("/reports/v1/native/artifacts/{raw_grant}/{artifact}", include_in_schema=False)
    async def download_native_artifact(raw_grant: str, artifact: Literal["word", "pdf", "xlsx", "pptx"]):
        if download_service is None:
            raise HTTPException(status_code=503, detail={"code": "native_download_unavailable"})
        try:
            grant = await download_service.grants.lookup(raw_grant)
            if not grant.scope.workflow_run_id.startswith("native:"):
                raise ReportingError("native_permission_denied", "下载授权不是原生文档。")
            scope = NativeScope(
                database=grant.scope.database,
                companyId=grant.scope.company_id,
                userId=grant.scope.user_id,
                threadId=grant.scope.session_id,
            )
            key = bind_native_workspace(editor.workspace, scope)
            document_id = grant.scope.workflow_run_id.removeprefix("native:")
            if (
                not grant.scope.workflow_run_id.startswith("native:")
                or grant.report_id != f"native:{document_id}:r{grant.revision}"
                or grant.scope.thread_id != key
            ):
                raise ReportingError("native_permission_denied", "下载作用域与原生文档不一致。")
            grant, stream = await download_service.stream(raw_grant, artifact=artifact)
        except ReportingError as error:
            raise _error(error) from None
        except ValidationError:
            raise HTTPException(
                status_code=403, detail={"code": "native_permission_denied"}
            ) from None
        suffix = "docx" if artifact == "word" else artifact
        return StreamingResponse(
            stream,
            media_type=NATIVE_ARTIFACT_MEDIA[artifact],
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'attachment; filename="report.{suffix}"',
            },
        )

    @router.get("/reports/v1/native/{document_id}/{revision}", include_in_schema=False)
    async def native_page(document_id: str, revision: int, request: Request):
        await session_context(request, document_id, revision)
        page = root / "native.html"
        if page.is_file():
            return FileResponse(
                page, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
            )
        # 在浏览器组件接入前如实展示已登记状态，不伪称已有完整编辑界面。
        return HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>原生文档</title><p>原生文件已登记，编辑界面尚未部署。</p></html>',
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    @router.get("/reports/v1/native/{document_id}/{revision}/api/context")
    async def native_context(document_id: str, revision: int, request: Request):
        session, context = await session_context(request, document_id, revision)
        return {
            "context": context.model_dump(mode="json", by_alias=True),
            "csrfToken": grants.csrf_token(request.cookies.get(NATIVE_SESSION_COOKIE, "")),
            "capabilities": session.capabilities,
            "aiEnabled": ai_enabled and (
                context.format == "docx" and editor.docx_enabled
                or context.format == "pdf" and editor.pdf_enabled and editor.pdf_text_enabled
                or context.format in {"pptx", "xlsx"} and editor.office_enabled
            ),
            "pdfReadAIEnabled": ai_enabled and context.format == "pdf",
            "wordReadAIEnabled": ai_enabled and context.format == "docx",
            "officeReadAIEnabled": ai_enabled and context.format in {"xlsx", "pptx"},
            "pdfFormAIEnabled": ai_enabled and context.format == "pdf" and editor.pdf_enabled,
            "pdfReviewAIEnabled": ai_enabled and context.format == "pdf" and editor.pdf_enabled and editor.pdf_text_enabled,
            "editingEnabled": editor.is_enabled(context.format),
            "pdfTextEnabled": editor.pdf_text_enabled and editor.pdf_enabled and context.format == "pdf",
        }

    @router.get("/reports/v1/native/{document_id}/{revision}/api/file")
    async def native_file(document_id: str, revision: int, request: Request):
        _, context = await session_context(request, document_id, revision)
        try:
            content = await editor.read_file(context)
        except ReportingError as error:
            raise _error(error) from None
        return Response(
            content,
            media_type=context.source_file.media_type,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/reports/v1/native/{document_id}/{revision}/api/read-model")
    async def native_read_model(document_id: str, revision: int, request: Request):
        _, context = await session_context(request, document_id, revision)
        try:
            if context.format != "docx":
                raise ReportingError("native_format_invalid", "只读内容模型仅支持 Word。")
            content = await editor.read_file(context)
            model = await run_office_engine(inspect_docx, content)
            return {"sourceSha256": context.source_file.sha256, "model": model}
        except ReportingError as error:
            raise _error(error) from None

    @router.post("/reports/v1/native/{document_id}/{revision}/api/preview")
    async def native_preview(
        document_id: str, revision: int, request: Request, payload: NativePreviewPayload
    ):
        _, context = await session_context(request, document_id, revision, write=True)
        try:
            return await editor.preview(
                context, expected_sha256=payload.expected_sha256, operations=payload.operations
            )
        except ReportingError as error:
            raise _error(error) from None

    @router.post("/reports/v1/native/{document_id}/{revision}/api/render-tree")
    async def native_render_tree(document_id: str, revision: int, request: Request, payload: NativePreviewPayload):
        _, context = await session_context(request, document_id, revision, write=True)
        try:
            return await editor.render_tree(context, expected_sha256=payload.expected_sha256, operations=payload.operations)
        except ReportingError as error:
            raise _error(error) from None

    @router.post("/reports/v1/native/{document_id}/{revision}/api/preview.pdf")
    async def native_preview_pdf(document_id: str, revision: int, request: Request, payload: NativePreviewPayload):
        _, context = await session_context(request, document_id, revision, write=True)
        try:
            receipt = await editor.preview_file(context, expected_sha256=payload.expected_sha256,
                operations=payload.operations, expected_preview_digest=payload.expected_preview_digest)
        except ReportingError as error:
            raise _error(error) from None
        return Response(receipt["content"], media_type="application/pdf", headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            **({"X-Native-Preview-Digest": receipt["previewDigest"]} if "previewDigest" in receipt else {}),
        })

    @router.get("/reports/v1/native/{document_id}/{revision}/api/preview.pdf")
    async def native_original_preview_pdf(document_id: str, revision: int, request: Request):
        _, context = await session_context(request, document_id, revision)
        if context.format != "pptx":
            raise HTTPException(422, detail={"code": "native_format_invalid"})
        try:
            receipt = await editor.preview_file(context, expected_sha256=context.source_file.sha256, operations=[])
        except ReportingError as error:
            raise _error(error) from None
        return Response(receipt["content"], media_type="application/pdf", headers={"Cache-Control":"no-store"})

    async def save(request, document_id, revision, payload, export_pdf):
        _, context = await session_context(request, document_id, revision, write=True)
        try:
            return await editor.save(
                context,
                request_id=payload.request_id,
                expected_sha256=payload.expected_sha256,
                operations=payload.operations,
                export_pdf=export_pdf,
                note=payload.note,
                **({"confirmed_preview_digest": payload.confirmed_preview_digest} if payload.confirmed_preview_digest is not None else {}),
            )
        except ReportingError as error:
            raise _error(error) from None

    @router.post("/reports/v1/native/{document_id}/{revision}/api/extract-pages")
    async def native_extract_pages(document_id: str, revision: int, request: Request, payload: NativeExtractPayload):
        _, context = await session_context(request, document_id, revision, write=True)
        try:
            if payload.expected_sha256 != context.source_file.sha256:
                raise ReportingError("native_source_changed", "PDF 来源已变化，请重新打开。")
            return await editor.extract_pages(context, pages=payload.pages, request_id=payload.request_id)
        except ReportingError as error:
            raise _error(error) from None

    @router.post('/reports/v1/native/{document_id}/{revision}/api/external-pages')
    async def native_external_pages(document_id: str,revision: int,request: Request,payload: NativeExternalPagesPayload):
        from .native_pdf_external_pages import external_pages

        _,context=await session_context(request,document_id,revision,write=True)
        try:
            return await external_pages(editor,context,action=payload.action,request_id=payload.request_id,
                expected_sha256=payload.expected_sha256,external_sha256=payload.external_sha256,
                bytes_base64=payload.bytes_base64,after_page=payload.after_page,pages=payload.pages)
        except ReportingError as error:
            raise _error(error) from None

    @router.post('/reports/v1/native/{document_id}/{revision}/api/protect-pdf')
    async def native_protect_pdf(document_id: str,revision: int,request: Request,payload: NativePdfProtectionPayload):
        from .native_pdf_protection import protect_pdf

        _,context=await session_context(request,document_id,revision,write=True)
        try:
            return await protect_pdf(editor,context,request_id=payload.request_id,
                expected_sha256=payload.expected_sha256,user_password=payload.user_password.get_secret_value(),
                owner_password=payload.owner_password.get_secret_value(),permissions=payload.permissions.model_dump())
        except ReportingError as error:
            raise _error(error) from None

    @router.post('/reports/v1/native/{document_id}/{revision}/api/export-images')
    async def native_export_pdf_images(document_id: str,revision: int,request: Request,payload: NativePdfImagesPayload):
        from .native_pdf_image_export import export_pdf_images

        _,context=await session_context(request,document_id,revision,write=True)
        try:
            receipt=await export_pdf_images(editor,context,expected_sha256=payload.expected_sha256,
                pages=payload.pages,image_format=payload.format,dpi=payload.dpi)
        except ReportingError as error:
            raise _error(error) from None
        return Response(receipt['content'],media_type=receipt['mediaType'],headers={
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'Content-Disposition':f'attachment; filename="{receipt["filename"]}"',
            'X-Native-Export-Sha256':receipt['sha256'],'X-Native-Export-Size':str(receipt['size']),
            'X-Native-Source-Sha256':receipt['sourceSha256'],
        })

    @router.post('/reports/v1/native/{document_id}/{revision}/api/convert-office')
    async def native_convert_pdf_office(document_id: str,revision: int,request: Request,payload: NativePdfConvertPayload):
        from .native_pdf_convert import convert_office

        _,context=await session_context(request,document_id,revision,write=True)
        try:
            return await convert_office(editor,context,expected_sha256=payload.expected_sha256,
                request_id=payload.request_id,output_format=payload.format)
        except ReportingError as error:
            raise _error(error) from None

    @router.post("/reports/v1/native/{document_id}/{revision}/api/save")
    async def native_save(
        document_id: str, revision: int, request: Request, payload: NativeSavePayload
    ):
        return await save(request, document_id, revision, payload, False)

    @router.post("/reports/v1/native/{document_id}/{revision}/api/export")
    async def native_export(
        document_id: str, revision: int, request: Request, payload: NativeSavePayload
    ):
        return await save(request, document_id, revision, payload, True)

    return router
