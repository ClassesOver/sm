import hashlib

import httpx
import pytest

from smart_reporting.sandbox import ExecutionStatus, RunPythonScriptResult
from smart_reporting.sandbox.local.app import create_local_sandbox_app
from smart_reporting.sandbox.local.runtime import LocalSandboxRuntime


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


@pytest.mark.anyio
async def test_daemon_round_trips_file_and_cleans_python_source(tmp_path) -> None:
    class Executor:
        def __init__(self, workspace):
            self.workspace = workspace

        async def run(self, request, *, script_path):
            runtime_script = (self.workspace / script_path).read_text()
            assert "fontManager.addfont" in runtime_script
            assert repr(request.script) in runtime_script
            assert runtime_script.index("fontManager.addfont") < runtime_script.index(
                "exec(compile("
            )
            return RunPythonScriptResult(
                status=ExecutionStatus.SUCCEEDED,
                exit_code=0,
                stdout="ok",
                script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
            )

    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    runtime = LocalSandboxRuntime(
        node_id="node-a",
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        dependency_bundle_digest="sha256:" + "b" * 64,
        workspace_root=workspace_root,
        executor_factory=Executor,
    )
    app = create_local_sandbox_app(runtime)
    headers = {
        "x-sandbox-binding": "c" * 64,
        "idempotency-key": "request-00000001",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/workspaces",
            headers=headers,
            json={"profile": "ubuntu", "rootfs_digest": "sha256:" + "a" * 64},
        )
        resource_id = created.json()["ref"]["resource_id"]
        uploaded = await client.put(
            f"/v1/workspaces/{resource_id}/files/content",
            headers=headers,
            params={"path": "/home/daytona/workspace/input.txt"},
            content=b"content",
        )
        downloaded = await client.post(
            f"/v1/workspaces/{resource_id}/files/download",
            headers={"x-sandbox-binding": "c" * 64},
            json={"path": "/home/daytona/workspace/input.txt"},
        )
        executed = await client.post(
            f"/v1/workspaces/{resource_id}/process/python",
            headers={"x-sandbox-binding": "c" * 64},
            json={"script": "print('ok')"},
        )

    assert uploaded.status_code == 200
    assert downloaded.content == b"content"
    assert executed.status_code == 200
    assert not list(workspace_root.glob("*/.sandbox-runs/*.py"))
