"""业务原件管理HTTP入口；读取与写入均沿用管理会话和组织身份。"""

import hmac
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import Field, ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..http.request_limits import (
    MAX_BUSINESS_DOCUMENT_REQUEST_BYTES,
    RequestBodyLimitError,
    install_streaming_body_limit,
)
from ..reporting.business_knowledge.ingestion import MAX_DOCUMENT_BYTES
from ..reporting.business_knowledge.models import BusinessDocumentInput
from ..reporting.semantics.models import Identity, SemanticModel
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .business_documents import BusinessDocumentService
from .models import ManagementError, ManagementScope
from .settings import ManagementSettings


class DocumentUploadForm(SemanticModel):
    scope_database: str = Field(min_length=1, max_length=128)
    company_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=0)
    request_id: Identity
    metadata: str = Field(min_length=1, max_length=60000)


class DocumentReviewInput(SemanticModel):
    scope_database: str = Field(min_length=1, max_length=128)
    company_id: str = Field(min_length=1, max_length=128)
    expected_version: int = Field(ge=1, strict=True)
    decision: Literal["approved", "rejected", "revoked"]
    reason: str = Field(min_length=1, max_length=4000)


class IngestionRetryInput(SemanticModel):
    scope_database: str = Field(min_length=1, max_length=128)
    company_id: str = Field(min_length=1, max_length=128)
    expected_attempt: int = Field(ge=1, strict=True)


def create_business_documents_router(
    service: BusinessDocumentService, settings: ManagementSettings,
    *, notify: Callable[[], None] | None = None,
) -> APIRouter:
    router = create_protected_router(service.scopes.auth, "management-business-documents")

    def require_csrf(request: Request):
        raw = request.cookies.get(SESSION_COOKIE, "")
        if settings.public_origin is None or request.headers.get("origin") != settings.public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        if not raw or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
            raise ManagementError("management_csrf_invalid", "请求校验失败，请刷新后重试。", 403)

    @router.post("/management/api/v1/business-documents", status_code=201)
    async def upload(request: Request):
        require_csrf(request)
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
            raise ManagementError("management_document_invalid", "请使用文件上传表单。", 422)
        limit_state = None
        try:
            limit_state = install_streaming_body_limit(request, MAX_BUSINESS_DOCUMENT_REQUEST_BYTES)
            async with request.form(max_files=1, max_fields=5, max_part_size=60_000) as form:
                expected_fields = {"file", "scopeDatabase", "companyId", "expectedVersion", "requestId", "metadata"}
                if set(form) != expected_fields or len(form.multi_items()) != len(expected_fields):
                    raise ValueError("invalid_fields")
                file = form["file"]
                if not isinstance(file, UploadFile):
                    raise ValueError("invalid_file")
                payload = DocumentUploadForm.model_validate({key: value for key, value in form.items() if key != "file"})
                metadata = BusinessDocumentInput.model_validate_json(payload.metadata)
                content = await file.read(MAX_DOCUMENT_BYTES + 1)
                receipt = await service.register_document(
                    request.cookies[SESSION_COOKIE], ManagementScope(payload.scope_database, payload.company_id),
                    content, filename=file.filename or "", metadata=metadata,
                    request_id=payload.request_id, expected_version=payload.expected_version,
                )
        except RequestBodyLimitError as error:
            raise ManagementError("management_document_too_large", "上传请求超过允许大小。", 413) from error
        except StarletteHTTPException as error:
            if limit_state is not None and limit_state.error:
                raise ManagementError("management_document_too_large", "上传请求超过允许大小。", 413) from error
            raise ManagementError("management_document_invalid", "文件上传表单格式无效。", 422) from error
        except (ValueError, ValidationError) as error:
            raise ManagementError("management_document_invalid", "文件登记参数或类型无效。", 422) from error
        if notify is not None:
            notify()
        return receipt.model_dump(mode="json", by_alias=True)

    @router.get("/management/api/v1/business-documents")
    async def catalog(request: Request,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        q: Annotated[str, Query(max_length=200)] = '',
        kind: Literal['rule_evidence', 'background'] | None = None,
        review_status: Annotated[Literal['pending', 'approved', 'rejected', 'revoked'] | None, Query(alias='reviewStatus')] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ):
        return await service.list_documents(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id),
            query=q, kind=kind, review_status=review_status, limit=limit, after=after)

    @router.get("/management/api/v1/business-documents/{document_id}")
    async def document(
        request: Request, document_id: str,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
    ):
        return await service.get_document(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), document_id)

    @router.get("/management/api/v1/business-documents/{document_id}/revisions/{revision}/impact")
    async def revision_impact(request: Request, document_id: str,
        revision: Annotated[int, Field(ge=1)],
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=400)] = None,
    ):
        return await service.read_revision_impact(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id),
            document_id, revision, limit=limit, after=after)

    @router.get("/management/api/v1/business-documents/{document_id}/revisions/{revision}/ingestion-jobs")
    async def revision_jobs(request: Request, document_id: str,
        revision: Annotated[int, Field(ge=1)],
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ):
        return await service.list_revision_jobs(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id),
            document_id, revision, limit=limit, after=after)

    @router.get("/management/api/v1/business-documents/{document_id}/revisions/{revision}/original")
    async def original(
        request: Request, document_id: str, revision: int,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
    ):
        content = await service.read_original(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), document_id, revision)
        return Response(content, media_type="application/octet-stream", headers={
            "Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff",
        })

    @router.post("/management/api/v1/business-documents/{document_id}/revisions/{revision}/review")
    async def review(request: Request, document_id: str, revision: int, payload: DocumentReviewInput):
        require_csrf(request)
        return await service.review_revision(
            request.cookies[SESSION_COOKIE], ManagementScope(payload.scope_database, payload.company_id), document_id, revision,
            decision=payload.decision, reason=payload.reason, expected_version=payload.expected_version,
        )

    @router.get("/management/api/v1/business-document-requests/{request_id}")
    async def registration(request: Request,
        request_id: Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")],
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
    ):
        return await service.get_registration(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), request_id)

    @router.get("/management/api/v1/business-ingestion-jobs/{job_id}")
    async def job(
        request: Request, job_id: str,
        scope_database: Annotated[str, Query(alias="scopeDatabase", min_length=1, max_length=128)],
        company_id: Annotated[str, Query(alias="companyId", min_length=1, max_length=128)],
    ):
        receipt = await service.get_job(request.cookies[SESSION_COOKIE], ManagementScope(scope_database, company_id), job_id)
        return receipt.model_dump(mode="json", by_alias=True)

    @router.post("/management/api/v1/business-ingestion-jobs/{job_id}/retry")
    async def retry(request: Request, job_id: str, payload: IngestionRetryInput):
        require_csrf(request)
        receipt = await service.retry_job(
            request.cookies[SESSION_COOKIE], ManagementScope(payload.scope_database, payload.company_id),
            job_id, expected_attempt=payload.expected_attempt,
        )
        if notify is not None:
            notify()
        return receipt.model_dump(mode="json", by_alias=True)

    return router
