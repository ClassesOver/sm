import pytest

from smart_reporting.reporting.agent import _completed_report_content


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
