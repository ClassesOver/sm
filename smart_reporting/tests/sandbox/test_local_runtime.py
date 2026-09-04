from pathlib import Path

import pytest

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
    assert argv[-4:] == ("/usr/bin/python3", "-I", "-B", "/workspace/jobs/script.py")
    assert "python" not in " ".join(argv[:-4])


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
