"""上传入口仅使用已验签 workspace 身份，不借用编辑 grant 或客户端身份字段。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..http.request_limits import (
    MAX_AGENT_RUN_FILE_BYTES,
    MAX_NATIVE_IMPORT_REQUEST_BYTES,
    RequestBodyLimitError,
    install_streaming_body_limit,
)
from ..http.security import CapabilityClaims
from ..reporting.models import ReportingError
from .native_models import NativeScope

MAX_NATIVE_UPLOAD_BYTES = MAX_AGENT_RUN_FILE_BYTES


def create_native_import_router(importer: Any, *, enabled: bool = False) -> APIRouter:
    router = APIRouter()

    @router.post("/reports/v1/native/import")
    async def import_native_file(request: Request):
        claims = getattr(request.state, "capability", None)
        if not isinstance(claims, CapabilityClaims):
            raise HTTPException(403, detail={"code": "native_import_identity_required"})
        if not enabled:
            raise HTTPException(503, detail={"code": "native_import_disabled"})
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
            raise HTTPException(422, detail={"code": "native_import_multipart_required"})
        try:
            install_streaming_body_limit(request, MAX_NATIVE_IMPORT_REQUEST_BYTES)
            async with request.form(max_files=1, max_fields=1, max_part_size=1024) as form:
                if len(form.multi_items()) != 2 or set(form) != {"file", "requestId"}:
                    raise HTTPException(422, detail={"code": "native_import_fields_invalid"})
                upload, request_id = form["file"], form["requestId"]
                if (
                    not isinstance(upload, UploadFile)
                    or not isinstance(request_id, str)
                    or not request_id.strip()
                    or len(request_id) > 256
                ):
                    raise HTTPException(422, detail={"code": "native_import_fields_invalid"})
                content = bytearray()
                while chunk := await upload.read(64 * 1024):
                    if len(content) + len(chunk) > MAX_NATIVE_UPLOAD_BYTES:
                        raise HTTPException(413, detail={"code": "native_file_too_large"})
                    content.extend(chunk)
                scope = NativeScope(
                    database=claims.database,
                    companyId=str(claims.company),
                    userId=str(claims.user),
                    threadId=claims.thread,
                )
                return await importer.import_file(
                    scope=scope, content=bytes(content), request_id=request_id,
                    filename=upload.filename or "",
                )
        except RequestBodyLimitError:
            raise HTTPException(413, detail={"code": "native_file_too_large"}) from None
        except ReportingError as error:
            status = 413 if error.code == "native_file_too_large" else 422
            if error.code in {"native_engine_unavailable", "native_feature_disabled"}:
                status = 503
            elif error.code in {"native_source_changed", "native_import_source_changed", "native_revision_conflict"}:
                status = 409
            raise HTTPException(status, detail={"code": error.code, "message": error.message}) from None
        except ValidationError:
            raise HTTPException(403, detail={"code": "native_import_identity_invalid"}) from None
        except StarletteHTTPException as error:
            if error.status_code == 400:
                raise HTTPException(422, detail={"code": "native_import_multipart_invalid"}) from None
            raise

    return router
