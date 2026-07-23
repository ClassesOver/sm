import os
from pathlib import Path

from agno.skills import LocalSkills, Skills
from agno.skills.loaders.base import SkillLoader

BUILTIN_CODING_SKILLS_DIR = Path(__file__).with_name("builtin_skills")


def load_skills(path: str | None = None) -> Skills:
    skills_path = (path if path is not None else os.getenv("AGENT_SKILLS_DIR", "")).strip()
    loaders: list[SkillLoader] = []
    if skills_path:
        loaders.append(LocalSkills(skills_path))
    return Skills(loaders=loaders)


def load_builtin_coding_skills() -> Skills:
    return Skills(loaders=[LocalSkills(str(BUILTIN_CODING_SKILLS_DIR))])


def public_skill_metadata(skills: Skills) -> list[dict[str, str]]:
    return [
        {
            "id": skill.name,
            "name": skill.name,
            "description": skill.description or "",
        }
        for skill in skills.get_all_skills()
    ]
