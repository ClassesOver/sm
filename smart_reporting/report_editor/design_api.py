"""报告设计、个人模板与临时成品预览路由。"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import Field

from ..reporting.contract import SHA256_PATTERN
from ..reporting.delivery.report_design import DesignModel, ReportDesign
from ..reporting.models import ReportingError
from .capabilities import EditorCapabilities


class DesignWritePayload(DesignModel):
    design: ReportDesign
    expected_design_sha256: str = Field(pattern=SHA256_PATTERN)


class DesignTemplatePayload(DesignModel):
    name: str = Field(min_length=1, max_length=100)
    design: ReportDesign


class DesignPreviewPayload(DesignModel):
    expected_sha256: str = Field(pattern=SHA256_PATTERN)
    expected_design_sha256: str = Field(pattern=SHA256_PATTERN)


def register_design_routes(router, *, grants, editor, allowed_origin):
    from .api import _editor_http_error, _read_session_context, _write_session_context

    base = "/reports/v1/editor/{report_id}/{revision}/api"

    async def context(request, report_id, revision, *, write=False, full=False):
        reader = _write_session_context if write else _read_session_context
        kwargs = {"allowed_origin": allowed_origin} if write else {}
        session, selected = await reader(grants, editor, request, report_id=report_id, revision=revision, **kwargs)
        if full and not EditorCapabilities.of(session.capabilities).full:
            raise HTTPException(status_code=403, detail={"code": "dataset_access_denied", "message": "分享会话不能修改报告设计或管理个人模板。"})
        return selected

    @router.get(base + "/design", include_in_schema=False)
    async def read_design(report_id: str, revision: int, request: Request) -> dict[str, Any]:
        selected = await context(request, report_id, revision)
        try:
            return await editor.design.read(selected)
        except ReportingError as error:
            _editor_http_error(error)

    @router.put(base + "/design", include_in_schema=False)
    async def save_design(report_id: str, revision: int, payload: DesignWritePayload, request: Request) -> dict[str, Any]:
        selected = await context(request, report_id, revision, write=True, full=True)
        try:
            return await editor.design.save(selected, payload.design, payload.expected_design_sha256)
        except ReportingError as error:
            _editor_http_error(error)

    @router.get(base + "/design-templates", include_in_schema=False)
    async def list_templates(report_id: str, revision: int, request: Request) -> dict[str, Any]:
        selected = await context(request, report_id, revision, full=True)
        if editor.design_templates is None:
            return {"items": []}
        return {"items": await editor.design_templates.list(selected.scope["userId"])}

    @router.put(base + "/design-templates/{template_id}", include_in_schema=False)
    async def save_template(report_id: str, revision: int, template_id: str, payload: DesignTemplatePayload, request: Request) -> dict[str, Any]:
        selected = await context(request, report_id, revision, write=True, full=True)
        if len(template_id) > 64 or not template_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(status_code=422, detail={"code": "report_editor_design_template_invalid"})
        if editor.design_templates is None:
            raise HTTPException(status_code=503, detail={"code": "report_editor_design_templates_unavailable"})
        return await editor.design_templates.save(selected.scope["userId"], template_id, payload.name.strip() or "未命名模板", payload.design)

    @router.delete(base + "/design-templates/{template_id}", include_in_schema=False)
    async def delete_template(report_id: str, revision: int, template_id: str, request: Request) -> dict[str, bool]:
        selected = await context(request, report_id, revision, write=True, full=True)
        if editor.design_templates is None:
            raise HTTPException(status_code=503, detail={"code": "report_editor_design_templates_unavailable"})
        return {"deleted": await editor.design_templates.delete(selected.scope["userId"], template_id)}

    @router.post(base + "/design-preview", status_code=202, include_in_schema=False)
    async def create_preview(report_id: str, revision: int, payload: DesignPreviewPayload, request: Request) -> dict[str, Any]:
        selected = await context(request, report_id, revision, write=True, full=True)
        try:
            return await editor.design_preview.start(selected, payload.expected_sha256, payload.expected_design_sha256)
        except ReportingError as error:
            _editor_http_error(error)

    @router.get(base + "/design-preview/{preview_id}", include_in_schema=False)
    async def preview_status(report_id: str, revision: int, preview_id: str, request: Request) -> dict[str, Any]:
        selected = await context(request, report_id, revision, full=True)
        try:
            return await editor.design_preview.status(selected, preview_id)
        except ReportingError as error:
            _editor_http_error(error)

    @router.get(base + "/design-preview/{preview_id}/pdf", include_in_schema=False)
    async def preview_pdf(report_id: str, revision: int, preview_id: str, request: Request) -> Response:
        selected = await context(request, report_id, revision, full=True)
        try:
            content = await editor.design_preview.pdf(selected, preview_id)
        except ReportingError as error:
            _editor_http_error(error)
        return Response(content, media_type="application/pdf", headers={"Cache-Control": "no-store", "Content-Disposition": 'inline; filename="report-preview.pdf"', "X-Content-Type-Options": "nosniff"})
