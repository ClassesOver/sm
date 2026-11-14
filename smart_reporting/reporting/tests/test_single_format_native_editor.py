"""单格式正式交付只派生相同目标格式，保留来源文件。"""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorContext,
    ReportEditorGrantService,
)
from smart_reporting.reporting.tests.test_native_editor_api import setup  # noqa: F401


@pytest.mark.anyio
@pytest.mark.parametrize("delivery_format", ["pdf", "docx"])
async def test_single_format_report_opens_verified_native_copy_and_rejects_intermediate(setup, delivery_format):  # noqa: F811
    from smart_reporting.report_editor.native import bind_native_workspace

    env = setup
    if delivery_format == "docx":
        from io import BytesIO

        from docx import Document

        document = Document()
        document.add_paragraph("已发布正文")
        stream = BytesIO()
        document.save(stream)
        target = stream.getvalue()
    else:
        target = env.content
    path = f"reports/report.{delivery_format}"
    await env.report_workspace.awrite_bytes(env.context.scope["threadId"], path, target, overwrite=True)
    target_identity = {"path": path, "size": len(target), "sha256": hashlib.sha256(target).hexdigest()}
    render = {"pdf": target_identity, "word": target_identity}
    context = env.context.model_copy(update={"delivery_format": delivery_format,
        "job": {"jobId": "job", "render": render}})
    env.service.report_editor.state_repository.get = AsyncMock(return_value=SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}))
    env.service.docx_enabled = True
    grant, _ = await env.grants.issue(context)
    token, _ = await env.grants.exchange(grant)
    async with AsyncClient(transport=ASGITransport(app=env.app), base_url="http://test") as client:
        client.cookies.set("report_editor_session", token)
        headers = {"Origin": "http://test", "X-CSRF-Token": env.grants.csrf_token(token)}
        endpoint = "/reports/v1/editor/report/1/api/native/open"
        opened = await client.post(endpoint, json={"format": delivery_format, "requestId": "single-target"}, headers=headers)
        assert opened.status_code == 200, opened.text
        saved = env.repo.revisions[(opened.json()["documentId"], 1)].context
        copied = await env.workspace.afile_bytes(bind_native_workspace(env.workspace, saved.scope), saved.source_file.path)
        assert copied[0] == target
        assert saved.source_file.sha256 == target_identity["sha256"]
        assert saved.source_file.path != path
        original = await env.report_workspace.afile_bytes(context.scope["threadId"], path)
        assert original[0] == target
        other = "pdf" if delivery_format == "docx" else "docx"
        denied = await client.post(endpoint, json={"format": other, "requestId": "intermediate"}, headers=headers)
        assert denied.status_code == 422
        assert denied.json()["detail"]["code"] == "native_format_invalid"
        assert len(env.repo.documents) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("delivery_format,want", [("pdf", ["pdf"]), ("docx", ["docx"]), ("md", [])])
async def test_native_launcher_advertises_only_requested_registered_format(delivery_format, want):
    from smart_reporting.report_editor.api import create_report_editor_router

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    context = ReportEditorContext(reportId="report", revision=1, jobId="job", workflowRunId="run",
        deliveryFormat=delivery_format, markdownPath="report.md", scope={"database": "db", "companyId": "c", "userId": "u", "threadId": "t"},
        **({"mdPath": "report.md", "mdSize": 5, "mdSha256": "c" * 64} if delivery_format == "md" else {}),
        job={"jobId": "job", "render": {
            "pdf": {"path": "report.pdf", "size": 5, "sha256": "a" * 64},
            "word": {"path": "report.docx", "size": 5, "sha256": "b" * 64}}})
    report = SimpleNamespace(context_for_session=AsyncMock(return_value=context),
        read_document=AsyncMock(return_value=SimpleNamespace(path="report.md", markdown="# 正文", sha256="c" * 64)))
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=report,
        native_editor=SimpleNamespace(docx_enabled=True, pdf_enabled=True), cookie_secure=False))
    grant, _ = await grants.issue(context)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get(f"/reports/v1/editor/open/{grant}")
        result = await client.get("/reports/v1/editor/report/1/api/document")
        assert result.status_code == 200
        assert result.json()["nativeFormats"] == want
