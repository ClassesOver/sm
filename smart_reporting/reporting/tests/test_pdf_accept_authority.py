"""Real ASGI/grants/service boundary; controlled preview, no PDF engine or save."""

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from time import monotonic
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.report_editor._file_identity import read_verified_file
from smart_reporting.report_editor.native_api import NATIVE_SESSION_COOKIE
from smart_reporting.report_editor.native_pdf_ai_tasks import _ReadJob
from smart_reporting.report_editor.native_pdf_form_ai_api import create_native_pdf_form_ai_router
from smart_reporting.report_editor.native_pdf_form_ai_tasks import NativePDFFormService
from smart_reporting.report_editor.native_pdf_review_ai_api import (
    create_native_pdf_review_ai_router,
)
from smart_reporting.report_editor.native_pdf_review_ai_tasks import NativePDFReviewService
from smart_reporting.report_editor.service import (
    InMemoryReportEditorRepository,
    ReportEditorGrantService,
    ReportEditorSession,
    token_hash,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("kind", ["forms", "review"])
@pytest.mark.parametrize(
    "fault", ["none", "revoke", "expiry", "context", "snapshot", "source", "capability"]
)
@pytest.mark.parametrize("window", ["preview", "context"])
async def test_pdf_accept_rechecks_authority_after_preview(kind, fault, window, tmp_path):
    source = b"synthetic unchanged source"
    workspace = ReportingWorkspaceRouter(ReportingWorkspaceRegistry(tmp_path, secret="w" * 32))
    from smart_reporting.report_editor.native import bind_native_workspace
    from smart_reporting.report_editor.native_models import NativeScope

    scope = NativeScope(database="db", companyId="company", userId="user", threadId="thread")
    key = bind_native_workspace(workspace, scope)
    await workspace.awrite_bytes(key, "native/source.pdf", source)
    sha = hashlib.sha256(source).hexdigest()
    context_digest = "a" * 64
    context = SimpleNamespace(
        format="pdf", source_file=SimpleNamespace(sha256=sha), digest=lambda: context_digest
    )
    entered, release = asyncio.Event(), asyncio.Event()
    receipt = dict(
        content=b"preview",
        size=7,
        sha256=hashlib.sha256(b"preview").hexdigest(),
        sourceSha256=sha,
        previewDigest="b" * 64,
        appliedOperationIndices=[],
        skippedOperations=[],
    )

    class Editor:
        save_calls = 0
        context_calls = 0

        def require_enabled(self, format):
            assert format == "pdf"

        async def context_for_session(self, session):
            self.context_calls += 1
            if window == "context" and self.context_calls == 3:
                entered.set()
                await release.wait()
            return context

        async def preview_file(self, context, **kwargs):
            if window == "preview":
                entered.set()
                await release.wait()
            return receipt

        async def read_file(self, context):
            return await read_verified_file(
                workspace,
                {"threadId": key},
                "native/source.pdf",
                size=len(source),
                sha256=sha,
                error_code="native_source_changed",
                format_name="PDF",
            )

        async def save(self, *args, **kwargs):
            self.save_calls += 1
            raise AssertionError("accept must not save")

    editor = Editor()
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="synthetic-test-only-secret-" * 2)
    raw = "synthetic-session"
    session = ReportEditorSession(
        "doc",
        1,
        "run",
        context_digest,
        datetime.now(UTC) + timedelta(seconds=0.3 if fault == "expiry" else 30),
    )
    await repository.put_session(token_hash(raw), session)
    cls = NativePDFFormService if kind == "forms" else NativePDFReviewService
    service = cls(editor, planner=None, enabled=True)
    job = _ReadJob("edit", "request", context_digest, monotonic(), "c" * 64, status="succeeded")
    job.base = []
    job.result = dict(
        operations=[],
        previewDigest="b" * 64,
        appliedOperationIndices=[],
        skippedOperations=[],
        changes=[],
        notes=[],
    )
    service._jobs[(context_digest, "request")] = job
    app = FastAPI()
    factory = (
        create_native_pdf_form_ai_router if kind == "forms" else create_native_pdf_review_ai_router
    )
    app.include_router(
        factory(grants, editor=editor, **{kind if kind == "forms" else "review": service})
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://test",
        cookies={NATIVE_SESSION_COOKIE: raw},
    ) as client:
        request = asyncio.create_task(
            client.post(
                f"/reports/v1/native/doc/1/api/ai/{kind}/edit/accept",
                headers={"origin": "https://test", "x-csrf-token": grants.csrf_token(raw)},
                json=dict(expectedSha256=sha, snapshotSha256="c" * 64, operations=[]),
            )
        )
        try:
            await asyncio.wait_for(entered.wait(), 3)
            if fault == "revoke":
                del repository.sessions[token_hash(raw)]
            elif fault == "expiry":
                assert datetime.now(UTC) < session.expires_at
                await asyncio.sleep((session.expires_at - datetime.now(UTC)).total_seconds() + 0.02)
                assert datetime.now(UTC) > session.expires_at
            elif fault == "context":
                context_digest = "d" * 64
            elif fault == "capability":
                from dataclasses import replace

                repository.sessions[token_hash(raw)] = replace(
                    session, capabilities={"native_editor": False}
                )
            elif fault == "source":
                await workspace.awrite_bytes(
                    key, "native/source.pdf", b"external change", overwrite=True
                )
            elif fault == "snapshot":
                job.snapshot_sha256 = "e" * 64
        finally:
            release.set()
        response = await asyncio.wait_for(request, 3)
    assert editor.save_calls == 0
    actual, _ = await workspace.afile_bytes(key, "native/source.pdf")
    assert actual == (b"external change" if fault == "source" else source)
    if fault == "none":
        assert response.status_code == 200, response.text
        assert response.json()["operations"] == []
    else:
        code = dict(
            revoke="report_editor_session_invalid",
            expiry="report_editor_session_expired",
            context="native_ai_preview_changed",
            snapshot="native_ai_snapshot_changed",
            source="native_source_changed",
            capability="native_permission_denied",
        )[fault]
        assert response.status_code == (
            403 if fault in {"revoke", "expiry", "capability"} else 409
        ), response.text
        assert response.json()["detail"]["code"] == code
        assert "operations" not in response.json()
