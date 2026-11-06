from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ..reporting.metadata import ReportingMetadataClient
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .catalog import CatalogService
from .data_sources.secrets import CredentialVault
from .models import ManagementError, ManagementScope
from .scopes import ScopeService
from .settings import ManagementSettings


class CatalogSyncInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_database: str = Field(alias="scopeDatabase", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    expected_draft_version: int = Field(alias="expectedDraftVersion", ge=1)


class CatalogPublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_database: str = Field(alias="scopeDatabase", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    revision: int = Field(ge=1)


def create_catalog_router(scopes: ScopeService, vault: CredentialVault | None = None,
                          metadata_client: ReportingMetadataClient | None = None) -> APIRouter:
    router = create_protected_router(scopes.auth, "management-catalog")
    service = CatalogService(scopes, vault=vault, metadata_client=metadata_client)

    def csrf(request: Request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if not raw or request.headers.get("origin") != ManagementSettings.from_environment().public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if request.headers.get("x-csrf-token", "") != csrf_token(raw):
            raise ManagementError("management_csrf_invalid", "请求校验失败。", 403)

    @router.post("/management/api/v1/sources/{source_id}/catalog/sync")
    async def sync(request: Request, source_id: str, payload: CatalogSyncInput):
        csrf(request)
        return await service.synchronize(request.cookies[SESSION_COOKIE],
                                  ManagementScope(payload.scope_database, payload.company_id),
                                  source_id, payload.expected_draft_version)

    @router.post("/management/api/v1/sources/{source_id}/catalog/publish")
    async def publish(request: Request, source_id: str, payload: CatalogPublishInput):
        csrf(request)
        return await service.publish(request.cookies[SESSION_COOKIE],
                                     ManagementScope(payload.scope_database, payload.company_id),
                                     source_id, payload.revision)

    return router
