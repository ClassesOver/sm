"""Skill 能力的稳定公共入口。"""

from .core import (
    TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY,
    create_skill_script_hook,
    is_skill_script_hook,
    load_skills,
    load_task_skills,
    public_skill_metadata,
    skill_script_receipt_hook,
)

__all__ = [
    "TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY",
    "create_skill_script_hook",
    "is_skill_script_hook",
    "load_skills",
    "load_task_skills",
    "public_skill_metadata",
    "skill_script_receipt_hook",
]
