"""Reporting PDF 渲染、页码和视觉验收能力。"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from string import Formatter
from typing import Any

from .markdown import REPORT_VISUAL_THEME
from .validation import MAX_PDF_BYTES, ReportFailure

MAX_PDF_PAGES = 200
DEFAULT_PAGE_LAYOUT = {
    "headerLeft": "{organization}",
    "headerRight": "{title}",
    "footerLeft": "企业智能运营报表",
    "footerRight": "第 {page} / {pages} 页",
}
PAGE_LAYOUT_FIELDS = frozenset(DEFAULT_PAGE_LAYOUT)
PAGE_LAYOUT_PLACEHOLDERS = frozenset({"title", "organization", "page", "pages"})
_CITATION_MARKER = re.compile(r"\[\[citation:([^\]\r\n]+)\]\]")
_SECTION_MARKER = re.compile(r"\[\[section:([^\]\r\n]+)\]\]")
_ANALYSIS_MARKER = re.compile(r"\[\[analysis:([^\]\r\n]+)\]\]")
_TABLE_MARKER = re.compile(r"\[\[/?table:[^\]\r\n]+\]\]")


def _pdf_markdown(markdown: str, presentations: Any) -> tuple[str, list[dict[str, Any]]]:
    marker_ids = tuple(dict.fromkeys(_CITATION_MARKER.findall(markdown)))
    if not marker_ids:
        visible_markdown = _ANALYSIS_MARKER.sub("", _SECTION_MARKER.sub("", markdown))
        return _TABLE_MARKER.sub("", visible_markdown), []
    if not isinstance(presentations, list):
        raise ReportFailure("PDF 缺少服务端实际引用展示信息")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(presentations, start=1):
        if not isinstance(item, dict) or set(item) != {"citationId", "label", "coverageItems"}:
            raise ReportFailure("PDF 实际引用展示信息无效")
        citation_id = item.get("citationId")
        label = item.get("label")
        coverage_items = item.get("coverageItems")
        if (
            not isinstance(citation_id, str)
            or not citation_id
            or not isinstance(label, str)
            or not 1 <= len(label) <= 200
            or not isinstance(coverage_items, list)
            or len(coverage_items) > 100
        ):
            raise ReportFailure("PDF 实际引用展示信息与 Markdown 顺序不一致")
        normalized_coverage: list[dict[str, Any]] = []
        for coverage_index, coverage in enumerate(coverage_items, start=1):
            if not isinstance(coverage, dict) or set(coverage) != {"label", "periods"}:
                raise ReportFailure("PDF 实际引用数据覆盖信息无效")
            coverage_label = coverage.get("label")
            periods = coverage.get("periods")
            if (
                not isinstance(coverage_label, str)
                or not 1 <= len(coverage_label) <= 200
                or not isinstance(periods, list)
                or len(periods) > 1200
                or any(not isinstance(period, str) or len(period) > 32 for period in periods)
            ):
                raise ReportFailure("PDF 实际引用数据覆盖信息无效")
            normalized_coverage.append(
                {"label": coverage_label or f"来源项 {coverage_index}", "periods": periods}
            )
        normalized.append(
            {
                "citationId": citation_id,
                "alias": f"[引用 {index:03d}]",
                "label": label,
                "coverageItems": normalized_coverage,
            }
        )
    presentation_ids = [item["citationId"] for item in normalized]
    # Manifest 绑定全部授权 DatasetLineage，而专题正文可以只直接使用其中一部分。
    # 展示 ledger 因而允许是 Markdown marker 的超集，但 marker 仍必须逐个来自服务端
    # ledger，且 ledger 自身不能重复，防止模型注入未知 citation 或伪造展示标签。
    if len(presentation_ids) != len(set(presentation_ids)) or not set(marker_ids).issubset(
        presentation_ids
    ):
        raise ReportFailure("PDF 实际引用展示信息与 Markdown 引用不一致")
    # Citation 绑定仍由服务端校验并写入渲染回执，但 PDF 展示层不泄露机器 marker、
    # 可读别名或来源附录；权威 Markdown 保持原样，供产物协议和血缘验收使用。
    visible_markdown = _ANALYSIS_MARKER.sub(
        "", _SECTION_MARKER.sub("", _CITATION_MARKER.sub("", markdown))
    )
    return _TABLE_MARKER.sub("", visible_markdown), normalized


def _page_layout(value: Any) -> dict[str, str]:
    if value is None:
        return dict(DEFAULT_PAGE_LAYOUT)
    if not isinstance(value, dict) or set(value) - PAGE_LAYOUT_FIELDS:
        raise ReportFailure("PDF 页面格式无效")
    layout = dict(DEFAULT_PAGE_LAYOUT)
    for key, item in value.items():
        if not isinstance(item, str) or len(item) > 200:
            raise ReportFailure("PDF 页面格式无效")
        if any(ord(character) < 32 and character != "\t" for character in item):
            raise ReportFailure("PDF 页面格式包含控制字符")
        try:
            parsed = tuple(Formatter().parse(item))
        except ValueError as error:
            raise ReportFailure("PDF 页面格式无效") from error
        if any(
            field_name not in PAGE_LAYOUT_PLACEHOLDERS or format_spec or conversion
            for _literal, field_name, format_spec, conversion in parsed
            if field_name is not None
        ):
            raise ReportFailure("PDF 页面格式包含不受支持的占位符")
        layout[key] = item
    footer = f"{layout['footerLeft']}\n{layout['footerRight']}"
    if "{page}" not in footer or "{pages}" not in footer:
        raise ReportFailure("PDF 页脚必须包含当前页和总页数")
    return layout


def _formatted_page_text(
    template: str, *, title: str, organization: str, page: str | int, pages: str | int
) -> str:
    return template.format(title=title, organization=organization, page=page, pages=pages)


def _has_page_layout(
    text: str,
    layout: dict[str, str],
    *,
    title: str,
    organization: str,
    page: str | int,
    pages: str | int,
) -> bool:
    compact = "".join(text.split())
    expected = (
        _formatted_page_text(value, title=title, organization=organization, page=page, pages=pages)
        for value in layout.values()
        if value
    )
    return all("".join(value.split()) in compact for value in expected)


def _toc_page_numbers(
    pages: Sequence[Any], headings: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    """从 WeasyPrint 页面锚点计算正文从 1 开始的稳定目录页码。"""
    anchor_pages: dict[str, int] = {}
    expected_anchors = {str(item["anchor"]): str(item["anchor"]) for item in headings}
    for physical_page, page in enumerate(pages, start=1):
        anchors = getattr(page, "anchors", None)
        if not isinstance(anchors, Mapping):
            continue
        for anchor in anchors:
            heading_anchor = expected_anchors.get(anchor)
            if heading_anchor is None:
                continue
            if heading_anchor in anchor_pages:
                raise ReportFailure("PDF 正文标题锚点重复")
            anchor_pages[heading_anchor] = physical_page
    if set(anchor_pages) != set(expected_anchors):
        raise ReportFailure("PDF 正文标题锚点不完整")
    body_start_page = anchor_pages[str(headings[0]["anchor"])]
    page_numbers = {anchor: page - body_start_page + 1 for anchor, page in anchor_pages.items()}
    if any(number < 1 for number in page_numbers.values()):
        raise ReportFailure("PDF 正文章节页码顺序无效")
    return page_numbers


def _roman(value: int) -> str:
    if not 1 <= value <= 3_999:
        raise ReportFailure("罗马页码超出支持范围")
    result: list[str] = []
    remaining = value
    for number, numeral in (
        (1000, "m"),
        (900, "cm"),
        (500, "d"),
        (400, "cd"),
        (100, "c"),
        (90, "xc"),
        (50, "l"),
        (40, "xl"),
        (10, "x"),
        (9, "ix"),
        (5, "v"),
        (4, "iv"),
        (1, "i"),
    ):
        count, remaining = divmod(remaining, number)
        result.extend(numeral for _index in range(count))
    return "".join(result)


def _page_number_context(
    physical_page: int, *, body_start_page: int, physical_page_count: int
) -> tuple[str | int, str | int]:
    """返回当前分节内的页码和分节总页数，封面不进入编号体系。"""
    if (
        not 2 <= physical_page <= physical_page_count
        or not 2 <= body_start_page <= physical_page_count
    ):
        raise ReportFailure("报表分节页码边界无效")
    if physical_page < body_start_page:
        return _roman(physical_page - 1), _roman(body_start_page - 2)
    return physical_page - body_start_page + 1, physical_page_count - body_start_page + 1


def _pdf_section_pages(reader: Any, sections: list[dict[str, str]]) -> dict[str, int]:
    destinations = getattr(reader, "named_destinations", {})
    pages: dict[str, int] = {}
    for section in sections:
        name = f"report-section-{section['code']}"
        destination = destinations.get(name)
        if destination is None:
            raise ReportFailure("PDF 缺少稳定章节锚点")
        try:
            pages[section["code"]] = int(reader.get_destination_page_number(destination)) + 1
        except Exception as error:
            raise ReportFailure("PDF 章节锚点无法解析") from error
    if list(pages) != [item["code"] for item in sections] or list(pages.values()) != sorted(
        pages.values()
    ):
        raise ReportFailure("PDF 章节锚点顺序与已批准提纲不一致")
    return pages


def _pdf_heading_pages(reader: Any, headings: list[dict[str, Any]]) -> dict[str, int]:
    destinations = getattr(reader, "named_destinations", {})
    pages: dict[str, int] = {}
    for item in headings:
        destination = destinations.get(item["anchor"])
        if destination is None:
            raise ReportFailure("PDF 缺少稳定标题锚点")
        try:
            pages[item["anchor"]] = int(reader.get_destination_page_number(destination)) + 1
        except Exception as error:
            raise ReportFailure("PDF 标题锚点无法解析") from error
    if list(pages.values()) != sorted(pages.values()):
        raise ReportFailure("PDF 标题锚点顺序与编号映射不一致")
    return pages


def _pdf_link_count(reader: Any, *, start_page: int, end_page: int) -> int:
    count = 0
    for page in reader.pages[start_page - 1 : end_page]:
        annotations = page.get("/Annots") or ()
        for reference in annotations:
            try:
                annotation = reference.get_object()
            except Exception:
                continue
            if annotation.get("/Subtype") == "/Link":
                count += 1
    return count


def _apply_pdf_page_decorations(
    path: Path, *, context: dict[str, Any], layout: dict[str, str]
) -> None:
    try:
        import pypdf
        from weasyprint import HTML
    except ImportError as error:
        raise ReportFailure("PDF 页面装饰运行时依赖不可用") from error
    overlay = path.with_name("render.decorations.pdf")
    decorated = path.with_name("render.decorated.pdf")
    try:
        reader = pypdf.PdfReader(str(path))
        if not reader.pages:
            raise ReportFailure("PDF 页面装饰处理缺少页面")
        section_pages = _pdf_section_pages(reader, context["sections"])
        body_start_page = min(section_pages.values())
        page_count = len(reader.pages)
        decoration_pages: list[str] = []
        for page_number in range(2, page_count + 1):
            page_value, pages_value = _page_number_context(
                page_number, body_start_page=body_start_page, physical_page_count=page_count
            )
            values = {
                key: html.escape(
                    _formatted_page_text(
                        template,
                        title=context["title"],
                        organization=context["organizationName"],
                        page=page_value,
                        pages=pages_value,
                    )
                )
                for key, template in layout.items()
            }
            decoration_pages.append(
                '<section class="decoration-page"><header><span class="left">'
                f'{values["headerLeft"]}</span><span class="right">{values["headerRight"]}</span></header>'
                f'<div class="watermark">{html.escape(context["watermarkText"])}</div>'
                '<footer><span class="left">'
                f'{values["footerLeft"]}</span><span class="right">{values["footerRight"]}</span></footer></section>'
            )
        document = (
            "<meta charset='utf-8'><style>"
            "@page{size:A4;margin:0}html,body{margin:0}body{"
            "font-family:'Noto Sans CJK SC','Noto Sans CJK JP',sans-serif;color:"
            f"{REPORT_VISUAL_THEME['muted']}"
            "}"
            ".decoration-page{position:relative;box-sizing:border-box;width:210mm;height:297mm;"
            "break-after:page;overflow:hidden}.decoration-page:last-child{break-after:auto}"
            "header,footer{position:absolute;left:18mm;right:18mm;display:grid;"
            "grid-template-columns:minmax(0,1fr) minmax(0,1fr);column-gap:8mm;"
            "font-size:8pt;line-height:1.2}header{top:7mm}footer{bottom:8mm;"
            "border-top:.5pt solid "
            f"{REPORT_VISUAL_THEME['grid']}"
            ";padding-top:2mm}"
            ".left{text-align:left;white-space:pre-wrap;overflow-wrap:anywhere}"
            ".right{text-align:right;white-space:pre-wrap;overflow-wrap:anywhere}"
            ".watermark{position:absolute;left:25mm;right:25mm;top:122mm;text-align:center;"
            "transform:rotate(-32deg);font-size:26pt;line-height:1.15;font-weight:600;"
            "color:rgba(71,84,103,.045);overflow-wrap:anywhere}"
            f"</style><body>{''.join(decoration_pages)}</body>"
        )
        HTML(string=document).write_pdf(str(overlay), pdf_variant="pdf/ua-1")
        overlay_pages = pypdf.PdfReader(str(overlay)).pages
        if len(overlay_pages) != page_count - 1:
            raise ReportFailure("PDF 页面装饰页数不一致")
        writer = pypdf.PdfWriter(clone_from=str(path))
        # pypdf 默认将合并产物写成 1.3，即使源文档是 PDF/UA-1（1.7）；保留
        # PDF/UA 所需的版本声明，避免页面装饰步骤让结构化标签变成不一致的协议。
        writer.pdf_header = "%PDF-1.7"
        # WeasyPrint 的命名页沿用绝对页计数。服务端按章节锚点一次生成全部装饰页，
        # 目录使用罗马数字，正文从 1 重启；封面明确不合并任何页面元素。
        for page, overlay_page in zip(writer.pages[1:], overlay_pages, strict=True):
            page.merge_page(overlay_page, over=False)
        with decorated.open("wb") as stream:
            writer.write(stream)
        os.replace(decorated, path)
    except ReportFailure:
        raise
    except Exception as error:
        raise ReportFailure("PDF 页面装饰处理失败") from error
    finally:
        overlay.unlink(missing_ok=True)
        decorated.unlink(missing_ok=True)


__all__ = [
    "DEFAULT_PAGE_LAYOUT",
    "MAX_PDF_BYTES",
    "MAX_PDF_PAGES",
    "PAGE_LAYOUT_FIELDS",
    "PAGE_LAYOUT_PLACEHOLDERS",
    "REPORT_VISUAL_THEME",
    "_apply_pdf_page_decorations",
    "_formatted_page_text",
    "_has_page_layout",
    "_page_layout",
    "_page_number_context",
    "_pdf_heading_pages",
    "_pdf_link_count",
    "_pdf_markdown",
    "_pdf_section_pages",
    "_toc_page_numbers",
]
