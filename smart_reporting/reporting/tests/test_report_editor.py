from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agno.run import RunContext
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from loguru import logger
from pydantic import ValidationError

from smart_reporting.report_editor import (
    InMemoryReportEditorRepository,
    ReportEditorContext,
    ReportEditorGrantService,
    ReportEditorService,
    SqlAlchemyReportEditorRepository,
    create_report_editor_router,
)
from smart_reporting.report_editor.api import EditorEventPayload, EditorExportPayload
from smart_reporting.reporting.delivery.publishing import (
    ReportDownloadAccessLogFilter,
    ReportDownloadGrant,
)
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.scope import ReportingWorkflowScope, reporting_scope_keys
from smart_reporting.reporting.workflow.state import (
    ReportingCommand,
    ReportingRunState,
    apply,
)
from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY
from smart_reporting.workspace import WorkspacePathConflict


def test_editor_export_settings_are_strict_and_whitelisted() -> None:
    payload = EditorExportPayload.model_validate(
        {
            "expectedSha256": "a" * 64,
            "settings": {"cover": True},
            "note": "运营数据复核后发布",
        }
    )
    assert payload.settings.model_dump(by_alias=True)["cover"] is True
    assert payload.note == "运营数据复核后发布"
    defaults = EditorExportPayload.model_validate({"expectedSha256": "a" * 64}).settings
    assert defaults is None
    with pytest.raises(ValidationError):
        EditorExportPayload.model_validate(
            {"expectedSha256": "a" * 64, "settings": {"cover": "true"}}
        )
    with pytest.raises(ValidationError):
        EditorExportPayload.model_validate(
            {"expectedSha256": "a" * 64, "settings": {"watermark": True}}
        )
    with pytest.raises(ValidationError):
        EditorExportPayload.model_validate({"expectedSha256": "a" * 64, "note": "x" * 201})


def test_editor_event_payload_rejects_content_and_unknown_events() -> None:
    event = EditorEventPayload.model_validate(
        {
            "event": "export_failed",
            "durationMs": 250,
            "format": "pdf",
            "errorCode": "report_editor_export_timeout",
        }
    )
    assert event.event == "export_failed"
    with pytest.raises(ValidationError):
        EditorEventPayload.model_validate({"event": "document_content", "durationMs": 1})
    with pytest.raises(ValidationError):
        EditorEventPayload.model_validate(
            {
                "event": "save_failed",
                "durationMs": 1,
                "markdown": "# 不应记录",
            }
        )


def test_sql_editor_repository_requires_postgresql() -> None:
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    with pytest.raises(ValueError, match="只支持 PostgreSQL"):
        SqlAlchemyReportEditorRepository(engine)  # type: ignore[arg-type]


def test_editor_context_digest_keeps_legacy_default_metadata_compatible() -> None:
    context = _context()
    legacy_payload = context.model_dump(mode="json", by_alias=True)
    for field in ("source", "createdAt", "note"):
        legacy_payload.pop(field)
    legacy_digest = hashlib.sha256(
        json.dumps(
            legacy_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()

    assert context.digest() == legacy_digest
    assert context.model_copy(update={"source": "manual"}).digest() != legacy_digest


def test_access_log_filter_redacts_editor_open_grant() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        "GET /reports/v1/editor/open/secret-grant HTTP/1.1",
        (),
        None,
    )

    ReportDownloadAccessLogFilter().filter(record)

    assert "secret-grant" not in str(record.msg)
    assert "/reports/v1/editor/open/<redacted>" in str(record.msg)


def _scope() -> ReportingWorkflowScope:
    keys = reporting_scope_keys(
        database="database-1",
        company_id="company-1",
        user_id="user-1",
        thread_id="caller-thread",
        run_id="report-1",
    )
    return ReportingWorkflowScope(
        run_id="report-1",
        external_run_id="external-1",
        session_id="workflow-session",
        caller_thread_id="caller-thread",
        user_id="user-1",
        database="database-1",
        company_id="company-1",
        thread_lease_key=keys.thread_lease_key,
        workspace_key=keys.workspace_key,
    )


def _context(markdown_path: str = "reports/revision-1/report.md") -> ReportEditorContext:
    return ReportEditorContext(
        reportId="report-1",
        revision=1,
        jobId="job-1",
        workflowRunId="report-1",
        markdownPath=markdown_path,
        job={"jobId": "job-1", "status": "validated"},
        scope=_scope().as_state(),
    )


@pytest.mark.anyio
async def test_editor_grant_is_reusable_but_rejects_tampering_and_expiry() -> None:
    now = datetime(2026, 9, 15, 8, tzinfo=UTC)
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(
        repository,
        secret="s" * 32,
        grant_ttl=timedelta(minutes=5),
        session_ttl=timedelta(hours=1),
    )

    raw, expires_at = await grants.issue(_context(), now=now)
    session_token, session = await grants.exchange(raw, now=now + timedelta(minutes=1))

    assert expires_at == now + timedelta(minutes=5)
    assert session.report_id == "report-1"
    assert await grants.lookup_session(session_token, now=now + timedelta(minutes=2)) == session
    # 链接可重复打开，每次兑换得到独立会话。
    second_token, second = await grants.exchange(raw, now=now + timedelta(minutes=2))
    assert second_token != session_token
    assert second.context_sha256 == session.context_sha256
    unregistered = ReportEditorGrantService(
        InMemoryReportEditorRepository(), secret="s" * 32, grant_ttl=timedelta(minutes=5)
    )
    with pytest.raises(ReportingError, match="无效"):
        await unregistered.exchange(raw, now=now + timedelta(minutes=2))
    with pytest.raises(ReportingError, match="无效"):
        await grants.exchange(f"{raw[:-1]}x", now=now + timedelta(minutes=2))

    expired, _ = await grants.issue(_context(), now=now)
    with pytest.raises(ReportingError, match="过期"):
        await grants.exchange(expired, now=now + timedelta(minutes=6))


@pytest.mark.anyio
async def test_editor_recovers_host_workspace_and_saves_draft_with_cas(tmp_path: Path) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", "# 原报告\n")
    registry.release(scope.workspace_key)
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": _context().model_dump(mode="json", by_alias=True)}}
    )
    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
    )

    document = await service.read_document(_context())
    saved = await service.save_draft(
        _context(), markdown="# 人工修订\n", expected_sha256=document.sha256
    )

    assert document.markdown == "# 原报告\n"
    assert saved.path == "reports/revision-1/draft/report.md"
    assert saved.sha256 == hashlib.sha256("# 人工修订\n".encode()).hexdigest()
    await workspace.awrite_text(
        scope.workspace_key,
        saved.path,
        "# 其他编辑\n",
        overwrite=True,
        expected_sha256=saved.sha256,
    )
    with pytest.raises(ReportingError, match="冲突"):
        await service.save_draft(_context(), markdown="# 过期编辑\n", expected_sha256=saved.sha256)


@pytest.mark.anyio
async def test_editor_open_exchanges_grant_for_http_only_cookie_without_token_url() -> None:
    now = datetime.now(UTC)
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context(), now=now)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, cookie_secure=False))

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        response = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/reports/v1/editor/report-1/1"
    assert raw not in response.headers["location"]
    cookie = response.headers["set-cookie"]
    assert "report_editor_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie


@pytest.mark.anyio
async def test_editor_document_api_binds_cookie_to_report_revision() -> None:
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context())

    class Editor:
        async def context_for_session(self, session):
            assert session.report_id == "report-1"
            return _context()

        async def read_document(self, context):
            assert context == _context()
            return SimpleNamespace(
                path="reports/revision-1/report.md",
                markdown="# 报告\n",
                sha256="a" * 64,
            )

    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=Editor(), cookie_secure=False))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        opened = await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        assert opened.status_code == 303
        loaded = await client.get("/reports/v1/editor/report-1/1/api/document")
        mismatched = await client.get("/reports/v1/editor/other-report/1/api/document")

    assert loaded.json() == {
        "path": "reports/revision-1/report.md",
        "markdown": "# 报告\n",
        "sha256": "a" * 64,
        "csrfToken": loaded.json()["csrfToken"],
    }
    assert len(loaded.json()["csrfToken"]) >= 32
    assert mismatched.status_code == 404


@pytest.mark.anyio
async def test_editor_api_exposes_registered_interactive_chart_and_hardened_json() -> None:
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context())
    image_path = "reports/revision-1/chart.png"
    spec_path = "reports/revision-1/chart.plotly.json"

    class Editor:
        async def context_for_session(self, _session):
            return _context()

        async def read_document(self, _context):
            return SimpleNamespace(
                path="reports/revision-1/report.md", markdown="![收入](chart.png)", sha256="a" * 64
            )

        async def interactive_charts(self, _context):
            return {image_path: spec_path}

        async def read_asset(self, _context, path):
            assert path == spec_path
            return b'{"data":[{"type":"bar"}]}', "application/json"

    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=Editor(), cookie_secure=False))
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        loaded = await client.get("/reports/v1/editor/report-1/1/api/document")
        resource = await client.get(f"/reports/v1/editor/report-1/1/asset/{spec_path}")

    assert loaded.json()["interactiveCharts"] == {image_path: spec_path}
    assert resource.status_code == 200
    assert resource.headers["content-type"].startswith("application/json")
    assert resource.headers["cache-control"] == "private, no-store"
    assert resource.headers["x-content-type-options"] == "nosniff"
    assert resource.headers["content-security-policy"] == "default-src 'none'"


@pytest.mark.anyio
async def test_editor_page_requires_session_and_sets_restrictive_csp(tmp_path: Path) -> None:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><main id='app'></main>")
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context())

    class Editor:
        async def context_for_session(self, _session):
            return _context()

    app = FastAPI()
    app.include_router(
        create_report_editor_router(
            grants,
            editor=Editor(),
            cookie_secure=False,
            static_dir=static,
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        unauthorized = await client.get("/reports/v1/editor/report-1/1")
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        response = await client.get("/reports/v1/editor/report-1/1")

    assert unauthorized.status_code == 404
    assert response.status_code == 200
    assert "id='app'" in response.text
    csp = response.headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "img-src 'self' data:" in csp
    assert "object-src 'none'" in csp
    assert "'unsafe-inline'" not in csp


@pytest.mark.anyio
async def test_editor_serves_only_unchanged_images_registered_by_current_job(
    tmp_path: Path,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    image = b"registered-image"
    image_path = "reports/charts/revenue.png"
    await workspace.awrite_bytes(scope.workspace_key, image_path, image)
    context = _context().model_copy(
        update={
            "job": {
                "jobId": "job-1",
                "render": {
                    "images": [
                        {
                            "path": image_path,
                            "size": len(image),
                            "sha256": hashlib.sha256(image).hexdigest(),
                        }
                    ]
                },
            }
        }
    )
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )
    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
    )

    content, media_type = await service.read_asset(context, image_path)

    assert content == image
    assert media_type == "image/png"
    with pytest.raises(ReportingError, match="不存在"):
        await service.read_asset(context, "reports/charts/other.png")
    await workspace.awrite_bytes(scope.workspace_key, image_path, b"changed", overwrite=True)
    with pytest.raises(ReportingError, match="变化"):
        await service.read_asset(context, image_path)


@pytest.mark.anyio
async def test_editor_serves_only_registered_unchanged_plotly_spec(tmp_path: Path) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    spec_path = "reports/revision-1/chart-001.plotly.json"
    image_path = "reports/revision-1/chart-001.png"
    spec = b'{"data":[{"type":"bar","x":[1],"y":[2]}]}'
    await workspace.awrite_bytes(scope.workspace_key, spec_path, spec)
    context = _context().model_copy(
        update={
            "job": {
                "jobId": "job-1",
                "render": {"images": []},
                "interactiveCharts": {
                    image_path: {
                        "path": spec_path,
                        "size": len(spec),
                        "sha256": hashlib.sha256(spec).hexdigest(),
                    }
                },
            }
        }
    )
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )
    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
    )

    content, media_type = await service.read_asset(context, spec_path)
    assert content == spec
    assert media_type == "application/json"
    assert (await service.read_asset(context, "chart-001.plotly.json"))[0] == spec
    assert await service.interactive_charts(context) == {image_path: spec_path}
    with pytest.raises(ReportingError, match="不存在"):
        await service.read_asset(context, "reports/revision-1/other.plotly.json")
    await workspace.awrite_bytes(scope.workspace_key, spec_path, b"changed", overwrite=True)
    with pytest.raises(ReportingError, match="变化"):
        await service.read_asset(context, spec_path)


@pytest.mark.anyio
async def test_editor_lists_persisted_report_revision_history(tmp_path: Path) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    first = _context()
    second = first.model_copy(
        update={
            "revision": 2,
            "markdown_path": "reports/revision-2/report.md",
            "source": "manual",
            "created_at": datetime(2026, 9, 16, 8, 30, tzinfo=UTC),
            "note": "运营数据复核后发布",
        }
    )
    await workspace.awrite_text(scope.workspace_key, first.markdown_path, "# 第一版\n")
    await workspace.awrite_text(scope.workspace_key, second.markdown_path, "# 第二版\n")
    state = SimpleNamespace(
        payload={
            "reportEditorContexts": {
                "1": first.model_dump(mode="json", by_alias=True),
                "2": second.model_dump(mode="json", by_alias=True),
            }
        }
    )
    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
    )

    history = await service.list_history(second)

    assert [(item["revision"], item["markdown"]) for item in history] == [
        (1, "# 第一版\n"),
        (2, "# 第二版\n"),
    ]

    metadata = await service.list_history(second, include_markdown=False)
    assert [item["revision"] for item in metadata] == [1, 2]
    assert metadata[1]["source"] == "manual"
    assert metadata[1]["createdAt"] == "2026-09-16T08:30:00+00:00"
    assert metadata[1]["note"] == "运营数据复核后发布"
    assert all("markdown" not in item for item in metadata)
    page = await service.list_history(second, limit=1, offset=1, include_markdown=False)
    assert page == [metadata[1]]
    full_page = await service.history_page(second)
    assert full_page == {"items": metadata, "total": 2, "hasMore": False}
    paged = await service.history_page(second, limit=1, offset=0)
    assert paged == {"items": [metadata[0]], "total": 2, "hasMore": True}
    detail = await service.read_history_revision(second, 1)
    assert detail == {
        "revision": 1,
        "markdown": "# 第一版\n",
        "sha256": hashlib.sha256("# 第一版\n".encode()).hexdigest(),
    }


@pytest.mark.anyio
async def test_editor_write_api_requires_same_origin_and_csrf() -> None:
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context())
    saved: list[str] = []

    class Editor:
        async def context_for_session(self, _session):
            return _context()

        async def read_document(self, _context):
            return SimpleNamespace(
                path="reports/revision-1/report.md",
                markdown="# 报告\n",
                sha256="a" * 64,
            )

        async def save_draft(self, _context, *, markdown: str, expected_sha256: str):
            assert expected_sha256 == "a" * 64
            saved.append(markdown)
            return SimpleNamespace(
                path="reports/revision-1/draft/report.md",
                markdown=markdown,
                sha256="b" * 64,
            )

        async def export_revision(self, _context, *, expected_sha256: str, request_id: str):
            assert expected_sha256 == "b" * 64
            assert request_id
            return {
                "reportId": "report-1",
                "revision": 2,
                "pdf": {"downloadUrl": "/reports/v1/download/pdf"},
                "word": {"downloadUrl": "/reports/v1/download/word"},
            }

    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=Editor(), cookie_secure=False))
    payload = {"markdown": "# 人工修订\n", "expectedSha256": "a" * 64}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        loaded = await client.get("/reports/v1/editor/report-1/1/api/document")
        csrf = loaded.json()["csrfToken"]
        missing_origin = await client.put(
            "/reports/v1/editor/report-1/1/api/document",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )
        wrong_csrf = await client.put(
            "/reports/v1/editor/report-1/1/api/document",
            json=payload,
            headers={"Origin": "http://reports.test", "X-CSRF-Token": "wrong"},
        )
        response = await client.put(
            "/reports/v1/editor/report-1/1/api/document",
            json=payload,
            headers={"Origin": "http://reports.test", "X-CSRF-Token": csrf},
        )
        exported = await client.post(
            "/reports/v1/editor/report-1/1/api/export",
            json={"expectedSha256": "b" * 64},
            headers={"Origin": "http://reports.test", "X-CSRF-Token": csrf},
        )

    assert missing_origin.status_code == 403
    assert wrong_csrf.status_code == 403
    assert response.json() == {
        "path": "reports/revision-1/draft/report.md",
        "markdown": "# 人工修订\n",
        "sha256": "b" * 64,
    }
    assert saved == ["# 人工修订\n"]
    assert exported.json()["revision"] == 2
    assert exported.json()["pdf"]["downloadUrl"] == "/reports/v1/download/pdf"


@pytest.mark.anyio
async def test_editor_event_api_logs_only_allowlisted_operational_fields() -> None:
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context())

    class Editor:
        async def context_for_session(self, _session):
            return _context()

        async def read_document(self, _context):
            return SimpleNamespace(
                path="reports/revision-1/report.md",
                markdown="# 私密报告正文\n",
                sha256="a" * 64,
            )

    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=Editor(), cookie_secure=False))
    messages: list[str] = []
    sink = logger.add(messages.append, level="INFO", format="{message}")
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://reports.test"
        ) as client:
            await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
            loaded = await client.get("/reports/v1/editor/report-1/1/api/document")
            response = await client.post(
                "/reports/v1/editor/report-1/1/api/events",
                json={
                    "event": "save_failed",
                    "durationMs": 25,
                    "errorCode": "report_editor_conflict",
                },
                headers={
                    "Origin": "http://reports.test",
                    "X-CSRF-Token": loaded.json()["csrfToken"],
                },
            )
    finally:
        logger.remove(sink)

    assert response.status_code == 204
    event_log = next(message for message in messages if "report_editor_event" in message)
    assert "save_failed" in event_log
    assert "report_editor_conflict" in event_log
    assert "私密报告正文" not in event_log


@pytest.mark.anyio
async def test_editor_ai_rewrite_requires_csrf_and_streams_markdown() -> None:
    repository = InMemoryReportEditorRepository()
    grants = ReportEditorGrantService(repository, secret="s" * 32)
    raw, _expires_at = await grants.issue(_context())
    calls: list[tuple[ReportEditorContext, str, str]] = []

    class Editor:
        async def context_for_session(self, _session):
            return _context()

        async def read_document(self, _context):
            return SimpleNamespace(
                path="reports/revision-1/report.md",
                markdown="# 报告\n",
                sha256="a" * 64,
            )

    class AI:
        async def stream_rewrite(self, context, *, selection: str, action: str):
            calls.append((context, selection, action))
            yield "改写后的"
            yield "正文"

    app = FastAPI()
    app.include_router(
        create_report_editor_router(
            grants,
            editor=Editor(),
            ai=AI(),
            cookie_secure=False,
        )
    )
    payload = {"selection": "原始正文", "action": "polish"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://reports.test"
    ) as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        loaded = await client.get("/reports/v1/editor/report-1/1/api/document")
        csrf = loaded.json()["csrfToken"]
        rejected = await client.post(
            "/reports/v1/editor/report-1/1/api/ai/rewrite",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )
        response = await client.post(
            "/reports/v1/editor/report-1/1/api/ai/rewrite",
            json=payload,
            headers={"Origin": "http://reports.test", "X-CSRF-Token": csrf},
        )

    assert rejected.status_code == 403
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.text == "改写后的正文"
    assert calls == [(_context(), "原始正文", "polish")]


@pytest.mark.anyio
async def test_editor_save_records_manual_revision_soft_warning(tmp_path: Path) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", "# 原报告\n")
    context = _context()
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )
    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
    )
    document = await service.read_document(context)
    messages: list[str] = []
    sink = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    try:
        await service.save_draft(context, markdown="# 人工修订\n", expected_sha256=document.sha256)
    finally:
        logger.remove(sink)

    assert any(
        "report_editor_manual_save" in message
        and "report-1" in message
        and document.sha256 in message
        for message in messages
    )


@pytest.mark.anyio
@pytest.mark.parametrize("editor_grant_fails", [False, True])
async def test_editor_export_creates_new_revision_without_overwriting_published_markdown(
    tmp_path: Path,
    editor_grant_fails: bool,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    job_id = str(uuid4())
    source_markdown = "# 原报告\n"
    draft_markdown = "# 人工修订\n"
    source_sha = hashlib.sha256(source_markdown.encode()).hexdigest()
    draft_sha = hashlib.sha256(draft_markdown.encode()).hexdigest()
    await workspace.awrite_text(
        scope.workspace_key, "reports/revision-1/report.md", source_markdown
    )
    await workspace.awrite_text(
        scope.workspace_key, "reports/revision-1/draft/report.md", draft_markdown
    )
    await workspace.awrite_bytes(scope.workspace_key, "reports/revision-1/report.pdf", b"old-pdf")
    await workspace.awrite_bytes(scope.workspace_key, "reports/revision-1/report.docx", b"old-word")
    image = b"chart-image"
    spec = b'{"data":[{"type":"bar","x":[1],"y":[2]}]}'
    await workspace.awrite_bytes(scope.workspace_key, "reports/revision-1/chart-001.png", image)
    await workspace.awrite_bytes(
        scope.workspace_key, "reports/revision-1/chart-001.plotly.json", spec
    )
    job = {
        "jobId": job_id,
        "_threadBinding": hashlib.sha256(scope.workspace_key.encode()).hexdigest(),
        "sources": [
            {
                "path": "reports/revision-1/report.md",
                "size": len(source_markdown.encode()),
                "sha256": source_sha,
            }
        ],
        "render": {
            "markdown": {
                "path": "reports/revision-1/report.md",
                "size": len(source_markdown.encode()),
                "sha256": source_sha,
            },
            "pdf": {
                "path": "reports/revision-1/report.pdf",
                "size": 7,
                "sha256": hashlib.sha256(b"old-pdf").hexdigest(),
            },
            "word": {
                "path": "reports/revision-1/report.docx",
                "size": 8,
                "sha256": hashlib.sha256(b"old-word").hexdigest(),
            },
            "images": [
                {
                    "path": "reports/revision-1/chart-001.png",
                    "size": len(image),
                    "sha256": hashlib.sha256(image).hexdigest(),
                }
            ],
        },
        "interactiveCharts": {
            "reports/revision-1/chart-001.png": {
                "path": "reports/revision-1/chart-001.plotly.json",
                "size": len(spec),
                "sha256": hashlib.sha256(spec).hexdigest(),
            }
        },
        "validation": {"ok": True},
    }
    context = ReportEditorContext(
        reportId="report-1",
        revision=1,
        jobId=job_id,
        workflowRunId="report-1",
        markdownPath="reports/revision-1/report.md",
        job=job,
        scope=scope.as_state(),
    )
    durable = SimpleNamespace(
        state_version=4,
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}},
    )

    class StateRepository:
        async def get(self, _run_id: str):
            return durable

        async def apply(self, _run_id: str, command, *, expected_version: int):
            assert expected_version == 4
            durable.payload.setdefault("reportEditorContexts", {})["2"] = command.payload["context"]
            durable.state_version += 1

    class ReportTools:
        async def _render_report_pair(
            self,
            actual_job_id: str,
            markdown_path: str,
            output_path: str,
            *,
            artifact_manifest,
            run_context: RunContext,
        ):
            assert actual_job_id == job_id
            assert markdown_path == "reports/revision-1/draft/report.md"
            assert output_path == "reports/revision-2/report.pdf"
            assert artifact_manifest is None
            assert run_context.session_state["report_workflow_scope"] == scope.as_state()
            assert run_context.session_state[REPORT_JOBS_STATE_KEY][job_id] == job
            await workspace.awrite_bytes(scope.workspace_key, output_path, b"new-pdf")
            word_path = str(Path(output_path).with_suffix(".docx"))
            await workspace.awrite_bytes(scope.workspace_key, word_path, b"new-word")
            stored = run_context.session_state[REPORT_JOBS_STATE_KEY][job_id]
            stored["render"] = {
                **stored["render"],
                "pdf": {
                    "path": output_path,
                    "size": 7,
                    "sha256": hashlib.sha256(b"new-pdf").hexdigest(),
                },
                "word": {
                    "path": word_path,
                    "size": 8,
                    "sha256": hashlib.sha256(b"new-word").hexdigest(),
                },
            }
            return {"status": "validated", "validation": {"ok": True}}

    persisted: list[object] = []

    class Persistence:
        async def persist(self, **values):
            persisted.extend(values["artifacts"])

    class DownloadGrants:
        async def issue(self, **values):
            return "download-raw", ReportDownloadGrant(
                grant_hash="d" * 64,
                scope=values["scope"],
                report_id=values["report_id"],
                revision=values["revision"],
                pdf_path=values["pdf_path"],
                pdf_size=values["pdf_size"],
                pdf_sha256=values["pdf_sha256"],
                word_path=values["word_path"],
                word_size=values["word_size"],
                word_sha256=values["word_sha256"],
                expires_at=datetime(2026, 10, 15, tzinfo=UTC),
            )

    class EditorGrants:
        async def issue(self, issued_context):
            if editor_grant_fails:
                raise RuntimeError("editor grant store unavailable")
            assert issued_context.revision == 2
            assert issued_context.source == "manual"
            assert issued_context.note == "运营数据复核后发布"
            assert issued_context.created_at is not None
            return "editor-raw", datetime(2026, 9, 15, 9, tzinfo=UTC)

    service = ReportEditorService(
        state_repository=StateRepository(),
        workspace_registry=registry,
        workspace=workspace,
        report_tools=ReportTools(),
        artifact_persistence=Persistence(),
        download_grants=DownloadGrants(),
        editor_grants=EditorGrants(),
        public_base_url="https://reports.example.com",
    )

    if editor_grant_fails:
        with pytest.raises(RuntimeError, match="editor grant store unavailable"):
            await service.export_revision(
                context, expected_sha256=draft_sha, note="运营数据复核后发布"
            )
        # 编辑上下文已提交后签发失败：revision-2 必须完整保留，与已提交状态一致。
        assert "2" in durable.payload["reportEditorContexts"]
        assert (
            await workspace.aread_text(scope.workspace_key, "reports/revision-2/report.md")
            == draft_markdown
        )
        assert await workspace.apath_exists(scope.workspace_key, "reports/revision-2/chart-001.png")
        return

    result = await service.export_revision(
        context,
        expected_sha256=draft_sha,
        note="运营数据复核后发布",
    )

    assert result["revision"] == 2
    assert result["pdf"]["downloadUrl"].endswith("/reports/v1/download/download-raw")
    assert result["editor"]["openUrl"].endswith("/reports/v1/editor/open/editor-raw")
    assert {item.artifact for item in persisted} == {"pdf", "word"}
    assert await workspace.aread_text(scope.workspace_key, context.markdown_path) == source_markdown
    assert (
        await workspace.aread_text(scope.workspace_key, "reports/revision-2/report.md")
        == draft_markdown
    )
    next_context = ReportEditorContext.model_validate(durable.payload["reportEditorContexts"]["2"])
    assert next_context.markdown_path == "reports/revision-2/report.md"
    assert next_context.job["render"]["pdf"]["path"] == "reports/revision-2/report.pdf"
    assert next_context.job["render"]["images"] == [
        {
            "path": "reports/revision-2/chart-001.png",
            "size": len(image),
            "sha256": hashlib.sha256(image).hexdigest(),
        }
    ]
    assert await service.interactive_charts(next_context) == {
        "reports/revision-2/chart-001.png": "reports/revision-2/chart-001.plotly.json"
    }
    assert (await service.read_asset(next_context, "chart-001.png"))[0] == image
    assert (await service.read_asset(next_context, "chart-001.plotly.json"))[0] == spec


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("occupied_path", "occupied_content"),
    [
        ("reports/revision-2/report.md", b"# existing\n"),
        ("reports/revision-2/report.pdf", b"existing-pdf"),
        ("reports/revision-2/report.docx", b"existing-word"),
    ],
)
async def test_editor_export_rejects_occupied_revision_before_rendering(
    tmp_path: Path,
    occupied_path: str,
    occupied_content: bytes,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    markdown = "# 人工修订\n"
    await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", markdown)
    await workspace.awrite_bytes(scope.workspace_key, occupied_path, occupied_content)
    context = ReportEditorContext(
        reportId="report-1",
        revision=1,
        jobId="job-1",
        workflowRunId="report-1",
        markdownPath="reports/revision-1/report.md",
        job={
            "jobId": "job-1",
            "render": {"pdf": {"path": "reports/revision-1/report.pdf"}},
        },
        scope=scope.as_state(),
    )
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )

    class ReportTools:
        calls = 0

        async def _render_report_pair(self, *_args, **_kwargs):
            self.calls += 1
            return {"validation": {"ok": True}}

    report_tools = ReportTools()
    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
        report_tools=report_tools,
        artifact_persistence=object(),
        download_grants=object(),
        editor_grants=object(),
        public_base_url="https://reports.example.com",
    )

    with pytest.raises(ReportingError) as raised:
        await service.export_revision(
            context,
            expected_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        )

    assert raised.value.code == "report_editor_revision_conflict"
    assert report_tools.calls == 0
    assert (await workspace.afile_bytes(scope.workspace_key, occupied_path))[0] == occupied_content


@pytest.mark.anyio
async def test_editor_export_maps_atomic_publish_race_to_revision_conflict(
    tmp_path: Path,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    markdown = "# 人工修订\n"
    await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", markdown)
    context = ReportEditorContext(
        reportId="report-1",
        revision=1,
        jobId="job-1",
        workflowRunId="report-1",
        markdownPath="reports/revision-1/report.md",
        job={
            "jobId": "job-1",
            "render": {"pdf": {"path": "reports/revision-1/report.pdf"}},
        },
        scope=scope.as_state(),
    )
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )

    class ReportTools:
        async def _render_report_pair(self, *_args, **_kwargs):
            raise WorkspacePathConflict("移动目标已经存在，请更换路径。")

    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
        report_tools=ReportTools(),
        artifact_persistence=object(),
        download_grants=object(),
        editor_grants=object(),
        public_base_url="https://reports.example.com",
    )

    with pytest.raises(ReportingError) as raised:
        await service.export_revision(
            context,
            expected_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
        )

    assert raised.value.code == "report_editor_revision_conflict"


@pytest.mark.anyio
async def test_editor_export_cleanup_removes_published_revision_on_failure(
    tmp_path: Path,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    await workspace.awrite_bytes(scope.workspace_key, "reports/revision-2/report.pdf", b"pdf")
    await workspace.awrite_bytes(scope.workspace_key, "reports/revision-2/report.docx", b"word")
    await workspace.awrite_text(scope.workspace_key, "reports/revision-2/report.md", "# draft\n")

    await ReportEditorService._cleanup_export_revision(
        workspace,
        scope.workspace_key,
        "reports/revision-2",
    )

    assert not await workspace.apath_exists(scope.workspace_key, "reports/revision-2")


@pytest.mark.anyio
async def test_editor_export_timeout_cleans_partial_revision_and_logs_request_id(
    tmp_path: Path,
) -> None:
    scope = _scope()
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    registry.resolve(scope)
    markdown = "# 人工修订\n"
    await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", markdown)
    context = ReportEditorContext(
        reportId="report-1",
        revision=1,
        jobId="job-1",
        workflowRunId="report-1",
        markdownPath="reports/revision-1/report.md",
        job={
            "jobId": "job-1",
            "render": {"pdf": {"path": "reports/revision-1/report.pdf"}},
        },
        scope=scope.as_state(),
    )
    state = SimpleNamespace(
        payload={"reportEditorContexts": {"1": context.model_dump(mode="json", by_alias=True)}}
    )

    class ReportTools:
        async def _render_report_pair(self, *_args, **_kwargs):
            await workspace.awrite_bytes(
                scope.workspace_key,
                "reports/revision-2/report.pdf",
                b"partial",
            )
            await asyncio.sleep(60)

    service = ReportEditorService(
        state_repository=SimpleNamespace(get=AsyncMock(return_value=state)),
        workspace_registry=registry,
        workspace=workspace,
        report_tools=ReportTools(),
        artifact_persistence=object(),
        download_grants=object(),
        editor_grants=object(),
        public_base_url="https://reports.example.com",
        export_timeout_seconds=0.01,
    )
    request_id = "01995f3d-7bd2-7000-8000-000000000001"
    messages: list[str] = []
    sink = logger.add(messages.append, level="INFO", format="{message}")
    try:
        with pytest.raises(ReportingError) as raised:
            await service.export_revision(
                context,
                expected_sha256=hashlib.sha256(markdown.encode()).hexdigest(),
                request_id=request_id,
            )
    finally:
        logger.remove(sink)

    assert raised.value.code == "report_editor_export_timeout"
    assert not await workspace.apath_exists(scope.workspace_key, "reports/revision-2")
    assert any(
        request_id in message and "report_editor_export_failed" in message for message in messages
    )


def test_editor_context_is_registered_as_immutable_durable_revision() -> None:
    state = ReportingRunState.initial(
        report_run_id="report-1",
        external_run_id="external-1",
        thread_id="caller-thread",
        owner_user_id="user-1",
    )
    command = ReportingCommand(
        name="set_report_editor_context",
        payload={"context": _context().model_dump(mode="json", by_alias=True)},
        commandId="editor-context:1",
    )

    updated = apply(state, command).state

    assert updated.payload["reportEditorContexts"]["1"] == command.payload["context"]
    changed = command.model_copy(
        update={
            "payload": {
                "context": _context("reports/revision-1/changed.md").model_dump(
                    mode="json", by_alias=True
                )
            },
            "command_id": "editor-context:changed",
        }
    )
    with pytest.raises(Exception, match="已绑定"):
        apply(updated, changed)
