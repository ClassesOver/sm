import json
import os

import pytest

from agentos_dev.skills import (
    SecureSkills,
    TrustedLocalSkills,
    UntrustedSkillsDirectory,
)


def create_skill(root, name="review"):
    folder = root / name
    (folder / "scripts").mkdir(parents=True)
    (folder / "references").mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review documents\n---\nSecret instructions",
        encoding="utf-8",
    )
    (folder / "scripts" / "check.py").write_text("print('ok')", encoding="utf-8")
    (folder / "references" / "guide.md").write_text("guide", encoding="utf-8")
    return folder


def test_public_metadata_is_clean_and_host_script_execution_is_absent(tmp_path):
    create_skill(tmp_path)
    skills = SecureSkills(loaders=[TrustedLocalSkills(str(tmp_path))])
    metadata = skills.public_metadata()
    serialized = json.dumps(metadata)

    assert metadata == [{
        "id": SecureSkills.skill_id("review"),
        "name": "review",
        "description": "Review documents",
    }]
    assert "Secret instructions" not in serialized
    assert str(tmp_path) not in serialized
    tools = {tool.name: tool for tool in skills.get_tools()}
    assert set(tools) == {
        "get_skill_instructions", "get_skill_reference", "get_skill_script",
    }
    assert "execute" not in tools["get_skill_script"].parameters["properties"]
    assert "print('ok')" in skills.read_skill_script("review", "check.py")


def test_rejects_untrusted_root_and_escaping_symlink(tmp_path):
    untrusted = tmp_path / "untrusted"
    untrusted.mkdir()
    untrusted.chmod(0o777)
    with pytest.raises(UntrustedSkillsDirectory):
        TrustedLocalSkills(str(untrusted))

    trusted = tmp_path / "trusted"
    folder = create_skill(trusted)
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    (folder / "scripts" / "check.py").unlink()
    (folder / "scripts" / "check.py").symlink_to(outside)
    with pytest.raises(UntrustedSkillsDirectory):
        SecureSkills(loaders=[TrustedLocalSkills(str(trusted))])
