from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from smart_reporting.reporting.delivery.report_runtime import (
    _WORD_PAGE_FIELDS,
    DEFAULT_PAGE_LAYOUT,
    _normalize_cjk_strong_markers,
    _page_number_context,
    _postprocess_docx,
    normalize_report_markdown_strong_spacing,
)


def test_normalize_cjk_strong_markers_supports_chinese_punctuation() -> None:
    from markdown_it import MarkdownIt

    markdown = "呈**“年初低位—3月跳升”**形态"

    normalized = _normalize_cjk_strong_markers(markdown)
    rendered = MarkdownIt("commonmark", {"html": False}).render(normalized)

    assert normalized == "呈 **“年初低位—3月跳升”** 形态"
    assert "<strong>“年初低位—3月跳升”</strong>" in rendered
    assert "**" not in rendered


def test_normalize_cjk_strong_markers_preserves_unmatched_stars() -> None:
    markdown = "数量增长 * 2，备注 **未闭合"

    assert _normalize_cjk_strong_markers(markdown) == markdown


def test_normalize_spaced_strong_markers_renders_budget_values() -> None:
    from markdown_it import MarkdownIt

    markdown = "预算为 ** 131.73 亿元 **，执行率 ** 95.14% **。"

    normalized = _normalize_cjk_strong_markers(markdown)
    rendered = MarkdownIt("commonmark", {"html": False}).render(normalized)

    assert normalized == "预算为 **131.73 亿元**，执行率 **95.14%**。"
    assert "<strong>131.73 亿元</strong>" in rendered
    assert "<strong>95.14%</strong>" in rendered
    assert "**" not in rendered


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("由** 总部院区**、", "由**总部院区**、"),
        ("由**总部院区 **、", "由**总部院区**、"),
        ("由** 总部院区 **、", "由**总部院区**、"),
        ("由**总部院区**、", "由**总部院区**、"),
        ("** 总部院区**", "**总部院区**"),
    ],
)
def test_normalize_spaced_chinese_strong_markers(source: str, expected: str) -> None:
    from markdown_it import MarkdownIt

    normalized = normalize_report_markdown_strong_spacing(source)
    rendered = MarkdownIt("commonmark", {"html": False}).render(normalized)

    assert normalized == expected
    assert "<strong>总部院区</strong>" in rendered
    assert "**" not in rendered


@pytest.mark.parametrize(
    "markdown",
    [
        "说明 `由** 总部院区**、`。",
        "```markdown\n** 总部院区**\n```",
        "~~~~\n** 总部院区**\n~~~~",
        "    ** 总部院区**",
    ],
)
def test_normalize_strong_markers_does_not_change_code(markdown: str) -> None:
    assert normalize_report_markdown_strong_spacing(markdown) == markdown
    assert _normalize_cjk_strong_markers(markdown) == markdown


def test_normalize_strong_markers_preserves_math_stars() -> None:
    markdown = "幂运算 2 ** 3，未格式化 ** 2 **。"

    assert _normalize_cjk_strong_markers(markdown) == markdown


@pytest.mark.parametrize(
    ("physical_page", "body_start_page", "physical_page_count", "expected"),
    [
        (2, 3, 25, ("i", "i")),
        (2, 4, 25, ("i", "ii")),
        (3, 4, 25, ("ii", "ii")),
        (3, 3, 25, (1, 23)),
        (25, 3, 25, (23, 23)),
    ],
)
def test_page_number_context_uses_section_page_count(
    physical_page: int,
    body_start_page: int,
    physical_page_count: int,
    expected: tuple[str | int, str | int],
) -> None:
    assert (
        _page_number_context(
            physical_page,
            body_start_page=body_start_page,
            physical_page_count=physical_page_count,
        )
        == expected
    )


def test_postprocess_docx_uses_section_page_count_field(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")

    path = tmp_path / "report.docx"
    document = docx.Document()
    for text in (
        "测试报告",
        "__REPORT_COVER_END__",
        "目录",
        "__REPORT_TOC_FIELD_START__",
        "经营概览",
        "__REPORT_TOC_FIELD_END__",
        "__REPORT_TOC_END__",
        "__REPORT_BODY_START__",
        "经营概览",
        "测试机构",
        "2026-08-17",
    ):
        document.add_paragraph(text)
    document.save(path)

    _postprocess_docx(
        path,
        context={
            "title": "测试报告",
            "periodLabel": "2025 年",
            "organizationName": "测试机构",
            "generatedByLabel": "Reporting Agent",
            "watermarkText": "内部资料",
            "generatedDate": "2026-08-17",
            "sections": [{"code": "overview", "title": "经营概览"}],
        },
        layout=DEFAULT_PAGE_LAYOUT,
    )

    with zipfile.ZipFile(path) as package:
        footer_xml = "\n".join(
            package.read(name).decode("utf-8")
            for name in package.namelist()
            if name.startswith("word/footer") and name.endswith(".xml")
        )

    assert "SECTIONPAGES" in footer_xml
    assert "NUMPAGES" not in footer_xml


def test_word_page_fields_use_section_page_count() -> None:
    assert _WORD_PAGE_FIELDS == {"page": "PAGE", "pages": "SECTIONPAGES"}
