from __future__ import annotations

import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from .auth import AdminAuthService
from .models import AdminAccount, AdminSessionInvalid, ManagementError, ManagementScope
from .repository import audit_events
from .scopes import ScopeService
from .settings import ManagementSettings

SESSION_COOKIE = "report_management_session"


def csrf_token(raw: str) -> str:
    return hmac.new(raw.encode(), b"report-management-csrf-v1", hashlib.sha256).hexdigest()


class ManagementRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                response = await original(request)
            except RequestValidationError as error:
                allowed = {"name", "database", "sourceId", "dsn", "username", "password", "newPassword", "currentPassword", "companyId", "scopeDatabase", "expectedVersion", "reportingProfileVersionId", "metadataVersionId"}
                fields = [{"field": str(item["loc"][-1]), "code": item["type"], "message": "请检查此字段的格式或长度。"}
                          for item in error.errors() if item.get("loc") and str(item["loc"][-1]) in allowed]
                response = JSONResponse(
                    {"code": "management_input_invalid", "message": "输入格式无效，请检查表单。", "fieldErrors": fields},
                    status_code=422,
                )
            except ManagementError as error:
                response = JSONResponse(
                    {"code": error.code, "message": error.message}, status_code=error.status
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


def create_protected_router(auth: AdminAuthService, tag: str) -> APIRouter:
    async def require_admin(request: Request):
        return await auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))

    return APIRouter(route_class=ManagementRoute, tags=[tag], dependencies=[Depends(require_admin)])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=128)
    password: str = Field(max_length=128)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(alias="currentPassword", max_length=128)
    new_password: str = Field(alias="newPassword", min_length=12, max_length=128)


class ScopeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)


def create_management_router(auth: AdminAuthService, settings: ManagementSettings, *, report_runtime=None) -> APIRouter:
    router = APIRouter(route_class=ManagementRoute, tags=["management"])

    async def require_admin(request: Request) -> AdminAccount:
        return await auth.authenticate(request.cookies.get(SESSION_COOKIE, ""))

    def require_origin(request: Request):
        if settings.public_origin is None:
            raise ManagementError("management_not_configured", "尚未配置管理公开地址。", 503)
        if request.headers.get("origin") != settings.public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)

    def require_csrf(request: Request):
        require_origin(request)
        raw = request.cookies.get(SESSION_COOKIE, "")
        if not raw or not hmac.compare_digest(
            request.headers.get("x-csrf-token", ""), csrf_token(raw)
        ):
            raise ManagementError("management_csrf_invalid", "请求校验失败，请刷新页面。", 403)

    @router.post("/management/api/v1/auth/login")
    async def login(request: Request, payload: LoginInput):
        require_origin(request)
        # 只使用 ASGI peer；反向代理来源解析应由受信任代理配置完成。
        address = request.client.host if request.client else "unknown"
        result = await auth.login(payload.username, payload.password, address)
        old = request.cookies.get(SESSION_COOKIE)
        if old:
            await auth.logout(old)
        response = JSONResponse({"username": "admin"})
        response.set_cookie(
            SESSION_COOKIE,
            result.raw_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/management",
            max_age=max(0, int((result.expires_at - auth.clock()).total_seconds())),
        )
        return response

    @router.post("/management/api/v1/auth/logout")
    async def logout(request: Request):
        require_origin(request)
        raw = request.cookies.get(SESSION_COOKIE, "")
        try:
            await auth.authenticate(raw)
        except AdminSessionInvalid:
            pass
        else:
            require_csrf(request)
        await auth.logout(raw)
        response = JSONResponse({"loggedOut": True})
        response.delete_cookie(
            SESSION_COOKIE,
            path="/management",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return response

    # 所有业务 API 共享认证依赖；新增资源路由挂载到该子 router。
    protected = APIRouter(route_class=ManagementRoute, dependencies=[Depends(require_admin)])

    @protected.get("/management/api/v1/me")
    async def me(request: Request):
        return {"username": "admin", "csrfToken": csrf_token(request.cookies[SESSION_COOKIE])}

    @protected.post("/management/api/v1/auth/password")
    async def password(request: Request, payload: PasswordInput):
        require_csrf(request)
        await auth.change_password(
            request.cookies[SESSION_COOKIE], payload.current_password, payload.new_password
        )
        response = JSONResponse({"changed": True})
        response.delete_cookie(
            SESSION_COOKIE,
            path="/management",
            secure=settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return response

    @protected.get("/management/api/v1/audit")
    async def audit(
        request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50, before: str | None = None
    ):
        async with auth.repository.transaction() as connection:
            await auth.repository.authenticate_in_transaction(
                connection, request.cookies[SESSION_COOKIE], auth.clock()
            )
            query = select(audit_events).order_by(
                audit_events.c.occurred_at.desc(), audit_events.c.id.desc()
            )
            if before is not None:
                # UUID 游标定位到同一稳定排序位置，避免时间相同记录被跳过。
                anchor = (
                    (
                        await connection.execute(
                            select(audit_events).where(audit_events.c.id == before)
                        )
                    )
                    .mappings()
                    .first()
                )
                if anchor is None:
                    raise ManagementError("management_cursor_invalid", "分页位置无效。")
                from sqlalchemy import tuple_

                query = query.where(
                    tuple_(audit_events.c.occurred_at, audit_events.c.id)
                    < tuple_(anchor["occurred_at"], anchor["id"])
                )
            rows = (await connection.execute(query.limit(limit + 1))).mappings().all()
        return {
            "items": jsonable_encoder([dict(row) for row in rows[:limit]]),
            "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
        }

    scopes = ScopeService(auth)

    @protected.get("/management/api/v1/scopes")
    async def list_scopes(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                          after: str | None = None):
        return await scopes.list(request.cookies[SESSION_COOKIE], limit, after)

    @protected.post("/management/api/v1/scopes", status_code=201)
    async def register_scope(request: Request, payload: ScopeInput):
        require_csrf(request)
        return await scopes.register(request.cookies[SESSION_COOKIE],
                                     ManagementScope(payload.database, payload.company_id), payload.name)

    router.include_router(protected)
    from .report_bases import ReportBasisService
    from .report_issue_reviews import ReportIssueReviewService
    from .report_issue_reviews_api import create_report_issue_reviews_router

    router.include_router(create_report_issue_reviews_router(
        ReportIssueReviewService(ReportBasisService(scopes)), settings, report_runtime=report_runtime,
    ))

    def page():
        path = settings.static_dir / "management.html" if settings.static_dir else None
        if path is None or not path.is_file():
            raise ManagementError("management_frontend_unavailable", "管理页面尚未构建。", 503)
        return FileResponse(path)

    @router.get("/management/login", include_in_schema=False)
    async def login_page():
        return page()

    @router.get("/management/assets/{asset_path:path}", include_in_schema=False)
    async def management_asset(asset_path: str):
        if settings.static_dir is None:
            raise HTTPException(status_code=404)
        root = (settings.static_dir / "assets").resolve()
        path = (root / asset_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)

    @router.get("/management", include_in_schema=False)
    @router.get("/management/", include_in_schema=False)
    async def management_index():
        return RedirectResponse("/management/sources", status_code=303)

    @router.get("/management/sources", include_in_schema=False)
    @router.get("/management/sources/new", include_in_schema=False)
    @router.get("/management/sources/{source_id}", include_in_schema=False)
    @router.get("/management/sources/{source_id}/view", include_in_schema=False)
    @router.get("/management/sources/{source_id}/edit", include_in_schema=False)
    @router.get("/management/organizations", include_in_schema=False)
    @router.get("/management/report-issues", include_in_schema=False)
    @router.get("/management/account/password", include_in_schema=False)
    async def management_page(request: Request):
        try:
            await require_admin(request)
        except AdminSessionInvalid:
            from urllib.parse import quote
            target = request.url.path + ("?" + request.url.query if request.url.query else "")
            return RedirectResponse("/management/login?returnTo=" + quote(target, safe=""), status_code=303)
        return page()

    return router
