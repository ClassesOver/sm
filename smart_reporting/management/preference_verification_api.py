"""两个限定Cookie路径的偏好验收交接；请求不接收任何会话或会话摘要。"""

import hmac

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..report_editor.api import EDITOR_SESSION_COOKIE, _read_session_context, _write_session_context
from ..report_editor.capabilities import EditorCapabilities
from ..reporting.models import ReportingError
from .api import SESSION_COOKIE, ManagementRoute, create_protected_router, csrf_token
from .models import ManagementError


class VerificationDraftInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    expected_version: int = Field(alias='expectedVersion', ge=1)
    expected_hash: str = Field(alias='expectedHash', pattern='^[0-9a-f]{64}$')


class HandoffInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    handoff_token: str = Field(alias='handoffToken', min_length=32, max_length=128, pattern='^[A-Za-z0-9_-]+$')


class VerificationRunInput(VerificationDraftInput, HandoffInput):
    pass


class VerificationPrepareInput(VerificationDraftInput):
    evidence_ids: list[str] = Field(alias='evidenceIds', min_length=1, max_length=20)


def create_preference_verification_router(service, settings):
    from fastapi import APIRouter

    router = APIRouter(route_class=ManagementRoute)
    management = create_protected_router(service.auth, 'preference-report-verification')
    root = '/management/api/v1/configuration/preferences/report-verification'
    editor_path = '/reports/v1/editor/{report_id}/{revision}/api/preference-verification'

    def require_csrf(request):
        raw = request.cookies.get(SESSION_COOKIE, '')
        if (not settings.public_origin or request.headers.get('origin') != settings.public_origin
            or not raw or not hmac.compare_digest(request.headers.get('x-csrf-token', ''), csrf_token(raw))):
            raise ManagementError('management_csrf_invalid', '请求校验失败，请刷新页面。', 403)

    async def call(awaitable, *, editor_endpoint=False):
        try:
            return await awaitable
        except ReportingError as error:
            status = 401 if editor_endpoint and error.code in {'report_editor_session_invalid', 'report_editor_session_expired'} else 403
            raise ManagementError(error.code, error.message, status) from None

    @management.post(root)
    async def create(request: Request, payload: VerificationDraftInput):
        require_csrf(request)
        return await service.create(request.cookies[SESSION_COOKIE],
            expected_version=payload.expected_version, expected_hash=payload.expected_hash)

    @management.post(root + '/run')
    async def run(request: Request, payload: VerificationRunInput):
        require_csrf(request)
        return await call(service.run(request.cookies[SESSION_COOKIE], payload.handoff_token,
            expected_version=payload.expected_version, expected_hash=payload.expected_hash))

    @management.get(root + '/results/{id}')
    async def read_result(request: Request, id: str):
        return await call(service.evidence.read(request.cookies[SESSION_COOKIE], id))

    @management.get(root + '/results')
    async def list_results(request: Request, expectedVersion: int = Query(ge=1),
        expectedHash: str = Query(pattern='^[0-9a-f]{64}$')):
        return await call(service.evidence.list_for_draft(request.cookies[SESSION_COOKIE],
            expected_version=expectedVersion, expected_hash=expectedHash))

    @management.post(root + '/prepare')
    async def prepare(request: Request, payload: VerificationPrepareInput):
        require_csrf(request)
        return await call(service.evidence.prepare(request.cookies[SESSION_COOKIE],
            expected_version=payload.expected_version, expected_hash=payload.expected_hash,
            evidence_ids=payload.evidence_ids))

    @router.get(editor_path, include_in_schema=False)
    async def bootstrap(request: Request, report_id: str, revision: int):
        session, _ = await _read_session_context(service.bound.grants, service.bound.editor, request,
            report_id=report_id, revision=revision)
        if not EditorCapabilities.of(session.capabilities).full:
            raise ManagementError('management_preference_full_editor_required', '需要此修订的完整编辑权限。', 403)
        return {'csrfToken': service.bound.grants.csrf_token(request.cookies[EDITOR_SESSION_COOKIE])}

    @router.post(editor_path, include_in_schema=False)
    async def confirm(request: Request, report_id: str, revision: int, payload: HandoffInput):
        await _write_session_context(service.bound.grants, service.bound.editor, request,
            report_id=report_id, revision=revision, allowed_origin=settings.public_origin)
        return await call(service.confirm(payload.handoff_token, request.cookies[EDITOR_SESSION_COOKIE],
            report_id=report_id, revision=revision), editor_endpoint=True)

    router.include_router(management)
    return router
