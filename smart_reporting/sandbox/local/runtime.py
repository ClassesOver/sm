from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from ..contracts import ExecutionStatus, RunPythonScriptRequest, RunPythonScriptResult
from ..errors import SandboxPolicyDenied, SandboxTimeout
from .preflight import inspect_host, run_preflight


@dataclass(frozen=True)
class LaunchPolicy:
    bwrap: str
    rootfs: Path
    bundle: Path
    workspace: Path
    seccomp: Path
    cgroup: Path | None = None


def _script_path(value: str) -> str:
    candidate = PurePosixPath(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix != ".py":
        raise SandboxPolicyDenied("Python 脚本路径无效。", reason="invalid_script_path")
    return "/workspace/" + "/".join(candidate.parts)


def build_python_argv(
    policy: LaunchPolicy, script_path: str, *, seccomp_fd: int = 3
) -> tuple[str, ...]:
    return (
        policy.bwrap,
        "--unshare-user",
        "--unshare-pid",
        "--unshare-net",
        "--unshare-uts",
        "--unshare-ipc",
        "--die-with-parent",
        "--new-session",
        "--ro-bind",
        str(policy.rootfs),
        "/",
        "--ro-bind",
        str(policy.bundle),
        "/opt/reporting-deps",
        "--bind",
        str(policy.workspace),
        "/workspace",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--seccomp",
        str(seccomp_fd),
        "/usr/bin/python3",
        "-I",
        "-B",
        _script_path(script_path),
    )


class PythonRuntime:
    """只执行固定 Python runner 的 Linux 隔离启动器。"""

    def __init__(self, policy: LaunchPolicy, *, rootfs_digest: str) -> None:
        self.policy = policy
        self.rootfs_digest = rootfs_digest
        run_preflight(inspect_host(rootfs=policy.rootfs, bundle=policy.bundle, bwrap=policy.bwrap))
        if not policy.seccomp.is_file() or policy.seccomp.is_symlink():
            raise ValueError("seccomp BPF 制品无效")
        if policy.cgroup is None or not (policy.cgroup / "cgroup.kill").exists():
            raise ValueError("必须提供可管理的 cgroup v2")

    async def run(
        self, request: RunPythonScriptRequest, *, script_path: str
    ) -> RunPythonScriptResult:
        seccomp_fd = os.open(self.policy.seccomp, os.O_RDONLY | os.O_CLOEXEC)
        try:
            argv = build_python_argv(self.policy, script_path, seccomp_fd=seccomp_fd)
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={"PATH": "/usr/bin", "PYTHONPATH": "/opt/reporting-deps"},
                pass_fds=(seccomp_fd,),
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=request.timeout_ms / 1000
                )
            except TimeoutError as error:
                assert self.policy.cgroup is not None
                (self.policy.cgroup / "cgroup.kill").write_text("1")
                await process.wait()
                raise SandboxTimeout("Python 脚本执行超时。") from error
        finally:
            os.close(seccomp_fd)
        limit = request.output_limit_bytes
        return RunPythonScriptResult(
            status=(
                ExecutionStatus.SUCCEEDED if process.returncode == 0 else ExecutionStatus.FAILED
            ),
            exit_code=process.returncode,
            stdout=stdout[:limit].decode("utf-8", errors="replace"),
            stderr=stderr[:limit].decode("utf-8", errors="replace"),
            script_hash=hashlib.sha256(request.script.encode()).hexdigest(),
        )
