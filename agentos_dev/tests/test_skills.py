import json

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
    root.chmod(0o755)
    folder.chmod(0o755)
    (folder / "scripts").chmod(0o755)
    (folder / "references").chmod(0o755)
    (folder / "SKILL.md").chmod(0o644)
    (folder / "scripts" / "check.py").chmod(0o644)
    (folder / "references" / "guide.md").chmod(0o644)
    return folder


def test_public_metadata_is_clean_and_host_script_execution_is_absent(tmp_path):
    create_skill(tmp_path)
    skills = SecureSkills(loaders=[TrustedLocalSkills(str(tmp_path))])
    metadata = skills.public_metadata()
    serialized = json.dumps(metadata)

    assert metadata == [
        {
            "id": SecureSkills.skill_id("review"),
            "name": "review",
            "description": "Review documents",
        }
    ]
    assert "Secret instructions" not in serialized
    assert str(tmp_path) not in serialized
    tools = {tool.name: tool for tool in skills.get_tools()}
    assert set(tools) == {
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
    }
    assert "execute" not in tools["get_skill_script"].parameters["properties"]
    assert "print('ok')" in skills.read_skill_script("review", "check.py")


def test_rejects_untrusted_root_and_escaping_symlink(tmp_path):
    trusted = tmp_path / "trusted"
    folder = create_skill(trusted)
    outside = tmp_path / "outside.py"
    outside.write_text("print('outside')", encoding="utf-8")
    (folder / "scripts" / "check.py").unlink()
    (folder / "scripts" / "check.py").symlink_to(outside)
    with pytest.raises(UntrustedSkillsDirectory):
        SecureSkills(loaders=[TrustedLocalSkills(str(trusted))])


def test_revalidates_symlink_and_accepts_group_writable_paths(tmp_path):
    folder = create_skill(tmp_path)
    folder.chmod(0o775)
    reference = folder / "references" / "guide.md"
    reference.chmod(0o664)
    skills = SecureSkills(loaders=[TrustedLocalSkills(str(tmp_path))])

    assert "guide" in skills._get_skill_reference("review", "guide.md")

    script = folder / "scripts" / "check.py"
    script.chmod(0o664)
    assert skills.script_bytes("review", "check.py") == b"print('ok')"

    script.unlink()
    script.symlink_to(folder / "SKILL.md")
    with pytest.raises(UntrustedSkillsDirectory):
        skills.script_bytes("review", "check.py")
