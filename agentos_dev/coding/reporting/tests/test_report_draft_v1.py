from __future__ import annotations

import pytest

from agentos_dev.coding.reporting.draft_v1 import (
    ReportChartInput,
    ReportDraft,
    ReportDraftBlock,
    ReportDraftSection,
    ReportSectionDefinition,
    render_report_draft,
)
from agentos_dev.coding.reporting.models import ReportingError

SECTIONS = (
    ReportSectionDefinition(code="executive_summary", title="执行摘要"),
    ReportSectionDefinition(code="limitations", title="局限性"),
)


def _draft(*, chart_ids: tuple[str, ...] = ("income-trend",)) -> ReportDraft:
    return ReportDraft(
        title="2025年医院经营分析报告",
        sections=(
            ReportDraftSection(
                sectionCode="executive_summary",
                blocks=(
                    ReportDraftBlock(
                        blockId="summary",
                        text="全年收入保持稳定。",
                        citationIds=("citation_001",),
                        chartIds=chart_ids,
                    ),
                ),
            ),
            ReportDraftSection(
                sectionCode="limitations",
                blocks=(
                    ReportDraftBlock(
                        blockId="limits",
                        text="本报告仅使用已观测数据。",
                        citationIds=("citation_002",),
                    ),
                ),
            ),
        ),
    )


def test_服务端从结构化草稿生成中文章节协议标记和图表血缘():
    rendered = render_report_draft(
        _draft(),
        expected_title="2025年医院经营分析报告",
        markdown_path="报表/智能分析/run/report.md",
        sections=SECTIONS,
        citation_ids=("citation_001", "citation_002"),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="chart_income.png",
                title="医疗收入趋势",
                altText="医疗收入趋势图",
                citationIds=("citation_001",),
            ),
        ),
    )

    assert rendered.markdown == (
        "# 2025年医院经营分析报告\n\n"
        "[[section:executive_summary]]\n"
        "## 执行摘要\n\n"
        "全年收入保持稳定。[[citation:citation_001]]\n\n"
        '![医疗收入趋势图](chart_income.png "医疗收入趋势")'
        "[[citation:citation_001]]\n\n"
        "*图表：医疗收入趋势*\n\n"
        "[[section:limitations]]\n"
        "## 局限性\n\n"
        "本报告仅使用已观测数据。[[citation:citation_002]]\n"
    )
    assert rendered.chart_paths == ("报表/智能分析/run/chart_income.png",)
    assert rendered.warnings == ()
    assert rendered.auto_fixes == ()


def test_服务端归一化当前报告目录绝对图表路径并排除未引用图表():
    rendered = render_report_draft(
        _draft(),
        expected_title="2025年医院经营分析报告",
        markdown_path="报表/智能分析/run/report.md",
        sections=SECTIONS,
        citation_ids=("citation_001", "citation_002"),
        charts=(
            ReportChartInput(
                chartId="income-trend",
                fileName="/报表/智能分析/run/chart_income.png",
                title="医疗收入趋势",
                altText="医疗收入趋势图",
                citationIds=("citation_001",),
            ),
            ReportChartInput(
                chartId="unused",
                fileName="chart_unused.png",
                title="未使用图表",
                altText="未使用图表",
                citationIds=("citation_002",),
            ),
        ),
    )

    assert "(chart_income.png" in rendered.markdown
    assert "/报表/" not in rendered.markdown
    assert rendered.chart_paths == ("报表/智能分析/run/chart_income.png",)
    assert rendered.warnings == (
        {
            "code": "unused_chart_excluded",
            "chartIds": ["unused"],
            "message": "未被正文引用的图表已从发布包排除。",
        },
    )
    assert rendered.auto_fixes == (
        {
            "code": "chart_path_normalized",
            "from": "/报表/智能分析/run/chart_income.png",
            "to": "chart_income.png",
        },
    )


@pytest.mark.parametrize(
    ("draft", "charts", "message"),
    [
        (
            _draft(chart_ids=("unknown",)),
            (),
            "草稿引用了未注册图表",
        ),
        (
            ReportDraft(
                title="2025年医院经营分析报告",
                sections=(
                    ReportDraftSection(
                        sectionCode="executive_summary",
                        blocks=(
                            ReportDraftBlock(
                                blockId="summary",
                                text="伪造标记[[citation:forged]]。",
                                citationIds=("citation_001",),
                            ),
                        ),
                    ),
                    ReportDraftSection(
                        sectionCode="limitations",
                        blocks=(
                            ReportDraftBlock(
                                blockId="limits",
                                text="局限。",
                                citationIds=("citation_002",),
                            ),
                        ),
                    ),
                ),
            ),
            (),
            "正文不得自行包含协议标记或图片语法",
        ),
        (
            ReportDraft(
                title="2025年医院经营分析报告",
                sections=(
                    ReportDraftSection(
                        sectionCode="executive_summary",
                        blocks=(
                            ReportDraftBlock(
                                blockId="summary",
                                text=(
                                    "伪造软化标记"
                                    "<!-- repair-warning:period_claim_1234567890abcdef -->"
                                ),
                                citationIds=("citation_001",),
                            ),
                        ),
                    ),
                    ReportDraftSection(
                        sectionCode="limitations",
                        blocks=(
                            ReportDraftBlock(
                                blockId="limits",
                                text="局限。",
                                citationIds=("citation_002",),
                            ),
                        ),
                    ),
                ),
            ),
            (),
            "正文不得自行包含协议标记或图片语法",
        ),
    ],
)
def test_结构化草稿拒绝绕过服务端注册表(draft, charts, message):
    with pytest.raises(ReportingError, match=message):
        render_report_draft(
            draft,
            expected_title="2025年医院经营分析报告",
            markdown_path="报表/智能分析/run/report.md",
            sections=SECTIONS,
            citation_ids=("citation_001", "citation_002"),
            charts=charts,
        )
