from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager

import httpx
import pytest

from smart_reporting.sandbox import (
    ExecutionStatus,
    RunPythonScriptRequest,
    RunPythonScriptResult,
    WorkspaceBinding,
)
from smart_reporting.sandbox.local.app import create_local_sandbox_app
from smart_reporting.sandbox.local.client import LocalProvider
from smart_reporting.sandbox.local.config import LocalProviderConfig
from smart_reporting.sandbox.local.runtime import LocalSandboxRuntime
from smart_reporting.task_execution.tools import abuild_workspace_changes
from smart_reporting.workspace import WorkspaceError, WorkspaceService


class _RegistryTransaction:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def set_binding(self, record) -> None:
        self.values[record.binding_digest] = record.resource_id


class _Registry:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    @asynccontextmanager
    async def locked(self, _key: str):
        yield _RegistryTransaction(self.values)


@pytest.mark.anyio
async def test_local_provider_round_trips_real_daemon_contract(tmp_path) -> None:
    class Executor:
        def __init__(self, workspace) -> None:
            self.workspace = workspace

        async def run(self, request, *, script_path):
            runtime_script = (self.workspace / script_path).read_text(encoding="utf-8")
            assert "fontManager.addfont" in runtime_script
            assert repr(request.script) in runtime_script
            assert runtime_script.index("fontManager.addfont") < runtime_script.index(
                "exec(compile("
            )
            return RunPythonScriptResult(
                status=ExecutionStatus.SUCCEEDED,
                exit_code=0,
                stdout="ok\n",
                script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
                dependency_bundle_digest="sha256:" + "b" * 64,
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
    provider = LocalProvider(
        LocalProviderConfig(
            profile="ubuntu",
            endpoint="http://local-sandboxd",
            rootfs_digest="sha256:" + "a" * 64,
        ),
        registry=_Registry(),
        binding_secret=b"0123456789abcdef0123456789abcdef",
        transport=httpx.ASGITransport(app=create_local_sandbox_app(runtime)),
    )
    binding = WorkspaceBinding(
        tenant_id="tenant",
        user_id="user",
        company_id="company",
        thread_id="thread",
        idempotency_key="workspace-request-1",
        profile="ubuntu",
    )
    try:
        handle = await provider.ensure_workspace(binding)
        path = "/home/daytona/workspace/analysis/model.py"
        await handle.fs.upload_file(b"print('ok')\n", path)

        info = await handle.fs.get_file_info(path)
        content = await handle.fs.download_file(path)
        executed = await handle.execution.run_python_script(
            RunPythonScriptRequest(script=content.decode("utf-8"))
        )
        destroyed = await provider.destroy_workspace(handle.ref, binding)

        assert info.size == len(content)
        assert executed.status == ExecutionStatus.SUCCEEDED
        assert executed.stdout == "ok\n"
        assert destroyed.deleted is True
        assert await provider.list_workspaces(binding) == []

        workspace = WorkspaceService(
            "0123456789abcdef0123456789abcdef",
            provider=provider,
            async_registry=_Registry(),
        )
        created = await workspace.aapply_changes(
            "report-thread",
            [
                {
                    "operation": "create",
                    "path": "analysis/model.py",
                    "content": "print('before')\n",
                },
                {"operation": "create", "path": "analysis/delete.py", "content": "delete\n"},
                {"operation": "create", "path": "analysis/move.py", "content": "move\n"},
            ],
        )
        hashes = {item["path"]: item["sha256"] for item in created["files"]}
        changed = await workspace.aapply_changes(
            "report-thread",
            [
                {
                    "operation": "update",
                    "path": "analysis/model.py",
                    "content": "print('updated')\n",
                    "expected_sha256": hashes["analysis/model.py"],
                },
                {
                    "operation": "delete",
                    "path": "analysis/delete.py",
                    "expected_sha256": hashes["analysis/delete.py"],
                },
                {
                    "operation": "move",
                    "path": "analysis/move.py",
                    "destination": "archive/moved.py",
                    "expected_sha256": hashes["analysis/move.py"],
                },
            ],
        )
        patch = """--- a/analysis/model.py
+++ b/analysis/model.py
@@ -1 +1 @@
-print('updated')
+print('ready')
"""
        patch_changes = await abuild_workspace_changes(workspace, "report-thread", patch)
        await workspace.aapply_changes("report-thread", patch_changes)
        ran = await workspace.arun_python_script("report-thread", "analysis/model.py", timeout=5)

        assert changed["operations"] == 3
        assert (
            await workspace.aread_text("report-thread", "analysis/model.py") == "print('ready')\n"
        )
        assert await workspace.aread_text("report-thread", "archive/moved.py") == "move\n"
        with pytest.raises(WorkspaceError, match="不存在"):
            await workspace.aread_text("report-thread", "analysis/delete.py")
        assert ran["status"] == "completed"
        assert await workspace.adestroy("report-thread") is True
    finally:
        await provider.aclose()
