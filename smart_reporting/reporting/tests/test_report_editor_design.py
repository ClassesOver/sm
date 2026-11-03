"""设计草稿、恢复与模板接口的持久化行为。"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.report_editor.service import ReportEditorService
from smart_reporting.reporting.delivery.report_design import ReportDesign
from smart_reporting.reporting.host_workspace import (
    ReportingWorkspaceRegistry,
    ReportingWorkspaceRouter,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_report_editor import _context, _scope


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def make_editor(tmp_path):
    registry = ReportingWorkspaceRegistry(tmp_path, secret="s" * 32)
    workspace = ReportingWorkspaceRouter(registry)
    scope = _scope()
    registry.resolve(scope)
    await workspace.awrite_text(scope.workspace_key, "reports/revision-1/report.md", "# 原报告\n")
    state = SimpleNamespace(payload={"reportEditorContexts": {"1": _context().model_dump(mode="json", by_alias=True)}})
    return ReportEditorService(state_repository=SimpleNamespace(get=AsyncMock(return_value=state)), workspace_registry=registry, workspace=workspace)


@pytest.mark.anyio
async def test_design_persists_independently_of_markdown_and_detects_stale_save(tmp_path):
    editor = await make_editor(tmp_path)
    before = await editor.read_document(_context())
    record = await editor.design.read(_context())
    design = ReportDesign.model_validate(record["design"])
    design.cover.title.text = "设计标题"
    design.watermark.enabled = False
    saved = await editor.design.save(_context(), design, record["designSha256"])
    assert saved["designSha256"] != record["designSha256"]
    with pytest.raises(ReportingError) as conflict:
        await editor.design.save(_context(), design, record["designSha256"])
    assert conflict.value.code == "report_editor_design_conflict"
    restarted = ReportEditorService(state_repository=editor.state_repository, workspace_registry=editor.workspace_registry, workspace=editor.workspace)
    assert (await restarted.design.read(_context()))["design"]["cover"]["title"]["text"] == "设计标题"
    assert (await editor.read_document(_context())).sha256 == before.sha256


@pytest.mark.anyio
async def test_restore_design_pending_selects_only_matching_markdown(tmp_path):
    editor = await make_editor(tmp_path)
    context = _context()
    _, _, original_sha = await editor._read_revision_markdown(context)
    design = ReportDesign()
    design.cover.title.text = "历史标题"
    await editor.design.prepare_restore(context, original_sha, "f" * 64, design)
    assert (await editor.design.read(context))["design"]["cover"]["title"]["text"] is None
    # 恢复写入中断时，当前正文仍是原文，不得提前读取历史设计。
    await editor.workspace.awrite_text(_scope().workspace_key, "reports/revision-1/draft/report.md", "历史正文")
    import hashlib
    pending_sha = hashlib.sha256("历史正文".encode()).hexdigest()
    await editor.design.prepare_restore(context, pending_sha, pending_sha, design)
    assert (await editor.design.read(context))["design"]["cover"]["title"]["text"] == "历史标题"


@pytest.mark.anyio
async def test_personal_templates_rebind_report_text_and_survive_repository_reuse():
    from smart_reporting.report_editor.design_repository import InMemoryDesignTemplateRepository
    repo = InMemoryDesignTemplateRepository()
    design = ReportDesign()
    design.cover.title.text = "旧标题"
    design.watermark.text = "内部资料"
    saved = await repo.save("u1", "t1", "年度模板", design)
    assert saved["design"]["cover"]["title"]["text"] is None
    assert saved["design"]["watermark"]["text"] == "内部资料"
    assert await repo.list("u2") == []
    assert (await repo.list("u1"))[0]["name"] == "年度模板"
    assert await repo.delete("u2", "t1") is False
    assert await repo.delete("u1", "t1") is True
    assert await repo.list("u1") == []


@pytest.mark.anyio
async def test_design_api_requires_csrf_and_returns_persisted_design(tmp_path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
        create_report_editor_router,
    )
    from smart_reporting.report_editor.design_repository import InMemoryDesignTemplateRepository
    editor = await make_editor(tmp_path)
    editor.design_templates = InMemoryDesignTemplateRepository()
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    token, _ = await grants.issue(_context())
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.get(f"/reports/v1/editor/open/{token}")
        base = "/reports/v1/editor/report-1/1/api"
        record = (await client.get(base + "/design")).json()
        design = record["design"]
        design["watermark"]["enabled"] = False
        payload = {"design": design, "expectedDesignSha256": record["designSha256"]}
        assert (await client.put(base + "/design", json=payload)).status_code == 403
        headers = {"Origin": "http://testserver", "X-CSRF-Token": grants.csrf_token(client.cookies["report_editor_session"])}
        saved = await client.put(base + "/design", json=payload, headers=headers)
        assert saved.status_code == 200
        assert (await client.get(base + "/document")).json()["design"]["watermark"]["enabled"] is False
        assert (await client.put(base + "/design", json=payload, headers=headers)).status_code == 409
        template = await client.put(base + "/design-templates/t1", json={"name": "简约", "design": design}, headers=headers)
        assert template.status_code == 200
        assert len((await client.get(base + "/design-templates")).json()["items"]) == 1


@pytest.mark.anyio
async def test_shared_session_cannot_change_design_or_manage_personal_templates(tmp_path):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from smart_reporting.report_editor import (
        InMemoryReportEditorRepository,
        ReportEditorGrantService,
        create_report_editor_router,
    )
    editor = await make_editor(tmp_path)
    grants = ReportEditorGrantService(InMemoryReportEditorRepository(), secret="s" * 32)
    token, _ = await grants.issue(_context(), capabilities={"download_original": False})
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await client.get(f"/reports/v1/editor/open/{token}")
        base = "/reports/v1/editor/report-1/1/api"
        record = (await client.get(base + "/design")).json()
        headers = {"Origin": "http://testserver", "X-CSRF-Token": grants.csrf_token(client.cookies["report_editor_session"])}
        assert (await client.put(base + "/design", json={"design": record["design"], "expectedDesignSha256": record["designSha256"]}, headers=headers)).status_code == 403
        assert (await client.get(base + "/design-templates")).status_code == 403


@pytest.mark.anyio
async def test_preview_freezes_design_without_creating_revision_and_checks_file_identity(tmp_path):
    from smart_reporting.reporting.workspace import REPORT_JOBS_STATE_KEY
    editor = await make_editor(tmp_path)
    context = _context()
    document = await editor.read_document(context)
    record = await editor.design.read(context)
    captured = []
    editor._lineage_features["exportSources"] = False
    async def render(job_id, markdown_path, output_path, *, run_context, **kwargs):
        state = run_context.session_state[REPORT_JOBS_STATE_KEY][job_id]
        captured.append(state["_reportDesign"])
        assert state["_editorExportSettings"]["sources"] is False
        await editor.workspace.awrite_bytes(context.scope["threadId"], output_path, b"%PDF preview")
        return {"pdfPath": output_path, "validation": {"ok": False, "issues": [{"message": "示例告警"}]}}
    editor.report_tools = SimpleNamespace(_render_report_pair=render)
    started = await editor.design_preview.start(context, document.sha256, record["designSha256"])
    task = editor.design_preview.jobs[started["previewId"]].task
    await task
    status = await editor.design_preview.status(context, started["previewId"])
    assert status["status"] == "succeeded"
    assert status["validation"]["ok"] is False
    assert ReportDesign.model_validate(captured[0]).cover.title.size == 28
    assert await editor.design_preview.pdf(context, started["previewId"]) == b"%PDF preview"
    assert not await editor.workspace.apath_exists(context.scope["threadId"], "reports/revision-2")
    path = status["pdfPath"]
    await editor.workspace.awrite_bytes(context.scope["threadId"], path, b"changed", overwrite=True)
    with pytest.raises(ReportingError):
        await editor.design_preview.pdf(context, started["previewId"])
    await editor.design_preview.aclose()
    assert not await editor.workspace.apath_exists(context.scope["threadId"], str(__import__('pathlib').PurePosixPath(path).parent))


@pytest.mark.anyio
async def test_restore_identical_body_commits_design_and_historical_source_together(tmp_path):
    from smart_reporting.reporting.tests.test_report_editor_history_restore import _setup
    editor, _, historical, current, old = await _setup(tmp_path)
    historical_design = ReportDesign()
    historical_design.cover.title.text = "历史封面"
    historical = historical.model_copy(update={"job": {**historical.job, "_reportDesign": historical_design.model_dump(mode="json", by_alias=True)}})
    state = await editor.state_repository.get(current.workflow_run_id)
    state.payload["reportEditorContexts"]["1"] = historical.model_dump(mode="json", by_alias=True)
    document = await editor.read_document(current)
    saved = await editor.save_draft(current, markdown=old, expected_sha256=document.sha256)
    assert saved.source_revision == 2
    restored = await editor.restore_history(current, 1, expected_sha256=saved.sha256)
    assert restored.sha256 == saved.sha256
    assert restored.source_revision == 1
    assert (await editor.design.read(current))["design"]["cover"]["title"]["text"] == "历史封面"
    # 后续编辑和设计保存均不得回退到当前修订的数据来源。
    record = await editor.design.read(current)
    await editor.design.save(current, ReportDesign.model_validate(record["design"]), record["designSha256"])
    edited = await editor.save_draft(current, markdown=old + "\n编辑", expected_sha256=restored.sha256)
    assert edited.source_revision == 1
    assert (await editor.read_document(current)).source_revision == 1


@pytest.mark.anyio
async def test_identical_body_design_restore_protects_historical_sources(tmp_path):
    from datetime import UTC, datetime

    from smart_reporting.reporting.tests.test_report_editor_retention import _make_shared_revisions
    editor, _, first, second, _ = await _make_shared_revisions(tmp_path)
    old = (await editor.read_document(first)).markdown
    before = await editor.read_document(second)
    saved = await editor.save_draft(second, markdown=old, expected_sha256=before.sha256)
    await editor.restore_history(second, 1, expected_sha256=saved.sha256)
    now = datetime(2026, 10, 1, tzinfo=UTC)
    await editor.set_revision_retention(first, expires_at=now)
    result = await editor.preview_revision_source_cleanup(second, now=now)
    assert result["protectedRevisions"] == [1, 2]
    assert result["candidateFiles"] == []
