from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from ..api import SESSION_COOKIE, create_protected_router, csrf_token
from ..models import ManagementError, ManagementScope
from ..scopes import ScopeService
from ..settings import ManagementSettings
from .models import SourceDraftInput
from .secrets import CredentialVault
from .service import SourceService


class SourceCreateInput(SourceDraftInput):
    source_id: str = Field(alias='sourceId', min_length=1, max_length=64)
    database_scope: str = Field(alias='scopeDatabase', min_length=1, max_length=128)
    company_id: str = Field(alias='companyId', min_length=1, max_length=128)


class SourceSaveInput(SourceDraftInput):
    expected_version: int = Field(alias='expectedVersion', ge=1)
    scope_database: str = Field(alias='scopeDatabase', min_length=1, max_length=128)
    company_id: str = Field(alias='companyId', min_length=1, max_length=128)


class PublishInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(alias='expectedVersion', ge=1)
    scope_database: str = Field(alias='scopeDatabase', min_length=1, max_length=128)
    company_id: str = Field(alias='companyId', min_length=1, max_length=128)


def create_source_router(scopes: ScopeService, vault: CredentialVault) -> APIRouter:
    router = create_protected_router(scopes.auth, 'management-sources')
    service = SourceService(scopes, vault)

    def scope_from(payload):
        return ManagementScope(payload.scope_database if hasattr(payload, 'scope_database') else payload.database_scope,
                               payload.company_id)

    def csrf(request: Request):
        raw = request.cookies.get(SESSION_COOKIE, '')
        if not raw or request.headers.get('origin') != ManagementSettings.from_environment().public_origin:
            raise ManagementError('management_origin_invalid', '请求来源无效。', 403)
        if request.headers.get('x-csrf-token', '') != csrf_token(raw):
            raise ManagementError('management_csrf_invalid', '请求校验失败。', 403)

    @router.post('/management/api/v1/sources', status_code=201)
    async def create(request: Request, payload: SourceCreateInput):
        csrf(request)
        source_id = payload.source_id
        scope = scope_from(payload)
        draft = SourceDraftInput(name=payload.name, type=payload.source_type, database=payload.database, dsn=payload.dsn, reportingProfileVersionId=payload.profile_version_id, metadataVersionId=payload.metadata_version_id)
        return await service.create_draft(request.cookies[SESSION_COOKIE], scope, source_id, draft)

    @router.put('/management/api/v1/sources/{source_id}/draft')
    async def save(request: Request, source_id: str, payload: SourceSaveInput):
        csrf(request)
        scope = scope_from(payload)
        draft = SourceDraftInput(name=payload.name, type=payload.source_type, database=payload.database, dsn=payload.dsn, reportingProfileVersionId=payload.profile_version_id, metadataVersionId=payload.metadata_version_id)
        expected = payload.expected_version
        return await service.save_draft(request.cookies[SESSION_COOKIE], scope, source_id, draft, expected)

    @router.post('/management/api/v1/sources/{source_id}/publish')
    async def publish(request: Request, source_id: str, payload: PublishInput):
        csrf(request)
        return await service.publish(request.cookies[SESSION_COOKIE],
                                     ManagementScope(payload.scope_database, payload.company_id),
                                     source_id, payload.expected_version)

    return router
