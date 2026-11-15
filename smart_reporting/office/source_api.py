from typing import Literal

from fastapi import Depends, Request, Query
from pydantic import Field

from ..management.data_sources.api import SourceCreateInput, SourceSaveInput, PublishInput
from ..management.data_sources.models import SourceDraftInput
from ..management.data_sources.service import SourceService
from ..management.models import ManagementError
from ..management.table_access import TableAccessService
from ..management.table_access_api import TableAccessInput
from .api import COOKIE, Input
from .repository import OfficeError
from .source_management import OfficeSourceScopes
from .source_runtime import OfficeSourceRuntime
from ..reporting.models import ReportingError


class SourceGrant(Input):
    tables: list[str] = Field(max_length=10000)


class SourceQuery(Input):
    sql: str = Field(min_length=1, max_length=256 * 1024)


class MemberSourceLimit(Input):
    tables: list[str] | None = Field(max_length=10000)


def mount_source_routes(router, actor, office, vault, metadata_client=None):
    scopes = OfficeSourceScopes(office)
    service = SourceService(scopes, vault)
    table_access = TableAccessService(scopes, vault, metadata_client)
    runtime = OfficeSourceRuntime(office, vault)

    async def scope(identity):
        try:
            return await scopes.ensure_registered(identity)
        except ManagementError as error:
            raise OfficeError(error.code, error.message, error.status) from error
        except ReportingError as error:
            raise OfficeError(error.code, error.message, 422) from error

    async def run(method, *args, **kwargs):
        try:
            return await method(*args, **kwargs)
        except ManagementError as error:
            raise OfficeError(error.code, error.message, error.status) from error
        except ReportingError as error:
            raise OfficeError(error.code, error.message, 422) from error

    @router.get("/admin/data-sources")
    async def sources(request: Request, identity=Depends(actor),
                      q: str = Query(default="", max_length=100),
                      after: str | None = None,
                      limit: int = Query(default=50, ge=1, le=100)):
        return await run(service.list, request.cookies[COOKIE], await scope(identity), limit, after, q)

    @router.get("/admin/data-sources/{source}")
    async def detail(source: str, request: Request, identity=Depends(actor)):
        return await run(service.detail, request.cookies[COOKIE], await scope(identity), source)

    @router.post("/admin/data-sources", status_code=201)
    async def create(body: SourceCreateInput, request: Request, identity=Depends(actor)):
        draft = SourceDraftInput.model_validate(body.model_dump(by_alias=True, exclude={"source_id"}))
        return await run(service.create_draft, request.cookies[COOKIE], await scope(identity), body.source_id, draft)

    @router.put("/admin/data-sources/{source}/draft")
    async def save(source: str, body: SourceSaveInput, request: Request, identity=Depends(actor)):
        draft = SourceDraftInput.model_validate(body.model_dump(
            by_alias=True, exclude={"expected_version"}, exclude_unset=True))
        return await run(service.save_draft, request.cookies[COOKIE], await scope(identity),
                         source, draft, body.expected_version)

    @router.get("/admin/data-sources/{source}/release-check")
    async def release_check(source: str, request: Request, expectedVersion: int = Query(ge=1),
                            identity=Depends(actor)):
        return await run(service.release_check, request.cookies[COOKIE], await scope(identity), source, expectedVersion)

    @router.post("/admin/data-sources/{source}/publish")
    async def publish(source: str, body: PublishInput, request: Request, identity=Depends(actor)):
        return await run(service.publish, request.cookies[COOKIE], await scope(identity), source, body.expected_version)

    @router.post("/admin/data-sources/{source}/table-discoveries")
    async def discover(source: str, body: PublishInput, request: Request, identity=Depends(actor)):
        return await run(table_access.discover, request.cookies[COOKIE], await scope(identity), source, body.expected_version)

    @router.get("/admin/data-sources/{source}/table-access")
    async def access(source: str, request: Request, identity=Depends(actor)):
        return await run(table_access.access, request.cookies[COOKIE], await scope(identity), source)

    @router.put("/admin/data-sources/{source}/table-access")
    async def save_access(source: str, body: TableAccessInput, request: Request, identity=Depends(actor)):
        return await run(table_access.save, request.cookies[COOKIE], await scope(identity), source,
                         body.expected_draft_version, body.discovery_id,
                         [(table.database, table.name) for table in body.selected_tables])

    @router.get("/admin/data-sources/{source}/table-discoveries/{discovery}/tables")
    async def tables(source: str, discovery: str, request: Request, identity=Depends(actor),
                     q: str = Query(default="", max_length=100),
                     kind: Literal["all", "table", "view"] = "all",
                     offset: int = Query(default=0, ge=0),
                     limit: int = Query(default=50, ge=1, le=100)):
        return await run(table_access.tables, request.cookies[COOKIE], await scope(identity),
                         source, discovery, q=q, kind=kind, offset=offset, limit=limit)

    @router.put("/admin/workspaces/{space}/data-sources/{source}")
    async def grant(space: str, source: str, body: SourceGrant, request: Request, identity=Depends(actor)):
        if body.tables:
            managed_scope = await scope(identity)
            # New grants must belong to the current published catalog. An empty
            # grant can always revoke existing access, even after retirement.
            await run(service.detail, request.cookies[COOKIE], managed_scope, source)
            await runtime.authorize_grant(identity, source, body.tables)
        await office.grant_source(identity, space, source, body.tables)
        return {"updated": True}

    @router.get("/admin/workspaces/{space}/data-sources/{source}")
    async def read_grant(space: str, source: str, identity=Depends(actor)):
        return await office.source_grant(identity, space, source)

    @router.get("/workspaces/{space}/data-sources")
    async def available(space: str, identity=Depends(actor)):
        return {"items": await run(runtime.available, identity, space)}

    @router.post("/workspaces/{space}/data-sources/{source}/query")
    async def query(space: str, source: str, body: SourceQuery, identity=Depends(actor)):
        return await run(runtime.query, identity, space, source, body.sql)

    @router.put("/workspaces/{space}/data-sources/{source}/members/{user}")
    async def limit_member(space: str, source: str, user: str, body: MemberSourceLimit,
                           identity=Depends(actor)):
        await office.limit_source_member(identity, space, source, user, body.tables)
        return {"updated": True}

    @router.get("/workspaces/{space}/data-sources/{source}/members")
    async def read_limits(space: str, source: str, identity=Depends(actor)):
        return await office.source_member_limits(identity, space, source)
