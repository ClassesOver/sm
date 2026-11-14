"""系统配置及格式偏好草稿 API；应用入口随执行器接入单独开放。"""

from __future__ import annotations

import hmac
from typing import Annotated, Any, Literal

from fastapi import Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..preferences.models import FormatPreferences
from ..runtime.settings import AgentSettings
from ..runtime.system_configuration import system_application_status
from .api import SESSION_COOKIE, create_protected_router, csrf_token
from .configuration_catalog import configuration_inventory
from .format_preferences import FormatPreferenceService
from .models import ManagementError
from .settings import ManagementSettings
from .system_configuration import SystemConfigurationService

Kind = Literal["system", "preferences"]


class ExpectedVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(alias="expectedVersion", ge=1)


class ConfigurationDraftInput(ExpectedVersionInput):
    document: dict[str, Any]


class ConfigurationRestoreInput(ExpectedVersionInput):
    revision: int = Field(ge=1)


class PreferenceApplyInput(ExpectedVersionInput):
    expected_hash: str = Field(alias='expectedHash', pattern='^[0-9a-f]{64}$')
    expected_effective_revision: int = Field(alias='expectedEffectiveRevision', ge=0)
    approval_id: str = Field(alias='approvalId', pattern='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
    expected_approval_hash: str = Field(alias='expectedApprovalHash', pattern='^[0-9a-f]{64}$')


class CredentialReplacementInput(ExpectedVersionInput):
    secret: str = Field(min_length=1, max_length=8192, repr=False)


def create_configuration_router(auth, management: ManagementSettings, startup: AgentSettings, *, system_configuration_state=None):
    router = create_protected_router(auth, "management-configuration")
    services = {
        "system": SystemConfigurationService(auth, startup),
        "preferences": FormatPreferenceService(auth, FormatPreferences.from_delivery(startup.report_delivery_settings)),
    }

    def require_csrf(request):
        if management.public_origin is None or request.headers.get("origin") != management.public_origin:
            raise ManagementError("management_origin_invalid", "请求来源无效。", 403)
        raw = request.cookies.get(SESSION_COOKIE, "")
        if not raw or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(raw)):
            raise ManagementError("management_csrf_invalid", "请求校验失败，请刷新页面。", 403)

    @router.get("/management/api/v1/configuration/system/catalog")
    async def catalog():
        items = configuration_inventory(startup)
        for item in items:
            if system_configuration_state and item["key"] in system_configuration_state.managed_keys:
                item["source"] = "management"
            item["editable"] = system_configuration_state is not None and item["activation"] == "restart" and not item["sensitive"]
        return {"items": items}

    @router.get("/management/api/v1/configuration/{kind}")
    async def detail(request: Request, kind: Kind):
        payload = await services[kind].detail(request.cookies[SESSION_COOKIE])
        if kind == "system":
            return {**payload, "application": system_application_status(system_configuration_state, payload["effective"])}
        return {**payload, "application": {"canApply": False,
            "reason": "先保存草稿并在实际报告验收中汇总全部要求；取得本草稿的完整批准后再单独确认应用。"}}

    if system_configuration_state is not None:
        @router.post("/management/api/v1/configuration/system/apply")
        async def apply_system(request: Request, payload: ExpectedVersionInput):
            require_csrf(request)
            published = await services["system"].publish(request.cookies[SESSION_COOKIE], payload.expected_version)
            return {"revision": published["revision"], "contentHash": published["contentHash"],
                **system_application_status(system_configuration_state, published)}

    @router.post('/management/api/v1/configuration/preferences/apply')
    async def apply_preferences(request: Request, payload: PreferenceApplyInput):
        require_csrf(request)
        approval = getattr(request.app.state, 'preference_approval', None)
        if approval is None:
            raise ManagementError('management_preference_approval_unavailable', '偏好批准服务尚未就绪。', 503)
        return await approval.preferences.apply_approved(request.cookies[SESSION_COOKIE],
            expected_version=payload.expected_version, expected_hash=payload.expected_hash,
            expected_effective_revision=payload.expected_effective_revision,
            approval_id=payload.approval_id, expected_approval_hash=payload.expected_approval_hash)

    @router.put("/management/api/v1/configuration/{kind}/draft")
    async def save(request: Request, kind: Kind, payload: ConfigurationDraftInput):
        require_csrf(request)
        return await services[kind].save_draft(request.cookies[SESSION_COOKIE], payload.document, payload.expected_version)

    @router.put('/management/api/v1/configuration/system/credentials/{key}')
    async def replace_credential(request: Request, key: Literal['OPENAI_API_KEY', 'AGENT_REPORT_METADATA_TOKEN'], payload: CredentialReplacementInput):
        require_csrf(request)
        return await services['system'].replace_credential(request.cookies[SESSION_COOKIE], key, payload.secret, payload.expected_version)

    @router.post("/management/api/v1/configuration/{kind}/draft/reset")
    async def reset(request: Request, kind: Kind, payload: ExpectedVersionInput):
        require_csrf(request)
        return await services[kind].reset_draft(request.cookies[SESSION_COOKIE], payload.expected_version)

    @router.post("/management/api/v1/configuration/{kind}/draft/restore")
    async def restore(request: Request, kind: Kind, payload: ConfigurationRestoreInput):
        require_csrf(request)
        return await services[kind].restore_draft(request.cookies[SESSION_COOKIE], payload.revision, payload.expected_version)

    @router.get("/management/api/v1/configuration/{kind}/versions")
    async def history(request: Request, kind: Kind,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        before: Annotated[int | None, Query(ge=1)] = None):
        return await services[kind].history(request.cookies[SESSION_COOKIE], before=before, limit=limit)

    @router.get("/management/api/v1/configuration/{kind}/versions/{revision}")
    async def version(request: Request, kind: Kind, revision: int):
        return await services[kind].version(request.cookies[SESSION_COOKIE], revision)

    return router
