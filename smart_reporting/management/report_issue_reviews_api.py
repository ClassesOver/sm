"""管理会话仅能裁定问题；报告用户身份不能调用此写入口。"""

import hmac
from typing import Annotated, Literal

from fastapi import Path, Query, Request
from fastapi.responses import JSONResponse

from ..reporting.semantics.issue_approval import IssueBusinessApprovalRequest
from ..reporting.semantics.issue_regression import IssueRegressionRequest
from ..reporting.semantics.issue_resolution import IssueResolutionRequest
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .models import ManagementError, INSTANCE_SCOPE
from .report_issue_regression_checks import IssueRegressionCheckRequest
from .report_issue_resolution_evidence import IssueResolutionCheckRequest
from .report_issue_reviews import IssueDecision

class IssueDecisionInput(IssueDecision):
    pass

class IssueRegressionInput(IssueRegressionRequest):
    pass

class IssueRegressionCheckInput(IssueRegressionCheckRequest):
    pass

class IssueBusinessApprovalInput(IssueBusinessApprovalRequest):
    pass

class IssueResolutionCheckInput(IssueResolutionCheckRequest):
    pass

class IssueResolutionInput(IssueResolutionRequest):
    pass

def _resolution_public(receipt):
    from .business_documents import _digest

    result = receipt.model_dump(mode='json', by_alias=True)
    result['requestHash'] = _digest(result['request'])
    result['historicalResult'] = True
    return result

def _approval_public(receipt):
    from .business_documents import _digest

    result = receipt.model_dump(mode='json', by_alias=True)
    result['requestHash'] = _digest(result['request'])
    result['currentEvidenceStatus'] = 'not_checked'
    # 历史读回只供身份核对，不成为绕过原件撤销的原文缓存入口。
    for source in result['request']['sources']:
        source.pop('quote')
    return result

def create_report_issue_reviews_router(service, settings, *, report_runtime=None):
    router = create_protected_router(service.scopes.auth, 'management-report-issues')

    def require_csrf(request):
        raw = request.cookies[SESSION_COOKIE]
        if settings.public_origin is None or request.headers.get('origin') != settings.public_origin:
            raise ManagementError('management_origin_invalid', '请求来源无效。', 403)
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), csrf_token(raw)):
            raise ManagementError('management_csrf_invalid', '请求校验失败，请刷新后重试。', 403)
        return raw

    @router.get('/management/api/v1/report-issue-reviews')
    async def listing(request: Request,

        issue_id: Annotated[str | None, Query(alias='issueId', max_length=128)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
    ):
        result = await service.admin_list(request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            issue_id=issue_id, limit=limit, after=after)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.post('/management/api/v1/report-issue-reviews/{issue_id}/decision')
    async def decide(request: Request, issue_id: str, payload: IssueDecisionInput):
        raw = require_csrf(request)
        result = await service.decide(raw, INSTANCE_SCOPE, issue_id,
            payload.model_dump(mode='json', by_alias=True, exclude_unset=True))
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/fix-options')
    async def fix_options(request: Request, issue_id: str,

        asset_type: Annotated[Literal['metric', 'statistical_policy', 'document', 'evidence_release'], Query(alias='assetType')],
        q: Annotated[str, Query(max_length=128)] = '',
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=1024)] = None,
    ):
        from .report_issue_fix_options import list_fix_options

        result = await list_fix_options(service, request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            issue_id, asset_type=asset_type, query=q, limit=limit, after=after)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.post('/management/api/v1/report-issue-reviews/{issue_id}/regression-evidence-check')
    async def check_regressions(request: Request, issue_id: str, payload: IssueRegressionCheckInput):
        from .report_issue_regression_checks import check_regression_evidence

        result = await check_regression_evidence(service, require_csrf(request),
            INSTANCE_SCOPE, issue_id,
            payload.model_dump(mode='json', by_alias=True), runtime=report_runtime)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.post('/management/api/v1/report-issue-reviews/{issue_id}/resolution-evidence-check')
    async def check_resolution(request: Request, issue_id: str, payload: IssueResolutionCheckInput):
        from .report_issue_resolution_evidence import check_resolution_evidence

        result = await check_resolution_evidence(service, require_csrf(request),
            INSTANCE_SCOPE, issue_id,
            payload.model_dump(mode='json', by_alias=True), runtime=report_runtime)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.post('/management/api/v1/report-issue-reviews/{issue_id}/resolutions')
    async def resolve(request: Request, issue_id: str, payload: IssueResolutionInput):
        from .report_issue_resolutions import resolve_issue

        result = await resolve_issue(service, require_csrf(request),
            INSTANCE_SCOPE, issue_id,
            payload.model_dump(mode='json', by_alias=True), runtime=report_runtime)
        return JSONResponse(_resolution_public(result), headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/resolutions/{request_id}')
    async def read_resolved(request: Request, issue_id: str,
        request_id: Annotated[str, Path(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')],
    ):
        from .report_issue_resolutions import read_resolution

        result = await read_resolution(service, request.cookies[SESSION_COOKIE],
            INSTANCE_SCOPE, issue_id, request_id)
        if result is None:
            raise ManagementError('management_issue_resolution_not_found', '本问题未登记此关闭请求。', 404)
        return JSONResponse(_resolution_public(result), headers={'Cache-Control': 'no-store'})

    @router.post('/management/api/v1/report-issue-reviews/{issue_id}/business-approvals')
    async def approve_business_expectations(request: Request, issue_id: str, payload: IssueBusinessApprovalInput):
        from .report_issue_business_approvals import approve_expectations

        result = await approve_expectations(service, require_csrf(request),
            INSTANCE_SCOPE, issue_id,
            payload.model_dump(mode='json', by_alias=True), runtime=report_runtime)
        return JSONResponse(_approval_public(result), headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/approval-source-options')
    async def approval_sources(request: Request, issue_id: str,

        q: Annotated[str, Query(max_length=128)] = '',
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=1024)] = None,
    ):
        from .report_issue_approval_sources import list_approval_sources

        result = await list_approval_sources(service, request.cookies[SESSION_COOKIE],
            INSTANCE_SCOPE, issue_id, query=q, limit=limit, after=after)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/business-approvals/{request_id}')
    async def read_business_approval(request: Request, issue_id: str,
        request_id: Annotated[str, Path(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')],
    ):
        from .report_issue_business_approvals import read_approval

        result = await read_approval(service, request.cookies[SESSION_COOKIE],
            INSTANCE_SCOPE, issue_id, request_id)
        if result is None:
            raise ManagementError('management_issue_approval_not_found', '尚未登记此业务预期签认，请先核对原请求。', 404)
        return JSONResponse(_approval_public(result), headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/regression-targets')
    async def regression_targets(request: Request, issue_id: str,

        q: Annotated[str, Query(max_length=128)] = '',
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=1024)] = None,
    ):
        from .report_issue_regression_targets import list_regression_targets

        result = await list_regression_targets(service, request.cookies[SESSION_COOKIE], INSTANCE_SCOPE,
            issue_id, query=q, limit=limit, after=after)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.post('/management/api/v1/report-issue-reviews/{issue_id}/regressions')
    async def verify(request: Request, issue_id: str, payload: IssueRegressionInput):
        from .report_issue_regressions import verify_regression

        result = await verify_regression(service, require_csrf(request),
            INSTANCE_SCOPE, issue_id,
            payload.model_dump(mode='json', by_alias=True), runtime=report_runtime)
        return JSONResponse(result.model_dump(mode='json', by_alias=True), headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/regressions')
    async def verification_history(request: Request, issue_id: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        after: Annotated[str | None, Query(max_length=128)] = None,
        request_id: Annotated[str | None, Query(alias='requestId', min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_.:-]*$')] = None,
    ):
        from .report_issue_regressions import list_regressions

        result = await list_regressions(service, request.cookies[SESSION_COOKIE],
            INSTANCE_SCOPE, issue_id, limit=limit, after=after, request_id=request_id)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @router.get('/management/api/v1/report-issue-reviews/{issue_id}/regressions/{receipt_id}')
    async def read_verification(request: Request, issue_id: str, receipt_id: str,
    ):
        from .report_issue_regressions import read_regression

        result = await read_regression(service, request.cookies[SESSION_COOKIE],
            INSTANCE_SCOPE, issue_id, receipt_id)
        if result is None:
            raise ManagementError('management_issue_regression_not_found', '尚未登记该回归结果。', 404)
        return JSONResponse(result.model_dump(mode='json', by_alias=True), headers={'Cache-Control': 'no-store'})

    return router
