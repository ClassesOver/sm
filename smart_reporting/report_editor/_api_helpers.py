"""编辑器 API 共用的请求校验；状态码与业务错误由调用方决定。"""

import secrets

from fastapi import HTTPException, Request

from ..reporting.models import ReportingError
from .service import ReportEditorGrantService


def reporting_http_error(error: ReportingError, *, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": error.code, "message": error.message}
    )


def reporting_editor_error(error: ReportingError) -> HTTPException:
    return reporting_http_error(
        error, status_code=403 if "permission_denied" in error.code else 409
    )


def require_editor_csrf(
    request: Request, grants: ReportEditorGrantService, *, session_cookie: str,
    csrf_cookie: str, error_code: str,
) -> None:
    token = grants.csrf_token(request.cookies.get(session_cookie, ""))
    if not secrets.compare_digest(request.headers.get("X-CSRF-Token", ""), token) or not secrets.compare_digest(
        request.cookies.get(csrf_cookie, ""), token
    ):
        raise HTTPException(status_code=403, detail={"code": error_code})


async def read_editor_json(
    request: Request, *, error_code: str, message: str | None = None,
) -> object:
    try:
        return await request.json()
    except ValueError:
        detail = {"code": error_code}
        if message is not None:
            detail["message"] = message
        raise HTTPException(status_code=400, detail=detail) from None
