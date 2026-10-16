from __future__ import annotations

import copy
import json
import math
import re
import unicodedata
from typing import Any

MAX_ACCEPTANCE_REQUIREMENTS = 32
MAX_ACCEPTANCE_ARTIFACT_PATTERNS = 16
MAX_ACCEPTANCE_CONTRACT_BYTES = 64 * 1024
MAX_ACCEPTANCE_PARAMETERS_BYTES = 16 * 1024
MAX_ACCEPTANCE_JSON_DEPTH = 8
MAX_ACCEPTANCE_JSON_NODES = 512
MAX_ACCEPTANCE_STRING_CHARS = 4096
MAX_ACCEPTANCE_PATTERN_BYTES = 1024

_REQUIREMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_VALIDATOR_PART_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\Z")


class AcceptanceContractError(ValueError):
    pass


def _json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AcceptanceContractError("acceptance contract 只允许严格 JSON 值。") from error


def _validate_json_value(value: Any, *, label: str) -> None:
    nodes = 0

    def visit(current: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_ACCEPTANCE_JSON_NODES:
            raise AcceptanceContractError(f"{label} 的 JSON 节点过多。")
        if depth > MAX_ACCEPTANCE_JSON_DEPTH:
            raise AcceptanceContractError(f"{label} 的 JSON 嵌套过深。")
        if current is None or isinstance(current, bool | int):
            return
        if isinstance(current, float):
            if not math.isfinite(current):
                raise AcceptanceContractError(f"{label} 不允许非有限浮点数。")
            return
        if isinstance(current, str):
            if len(current) > MAX_ACCEPTANCE_STRING_CHARS:
                raise AcceptanceContractError(f"{label} 包含过长字符串。")
            return
        if isinstance(current, list):
            for item in current:
                visit(item, depth + 1)
            return
        if isinstance(current, dict):
            for key, item in current.items():
                if not isinstance(key, str) or not key or len(key) > 128:
                    raise AcceptanceContractError(f"{label} 的 JSON 对象键无效。")
                visit(item, depth + 1)
            return
        raise AcceptanceContractError(f"{label} 只允许严格 JSON 值。")

    visit(value, 0)


def validate_artifact_pattern(pattern: Any) -> str:
    if not isinstance(pattern, str) or not pattern:
        raise AcceptanceContractError("artifactPatterns 必须包含非空相对 glob。")
    if len(pattern.encode("utf-8")) > MAX_ACCEPTANCE_PATTERN_BYTES:
        raise AcceptanceContractError("artifactPatterns 中的相对 glob 过长。")
    if any(unicodedata.category(character).startswith("C") for character in pattern):
        raise AcceptanceContractError("artifactPatterns 中的相对 glob 包含控制字符。")
    if "\\" in pattern or pattern.startswith("/"):
        raise AcceptanceContractError("artifactPatterns 必须使用工作区相对 glob。")
    parts = pattern.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise AcceptanceContractError("artifactPatterns 必须使用工作区相对 glob。")
    if len(pattern) >= 2 and pattern[0].isalpha() and pattern[1] == ":":
        raise AcceptanceContractError("artifactPatterns 必须使用工作区相对 glob。")
    return pattern


def _normalize_validator_id(value: Any) -> str:
    if not isinstance(value, str) or value.count(":") != 1:
        raise AcceptanceContractError("validatorId 必须使用 <skill>:<validator> 格式。")
    skill_name, validator_name = value.split(":", 1)
    if not _VALIDATOR_PART_RE.fullmatch(skill_name) or not _VALIDATOR_PART_RE.fullmatch(
        validator_name
    ):
        raise AcceptanceContractError("validatorId 必须使用 <skill>:<validator> 格式。")
    return value


def _normalize_requirement(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {
        "id",
        "validatorId",
        "parameters",
        "artifactPatterns",
    }:
        raise AcceptanceContractError("acceptance requirement 字段无效。")
    requirement_id = raw.get("id")
    if not isinstance(requirement_id, str) or not _REQUIREMENT_ID_RE.fullmatch(requirement_id):
        raise AcceptanceContractError("acceptance requirement id 无效。")
    validator_id = _normalize_validator_id(raw.get("validatorId"))
    parameters = raw.get("parameters")
    if not isinstance(parameters, dict):
        raise AcceptanceContractError("acceptance requirement parameters 必须是 JSON 对象。")
    _validate_json_value(parameters, label="acceptance requirement parameters")
    if len(_json_bytes(parameters)) > MAX_ACCEPTANCE_PARAMETERS_BYTES:
        raise AcceptanceContractError("acceptance requirement parameters 超过 16 KiB。")
    patterns = raw.get("artifactPatterns")
    if (
        not isinstance(patterns, list)
        or len(patterns) > MAX_ACCEPTANCE_ARTIFACT_PATTERNS
        or len(set(patterns)) != len(patterns)
    ):
        raise AcceptanceContractError("artifactPatterns 必须是最多 16 个不重复相对 glob。")
    normalized_patterns = [validate_artifact_pattern(pattern) for pattern in patterns]
    return {
        "id": requirement_id,
        "validatorId": validator_id,
        "parameters": copy.deepcopy(parameters),
        "artifactPatterns": normalized_patterns,
    }


def normalize_acceptance_contract(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict) or set(raw) != {"version", "requirements"}:
        raise AcceptanceContractError("acceptance contract 字段无效。")
    version = raw.get("version")
    if isinstance(version, bool) or version != 1:
        raise AcceptanceContractError("acceptance contract version 只支持 1。")
    requirements = raw.get("requirements")
    if (
        not isinstance(requirements, list)
        or not 1 <= len(requirements) <= MAX_ACCEPTANCE_REQUIREMENTS
    ):
        raise AcceptanceContractError("acceptance contract 必须包含 1 至 32 个 requirements。")
    normalized_requirements = [_normalize_requirement(item) for item in requirements]
    requirement_ids = [item["id"] for item in normalized_requirements]
    if len(set(requirement_ids)) != len(requirement_ids):
        raise AcceptanceContractError("acceptance contract 包含重复 requirement id。")
    normalized = {"version": 1, "requirements": normalized_requirements}
    if len(_json_bytes(normalized)) > MAX_ACCEPTANCE_CONTRACT_BYTES:
        raise AcceptanceContractError("acceptance contract 超过 64 KiB。")
    return normalized
