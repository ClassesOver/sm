from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .catalog_api import CatalogSyncInput
from .models import ManagementError, ManagementScope
from .settings import ManagementSettings
from .table_access import TableAccessService


class TableIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    database: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")


class TableAccessInput(CatalogSyncInput):
    discovery_id: str = Field(alias="discoveryId", min_length=1, max_length=36)
    selected_tables: list[TableIdentity] = Field(alias="selectedTables", max_length=200)


def create_table_access_router(scopes, vault, metadata_client=None) -> APIRouter:
    router = create_protected_router(scopes.auth, "management-table-access")
    service = TableAccessService(scopes, vault, metadata_client)

    def csrf(request):
        token = request.cookies.get(SESSION_COOKIE, "")
        if request.headers.get("origin") != ManagementSettings.from_environment().public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if request.headers.get("x-csrf-token") != csrf_token(token):
            raise ManagementError("management_csrf_invalid", "请求校验失败。", 403)

    def scope(payload):
        return ManagementScope(payload.scope_database, payload.company_id)

    @router.post("/management/api/v1/sources/{source_id}/table-discoveries", status_code=201)
    async def discover(request: Request, source_id: str, payload: CatalogSyncInput):
        csrf(request)
        return await service.discover(
            request.cookies[SESSION_COOKIE],
            scope(payload),
            source_id,
            payload.expected_draft_version,
        )

    @router.get("/management/api/v1/sources/{source_id}/table-access")
    async def access(
        request: Request,
        source_id: str,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
    ):
        return await service.access(
            request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), source_id
        )

    @router.put("/management/api/v1/sources/{source_id}/table-access")
    async def save(request: Request, source_id: str, payload: TableAccessInput):
        csrf(request)
        return await service.save(
            request.cookies[SESSION_COOKIE],
            scope(payload),
            source_id,
            payload.expected_draft_version,
            payload.discovery_id,
            [(t.database, t.name) for t in payload.selected_tables],
        )

    @router.get("/management/api/v1/sources/{source_id}/table-discoveries/{discovery_id}/tables")
    async def tables(
        request: Request,
        source_id: str,
        discovery_id: str,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        q: Annotated[str, Query(max_length=100)] = "",
        kind: Literal["all", "table", "view"] = "all",
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        selected_only: Annotated[bool, Query(alias="selectedOnly")] = False,
    ):
        return await service.tables(
            request.cookies[SESSION_COOKIE],
            ManagementScope(scope_database, company_id),
            source_id,
            discovery_id,
            q=q,
            kind=kind,
            offset=offset,
            limit=limit,
            selected_only=selected_only,
        )

    @router.get("/management/api/v1/sources/{source_id}/table-discoveries/{discovery_id}/columns")
    async def columns(
        request: Request,
        source_id: str,
        discovery_id: str,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        database: Annotated[str, Query(min_length=1, max_length=128)],
        table: Annotated[str, Query(min_length=1, max_length=128)],
    ):
        return await service.columns(
            request.cookies[SESSION_COOKIE],
            ManagementScope(scope_database, company_id),
            source_id,
            discovery_id,
            database,
            table,
        )

    return router
