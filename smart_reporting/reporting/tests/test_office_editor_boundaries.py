from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.report_editor.slides import ReportSlidesEditorService
from smart_reporting.report_editor.slides_api import create_report_slides_editor_router
from smart_reporting.report_editor.workbook import ReportWorkbookEditorService
from smart_reporting.report_editor.workbook_api import create_report_workbook_editor_router
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_slides_editor_api import SlidesService
from smart_reporting.reporting.tests.test_slides_editor_api import _context as slides_context
from smart_reporting.reporting.tests.test_workbook_editor import _bytes
from smart_reporting.reporting.tests.test_workbook_editor import _context as workbook_context
from smart_reporting.reporting.tests.test_workbook_editor_api import Workbooks


def _editor(kind):
    if kind == "slides":
        return slides_context(), SlidesService(), create_report_slides_editor_router, "slides", "pptx", "save"
    return workbook_context(_bytes()), Workbooks(), create_report_workbook_editor_router, "workbooks", "xlsx", "snapshot"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["slides", "workbook"])
@pytest.mark.parametrize(("header", "cookie"), [
    ("missing", "valid"), ("valid", "missing"),
    ("invalid", "valid"), ("valid", "invalid"),
])
async def test_office_editor_requires_both_csrf_values(tmp_path, kind, header, cookie):
    context, service, router, route, artifact, action = _editor(kind)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(context, capabilities={f"{artifact}_editor": True})
    app = FastAPI()
    app.include_router(router(grants, **{route: service}, static_dir=tmp_path, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://report.test") as client:
        opened = await client.get(f"/reports/v1/{route}/open/{raw}")
        token = client.cookies.get(f"report_{kind}_csrf")
        if cookie != "valid":
            client.cookies.delete(f"report_{kind}_csrf")
        if cookie == "invalid":
            client.cookies.set(f"report_{kind}_csrf", "wrong")
        headers = {"X-CSRF-Token": token if header == "valid" else "wrong"} if header != "missing" else {}
        response = await client.post(opened.headers["location"] + f"/api/{action}", json={}, headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"] == {"code": f"report_{kind}_csrf_invalid"}


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["slides", "workbook"])
@pytest.mark.parametrize("body", [b"{invalid", b"[]"])
async def test_office_editor_keeps_format_specific_json_errors(tmp_path, kind, body):
    context, service, router, route, artifact, action = _editor(kind)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(context, capabilities={f"{artifact}_editor": True})
    app = FastAPI()
    app.include_router(router(grants, **{route: service}, static_dir=tmp_path, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://report.test") as client:
        opened = await client.get(f"/reports/v1/{route}/open/{raw}")
        token = client.cookies.get(f"report_{kind}_csrf")
        response = await client.post(opened.headers["location"] + f"/api/{action}", content=body,
            headers={"X-CSRF-Token": token, "Content-Type": "application/json"})
    if body == b"{invalid":
        assert response.status_code == 400
        detail = {"code": f"report_{kind}_payload_invalid"}
        if kind == "slides":
            detail["message"] = "请求内容不是有效的 JSON。"
    elif kind == "slides":
        assert response.status_code == 409
        detail = {"code": "report_slides_edit_invalid", "message": "幻灯片修改内容无效。"}
    else:
        assert response.status_code == 422
        detail = {"code": "report_workbook_payload_invalid"}
    assert response.json()["detail"] == detail


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["slides", "workbook"])
@pytest.mark.parametrize("code", ["permission_denied", "identity_changed"])
async def test_office_editor_keeps_context_error_status(tmp_path, kind, code):
    context, service, router, route, artifact, _action = _editor(kind)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw, _ = await grants.issue(context, capabilities={f"{artifact}_editor": True})
    app = FastAPI()
    app.include_router(router(grants, **{route: service}, static_dir=tmp_path, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://report.test") as client:
        opened = await client.get(f"/reports/v1/{route}/open/{raw}")
        async def fail(_session):
            raise ReportingError(f"report_{kind}_{code}", "原始错误")
        service.context_for_session = fail
        response = await client.get(opened.headers["location"] + ("/api/deck" if kind == "slides" else "/api/file"))
    expected_status = 403 if code == "permission_denied" else 404 if kind == "slides" else 409
    assert response.status_code == expected_status
    assert response.json()["detail"] == {"code": f"report_{kind}_{code}", "message": "原始错误"}


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["slides", "workbook"])
@pytest.mark.parametrize("fault", ["none", "size", "hash", "read", "scope"])
async def test_office_editor_reads_only_verified_bytes(kind, fault):
    content = b"verified-office-file"
    context = (slides_context() if kind == "slides" else workbook_context(content)).model_copy(update={
        ("pptx_size" if kind == "slides" else "xlsx_size"): len(content) + (fault == "size"),
        ("pptx_sha256" if kind == "slides" else "xlsx_sha256"): "a" * 64 if fault == "hash" else hashlib.sha256(content).hexdigest(),
        "scope": {} if fault == "scope" else {"threadId": "thread"},
    })
    async def read(thread_id, path):
        assert thread_id == "thread"
        assert path == (context.pptx_path if kind == "slides" else context.xlsx_path)
        if fault == "read":
            raise OSError("unreadable")
        return content, "application/octet-stream"
    service_type = ReportSlidesEditorService if kind == "slides" else ReportWorkbookEditorService
    service = service_type(state_repository=None, workspace_registry=None, workspace=SimpleNamespace(afile_bytes=read))
    read_verified = service._read_verified_pptx if kind == "slides" else service._read_verified
    if fault == "none":
        assert await read_verified(context) == content
    else:
        with pytest.raises(ReportingError) as caught:
            await read_verified(context)
        assert caught.value.code == f"report_{kind}_identity_changed"
        artifact = "PPTX" if kind == "slides" else "XLSX"
        assert caught.value.message == f"{artifact} 文件{'无法读取' if fault in {'read', 'scope'} else '身份已变化'}。"
