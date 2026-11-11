"""已审核证据集合的显式发布、结果读回和检索预览。"""

import hmac
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import Field

from ..reporting.business_knowledge.retrieval import DocumentRevisionRef, EvidenceQuery
from ..reporting.semantics.models import Identity, SemanticModel
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .business_evidence import BusinessEvidenceService
from .models import ManagementError, ManagementScope
from .settings import ManagementSettings


class EvidenceScopeInput(SemanticModel):
    scope_database: str = Field(min_length=1, max_length=128)
    company_id: str = Field(min_length=1, max_length=128)


class EvidencePublishInput(EvidenceScopeInput):
    request_id: Identity
    kind: Literal["rule_evidence", "background"]
    revision_ids: tuple[DocumentRevisionRef, ...] = Field(min_length=1, max_length=200)


class EvidencePreviewInput(EvidenceQuery, EvidenceScopeInput):
    pass


def create_business_evidence_router(service: BusinessEvidenceService, settings: ManagementSettings) -> APIRouter:
    router = create_protected_router(service.scopes.auth, "management-business-evidence")

    def require_csrf(request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if settings.public_origin is None or request.headers.get("origin") != settings.public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if not raw or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
            raise ManagementError("management_csrf_invalid", "请求校验失败，请刷新后重试。", 403)

    @router.post("/management/api/v1/business-evidence-releases", status_code=201)
    async def publish(request: Request, payload: EvidencePublishInput):
        require_csrf(request)
        release = await service.publish(request.cookies[SESSION_COOKIE], ManagementScope(payload.scope_database, payload.company_id),
            request_id=payload.request_id, kind=payload.kind, revision_ids=payload.revision_ids)
        return release.model_dump(mode="json", by_alias=True)

    @router.get("/management/api/v1/business-evidence-releases")
    async def by_request(request: Request,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        request_id: Annotated[str, Query(alias="requestId", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")],
    ):
        release = await service.get_by_request(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), request_id)
        return release.model_dump(mode="json", by_alias=True)

    @router.get("/management/api/v1/business-evidence-releases/catalog")
    async def catalog(request: Request,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        kind: Literal['rule_evidence', 'background'] | None = None,
        q: Annotated[str, Query(max_length=200)] = '',
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ):
        return await service.list_releases(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id),
            kind=kind, query=q, limit=limit, after=after)

    @router.get("/management/api/v1/business-evidence-releases/{release_id}")
    async def detail(request: Request, release_id: str,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
    ):
        release = await service.get(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), release_id)
        return release.model_dump(mode="json", by_alias=True)

    @router.post("/management/api/v1/business-evidence-releases/{release_id}/search-preview")
    async def preview(request: Request, release_id: str, payload: EvidencePreviewInput):
        require_csrf(request)
        result = await service.search_preview(request.cookies[SESSION_COOKIE], ManagementScope(payload.scope_database, payload.company_id),
            release_id, **payload.model_dump(exclude={"scope_database", "company_id"}))
        return result.model_dump(mode="json", by_alias=True)

    return router
