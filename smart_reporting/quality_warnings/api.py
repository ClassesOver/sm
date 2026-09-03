from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from .models import TenantScope, WarningDisposition, WarningQuery
from .service import QualityWarningService


def create_quality_warning_router() -> APIRouter:
    """创建只读告警查询路由；租户边界只来自已验签 capability。"""

    router = APIRouter(tags=["quality-warnings"])

    @router.get("/quality-warnings")
    async def list_quality_warnings(
        request: Request,
        domain: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
        status: Annotated[str, Query(pattern="^(open|resolved)$")] = "open",
        rule_code: Annotated[
            str | None, Query(alias="ruleCode", min_length=1, max_length=128)
        ] = None,
        subject_type: Annotated[
            str | None, Query(alias="subjectType", min_length=1, max_length=128)
        ] = None,
        subject_id: Annotated[
            str | None, Query(alias="subjectId", min_length=1, max_length=128)
        ] = None,
        disposition: Annotated[WarningDisposition | None, Query()] = None,
        first_observed_after: Annotated[datetime | None, Query(alias="firstObservedAfter")] = None,
        last_observed_before: Annotated[datetime | None, Query(alias="lastObservedBefore")] = None,
        cursor: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
    ):
        tenant = _tenant_scope(request)
        service = _service(request)
        page = await service.list_warning_page(
            tenant=tenant,
            query=WarningQuery(
                domain=domain,
                status=cast(Literal["open", "resolved"], status),
                rule_code=rule_code,
                subject_type=subject_type,
                subject_id=subject_id,
                disposition=disposition,
                first_observed_after=first_observed_after,
                last_observed_before=last_observed_before,
                cursor=cursor,
                limit=limit,
            ),
        )
        return page

    @router.get("/quality-warnings/{warning_id}")
    async def get_quality_warning(request: Request, warning_id: UUID):
        tenant = _tenant_scope(request)
        record = await _service(request).get_warning(tenant=tenant, warning_id=warning_id)
        if record is None:
            raise HTTPException(status_code=404, detail="quality_warning_not_found")
        return record

    @router.get("/quality-warnings/{warning_id}/events")
    async def list_quality_warning_events(request: Request, warning_id: UUID):
        tenant = _tenant_scope(request)
        service = _service(request)
        if await service.get_warning(tenant=tenant, warning_id=warning_id) is None:
            raise HTTPException(status_code=404, detail="quality_warning_not_found")
        return {"records": await service.list_events(tenant=tenant, warning_id=warning_id)}

    return router


def _service(request: Request) -> QualityWarningService:
    context = getattr(request.app.state, "agentos_context", None)
    service = getattr(context, "quality_warning_service", None)
    if not isinstance(service, QualityWarningService) and not hasattr(service, "list_warning_page"):
        raise HTTPException(status_code=503, detail="quality_warning_service_unavailable")
    return cast(QualityWarningService, service)


def _tenant_scope(request: Request) -> TenantScope:
    capability = getattr(request.state, "capability", None)
    database = getattr(capability, "database", None)
    company = getattr(capability, "company", None)
    if not isinstance(database, str) or not database or not isinstance(company, int):
        raise HTTPException(status_code=401, detail="quality_warning_capability_required")
    return TenantScope(database_name=database, company_id=str(company))
