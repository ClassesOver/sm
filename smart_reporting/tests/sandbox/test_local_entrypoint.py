import json
from pathlib import Path

import pytest

PROFILE_ROOT = Path(__file__).parents[3] / "deploy" / "local-sandboxd" / "profiles"


@pytest.mark.parametrize("profile", ["ubuntu", "openeuler"])
def test_built_in_profile_is_complete(profile: str) -> None:
    value = json.loads((PROFILE_ROOT / f"{profile}.json").read_text())

    assert value["profile"] == profile
    assert value["network"] == "disabled"
    assert value["require_cgroup_v2"] is True
    assert value["require_seccomp"] is True
    assert value["python_abi"] == "cp312"
