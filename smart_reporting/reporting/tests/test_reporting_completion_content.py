from smart_reporting.reporting.agent import _completed_report_content


def test_completed_report_content_presents_delivery_actions_compactly() -> None:
    content = _completed_report_content(
        {
            "status": "completed",
            "report": {
                "reportId": "report-run-123",
                "reportTitle": "年度运营分析报告",
                "revision": 2,
                "pdf": {"downloadUrl": "https://reports.example/report.pdf"},
                "word": {"downloadUrl": "https://reports.example/report.docx"},
                "html": {"previewUrl": "https://reports.example/report.html"},
            },
        }
    )

    assert content == (
        "## 报表已生成\n\n"
        "### 年度运营分析报告\n\n"
        "报告已完成发布。\n\n"
        "[**在线预览**](https://reports.example/report.html) · "
        "[下载 PDF](https://reports.example/report.pdf) · "
        "[下载 Word](https://reports.example/report.docx)"
    )
