from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..errors import SandboxPreflightFailed


@dataclass(frozen=True)
class PreflightProfile:
    user_ns: bool
    cgroup_v2: bool
    seccomp: bool
    rootfs: bool
    bundle: bool
    bwrap: bool


def inspect_host(*, rootfs: Path, bundle: Path, bwrap: str = "bwrap") -> PreflightProfile:
    user_ns_setting = Path("/proc/sys/kernel/unprivileged_userns_clone")
    user_ns = Path("/proc/self/ns/user").exists() and (
        not user_ns_setting.exists() or user_ns_setting.read_text().strip() == "1"
    )
    return PreflightProfile(
        user_ns=user_ns,
        cgroup_v2=Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        seccomp="Seccomp:" in Path("/proc/self/status").read_text(),
        rootfs=rootfs.is_dir() and not rootfs.is_symlink(),
        bundle=bundle.is_dir() and not bundle.is_symlink(),
        bwrap=bool(shutil.which(bwrap) if os.path.sep not in bwrap else Path(bwrap).is_file()),
    )


def run_preflight(profile: PreflightProfile) -> None:
    missing = [name for name, available in vars(profile).items() if not available]
    if missing:
        raise SandboxPreflightFailed(
            "local sandbox 宿主预检失败: " + ", ".join(missing),
            details={"missing": missing},
        )
