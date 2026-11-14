"""指标草稿与发布HTTP入口；不接受客户端登记组织身份或发布版本。"""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator

from ..reporting.semantics.models import MetricDefinition, MetricVersionRef, SemanticModel
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .metrics import MetricService
from .models import ManagementError, INSTANCE_SCOPE
from .settings import ManagementSettings

class MetricDraftDefinition(MetricDefinition):
    scope_id: Literal["draft"] = "draft"
    revision: Literal[1] = 1

    @model_validator(mode="before")
    @classmethod
    def reject_server_fields(cls, value):
        if isinstance(value, dict) and {"scopeId", "scope_id", "revision"}.intersection(value):
            raise ValueError("配置归属与发布版本由服务端登记")
        return value

class MetricWriteInput(SemanticModel):
    expected_version: int = Field(ge=0, strict=True)

class MetricDraftInput(MetricWriteInput):
    definition: MetricDraftDefinition

class MetricRetireInput(SemanticModel):
    reason: str = Field(min_length=1, max_length=4000)
    replacement: MetricVersionRef | None = None

def create_metrics_router(service: MetricService, settings: ManagementSettings) -> APIRouter:
    router = create_protected_router(service.scopes.auth, "management-metrics")

    def require_csrf(request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if settings.public_origin is None or request.headers.get("origin") != settings.public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if not raw or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
            raise ManagementError("management_csrf_invalid", "请求校验失败，请刷新后重试。", 403)

    @router.get("/management/api/v1/metric-field-catalog")
    async def field_catalog(request: Request,
        source_id: Annotated[str, Query(alias="sourceId", min_length=1, max_length=64)],
        source_revision: Annotated[int, Query(alias="sourceRevision", ge=1)],
        q: Annotated[str, Query(max_length=200)] = '',
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=520)] = None,
    ):
        return await service.field_catalog(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            source_id, source_revision, query=q, limit=limit, after=after)

    @router.get("/management/api/v1/metrics")
    async def listing(request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50, after: Annotated[str | None, Query(max_length=128)] = None,
    ):
        return await service.list(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE, limit=limit, after=after)

    @router.get("/management/api/v1/metrics/{metric_id}")
    async def detail(request: Request, metric_id: str,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ):
        return await service.get(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE, metric_id, revision=revision)

    @router.get("/management/api/v1/metrics/{metric_id}/impact")
    async def impact(request: Request, metric_id: str,
        revision: Annotated[int, Query(ge=1)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=300)] = None,
    ):
        return await service.impact(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            metric_id, revision=revision, limit=limit, after=after)

    @router.put("/management/api/v1/metrics/{metric_id}/draft")
    async def save(request: Request, metric_id: str, payload: MetricDraftInput):
        require_csrf(request)
        if metric_id != payload.definition.id:
            raise ManagementError("management_metric_invalid", "请求与指标标识不一致。", 422)
        return await service.save_draft(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            payload.definition.model_dump(mode="json", by_alias=True, exclude={"scope_id", "revision"}), payload.expected_version)

    @router.post("/management/api/v1/metrics/{metric_id}/publish")
    async def publish(request: Request, metric_id: str, payload: MetricWriteInput):
        require_csrf(request)
        return await service.publish(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            metric_id, expected_version=payload.expected_version)

    @router.post("/management/api/v1/metrics/{metric_id}/versions/{revision}/retire")
    async def retire(request: Request, metric_id: str, revision: int, payload: MetricRetireInput):
        require_csrf(request)
        return await service.retire(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            metric_id, revision, reason=payload.reason, replacement=payload.replacement)

    return router
