"""真实文件桥接和下载服务验证原生保存的非阻断契约。"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from unittest.mock import AsyncMock
from urllib.parse import unquote

import pytest
from docx import Document

from smart_reporting.report_editor.native_models import (
    NativeEditorContext,
    NativeRevision,
    NativeScope,
)
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile
from smart_reporting.reporting.delivery.publishing import (
    ReportArtifactPersistenceService,
    ReportDownloadGrantService,
    ReportDownloadHttpService,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.tests.delivery_fakes import (
    InMemoryDownloadGrantRepository,
    InMemoryReportArtifactRepository,
)


class Repository:
    def __init__(self):
        self.rows = {}
        self.completions = 0

    async def reserve_revision(
        self, document_id, *, parent_revision, request_id, request_sha256, scope, note=""
    ):
        from smart_reporting.report_editor.native_repository import NativeRepositoryConflict

        if request_id in self.rows:
            current = self.rows[request_id]
            if (
                current.request_sha256 != request_sha256
                or current.parent_revision != parent_revision
            ):
                raise NativeRepositoryConflict()
            return current
        result = NativeRevision(
            documentId=document_id,
            revision=len(self.rows) + 2,
            scope=scope,
            parentRevision=parent_revision,
            requestId=request_id,
            requestSha256=request_sha256,
            note=note,
            status="reserved",
            createdAt=datetime.now(UTC),
        )
        self.rows[request_id] = result
        return result

    async def complete_revision(self, reservation, *, context, artifacts, validation):
        self.completions += 1
        result = reservation.model_copy(
            update={
                "context": context,
                "artifacts": artifacts,
                "validation": validation,
                "status": "saved",
            }
        )
        self.rows[reservation.request_id] = result
        return result

    async def fail_revision(self, reservation, *, code):
        self.rows[reservation.request_id] = reservation.model_copy(
            update={"status": "failed", "failure_code": code}
        )


async def create_publication(tmp_path):
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_publication import NativePublicationService

    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    scope = NativeScope(database="db", companyId="company", userId="user", threadId="source-thread")
    key = bind_native_workspace(workspace, scope)
    document = Document()
    document.add_paragraph("原始段落")
    stream = BytesIO()
    document.save(stream)
    source = stream.getvalue()
    await workspace.awrite_bytes(key, "native/original.docx", source)
    context = NativeEditorContext(
        documentId="document",
        revision=1,
        scope=scope,
        format="docx",
        origin="report",
        sourceFile=ArtifactFile(
            path="native/original.docx",
            size=len(source),
            sha256=hashlib.sha256(source).hexdigest(),
            mediaType="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    )
    grants = ReportDownloadGrantService(InMemoryDownloadGrantRepository())
    artifacts = InMemoryReportArtifactRepository()
    editor_grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="e" * 32)
    service = NativePublicationService(
        Repository(),
        workspace,
        grants,
        editor_grants,
        artifact_persistence=ReportArtifactPersistenceService(artifacts, workspace),
        public_base_url="http://test",
    )
    downloads = ReportDownloadHttpService(grants, artifacts, workspace_service=workspace)
    return service, context, downloads


@pytest.fixture
async def publication(tmp_path):
    return await create_publication(tmp_path)


async def assert_downloads(result, downloads):
    assert result["artifacts"]["word"]["downloadUrl"]
    url = result["artifacts"]["word"]["downloadUrl"]
    raw = url.split("/")[-2]
    grant, chunks = await downloads.stream(raw, artifact="word")
    content = b"".join([chunk async for chunk in chunks])
    assert hashlib.sha256(content).hexdigest() == result["artifacts"]["word"]["sha256"]
    assert grant.report_id == f"native:{result['documentId']}:r{result['revision']}"
    assert Document(BytesIO(content)).paragraphs[0].text == "原始段落"


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["validation", "complete", "persistence", "pdf"])
async def test_native_save_failure_keeps_actual_word_download(publication, monkeypatch, failure):
    service, context, downloads = publication
    if failure == "validation":
        service.validator = AsyncMock(side_effect=RuntimeError("layout unavailable"))
    elif failure == "complete":
        service.repository.complete_revision = AsyncMock(
            side_effect=RuntimeError("database unavailable")
        )
    elif failure == "persistence":
        service.artifact_persistence.persist_available = AsyncMock(
            side_effect=RuntimeError("copy unavailable")
        )
    else:
        monkeypatch.setattr(
            "smart_reporting.report_editor.native_publication.libreoffice_to_pdf",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("conversion unavailable")),
        )
    result = await service.save_revision(
        context,
        operations=[],
        request_id="save",
        expected_sha256=context.source_file.sha256,
        export_pdf=failure == "pdf",
    )
    assert result["validation"]["ok"] is False
    codes = {issue["code"] for issue in result["validation"]["issues"]}
    assert {
        "validation": "native_validation_failed",
        "complete": "native_revision_registration_failed",
        "persistence": "native_artifact_persistence_failed",
        "pdf": "native_pdf_export_failed",
    }[failure] in codes
    assert result["revisionRegistered"] is (failure != "complete")
    if failure == "pdf":
        assert "pdf" not in result["artifacts"]
    await assert_downloads(result, downloads)


@pytest.mark.anyio
async def test_native_recorded_revision_uses_authorized_user_and_keeps_download(publication):
    from lxml import etree
    from zipfile import ZipFile

    namespaces = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.reporting.delivery.docx_native import inspect_docx

    service, context, downloads = publication
    source, _ = await service.workspace.afile_bytes(
        bind_native_workspace(service.workspace, context.scope), context.source_file.path
    )
    block = inspect_docx(source)['blocks'][0]
    result = await service.save_revision(
        context,
        operations=[{'kind': 'recordTextRevision', 'blockId': block['blockId'],
            'expectedObjectSha256': block['expectedObjectSha256'], 'from': 1, 'to': 2, 'text': '新'}],
        request_id='tracked-revision',
        expected_sha256=context.source_file.sha256,
    )
    assert result['validation']['ok'] is False
    assert result['artifacts']['word']['downloadUrl']
    raw = result['artifacts']['word']['downloadUrl'].split('/')[-2]
    _, chunks = await downloads.stream(raw, artifact='word')
    output = b''.join([chunk async for chunk in chunks])
    with ZipFile(BytesIO(output)) as archive:
        document = etree.fromstring(archive.read('word/document.xml'))
        authors = document.xpath('.//w:ins/@w:author | .//w:del/@w:author', namespaces=namespaces)
    assert authors and set(authors) == {context.scope.user_id}


@pytest.mark.anyio
async def test_saved_retry_reuses_revision_and_actual_bytes(publication):
    service, context, downloads = publication
    first = await service.save_revision(
        context, operations=[], request_id="same", expected_sha256=context.source_file.sha256
    )
    second = await service.save_revision(
        context, operations=[], request_id="same", expected_sha256=context.source_file.sha256
    )
    assert first["revision"] == second["revision"] == 2
    assert first["artifacts"]["word"]["sha256"] == second["artifacts"]["word"]["sha256"]
    assert service.repository.completions == 1
    await assert_downloads(second, downloads)


@pytest.mark.anyio
async def test_primary_grant_failure_uses_scoped_native_fallback(publication):
    service, context, _ = publication
    service.download_grants.issue = AsyncMock(side_effect=RuntimeError("primary unavailable"))
    result = await service.save_revision(
        context, operations=[], request_id="fallback", expected_sha256=context.source_file.sha256
    )
    url = result["artifacts"]["word"]["downloadUrl"]
    assert "/native/download/" in url
    _, session = await service.editor_grants.exchange(unquote(url.split("/")[-2]))
    cap = session.capabilities
    assert cap["native_download"] is True
    assert "native_editor" not in cap
    assert cap["scope"] == context.scope.model_dump(by_alias=True)
    assert cap["artifacts"]["word"]["sha256"] == result["artifacts"]["word"]["sha256"]
    assert session.workflow_run_id == context.workflow_run_id


@pytest.mark.anyio
async def test_failed_registration_retry_recovers_verified_files(publication, monkeypatch):
    service, context, downloads = publication
    original = service.repository.complete_revision
    service.repository.complete_revision = AsyncMock(
        side_effect=RuntimeError("temporarily unavailable")
    )
    first = await service.save_revision(
        context, operations=[], request_id="recover", expected_sha256=context.source_file.sha256
    )
    assert first["revisionRegistered"] is False
    service.repository.complete_revision = original
    monkeypatch.setattr(
        "smart_reporting.report_editor.native_publication.patch_docx",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must recover saved bytes")),
    )
    recovered = await service.save_revision(
        context, operations=[], request_id="recover", expected_sha256=context.source_file.sha256
    )
    assert recovered["revisionRegistered"] is True
    assert first["artifacts"]["word"]["sha256"] == recovered["artifacts"]["word"]["sha256"]
    await assert_downloads(recovered, downloads)


@pytest.mark.anyio
async def test_export_signs_word_pdf_together_without_invalidating_original(
    publication, monkeypatch
):
    service, context, downloads = publication
    from reportlab.pdfgen.canvas import Canvas

    from smart_reporting.reporting.delivery.publishing import ReportDownloadScope

    pdf = BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(30, 700, "native preview")
    canvas.save()
    monkeypatch.setattr(
        "smart_reporting.report_editor.native_publication.libreoffice_to_pdf",
        lambda *a, **k: pdf.getvalue(),
    )
    original_raw, _ = await service.download_grants.issue(
        scope=ReportDownloadScope(
            database="db",
            company_id="company",
            user_id="user",
            session_id="original",
            thread_id="original",
            workflow_run_id="original",
        ),
        report_id="original-report",
        revision=1,
        word_path=context.source_file.path,
        word_size=context.source_file.size,
        word_sha256=context.source_file.sha256,
    )
    issue = service.download_grants.issue
    service.download_grants.issue = AsyncMock(wraps=issue)
    result = await service.save_revision(
        context,
        operations=[],
        request_id="export",
        expected_sha256=context.source_file.sha256,
        export_pdf=True,
    )
    assert service.download_grants.issue.await_count == 1
    word_raw = result["artifacts"]["word"]["downloadUrl"].split("/")[-2]
    pdf_raw = result["artifacts"]["pdf"]["downloadUrl"].split("/")[-2]
    assert word_raw == pdf_raw
    _, chunks = await downloads.stream(pdf_raw, artifact="pdf")
    assert b"".join([chunk async for chunk in chunks]) == pdf.getvalue()
    assert (await service.download_grants.lookup(original_raw)).report_id == "original-report"
    await assert_downloads(result, downloads)


@pytest.mark.anyio
async def test_both_grants_failure_retains_identity_and_specific_issues(publication):
    service, context, _ = publication
    service.download_grants.issue = AsyncMock(side_effect=RuntimeError("primary unavailable"))
    service.editor_grants.issue = AsyncMock(side_effect=RuntimeError("fallback unavailable"))
    result = await service.save_revision(
        context, operations=[], request_id="grants", expected_sha256=context.source_file.sha256
    )
    assert "downloadUrl" not in result["artifacts"]["word"]
    assert result["artifacts"]["word"]["size"] > 0
    assert result["validation"]["ok"] is False
    codes = {item["code"] for item in result["validation"]["issues"]}
    assert {
        "native_download_grant_failed",
        "native_download_fallback_failed",
        "native_editor_grant_failed",
    } <= codes


@pytest.mark.anyio
async def test_saved_revision_with_missing_file_does_not_issue_that_format(publication):
    service, context, downloads = publication
    from smart_reporting.report_editor.native import bind_native_workspace

    first = await service.save_revision(
        context, operations=[], request_id="missing", expected_sha256=context.source_file.sha256
    )
    file = first["artifacts"]["word"]
    key = bind_native_workspace(service.workspace, context.scope)
    await service.workspace.adelete_registered_file(
        key, file["path"], size=file["size"], sha256=file["sha256"]
    )
    service.download_grants.issue = AsyncMock(wraps=service.download_grants.issue)
    result = await service.save_revision(
        context, operations=[], request_id="missing", expected_sha256=context.source_file.sha256
    )
    assert result["artifacts"] == {}
    service.download_grants.issue.assert_not_awaited()
    assert "native_word_identity_unavailable" in {
        item["code"] for item in result["validation"]["issues"]
    }


@pytest.mark.anyio
async def test_primary_identity_failure_still_publishes_independent_pdf(publication, monkeypatch):
    service, context, downloads = publication
    from reportlab.pdfgen.canvas import Canvas

    pdf = BytesIO()
    canvas = Canvas(pdf)
    canvas.drawString(30, 700, "retained PDF")
    canvas.save()
    monkeypatch.setattr(
        "smart_reporting.report_editor.native_publication.libreoffice_to_pdf",
        lambda *a, **k: pdf.getvalue(),
    )
    write = service._write_file

    async def write_with_broken_primary(key, path, content, media_type):
        identity = await write(key, path, content, media_type)
        if path.endswith(".docx"):
            raise OSError("primary identity read failed")
        return identity

    monkeypatch.setattr(service, "_write_file", write_with_broken_primary)
    result = await service.save_revision(
        context,
        operations=[],
        request_id="primary-fault",
        expected_sha256=context.source_file.sha256,
        export_pdf=True,
    )
    assert result["revisionRegistered"] is False
    assert "word" not in result["artifacts"]
    raw = result["artifacts"]["pdf"]["downloadUrl"].split("/")[-2]
    _, chunks = await downloads.stream(raw, artifact="pdf")
    assert b"".join([chunk async for chunk in chunks]) == pdf.getvalue()


@pytest.mark.anyio
async def test_damaged_recovery_record_does_not_block_own_verified_output(publication):
    service, context, downloads = publication
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_models import native_digest

    key = bind_native_workspace(service.workspace, context.scope)
    prefix = f"native/documents/{native_digest(context.document_id)}/r2"
    await service.workspace.awrite_bytes(key, f"{prefix}/saved.json", b"{corrupt")
    result = await service.save_revision(
        context, operations=[], request_id="damaged", expected_sha256=context.source_file.sha256
    )
    assert result["revisionRegistered"] is False
    assert "native_recovery_record_invalid" in {
        item["code"] for item in result["validation"]["issues"]
    }
    await assert_downloads(result, downloads)


@pytest.mark.anyio
async def test_two_service_workers_reuse_first_complete_receipt(publication, monkeypatch):
    import asyncio

    from smart_reporting.report_editor.native_publication import NativePublicationService

    service, context, downloads = publication
    other = NativePublicationService(
        service.repository,
        service.workspace,
        service.download_grants,
        service.editor_grants,
        artifact_persistence=service.artifact_persistence,
        public_base_url="http://test",
    )
    write = service.workspace.awrite_bytes
    started = 0
    gate = asyncio.Event()

    async def concurrent_write(key, path, content, **kwargs):
        nonlocal started
        if path.endswith(".docx"):
            started += 1
            if started == 2:
                gate.set()
            await gate.wait()
        return await write(key, path, content, **kwargs)

    monkeypatch.setattr(service.workspace, "awrite_bytes", concurrent_write)
    kwargs = dict(operations=[], request_id="workers", expected_sha256=context.source_file.sha256)
    first, second = await asyncio.gather(
        service.save_revision(context, **kwargs), other.save_revision(context, **kwargs)
    )
    assert first["revision"] == second["revision"] == 2
    assert first["artifacts"]["word"]["sha256"] == second["artifacts"]["word"]["sha256"]
    assert first["artifacts"]["word"]["path"] == second["artifacts"]["word"]["path"]
    # 复用既有grant轮换策略，两个并发响应中较早签发的链接可被后签发轮换。
    latest = await service.save_revision(context, **kwargs)
    await assert_downloads(latest, downloads)


@pytest.mark.anyio
async def test_native_pdf_save_runs_real_bridge_and_streams_changed_page(publication):
    from pypdf import PdfReader
    from reportlab.pdfgen.canvas import Canvas

    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.reporting.delivery.pdf_native import inspect_pdf

    service, old, downloads = publication
    source = BytesIO()
    canvas = Canvas(source)
    canvas.drawString(30, 700, "PDF ORIGINAL")
    canvas.save()
    content = source.getvalue()
    key = bind_native_workspace(service.workspace, old.scope)
    await service.workspace.awrite_bytes(key, "native/pdf-original.pdf", content)
    context = old.model_copy(
        update={
            "format": "pdf",
            "source_file": ArtifactFile(
                path="native/pdf-original.pdf",
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                mediaType="application/pdf",
            ),
        }
    )
    page = inspect_pdf(content)["pages"][0]["pageId"]
    result = await service.save_revision(
        context,
        operations=[{"kind": "rotatePage", "pageId": page, "delta": 90}],
        request_id="pdf-real",
        expected_sha256=context.source_file.sha256,
        note="页面旋转",
    )
    assert result["note"] == "页面旋转"
    raw = result["artifacts"]["pdf"]["downloadUrl"].split("/")[-2]
    _, chunks = await downloads.stream(raw, artifact="pdf")
    revised = b"".join([chunk async for chunk in chunks])
    assert PdfReader(BytesIO(revised)).pages[0].get("/Rotate") == 90
    assert "PDF ORIGINAL" in PdfReader(BytesIO(revised)).pages[0].extract_text()
    assert PdfReader(BytesIO(content)).pages[0].get("/Rotate", 0) == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    "operations",
    [
        [{"kind": "highlight", "rect": [float("nan"), 0, 1, 1]}],
        [{"kind": "replaceParagraph", "text": "x" * (12 * 1024 * 1024)}],
    ],
)
async def test_native_save_rejects_nonfinite_or_oversized_json_before_reserving(
    publication, operations
):
    from smart_reporting.reporting.models import ReportingError

    service, context, _ = publication
    with pytest.raises(ReportingError, match="native_operations_invalid"):
        await service.save_revision(
            context,
            operations=operations,
            request_id="invalid",
            expected_sha256=context.source_file.sha256,
        )
    assert service.repository.rows == {}
