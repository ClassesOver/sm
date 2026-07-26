from __future__ import annotations

import copy
import fnmatch
import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
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


def requirement_digest(requirement: dict[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(_normalize_requirement(requirement))).hexdigest()


@dataclass(frozen=True)
class AcceptanceDecision:
    accepted: bool
    code: str | None
    message: str
    details: dict[str, Any]
    required_actions: list[str]
    summary: dict[str, Any] | None = None


class AcceptancePolicy:
    """只依据不可变契约和持久化 execution receipt 评估语义验收。"""

    def evaluate(
        self,
        contract: dict[str, Any],
        executions: list[Any],
        mutation_sequence: int,
        artifacts: list[dict[str, Any]],
        validator_sha256: dict[str, str],
    ) -> AcceptanceDecision:
        normalized = normalize_acceptance_contract(contract)
        final_artifacts: dict[str, dict[str, Any]] = {}
        for item in artifacts:
            path = item.get("path") if isinstance(item, dict) else None
            if isinstance(path, str) and isinstance(item.get("sha256"), str):
                final_artifacts[path] = item
        requirement_states: list[dict[str, Any]] = []
        for requirement in normalized["requirements"]:
            requirement_states.append(
                self._requirement_state(
                    requirement,
                    executions,
                    mutation_sequence,
                    final_artifacts,
                    validator_sha256.get(requirement["validatorId"]),
                )
            )

        statuses = {item["status"] for item in requirement_states}
        details = {"version": 1, "requirements": requirement_states}
        if "missing" in statuses:
            return AcceptanceDecision(
                False,
                "finish_acceptance_missing",
                "任务验收契约缺少语义验证证据。",
                details,
                ["运行 details.requirements 中缺失的 validator_id 后重新提交验收。"],
            )
        if "failed" in statuses:
            return AcceptanceDecision(
                False,
                "finish_acceptance_failed",
                "任务验收契约的语义验证未通过。",
                details,
                ["修复失败 requirement，并重新运行对应 validator_id。"],
            )
        if "stale" in statuses:
            return AcceptanceDecision(
                False,
                "finish_acceptance_stale",
                "任务验收契约的语义验证证据已过期。",
                details,
                ["在当前 mutation 和当前 validator 版本上重新运行对应 validator_id。"],
            )
        summary = {
            "version": 1,
            "requirements": [
                {
                    "id": item["id"],
                    "validatorId": item["validatorId"],
                    "status": "passed",
                    "executionId": item["executionId"],
                }
                for item in requirement_states
            ],
        }
        return AcceptanceDecision(True, None, "语义验收通过。", details, [], summary)

    @staticmethod
    def _requirement_state(
        requirement: dict[str, Any],
        executions: list[Any],
        mutation_sequence: int,
        final_artifacts: dict[str, dict[str, Any]],
        expected_validator_sha256: str | None,
    ) -> dict[str, Any]:
        base = {
            "id": requirement["id"],
            "validatorId": requirement["validatorId"],
        }
        expected_requirement_digest = requirement_digest(requirement)
        matching: list[tuple[Any, dict[str, Any], dict[str, Any]]] = []
        for execution in executions:
            receipt = getattr(execution, "operation_receipt", None)
            acceptance = receipt.get("acceptance") if isinstance(receipt, dict) else None
            if (
                not isinstance(acceptance, dict)
                or acceptance.get("validatorId") != requirement["validatorId"]
            ):
                continue
            results = acceptance.get("requirements")
            if not isinstance(results, list):
                continue
            result = next(
                (
                    item
                    for item in results
                    if isinstance(item, dict) and item.get("id") == requirement["id"]
                ),
                None,
            )
            if isinstance(result, dict):
                matching.append((execution, acceptance, result))
        if not matching:
            return {**base, "status": "missing"}

        for execution, acceptance, result in reversed(matching):
            current = bool(
                expected_validator_sha256 is not None
                and getattr(execution, "is_verification", False)
                and getattr(execution, "status", None) == "completed"
                and getattr(execution, "exit_code", None) == 0
                and getattr(execution, "mutation_sequence", None) == mutation_sequence
                and acceptance.get("mutationSequence") == mutation_sequence
                and acceptance.get("validatorSha256") == expected_validator_sha256
                and result.get("requirementDigest") == expected_requirement_digest
            )
            if not current:
                continue
            execution_id = str(getattr(execution, "execution_id", "") or "")
            if result.get("passed") is not True:
                return {
                    **base,
                    "status": "failed",
                    "executionId": execution_id,
                    **(
                        {"message": result["message"]}
                        if isinstance(result.get("message"), str)
                        else {}
                    ),
                }
            evidence_artifacts = acceptance.get("artifacts")
            if not AcceptancePolicy._artifacts_cover_requirement(
                requirement,
                evidence_artifacts if isinstance(evidence_artifacts, list) else [],
                final_artifacts,
            ):
                return {
                    **base,
                    "status": "failed",
                    "executionId": execution_id,
                    "message": "语义证据未绑定到最终交付产物。",
                }
            return {**base, "status": "passed", "executionId": execution_id}
        return {**base, "status": "stale"}

    @staticmethod
    def _artifacts_cover_requirement(
        requirement: dict[str, Any],
        evidence_artifacts: list[Any],
        final_artifacts: dict[str, dict[str, Any]],
    ) -> bool:
        evidence = [
            item
            for item in evidence_artifacts
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and isinstance(item.get("sha256"), str)
        ]
        for pattern in requirement["artifactPatterns"]:
            matched = False
            for item in evidence:
                if not fnmatch.fnmatchcase(item["path"], pattern):
                    continue
                final = final_artifacts.get(item["path"])
                if final is not None and final.get("sha256") == item["sha256"]:
                    matched = True
                    break
            if not matched:
                return False
        return True
