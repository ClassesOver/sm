import hashlib
import json

import pytest
from agno.run import RunContext
from agno.skills import LocalSkills, Skills

from smart_reporting.skills import (
    TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
    load_task_skills,
    load_skills,
    public_skill_metadata,
    skill_script_receipt_hook,
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


@pytest.mark.anyio
async def test_skill_script_hook_records_read_content_but_not_execution_output():
    context = RunContext(run_id="run", session_id="session", session_state={})
    body = "print('validate')\n"

    async def read_script(**_kwargs):
        return json.dumps({"skill_name": "report", "script_path": "validate.py", "content": body})

    result = await skill_script_receipt_hook(
        context,
        "get_skill_script",
        read_script,
        {"skill_name": "report", "script_path": "validate.py", "execute": False},
    )

    assert json.loads(result)["content"] == body
    assert context.session_state[TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY] == {
        "report:validate.py": {
            "skill": "report",
            "path": "validate.py",
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
            "chars": len(body),
        }
    }

    await skill_script_receipt_hook(
        context,
        "get_skill_script",
        read_script,
        {"skill_name": "report", "script_path": "validate.py", "execute": True},
    )
    assert len(context.session_state[TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY]) == 1


def test_load_task_skills_only_loads_additional_directory(tmp_path):
    create_skill(tmp_path)
    skill_file = tmp_path / "review" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            "description: Review documents\n",
            "description: Review documents\nversion: 1.0.0\nauthor: Example\n",
        ),
        encoding="utf-8",
    )

    skills = load_task_skills(str(tmp_path))

    assert [skill.name for skill in skills.get_all_skills()] == ["review"]
    assert len(skills.loaders) == 1
    assert skills.loaders[0].validate is False


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
