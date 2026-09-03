import hashlib
import json
import os
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any

from agno.run import RunContext
from agno.skills import LocalSkills, Skills
from agno.skills.loaders.base import SkillLoader
from daytona.common.errors import DaytonaNotFoundError

from ..task_execution.acceptance import (
    AcceptanceContractError,
    normalize_acceptance_contract,
    validate_artifact_pattern,
)

CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY = "agentos_coding_skill_script_receipts"
CODING_SKILL_SCRIPT_ROOT = "/home/daytona/.agentos/skill-scripts"
MAX_SKILL_SCRIPT_RECEIPTS = 64
MAX_SKILL_VALIDATORS = 32
MAX_SKILL_VALIDATOR_SCRIPT_BYTES = 1024 * 1024
MAX_SKILL_VALIDATOR_TIMEOUT = 900
_VALIDATOR_NAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")
_SKILL_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SKILL_SCRIPT_HOOK_MARKER = "_agentos_skill_script_hook"


class SkillAcceptanceError(ValueError):
    pass


async def lock_sandbox_paths(sandbox: Any, permissions: dict[str, str]) -> None:
    if not permissions or any(
        not path.startswith("/home/daytona/.agentos/") or mode not in {"444", "555"}
        for path, mode in permissions.items()
    ):
        raise SkillAcceptanceError("只读脚本权限范围无效。")
    commands = [shlex.join(["sudo", "chown", "root:root", "--", *permissions])]
    for mode in sorted(set(permissions.values())):
        paths = [path for path, path_mode in permissions.items() if path_mode == mode]
        commands.append(shlex.join(["sudo", "chmod", mode, "--", *paths]))
    command = " && ".join(commands)
    result = await sandbox.process.exec(command, timeout=30)
    if getattr(result, "exit_code", None) != 0:
        raise SkillAcceptanceError("只读脚本所有权设置失败。")


@dataclass(frozen=True)
class SkillValidator:
    validator_id: str
    skill_name: str
    name: str
    script_name: str
    script_content: bytes
    script_sha256: str
    timeout: int
    artifact_patterns: tuple[str, ...]

    @property
    def install_digest(self) -> str:
        return hashlib.sha256(f"{self.validator_id}:{self.script_sha256}".encode()).hexdigest()


class SkillValidatorRegistry:
    def __init__(self, validators: dict[str, SkillValidator] | None = None):
        self._validators = dict(validators or {})

    @classmethod
    def from_skills(cls, skills: Skills | None) -> "SkillValidatorRegistry":
        if skills is None:
            return cls()
        validators: dict[str, SkillValidator] = {}
        for skill in skills.get_all_skills():
            metadata = skill.metadata or {}
            if not isinstance(metadata, dict):
                raise SkillAcceptanceError(f"Skill {skill.name} metadata 无效。")
            agentos = metadata.get("agentos")
            if agentos is None:
                continue
            if not isinstance(agentos, dict):
                raise SkillAcceptanceError(f"Skill {skill.name} agentos metadata 无效。")
            acceptance = agentos.get("acceptance")
            if acceptance is None:
                continue
            if not isinstance(acceptance, dict) or set(acceptance) != {"validators"}:
                raise SkillAcceptanceError(f"Skill {skill.name} acceptance metadata 无效。")
            raw_validators = acceptance.get("validators")
            if (
                not isinstance(raw_validators, dict)
                or not raw_validators
                or len(raw_validators) > MAX_SKILL_VALIDATORS
            ):
                raise SkillAcceptanceError(
                    f"Skill {skill.name} acceptance validators 必须包含 1 至 32 项。"
                )
            for name, config in raw_validators.items():
                validator = cls._load_validator(skill, name, config)
                if validator.validator_id in validators:
                    raise SkillAcceptanceError(f"重复 validator ID: {validator.validator_id}")
                validators[validator.validator_id] = validator
        return cls(validators)

    @staticmethod
    def _load_validator(skill: Any, name: Any, config: Any) -> SkillValidator:
        if not isinstance(name, str) or not _VALIDATOR_NAME_RE.fullmatch(name):
            raise SkillAcceptanceError(f"Skill {skill.name} validator 名称无效。")
        if not isinstance(config, dict) or set(config) != {
            "script",
            "timeout",
            "artifactPatterns",
        }:
            raise SkillAcceptanceError(f"Skill {skill.name}:{name} validator 配置无效。")
        script_name = config.get("script")
        if (
            not isinstance(script_name, str)
            or not script_name.endswith(".py")
            or Path(script_name).name != script_name
            or script_name not in skill.scripts
        ):
            raise SkillAcceptanceError("acceptance validator 只允许 Skill scripts/*.py。")
        timeout = config.get("timeout")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= MAX_SKILL_VALIDATOR_TIMEOUT
        ):
            raise SkillAcceptanceError(f"Skill {skill.name}:{name} timeout 必须是 1 至 900 秒。")
        raw_patterns = config.get("artifactPatterns")
        if (
            not isinstance(raw_patterns, list)
            or len(raw_patterns) > 16
            or len(set(raw_patterns)) != len(raw_patterns)
        ):
            raise SkillAcceptanceError(f"Skill {skill.name}:{name} artifactPatterns 无效。")
        try:
            patterns = tuple(validate_artifact_pattern(pattern) for pattern in raw_patterns)
        except AcceptanceContractError as error:
            raise SkillAcceptanceError(
                f"Skill {skill.name}:{name} artifactPatterns 无效。"
            ) from error
        script_path = Path(skill.source_path) / "scripts" / script_name
        if script_path.is_symlink() or not script_path.is_file():
            raise SkillAcceptanceError("acceptance validator 只允许 Skill scripts/*.py 普通文件。")
        content = script_path.read_bytes()
        if not content or len(content) > MAX_SKILL_VALIDATOR_SCRIPT_BYTES:
            raise SkillAcceptanceError("acceptance validator 脚本必须介于 1 byte 与 1 MiB。")
        return SkillValidator(
            validator_id=f"{skill.name}:{name}",
            skill_name=skill.name,
            name=name,
            script_name=script_name,
            script_content=content,
            script_sha256=hashlib.sha256(content).hexdigest(),
            timeout=timeout,
            artifact_patterns=patterns,
        )

    def require(self, validator_id: str) -> SkillValidator:
        validator = self._validators.get(validator_id)
        if validator is None:
            raise SkillAcceptanceError(f"未知 acceptance validator: {validator_id}")
        return validator

    def validate_contract(self, contract: Any) -> dict[str, Any]:
        try:
            normalized = normalize_acceptance_contract(contract)
        except AcceptanceContractError as error:
            raise SkillAcceptanceError(str(error)) from error
        for requirement in normalized["requirements"]:
            validator = self.require(requirement["validatorId"])
            unknown_patterns = sorted(
                set(requirement["artifactPatterns"]) - set(validator.artifact_patterns)
            )
            if unknown_patterns:
                raise SkillAcceptanceError(
                    f"{validator.validator_id} 未注册契约产物规则: {unknown_patterns[0]}"
                )
        return normalized

    def script_sha256(self) -> dict[str, str]:
        return {
            validator_id: validator.script_sha256
            for validator_id, validator in self._validators.items()
        }

    def __len__(self) -> int:
        return len(self._validators)


async def skill_script_receipt_hook(
    run_context: RunContext,
    function_name: str,
    function_call: Callable[..., Any],
    arguments: dict[str, Any],
    *,
    workspace_service: Any | None = None,
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
    readonly_path: str | None = None
    if workspace_service is not None:
        if (
            _SKILL_PATH_SEGMENT_RE.fullmatch(skill) is None
            or _SKILL_PATH_SEGMENT_RE.fullmatch(Path(path).name) is None
        ):
            return result
        thread_id = str(run_context.session_id or "")
        if not thread_id:
            return result
        install_digest = hashlib.sha256(f"{skill}:{path}:{digest}".encode()).hexdigest()
        install_dir = f"{CODING_SKILL_SCRIPT_ROOT}/{install_digest}"
        readonly_path = f"{install_dir}/{Path(path).name}"
        lock_key = f"skill-script-install:{workspace_service._hash(thread_id)}"
        async with workspace_service._async_client() as client:
            sandbox = await workspace_service._asandbox_for(client, thread_id)
            async with workspace_service.async_registry.locked(lock_key):
                current = ""
                for part in install_dir.strip("/").split("/"):
                    current = f"{current}/{part}"
                    try:
                        info = await sandbox.fs.get_file_info(current)
                    except DaytonaNotFoundError:
                        await sandbox.fs.create_folder(current, "755")
                        continue
                    if workspace_service._is_symlink(info) or not bool(
                        getattr(info, "is_dir", False)
                    ):
                        raise SkillAcceptanceError("Skill 脚本安装目录不是安全普通目录。")
                try:
                    info = await sandbox.fs.get_file_info(readonly_path)
                except DaytonaNotFoundError:
                    await sandbox.fs.upload_file(encoded, readonly_path)
                else:
                    if not workspace_service._is_regular_file(info):
                        raise SkillAcceptanceError("Skill 脚本安装路径不是普通文件。")
                installed = await sandbox.fs.download_file(readonly_path)
                if hashlib.sha256(installed).hexdigest() != digest:
                    raise SkillAcceptanceError("Skill 脚本安装摘要验证失败。")
                await lock_sandbox_paths(
                    sandbox,
                    {readonly_path: "555", install_dir: "555"},
                )
        payload = {**payload, "readonly_path": readonly_path}
        result = json.dumps(payload, ensure_ascii=False) if isinstance(result, str) else payload
    if not isinstance(run_context.session_state, dict):
        run_context.session_state = {}
    receipts = run_context.session_state.setdefault(CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY, {})
    if not isinstance(receipts, dict):
        receipts = {}
        run_context.session_state[CODING_SKILL_SCRIPT_RECEIPTS_STATE_KEY] = receipts
    key = f"{skill}:{path}"
    receipts.pop(key, None)
    receipts[key] = {
        "skill": skill,
        "path": path,
        "sha256": digest,
        "chars": len(content),
        **({"readonlyPath": readonly_path} if readonly_path is not None else {}),
    }
    while len(receipts) > MAX_SKILL_SCRIPT_RECEIPTS:
        del receipts[next(iter(receipts))]
    return result


def create_skill_script_hook(workspace_service: Any) -> Callable[..., Any]:
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
            workspace_service=workspace_service,
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


def load_sandbox_execution_skills(additional_path: str | None = None) -> Skills:
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
