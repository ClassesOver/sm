"""Real ASGI/session registry accept checks; candidate and preview are controlled, not engines."""

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.reporting.models import ReportingError
from smart_reporting.report_editor.native import NativeEditorService, bind_native_workspace
from smart_reporting.report_editor.native_ai import NativeAIService, _NativeAIJob
from smart_reporting.report_editor.native_ai_api import create_native_ai_router
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
from smart_reporting.report_editor.native_models import NativeEditorContext, NativeScope
from smart_reporting.office.editor_grants import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    token_hash,
)
from smart_reporting.report_editor.slides_native_ai import NativeSlidesAIService
from smart_reporting.report_editor.slides_native_ai_api import create_native_slides_ai_router
from smart_reporting.report_editor.workbook_native_ai import NativeWorkbookAIService
from smart_reporting.report_editor.workbook_native_ai_api import create_native_workbook_ai_router
from smart_reporting.office.artifacts import ArtifactFile
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)


@pytest.mark.anyio
@pytest.mark.parametrize("format", ["docx", "pdf", "xlsx", "pptx"])
@pytest.mark.parametrize("fault", ["none", "revoke", "expiry", "context", "source", "snapshot", "proposal", "readonly"])
async def test_regular_accept_rechecks_authority_after_preview(tmp_path, format, fault):
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret="w" * 32))
    scope = NativeScope(database="db", companyId="company", userId="user", threadId="thread")
    key = bind_native_workspace(workspace, scope)
    original = b"synthetic source identity; no engine in this boundary test"
    path = f"native/source.{format}"
    await workspace.awrite_bytes(key, path, original)
    context = NativeEditorContext(
        documentId="doc",
        revision=1,
        format=format,
        origin="report",
        scope=scope,
        sourceFile=ArtifactFile(
            path=path,
            size=len(original),
            sha256=hashlib.sha256(original).hexdigest(),
            mediaType={
                "pdf": "application/pdf",
                "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }[format],
        ),
    )
    row = SimpleNamespace(status="saved", context=context)
    repository = SimpleNamespace(
        get_revision=AsyncMock(return_value=row), reserve_revision=AsyncMock()
    )
    registry = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(registry, secret="g" * 32)
    editor = NativeEditorService(
        workspace,
        repository,
        grants,
        docx_enabled=True,
        pdf_enabled=True,
        office_enabled=True,
        pdf_text_enabled=True,
    )
    can_write = True

    async def authorize(_session, *, write=False):
        if write and not can_write:
            raise ReportingError("native_permission_denied", "工作区写权限已撤销。")

    editor.office_authorize = authorize
    raw, _ = await grants.issue(context, capabilities={**editor.capabilities(context), "office": True})
    cookie, session = await grants.exchange(raw)
    cls, router, route = {
        "docx": (NativeAIService, create_native_ai_router, "ai"),
        "pdf": (NativeAIService, create_native_ai_router, "ai"),
        "xlsx": (NativeWorkbookAIService, create_native_workbook_ai_router, "workbook-ai"),
        "pptx": (NativeSlidesAIService, create_native_slides_ai_router, "slides-ai"),
    }[format]
    ai = cls(editor, planner=AsyncMock(), enabled=True)
    operations = [{"kind": "editSlides", "edits": []}] if format == "pptx" else []
    job = _NativeAIJob(
        "edit",
        context.digest(),
        ai._snapshot(context, []),
        scope.user_id,
        datetime.now(UTC),
        status="succeeded",
        proposal={"operations": operations, "previewDigest": "digest"},
    )
    ai._jobs[job.edit_id] = job
    entered, release = asyncio.Event(), asyncio.Event()

    async def preview(*args, **kwargs):
        await editor.read_file(context)
        entered.set()
        await release.wait()
        return {"previewDigest": "digest"}

    editor.preview = preview
    app = FastAPI()
    app.include_router(router(grants, editor=editor, ai=ai))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        cookies={NATIVE_SESSION_COOKIE: cookie},
    ) as client:
        task = asyncio.create_task(
            client.post(
                f"/reports/v1/native/doc/1/api/{route}/edit/accept",
                headers={"origin": "http://test", "x-csrf-token": grants.csrf_token(cookie)},
                json={
                    "expectedSha256": context.source_file.sha256,
                    "operations": [],
                    "snapshotSha256": job.snapshot_sha256,
                },
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if fault == "revoke":
                del registry.sessions[token_hash(cookie)]
            elif fault == "expiry":
                expires = datetime.now(UTC) + timedelta(milliseconds=30)
                registry.sessions[token_hash(cookie)] = replace(session, expires_at=expires)
                while datetime.now(UTC) <= expires:
                    await asyncio.sleep(0.005)
            elif fault == "context":
                row.context = context.model_copy(update={"origin": "upload"})
            if fault == "readonly":
                can_write = False
            if fault == "source":
                await workspace.awrite_bytes(key, path, b"external change", overwrite=True)
            elif fault == "snapshot":
                job.snapshot_sha256 = "f" * 64
            elif fault == "proposal":
                job.proposal = {**job.proposal, "notes": ["replacement candidate"]}
            release.set()
            response = await task
            expected = {
                "none": (200, None),
                "revoke": (403, "report_editor_session_invalid"),
                "expiry": (403, "report_editor_session_expired"),
                "context": (403, "native_permission_denied"),
                "readonly": (403, "native_permission_denied"),
                "source": (409, "native_source_changed"),
                "snapshot": (409, "native_ai_snapshot_changed"),
                "proposal": (422, "native_ai_not_ready"),
            }[fault]
            assert response.status_code == expected[0], response.text
            if expected[1]:
                assert response.json()["detail"]["code"] == expected[1]
            assert job.accepted is (fault == "none")
            repository.reserve_revision.assert_not_awaited()
            if fault != "source":
                assert await editor.read_file(context) == original
            else:
                assert (await workspace.afile_bytes(key, path))[0] == b"external change"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            await ai.aclose()

@pytest.mark.anyio
@pytest.mark.parametrize("format", ["xlsx", "pptx"])
@pytest.mark.parametrize("revoke_at_preview", [1, 2])
async def test_generation_rechecks_office_edit_access_before_model_and_receipt(format, revoke_at_preview):
    from smart_reporting.office.native_access import bind
    from smart_reporting.reporting.tests.test_slides_native_ai import Editor as SlidesEditor
    from smart_reporting.reporting.tests.test_workbook_native_ai import Editor as WorkbookEditor, proposal

    if format == "xlsx":
        editor = WorkbookEditor()
        service = NativeWorkbookAIService
        selection = {"sheetName": "Sheet", "startRow": 0, "endRow": 0, "startColumn": 0, "endColumn": 0}
        candidate = proposal()
    else:
        editor = SlidesEditor()
        service = NativeSlidesAIService
        selection = [{"slideIndex": 0, "elementId": "title"}]
        candidate = {"summary": "更新标题", "order": [0, 1],
                     "edits": [{"slideIndex": 0, "elementId": "title", "text": "新标题"}]}
    can_write = True
    original_preview = editor.preview
    original_context = editor.context_for_session
    session = SimpleNamespace(report_id=editor.context.document_id, capabilities={"office": True})

    async def authorize(_session, *, write=False):
        if write and not can_write:
            raise ReportingError("native_permission_denied", "工作区写权限已撤销。")

    async def context_for_session(session):
        bind(session, authorize)
        return await original_context(session)

    async def preview(*args, **kwargs):
        nonlocal can_write
        result = await original_preview(*args, **kwargs)
        if len(editor.previews) == revoke_at_preview:
            can_write = False
        return result

    editor.context_for_session = context_for_session
    editor.preview = preview
    model = AsyncMock(return_value=candidate)

    async def planner(prompt, **kwargs):
        return await model(prompt, **kwargs)
    ai = service(editor, planner=planner, enabled=True)
    try:
        started = await ai.start_edit(
            session, client_request_id="draft", instruction="修改选区",
            expected_sha256=editor.context.source_file.sha256, operations=[], selection=selection,
        )
        result = await ai.wait_edit_status(session, started["editId"])
        assert result["status"] == "failed", result
        assert result["error"]["code"] == "native_permission_denied"
        assert "proposal" not in result
        assert model.await_count == revoke_at_preview - 1
    finally:
        await ai.aclose()
