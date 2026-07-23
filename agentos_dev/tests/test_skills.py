from agno.skills import LocalSkills, Skills

from agentos_dev.skills import (
    load_builtin_coding_skills,
    load_skills,
    public_skill_metadata,
)


def create_skill(root, name="review"):
    folder = root / name
    (folder / "scripts").mkdir(parents=True)
    (folder / "references").mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review documents\n---\nReview instructions\n",
        encoding="utf-8",
    )
    (folder / "scripts" / "check.py").write_text("print('ok')", encoding="utf-8")
    (folder / "references" / "guide.md").write_text("guide", encoding="utf-8")


def test_load_skills_uses_official_local_loader(tmp_path):
    create_skill(tmp_path)

    skills = load_skills(str(tmp_path))

    assert isinstance(skills, Skills)
    assert len(skills.loaders) == 1
    assert isinstance(skills.loaders[0], LocalSkills)
    assert [skill.name for skill in skills.get_all_skills()] == ["review"]
    assert {tool.name for tool in skills.get_tools()} == {
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
    }


def test_load_skills_without_path_uses_no_loaders(monkeypatch):
    monkeypatch.delenv("AGENT_SKILLS_DIR", raising=False)

    skills = load_skills()

    assert isinstance(skills, Skills)
    assert skills.loaders == []
    assert skills.get_all_skills() == []


def test_load_builtin_coding_skills_describes_sandbox_image_capabilities():
    skills = load_builtin_coding_skills()

    assert [skill.name for skill in skills.get_all_skills()] == ["sandbox-tooling"]
    skill = skills.get_all_skills()[0]
    assert "Daytona" in skill.description
    assert {tool.name for tool in skills.get_tools()} == {
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
    }

    instructions = skill.instructions
    assert "sandbox-tools-20260723" not in instructions
    assert "ripgrep" in instructions
    assert "LibreOffice" in instructions
    assert "pytest" in instructions
    assert "Jedi" in instructions
    assert "WebSockets" in instructions
    assert "PostgreSQL" in instructions
    assert "Playwright" in instructions
    assert "network_block_all" in instructions
    assert "项目既有检查入口" in instructions
    assert "格式检查、lint、类型检查和测试" in instructions
    assert "git diff --check" in instructions
    assert "未执行检查及原因" in instructions
    assert "image-source" not in instructions
    assert "镜像能力的权威来源" not in instructions


def test_public_skill_metadata_uses_skill_name_as_id(tmp_path):
    create_skill(tmp_path)
    skills = load_skills(str(tmp_path))

    assert public_skill_metadata(skills) == [
        {
            "id": "review",
            "name": "review",
            "description": "Review documents",
        }
    ]
