"""Skill 能力的稳定公共入口。"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import TYPE_CHECKING, Any

_legacy_path = Path(__file__).resolve().parent.parent / "skills.py"
_spec = spec_from_file_location("smart_reporting._skills_legacy", _legacy_path)
if _spec is None or _spec.loader is None:
    raise ImportError("无法加载 Skill 实现。")
_legacy = module_from_spec(_spec)
_spec.loader.exec_module(_legacy)

for _name in dir(_legacy):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_legacy, _name)

if TYPE_CHECKING:
    SkillAcceptanceError: Any
    SkillValidator: Any
    SkillValidatorRegistry: Any
    CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY: str
    create_skill_script_hook: Any
    is_skill_script_hook: Any
    lock_sandbox_paths: Any
    skill_script_receipt_hook: Any
    load_skills: Any
    load_sandbox_execution_skills: Any
    load_builtin_coding_skills: Any
    public_skill_metadata: Any

__all__ = [
    "SkillAcceptanceError",
    "SkillValidator",
    "SkillValidatorRegistry",
    "create_skill_script_hook",
    "is_skill_script_hook",
    "load_skills",
    "load_sandbox_execution_skills",
    "load_builtin_coding_skills",
    "lock_sandbox_paths",
    "public_skill_metadata",
    "skill_script_receipt_hook",
]
