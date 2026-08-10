from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentos_dev.coding.reporting.delivery.draft_v1 import (
    ReportChartInput,
    ReportDraft,
    ReportSectionDefinition,
    assemble_report_markdown,
)


def _draft() -> ReportDraft:
    return ReportDraft.model_validate(
        {
            "title": "运营报告",
            "sections": [
                {
                    "sectionCode": "income",
                    "blocks": [
                        {
                            "blockId": "income-summary",
                            "markdown": (
                                "### 核心结论\n\n医疗收入为100万元。\n\n"
                                "| 项目 | 本期值 |\n| --- | --- |\n| 医疗收入 | 100万元 |"
                            ),
                            "citationIds": ["citation_001"],
                            "analysisIds": ["analysis_001"],
                            "chartIds": ["income-trend"],
                        }
                    ],
                }
            ],
        }
    )


def test_dataset协议渲染正文表格图表和analysis引用() -> None:
    rendered = assemble_report_markdown(
        _draft(),
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(
            ReportSectionDefinition(code="income", title="收入分析", analysisIds=("analysis_001",)),
        ),
        citation_ids=("citation_001",),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="income.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001",),
            ),
        ),
        require_table=True,
    )

    assert "| 医疗收入 | 100万元 |" in rendered.markdown
    assert "[[citation:citation_001]]" in rendered.markdown
    assert "[[analysis:analysis_001]]" in rendered.markdown
    assert rendered.chart_paths == ("reports/income.png",)


@pytest.mark.parametrize("field", ["factIds", "seriesId"])
def test_dataset协议拒绝旧Fact字段(field: str) -> None:
    payload = {
        "chartId": "income-trend",
        "fileName": "income.png",
        "title": "收入趋势",
        "altText": "收入趋势图",
        "citationIds": ["citation_001"],
        field: ["fact-1"] if field == "factIds" else "series-" + "1" * 24,
    }
    with pytest.raises(ValidationError):
        ReportChartInput.model_validate(payload)


def test草稿analysisId不执行提纲覆盖校验() -> None:
    rendered = assemble_report_markdown(
        _draft(),
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(
            ReportSectionDefinition(code="income", title="收入分析", analysisIds=("analysis_002",)),
        ),
        citation_ids=("citation_001",),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="income.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001",),
            ),
        ),
    )

    assert rendered.analysis_ids == ("analysis_001",)


def test草稿可省略标题并归一化重复引用() -> None:
    payload = _draft().model_dump(mode="json", by_alias=True)
    payload.pop("title")
    block = payload["sections"][0]["blocks"][0]
    block["citationIds"] = ["citation_001", "citation_001"]
    block["analysisIds"] = ["analysis_001", "analysis_001"]
    block["chartIds"] = ["income-trend", "income-trend"]
    draft = ReportDraft.model_validate(payload)

    rendered = assemble_report_markdown(
        draft,
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(
            ReportSectionDefinition(code="income", title="收入分析", analysisIds=("analysis_001",)),
        ),
        citation_ids=("citation_001",),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="income.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001", "citation_001"),
            ),
        ),
    )

    assert rendered.markdown.startswith("# 运营报告")
    assert "### 核心结论" in rendered.markdown
    assert rendered.markdown.count("![收入趋势图]") == 1


def test组装草稿移除正文首个重复章节标题() -> None:
    payload = _draft().model_dump(mode="json", by_alias=True)
    payload["sections"][0]["blocks"][0]["markdown"] = (
        "## 收入趋势与主要贡献对象\n\n### 管理结论\n\n医疗收入保持增长。"
    )

    rendered = assemble_report_markdown(
        ReportDraft.model_validate(payload),
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(ReportSectionDefinition(code="income", title="收入趋势与主要贡献对象"),),
        citation_ids=("citation_001",),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="income.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001",),
            ),
        ),
    )

    assert rendered.markdown.count("## 收入趋势与主要贡献对象") == 1
    assert "### 管理结论" in rendered.markdown
    assert rendered.auto_fixes == (
        {
            "code": "duplicate_section_heading_removed",
            "sectionCode": "income",
            "blockId": "income-summary",
            "title": "收入趋势与主要贡献对象",
        },
    )


def test组装草稿保留不同的二级标题() -> None:
    payload = _draft().model_dump(mode="json", by_alias=True)
    payload["sections"][0]["blocks"][0]["markdown"] = "## 收入结构\n\n医疗收入保持增长。"

    rendered = assemble_report_markdown(
        ReportDraft.model_validate(payload),
        expected_title="运营报告",
        markdown_path="reports/report.md",
        sections=(ReportSectionDefinition(code="income", title="收入趋势与主要贡献对象"),),
        citation_ids=("citation_001",),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="income.png",
                title="收入趋势",
                altText="收入趋势图",
                citationIds=("citation_001",),
            ),
        ),
    )

    assert "## 收入结构" in rendered.markdown
    assert rendered.auto_fixes == ()
