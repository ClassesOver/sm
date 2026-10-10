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

    # 中文语境的半角引号按正文规则改为中文引号；强调符号不破坏图片与图注。
    assert '<img src="chart.png" alt="收入［门诊］ 趋势" title="门诊“收入”*增长*率" />' in html
    assert "<em>图表：门诊“收入”*增长*率</em>" in html

    # 英文标题保留半角引号，图片标题与图注中按 HTML 转义。
    english = chart.model_copy(update={"title": 'Revenue "A" *growth*'})
    html = MarkdownIt("commonmark").render(_chart_figure_markdown(english, "chart.png"))
    assert 'title="Revenue &quot;A&quot; *growth*"' in html
    assert "<em>图表：Revenue &quot;A&quot; *growth*</em>" in html


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


@pytest.mark.parametrize("file_name", ["收入 趋势.png", "收入(2025.png", "a%20b.png", "plain.png"])
def test_chart_figure_destination_survives_unsafe_file_names(file_name: str) -> None:
    from urllib.parse import unquote

    from markdown_it import MarkdownIt

    from smart_reporting.reporting.delivery.draft_v1 import ReportChartInput, _chart_figure_markdown

    chart = ReportChartInput(
        chartId="chart_001",
        fileName=file_name,
        title="收入趋势",
        altText="收入趋势",
        citationIds=("cite_1",),
    )
    tokens = MarkdownIt("commonmark").parse(_chart_figure_markdown(chart, file_name))
    images = [child for token in tokens for child in token.children or () if child.type == "image"]

    assert len(images) == 1
    assert unquote(str(images[0].attrGet("src"))) == file_name


@pytest.mark.parametrize(("title", "alt", "expected_title", "expected_alt"), [
    # 去掉内部 ID 后汉字间的空格按正文规则一并去掉。
    ("门诊收入趋势（analysis_001）", "门诊收入 · citation_002 月度趋势", "门诊收入趋势", "门诊收入月度趋势"),
    ("收入构成 fact-" + "a" * 16, "收入构成[analysis_003]", "收入构成", "收入构成"),
    ("analysis_001", "chart_001", "图表", "图表"),
    ("2025年门诊收入趋势", "按月收入", "2025年门诊收入趋势", "按月收入"),
])
def test_chart_labels_drop_internal_ids(title, alt, expected_title, expected_alt) -> None:
    # 图题与替代文本读者可见；内部 ID 只应留在结构化引用字段中。
    chart = ReportChartInput(chartId="chart_001", fileName="chart.png", title=title,
                             altText=alt, citationIds=("citation_001",))
    html = MarkdownIt("commonmark").render(_chart_figure_markdown(chart, "chart.png"))
    assert f'alt="{expected_alt}"' in html
    assert f"<em>图表：{expected_title}</em>" in html
