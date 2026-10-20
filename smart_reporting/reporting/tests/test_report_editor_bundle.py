"""固定路由打包完整报告：真实工作区、授权、来源索引和无损压缩。"""

import hashlib
import io
import json
import os
import zipfile

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import ReportEditorContext, create_report_editor_router

from .test_report_editor_trace import CSV_BYTES, CSV_PATH, _make_editor

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]
URL = "/reports/v1/editor/report-1/1/export"


async def bundle_fixture(tmp_path, *, capabilities=None, extra=None):
    editor, grants, workspace = await _make_editor(
        tmp_path, with_fact_file=True, with_chart_trace=True, with_computation=True,
    )
    state = await editor.state_repository.get("report-1")
    context = ReportEditorContext.model_validate(state.payload["reportEditorContexts"]["1"])
    await editor._restore(context)
    files = {
        "reports/revision-1/report.pdf": b"%PDF-test",
        "reports/revision-1/report.docx": b"word-test",
        "analysis/plan.json": b'{"analysis": "revenue"}',
        **(extra or {}),
    }
    identities = {}
    for path, content in files.items():
        await workspace.awrite_bytes(context.scope["threadId"], path, content)
        identities[path] = {"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    context = context.model_copy(update={"job": {**context.job, "render": {
        "pdf": identities["reports/revision-1/report.pdf"],
        "word": identities["reports/revision-1/report.docx"],
    }, "validation": {"ok": False, "issues": [{"code": "semantic_warning"}]}}})
    state.payload["reportEditorContexts"]["1"] = context.model_dump(mode="json", by_alias=True)
    state.payload["workflowCheckpoint"] = {"files": list(identities.values())}
    # 同一工作区中的未登记文件不属于报告导出范围。
    await workspace.awrite_bytes(context.scope["threadId"], "other-report/secret.txt", b"foreign")
    raw, _ = await grants.issue(context, capabilities=capabilities)
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    return editor, context, raw, app


async def fetch(app, raw, url=URL):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        if raw:
            await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        return await client.get(url)


async def test_bundle_contains_all_registered_artifacts_despite_validation_warning(tmp_path):
    editor, context, raw, app = await bundle_fixture(tmp_path)
    result = await fetch(app, raw)
    assert result.status_code == 200, result.text
    assert result.headers["content-type"] == "application/zip"
    assert result.headers["cache-control"] == "no-store"
    assert "attachment;" in result.headers["content-disposition"]
    assert int(result.headers["content-length"]) == len(result.content) < 30 * 1024 * 1024
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        for name in ("reports/revision-1/report.md", "reports/revision-1/report.pdf",
                     "reports/revision-1/report.docx", "reports/revision-1/report.manifest.json",
                     "reports/revision-1/trace-index-v1.json", "analysis/plan.json",
                     "reports/revision-1/chart-001.png", CSV_PATH):
            assert name in names
        assert any(name.endswith("supplement.py") for name in names)
        assert any(name.endswith("supplement.json") for name in names)
        assert any(name.endswith("chart-input.json") for name in names)
        assert "other-report/secret.txt" not in names
        assert archive.read(CSV_PATH) == CSV_BYTES
        for item in archive.infolist():
            assert item.compress_type == zipfile.ZIP_LZMA
            if item.filename != "bundle.json":
                original = await editor.workspace.read_limited_regular_file(
                    context.scope["threadId"], item.filename, max_bytes=200 * 1024 * 1024)
                assert archive.read(item.filename) == original
        metadata = json.loads(archive.read("bundle.json"))
        assert metadata["reportId"] == "report-1"
        assert metadata["revision"] == 1
        assert metadata["validation"]["ok"] is False
    assert editor._source_lifecycle_locks == {}


@pytest.mark.parametrize("capabilities", [{}, {"download_original": False},
                         {"download_original": True, "blocked_columns": ["revenue"]}])
async def test_bundle_does_not_bypass_share_permissions(tmp_path, capabilities):
    _, _, raw, app = await bundle_fixture(tmp_path, capabilities=capabilities)
    result = await fetch(app, raw)
    assert result.status_code == 403
    assert result.json()["detail"]["code"] == "dataset_access_denied"


@pytest.mark.parametrize("raw_session,url", [(False, URL), (True, "/reports/v1/editor/other/1/export"),
                                            (True, "/reports/v1/editor/report-1/2/export")])
async def test_bundle_requires_matching_editor_session(tmp_path, raw_session, url):
    _, _, raw, app = await bundle_fixture(tmp_path)
    result = await fetch(app, raw if raw_session else None, url)
    assert result.status_code == 404


@pytest.mark.parametrize("change", ["modified", "deleted", "symlink"])
async def test_bundle_rejects_changed_source_without_partial_download(tmp_path, change):
    editor, context, raw, app = await bundle_fixture(tmp_path)
    root = editor.workspace_registry.get(context.scope["threadId"]).root
    path = root / CSV_PATH
    if change == "modified":
        path.write_bytes(CSV_BYTES.replace(b"1000", b"9999"))
    else:
        path.unlink()
        if change == "symlink":
            target = tmp_path / "outside.csv"
            target.write_bytes(CSV_BYTES)
            path.symlink_to(target)
    result = await fetch(app, raw)
    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "snapshot_integrity_failed"
    assert editor._source_lifecycle_locks == {}


async def test_bundle_compresses_large_source_without_truncating_it(tmp_path):
    content = b"2025-09,department,1000\n" * 1_500_000
    assert len(content) > 30 * 1024 * 1024
    _, _, raw, app = await bundle_fixture(tmp_path, extra={"analysis/large.csv": content})
    result = await fetch(app, raw)
    assert result.status_code == 200
    assert len(result.content) < 30 * 1024 * 1024
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert archive.read("analysis/large.csv") == content


async def test_bundle_refuses_oversize_archive_instead_of_dropping_artifacts(tmp_path):
    _, _, raw, app = await bundle_fixture(tmp_path, extra={
        "analysis/random.bin": os.urandom(31 * 1024 * 1024)})
    result = await fetch(app, raw)
    assert result.status_code == 413
    assert result.json()["detail"]["code"] == "resource_limit_exceeded"
