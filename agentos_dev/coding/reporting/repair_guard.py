from __future__ import annotations

import re
import shlex
from typing import Any

from .acceptance import REPORT_ARTIFACT_VALIDATOR_ID

REPORT_REPAIR_STATE_KEY = "agentos_reporting_repair_guard"

_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
_JSON_FIELD = re.compile(r'^\s*[+-]\s*"([^"\\]+)"\s*:')
_WRITE_TOOLS = frozenset(
    {
        "terminal",
        "process",
        "create_file",
        "create_files",
        "overwrite_file",
        "replace_text",
        "apply_patch",
        "patch",
    }
)
_READ_ONLY_REPAIR_COMMANDS = frozenset({"sha256sum", "stat", "wc"})


def _rejection(
    code: str,
    message: str,
    state: dict[str, Any],
    actions: list[str],
    *,
    retryable: bool = True,
    extra_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "rejected",
        "code": code,
        "message": message,
        "details": {
            "repairTarget": state.get("repairTarget"),
            "authorizedManifestMutationPaths": state.get("authorizedManifestMutationPaths", []),
            "verifyCount": state.get("verifyCount", 0),
            **(extra_details or {}),
        },
        "requiredActions": actions,
        "retryable": retryable,
    }


def _patch_paths(arguments: dict[str, Any]) -> set[str]:
    patch = arguments.get("patch")
    return set(_PATCH_PATH.findall(patch)) if isinstance(patch, str) else set()


def _manifest_patch_fields(arguments: dict[str, Any]) -> set[str] | None:
    patch = arguments.get("patch")
    if not isinstance(patch, str):
        return None
    fields: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith(("+", "-")) or line.startswith(("+++", "---")):
            continue
        match = _JSON_FIELD.match(line)
        if match is None:
            return None
        fields.add(match.group(1))
    return fields


def _is_read_only_repair_command(command: Any, repair_target: Any) -> bool:
    if not isinstance(command, str) or not isinstance(repair_target, str):
        return False
    try:
        arguments = shlex.split(command)
    except ValueError:
        return False
    if not arguments or arguments[0].rsplit("/", 1)[-1] not in _READ_ONLY_REPAIR_COMMANDS:
        return False
    return repair_target in arguments and not any(
        marker in command for marker in (";", "&&", "||", "|", ">", "<", "\n", "\r")
    )


class ReportRepairGuard:
    """将报告 validator 反馈收敛为一次性、定点的工具授权。"""

    @staticmethod
    def _state(session_state: dict[str, Any]) -> dict[str, Any]:
        value = session_state.get(REPORT_REPAIR_STATE_KEY)
        if not isinstance(value, dict):
            value = {"verifyCount": 0, "phase": "generation"}
            session_state[REPORT_REPAIR_STATE_KEY] = value
        return value

    def admission_rejection(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session_state: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if session_state is None:
            return None
        state = self._state(session_state)
        phase = state.get("phase")

        if tool_name == "verify" and arguments.get("validator_id") == REPORT_ARTIFACT_VALIDATOR_ID:
            if state["verifyCount"] >= 2:
                return _rejection(
                    "report_verify_limit_reached",
                    "报告正式验收最多执行两次，本次未执行。",
                    state,
                    ["保留第二次验收反馈并结束当前 Coding Attempt，不得继续修改产物。"],
                    retryable=False,
                )
            if phase == "repair" and not self._repair_complete(state):
                return _rejection(
                    "report_repair_incomplete",
                    "定点修复及 manifest 元数据同步尚未完成，本次验收未执行。",
                    state,
                    self._remaining_actions(state),
                )
            return None

        if phase not in {"repair", "exhausted", "passed"} or tool_name not in _WRITE_TOOLS:
            return None
        if phase in {"exhausted", "passed"}:
            return _rejection(
                "report_repair_closed",
                "报告修复窗口已经关闭，本次写操作未执行。",
                state,
                ["不得继续修改产物；使用已有验收结果结束当前任务。"],
                retryable=False,
            )
        if not isinstance(state.get("repairTarget"), str):
            return _rejection(
                "report_repair_target_missing",
                "validator 未提供唯一 repairTarget，服务端拒绝猜测性修改。",
                state,
                ["保留 failedRequirements 并结束当前 Attempt，由契约或程序修复后重试。"],
                retryable=False,
            )
        if tool_name == "terminal" and _is_read_only_repair_command(
            arguments.get("command"), state["repairTarget"]
        ):
            return None
        if tool_name != "apply_patch":
            return _rejection(
                "report_repair_tool_forbidden",
                "验收失败后只允许一次性 apply_patch 定点修复，本次工具未执行。",
                state,
                self._remaining_actions(state),
            )
        return self._patch_rejection(arguments, state)

    def _patch_rejection(
        self, arguments: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any] | None:
        paths = _patch_paths(arguments)
        repair_target = state["repairTarget"]
        manifest_target = state.get("manifestTarget")
        if paths == {repair_target}:
            flag = (
                "manifestPatchApplied"
                if repair_target == manifest_target
                else "markdownPatchApplied"
            )
            if state.get(flag):
                return _rejection(
                    "report_repair_already_applied",
                    "repairTarget 已完成一次补丁，拒绝重复散改。",
                    state,
                    self._remaining_actions(state),
                )
            if repair_target == manifest_target:
                return self._manifest_field_rejection(arguments, state)
            return self._markdown_patch_rejection(arguments, state)
        if paths == {manifest_target} and state.get("markdownPatchApplied"):
            if state.get("manifestPatchApplied"):
                return _rejection(
                    "report_repair_already_applied",
                    "manifest 元数据已经同步一次，拒绝再次修改。",
                    state,
                    self._remaining_actions(state),
                )
            return self._manifest_field_rejection(arguments, state)
        return _rejection(
            "report_repair_path_forbidden",
            "补丁路径不属于 validator 授权的定点修复范围。",
            state,
            self._remaining_actions(state),
        )

    @staticmethod
    def _markdown_patch_rejection(
        arguments: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any] | None:
        patch = arguments.get("patch")
        if not isinstance(patch, str):
            additions = ""
            removals = ""
        else:
            additions = "\n".join(
                line[1:]
                for line in patch.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            removals = "\n".join(
                line[1:]
                for line in patch.splitlines()
                if line.startswith("-") and not line.startswith("---")
            )
        unresolved = [
            item for item in state.get("requiredPatchAdditions", []) if item not in additions
        ]
        unresolved.extend(
            item for item in state.get("requiredPatchRemovals", []) if item not in removals
        )
        if unresolved:
            return _rejection(
                "report_repair_patch_incomplete",
                "补丁尚未覆盖 validator 列出的全部失败项，未写入工作区。",
                state,
                ["在同一个 apply_patch 中处理 unresolvedFeedback 的全部项目后重新提交。"],
                extra_details={"unresolvedFeedback": unresolved[:50]},
            )
        return None

    @staticmethod
    def _manifest_field_rejection(
        arguments: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any] | None:
        authorized = set(state.get("authorizedManifestMutationPaths") or [])
        if not authorized:
            return _rejection(
                "report_manifest_mutation_forbidden",
                "validator 没有提供可执行的 manifest 字段授权，补丁未写入工作区。",
                state,
                ["保留 schemaErrors 并修复 validator 契约，不得猜测性修改 manifest。"],
                retryable=False,
            )
        if authorized == {"markdown.size", "markdown.sha256"}:
            fields = _manifest_patch_fields(arguments)
            if fields != {"size", "sha256"}:
                return _rejection(
                    "report_manifest_mutation_forbidden",
                    "manifest 补丁只能同时更新 markdown.size 和 markdown.sha256。",
                    state,
                    ["重新计算 Markdown 的 size 和 SHA-256，并在一个补丁中只更新这两个字段。"],
                )
        elif all("." in path for path in authorized):
            fields = _manifest_patch_fields(arguments)
            allowed_fields = {path.rsplit(".", 1)[-1] for path in authorized}
            if fields is None or not fields or not fields <= allowed_fields:
                return _rejection(
                    "report_manifest_mutation_forbidden",
                    "manifest 补丁包含 authorizedManifestMutationPaths 之外的字段。",
                    state,
                    ["只修改授权路径的末级字段，并在同一个 apply_patch 中完成。"],
                )
        return None

    def record_result(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: Any,
        session_state: dict[str, Any] | None,
    ) -> None:
        if session_state is None or not isinstance(result, dict):
            return
        state = self._state(session_state)
        if (
            tool_name == "apply_patch"
            and result.get("ok") is True
            and state.get("phase") == "repair"
        ):
            paths = _patch_paths(arguments)
            if paths == {state.get("manifestTarget")}:
                state["manifestPatchApplied"] = True
            if paths == {state.get("repairTarget")} and state.get("repairTarget") != state.get(
                "manifestTarget"
            ):
                state["markdownPatchApplied"] = True
            return
        if tool_name != "verify" or arguments.get("validator_id") != REPORT_ARTIFACT_VALIDATOR_ID:
            return
        if (isinstance(result.get("code"), str) and result["code"].startswith("report_")) or (
            "execution_id" not in result
            and result.get("code") != "verification_acceptance_failed"
            and "acceptance" not in result
        ):
            return

        state["verifyCount"] = int(state.get("verifyCount", 0)) + 1
        failed = result.get("failedRequirements")
        if not isinstance(failed, list) or not failed:
            state["phase"] = "passed"
            return
        details: list[dict[str, Any]] = []
        for item in failed:
            if not isinstance(item, dict):
                continue
            item_details = item.get("details")
            if isinstance(item_details, dict):
                details.append(item_details)
        repair_targets = {
            item["repairTarget"] for item in details if isinstance(item.get("repairTarget"), str)
        }
        manifest_targets = {
            path
            for path in arguments.get("artifact_paths", [])
            if isinstance(path, str) and path.endswith(".manifest.json")
        }
        state.update(
            {
                "phase": "exhausted" if state["verifyCount"] >= 2 else "repair",
                "failedRequirements": failed,
                "repairTarget": next(iter(repair_targets)) if len(repair_targets) == 1 else None,
                "manifestTarget": next(iter(manifest_targets))
                if len(manifest_targets) == 1
                else None,
                "authorizedManifestMutationPaths": sorted(
                    {
                        path
                        for item in details
                        for path in item.get("authorizedManifestMutationPaths", [])
                        if isinstance(path, str)
                    }
                ),
                "requiredPatchAdditions": sorted(
                    {
                        value
                        for item in details
                        for key in (
                            "missingCitationMarkers",
                            "missingSectionMarkers",
                            "missingMarkdownChartPaths",
                        )
                        for value in item.get(key, [])
                        if isinstance(value, str)
                    }
                ),
                "requiredPatchRemovals": sorted(
                    {
                        value
                        for item in details
                        for key in ("visibleMachineTerms", "forbiddenDerivedClaims")
                        for value in item.get(key, [])
                        if isinstance(value, str)
                    }
                    | {
                        issue["claim"]
                        for item in details
                        for key in ("contradictoryPeriodClaims", "unboundPeriodClaims")
                        for issue in item.get(key, [])
                        if isinstance(issue, dict) and isinstance(issue.get("claim"), str)
                    }
                ),
                "markdownPatchApplied": False,
                "manifestPatchApplied": False,
            }
        )

    @staticmethod
    def _repair_complete(state: dict[str, Any]) -> bool:
        if state.get("repairTarget") == state.get("manifestTarget"):
            return state.get("manifestPatchApplied") is True
        return (
            state.get("markdownPatchApplied") is True and state.get("manifestPatchApplied") is True
        )

    @staticmethod
    def _remaining_actions(state: dict[str, Any]) -> list[str]:
        actions = []
        if state.get("repairTarget") != state.get("manifestTarget") and not state.get(
            "markdownPatchApplied"
        ):
            actions.append(f"使用一次 apply_patch 修复 {state.get('repairTarget')} 的全部失败项。")
        if not state.get("manifestPatchApplied"):
            actions.append(
                f"使用一次 apply_patch 仅更新 {state.get('manifestTarget')} 中授权的 manifest 路径。"
            )
        return actions or ["完成修复后只再执行一次正式 validator。"]
