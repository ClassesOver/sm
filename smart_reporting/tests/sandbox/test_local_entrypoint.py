import json
from pathlib import Path

import pytest

from smart_reporting.sandbox.local.__main__ import _prepare_delegated_cgroup

PROFILE_ROOT = Path(__file__).parents[3] / "deploy" / "local-sandboxd" / "profiles"


@pytest.mark.parametrize("profile", ["ubuntu", "openeuler"])
def test_built_in_profile_is_complete(profile: str) -> None:
    value = json.loads((PROFILE_ROOT / f"{profile}.json").read_text())

    assert value["profile"] == profile
    assert value["network"] == "disabled"
    assert value["require_cgroup_v2"] is True
    assert value["require_seccomp"] is True
    assert value["python_abi"] == "cp312"


def test_prepare_delegated_cgroup_moves_daemon_and_enables_controllers(tmp_path: Path) -> None:
    root = tmp_path / "local-sandboxd.service"
    daemon = root / "daemon"
    daemon.mkdir(parents=True)
    (root / "cgroup.controllers").write_text("cpu memory pids", encoding="utf-8")
    (root / "cgroup.subtree_control").write_text("", encoding="utf-8")
    (daemon / "cgroup.procs").write_text("", encoding="utf-8")

    _prepare_delegated_cgroup(root, pid=1234)

    assert (daemon / "cgroup.procs").read_text(encoding="utf-8") == "1234"
    assert (root / "cgroup.subtree_control").read_text(encoding="utf-8") == "+cpu +memory +pids"


def test_prepare_delegated_cgroup_rejects_missing_controller(tmp_path: Path) -> None:
    root = tmp_path / "local-sandboxd.service"
    daemon = root / "daemon"
    daemon.mkdir(parents=True)
    (root / "cgroup.controllers").write_text("cpu memory", encoding="utf-8")
    (root / "cgroup.subtree_control").write_text("", encoding="utf-8")
    (daemon / "cgroup.procs").write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="pids"):
        _prepare_delegated_cgroup(root, pid=1234)
