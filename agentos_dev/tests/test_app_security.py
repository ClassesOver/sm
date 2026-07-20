import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest

from agentos_dev import app as app_module


SECRET = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app_module.app),
        base_url="http://testserver",
    ) as value:
        yield value


def capability(thread="thread-1", **overrides):
    now = int(time.time())
    header = {"alg": "HS256", "typ": "AGUI-CAP"}
    claims = {
        "aud": "agui-agentos-workspace",
        "database": "odoo",
        "user": 7,
        "company": 3,
        "odoo_session": "a" * 64,
        "thread": thread,
        "iat": now,
        "exp": now + 600,
    }
    claims.update(overrides)

    def segment(value):
        return base64.urlsafe_b64encode(
            json.dumps(value, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=").decode()

    signing_input = "%s.%s" % (segment(header), segment(claims))
    signature = base64.urlsafe_b64encode(hmac.new(
        SECRET.encode(), signing_input.encode(), hashlib.sha256,
    ).digest()).rstrip(b"=").decode()
    return "%s.%s" % (signing_input, signature)


@pytest.mark.anyio
async def test_public_config_and_protected_routes(monkeypatch, client):
    monkeypatch.setattr(app_module, "workspace_secret", SECRET)

    config = await client.get("/config")
    assert config.status_code == 200
    assert set(config.json()) == {
        "protocol", "bundle_version", "command_catalog_hash", "skills", "limits",
    }
    assert config.json()["limits"] == {
        "run_request_bytes": 2 * 1024 * 1024,
        "workspace_upload_request_bytes": 12 * 1024 * 1024,
        "json_mutation_request_bytes": 64 * 1024,
    }

    workspace = await client.get(
        "/workspace/files",
        params={"threadId": "thread-1"},
        headers={"X-AGUI-Thread": "thread-1"},
    )
    assert workspace.status_code == 401

    run = await client.post(
        "/agui",
        json={"threadId": "body-thread"},
        headers={
            "X-AGUI-Thread": "header-thread",
            "X-AGUI-Capability": capability("header-thread"),
        },
    )
    assert run.status_code == 403
    assert run.json() == {"error": "capability_thread_mismatch"}

    missing_thread = await client.post(
        "/agui",
        json={"threadId": "thread-1"},
        headers={"X-AGUI-Capability": capability()},
    )
    assert missing_thread.status_code == 400
    assert missing_thread.json() == {"error": "thread_header_required"}


@pytest.mark.anyio
async def test_branch_requires_controlled_props_and_matching_source_capability(monkeypatch, client):
    monkeypatch.setattr(app_module, "workspace_secret", SECRET)
    base_payload = {
        "threadId": "target-thread",
        "runId": "request-run",
        "state": {},
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    headers = {
        "X-AGUI-Thread": "target-thread",
        "X-AGUI-Capability": capability("target-thread"),
    }

    arbitrary = await client.post(
        "/agui",
        json={**base_payload, "forwardedProps": {"user_id": "admin"}},
        headers=headers,
    )
    assert arbitrary.status_code == 403
    assert arbitrary.json() == {"error": "forwarded_props_invalid"}

    branch_payload = {**base_payload, "forwardedProps": {"branch": {
        "sourceThreadId": "source-thread",
        "sourceRunId": "source-run",
        "targetMessageId": "answer-1",
    }}}
    missing_source = await client.post("/agui", json=branch_payload, headers=headers)
    assert missing_source.status_code == 401

    mismatched = await client.post(
        "/agui",
        json=branch_payload,
        headers={
            **headers,
            "X-AGUI-Source-Capability": capability("source-thread", user=8),
        },
    )
    assert mismatched.status_code == 403
    assert mismatched.json() == {"error": "branch_identity_mismatch"}


@pytest.mark.anyio
async def test_limited_json_body_is_replayed_to_workspace_route(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(app_module, "workspace_secret", SECRET)
    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(app_module.workspace_service, "destroy", lambda _thread: False)

    response = await client.request(
        "DELETE",
        "/workspace/sandbox",
        json={"threadId": "thread-1"},
        headers={
            "X-AGUI-Thread": "thread-1",
            "X-AGUI-Capability": capability(),
        },
    )

    assert response.status_code == 404
    assert response.json() == {"ok": True, "deleted": False}


@pytest.mark.anyio
async def test_http_上传保持覆盖路径的兼容调用语义(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    calls = []

    def upload(thread, path, content):
        calls.append((thread, path, content))
        return {"path": path, "size": len(content), "status": "synced"}

    monkeypatch.setattr(app_module, "workspace_secret", SECRET)
    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(app_module.workspace_service, "upload", upload)
    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }

    first = await client.post(
        "/workspace/upload",
        data={"threadId": "thread-1", "path": "报告.txt"},
        files={"file": ("报告.txt", b"first", "text/plain")},
        headers=headers,
    )
    second = await client.post(
        "/workspace/upload",
        data={"threadId": "thread-1", "path": "报告.txt"},
        files={"file": ("报告.txt", b"second", "text/plain")},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert calls == [
        ("thread-1", "报告.txt", b"first"),
        ("thread-1", "报告.txt", b"second"),
    ]


@pytest.mark.anyio
async def test_invalid_capability_is_rejected_before_large_run_body(monkeypatch, client):
    monkeypatch.setattr(app_module, "workspace_secret", SECRET)

    response = await client.post(
        "/agui",
        content=b"x" * (app_module.MAX_RUN_REQUEST_BYTES + 1),
        headers={"X-AGUI-Thread": "thread-1", "X-AGUI-Capability": "invalid"},
    )

    assert response.status_code == 401


@pytest.mark.anyio
async def test_chunked_request_limits_return_413(monkeypatch, client):
    monkeypatch.setattr(app_module, "workspace_secret", SECRET)
    headers = {
        "X-AGUI-Thread": "thread-1",
        "X-AGUI-Capability": capability(),
    }

    async def chunks():
        yield b"x" * app_module.MAX_RUN_REQUEST_BYTES
        yield b"x"

    response = await client.post(
        "/agui",
        content=chunks(),
        headers=headers,
    )
    mutation = await client.request(
        "DELETE",
        "/workspace/file",
        content=b"x" * (app_module.MAX_JSON_MUTATION_REQUEST_BYTES + 1),
        headers=headers,
    )

    async def upload_chunks():
        yield b"x" * app_module.MAX_WORKSPACE_UPLOAD_REQUEST_BYTES
        yield b"x"

    upload = await client.post(
        "/workspace/upload",
        content=upload_chunks(),
        headers=headers,
    )

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}
    assert mutation.status_code == 413
    assert upload.status_code == 413


@pytest.mark.anyio
async def test_ready_reports_all_required_checks(monkeypatch, client):
    async def inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(app_module, "run_in_threadpool", inline)
    monkeypatch.setattr(app_module, "_readiness_checks", lambda: {
        "postgresql": True, "sandbox_registry": True, "hmac": True,
    })
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    monkeypatch.setattr(app_module, "_readiness_checks", lambda: {
        "postgresql": True, "sandbox_registry": False, "hmac": True,
    })
    unavailable = await client.get("/ready")
    assert unavailable.status_code == 503
    assert unavailable.json()["status"] == "not_ready"
