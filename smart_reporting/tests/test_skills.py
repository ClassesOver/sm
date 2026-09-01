import hashlib
import json

import pytest
from agno.run import RunContext
from agno.skills import LocalSkills, Skills

from smart_reporting.reporting.delivery.acceptance import load_reporting_skills
from smart_reporting.skills import (
    CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
    SkillAcceptanceError,
    SkillValidatorRegistry,
    load_sandbox_execution_skills,
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


def test_load_reporting_skills_includes_sandbox_environment_without_tool_contract():
    skills = load_reporting_skills(None)

    assert {skill.name for skill in skills.get_all_skills()} == {
        "report-visualization",
        "sandbox-tooling",
    }
    skill = next(skill for skill in skills.get_all_skills() if skill.name == "sandbox-tooling")
    assert "Daytona" in skill.description
    assert {tool.name for tool in skills.get_tools()} == {
        "get_skill_instructions",
        "get_skill_reference",
        "get_skill_script",
    }

    instructions = skill.instructions
    assert "sandbox-tools-20260723" not in instructions
    assert "`rg`" in instructions
    assert "LibreOffice" in instructions
    assert "pytest" in instructions
    assert "network_block_all" in instructions
    assert "当前 Task 实际注册的工具" in instructions
    assert "create_analysis_file" in instructions
    assert "overwrite_analysis_file" in instructions
    assert "仅轮询同一 Task 启动的运行进程" in instructions
    for retired_tool_name in (
        "create_files",
        "overwrite_file",
        "replace_text",
        "apply_patch",
    ):
        assert retired_tool_name not in instructions
    assert "image-source" not in instructions
    assert "镜像能力的权威来源" not in instructions
    assert "co" + "dex" not in instructions.lower()


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
    assert context.session_state[CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY] == {
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
    assert len(context.session_state[CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY]) == 1


def test_load_sandbox_execution_skills_only_loads_additional_directory(tmp_path):
    create_skill(tmp_path)
    skill_file = tmp_path / "review" / "SKILL.md"
    skill_file.write_text(
        skill_file.read_text(encoding="utf-8").replace(
            "description: Review documents\n",
            "description: Review documents\nversion: 1.0.0\nauthor: Example\n",
        ),
        encoding="utf-8",
    )

    skills = load_sandbox_execution_skills(str(tmp_path))

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


def test_skill_validator_registry_pins_server_script_and_rules(tmp_path):
    create_skill(tmp_path, "review")
    skill_file = tmp_path / "review" / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: review\n"
        "description: Review documents\n"
        "metadata:\n"
        "  agentos:\n"
        "    acceptance:\n"
        "      validators:\n"
        "        report:\n"
        "          script: check.py\n"
        "          timeout: 17\n"
        "          artifactPatterns:\n"
        "            - reports/*.json\n"
        "---\n"
        "Review instructions\n",
        encoding="utf-8",
    )
    skills = load_skills(str(tmp_path))

    registry = SkillValidatorRegistry.from_skills(skills)
    validator = registry.require("review:report")

    assert validator.validator_id == "review:report"
    assert validator.timeout == 17
    assert validator.artifact_patterns == ("reports/*.json",)
    assert validator.script_sha256 == hashlib.sha256(b"print('ok')").hexdigest()
    assert validator.script_content == b"print('ok')"


def test_skill_validator_registry_rejects_non_python_or_unregistered_contract_rules(tmp_path):
    create_skill(tmp_path, "review")
    skill_file = tmp_path / "review" / "SKILL.md"
    skill_file.write_text(
        "---\n"
        "name: review\n"
        "description: Review documents\n"
        "metadata:\n"
        "  agentos:\n"
        "    acceptance:\n"
        "      validators:\n"
        "        report:\n"
        "          script: ../references/guide.md\n"
        "          timeout: 17\n"
        "          artifactPatterns: []\n"
        "---\n"
        "Review instructions\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillAcceptanceError, match="scripts/.*py"):
        SkillValidatorRegistry.from_skills(load_skills(str(tmp_path)))

    skill_file.write_text(
        skill_file.read_text(encoding="utf-8")
        .replace("../references/guide.md", "check.py")
        .replace("artifactPatterns: []", "artifactPatterns: [reports/*.json]"),
        encoding="utf-8",
    )
    registry = SkillValidatorRegistry.from_skills(load_skills(str(tmp_path)))
    with pytest.raises(SkillAcceptanceError, match="产物规则"):
        registry.validate_contract(
            {
                "version": 1,
                "requirements": [
                    {
                        "id": "report",
                        "validatorId": "review:report",
                        "parameters": {},
                        "artifactPatterns": ["reports/*.pdf"],
                    }
                ],
            }
        )
