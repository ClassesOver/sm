import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from smart_reporting.reporting_identity import (
    apply_report_identity,
    requires_workspace_capability,
)
from smart_reporting.security import CapabilityError, verify_capability

SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _capability(thread: str = "thread-1", **overrides) -> str:
    now = int(time.time())
    header = {"alg": "HS256", "typ": "WORKSPACE-CAP"}
    claims = {
        "aud": "agentos-workspace",
        "database": "odoo",
        "user": 7,
        "company": 3,
        "odoo_session": "a" * 64,
        "thread": thread,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)

    def segment(value) -> str:
        return (
            base64.urlsafe_b64encode(
                json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
            )
            .rstrip(b"=")
            .decode()
        )

    signing_input = f"{segment(header)}.{segment(claims)}"
    signature = (
        base64.urlsafe_b64encode(
            hmac.new(SECRET.encode(), signing_input.encode(), hashlib.sha256).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    return f"{signing_input}.{signature}"


def _app() -> FastAPI:
    application = FastAPI()

    @application.middleware("http")
    async def require_report_identity(request: Request, call_next):
        thread = str(request.headers.get("X-Workspace-Thread", "")).strip()
        capability = str(request.headers.get("X-Workspace-Capability", "")).strip()
        if not requires_workspace_capability(
            request.url.path,
            has_thread=bool(thread),
            has_capability=bool(capability),
        ):
            return await call_next(request)
        if not thread:
            return JSONResponse({"error": "thread_header_required"}, status_code=400)
        try:
            claims = verify_capability(capability, SECRET, thread)
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=401)
        apply_report_identity(
            request,
            user_id=str(claims.user),
            thread_id=thread,
            database=claims.database,
            company_id=str(claims.company),
        )
        return await call_next(request)

    @application.post("/agents/smart-reporting/runs")
    async def report_run(request: Request):
        return {
            "requestUserId": getattr(request.state, "user_id", None),
            "requestSessionId": getattr(request.state, "session_id", None),
            "requestDependencies": getattr(request.state, "dependencies", None),
        }

    @application.get("/workspace/files")
    async def workspace_files():
        return {"ok": True}

    @application.get("/agents/smart-reporting/runs/run-1/resume")
    async def resume_report_run(request: Request):
        async def body():
            yield f"{request.state.user_id}:{request.state.session_id}"

        return StreamingResponse(body())

    @application.get("/ready")
    async def ready():
        return {"ok": True}

    return application


@pytest.mark.anyio
async def test_reporting_run_without_capability_uses_native_agentos_identity() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post("/agents/smart-reporting/runs")

    assert response.status_code == 200
    assert response.json() == {
        "requestUserId": None,
        "requestSessionId": None,
        "requestDependencies": None,
    }


@pytest.mark.anyio
async def test_workspace_still_requires_odoo_capability() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/workspace/files")

    assert response.status_code == 400
    assert response.json() == {"error": "thread_header_required"}


@pytest.mark.parametrize(
    ("has_thread", "has_capability"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_report_download_link_does_not_require_workspace_capability(
    has_thread: bool,
    has_capability: bool,
) -> None:
    assert (
        requires_workspace_capability(
            "/reports/v1/download/opaque-grant",
            has_thread=has_thread,
            has_capability=has_capability,
        )
        is False
    )


@pytest.mark.parametrize(
    "path",
    [
        "/reports/v1/download/opaque-grant",
        "/reports/v1/download/opaque-grant/word",
        "/reports/v1/download/opaque-grant/html",
    ],
)
def test_all_report_download_formats_do_not_require_workspace_capability(path: str) -> None:
    assert requires_workspace_capability(path, has_thread=False, has_capability=False) is False


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("headers", "status_code", "error"),
    [
        (
            {"X-Workspace-Capability": _capability()},
            400,
            "thread_header_required",
        ),
        (
            {"X-Workspace-Thread": "thread-1"},
            401,
            "capability_invalid",
        ),
    ],
)
async def test_reporting_run_rejects_partial_workspace_identity(
    headers: dict[str, str], status_code: int, error: str
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post("/agents/smart-reporting/runs", headers=headers)

    assert response.status_code == status_code
    assert response.json() == {"error": error}


@pytest.mark.anyio
async def test_reporting_run_binds_all_odoo_identity_fields() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/agents/smart-reporting/runs",
            headers={
                "X-Workspace-Thread": "thread-1",
                "X-Workspace-Capability": _capability(),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "requestUserId": "7",
        "requestSessionId": "thread-1",
        "requestDependencies": {"AgentOS 报表工作流": {"database": "odoo", "companyId": "3"}},
    }


def test_apply_report_identity_binds_capability_tenant_to_agentos_dependencies() -> None:
    request = SimpleNamespace(state=SimpleNamespace())

    apply_report_identity(
        request,
        user_id="7",
        thread_id="thread-1",
        database="odoo",
        company_id="3",
    )

    assert request.state.dependencies == {
        "AgentOS 报表工作流": {"database": "odoo", "companyId": "3"}
    }


@pytest.mark.anyio
async def test_reporting_stream_keeps_request_identity_until_body_finishes() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get(
            "/agents/smart-reporting/runs/run-1/resume",
            headers={
                "X-Workspace-Thread": "thread-1",
                "X-Workspace-Capability": _capability(),
            },
        )

    assert response.status_code == 200
    assert response.text == "7:thread-1"


@pytest.mark.anyio
async def test_readiness_does_not_require_odoo_capability() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 200
