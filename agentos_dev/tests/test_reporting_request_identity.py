import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agentos_dev.reporting_identity import (
    ReportServerIdentity,
    apply_report_identity,
    bind_report_identity,
    current_report_identity,
    is_report_run_path,
)
from agentos_dev.security import CapabilityError, verify_capability

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
        if not is_report_run_path(request.url.path):
            return await call_next(request)
        thread = str(request.headers.get("X-Workspace-Thread", "")).strip()
        if not thread:
            return JSONResponse({"error": "thread_header_required"}, status_code=400)
        try:
            claims = verify_capability(
                request.headers.get("X-Workspace-Capability", ""), SECRET, thread
            )
        except CapabilityError as error:
            return JSONResponse({"error": str(error)}, status_code=401)
        identity = ReportServerIdentity(
            database=claims.database,
            user_id=str(claims.user),
            company_id=str(claims.company),
            session_id=claims.odoo_session,
            thread_id=thread,
        )
        apply_report_identity(request, identity)
        with bind_report_identity(identity):
            return await call_next(request)

    @application.post("/agents/report-agent/runs")
    async def report_run(request: Request):
        identity = current_report_identity()
        assert identity is not None
        return {
            "database": identity.database,
            "userId": identity.user_id,
            "companyId": identity.company_id,
            "sessionId": identity.session_id,
            "threadId": identity.thread_id,
            "requestUserId": request.state.user_id,
            "requestSessionId": request.state.session_id,
        }

    @application.get("/agents/report-agent/runs/run-1/resume")
    async def resume_report_run():
        async def body():
            identity = current_report_identity()
            yield identity.database if identity is not None else "missing"

        return StreamingResponse(body())

    @application.get("/ready")
    async def ready():
        return {"ok": True}

    return application


@pytest.mark.anyio
async def test_reporting_run_requires_odoo_capability() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post("/agents/report-agent/runs")

    assert response.status_code == 400
    assert response.json() == {"error": "thread_header_required"}


@pytest.mark.anyio
async def test_reporting_run_binds_all_odoo_identity_fields() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.post(
            "/agents/report-agent/runs",
            headers={
                "X-Workspace-Thread": "thread-1",
                "X-Workspace-Capability": _capability(),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "database": "odoo",
        "userId": "7",
        "companyId": "3",
        "sessionId": "a" * 64,
        "threadId": "thread-1",
        "requestUserId": "7",
        "requestSessionId": "thread-1",
    }
    assert current_report_identity() is None


@pytest.mark.anyio
async def test_reporting_stream_keeps_identity_until_body_finishes() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get(
            "/agents/report-agent/runs/run-1/resume",
            headers={
                "X-Workspace-Thread": "thread-1",
                "X-Workspace-Capability": _capability(),
            },
        )

    assert response.status_code == 200
    assert response.text == "odoo"
    assert current_report_identity() is None


@pytest.mark.anyio
async def test_readiness_does_not_require_odoo_capability() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://test"
    ) as client:
        response = await client.get("/ready")

    assert response.status_code == 200
