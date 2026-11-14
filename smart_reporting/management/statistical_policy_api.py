"""统计口径与场景默认HTTP入口，沿用管理会话与CSRF。"""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field, model_validator

from ..reporting.semantics.models import (
    Identity,
    PolicyVersionRef,
    SemanticModel,
    StatisticalPolicy,
)
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .models import ManagementError, INSTANCE_SCOPE
from .settings import ManagementSettings
from .statistical_policies import StatisticalPolicyService

class PolicyDraftDefinition(StatisticalPolicy):
    scope_id: Literal["draft"] = "draft"
    revision: Literal[1] = 1

    @model_validator(mode="before")
    @classmethod
    def reject_server_fields(cls, value):
        if isinstance(value, dict) and {"scopeId", "scope_id", "revision"}.intersection(value):
            raise ValueError("配置归属与发布版本由服务端登记")
        return value

class PolicyScopeInput(SemanticModel):
    pass

class PolicyPreviewInput(PolicyScopeInput):
    definition: PolicyDraftDefinition

class PolicyDraftInput(PolicyPreviewInput):
    expected_version: int = Field(ge=0, strict=True)

class PolicyPublishInput(PolicyScopeInput):
    expected_version: int = Field(ge=1, strict=True)

class PolicyDefaultInput(PolicyScopeInput):
    expected_version: int = Field(ge=0, strict=True)
    policy_version: PolicyVersionRef
    background_release_id: Identity | None = None

class PolicyRetireInput(PolicyScopeInput):
    reason: str = Field(min_length=1, max_length=4000)
    replacement: PolicyVersionRef | None = None

def create_statistical_policy_router(service: StatisticalPolicyService, settings: ManagementSettings) -> APIRouter:
    router = create_protected_router(service.scopes.auth, "management-statistical-policies")

    def require_csrf(request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if settings.public_origin is None or request.headers.get("origin") != settings.public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if not raw or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
            raise ManagementError("management_csrf_invalid", "请求校验失败，请刷新后重试。", 403)

    def definition(policy_id, payload):
        if policy_id != payload.definition.id:
            raise ManagementError("management_policy_invalid", "请求与口径标识不一致。", 422)
        return payload.definition.model_dump(mode="json", by_alias=True, exclude={"scope_id", "revision"})

    @router.get("/management/api/v1/statistical-policies")
    async def listing(request: Request,
        limit: Annotated[int, Query(ge=1, le=100)] = 50, after: Annotated[str | None, Query(max_length=128)] = None,
    ):
        return await service.list(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE, limit=limit, after=after)

    @router.get("/management/api/v1/statistical-policies/{policy_id}")
    async def detail(request: Request, policy_id: str,
        revision: Annotated[int | None, Query(ge=1)] = None,
    ):
        return await service.get(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE, policy_id, revision=revision)

    @router.put("/management/api/v1/statistical-policies/{policy_id}/draft")
    async def save(request: Request, policy_id: str, payload: PolicyDraftInput):
        require_csrf(request)
        return await service.save_draft(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            definition(policy_id, payload), expected_version=payload.expected_version)

    @router.post("/management/api/v1/statistical-policies/{policy_id}/preview")
    async def preview(request: Request, policy_id: str, payload: PolicyPreviewInput):
        require_csrf(request)
        return await service.preview(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE, definition(policy_id, payload))

    @router.post("/management/api/v1/statistical-policies/{policy_id}/publish")
    async def publish(request: Request, policy_id: str, payload: PolicyPublishInput):
        require_csrf(request)
        return await service.publish(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            policy_id, expected_version=payload.expected_version)

    @router.get("/management/api/v1/report-policy-defaults/{scenario}")
    async def get_default(request: Request, scenario: str,
    ):
        return await service.get_default(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE, scenario)

    @router.put("/management/api/v1/report-policy-defaults/{scenario}")
    async def set_default(request: Request, scenario: str, payload: PolicyDefaultInput):
        require_csrf(request)
        return await service.set_default(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            scenario, policy_version=payload.policy_version, expected_version=payload.expected_version, background_release_id=payload.background_release_id)

    @router.post("/management/api/v1/statistical-policies/{policy_id}/versions/{revision}/retire")
    async def retire(request: Request, policy_id: str, revision: int, payload: PolicyRetireInput):
        require_csrf(request)
        return await service.retire(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            policy_id, revision, reason=payload.reason, replacement=payload.replacement)

    @router.get("/management/api/v1/statistical-policies/{policy_id}/impact")
    async def impact(request: Request, policy_id: str,
        revision: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=264)] = None,
    ):
        return await service.impact(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            policy_id, revision=revision, limit=limit, after=after)

    return router
