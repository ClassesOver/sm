from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from smart_reporting.report_editor.native import (
    NativeEditorService,
    bind_native_workspace,
)
from smart_reporting.report_editor.native_models import (
    NATIVE_ARTIFACT_KEYS,
    NativeArtifacts,
    NativeDocument,
    NativeEditorContext,
    NativeRevision,
    NativeScope,
)
from smart_reporting.reporting.delivery.artifacts_v1 import ArtifactFile


def source_pdf() -> bytes:
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(300, 400))
    for text in ("source page one", "source page two", "source page three"):
        canvas.drawString(24, 350, text)
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


class MemoryRepository:
    def __init__(self):
        self.documents = {}
        self.revisions = {}

    async def create_from_source(self, source, *, scope, request_id):
        key = (source.model_dump_json(), scope.model_dump_json(), request_id)
        if key in self.documents:
            return self.documents[key]
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
            origin=source.origin,
        )
        revision = NativeRevision(
            documentId=document.document_id,
            revision=1,
            scope=scope,
            requestId=request_id,
            requestSha256=hashlib.sha256(source.model_dump_json().encode()).hexdigest(),
            status="saved",
            context=context,
            artifacts=NativeArtifacts(
                **{NATIVE_ARTIFACT_KEYS[source.format]: source.source_file}
            ),
            createdAt=datetime.now(UTC),
        )
        self.documents[key] = document
        self.revisions[document.document_id] = revision
        return document

    async def get_revision(self, document_id, revision, *, scope):
        result = self.revisions.get(document_id)
        return (
            result
            if result and result.scope == scope and revision == result.revision
            else None
        )


async def extract_fixture(tmp_path):
    repository = MemoryRepository()

    from smart_reporting.reporting.tests.test_native_publication_nonblocking import (
        create_publication,
    )

    publication, _, downloads = await create_publication(tmp_path / "publication")
    workspace = publication.workspace

    scope = NativeScope(
        database="db", companyId="company", userId="user", threadId="thread"
    )
    thread = bind_native_workspace(workspace, scope)
    original = source_pdf()
    original_identity = ArtifactFile(
        path="native/source.pdf",
        size=len(original),
        sha256=hashlib.sha256(original).hexdigest(),
        mediaType="application/pdf",
    )
    await workspace.awrite_bytes(thread, original_identity.path, original)
    parent = NativeEditorContext(
        documentId="parent-document",
        format="pdf",
        revision=4,
        scope=scope,
        sourceFile=original_identity,
        origin="upload",
        parentRevision=3,
    )
    editor = NativeEditorService(
        workspace,
        repository,
        publication.editor_grants,
        pdf_enabled=True,
        publication=publication,
    )
    repository.revisions[parent.document_id] = NativeRevision(
        documentId=parent.document_id,
        revision=parent.revision,
        scope=scope,
        requestId="parent",
        requestSha256=original_identity.sha256,
        status="saved",
        context=parent,
        artifacts=NativeArtifacts(pdf=original_identity),
        createdAt=datetime.now(UTC),
    )
    return SimpleNamespace(
        editor=editor,
        parent=parent,
        repository=repository,
        workspace=workspace,
        thread=thread,
        original=original,
        original_identity=original_identity,
        publication=publication,
        downloads=downloads,
    )


@pytest.mark.anyio
async def test_extract_pages_registers_derived_pdf_with_parent_identity_and_grant(
    tmp_path,
):
    f = await extract_fixture(tmp_path)
    editor, parent, repository = f.editor, f.parent, f.repository

    result = await editor.extract_pages(
        parent, pages=[3, 1], request_id="extract-pages-1"
    )

    child = next(iter(repository.documents.values()))
    revision = repository.revisions[child.document_id]
    output, _ = await f.workspace.afile_bytes(f.thread, child.source.source_file.path)
    output_reader = PdfReader(BytesIO(output))
    original_after, _ = await f.workspace.afile_bytes(
        f.thread, f.original_identity.path
    )

    assert result["documentId"] == child.document_id
    assert result["revision"] == 1
    assert "/reports/v1/native/open/" in result["editor"]["openUrl"]
    assert result["artifacts"]["pdf"]["downloadUrl"]
    assert child.source.origin == "derived"
    assert child.source.parent_document_id == parent.document_id
    assert child.source.parent_revision == parent.revision
    assert child.source.parent_sha256 == f.original_identity.sha256
    assert revision.status == "saved"
    assert [page.extract_text().strip() for page in output_reader.pages] == [
        "source page three",
        "source page one",
    ]
    assert hashlib.sha256(output).hexdigest() == child.source.source_file.sha256
    assert original_after == f.original

    retry = await editor.extract_pages(
        parent, pages=[3, 1], request_id="extract-pages-1"
    )
    assert retry["documentId"] == result["documentId"]
    assert len(repository.documents) == 1


def test_derived_source_requires_parent_identity_without_changing_legacy_source_serialization():
    from pydantic import ValidationError

    from smart_reporting.report_editor.native_models import NativeSource

    identity = ArtifactFile(
        path="source.pdf", size=1, sha256="a" * 64, mediaType="application/pdf"
    )
    legacy = NativeSource(format="pdf", origin="upload", sourceFile=identity)
    assert set(legacy.model_dump()) == {
        "format",
        "origin",
        "source_file",
        "report_id",
        "workflow_run_id",
        "revision",
    }
    with pytest.raises(ValidationError):
        NativeSource(format="pdf", origin="derived", sourceFile=identity)
    with pytest.raises(ValidationError):
        NativeSource(
            format="pdf",
            origin="upload",
            sourceFile=identity,
            parentDocumentId="parent",
            parentRevision=1,
            parentSha256="a" * 64,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("fault", ["csrf", "origin", "sha", "revision", "boolean_page"])
async def test_extract_http_rejects_untrusted_requests_before_deriving_files(
    tmp_path, fault
):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor.native_api import (
        NATIVE_SESSION_COOKIE,
        create_native_editor_router,
    )

    f = await extract_fixture(tmp_path)
    raw, _ = await f.editor.grants.issue(
        f.parent, capabilities=f.editor.capabilities(f.parent)
    )
    token, _ = await f.editor.grants.exchange(raw)
    app = FastAPI()
    app.include_router(
        create_native_editor_router(
            f.editor.grants, editor=f.editor, cookie_secure=False
        )
    )
    base = f"/reports/v1/native/{f.parent.document_id}/{f.parent.revision}"
    headers = {
        "Origin": "http://test",
        "X-CSRF-Token": f.editor.grants.csrf_token(token),
    }
    payload = {
        "requestId": "bad-extract",
        "expectedSha256": f.parent.source_file.sha256,
        "pages": [1],
    }
    if fault == "csrf":
        headers.pop("X-CSRF-Token")
    elif fault == "origin":
        headers["Origin"] = "https://foreign.invalid"
    elif fault == "sha":
        payload["expectedSha256"] = "f" * 64
    elif fault == "boolean_page":
        payload["pages"] = [True]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        client.cookies.set(NATIVE_SESSION_COOKIE, token, path="/reports/v1/native")
        target = base if fault != "revision" else base.rsplit("/", 1)[0] + "/3"
        response = await client.post(
            target + "/api/extract-pages", headers=headers, json=payload
        )
    assert (
        response.status_code
        == {
            "csrf": 403,
            "origin": 403,
            "sha": 409,
            "revision": 403,
            "boolean_page": 422,
        }[fault]
    )
    assert f.repository.documents == {}
