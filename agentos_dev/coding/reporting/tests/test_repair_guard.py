from agentos_dev.coding.reporting.repair_guard import ReportRepairGuard

VALIDATOR_ID = "report-artifact:manifest"
MARKDOWN_PATH = "报表/智能分析/report/run/report.md"
MANIFEST_PATH = "报表/智能分析/report/run/report.manifest.json"


def _failure(*, repair_target=MARKDOWN_PATH):
    details = {
        "missingCitationMarkers": ["[[citation:income_1]]"],
        "authorizedManifestMutationPaths": ["markdown.size", "markdown.sha256"],
    }
    if repair_target is not None:
        details["repairTarget"] = repair_target
    return {
        "code": "verification_acceptance_failed",
        "failedRequirements": [
            {
                "id": "report-artifact",
                "message": "报告 Markdown 缺少协议标记，请只修复 Markdown。",
                "details": details,
            }
        ],
    }


def _verify_arguments():
    return {
        "validator_id": VALIDATOR_ID,
        "artifact_paths": [MARKDOWN_PATH, MANIFEST_PATH],
    }


def _markdown_patch():
    return {
        "patch": (
            "*** Begin Patch\n"
            f"*** Update File: {MARKDOWN_PATH}\n"
            "@@\n"
            "-收入结论。\n"
            "+收入结论。[[citation:income_1]]\n"
            "*** End Patch"
        )
    }


def _manifest_patch():
    return {
        "patch": (
            "*** Begin Patch\n"
            f"*** Update File: {MANIFEST_PATH}\n"
            "@@\n"
            '-    "size": 100,\n'
            '-    "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
            '+    "size": 126,\n'
            '+    "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"\n'
            "*** End Patch"
        )
    }


def test_report修复门禁拒绝markdown散改和manifest整份覆盖():
    guard = ReportRepairGuard()
    state = {}
    guard.record_result("verify", _verify_arguments(), _failure(), state)

    markdown_rejection = guard.admission_rejection("replace_text", {"path": MARKDOWN_PATH}, state)
    manifest_rejection = guard.admission_rejection("overwrite_file", {"path": MANIFEST_PATH}, state)

    assert markdown_rejection["code"] == "report_repair_tool_forbidden"
    assert manifest_rejection["code"] == "report_repair_tool_forbidden"
    assert markdown_rejection["details"]["repairTarget"] == MARKDOWN_PATH


def test_report修复门禁只允许一次markdown补丁和一次manifest元数据补丁():
    guard = ReportRepairGuard()
    state = {}
    guard.record_result("verify", _verify_arguments(), _failure(), state)

    assert guard.admission_rejection("apply_patch", _markdown_patch(), state) is None
    guard.record_result("apply_patch", _markdown_patch(), {"ok": True}, state)
    repeated = guard.admission_rejection("apply_patch", _markdown_patch(), state)
    assert repeated["code"] == "report_repair_already_applied"

    assert guard.admission_rejection("apply_patch", _manifest_patch(), state) is None
    guard.record_result("apply_patch", _manifest_patch(), {"ok": True}, state)
    repeated_manifest = guard.admission_rejection("apply_patch", _manifest_patch(), state)
    assert repeated_manifest["code"] == "report_repair_already_applied"


def test_report修复门禁要求完成定点修改并拒绝第三次verify():
    guard = ReportRepairGuard()
    state = {}
    arguments = _verify_arguments()
    guard.record_result("verify", arguments, _failure(), state)

    premature = guard.admission_rejection("verify", arguments, state)
    assert premature["code"] == "report_repair_incomplete"

    guard.record_result("apply_patch", _markdown_patch(), {"ok": True}, state)
    guard.record_result("apply_patch", _manifest_patch(), {"ok": True}, state)
    assert guard.admission_rejection("verify", arguments, state) is None
    guard.record_result("verify", arguments, _failure(), state)

    third = guard.admission_rejection("verify", arguments, state)
    assert third["code"] == "report_verify_limit_reached"
    assert third["retryable"] is False


def test_report修复门禁没有明确目标时拒绝写入():
    guard = ReportRepairGuard()
    state = {}
    guard.record_result("verify", _verify_arguments(), _failure(repair_target=None), state)

    rejection = guard.admission_rejection("apply_patch", _markdown_patch(), state)

    assert rejection["code"] == "report_repair_target_missing"
    assert rejection["retryable"] is False


def test_report修复门禁在落盘前反馈补丁尚未覆盖的全部失败项():
    guard = ReportRepairGuard()
    state = {}
    failure = _failure()
    failure["failedRequirements"][0]["details"]["missingSectionMarkers"] = [
        "[[section:executive_summary]]"
    ]
    guard.record_result("verify", _verify_arguments(), failure, state)

    rejection = guard.admission_rejection("apply_patch", _markdown_patch(), state)

    assert rejection["code"] == "report_repair_patch_incomplete"
    assert rejection["details"]["unresolvedFeedback"] == ["[[section:executive_summary]]"]
    assert state["agentos_reporting_repair_guard"]["markdownPatchApplied"] is False
