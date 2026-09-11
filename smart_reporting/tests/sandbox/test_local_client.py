from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from smart_reporting.sandbox import (
    CodeRunRequest,
    ExecutionStatus,
    ProviderKind,
    SandboxNotFound,
    WorkspaceBinding,
)
from smart_reporting.sandbox.local.client import LocalProvider
from smart_reporting.sandbox.local.config import LocalProviderConfig


class MemoryRegistryTransaction:
    def __init__(self, values: dict[str, str], bindings: dict[str, object]) -> None:
        self.values = values
        self.bindings = bindings

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def set_binding(self, record: object) -> None:
        digest = record.binding_digest  # type: ignore[attr-defined]
        self.bindings[digest] = record
        self.values[digest] = record.resource_id  # type: ignore[attr-defined]


class MemoryRegistry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.bindings: dict[str, object] = {}

    @asynccontextmanager
    async def locked(self, _key: str):
        yield MemoryRegistryTransaction(self.values, self.bindings)


def _binding() -> WorkspaceBinding:
    return WorkspaceBinding(
        tenant_id="tenant",
        user_id="user",
        company_id="company",
        thread_id="thread",
        idempotency_key="request-00000001",
        profile="ubuntu",
    )


@pytest.mark.anyio
async def test_local_client_sends_binding_on_every_workspace_request() -> None:
    requests: list[httpx.Request] = []
    registry = MemoryRegistry()

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ref": {
                    "provider": "local",
                    "isolation": "linux_process",
                    "node": "node-a",
                    "resource_id": "local-1",
                    "generation": 1,
                    "binding_digest": request.headers["x-sandbox-binding"],
                    "dependency_bundle_digest": "sha256:" + "b" * 64,
                },
                "state": "started",
            },
        )

    provider = LocalProvider(
        LocalProviderConfig(
            profile="ubuntu",
            endpoint="unix:///run/local-sandboxd.sock",
            rootfs_digest="sha256:" + "a" * 64,
        ),
        registry=registry,
        binding_secret=b"0123456789abcdef0123456789abcdef",
        transport=httpx.MockTransport(respond),
    )

    handle = await provider.ensure_workspace(_binding())

    assert handle.ref.provider == ProviderKind.LOCAL
    assert requests[0].headers["x-sandbox-binding"] == handle.ref.binding_digest
    assert requests[0].headers["idempotency-key"] == "request-00000001"
    assert json.loads(requests[0].content)["profile"] == "ubuntu"
    assert registry.bindings[handle.ref.binding_digest].provider == ProviderKind.LOCAL
    assert registry.bindings[handle.ref.binding_digest].node == "node-a"  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_local_client_maps_stable_error_response() -> None:
    provider = LocalProvider(
        LocalProviderConfig(
            profile="ubuntu",
            endpoint="unix:///run/local-sandboxd.sock",
            rootfs_digest="sha256:" + "a" * 64,
        ),
        registry=MemoryRegistry(),
        binding_secret=b"0123456789abcdef0123456789abcdef",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                404,
                json={
                    "code": "sandbox_not_found",
                    "message": "workspace 不存在。",
                    "retryable": False,
                    "details": {},
                },
            )
        ),
    )

    with pytest.raises(SandboxNotFound, match="workspace 不存在"):
        await provider.ensure_workspace(_binding())


@pytest.mark.anyio
async def test_local_code_run_discards_python_only_truncation_metadata() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/workspaces":
            return httpx.Response(
                200,
                json={
                    "ref": {
                        "provider": "local",
                        "isolation": "linux_process",
                        "node": "node-a",
                        "resource_id": "local-1",
                        "generation": 1,
                        "binding_digest": request.headers["x-sandbox-binding"],
                        "dependency_bundle_digest": "sha256:" + "b" * 64,
                    },
                    "state": "started",
                },
            )
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "output_truncated": True,
                "script_hash": "a" * 64,
                "dependency_bundle_digest": "sha256:" + "b" * 64,
            },
        )

    provider = LocalProvider(
        LocalProviderConfig(
            profile="ubuntu",
            endpoint="unix:///run/local-sandboxd.sock",
            rootfs_digest="sha256:" + "a" * 64,
        ),
        registry=MemoryRegistry(),
        binding_secret=b"0123456789abcdef0123456789abcdef",
        transport=httpx.MockTransport(respond),
    )
    handle = await provider.ensure_workspace(_binding())

    result = await handle.process.code_run(CodeRunRequest(code="print('ok')"))

    assert result.status == ExecutionStatus.SUCCEEDED
    assert result.stdout == "ok"
