"""真实 CSV 下载路由在文件替换时只发送已核验的快照。"""

import asyncio
import hashlib
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import FileResponse

from smart_reporting.report_editor import create_report_editor_router, trace_retention
from smart_reporting.reporting.models import ReportingError

from .test_report_editor_trace import DATASET_ID, _context, _make_editor

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


async def download_fixture(tmp_path, derived):
    editor, grants, _ = await _make_editor(tmp_path)
    raw, _ = await grants.issue(_context())
    _, session = await grants.exchange(raw)
    if derived:
        started = await editor.trace_create_derived_export(
            _context(), session, DATASET_ID,
            policy="masked_columns", params={"columns": ["revenue"]},
        )
        await editor.trace.exports._jobs[started["exportId"]].task
        method = "trace_derived_export_download"
        identifier = started["exportId"]
        suffix = f"data-exports/{identifier}/download"
    else:
        method = "trace_dataset_download"
        identifier = DATASET_ID
        suffix = f"datasets/{identifier}/download"
    path, _, _ = await getattr(editor, method)(_context(), session, identifier)
    # exchange 允许重复打开同一有效 grant，获取独立 HTTP 会话。
    app = FastAPI()
    app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
    return editor, raw, app, method, Path(path), f"/reports/v1/editor/report-1/1/api/{suffix}"


@pytest.mark.parametrize("derived", [False, True])
@pytest.mark.parametrize("replace_before_snapshot", [False, True])
async def test_download_never_sends_replaced_source(
    tmp_path, monkeypatch, derived, replace_before_snapshot,
):
    editor, raw, app, method, path, url = await download_fixture(tmp_path, derived)
    original = path.read_bytes()
    modified = original.replace(b"2025-08", b"1999-01")
    assert len(modified) == len(original) and modified != original
    download = getattr(editor, method)

    def replace_source():
        replacement = path.with_name(path.name + ".replacement")
        replacement.write_bytes(modified)
        replacement.replace(path)

    async def validate_then_replace(*args, **kwargs):
        result = await download(*args, **kwargs)
        if kwargs.get("include_identity") and replace_before_snapshot:
            replace_source()
        return result

    monkeypatch.setattr(editor, method, validate_then_replace)
    snapshots = []

    class SnapshotResponse(FileResponse):
        async def __call__(self, scope, receive, send):
            snapshots.append(Path(self.path))
            return await super().__call__(scope, receive, send)

    monkeypatch.setattr(trace_retention, "FileResponse", SnapshotResponse)

    async def application(scope, receive, send):
        async def replacing_send(message):
            if (scope["path"] == url and message["type"] == "http.response.start"
                    and message["status"] == 200 and not replace_before_snapshot):
                replace_source()
            await send(message)
        await app(scope, receive, replacing_send)

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://reports.test") as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        result = await client.get(url)
    if replace_before_snapshot:
        assert result.status_code == 409
        assert result.json()["detail"]["code"] == "snapshot_integrity_failed"
        assert snapshots == []
    else:
        assert result.status_code == 200
        assert result.content == original
        assert snapshots and all(snapshot != path and not snapshot.exists() for snapshot in snapshots)
    assert path.read_bytes() == modified


@pytest.mark.parametrize("derived,method,headers", [
    (False, "GET", {}), (False, "HEAD", {}), (False, "GET", {"Range": "bytes=0-7"}),
    (True, "GET", {}), (True, "GET", {"Range": "bytes=0-7"}),
])
async def test_download_snapshot_preserves_http_behavior(tmp_path, derived, method, headers):
    editor, raw, app, _, path, url = await download_fixture(tmp_path, derived)
    original = path.read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        result = await client.request(method, url, headers=headers)
    assert result.status_code == (206 if headers else 200)
    assert result.content == (b"" if method == "HEAD" else original[:8] if headers else original)
    assert result.headers["cache-control"] == "no-store"
    assert "attachment;" in result.headers["content-disposition"]
    assert int(result.headers["content-length"]) == (8 if headers else len(original))
    assert hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(original).digest()


@pytest.mark.parametrize("derived", [False, True])
async def test_download_if_range_uses_stable_content_identity(tmp_path, derived):
    _, raw, app, _, path, url = await download_fixture(tmp_path, derived)
    original = path.read_bytes()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
        await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
        first = await client.get(url)
        second = await client.get(url, headers={"Range": "bytes=0-7", "If-Range": first.headers["etag"]})
    assert first.status_code == 200
    assert second.status_code == 206
    assert first.headers["etag"] == second.headers["etag"]
    assert second.content == original[:8]


@pytest.mark.parametrize("derived", [False, True])
async def test_cancelled_download_removes_snapshot_and_releases_source_lock(tmp_path, monkeypatch, derived):
    editor, _, _, method, path, _ = await download_fixture(tmp_path, derived)
    snapshots = []

    class CancelledResponse(FileResponse):
        async def __call__(self, scope, receive, send):
            snapshots.append(Path(self.path))
            assert snapshots[-1].is_file()
            raise asyncio.CancelledError()

    monkeypatch.setattr(trace_retention, "FileResponse", CancelledResponse)
    content = path.read_bytes()

    async def validate():
        return str(path), "data.csv", len(content), hashlib.sha256(content).hexdigest()

    response = trace_retention.SourceFileResponse(path, service=editor, context=_context(), validate=validate)
    with pytest.raises(asyncio.CancelledError):
        await response({"type": "http", "method": "GET", "headers": []}, None, None)
    assert snapshots and all(not snapshot.exists() for snapshot in snapshots)
    assert editor._source_lifecycle_locks == {}
    assert path.read_bytes() == content


async def test_disconnected_download_does_not_start_a_second_response(tmp_path, monkeypatch):
    editor, _, _, _, path, _ = await download_fixture(tmp_path, False)
    snapshots = []

    class SnapshotResponse(FileResponse):
        async def __call__(self, scope, receive, send):
            snapshots.append(Path(self.path))
            return await super().__call__(scope, receive, send)

    monkeypatch.setattr(trace_retention, "FileResponse", SnapshotResponse)
    content = path.read_bytes()

    async def validate():
        return str(path), "data.csv", len(content), hashlib.sha256(content).hexdigest()

    messages = []

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body":
            raise OSError("connection closed")

    response = trace_retention.SourceFileResponse(path, service=editor, context=_context(), validate=validate)
    with pytest.raises(ReportingError, match="快照读取失败"):
        await response({"type": "http", "method": "GET", "headers": []}, None, send)
    assert len([message for message in messages if message["type"] == "http.response.start"]) == 1
    assert snapshots and all(not snapshot.exists() for snapshot in snapshots)
    assert editor._source_lifecycle_locks == {}
