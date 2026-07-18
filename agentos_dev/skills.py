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


def _trusted_uids() -> set[int]:
    configured = os.getenv("AGENT_SKILLS_TRUSTED_UID", "").strip()
    try:
        configured_uid = int(configured) if configured else os.geteuid()
    except ValueError as error:
        raise UntrustedSkillsDirectory("AGENT_SKILLS_TRUSTED_UID 必须是整数") from error
    if configured_uid < 0:
        raise UntrustedSkillsDirectory("AGENT_SKILLS_TRUSTED_UID 不能是负数")
    return {0, os.geteuid(), configured_uid}


def _trusted_path(path: Path, expected: str) -> None:
    metadata = path.lstat()
    _trusted_metadata(metadata, path, expected)


def _trusted_metadata(metadata, path: Path, expected: str) -> None:
    if stat.S_ISLNK(metadata.st_mode):
        raise UntrustedSkillsDirectory(f"技能路径不能是符号链接：{path}")
    correct_type = stat.S_ISDIR(metadata.st_mode) if expected == "directory" else stat.S_ISREG(metadata.st_mode)
    if not correct_type:
        expected_name = "目录" if expected == "directory" else "文件"
        raise UntrustedSkillsDirectory(f"技能路径必须是{expected_name}：{path}")
    if metadata.st_uid not in _trusted_uids() or metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise UntrustedSkillsDirectory(f"技能路径的所有者或权限模式不受信任：{path}")


def _read_trusted_bytes(path: Path) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        _trusted_metadata(os.fstat(descriptor), path, "file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


class TrustedLocalSkills(LocalSkills):
    def __init__(self, path: str, validate: bool = True):
        original = Path(path)
        _trusted_path(original, "directory")
        super().__init__(path, validate=validate)
        self.root = original.resolve()

    def load(self):
        self._validate_tree()
        skills = super().load()
        for skill in skills:
            folder = Path(skill.source_path)
            resolved_folder = folder.resolve()
            if resolved_folder == self.root or self.root not in resolved_folder.parents:
                raise UntrustedSkillsDirectory("技能目录超出配置的根目录")
            _trusted_path(folder, "directory")
            for child in [folder / "SKILL.md"] + [
                folder / category / name
                for category, names in (
                    ("scripts", skill.scripts), ("references", skill.references),
                )
                for name in names
            ]:
                category_path = child.parent
                if category_path != folder:
                    _trusted_path(category_path, "directory")
                if folder.resolve() not in child.resolve().parents:
                    raise UntrustedSkillsDirectory(
                        f"技能资源超出所属目录：{child}"
                    )
                _trusted_path(child, "file")
        return skills

    def _validate_tree(self) -> None:
        pending = [self.root]
        while pending:
            current = pending.pop()
            _trusted_path(current, "directory")
            for child in current.iterdir():
                metadata = child.lstat()
                if stat.S_ISDIR(metadata.st_mode):
                    _trusted_metadata(metadata, child, "directory")
                    pending.append(child)
                else:
                    _trusted_metadata(metadata, child, "file")

    def validate_resource(self, skill, category: str | None = None,
                          resource_path: str | None = None) -> Path:
        folder = Path(skill.source_path)
        _trusted_path(self.root, "directory")
        _trusted_path(folder, "directory")
        if self.root not in folder.resolve().parents:
            raise UntrustedSkillsDirectory("技能目录超出配置的根目录")
        target = folder / "SKILL.md" if category is None else folder / category / str(resource_path)
        if folder.resolve() not in target.resolve().parents:
            raise UntrustedSkillsDirectory("技能资源超出所属目录")
        parent = target.parent
        while parent != folder:
            _trusted_path(parent, "directory")
            parent = parent.parent
        _trusted_path(target, "file")
        return target


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
        loader = self._loader_for(skill)
        return loader.validate_resource(skill, category, resource_path)

    def _loader_for(self, skill) -> TrustedLocalSkills:
        folder = Path(skill.source_path).resolve()
        loader = next((
            item for item in self.loaders
            if isinstance(item, TrustedLocalSkills) and
            (folder == item.root or item.root in folder.parents)
        ), None)
        if loader is None:
            raise UntrustedSkillsDirectory("技能并非由受信任的本地加载器提供")
        return loader

    def _get_skill_instructions(self, skill_name: str) -> str:
        skill = self.get_skill(skill_name)
        if skill is None:
            return json.dumps({"error": f"未知技能：{skill_name}"})
        try:
            self._loader_for(skill).validate_resource(skill)
            return super()._get_skill_instructions(skill_name)
        except (OSError, UnicodeError, ValueError) as error:
            return json.dumps({"error": str(error), "skill_name": skill_name})

    def _get_skill_reference(self, skill_name: str, reference_path: str) -> str:
        skill = self.get_skill(skill_name)
        if skill is None or reference_path not in (skill.references or []):
            return json.dumps({"error": f"未知参考文档：{reference_path}"})
        try:
            target = self._skill_resource(skill_name, "references", reference_path)
            content = _read_trusted_bytes(target).decode("utf-8")
            return json.dumps({
                "skill_name": skill_name,
                "reference_path": reference_path,
                "content": content,
            })
        except (OSError, UnicodeError, ValueError) as error:
            return json.dumps({"error": str(error), "skill_name": skill_name})

    def read_skill_script(self, skill_name: str, script_path: str) -> str:
        try:
            content = _read_trusted_bytes(self._skill_resource(
                skill_name, "scripts", script_path
            )).decode("utf-8")
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
        content = _read_trusted_bytes(target)
        if len(content) > 256 * 1024:
            raise ValueError("技能脚本超过 256 KB")
        return content


def load_skills(path: str | None = None) -> SecureSkills:
    skills_path = (path if path is not None else os.getenv("AGENT_SKILLS_DIR", "")).strip()
    if not skills_path:
        return SecureSkills(loaders=[])
    return SecureSkills(loaders=[TrustedLocalSkills(skills_path)])
