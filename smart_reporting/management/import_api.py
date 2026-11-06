from __future__ import annotations

import os

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .api import ManagementRoute, SESSION_COOKIE, csrf_token
from .data_sources.secrets import CredentialVault
from .importer import ConfigurationImporter
from .models import ManagementError, ManagementScope
from .scopes import ScopeService
from .settings import ManagementSettings


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope_database: str = Field(alias="scopeDatabase", min_length=1, max_length=128)
    company_id: str = Field(alias="companyId", min_length=1, max_length=128)
    directory: str = Field(min_length=1, max_length=4096)
    dry_run: bool = Field(alias="dryRun", default=True)


def create_import_router(scopes: ScopeService, vault: CredentialVault) -> APIRouter:
    router = APIRouter(route_class=ManagementRoute, tags=["management-import"])
    importer = ConfigurationImporter(scopes, vault)

    @router.post("/management/api/v1/config/import")
    async def import_config(request: Request, payload: ImportInput):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if not raw or request.headers.get("origin") != ManagementSettings.from_environment().public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if request.headers.get("x-csrf-token", "") != csrf_token(raw):
            raise ManagementError("management_csrf_invalid", "请求校验失败。", 403)
        return await importer.import_configuration(
            raw, ManagementScope(payload.scope_database, payload.company_id),
            payload.directory, payload.dry_run, os.environ,
        )

    return router
