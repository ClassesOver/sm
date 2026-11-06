from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .models import ManagementError, ManagementScope
from .profiles import ProfileService
from .scopes import ScopeService
from .settings import ManagementSettings


class ProfilePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_database: str = Field(alias="scopeDatabase", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    profile: dict


class ProfileSavePayload(ProfilePayload):
    expected_version: int = Field(alias="expectedVersion", ge=0)


class ProfilePublishPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_database: str = Field(alias="scopeDatabase", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    expected_version: int = Field(alias="expectedVersion", ge=1)


def create_profile_router(scopes: ScopeService) -> APIRouter:
    router = create_protected_router(scopes.auth, "management-profiles")
    service = ProfileService(scopes)

    def require_csrf(request: Request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if not raw or request.headers.get("origin") != ManagementSettings.from_environment().public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if request.headers.get("x-csrf-token", "") != csrf_token(raw):
            raise ManagementError("management_csrf_invalid", "请求校验失败。", 403)

    @router.post("/management/api/v1/profiles/preview")
    async def preview(request: Request, payload: ProfilePayload):
        require_csrf(request)
        return await service.preview(
            request.cookies[SESSION_COOKIE],
            ManagementScope(payload.scope_database, payload.company_id),
            payload.profile,
        )

    @router.put("/management/api/v1/profiles/{profile_id}/draft")
    async def save(request: Request, profile_id: str, payload: ProfileSavePayload):
        require_csrf(request)
        if payload.profile.get("profileId") != profile_id:
            raise ManagementError("management_profile_invalid", "Profile 标识不一致。", 422)
        return await service.save_draft(
            request.cookies[SESSION_COOKIE],
            ManagementScope(payload.scope_database, payload.company_id),
            payload.profile,
            payload.expected_version,
        )

    @router.post("/management/api/v1/profiles/{profile_id}/publish")
    async def publish(request: Request, profile_id: str, payload: ProfilePublishPayload):
        require_csrf(request)
        return await service.publish(
            request.cookies[SESSION_COOKIE],
            ManagementScope(payload.scope_database, payload.company_id),
            profile_id,
            payload.expected_version,
        )

    return router
