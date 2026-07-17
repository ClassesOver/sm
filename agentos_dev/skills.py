import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from agno.skills import LocalSkills, Skills
from agno.tools.function import Function


class UntrustedSkillsDirectory(ValueError):
    pass


def _trusted_directory(path: Path) -> None:
    metadata = path.stat()
    if metadata.st_mode & stat.S_IWOTH or metadata.st_uid not in (0, os.geteuid()):
        raise UntrustedSkillsDirectory(f"技能目录的所有者或权限模式不受信任：{path}")


class TrustedLocalSkills(LocalSkills):
    def __init__(self, path: str, validate: bool = True):
        original = Path(path)
        if original.is_symlink():
            raise UntrustedSkillsDirectory("技能根目录不能是符号链接")
        super().__init__(path, validate=validate)
        if not self.path.is_dir():
            raise UntrustedSkillsDirectory("技能根路径必须是目录")
        _trusted_directory(self.path)

    def load(self):
        skills = super().load()
        for skill in skills:
            folder = Path(skill.source_path)
            resolved_folder = folder.resolve()
            if folder.is_symlink() or (
                resolved_folder != self.path and self.path not in resolved_folder.parents
            ):
                raise UntrustedSkillsDirectory("技能目录超出配置的根目录")
            _trusted_directory(folder)
            for child in [folder / "SKILL.md"] + [
                folder / category / name
                for category, names in (
                    ("scripts", skill.scripts), ("references", skill.references),
                )
                for name in names
            ]:
                if child.is_symlink() or folder.resolve() not in child.resolve().parents:
                    raise UntrustedSkillsDirectory(
                        f"技能资源超出所属目录：{child}"
                    )
        return skills


class SecureSkills(Skills):
    def _load_skills(self) -> None:
        for loader in self.loaders:
            for skill in loader.load():
                self._skills[skill.name] = skill

    def get_tools(self):
        return [
            Function(
                name="get_skill_instructions",
                description="加载技能的完整说明。",
                entrypoint=self._get_skill_instructions,
            ),
            Function(
                name="get_skill_reference",
                description="读取技能声明的一份参考文档。",
                entrypoint=self._get_skill_reference,
            ),
            Function(
                name="get_skill_script",
                description="读取技能声明的一个脚本；此工具不会执行脚本。",
                entrypoint=self.read_skill_script,
            ),
        ]

    def get_system_prompt_snippet(self) -> str:
        value = super().get_system_prompt_snippet()
        value = value.replace(
            "3. `get_skill_script(skill_name, script_path, execute=False)` - Read or run scripts",
            "3. `get_skill_script(skill_name, script_path)` - 仅可读取脚本源码",
        )
        value = value.replace(
            "4. **Scripts**: Use `get_skill_script` to read or execute scripts from a skill",
            "4. **脚本**：使用 `get_skill_script` 读取；仅可通过已确认的 `run_skill_script` 工具执行",
        )
        return value

    @staticmethod
    def skill_id(name: str) -> str:
        return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]

    def public_metadata(self, limit: int = 50) -> list[dict[str, str]]:
        return [
            {
                "id": self.skill_id(skill.name),
                "name": skill.name,
                "description": skill.description or "",
            }
            for skill in self.get_all_skills()[:limit]
        ]

    def skill_by_id(self, skill_id: str):
        return next(
            (
                skill for skill in self.get_all_skills()
                if self.skill_id(skill.name) == skill_id
            ),
            None,
        )

    def _skill_resource(self, skill_name: str, category: str, resource_path: str) -> Path:
        skill = self.get_skill(skill_name)
        if skill is None:
            raise ValueError(f"未知技能：{skill_name}")
        declared = skill.scripts if category == "scripts" else skill.references
        if resource_path not in declared:
            category_name = "脚本" if category == "scripts" else "参考文档"
            raise ValueError(f"未知{category_name}：{resource_path}")
        folder = Path(skill.source_path).resolve()
        target = folder / category / resource_path
        if target.is_symlink() or folder not in target.resolve().parents:
            raise ValueError("技能资源超出所属目录")
        return target

    def read_skill_script(self, skill_name: str, script_path: str) -> str:
        try:
            content = self._skill_resource(
                skill_name, "scripts", script_path
            ).read_text(encoding="utf-8")
            if len(content.encode("utf-8")) > 256 * 1024:
                raise ValueError("技能脚本超过 256 KB")
            return json.dumps({
                "skill_name": skill_name,
                "script_path": script_path,
                "content": content,
            })
        except (OSError, UnicodeError, ValueError) as error:
            return json.dumps({"error": str(error), "skill_name": skill_name})

    def script_bytes(self, skill_name: str, script_path: str) -> bytes:
        target = self._skill_resource(skill_name, "scripts", script_path)
        content = target.read_bytes()
        if len(content) > 256 * 1024:
            raise ValueError("技能脚本超过 256 KB")
        return content


def load_skills(path: str | None = None) -> SecureSkills:
    skills_path = (path if path is not None else os.getenv("AGENT_SKILLS_DIR", "")).strip()
    if not skills_path:
        return SecureSkills(loaders=[])
    return SecureSkills(loaders=[TrustedLocalSkills(skills_path)])
