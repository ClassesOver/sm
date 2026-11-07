"""真实会话签名、工作区字节和原生入口的权限边界。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor.native_models import (
    NativeArtifacts,
    NativeDocument,
    NativeEditorContext,
    NativeRevision,
    NativeValidation,
    native_digest,
)
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorContext,
    ReportEditorGrantService,
    ReportEditorService,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope, reporting_scope_keys


class Repository:
    def __init__(self):
        self.documents = {}
        self.revisions = {}
        self.keys = {}

    async def create_from_source(self, source, *, scope, request_id):
        key = native_digest([source.model_dump(mode="json"), scope.model_dump(), request_id])
        if key in self.keys:
            return self.documents[self.keys[key]]
        document = NativeDocument(
            documentId=uuid4().hex,
            scope=scope,
            ownerId=scope.user_id,
            source=source,
            createdAt=datetime.now(UTC),
            nextRevision=2,
        )
        context = NativeEditorContext(
            documentId=document.document_id,
            format=source.format,
            revision=1,
            scope=scope,
            sourceFile=source.source_file,
            origin="report",
        )
        self.documents[document.document_id] = document
        self.keys[key] = document.document_id
        self.revisions[(document.document_id, 1)] = NativeRevision(
            documentId=document.document_id,
            revision=1,
            scope=scope,
            requestId=request_id,
            requestSha256=key,
            status="saved",
            context=context,
            artifacts=NativeArtifacts(
                **{{"docx": "word", "pdf": "pdf", "xlsx": "xlsx", "pptx": "pptx"}[source.format]: source.source_file}
            ),
            validation=NativeValidation(ok=False),
            createdAt=datetime.now(UTC),
        )
        return document

    async def get_revision(self, document_id, revision, *, scope):
        found = self.revisions.get((document_id, revision))
        return found if found is not None and found.scope == scope else None


@pytest.fixture
async def setup(tmp_path):
    from smart_reporting.report_editor.native import NativeEditorService
    from smart_reporting.report_editor.native_api import create_native_editor_router

    keys = reporting_scope_keys(
        database="db", company_id="c", user_id="u", thread_id="t", run_id="run"
    )
    scope = ReportingWorkflowScope(
        run_id="run",
        external_run_id="run",
        session_id="s",
        caller_thread_id="t",
        user_id="u",
        database="db",
        company_id="c",
        thread_lease_key=keys.thread_lease_key,
        workspace_key=keys.workspace_key,
    )
    registry = ReportingWorkspaceRegistry(tmp_path / "reports", secret="s" * 32)
    registry.resolve(scope)
    workspace = ReportingWorkspaceRouter(registry)
    content = b"%PDF-1.4\nsource-test\n"
    path = "reports/report.pdf"
    await workspace.awrite_bytes(scope.workspace_key, path, content)
    context = ReportEditorContext(
        reportId="report",
        revision=1,
        jobId="job",
        workflowRunId="run",
        markdownPath="reports/report.md",
        job={
            "jobId": "job",
            "render": {
                "pdf": {
                    "path": path,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            },
        },
        scope=scope.as_state(),
    )
    report = ReportEditorService(
        state_repository=SimpleNamespace(
            get=AsyncMock(
                return_value=SimpleNamespace(
                    payload={
                        "reportEditorContexts": {
                            "1": context.model_dump(mode="json", by_alias=True)
                        }
                    }
                )
            )
        ),
        workspace_registry=registry,
        workspace=workspace,
    )
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    raw_grant, _ = await grants.issue(context)
    raw_session, session = await grants.exchange(raw_grant)
    native_workspace = ReportingWorkspaceRouter(
        ReportingWorkspaceRegistry(tmp_path / "native", secret="s" * 32)
    )
    repo = Repository()
    service = NativeEditorService(
        native_workspace, repo, grants, report_editor=report, pdf_enabled=True
    )
    app = FastAPI()
    app.include_router(create_native_editor_router(grants, editor=service, cookie_secure=False))
    yield SimpleNamespace(
        app=app,
        service=service,
        grants=grants,
        context=context,
        session=session,
        token=raw_session,
        repo=repo,
        content=content,
        report_workspace=workspace,
        workspace=native_workspace,
    )


async def fork(client, env, **body):
    client.cookies.set("report_editor_session", env.token)
    return await client.post(
        "/reports/v1/editor/report/1/api/native/open",
        json={"format": "pdf", "requestId": "open-1", **body},
        headers={"Origin": "http://test", "X-CSRF-Token": env.grants.csrf_token(env.token)},
    )


@pytest.mark.anyio
async def test_report_fork_uses_real_grants_and_independent_copy_and_retries(setup):
    from smart_reporting.report_editor.native import bind_native_workspace

    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        opened = await fork(client, setup)
        assert opened.status_code == 200, opened.text
        first = opened.json()
        assert (await fork(client, setup)).json()["documentId"] == first["documentId"]
        assert len(setup.repo.documents) == 1
        response = await client.get(first["editor"]["url"], follow_redirects=True)
        assert response.status_code == 200
        base = f"/reports/v1/native/{first['documentId']}/1"
        data = (await client.get(base + "/api/context")).json()
        assert data["context"]["format"] == "pdf"
        assert data["csrfToken"]
        assert (await client.get(base + "/api/file")).content == setup.content
        saved = setup.repo.revisions[(first["documentId"], 1)].context
        assert saved.source_file.path != "reports/report.pdf"
        assert bind_native_workspace(setup.workspace, saved.scope) != saved.scope.thread_id
        await setup.report_workspace.awrite_bytes(
            setup.context.scope["threadId"], "reports/report.pdf", b"changed", overwrite=True
        )
        assert (await client.get(base + "/api/file")).content == setup.content


@pytest.mark.anyio
async def test_legacy_grant_never_opens_native_context(setup):
    raw, _ = await setup.grants.issue(setup.context)
    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        response = await client.get("/reports/v1/native/open/" + raw)
        assert response.status_code == 403
        assert "native_editor_session" not in response.cookies


@pytest.mark.anyio
@pytest.mark.parametrize(
    "mode", ["origin", "csrf", "report", "restricted", "changed", "format", "extra"]
)
async def test_fork_rejects_invalid_or_untrusted_inputs(setup, mode):
    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        client.cookies.set("report_editor_session", setup.token)
        headers = {"Origin": "http://test", "X-CSRF-Token": setup.grants.csrf_token(setup.token)}
        body = {"format": "pdf", "requestId": "open-1"}
        path = "/reports/v1/editor/report/1/api/native/open"
        expected = 403
        if mode == "origin":
            headers["Origin"] = "https://evil.example"
        if mode == "csrf":
            headers["X-CSRF-Token"] = "bad"
        if mode == "report":
            path = path.replace("/report/", "/other/")
        if mode == "restricted":
            raw, _ = await setup.grants.issue(
                setup.context, capabilities={"download_original": True}
            )
            token, _ = await setup.grants.exchange(raw)
            client.cookies.set("report_editor_session", token)
            headers["X-CSRF-Token"] = setup.grants.csrf_token(token)
        if mode == "changed":
            await setup.report_workspace.awrite_bytes(
                setup.context.scope["threadId"], "reports/report.pdf", b"changed", overwrite=True
            )
            expected = 409
        if mode == "format":
            body["format"] = "xlsx"
            expected = 422
        if mode == "extra":
            body["scope"] = {"companyId": "evil"}
            expected = 422
        response = await client.post(path, json=body, headers=headers)
        assert response.status_code == expected, response.text
        assert not setup.repo.documents


@pytest.mark.anyio
async def test_native_scope_revision_and_capability_mismatches_are_rejected(setup):
    from smart_reporting.report_editor.native_models import NativeScope
    from smart_reporting.reporting.models import ReportingError

    result = await setup.service.open_report(setup.session, format="pdf", request_id="open-1")
    context = setup.repo.revisions[(result["documentId"], 1)].context
    for change in (
        {"scope": {**context.scope.model_dump(by_alias=True), "companyId": "other"}},
        {"format": "docx"},
        {"native_editor": False},
    ):
        capabilities = {**setup.service.capabilities(context), **change}
        raw, _ = await setup.grants.issue(context, capabilities=capabilities)
        _, session = await setup.grants.exchange(raw)
        with pytest.raises(ReportingError):
            await setup.service.context_for_session(session)
    assert (
        await setup.repo.get_revision(
            context.document_id,
            1,
            scope=NativeScope(**{**context.scope.model_dump(), "user_id": "other"}),
        )
        is None
    )


@pytest.mark.anyio
async def test_disabled_open_preserves_existing_native_file_access(setup):
    result = await setup.service.open_report(setup.session, format="pdf", request_id="open-1")
    context = setup.repo.revisions[(result["documentId"], 1)].context
    setup.service.pdf_enabled = False
    from smart_reporting.reporting.models import ReportingError

    with pytest.raises(ReportingError):
        await setup.service.open_report(setup.session, format="pdf", request_id="new")
    assert await setup.service.read_file(context) == setup.content


@pytest.mark.anyio
async def test_fallback_download_binds_digest_scope_and_verifies_file_after_restart(setup):
    result = await setup.service.open_report(setup.session, format="pdf", request_id="open-1")
    context = setup.repo.revisions[(result["documentId"], 1)].context
    caps = {
        **setup.service.capabilities(context),
        "native_editor": False,
        "context": context.model_dump(mode="json", by_alias=True),
        "artifacts": {"pdf": context.source_file.model_dump(mode="json", by_alias=True)},
    }
    raw, _ = await setup.grants.issue(context, capabilities=caps)
    from smart_reporting.report_editor.native import bind_native_workspace

    key = bind_native_workspace(setup.workspace, context.scope)
    setup.workspace.registry.release(key)
    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        url = f"/reports/v1/native/download/{raw}/pdf"
        response = await client.get(url)
        assert response.status_code == 200, response.text
        assert response.content == setup.content
        raw_bad, _ = await setup.grants.issue(
            context,
            capabilities={
                **caps,
                "context": {**caps["context"], "parentRevision": 1, "revision": 2},
            },
        )
        assert (await client.get(f"/reports/v1/native/download/{raw_bad}/pdf")).status_code == 403
        await setup.workspace.awrite_bytes(
            key, context.source_file.path, b"changed", overwrite=True
        )
        assert (await client.get(url)).status_code == 409


@pytest.mark.anyio
async def test_native_api_real_docx_preview_with_unsaved_operations_and_csrf(setup):
    from io import BytesIO

    from docx import Document

    document = Document()
    document.add_paragraph("原生中文正文")
    stream = BytesIO()
    document.save(stream)
    content = stream.getvalue()
    path = "reports/report.docx"
    await setup.report_workspace.awrite_bytes(setup.context.scope["threadId"], path, content)
    setup.context.job["render"]["word"] = {
        "path": path,
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    state = SimpleNamespace(
        payload={
            "reportEditorContexts": {"1": setup.context.model_dump(mode="json", by_alias=True)}
        }
    )
    setup.service.report_editor.state_repository.get = AsyncMock(return_value=state)
    token_grant, _ = await setup.grants.issue(setup.context)
    setup.token, setup.session = await setup.grants.exchange(token_grant)
    setup.service.docx_enabled = True
    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        response = await fork(client, setup, format="docx")
        assert response.status_code == 200, response.text
        result = response.json()
        await client.get(result["editor"]["url"])
        base = f"/reports/v1/native/{result['documentId']}/1"
        data = (await client.get(base + "/api/context")).json()
        headers = {"Origin": "http://test", "X-CSRF-Token": data["csrfToken"]}
        payload = {"expectedSha256": data["context"]["sourceFile"]["sha256"], "operations": []}
        original = await client.post(base + "/api/preview", json=payload, headers=headers)
        assert original.status_code == 200, original.text
        target = next(block for block in original.json()["model"]["blocks"] if block["editable"])
        payload["operations"] = [
            {
                "kind": "replaceParagraph",
                "blockId": target["blockId"],
                "expectedObjectSha256": target["expectedObjectSha256"],
                "text": "草稿修改中文",
            }
        ]
        preview = await client.post(base + "/api/preview", json=payload, headers=headers)
        assert preview.status_code == 200, preview.text
        assert preview.json()["sourceSha256"] != preview.json()["draftSha256"]
        assert any(block["text"] == "草稿修改中文" for block in preview.json()["model"]["blocks"])
        assert (await client.get(base + "/api/file")).content == content
        assert len(setup.repo.revisions) == 1
        assert (await client.post(base + "/api/preview", json=payload)).status_code == 403
        setup.workspace.registry.release(
            __import__(
                "smart_reporting.report_editor.native", fromlist=["bind_native_workspace"]
            ).bind_native_workspace(
                setup.workspace, setup.repo.revisions[(result["documentId"], 1)].scope
            )
        )
        assert (await client.get(base + "/api/file")).content == content


@pytest.mark.anyio
async def test_main_native_download_rebinds_workspace_and_rejects_foreign_grant(setup):
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_api import create_native_editor_router
    from smart_reporting.reporting.delivery.publishing import (
        ReportDownloadGrantService,
        ReportDownloadHttpService,
        ReportDownloadScope,
    )
    from smart_reporting.reporting.tests.delivery_fakes import (
        InMemoryDownloadGrantRepository,
        InMemoryReportArtifactRepository,
    )

    result = await setup.service.open_report(setup.session, format="pdf", request_id="open-1")
    context = setup.repo.revisions[(result["documentId"], 1)].context
    key = bind_native_workspace(setup.workspace, context.scope)
    downloads = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    service = ReportDownloadHttpService(
        downloads, InMemoryReportArtifactRepository(), workspace_service=setup.workspace
    )
    app = FastAPI()
    app.include_router(
        create_native_editor_router(
            setup.grants, editor=setup.service, cookie_secure=False, download_service=service
        )
    )
    scope = ReportDownloadScope(
        database=context.scope.database,
        user_id=context.scope.user_id,
        company_id=context.scope.company_id,
        session_id=context.scope.thread_id,
        thread_id=key,
        workflow_run_id=context.workflow_run_id,
    )
    raw, _ = await downloads.issue(
        scope=scope,
        report_id=f"native:{context.document_id}:r1",
        revision=1,
        pdf_path=context.source_file.path,
        pdf_size=context.source_file.size,
        pdf_sha256=context.source_file.sha256,
    )
    setup.workspace.registry.release(key)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/reports/v1/native/artifacts/{raw}/pdf")
        assert response.status_code == 200, response.text
        assert response.content == setup.content
        await setup.workspace.awrite_bytes(key, context.source_file.path, b"changed", overwrite=True)
        changed = await client.get(f"/reports/v1/native/artifacts/{raw}/pdf")
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "report_download_file_changed"
        wrong, _ = await downloads.issue(
            scope=scope,
            report_id="original-report",
            revision=1,
            pdf_path=context.source_file.path,
            pdf_size=context.source_file.size,
            pdf_sha256=context.source_file.sha256,
        )
        assert (await client.get(f"/reports/v1/native/artifacts/{wrong}/pdf")).status_code == 403


@pytest.mark.anyio
async def test_save_route_passes_validated_snapshot_note_and_requires_csrf(setup):
    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        result = (await fork(client, setup)).json()
        await client.get(result["editor"]["url"])
        base = f"/reports/v1/native/{result['documentId']}/1"
        data = (await client.get(base + "/api/context")).json()
        publication = SimpleNamespace(
            save_revision=AsyncMock(return_value={"revision": 2, "revisionRegistered": True})
        )
        setup.service.publication = publication
        payload = {
            "requestId": "save-one",
            "expectedSha256": data["context"]["sourceFile"]["sha256"],
            "operations": [],
            "note": "人工审核说明",
        }
        response = await client.post(
            base + "/api/save",
            json=payload,
            headers={"Origin": "http://test", "X-CSRF-Token": data["csrfToken"]},
        )
        assert response.status_code == 200, response.text
        args = publication.save_revision.call_args
        assert args.kwargs["note"] == "人工审核说明"
        assert args.kwargs["request_id"] == "save-one"
        assert args.args[0].document_id == result["documentId"]
        assert (await client.post(base + "/api/save", json=payload)).status_code == 403
        assert publication.save_revision.await_count == 1
        wrong = await client.get(base.replace("/1", "/2") + "/api/file")
        assert wrong.status_code == 403


@pytest.mark.anyio
@pytest.mark.parametrize(
    "failure,status", [(ValueError("bad operation"), 422), (FileNotFoundError("missing node"), 503)]
)
async def test_save_engine_failures_have_product_http_status(setup, failure, status):
    async with AsyncClient(
        transport=ASGITransport(app=setup.app), base_url="http://test"
    ) as client:
        result = (await fork(client, setup)).json()
        await client.get(result["editor"]["url"])
        base = f"/reports/v1/native/{result['documentId']}/1"
        data = (await client.get(base + "/api/context")).json()
        setup.service.publication = SimpleNamespace(save_revision=AsyncMock(side_effect=failure))
        payload = {
            "requestId": "save-failure",
            "expectedSha256": data["context"]["sourceFile"]["sha256"],
            "operations": [],
        }
        response = await client.post(
            base + "/api/save",
            json=payload,
            headers={"Origin": "http://test", "X-CSRF-Token": data["csrfToken"]},
        )
        assert response.status_code == status, response.text


@pytest.mark.anyio
async def test_save_preserves_specific_reporting_conflict(setup):
    from smart_reporting.reporting.models import ReportingError

    result = await setup.service.open_report(setup.session, format="pdf", request_id="open-1")
    context = setup.repo.revisions[(result["documentId"], 1)].context
    setup.service.publication = SimpleNamespace(
        save_revision=AsyncMock(
            side_effect=ReportingError("native_revision_conflict", "same key different body")
        )
    )
    with pytest.raises(ReportingError) as raised:
        await setup.service.save(
            context, request_id="same", expected_sha256=context.source_file.sha256, operations=[]
        )
    assert raised.value.code == "native_revision_conflict"


@pytest.mark.anyio
async def test_report_document_only_advertises_enabled_registered_native_formats():
    from smart_reporting.report_editor.api import create_report_editor_router

    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    original = ReportEditorContext(reportId="report", revision=1, jobId="job", workflowRunId="run",
        markdownPath="report.md", job={"jobId":"job", "render":{"word":{"path":"report.docx","size":5,"sha256":"a"*64}}},
        scope={"database":"db", "companyId":"c", "userId":"u", "threadId":"t"})
    report = SimpleNamespace(context_for_session=AsyncMock(return_value=original),
        read_document=AsyncMock(return_value=SimpleNamespace(path="report.md",markdown="# 原稿",sha256="a"*64)))
    native = SimpleNamespace(docx_enabled=True,pdf_enabled=False)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=report, native_editor=native, cookie_secure=False))
    token, _ = await grants.issue(original)
    async with AsyncClient(transport=ASGITransport(app=app),base_url="http://test") as client:
        await client.get(f"/reports/v1/editor/open/{token}")
        response = await client.get("/reports/v1/editor/report/1/api/document")
        assert response.json()["nativeFormats"] == ["docx"]
        native.docx_enabled=False
        response = await client.get("/reports/v1/editor/report/1/api/document")
        assert response.json()["nativeFormats"] == []
