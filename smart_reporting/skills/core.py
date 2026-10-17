import hashlib
import json
import os
from collections.abc import Callable
from inspect import isawaitable
from typing import Any

from agno.run import RunContext
from agno.skills import LocalSkills, Skills
from agno.skills.loaders.base import SkillLoader

TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY = "agentos_task_execution_skill_script_receipts"
MAX_SKILL_SCRIPT_RECEIPTS = 64
_SKILL_SCRIPT_HOOK_MARKER = "_agentos_skill_script_hook"


async def skill_script_receipt_hook(
    run_context: RunContext,
    function_name: str,
    function_call: Callable[..., Any],
    arguments: dict[str, Any],
) -> Any:
    result: Any = function_call(**arguments)
    if isawaitable(result):
        result = await result
    if function_name != "get_skill_script" or arguments.get("execute", False) is True:
        return result
    try:
        payload = json.loads(result) if isinstance(result, str) else result
    except (TypeError, ValueError):
        return result
    if not isinstance(payload, dict) or "error" in payload:
        return result
    skill = payload.get("skill_name")
    path = payload.get("script_path")
    content = payload.get("content")
    if (
        not isinstance(skill, str)
        or not skill
        or not isinstance(path, str)
        or not path
        or not isinstance(content, str)
        or not content
    ):
        return result
    encoded = content.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    if not isinstance(run_context.session_state, dict):
        run_context.session_state = {}
    legacy_receipts = run_context.session_state.pop("agentos_coding_skill_script_receipts", None)
    if (
        TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY not in run_context.session_state
        and isinstance(legacy_receipts, dict)
    ):
        run_context.session_state[TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY] = legacy_receipts
    receipts = run_context.session_state.setdefault(
        TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY, {}
    )
    if not isinstance(receipts, dict):
        receipts = {}
        run_context.session_state[TASK_EXECUTION_SKILL_SCRIPT_RECEIPTS_STATE_KEY] = receipts
    key = f"{skill}:{path}"
    receipts.pop(key, None)
    receipts[key] = {
        "skill": skill,
        "path": path,
        "sha256": digest,
        "chars": len(content),
    }
    while len(receipts) > MAX_SKILL_SCRIPT_RECEIPTS:
        del receipts[next(iter(receipts))]
    return result


def create_skill_script_hook() -> Callable[..., Any]:
    async def hook(
        run_context: RunContext,
        function_name: str,
        function_call: Callable[..., Any],
        arguments: dict[str, Any],
    ) -> Any:
        return await skill_script_receipt_hook(
            run_context,
            function_name,
            function_call,
            arguments,
        )

    setattr(hook, _SKILL_SCRIPT_HOOK_MARKER, True)
    return hook


def is_skill_script_hook(hook: Callable[..., Any]) -> bool:
    return getattr(hook, _SKILL_SCRIPT_HOOK_MARKER, False) is True


def load_skills(path: str | None = None) -> Skills:
    skills_path = (path if path is not None else os.getenv("AGENT_SKILLS_DIR", "")).strip()
    loaders: list[SkillLoader] = []
    if skills_path:
        loaders.append(LocalSkills(skills_path))
    return Skills(loaders=loaders)


def load_task_skills(additional_path: str | None = None) -> Skills:
    loaders: list[SkillLoader] = []
    skills_path = (additional_path or "").strip()
    if skills_path:
        loaders.append(LocalSkills(skills_path, validate=False))
    return Skills(loaders=loaders)


def public_skill_metadata(skills: Skills) -> list[dict[str, str]]:
    return [
        {
            "id": skill.name,
            "name": skill.name,
            "description": skill.description or "",
        }
        for skill in skills.get_all_skills()
    ]
