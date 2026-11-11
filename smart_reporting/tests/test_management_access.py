from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from smart_reporting.tests.test_management_persistence import (
    NEW_PASSWORD,
    OLD_PASSWORD,
)
from smart_reporting.tests.test_management_persistence import (
    auth_context as auth_context,
)

pytestmark = [pytest.mark.anyio, pytest.mark.integration]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(auth_context):
    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.settings import ManagementSettings

    auth, _, _ = auth_context
    await auth.bootstrap(OLD_PASSWORD)
    app = FastAPI()
    app.include_router(
        create_management_router(
            auth,
            ManagementSettings(public_origin="https://reports.example"),
        )
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://reports.example"
    ) as value:
        yield value


async def login(client):
    result = await client.post(
        "/management/api/v1/auth/login",
        json={
            "username": "admin",
            "password": OLD_PASSWORD,
        },
        headers={"origin": "https://reports.example"},
    )
    assert result.status_code == 200
    return result


async def test_management_auth_cookie_origin_csrf_and_revocation(client):
    assert (await client.get("/management/api/v1/me")).status_code == 401
    assert (
        await client.post(
            "/management/api/v1/auth/login",
            json={
                "username": "admin",
                "password": OLD_PASSWORD,
            },
        )
    ).status_code == 403
    result = await login(client)
    cookie = result.headers["set-cookie"].lower()
    for attribute in ("httponly", "secure", "samesite=lax", "path=/management"):
        assert attribute in cookie
    me = await client.get("/management/api/v1/me")
    assert me.json()["username"] == "admin"
    assert "password" not in me.text
    csrf = me.json()["csrfToken"]
    response = await client.post(
        "/management/api/v1/auth/password",
        json={
            "currentPassword": OLD_PASSWORD,
            "newPassword": NEW_PASSWORD,
        },
        headers={"origin": "https://reports.example"},
    )
    assert response.status_code == 403
    old_cookie = client.cookies.get("report_management_session")
    response = await client.post(
        "/management/api/v1/auth/password",
        json={
            "currentPassword": OLD_PASSWORD,
            "newPassword": NEW_PASSWORD,
        },
        headers={"origin": "https://reports.example", "x-csrf-token": csrf},
    )
    assert response.status_code == 200
    response = await client.get(
        "/management/api/v1/me",
        headers={
            "cookie": f"report_management_session={old_cookie}",
        },
    )
    assert response.status_code == 401


async def test_editor_cookie_does_not_authorize_management_and_pages_redirect(client):
    response = await client.get(
        "/management/api/v1/me",
        headers={
            "cookie": "report_editor_session=arbitrary-editor-session",
        },
    )
    assert response.status_code == 401
    response = await client.get("/management/")
    assert response.status_code == 303
    assert response.headers["location"] == "/management/sources"
    response = await client.get("/management/sources")
    assert response.status_code == 303
    assert response.headers["location"].startswith("/management/login?returnTo=")


async def test_logout_is_server_side_and_idempotent(client):
    await login(client)
    me = (await client.get("/management/api/v1/me")).json()
    old = client.cookies.get("report_management_session")
    headers = {"origin": "https://reports.example", "x-csrf-token": me["csrfToken"]}
    assert (await client.post("/management/api/v1/auth/logout", headers=headers)).status_code == 200
    client.cookies.clear()
    assert (await client.post("/management/api/v1/auth/logout", headers=headers)).status_code == 200
    assert (
        await client.get(
            "/management/api/v1/me",
            headers={
                "cookie": f"report_management_session={old}",
            },
        )
    ).status_code == 401


async def test_management_report_issues_page_requires_admin(client):
    from urllib.parse import parse_qs, urlsplit

    target = "/management/report-issues?database=warehouse&companyId=100"
    response = await client.get(target)
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/management/login"
    assert parse_qs(location.query)["returnTo"] == [target]
    await login(client)
    response = await client.get(target)
    # 本 fixture 未部署前端；认证成功后应抵达静态页面检查，而非 404。
    assert response.status_code == 503
    assert response.json()["code"] == "management_frontend_unavailable"


async def test_audit_and_business_routes_require_admin(client):
    response = await client.get("/management/api/v1/audit")
    assert response.status_code == 401
    await login(client)
    response = await client.get("/management/api/v1/audit")
    assert response.status_code == 200
    assert any(item["action"] == "login_succeeded" for item in response.json()["items"])
    assert OLD_PASSWORD not in response.text


async def test_validation_errors_do_not_echo_passwords(client):
    sensitive = "sensitive-password-" * 20
    response = await client.post(
        "/management/api/v1/auth/login",
        json={
            "username": "admin",
            "password": sensitive,
        },
        headers={"origin": "https://reports.example"},
    )
    assert response.status_code == 422
    assert sensitive not in response.text
    assert "sensitive-password" not in response.text


async def test_database_unavailable_is_not_reported_as_invalid_credentials():
    from sqlalchemy.ext.asyncio import create_async_engine

    from smart_reporting.management.api import create_management_router
    from smart_reporting.management.auth import AdminAuthService
    from smart_reporting.management.repository import AdminRepository
    from smart_reporting.management.settings import ManagementSettings

    engine = create_async_engine(
        "postgresql+psycopg://unused@127.0.0.1:1/unused", connect_args={"connect_timeout": 1}
    )
    app = FastAPI()
    app.include_router(
        create_management_router(
            AdminAuthService(AdminRepository(engine)),
            ManagementSettings(public_origin="https://reports.example"),
        )
    )
    try:
        async with AsyncClient(
            transport=ASGITransport(app), base_url="https://reports.example"
        ) as client:
            result = await client.get(
                "/management/api/v1/me", headers={"cookie": "report_management_session=some-token"}
            )
        assert result.status_code == 503
        assert result.json()["code"] == "management_unavailable"
    finally:
        await engine.dispose()
