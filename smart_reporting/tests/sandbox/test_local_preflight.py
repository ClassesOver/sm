import pytest

from smart_reporting.sandbox import SandboxPreflightFailed
from smart_reporting.sandbox.local.preflight import PreflightProfile, run_preflight


@pytest.mark.parametrize("missing", ["user_ns", "cgroup_v2", "seccomp", "rootfs", "bundle"])
def test_preflight_fails_closed_when_required_capability_is_missing(missing: str) -> None:
    values = {
        "user_ns": True,
        "cgroup_v2": True,
        "seccomp": True,
        "rootfs": True,
        "bundle": True,
        "bwrap": True,
    }
    values[missing] = False

    with pytest.raises(SandboxPreflightFailed, match=missing):
        run_preflight(PreflightProfile(**values))
