from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ..api import SESSION_COOKIE, create_protected_router, csrf_token
from ..models import ManagementError, ManagementScope
from ..scopes import ScopeService
from ..settings import ManagementSettings
from .models import SourceDraftInput
from .secrets import CredentialVault
from .service import SourceService


class SourceCreateInput(SourceDraftInput):
    dsn: SecretStr = Field(min_length=1, max_length=4096, repr=False)
    source_id: str = Field(alias='sourceId', min_length=1, max_length=64)
    database_scope: str = Field(alias='scopeDatabase', min_length=1, max_length=128)
    company_id: str = Field(alias='companyId', min_length=1, max_length=128)


class SourceSaveInput(SourceDraftInput):
    @model_validator(mode='after')
    def reject_explicit_null(self):
        if 'dsn' in self.model_fields_set and self.dsn is None:
            raise ValueError('连接地址不能为空。')
        return self

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

    @router.get('/management/api/v1/sources')
    async def list_sources(
        request: Request,
        scope_database: Annotated[str, Query(alias='scopeDatabase', min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias='companyId', min_length=1, max_length=128)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=64)] = None,
        q: Annotated[str, Query(max_length=100)] = '',
        publication_state: Annotated[Literal['all', 'unpublished', 'published', 'changed'], Query(alias='publicationState')] = 'all',
    ):
        return await service.list(request.cookies[SESSION_COOKIE],
                                  ManagementScope(scope_database, company_id), limit, after, q, publication_state)

    @router.get('/management/api/v1/sources/{source_id}')
    async def detail(request: Request, source_id: str,
                     scope_database: Annotated[str, Query(alias='scopeDatabase')],
                     company_id: Annotated[str, Query(alias='companyId')]):
        return await service.detail(request.cookies[SESSION_COOKIE],
                                    ManagementScope(scope_database, company_id), source_id)

    @router.get('/management/api/v1/sources/{source_id}/release-check')
    async def release_check(request: Request, source_id: str,
                            scope_database: Annotated[str, Query(alias='scopeDatabase')],
                            company_id: Annotated[str, Query(alias='companyId')],
                            expected_version: Annotated[int, Query(alias='expectedVersion', ge=1)]):
        return await service.release_check(request.cookies[SESSION_COOKIE],
            ManagementScope(scope_database, company_id), source_id, expected_version)

    @router.post('/management/api/v1/sources', status_code=201)
    async def create(request: Request, payload: SourceCreateInput):
        csrf(request)
        source_id = payload.source_id
        scope = scope_from(payload)
        draft = SourceDraftInput.model_validate(payload.model_dump(by_alias=True, exclude={'expected_version', 'scope_database', 'company_id', 'source_id', 'database_scope'}, exclude_unset=True))
        return await service.create_draft(request.cookies[SESSION_COOKIE], scope, source_id, draft)

    @router.put('/management/api/v1/sources/{source_id}/draft')
    async def save(request: Request, source_id: str, payload: SourceSaveInput):
        csrf(request)
        scope = scope_from(payload)
        draft = SourceDraftInput.model_validate(payload.model_dump(by_alias=True, exclude={'expected_version', 'scope_database', 'company_id', 'source_id', 'database_scope'}, exclude_unset=True))
        expected = payload.expected_version
        return await service.save_draft(request.cookies[SESSION_COOKIE], scope, source_id, draft, expected)

    @router.post('/management/api/v1/sources/{source_id}/publish')
    async def publish(request: Request, source_id: str, payload: PublishInput):
        csrf(request)
        return await service.publish(request.cookies[SESSION_COOKIE],
                                     ManagementScope(payload.scope_database, payload.company_id),
                                     source_id, payload.expected_version)

    return router
