from __future__ import annotations

import pytest
from markdown_it import MarkdownIt

from smart_reporting.reporting.delivery.draft_v1 import ReportChartInput, _chart_figure_markdown
from smart_reporting.reporting.tools.base import _decode_utf8_page
from smart_reporting.reporting.workflow.runtime.phase_models import SectionBlockContent
from smart_reporting.workspace import WorkspaceError


def test_chart_figure_survives_quotes_and_emphasis_in_title() -> None:
    chart = ReportChartInput(
        chartId="chart_001",
        fileName="chart.png",
        title='门诊"收入"*增长*率',
        altText="收入[门诊]\n趋势",
        citationIds=("citation_001",),
    )

    html = MarkdownIt("commonmark").render(_chart_figure_markdown(chart, "chart.png"))

    assert (
        '<img src="chart.png" alt="收入［门诊］ 趋势" title="门诊&quot;收入&quot;*增长*率" />'
        in html
    )
    assert "<em>图表：门诊&quot;收入&quot;*增长*率</em>" in html


@pytest.mark.parametrize(
    ("markdown", "expected"),
    [
        ("结论如下\n---\n下一段", "结论如下\n\n---\n下一段"),
        ("第一行\n===\n尾", "第一行\n尾"),
        ("- 项目\n---", "- 项目\n---"),
    ],
)
def test_block_markdown_setext_underline_is_not_a_heading(markdown: str, expected: str) -> None:
    assert SectionBlockContent(markdown=markdown).markdown == expected


def test_decode_page_trims_only_truncated_tail_character() -> None:
    content = "收入abc".encode()

    assert _decode_utf8_page(content, offset=0, end=4) == "收"
    assert _decode_utf8_page(content, offset=3, end=len(content)) == "入abc"


def test_decode_page_rejects_binary_and_misaligned_offset() -> None:
    with pytest.raises(WorkspaceError, match="只能读取 UTF-8 文本"):
        _decode_utf8_page(b"\x89PNG\r\n\x1a\n" + b"\xff" * 64, offset=0, end=72)
    with pytest.raises(WorkspaceError, match="字符边界"):
        _decode_utf8_page("收入".encode(), offset=1, end=6)
