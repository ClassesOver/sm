"""显式临时 PostgreSQL 上的四格式原生导入、恢复、HTTP 字节验收。"""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from docx import Document
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Cookies
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from pptx.util import Inches
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from smart_reporting.report_editor.native import NativeEditorService
from smart_reporting.report_editor.native_api import create_native_editor_router
from smart_reporting.report_editor.native_import import NativeImportService
from smart_reporting.report_editor.native_import_api import create_native_import_router
from smart_reporting.report_editor.native_models import NativeScope
from smart_reporting.report_editor.native_publication import NativePublicationService
from smart_reporting.report_editor.native_repository import NativeDocumentRepository
from smart_reporting.report_editor.repository import SqlAlchemyReportEditorRepository
from smart_reporting.report_editor.service import ReportEditorGrantService
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
    SqlAlchemyDownloadGrantRepository,
    SqlAlchemyReportArtifactRepository,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.tests.test_reporting_request_identity import SECRET, _capability

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def durable_database():
    # 不从 .env、DATABASE_URL 或应用配置回退读取业务数据库。
    dsn = os.environ.get("NATIVE_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("需要显式 NATIVE_TEST_DATABASE_URL 临时 PostgreSQL")
    url = make_url(dsn)
    if url.drivername != "postgresql+psycopg":
        raise ValueError("验收需要 postgresql+psycopg")
    schema = "native_lifecycle_" + uuid4().hex
    admin = create_async_engine(url)
    engines = []
    async with admin.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    def new_engine():
        engine = create_async_engine(url, connect_args={"options": f"-csearch_path={schema}"})
        engines.append(engine)
        return engine

    try:
        yield new_engine
    finally:
        for engine in engines:
            await engine.dispose()
        async with admin.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()


async def build_services(engine, workspace_root):
    from smart_reporting.app import require_workspace_capability

    native = NativeDocumentRepository(engine)
    editor_repository = SqlAlchemyReportEditorRepository(engine)
    download_repository = SqlAlchemyDownloadGrantRepository(engine)
    artifacts = SqlAlchemyReportArtifactRepository(engine)
    await native.create_schema()
    await editor_repository.create_schema()
    await download_repository.create_schema()
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(workspace_root, secret="w" * 32))
    grants = ReportEditorGrantService(editor_repository, secret="e" * 32)
    downloads = ReportDownloadGrantService(download_repository)
    publication = NativePublicationService(
        native, workspace, downloads, grants,
        artifact_persistence=ReportArtifactPersistenceService(artifacts, workspace),
        public_base_url="http://test",
    )
    editor = NativeEditorService(
        workspace, native, grants, report_editor=None,
        docx_enabled=True, pdf_enabled=True, office_enabled=True,
        pdf_text_enabled=True, publication=publication,
    )
    app = FastAPI()
    app.state.agentos_context = SimpleNamespace(settings=SimpleNamespace(workspace_hmac_secret=SECRET))
    app.middleware("http")(require_workspace_capability)
    app.include_router(create_native_import_router(NativeImportService(workspace, native, grants), enabled=True))
    # 故意禁用工作区下载回退：HTTP bytes 必须来自 PostgreSQL 产物仓储。
    app.include_router(create_native_editor_router(
        grants, editor=editor, cookie_secure=False,
        download_service=ReportDownloadHttpService(downloads, artifacts),
    ))
    return SimpleNamespace(app=app, native=native, grants=grants)


def original_file(format):
    stream = BytesIO()
    if format == "docx":
        document = Document()
        document.add_paragraph("Amount due 500")
        document.add_paragraph("Amount due 500")
        document.add_paragraph("UNCHANGED CONTROL")
        document.save(stream)
    elif format == "pdf":
        canvas = Canvas(stream, pagesize=(400, 300))
        canvas.setFont("Helvetica", 14)
        for y, value in [(230, "Amount due 500"), (200, "Amount due 500"), (160, "UNCHANGED CONTROL")]:
            canvas.drawString(30, y, value)
        canvas.save()
    elif format == "xlsx":
        workbook = Workbook()
        workbook.active.append([500, "UNCHANGED CONTROL", "=SUM(A1:A2)"])
        workbook.active["A2"] = 500
        workbook.save(stream)
    else:
        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        for index, value in enumerate(["Amount due 500", "Amount due 500", "UNCHANGED CONTROL"]):
            slide.shapes.add_textbox(Inches(1), Inches(index + 1), Inches(4), Inches(.5)).text = value
        deck.save(stream)
    return stream.getvalue()


def numeric_operation(format, model):
    if format == "docx":
        target = model["blocks"][0]
        return {"kind": "replaceParagraph", "blockId": target["blockId"],
                "expectedObjectSha256": target["expectedObjectSha256"], "text": "Amount due 750"}
    if format == "pdf":
        page = model["pages"][0]
        target = page["textObjects"][0]
        return {"kind": "replaceText", "pageId": page["pageId"], "objectId": target["objectId"],
                "expectedTextSha256": target["expectedTextSha256"], "newText": "Amount due 750"}
    if format == "xlsx":
        return {"kind": "applyCellEdits", "edits": [
            {"sheetName": "Sheet", "row": 0, "column": 0, "writeValue": True, "cell": {"value": 750}},
        ]}
    target = next(item for item in model["slides"][0]["elements"] if item["text"] == "Amount due 500")
    return {"kind": "editSlides", "edits": [{"slideIndex": 0, "elementId": target["id"], "text": "Amount due 750"}]}


def assert_independent_readback(format, content, *, changed):
    stream = BytesIO(content)
    target = "Amount due 750" if changed else "Amount due 500"
    if format == "docx":
        assert [p.text for p in Document(stream).paragraphs] == [target, "Amount due 500", "UNCHANGED CONTROL"]
    elif format == "pdf":
        reader = PdfReader(stream)
        assert len(reader.pages) == 1
        body = reader.pages[0].extract_text()
        assert body.splitlines() == [target, "Amount due 500", "UNCHANGED CONTROL"]
    elif format == "xlsx":
        sheet = load_workbook(stream).active
        assert (sheet["A1"].value, sheet["A2"].value) == (750 if changed else 500, 500)
        assert sheet["B1"].value == "UNCHANGED CONTROL"
        assert sheet["C1"].value == "=SUM(A1:A2)"
    else:
        deck = Presentation(stream)
        assert len(deck.slides) == 1
        assert [shape.text for shape in deck.slides[0].shapes] == [target, "Amount due 500", "UNCHANGED CONTROL"]


def no_reexecution(*args, **kwargs):
    raise AssertionError("服务重建后必须复用实际文件，不得重新执行编辑引擎")


@pytest.mark.parametrize("format", ["docx", "pdf", "xlsx", "pptx"])
async def test_native_four_format_durable_lifecycle(durable_database, tmp_path, monkeypatch, format):
    engine = durable_database()
    first = await build_services(engine, tmp_path)
    original = original_file(format)
    original_hash = hashlib.sha256(original).hexdigest()
    key = "word" if format == "docx" else format
    async with AsyncClient(transport=ASGITransport(app=first.app), base_url="http://test") as client:
        uploaded = await client.post(
            "/reports/v1/native/import",
            headers={"X-Workspace-Thread": "thread-1", "X-Workspace-Capability": _capability()},
            data={"requestId": f"durable-import-{format}"},
            files={"file": (f"source.{format}", original)},
        )
        assert uploaded.status_code == 200, uploaded.text
        imported = uploaded.json()
        opened = await client.get(imported["editor"]["url"], follow_redirects=True)
        assert opened.status_code == 200, opened.text
        base = opened.url.path + "/api"
        response = await client.get(base + "/context")
        assert response.status_code == 200, response.text
        context = response.json()
        scope = NativeScope.model_validate(context["context"]["scope"])
        headers = {"Origin": "http://test", "X-CSRF-Token": context["csrfToken"]}
        preview = await client.post(base + "/preview", headers=headers,
                                    json={"expectedSha256": original_hash, "operations": []})
        assert preview.status_code == 200, preview.text
        payload = {"expectedSha256": original_hash, "requestId": f"durable-edit-{format}",
                   "operations": [numeric_operation(format, preview.json()["model"])]}
        if format == "pdf":
            checked = await client.post(base + "/preview", headers=headers, json={
                "expectedSha256": original_hash, "operations": payload["operations"],
            })
            assert checked.status_code == 200, checked.text
            assert checked.json()["appliedOperationIndices"] == [0]
            assert checked.json()["skippedOperations"] == []
            payload["confirmedPreviewDigest"] = checked.json()["previewDigest"]

        append_event = first.native._append_revision_event

        async def event_insert_fault(connection, revision):
            await append_event(connection, revision)
            raise RuntimeError("durable_lifecycle_event_insert_fault")

        # Real repository transaction inserts the event and then fails: both event
        # and revision must roll back, without blocking publication/download bytes.
        monkeypatch.setattr(first.native, "_append_revision_event", event_insert_fault)
        saved = await client.post(base + "/save", headers=headers, json=payload)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["revision"] == 2 and result["parentRevision"] == 1
        assert result["revisionRegistered"] is False
        assert result["validation"]["ok"] is False
        assert {"native_source_review_pending", "native_revision_registration_failed"} <= {
            issue["code"] for issue in result["validation"]["issues"]
        }
        assert set(result["artifacts"]) == {key}
        artifact = result["artifacts"][key]
        cookies = Cookies(client.cookies)
        pending = await first.native.get_revision(imported["documentId"], 2, scope=scope)
        assert pending.status == "reserved"
        page = await first.native.revision_events_after(imported["documentId"], scope=scope)
        assert [(event["revision"], event["status"]) for event in page["events"]] == [(1, "saved")]
        assert page["latestSequence"] == 1
    await engine.dispose()

    # 新 engine、新仓储、新工作区 registry、新授权/编辑/下载服务与新 ASGI 应用。
    rebuilt_engine = durable_database()
    rebuilt = await build_services(rebuilt_engine, tmp_path)
    for module, function in [
        ("smart_reporting.report_editor.native_publication", "patch_docx"),
        ("smart_reporting.report_editor.native_publication", "patch_pdf_with_receipt"),
        ("smart_reporting.report_editor.native_office", "patch_office"),
    ]:
        monkeypatch.setattr(f"{module}.{function}", no_reexecution)
    async with AsyncClient(transport=ASGITransport(app=rebuilt.app), base_url="http://test", cookies=cookies) as client:
        downloaded = await client.get(artifact["downloadUrl"])
        assert downloaded.status_code == 200, downloaded.text
        assert len(downloaded.content) == artifact["size"]
        assert hashlib.sha256(downloaded.content).hexdigest() == artifact["sha256"] != original_hash
        assert_independent_readback(format, downloaded.content, changed=True)
        assert (await client.get(base + "/file")).content == original
        assert_independent_readback(format, original, changed=False)
        # 原编辑会话及原导入 grant 均从 PostgreSQL 重读。
        assert (await client.get(base + "/context")).status_code == 200
        restored = await client.post(base + "/save", headers=headers, json=payload)
        assert restored.status_code == 200, restored.text
        recovered = restored.json()
        assert recovered["revisionRegistered"] is True and recovered["revision"] == 2
        assert recovered["parentRevision"] == 1 and recovered["validation"]["ok"] is False
        assert set(recovered["artifacts"]) == {key}
        assert recovered["artifacts"][key]["sha256"] == artifact["sha256"]
        again = await client.post(base + "/save", headers=headers, json=payload)
        assert again.status_code == 200, again.text
        assert again.json()["revision"] == 2
        assert again.json()["artifacts"][key]["sha256"] == artifact["sha256"]
        final = again.json()
        redownloaded = await client.get(final["artifacts"][key]["downloadUrl"])
        assert redownloaded.status_code == 200 and redownloaded.content == downloaded.content
        reopened = await client.get(final["editor"]["openUrl"], follow_redirects=True)
        assert reopened.status_code == 200, reopened.text
        assert (await client.get(reopened.url.path + "/api/file")).content == downloaded.content
        # 修订二会话不能访问修订一，HTTP 请求不能自行更换文档身份。
        revision_two_cookie = next(cookie.value for cookie in client.cookies.jar
                                   if cookie.name == "native_editor_session" and cookie.path == reopened.url.path)
        crossed = await client.get(base + "/file", headers={
            "Cookie": f"native_editor_session={revision_two_cookie}",
        })
        assert crossed.status_code == 403, crossed.text
        old = await client.get(imported["editor"]["url"], follow_redirects=True)
        assert old.status_code == 200
        assert (await client.get(base + "/file")).content == original
        revision = await rebuilt.native.get_revision(imported["documentId"], 2, scope=scope)
        assert revision.status == "saved" and revision.validation.ok is False
        page = await rebuilt.native.revision_events_after(imported["documentId"], scope=scope)
        assert [(event["revision"], event["status"]) for event in page["events"]] == [
            (1, "saved"), (2, "saved"),
        ]
        assert page["nextSequence"] == page["latestSequence"] == 2
        for dimension in ("database", "company_id", "user_id", "thread_id"):
            foreign = scope.model_copy(update={dimension: "foreign"})
            assert await rebuilt.native.get_document(imported["documentId"], scope=foreign) is None
            assert await rebuilt.native.get_revision(imported["documentId"], 2, scope=foreign) is None
            forged = revision.context.model_copy(update={"scope": foreign})
            raw, _ = await rebuilt.grants.issue(forged, capabilities=NativeEditorService.capabilities(forged))
            denied = await client.get(f"/reports/v1/native/open/{raw}")
            assert denied.status_code == 404, denied.text
    async with rebuilt_engine.connect() as connection:
        rows = (await connection.execute(text(
            "SELECT revision, status FROM report_native_revisions_v1 ORDER BY revision"
        ))).all()
        assert [tuple(row) for row in rows] == [(1, "saved"), (2, "saved")]
        count = (await connection.execute(text(
            "SELECT next_revision FROM report_native_documents_v1"
        ))).scalar_one()
        assert count == 3
        for table in ("report_editor_grants_v1", "report_editor_sessions_v1",
                      "report_download_grants_v2", "report_artifact_files_v1", "report_artifact_chunks_v1"):
            assert (await connection.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() > 0
    print(json.dumps({"format": format, "sourceSha256": original_hash,
                      "downloadSha256": artifact["sha256"], "downloadBytes": len(downloaded.content),
                      "repositoryRebuilt": True, "serviceRebuilt": True, "postgresDownloadOnly": True,
                      "revision": 2, "validationOk": False, "foreignScopeDimensionsRejected": 4}))
