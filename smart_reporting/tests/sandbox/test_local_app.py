import httpx
import pytest

from smart_reporting.sandbox.local.app import create_local_sandbox_app


class FakeRuntime:
    node_id = "node-a"

    async def ensure_workspace(self, binding_digest: str, **_values):
        return {
            "ref": {
                "provider": "local",
                "isolation": "linux_process",
                "node": self.node_id,
                "resource_id": "local-1",
                "generation": 1,
                "binding_digest": binding_digest,
                "dependency_bundle_digest": "sha256:" + "b" * 64,
            },
            "state": "started",
        }

    async def get_workspace(self, resource_id: str, binding_digest: str):
        if binding_digest != "a" * 64:
            raise PermissionError("binding_mismatch")
        return await self.ensure_workspace(binding_digest)


@pytest.mark.anyio
async def test_daemon_rejects_resource_from_other_binding() -> None:
    app = create_local_sandbox_app(FakeRuntime())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            "/v1/workspaces/local-1",
            headers={"x-sandbox-binding": "b" * 64},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "sandbox_policy_denied"


@pytest.mark.anyio
async def test_daemon_rejects_invalid_binding_before_runtime() -> None:
    app = create_local_sandbox_app(FakeRuntime())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/workspaces",
            headers={"x-sandbox-binding": "invalid", "idempotency-key": "request-00000001"},
            json={"profile": "ubuntu", "rootfs_digest": "sha256:" + "a" * 64},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "sandbox_policy_denied"
