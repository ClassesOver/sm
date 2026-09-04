from __future__ import annotations

import argparse
import base64
import json
import platform
import ssl
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import uvicorn
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from pydantic import BaseModel, ConfigDict, Field

from .app import create_local_sandbox_app
from .catalog import DependencyCatalog
from .preflight import inspect_host, run_preflight
from .runtime import LaunchPolicy, LocalSandboxRuntime, PythonRuntime


class DaemonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, max_length=256)
    profile: str = Field(pattern=r"^(ubuntu|openeuler)$")
    arch: str = Field(default_factory=platform.machine, min_length=1, max_length=32)
    python_abi: str = Field(default="cp312", pattern=r"^cp[0-9]{3}$")
    policy: str = Field(default="reporting", min_length=1, max_length=64)
    catalog_path: Path
    artifact_root: Path
    catalog_public_key: Path
    workspace_root: Path
    cgroup_root: Path
    seccomp_path: Path
    bwrap: str = "/usr/bin/bwrap"
    listener: str
    tls_cert: Path | None = None
    tls_key: Path | None = None
    client_ca: Path | None = None
    cpu_max: str = "200000 100000"
    memory_max: int = Field(default=2 * 1024 * 1024 * 1024, ge=64 * 1024 * 1024)
    pids_max: int = Field(default=128, ge=16, le=4096)


def _signature_verifier(public_key_path: Path):
    key = load_pem_public_key(public_key_path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("catalog 公钥必须是 Ed25519。")

    def verify(payload: bytes, signature: str) -> bool:
        try:
            key.verify(base64.b64decode(signature, validate=True), payload)
        except (InvalidSignature, ValueError, TypeError):
            return False
        return True

    return verify


def build_runtime(config: DaemonConfig) -> LocalSandboxRuntime:
    catalog = DependencyCatalog.load(
        config.catalog_path,
        artifact_root=config.artifact_root,
        verify_signature=_signature_verifier(config.catalog_public_key),
    )
    bundle = catalog.resolve(config.profile, config.arch, config.python_abi, config.policy)
    run_preflight(
        inspect_host(rootfs=bundle.rootfs_path, bundle=bundle.bundle_path, bwrap=config.bwrap)
    )
    if not config.workspace_root.is_dir() or config.workspace_root.is_symlink():
        raise ValueError("workspace_root 必须是预先创建的普通目录。")
    if not config.cgroup_root.is_dir() or config.cgroup_root.is_symlink():
        raise ValueError("cgroup_root 必须是预先委派的 cgroup v2 目录。")

    def executor(workspace: Path) -> PythonRuntime:
        cgroup = config.cgroup_root / workspace.name
        cgroup.mkdir(exist_ok=True)
        (cgroup / "cpu.max").write_text(config.cpu_max)
        (cgroup / "memory.max").write_text(str(config.memory_max))
        (cgroup / "pids.max").write_text(str(config.pids_max))
        return PythonRuntime(
            LaunchPolicy(
                bwrap=config.bwrap,
                rootfs=bundle.rootfs_path,
                bundle=bundle.bundle_path,
                workspace=workspace,
                seccomp=config.seccomp_path,
                cgroup=cgroup,
            ),
            rootfs_digest=bundle.rootfs_digest,
        )

    return LocalSandboxRuntime(
        node_id=config.node_id,
        profile=config.profile,
        rootfs_digest=bundle.rootfs_digest,
        dependency_bundle_digest=bundle.digest,
        workspace_root=config.workspace_root,
        executor_factory=executor,
    )


def _uvicorn_options(config: DaemonConfig) -> dict[str, Any]:
    parsed = urlsplit(config.listener)
    if parsed.scheme == "unix" and not parsed.netloc and parsed.path.startswith("/"):
        return {"uds": parsed.path}
    if parsed.scheme != "https" or not parsed.hostname or parsed.port is None:
        raise ValueError("listener 必须是绝对 unix socket 或带端口的 HTTPS 地址。")
    if not config.tls_cert or not config.tls_key or not config.client_ca:
        raise ValueError("HTTPS listener 必须配置服务端证书、私钥和客户端 CA。")
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "ssl_certfile": str(config.tls_cert),
        "ssl_keyfile": str(config.tls_key),
        "ssl_ca_certs": str(config.client_ca),
        "ssl_cert_reqs": ssl.CERT_REQUIRED,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="local-sandboxd")
    parser.add_argument("--config", type=Path, required=True)
    arguments = parser.parse_args()
    config = DaemonConfig.model_validate(json.loads(arguments.config.read_text(encoding="utf-8")))
    runtime = build_runtime(config)
    uvicorn.run(create_local_sandbox_app(runtime), access_log=False, **_uvicorn_options(config))


if __name__ == "__main__":
    main()
