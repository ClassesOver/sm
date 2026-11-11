from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from smart_reporting.management.api import create_management_router
from smart_reporting.management.models import AdminAccount, AdminSessionInvalid
from smart_reporting.management.settings import ManagementSettings


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_management_static_defaults_to_packaged_bundle(monkeypatch):
    monkeypatch.delenv("AGENT_MANAGEMENT_STATIC_DIR", raising=False)
    monkeypatch.delenv("AGENT_REPORT_EDITOR_STATIC_DIR", raising=False)
    settings = ManagementSettings.from_environment()
    assert settings.static_dir == Path(__file__).resolve().parents[1] / "report_editor/static/management"


def test_management_static_uses_deployed_editor_bundle(monkeypatch):
    monkeypatch.delenv("AGENT_MANAGEMENT_STATIC_DIR", raising=False)
    monkeypatch.setenv("AGENT_REPORT_EDITOR_STATIC_DIR", "/opt/report-editor-static")
    assert ManagementSettings.from_environment().static_dir == Path("/opt/report-editor-static/management")
    monkeypatch.setenv("AGENT_MANAGEMENT_STATIC_DIR", "/custom/management")
    assert ManagementSettings.from_environment().static_dir == Path("/custom/management")


@pytest.mark.anyio
async def test_management_serves_login_assets_and_preserves_authentication(tmp_path):
    (tmp_path / "management.html").write_text('<div id="management-root">数据源管理</div>')
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/app.js").write_text("window.managementLoaded = true")
    auth = AsyncMock()
    auth.authenticate.side_effect = AdminSessionInvalid()
    app = FastAPI()
    app.include_router(create_management_router(auth, ManagementSettings(static_dir=tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.test") as client:
        response = await client.get("/management/login")
        assert response.status_code == 200
        assert "数据源管理" in response.text
        assert response.headers["cache-control"] == "no-store"
        response = await client.get("/management/assets/app.js")
        assert response.status_code == 200
        assert "managementLoaded" in response.text
        assert (await client.get("/management/assets/missing.js")).status_code == 404
        response = await client.get("/management/")
        assert response.status_code == 303
        assert response.headers["location"] == "/management/sources"
        response = await client.get("/management/sources")
        assert response.status_code == 303
        assert response.headers["location"].startswith("/management/login?returnTo=")
        assert (await client.get("/management/api/v1/me")).status_code == 401
        auth.authenticate.side_effect = None
        auth.authenticate.return_value = AdminAccount(1, "admin", "unused", 1)
        assert (await client.get("/management/sources")).status_code == 200
        assert (await client.get("/management/sources/new/view")).status_code == 200
        assert (await client.get("/management/unknown")).status_code == 404
        assert (await client.get("/management/api/v1/missing")).status_code == 404


@pytest.mark.anyio
async def test_explicit_missing_bundle_still_reports_unavailable(tmp_path):
    app = FastAPI()
    app.include_router(create_management_router(AsyncMock(), ManagementSettings(static_dir=tmp_path)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://reports.test") as client:
        result = await client.get("/management/login")
    assert result.status_code == 503
    assert result.json()["code"] == "management_frontend_unavailable"
