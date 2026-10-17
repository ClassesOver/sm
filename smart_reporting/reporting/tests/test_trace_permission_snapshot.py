"""列权限判断必须读取已核验的字节，不能受原路径替换影响。"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.report_editor import create_report_editor_router, trace_exports
from smart_reporting.reporting.trace import dataset_service

from .test_report_editor_trace import DATASET_ID, _context, _make_editor

pytestmark = [pytest.mark.anyio, pytest.mark.parametrize("anyio_backend", ["asyncio"])]


@pytest.mark.parametrize("derived", [False, True])
async def test_column_permission_check_cannot_be_swapped_before_download(tmp_path, monkeypatch, derived):
    editor, grants, _ = await _make_editor(tmp_path)
    try:
        raw, _ = await grants.issue(_context())
        _, owner = await grants.exchange(raw)
        if derived:
            started = await editor.trace_create_derived_export(
                _context(), owner, DATASET_ID, policy="masked_columns", params={"columns": ["visits"]},
            )
            export_id = started["exportId"]
            await editor.trace.exports._jobs[export_id].task
            path, _, _ = await editor.trace_derived_export_download(_context(), owner, export_id)
            suffix = f"data-exports/{export_id}/download"
            module = trace_exports
        else:
            path, _, _ = await editor.trace_dataset_download(_context(), owner, DATASET_ID)
            suffix = f"datasets/{DATASET_ID}/download"
            module = dataset_service
        path = Path(path)
        original = path.read_bytes()
        replacement_bytes = original.replace(b"revenue", b"allowed", 1)
        assert replacement_bytes != original and len(replacement_bytes) == len(original)
        read_header = module.read_csv_header
        checked_paths = []

        def swapped_header(target):
            checked_paths.append(Path(target))
            if Path(target) != path:
                return read_header(target)
            replacement = path.with_suffix(".swap")
            replacement.write_bytes(replacement_bytes)
            replacement.replace(path)
            try:
                return read_header(target)
            finally:
                replacement.write_bytes(original)
                replacement.replace(path)

        monkeypatch.setattr(module, "read_csv_header", swapped_header)
        raw, _ = await grants.issue(_context(), capabilities={
            "blocked_columns": ["revenue"], "download_original": True, "download_derived": True,
        })
        app = FastAPI()
        app.include_router(create_report_editor_router(grants, editor=editor, cookie_secure=False))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://reports.test") as client:
            await client.get(f"/reports/v1/editor/open/{raw}", follow_redirects=False)
            response = await client.get(f"/reports/v1/editor/report-1/1/api/{suffix}")
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "dataset_access_denied"
        assert checked_paths and all(target != path for target in checked_paths)
        assert all(not target.exists() for target in checked_paths)
        assert path.read_bytes() == original
    finally:
        await editor.aclose()
