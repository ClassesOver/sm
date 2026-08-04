from __future__ import annotations

import hashlib
import json
from typing import Any

from .acceptance import REPORT_ARTIFACT_VALIDATOR_ID

REPORT_REPAIR_STATE_KEY = "agentos_reporting_repair_guard"

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
        "register_report_charts",
        "render_report_draft",
        "resume_report_draft",
        "repair_report_draft",
    }
)
_POST_VERIFY_ALLOWED_TOOLS = frozenset(
    {"repair_report_draft", "verify", "read_tool_output", "update_plan", "finish_task"}
)


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
            "verifyCount": state.get("verifyCount", 0),
            "requiredIssueIds": state.get("requiredIssueIds", []),
            **(extra_details or {}),
        },
        "requiredActions": actions,
        "retryable": retryable,
    }


class ReportRepairGuard:
    """把报告验收收敛为服务端渲染和最多一次结构化定点修复。"""

    @staticmethod
    def _state(session_state: dict[str, Any]) -> dict[str, Any]:
        value = session_state.get(REPORT_REPAIR_STATE_KEY)
        if not isinstance(value, dict):
            value = {
                "verifyCount": 0,
                "phase": "generation",
                "draftRendered": False,
                "draftRepairApplied": False,
            }
            session_state[REPORT_REPAIR_STATE_KEY] = value
        return value

    def record_draft_rendered(
        self,
        session_state: dict[str, Any],
        *,
        markdown_path: str,
        markdown_sha256: str,
    ) -> None:
        state = self._state(session_state)
        state.update(
            {
                "draftRendered": True,
                "phase": "rendered",
                "markdownPath": markdown_path,
                "markdownSha256": markdown_sha256,
            }
        )

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
            if int(state.get("verifyCount", 0)) >= 2:
                return _rejection(
                    "report_verify_limit_reached",
                    "报告正式验收最多执行两次，本次未执行。",
                    state,
                    ["保留第二次验收反馈并结束当前 Coding Attempt，不得继续修改产物。"],
                    retryable=False,
                )
            if state.get("draftRendered") is not True:
                return _rejection(
                    "report_draft_not_rendered",
                    "报告尚未经过服务端结构化渲染，本次验收未执行。",
                    state,
                    ["调用 render_report_draft 生成服务端 Markdown 后再执行 verify。"],
                )
            if phase == "repair" and state.get("draftRepairApplied") is not True:
                return _rejection(
                    "report_repair_incomplete",
                    "结构化定点修复尚未完成，本次验收未执行。",
                    state,
                    self._remaining_actions(),
                )
            return None

        if phase not in {"rendered", "repair", "exhausted", "passed"}:
            return None
        if phase == "repair" and tool_name not in _POST_VERIFY_ALLOWED_TOOLS:
            return _rejection(
                "report_repair_tool_forbidden",
                "首次验收失败后只允许 issueId 定点修复、第二次验收和失败详情读取。",
                state,
                self._remaining_actions(),
            )
        if tool_name not in _WRITE_TOOLS:
            return None
        if phase in {"rendered", "exhausted", "passed"}:
            return _rejection(
                "report_repair_closed",
                "报告服务端渲染后写入窗口已经关闭，本次写操作未执行。",
                state,
                ["不得继续修改产物；渲染后只执行正式 verify，验收通过后提交任务。"],
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
        if tool_name != "repair_report_draft":
            return _rejection(
                "report_repair_tool_forbidden",
                "验收失败后只允许一次结构化草稿定点修复，本次工具未执行。",
                state,
                self._remaining_actions(),
            )
        if state.get("draftRepairApplied") is True:
            return _rejection(
                "report_repair_already_applied",
                "结构化草稿已经完成一次定点修复，拒绝重复修改。",
                state,
                ["只再执行一次正式 validator。"],
            )
        return self._repair_changes_rejection(arguments, state)

    @staticmethod
    def _repair_changes_rejection(
        arguments: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any] | None:
        changes = arguments.get("changes")
        covered: set[str] = set()
        invalid = not isinstance(changes, list) or not changes
        if isinstance(changes, list):
            for item in changes:
                if not isinstance(item, dict) or set(item) != {"issueId", "newText"}:
                    invalid = True
                    continue
                issue_id = item.get("issueId")
                new_text = item.get("newText")
                if (
                    not isinstance(issue_id, str)
                    or not issue_id
                    or not isinstance(new_text, str)
                    or not new_text
                    or issue_id in covered
                ):
                    invalid = True
                    continue
                covered.add(issue_id)
        required = set(state.get("requiredIssueIds", []))
        unresolved = sorted(required - covered)
        unexpected = sorted(covered - required)
        if invalid or unresolved or unexpected:
            return _rejection(
                "report_repair_changes_incomplete",
                "结构化修复必须一次覆盖 validator 列出的全部 issueId，未写入工作区。",
                state,
                ReportRepairGuard._remaining_actions(),
                extra_details={
                    "unresolvedIssueIds": unresolved,
                    **({"unknownIssueIds": unexpected} if unexpected else {}),
                },
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
        if tool_name == "repair_report_draft" and result.get("ok") is True:
            state["phase"] = "repair"
            state["draftRepairApplied"] = True
            markdown_sha256 = result.get("markdownSha256")
            if isinstance(markdown_sha256, str):
                state["markdownSha256"] = markdown_sha256
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

        details = [
            item["details"]
            for item in failed
            if isinstance(item, dict) and isinstance(item.get("details"), dict)
        ]
        repair_targets = {
            item["repairTarget"] for item in details if isinstance(item.get("repairTarget"), str)
        }
        required_issues: list[dict[str, Any]] = []
        for item in details:
            for issue in item.get("contradictoryPeriodClaims", []):
                if not isinstance(issue, dict) or not isinstance(issue.get("claim"), str):
                    continue
                normalized = dict(issue)
                issue_id = normalized.get("issueId")
                if not isinstance(issue_id, str) or not issue_id:
                    payload = json.dumps(
                        {
                            "claim": normalized["claim"],
                            "observedPeriods": normalized.get("observedPeriods", []),
                        },
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    issue_id = "period_claim_" + hashlib.sha256(payload.encode()).hexdigest()[:16]
                    normalized["issueId"] = issue_id
                required_issues.append(normalized)
        required_ids = [item["issueId"] for item in required_issues]
        duplicate_ids = len(required_ids) != len(set(required_ids))
        if duplicate_ids:
            required_issues = []
            required_ids = []
        state.update(
            {
                "phase": (
                    "exhausted" if state["verifyCount"] >= 2 or not required_issues else "repair"
                ),
                "failedRequirements": failed,
                "repairTarget": next(iter(repair_targets)) if len(repair_targets) == 1 else None,
                "requiredIssues": required_issues,
                "requiredIssueIds": sorted(required_ids),
                "draftRepairApplied": False,
            }
        )

    @staticmethod
    def _remaining_actions() -> list[str]:
        return ["调用一次 repair_report_draft，并在 changes 中覆盖全部 requiredIssueIds。"]
