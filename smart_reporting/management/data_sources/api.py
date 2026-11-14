from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from ..api import SESSION_COOKIE, create_protected_router, csrf_token
from ..models import INSTANCE_SCOPE, ManagementError
from ..scopes import ScopeService
from ..settings import ManagementSettings
from .models import SourceDraftInput
from .secrets import CredentialVault
from .service import SourceService


class SourceCreateInput(SourceDraftInput):
    dsn: SecretStr = Field(min_length=1, max_length=4096, repr=False)
    source_id: str = Field(alias='sourceId', min_length=1, max_length=64)


class SourceSaveInput(SourceDraftInput):
    @model_validator(mode='after')
    def reject_explicit_null(self):
        if 'dsn' in self.model_fields_set and self.dsn is None:
            raise ValueError('连接地址不能为空。')
        return self

    expected_version: int = Field(alias='expectedVersion', ge=1)


class PublishInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(alias='expectedVersion', ge=1)


def create_source_router(scopes: ScopeService, vault: CredentialVault) -> APIRouter:
    router = create_protected_router(scopes.auth, 'management-sources')
    service = SourceService(scopes, vault)

    def csrf(request: Request):
        raw = request.cookies.get(SESSION_COOKIE, '')
        if not raw or request.headers.get('origin') != ManagementSettings.from_environment().public_origin:
            raise ManagementError('management_origin_invalid', '请求来源无效。', 403)
        if request.headers.get('x-csrf-token', '') != csrf_token(raw):
            raise ManagementError('management_csrf_invalid', '请求校验失败。', 403)

    @router.get('/management/api/v1/sources')
    async def list_sources(
        request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=64)] = None,
        q: Annotated[str, Query(max_length=100)] = '',
        publication_state: Annotated[Literal['all', 'unpublished', 'published', 'changed'], Query(alias='publicationState')] = 'all',
    ):
        return await service.list(request.cookies[SESSION_COOKIE],
                                  INSTANCE_SCOPE, limit, after, q, publication_state)

    @router.get('/management/api/v1/sources/{source_id}')
    async def detail(request: Request, source_id: str):
        return await service.detail(request.cookies[SESSION_COOKIE],
                                    INSTANCE_SCOPE, source_id)

    @router.get('/management/api/v1/sources/{source_id}/release-check')
    async def release_check(request: Request, source_id: str,
                            expected_version: Annotated[int, Query(alias='expectedVersion', ge=1)]):
        return await service.release_check(request.cookies[SESSION_COOKIE],
            INSTANCE_SCOPE, source_id, expected_version)

    @router.post('/management/api/v1/sources', status_code=201)
    async def create(request: Request, payload: SourceCreateInput):
        csrf(request)
        source_id = payload.source_id
        scope = INSTANCE_SCOPE
        draft = SourceDraftInput.model_validate(payload.model_dump(by_alias=True, exclude={'expected_version', 'source_id'}, exclude_unset=True))
        return await service.create_draft(request.cookies[SESSION_COOKIE], scope, source_id, draft)

    @router.put('/management/api/v1/sources/{source_id}/draft')
    async def save(request: Request, source_id: str, payload: SourceSaveInput):
        csrf(request)
        scope = INSTANCE_SCOPE
        draft = SourceDraftInput.model_validate(payload.model_dump(by_alias=True, exclude={'expected_version', 'source_id'}, exclude_unset=True))
        expected = payload.expected_version
        return await service.save_draft(request.cookies[SESSION_COOKIE], scope, source_id, draft, expected)

    @router.post('/management/api/v1/sources/{source_id}/publish')
    async def publish(request: Request, source_id: str, payload: PublishInput):
        csrf(request)
        return await service.publish(request.cookies[SESSION_COOKIE],
                                     INSTANCE_SCOPE,
                                     source_id, payload.expected_version)

    return router
