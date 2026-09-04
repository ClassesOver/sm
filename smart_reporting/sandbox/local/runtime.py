from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from ..contracts import (
    ExecutionStatus,
    FileInfo,
    ProviderCapabilities,
    ProviderHealth,
    ProviderKind,
    RunPythonScriptRequest,
    RunPythonScriptResult,
)
from ..errors import SandboxNotFound, SandboxPolicyDenied, SandboxTimeout
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


class ScriptExecutor(Protocol):
    async def run(
        self, request: RunPythonScriptRequest, *, script_path: str
    ) -> RunPythonScriptResult: ...


class LocalSandboxRuntime:
    """local-sandboxd 的工作区与结构化 runner 所有者。"""

    def __init__(
        self,
        *,
        node_id: str,
        profile: str,
        rootfs_digest: str,
        dependency_bundle_digest: str,
        workspace_root: Path,
        executor_factory: Callable[[Path], ScriptExecutor],
    ) -> None:
        self.node_id = node_id
        self.profile = profile
        self.rootfs_digest = rootfs_digest
        self.dependency_bundle_digest = dependency_bundle_digest
        self.workspace_root = workspace_root.resolve(strict=True)
        if self.workspace_root.is_symlink():
            raise ValueError("workspace root 不能是符号链接")
        self._executor_factory = executor_factory
        self._lock = asyncio.Lock()

    def _resource_id(self, binding_digest: str) -> str:
        return "local-" + hashlib.sha256(binding_digest.encode()).hexdigest()[:32]

    def _directory(self, resource_id: str) -> Path:
        if not re_fullmatch_resource(resource_id):
            raise SandboxPolicyDenied("workspace ID 无效。", reason="invalid_resource_id")
        return self.workspace_root / resource_id

    def _metadata(self, resource_id: str) -> dict[str, Any]:
        path = self._directory(resource_id) / ".sandbox-binding.json"
        if path.is_symlink() or not path.is_file():
            raise SandboxNotFound("local workspace 不存在。")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise SandboxNotFound("local workspace 元数据无效。") from error
        if not isinstance(value, dict):
            raise SandboxNotFound("local workspace 元数据无效。")
        return value

    def _require(self, resource_id: str, binding_digest: str) -> tuple[Path, dict[str, Any]]:
        metadata = self._metadata(resource_id)
        if metadata.get("binding_digest") != binding_digest:
            raise SandboxPolicyDenied("workspace 不属于当前绑定。", reason="binding_mismatch")
        return self._directory(resource_id), metadata

    def _response(self, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            "ref": {
                "provider": "local",
                "isolation": "linux_process",
                "node": self.node_id,
                "resource_id": metadata["resource_id"],
                "generation": metadata["generation"],
                "binding_digest": metadata["binding_digest"],
                "dependency_bundle_digest": self.dependency_bundle_digest,
            },
            "state": "started",
        }

    async def ensure_workspace(
        self,
        binding_digest: str,
        *,
        profile: str,
        rootfs_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if profile != self.profile or rootfs_digest != self.rootfs_digest:
            raise SandboxPolicyDenied(
                "请求的 sandbox profile 或 rootfs 未获部署授权。",
                reason="artifact_mismatch",
            )
        resource_id = self._resource_id(binding_digest)
        async with self._lock:
            directory = self._directory(resource_id)
            metadata_path = directory / ".sandbox-binding.json"
            if metadata_path.exists():
                metadata = self._metadata(resource_id)
                if metadata.get("idempotency_key") != idempotency_key:
                    raise SandboxPolicyDenied(
                        "workspace 幂等键与既有绑定冲突。", reason="idempotency_conflict"
                    )
                return self._response(metadata)
            directory.mkdir(mode=0o700)
            metadata = {
                "resource_id": resource_id,
                "binding_digest": binding_digest,
                "idempotency_key": idempotency_key,
                "generation": 1,
            }
            temporary = directory / f".binding-{uuid.uuid4().hex}.tmp"
            temporary.write_text(
                json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, metadata_path)
        return self._response(metadata)

    async def get_workspace(self, resource_id: str, binding_digest: str) -> dict[str, Any]:
        _directory, metadata = self._require(resource_id, binding_digest)
        return self._response(metadata)

    async def list_workspaces(self, binding_digest: str) -> list[dict[str, Any]]:
        resource_id = self._resource_id(binding_digest)
        try:
            return [await self.get_workspace(resource_id, binding_digest)]
        except SandboxNotFound:
            return []

    async def destroy_workspace(self, resource_id: str, binding_digest: str) -> dict[str, bool]:
        directory, _metadata = self._require(resource_id, binding_digest)
        shutil.rmtree(directory)
        return {"deleted": True}

    def _path(self, directory: Path, value: str, *, existing: bool = False) -> Path:
        normalized = value.replace("\\", "/")
        prefix = "/home/daytona/workspace"
        if normalized == prefix:
            normalized = ""
        elif normalized.startswith(prefix + "/"):
            normalized = normalized[len(prefix) + 1 :]
        candidate = PurePosixPath(normalized)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SandboxPolicyDenied("workspace 路径越界。", reason="invalid_path")
        current = directory
        for part in candidate.parts:
            current = current / part
            if current.exists() and current.is_symlink():
                raise SandboxPolicyDenied("workspace 路径包含符号链接。", reason="symlink")
        if existing and not current.exists():
            raise SandboxNotFound("workspace 文件不存在。")
        return current

    async def file_action(
        self, resource_id: str, binding_digest: str, action: str, values: dict[str, Any]
    ) -> Any:
        directory, _metadata = self._require(resource_id, binding_digest)
        if action == "move":
            source = self._path(directory, str(values["source"]), existing=True)
            destination = self._path(directory, str(values["destination"]))
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.replace(source, destination)
            return {"ok": True}
        path = self._path(directory, str(values["path"]), existing=action not in {"mkdir"})
        if action == "stat":
            value = path.stat(follow_symlinks=False)
            return FileInfo(
                name=path.name or "workspace",
                path=str(values["path"]),
                is_dir=stat.S_ISDIR(value.st_mode),
                size=value.st_size,
                mode=stat.filemode(value.st_mode),
            ).model_dump(mode="json")
        if action == "list":
            if not path.is_dir():
                raise SandboxPolicyDenied("目标不是目录。", reason="not_directory")
            entries = [entry for entry in path.iterdir() if not entry.name.startswith(".sandbox-")]
            if len(entries) > 500:
                raise SandboxPolicyDenied("目录条目超过限制。", reason="entry_limit")
            return [
                FileInfo(
                    name=entry.name,
                    path=str(values["path"]).rstrip("/") + "/" + entry.name,
                    is_dir=entry.is_dir(),
                    size=entry.stat(follow_symlinks=False).st_size,
                    mode=stat.filemode(entry.stat(follow_symlinks=False).st_mode),
                ).model_dump(mode="json")
                for entry in entries
                if not entry.is_symlink()
            ]
        if action == "mkdir":
            path.mkdir(mode=int(str(values["mode"]), 8), parents=True, exist_ok=True)
            return {"ok": True}
        if action == "download":
            if not path.is_file() or path.stat().st_size > 200 * 1024 * 1024:
                raise SandboxPolicyDenied("文件类型或大小不允许下载。", reason="download_denied")
            return path.read_bytes()
        if action == "delete":
            if path.is_dir():
                if not values.get("recursive"):
                    raise SandboxPolicyDenied("目录删除必须显式递归。", reason="recursive_required")
                shutil.rmtree(path)
            else:
                path.unlink()
            return {"ok": True}
        raise SandboxPolicyDenied("未知文件操作。", reason="unknown_file_action")

    async def upload_file(
        self,
        resource_id: str,
        binding_digest: str,
        path: str,
        content: bytes,
        _idempotency_key: str,
    ) -> None:
        directory, _metadata = self._require(resource_id, binding_digest)
        destination = self._path(directory, path)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = destination.parent / f".sandbox-upload-{uuid.uuid4().hex}"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)

    async def run_python_script(
        self,
        resource_id: str,
        binding_digest: str,
        request: RunPythonScriptRequest,
    ) -> dict[str, Any]:
        directory, _metadata = self._require(resource_id, binding_digest)
        run_directory = directory / ".sandbox-runs"
        run_directory.mkdir(mode=0o700, exist_ok=True)
        relative = f".sandbox-runs/{uuid.uuid4().hex}.py"
        script = self._path(directory, relative)
        descriptor = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as output:
                output.write(request.script.encode())
                output.flush()
            result = await self._executor_factory(directory).run(request, script_path=relative)
            return result.model_dump(mode="json")
        finally:
            os.close(descriptor)
            script.unlink(missing_ok=True)

    async def health(self) -> dict[str, Any]:
        return ProviderHealth(
            healthy=True,
            provider=ProviderKind.LOCAL,
            node=self.node_id,
            message="local-sandboxd 可用。",
        ).model_dump(mode="json")

    async def capabilities(self) -> dict[str, Any]:
        return ProviderCapabilities(
            persistent_sessions=False,
            pty=False,
            network_policy=True,
            branch_copy=True,
            resource_limits=True,
            snapshots=False,
        ).model_dump(mode="json")


def re_fullmatch_resource(value: str) -> bool:
    return (
        len(value) == 38
        and value.startswith("local-")
        and all(character in "0123456789abcdef" for character in value[6:])
    )
