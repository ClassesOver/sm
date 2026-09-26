from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from smart_reporting.integrations.dingyi_process import DingyiProcessAdapter

_OPERATION = {
    "operationId": "op-1",
    "sessionId": "thread-a",
    "runId": "run-1",
    "title": "生成报告",
    "execution": "foreground",
    "status": "running",
    "component": {"type": "agent", "id": "smart-reporting"},
    "updatedAt": "2026-09-26T00:00:00.000Z",
}


class _Journal:
    replay_retention_seconds = 60

    def snapshot(self, operation_id: str):
        if operation_id != "op-1":
            raise KeyError(operation_id)
        return {
            "protocol": "dingyi.process.v1",
            "sequence": 1,
            "operation": _OPERATION,
            "activities": [],
        }

    def list_operations(self, session_id, *, owner, run_id, limit, cursor):
        items = [_OPERATION] if session_id == "thread-a" else []
        return {"items": items, "nextCursor": None}

    def owner(self, operation_id: str):
        return "smart-reporting"


def _application(thread: str | None) -> FastAPI:
    adapter = DingyiProcessAdapter(engine=None)
    adapter._journal = _Journal()  # type: ignore[assignment]
    application = FastAPI()

    @application.middleware("http")
    async def verified_capability(request: Request, call_next):
        # 生产中间件在携带 X-Workspace-Capability 时写入验签结果。
        if thread is not None:
            request.state.capability = SimpleNamespace(thread=thread)
        return await call_next(request)

    application.include_router(adapter.router)
    return application


async def _get(application: FastAPI, path: str):
    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        return await client.get(f"/extensions/dingyi/process/v1{path}")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path", ["/sessions/thread-a/operations", "/operations/op-1", "/capabilities"]
)
async def test_process_extension_rejects_requests_without_verified_capability(path: str):
    response = await _get(_application(None), path)

    assert response.status_code == 401


@pytest.mark.anyio
async def test_process_extension_scopes_access_to_capability_thread():
    own = _application("thread-a")
    other = _application("thread-b")

    assert (await _get(own, "/sessions/thread-a/operations")).status_code == 200
    assert (await _get(own, "/operations/op-1")).json()["operation"]["operationId"] == "op-1"
    assert (await _get(other, "/sessions/thread-a/operations")).status_code == 404
    assert (await _get(other, "/operations/op-1")).status_code == 404
