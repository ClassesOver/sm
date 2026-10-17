from types import SimpleNamespace

import pytest

from smart_reporting.reporting.agent import _completed_report_content
from smart_reporting.reporting.workflow.controller import ReportWorkflowController
from smart_reporting.reporting_mcp.contracts import ReportingOperationResult


def _completed_payload(**overrides: object) -> dict[str, object]:
    return {
        "status": "completed",
        "report": {
            "reportId": "report-run-123",
            "reportTitle": "年度运营分析报告",
            "revision": 2,
            "pdf": {"downloadUrl": "https://reports.example/report.pdf"},
            "word": {"downloadUrl": "https://reports.example/report.docx"},
            "editor": {"openUrl": "https://reports.example/editor/report"},
            **overrides,
        },
    }


def test_completed_report_content_presents_delivery_actions_compactly() -> None:
    content = _completed_report_content(_completed_payload())

    assert content == (
        "## 报表已生成\n\n"
        "### 年度运营分析报告\n\n"
        "报告已完成发布。\n\n"
        "[编辑报告](https://reports.example/editor/report) · "
        "[下载 PDF](https://reports.example/report.pdf) · "
        "[下载 Word](https://reports.example/report.docx)"
    )


def test_completed_report_content_omits_invalid_delivery_urls() -> None:
    content = _completed_report_content(
        _completed_payload(
            editor={"openUrl": ""},
            word={"downloadUrl": "not-a-url"},
        )
    )

    assert content == (
        "## 报表已生成\n\n"
        "### 年度运营分析报告\n\n"
        "报告已完成发布。\n\n"
        "[下载 PDF](https://reports.example/report.pdf)"
    )


@pytest.mark.parametrize("template", [None, "# {report_title}\n\n{actions}", "{unknown}"])
def test_completed_report_content_discloses_failed_checks_with_download_links(template):
    content = _completed_report_content(_completed_payload(publicationGate={
        "formalReleaseAllowed": False,
        "issues": [
            {"code": "artifact_not_validated", "message": "PDF/Word 验收未通过。"},
            {"code": "artifact_not_validated", "message": "PDF/Word 验收未通过。"},
        ],
    }), template=template)
    assert "[下载 PDF](https://reports.example/report.pdf)" in content
    assert "[下载 Word](https://reports.example/report.docx)" in content
    assert "验收或发布检查未通过，下载链接已签发。" in content
    assert content.count("PDF/Word 验收未通过。") == 1


def test_completed_report_content_states_the_specific_validation_reasons():
    # AGENTS：验收失败仍签发下载，但须明确返回失败原因，不能只给笼统的“尚未完成验收”。
    content = _completed_report_content(_completed_payload(publicationGate={
        "formalReleaseAllowed": False,
        "issues": [{
            "code": "artifact_not_validated", "message": "Markdown、PDF 或 DOCX 尚未完成验收。",
            "details": {"validationIssues": [
                {"code": "page_layout_mismatch", "message": "PDF 与 Word 页数不一致。"},
                {"code": "font_missing"},
            ]},
        }],
    }), template=None)
    assert "[下载 PDF](https://reports.example/report.pdf)" in content
    assert "PDF 与 Word 页数不一致。" in content
    assert "font_missing" in content


@pytest.mark.parametrize("allowed", [False, True])
def test_controller_completion_preserves_gate_reasons_and_warnings(allowed):
    payload = _completed_payload(publicationGate={
        "formalReleaseAllowed": allowed,
        "issues": [] if allowed else [{
            "code": "artifact_not_validated", "message": "验收未通过。",
            "details": {"validationIssues": [{"message": "PDF 与 Word 页数不一致。"}]},
        }],
        "warnings": [{
            "code": "report_section_block_unverified_numbers", "message": "需核对。",
            "details": {"count": 2},
        }],
    })
    for kind in ("pdf", "word"):
        payload["report"][kind].update(
            path=f"报告.{kind}", expiresAt="2026-11-01T00:00:00Z", size=12, sha256="a" * 64,
        )
    payload["report"]["editor"]["expiresAt"] = "2026-11-01T00:00:00Z"
    result = ReportWorkflowController._result(
        SimpleNamespace(status="completed", review=None),
        SimpleNamespace(content=payload["report"]),
    )
    # The actual controller result must survive the MCP contract too.
    validated = ReportingOperationResult.model_validate({"operationId": "operation-1", **result})
    content = _completed_report_content(validated.model_dump(mode="json", by_alias=True))
    assert "[下载 PDF](https://reports.example/report.pdf)" in content
    assert "[下载 Word](https://reports.example/report.docx)" in content
    assert "2 处缺少登记依据的数值" in content
    assert ("PDF 与 Word 页数不一致。" in content) is (not allowed)
    assert ("验收或发布检查未通过" in content) is (not allowed)


def test_completed_report_content_discloses_residual_content_review_as_soft_notice():
    # 纠错后仍残留的复核告警与“待核实”替换不阻断发布，但须告知用户；只给结论句，不给模型纠正指引。
    review = {"code": "report_section_block_content_review",
              "message": "指标数值归属需复核：门诊收入名下的2.26%是住院收入的登记值。请改用门诊收入对应的数值引用，或改写主语。"}
    content = _completed_report_content(_completed_payload(publicationGate={
        "formalReleaseAllowed": True, "issues": [],
        "warnings": [
            review, review,
            {"code": "report_section_block_unverified_numbers", "message": "2 处……", "details": {"count": 2}},
            {"code": "report_section_block_unverified_numbers", "message": "1 处……", "details": {"count": 1}},
            {"code": "unused_chart_excluded", "message": "未被正文引用的图表已从发布包排除。"},
        ],
    }), template=None)
    assert content.endswith(
        "正文复核提示（不影响下载，建议在编辑器中核对）：3 处缺少登记依据的数值已标注为“待核实”；"
        "1 条正文复核提示未能自动修正，如：指标数值归属需复核：门诊收入名下的2.26%是住院收入的登记值。"
    )
    assert "验收或发布检查未通过" not in content and "请改用" not in content
    assert "[下载 PDF](https://reports.example/report.pdf)" in content


def test_completed_report_content_uses_custom_template() -> None:
    content = _completed_report_content(
        _completed_payload(),
        template="# {report_title}\n\n{actions}\n\n---\n生成完毕",
    )

    assert content == (
        "# 年度运营分析报告\n\n"
        "[编辑报告](https://reports.example/editor/report) · "
        "[下载 PDF](https://reports.example/report.pdf) · "
        "[下载 Word](https://reports.example/report.docx)\n\n"
        "---\n生成完毕"
    )


def test_completed_report_content_falls_back_on_bad_template() -> None:
    content = _completed_report_content(
        _completed_payload(),
        template="# {unknown_variable}\n\n{actions}",
    )

    assert content == (
        "## 报表已生成\n\n"
        "### 年度运营分析报告\n\n"
        "报告已完成发布。\n\n"
        "[编辑报告](https://reports.example/editor/report) · "
        "[下载 PDF](https://reports.example/report.pdf) · "
        "[下载 Word](https://reports.example/report.docx)"
    )


@pytest.mark.parametrize("template", ["# {0}", "# {report_title.missing}", "# {report_title[key]}"])
def test_completed_report_content_falls_back_on_positional_or_attribute_template(
    template: str,
) -> None:
    content = _completed_report_content(_completed_payload(), template=template)

    assert content is not None
    assert content.startswith("## 报表已生成\n\n### 年度运营分析报告")


def test_completed_report_content_uses_report_id_when_title_missing() -> None:
    content = _completed_report_content(
        _completed_payload(reportTitle=""),
    )

    assert "### report-run-123" in content
    assert "年度运营分析报告" not in content
