from agentos_dev.coding.reporting.repair_guard import ReportRepairGuard

VALIDATOR_ID = "report-artifact:manifest"
MARKDOWN_PATH = "报表/智能分析/report/run/report.md"
MANIFEST_PATH = "报表/智能分析/report/run/report.manifest.json"


def _failure(*, repair_target=MARKDOWN_PATH):
    details = {
        "contradictoryPeriodClaims": [
            {
                "issueId": "period_claim_workload",
                "claim": "工作量11月无记录。",
                "observedPeriods": ["2025-11"],
            }
        ],
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
        "artifact_paths": [MARKDOWN_PATH],
    }


def _draft_repair():
    return {
        "changes": [
            {
                "issueId": "period_claim_workload",
                "newText": "工作量11月观测值为零。",
            }
        ]
    }


def _rendered_state():
    state = {}
    ReportRepairGuard().record_draft_rendered(
        state,
        markdown_path=MARKDOWN_PATH,
        markdown_sha256="a" * 64,
    )
    return state


def test_report修复门禁拒绝通用文件工具并要求结构化修复():
    guard = ReportRepairGuard()
    state = _rendered_state()
    guard.record_result("verify", _verify_arguments(), _failure(), state)

    markdown_rejection = guard.admission_rejection("replace_text", {"path": MARKDOWN_PATH}, state)
    manifest_rejection = guard.admission_rejection("overwrite_file", {"path": MANIFEST_PATH}, state)

    assert markdown_rejection["code"] == "report_repair_tool_forbidden"
    assert manifest_rejection["code"] == "report_repair_tool_forbidden"
    assert markdown_rejection["details"]["repairTarget"] == MARKDOWN_PATH
    assert markdown_rejection["requiredActions"] == [
        "调用一次 repair_report_draft，并在 changes 中覆盖全部 requiredIssueIds。"
    ]


def test_report修复门禁只允许一次结构化草稿修复且禁止patch():
    guard = ReportRepairGuard()
    state = _rendered_state()
    guard.record_result("verify", _verify_arguments(), _failure(), state)

    assert guard.admission_rejection("repair_report_draft", _draft_repair(), state) is None
    guard.record_result("repair_report_draft", _draft_repair(), {"ok": True}, state)
    repeated = guard.admission_rejection("repair_report_draft", _draft_repair(), state)
    assert repeated["code"] == "report_repair_already_applied"

    patch_rejection = guard.admission_rejection("apply_patch", {"patch": "x"}, state)
    assert patch_rejection["code"] == "report_repair_tool_forbidden"


def test_report修复门禁要求完成定点修改并拒绝第三次verify():
    guard = ReportRepairGuard()
    state = _rendered_state()
    arguments = _verify_arguments()
    guard.record_result("verify", arguments, _failure(), state)

    premature = guard.admission_rejection("verify", arguments, state)
    assert premature["code"] == "report_repair_incomplete"

    guard.record_result("repair_report_draft", _draft_repair(), {"ok": True}, state)
    assert guard.admission_rejection("verify", arguments, state) is None
    guard.record_result("verify", arguments, _failure(), state)

    third = guard.admission_rejection("verify", arguments, state)
    assert third["code"] == "report_verify_limit_reached"
    assert third["retryable"] is False


def test_report修复门禁没有明确目标时拒绝写入():
    guard = ReportRepairGuard()
    state = _rendered_state()
    guard.record_result("verify", _verify_arguments(), _failure(repair_target=None), state)

    rejection = guard.admission_rejection("repair_report_draft", _draft_repair(), state)

    assert rejection["code"] == "report_repair_target_missing"
    assert rejection["retryable"] is False


def test_report修复门禁在落盘前反馈结构化修复尚未覆盖的全部失败项():
    guard = ReportRepairGuard()
    state = _rendered_state()
    failure = _failure()
    failure["failedRequirements"][0]["details"]["contradictoryPeriodClaims"].append(
        {
            "issueId": "period_claim_income",
            "claim": "收入12月无记录。",
            "observedPeriods": ["2025-12"],
        }
    )
    guard.record_result("verify", _verify_arguments(), failure, state)

    rejection = guard.admission_rejection("repair_report_draft", _draft_repair(), state)

    assert rejection["code"] == "report_repair_changes_incomplete"
    assert rejection["details"]["unresolvedIssueIds"] == ["period_claim_income"]
    assert state["agentos_reporting_repair_guard"]["draftRepairApplied"] is False


def test_report首次verify前必须经过服务端结构化渲染():
    guard = ReportRepairGuard()
    state = {}

    rejection = guard.admission_rejection("verify", _verify_arguments(), state)

    assert rejection["code"] == "report_draft_not_rendered"
    assert rejection["retryable"] is True
    assert rejection["requiredActions"] == [
        "调用 render_report_draft 生成服务端 Markdown 后再执行 verify。"
    ]


def test_report服务端渲染后拒绝通用工具篡改markdown():
    guard = ReportRepairGuard()
    state = _rendered_state()

    rejection = guard.admission_rejection(
        "overwrite_file",
        {"path": MARKDOWN_PATH, "content": "伪造内容", "expected_sha256": "a" * 64},
        state,
    )

    assert rejection["code"] == "report_repair_closed"
    assert rejection["retryable"] is False


def test_report修复门禁拒绝未知遗漏和重复issue_id():
    guard = ReportRepairGuard()
    state = _rendered_state()
    guard.record_result("verify", _verify_arguments(), _failure(), state)

    unknown = guard.admission_rejection(
        "repair_report_draft",
        {"changes": [{"issueId": "unknown", "newText": "有效观测。"}]},
        state,
    )
    duplicate = guard.admission_rejection(
        "repair_report_draft",
        {
            "changes": [
                {"issueId": "period_claim_workload", "newText": "有效观测。"},
                {"issueId": "period_claim_workload", "newText": "仍为有效观测。"},
            ]
        },
        state,
    )

    assert unknown["details"]["unresolvedIssueIds"] == ["period_claim_workload"]
    assert unknown["details"]["unknownIssueIds"] == ["unknown"]
    assert duplicate["code"] == "report_repair_changes_incomplete"
