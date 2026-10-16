import asyncio
import hashlib
import os
from pathlib import Path

import pytest

from smart_reporting.sandbox import (
    ExecutionStatus,
    RunPythonScriptRequest,
    RunPythonScriptResult,
)
from smart_reporting.sandbox.errors import SandboxPolicyDenied
from smart_reporting.sandbox.local.runtime import (
    LaunchPolicy,
    LocalSandboxRuntime,
    build_python_argv,
)


def test_runtime_builds_fixed_offline_python_argv(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    bundle = tmp_path / "bundle"
    workspace = tmp_path / "workspace"
    seccomp = tmp_path / "seccomp.bpf"
    for directory in (rootfs, bundle, workspace):
        directory.mkdir()
    seccomp.write_bytes(b"policy")

    argv = build_python_argv(
        LaunchPolicy(
            bwrap="/usr/bin/bwrap",
            rootfs=rootfs,
            bundle=bundle,
            workspace=workspace,
            seccomp=seccomp,
        ),
        "jobs/script.py",
    )

    assert "--unshare-net" in argv
    assert ("--ro-bind", str(rootfs), "/") == argv[
        argv.index("--ro-bind") : argv.index("--ro-bind") + 3
    ]
    assert ("--tmpfs", "/tmp") == argv[argv.index("--tmpfs") : argv.index("--tmpfs") + 2]
    assert ("--chdir", "/workspace") == argv[argv.index("--chdir") : argv.index("--chdir") + 2]
    assert (
        "--setenv",
        "MATPLOTLIBRC",
        "/workspace/.sandbox-matplotlib/matplotlibrc",
    ) == argv[argv.index("--setenv") : argv.index("--setenv") + 3]
    assert argv[-4:] == ("/usr/bin/python3", "-I", "-B", "/workspace/jobs/script.py")
    assert "python" not in " ".join(argv[:-4])


def test_runtime_maps_validated_relative_cwd_into_workspace(tmp_path: Path) -> None:
    rootfs = tmp_path / "rootfs"
    bundle = tmp_path / "bundle"
    workspace = tmp_path / "workspace"
    seccomp = tmp_path / "seccomp.bpf"
    for directory in (rootfs, bundle, workspace):
        directory.mkdir()
    seccomp.write_bytes(b"policy")

    argv = build_python_argv(
        LaunchPolicy(
            bwrap="/usr/bin/bwrap",
            rootfs=rootfs,
            bundle=bundle,
            workspace=workspace,
            seccomp=seccomp,
        ),
        "jobs/script.py",
        cwd="analysis/output",
    )

    assert argv[argv.index("--chdir") + 1] == "/workspace/analysis/output"


@pytest.mark.anyio
async def test_upload_idempotency_recreates_file_removed_after_prior_request(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    runtime = LocalSandboxRuntime(
        node_id="node-a",
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        dependency_bundle_digest="sha256:" + "b" * 64,
        workspace_root=workspace_root,
        executor_factory=lambda _workspace: None,  # type: ignore[arg-type,return-value]
    )
    binding = "c" * 64
    created = await runtime.ensure_workspace(
        binding,
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        idempotency_key="workspace-request-1",
    )
    resource_id = created["ref"]["resource_id"]
    path = "/home/daytona/workspace/result.txt"

    await runtime.upload_file(resource_id, binding, path, b"result", "upload-request-01")
    await runtime.file_action(resource_id, binding, "delete", {"path": path, "recursive": False})
    await runtime.upload_file(resource_id, binding, path, b"result", "upload-request-01")

    assert await runtime.file_action(resource_id, binding, "download", {"path": path}) == b"result"


def _runtime(tmp_path: Path, executor_factory):
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    return LocalSandboxRuntime(
        node_id="node-a",
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        dependency_bundle_digest="sha256:" + "b" * 64,
        workspace_root=workspace_root,
        executor_factory=executor_factory,
    )


async def _bound_workspace(runtime: LocalSandboxRuntime) -> tuple[str, str]:
    binding = "c" * 64
    created = await runtime.ensure_workspace(
        binding,
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        idempotency_key="workspace-request-1",
    )
    return created["ref"]["resource_id"], binding


@pytest.mark.anyio
async def test_ensure_workspace_recovers_directory_missing_metadata(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path, lambda _workspace: None)  # type: ignore[arg-type,return-value]
    binding = "d" * 64
    resource_id = runtime._resource_id(binding)
    directory = runtime._directory(resource_id)
    directory.mkdir(parents=True)
    (directory / "orphan").write_text("partial", encoding="utf-8")

    created = await runtime.ensure_workspace(
        binding,
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        idempotency_key="workspace-request-2",
    )

    assert created["ref"]["resource_id"] == resource_id
    assert (directory / ".sandbox-binding.json").is_file()
    assert not (directory / "orphan").exists()


@pytest.mark.anyio
async def test_upload_keeps_idempotency_when_replace_fails_after_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path, lambda _workspace: None)  # type: ignore[arg-type,return-value]
    resource_id, binding = await _bound_workspace(runtime)
    path = "/home/daytona/workspace/result.txt"
    original_replace = os.replace
    failed = False

    def flaky_replace(source, destination):
        nonlocal failed
        if not failed and str(destination).endswith("result.txt"):
            failed = True
            raise OSError("replace failed")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(OSError, match="replace failed"):
        await runtime.upload_file(resource_id, binding, path, b"one", "upload-key")
    with pytest.raises(SandboxPolicyDenied, match="不同请求"):
        await runtime.upload_file(resource_id, binding, path, b"two", "upload-key")

    await runtime.upload_file(resource_id, binding, path, b"one", "upload-key")

    assert await runtime.file_action(resource_id, binding, "download", {"path": path}) == b"one"


@pytest.mark.anyio
async def test_upload_waits_until_workspace_script_finishes(tmp_path: Path) -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    class Executor:
        async def run(
            self, request: RunPythonScriptRequest, *, script_path: str
        ) -> RunPythonScriptResult:
            del script_path
            entered.set()
            await release.wait()
            return RunPythonScriptResult(
                status=ExecutionStatus.SUCCEEDED,
                exit_code=0,
                script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
            )

    runtime = _runtime(tmp_path, lambda _workspace: Executor())
    resource_id, binding = await _bound_workspace(runtime)
    script = asyncio.create_task(
        runtime.run_python_script(
            resource_id, binding, RunPythonScriptRequest(script="print('one')")
        )
    )
    await entered.wait()
    upload = asyncio.create_task(
        runtime.upload_file(
            resource_id,
            binding,
            "/home/daytona/workspace/result.txt",
            b"later",
            "upload-during-script",
        )
    )
    await asyncio.sleep(0.05)
    assert not upload.done()
    release.set()
    await script
    await upload
    assert (
        await runtime.file_action(
            resource_id, binding, "download", {"path": "/home/daytona/workspace/result.txt"}
        )
        == b"later"
    )


@pytest.mark.anyio
async def test_runtime_serializes_scripts_within_same_workspace_cgroup(tmp_path: Path) -> None:
    active = 0
    max_active = 0

    class Executor:
        async def run(
            self, request: RunPythonScriptRequest, *, script_path: str
        ) -> RunPythonScriptResult:
            nonlocal active, max_active
            del script_path
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.01)
            finally:
                active -= 1
            return RunPythonScriptResult(
                status=ExecutionStatus.SUCCEEDED,
                exit_code=0,
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
        executor_factory=lambda _workspace: Executor(),
    )
    binding = "c" * 64
    created = await runtime.ensure_workspace(
        binding,
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        idempotency_key="workspace-request-1",
    )
    resource_id = created["ref"]["resource_id"]

    results = await asyncio.gather(
        runtime.run_python_script(
            resource_id, binding, RunPythonScriptRequest(script="print('one')")
        ),
        runtime.run_python_script(
            resource_id, binding, RunPythonScriptRequest(script="print('two')")
        ),
    )

    assert max_active == 1
    assert {result["dependency_bundle_digest"] for result in results} == {"sha256:" + "b" * 64}


@pytest.mark.anyio
async def test_runtime_bootstraps_default_chinese_matplotlib_font(tmp_path: Path) -> None:
    observed_script = ""

    class Executor:
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace

        async def run(
            self, request: RunPythonScriptRequest, *, script_path: str
        ) -> RunPythonScriptResult:
            nonlocal observed_script
            observed_script = (self.workspace / script_path).read_text()
            return RunPythonScriptResult(
                status=ExecutionStatus.SUCCEEDED,
                exit_code=0,
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
    binding = "c" * 64
    created = await runtime.ensure_workspace(
        binding,
        profile="ubuntu",
        rootfs_digest="sha256:" + "a" * 64,
        idempotency_key="workspace-request-1",
    )

    await runtime.run_python_script(
        created["ref"]["resource_id"],
        binding,
        RunPythonScriptRequest(script="print('ok')"),
    )

    assert "font.family: sans-serif" in observed_script
    assert "font.sans-serif: Noto Sans CJK SC, DejaVu Sans" in observed_script
    assert "TTCollection" in observed_script
    assert "fontManager.addfont" in observed_script
    assert observed_script.index("fontManager.addfont") < observed_script.index("print('ok')")
    execution_line = next(
        line for line in observed_script.splitlines() if line.startswith("exec(compile(")
    )
    assert execution_line == (
        "exec(compile(_reporting_source, '<target_code>', 'exec'), globals(), globals())"
    )
