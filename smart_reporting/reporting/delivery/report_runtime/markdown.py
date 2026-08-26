"""Reporting Markdown 规范化与语义文档能力。"""

import html
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from .validation import ReportFailure

# 视觉主题属于服务端渲染契约，而不是模型自由生成的正文内容。PDF、Word 与
# Coding 生成的图表共同引用这一份科技蓝颜色事实，避免封面、正文和图表各自选色；
# 图表类型、系列数量和强调对象仍由模型根据数据决定，琥珀/绿色仅用于语义强调。
REPORT_VISUAL_THEME = {
    "name": "enterprise-tech-blue",
    "primary": "#0B4F8A",
    "accent": "#007EA7",
    "highlight": "#F2B134",
    "ink": "#1B2A41",
    "muted": "#5B6B7A",
    "grid": "#C7D7E5",
    "surface": "#EDF5FC",
    "chartPalette": [
        "#0B4F8A",
        "#007EA7",
        "#2F80ED",
        "#56B4E9",
        "#F2B134",
        "#2E9F6B",
        "#7A5AF8",
        "#D66B3D",
    ],
}
_WORD_MARKERS = {
    "cover_end": "__REPORT_COVER_END__",
    "toc_field_start": "__REPORT_TOC_FIELD_START__",
    "toc_field_end": "__REPORT_TOC_FIELD_END__",
    "toc_end": "__REPORT_TOC_END__",
    "body_start": "__REPORT_BODY_START__",
}

_CJK_STRONG_MARKER = re.compile(
    r"(?P<left>[^\s*`])(?<!\*)(?P<open>\*\*)(?P<content>[^*\r\n`]*[\u3400-\u9fff][^*\r\n`]*?)(?P<close>\*\*)(?P<right>[^\s*`])"
)
_OPEN_SPACED_CJK_STRONG_MARKER = re.compile(
    r"(?<![\*`])\*\*[ \t]+(?P<content>[\u3400-\u9fff“「『【（《〈〔［｛][^*\r\n`]*?)\*\*(?![\*`])(?=\s|[，。；：、！？）】》〉〕］｝]|$)"
)
_SPACED_CJK_STRONG_MARKER = re.compile(
    r"(?<![\*`])\*\*(?P<content>[\u3400-\u9fff“「『【（《〈〔［｛][^*\r\n`]*?)\s+\*\*(?![\*`])(?=\s|[，。；：、！？）】》〉〕］｝])"
)
_SPACED_VALUE_STRONG_MARKER = re.compile(
    r"(?<![\*`])\*\*(?P<content>[^*\r\n`]*(?:%|％|亿元|万元|元|万)[^*\r\n`]*)\*\*(?![\*`])"
)
_FENCED_CODE_START = re.compile(r"^(?P<indent> {0,3})(?P<fence>`{3,}|~{3,})")
_INLINE_CODE_SPAN = re.compile(r"(?P<delimiter>`+).*?(?P=delimiter)")


def _trim_strong_marker_spacing(match: re.Match[str]) -> str:
    content = match["content"]
    trimmed = content.strip()
    if not trimmed:
        return match[0]
    return f"**{trimmed}**"


def _normalize_strong_spacing_line(line: str) -> str:
    normalized = _OPEN_SPACED_CJK_STRONG_MARKER.sub(_trim_strong_marker_spacing, line)
    normalized = _SPACED_CJK_STRONG_MARKER.sub(_trim_strong_marker_spacing, normalized)
    return _SPACED_VALUE_STRONG_MARKER.sub(_trim_strong_marker_spacing, normalized)


def _normalize_inline_text_segments(
    line: str,
    normalize_text: Callable[[str], str],
) -> str:
    normalized: list[str] = []
    previous_end = 0
    for code_span in _INLINE_CODE_SPAN.finditer(line):
        normalized.append(normalize_text(line[previous_end : code_span.start()]))
        normalized.append(code_span[0])
        previous_end = code_span.end()
    normalized.append(normalize_text(line[previous_end:]))
    return "".join(normalized)


def _normalize_report_markdown_segments(
    markdown: str,
    normalize_line: Callable[[str], str],
) -> str:
    """只规范普通 Markdown 行，保留围栏代码和缩进代码的原始文本。"""

    normalized: list[str] = []
    fence: tuple[str, int] | None = None
    for line in markdown.splitlines(keepends=True):
        if fence is not None:
            normalized.append(line)
            without_ending = line.rstrip("\r\n")
            indent = len(without_ending) - len(without_ending.lstrip(" "))
            candidate = without_ending.lstrip(" ").rstrip(" \t")
            if indent <= 3 and len(candidate) >= fence[1] and set(candidate) == {fence[0]}:
                fence = None
            continue
        opening = _FENCED_CODE_START.match(line)
        if opening is not None:
            marker = opening["fence"]
            fence = (marker[0], len(marker))
            normalized.append(line)
            continue
        if line.startswith("    ") or line.startswith("\t"):
            normalized.append(line)
            continue
        normalized.append(_normalize_inline_text_segments(line, normalize_line))
    return "".join(normalized)


def normalize_report_markdown_strong_spacing(markdown: str) -> str:
    """移除明确成对的中文或业务数值粗体标记内侧空白。"""

    return _normalize_report_markdown_segments(markdown, _normalize_strong_spacing_line)


def _normalize_cjk_strong_markers(markdown: str) -> str:
    """让报告中的中文/数值粗体文本进入 CommonMark 的强调解析路径。"""

    def add_boundaries(match: re.Match[str]) -> str:
        return f"{match['left']} {match['open']}{match['content']}{match['close']} {match['right']}"

    def normalize_line(line: str) -> str:
        normalized = _CJK_STRONG_MARKER.sub(add_boundaries, line)
        return _normalize_strong_spacing_line(normalized)

    return _normalize_report_markdown_segments(markdown, normalize_line)


def _document_context(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "title",
        "periodLabel",
        "organizationName",
        "generatedByLabel",
        "watermarkText",
        "generatedDate",
        "sectionNumbers",
        "sections",
        "headingNumbers",
    }:
        raise ReportFailure("报告缺少服务端文档展示契约")
    normalized: dict[str, Any] = {}
    for key, maximum in (
        ("title", 300),
        ("periodLabel", 100),
        ("organizationName", 200),
        ("generatedByLabel", 200),
        ("watermarkText", 200),
        ("generatedDate", 32),
    ):
        item = value.get(key)
        if (
            not isinstance(item, str)
            or not item.strip()
            or len(item) > maximum
            or any(ord(character) < 32 for character in item)
        ):
            raise ReportFailure("服务端文档展示契约无效")
        normalized[key] = item.strip()
    try:
        datetime.strptime(normalized["generatedDate"], "%Y-%m-%d")
    except ValueError as error:
        raise ReportFailure("服务端生成日期无效") from error
    sections = value.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 100:
        raise ReportFailure("服务端正式章节契约无效")
    normalized_sections: list[dict[str, str]] = []
    for item in sections:
        if not isinstance(item, dict) or set(item) != {"code", "sectionNumber", "title"}:
            raise ReportFailure("服务端正式章节契约无效")
        code = item.get("code")
        title = item.get("title")
        section_number = item.get("sectionNumber")
        if (
            not isinstance(code, str)
            or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", code) is None
            or not isinstance(title, str)
            or not title.strip()
            or len(title) > 300
            or any(ord(character) < 32 for character in title)
            or not isinstance(section_number, str)
            or re.fullmatch(r"[1-9][0-9]*", section_number) is None
        ):
            raise ReportFailure("服务端正式章节契约无效")
        normalized_sections.append(
            {"code": code, "sectionNumber": section_number, "title": title.strip()}
        )
    codes = [item["code"] for item in normalized_sections]
    titles = [item["title"] for item in normalized_sections]
    if len(codes) != len(set(codes)) or len(titles) != len(set(titles)):
        raise ReportFailure("服务端正式章节契约包含重复项")
    section_numbers = value.get("sectionNumbers")
    expected_section_numbers = [str(index) for index in range(1, len(sections) + 1)]
    if (
        section_numbers != expected_section_numbers
        or [item["sectionNumber"] for item in normalized_sections] != expected_section_numbers
    ):
        raise ReportFailure("服务端正式章节编号不连续")
    headings = value.get("headingNumbers")
    if not isinstance(headings, list) or not headings:
        raise ReportFailure("报告缺少服务端标题编号映射")
    normalized_headings: list[dict[str, Any]] = []
    for item in headings:
        if not isinstance(item, dict) or set(item) != {
            "level",
            "number",
            "title",
            "sectionCode",
            "anchor",
        }:
            raise ReportFailure("服务端标题编号映射无效")
        if (
            item["level"] not in {2, 3, 4}
            or not isinstance(item["number"], str)
            or re.fullmatch(r"[1-9][0-9]*(?:\.[1-9][0-9]*){0,2}", item["number"]) is None
            or not isinstance(item["title"], str)
            or not item["title"].strip()
            or item["sectionCode"] not in codes
            or not isinstance(item["anchor"], str)
            or re.fullmatch(r"report-(?:section|heading)-[a-z0-9_-]+", item["anchor"]) is None
        ):
            raise ReportFailure("服务端标题编号映射无效")
        normalized_headings.append({**item, "title": item["title"].strip()})
    primary = [item for item in normalized_headings if item["level"] == 2]
    if (
        [item["sectionCode"] for item in primary] != codes
        or [item["number"] for item in primary] != expected_section_numbers
        or len({item["anchor"] for item in normalized_headings}) != len(normalized_headings)
    ):
        raise ReportFailure("服务端标题编号映射与正式章节不一致")
    normalized["sectionNumbers"] = expected_section_numbers
    normalized["sections"] = normalized_sections
    normalized["headingNumbers"] = normalized_headings
    return normalized


def _markdown_title(tokens: list[Any]) -> str:
    for index, token in enumerate(tokens[:-1]):
        if token.type == "heading_open" and token.tag == "h1":
            title = str(getattr(tokens[index + 1], "content", "") or "").strip()
            if title:
                return title[:300]
    return "智能运营报表"


def _bind_heading_anchors(tokens: list[Any], headings_contract: list[dict[str, Any]]) -> None:
    headings: list[tuple[Any, int, str]] = []
    for index, token in enumerate(tokens[:-1]):
        if token.type == "heading_open" and token.tag in {"h2", "h3", "h4"}:
            headings.append(
                (
                    token,
                    int(token.tag[1:]),
                    "".join(
                        str(item.content or "")
                        for item in getattr(tokens[index + 1], "children", ()) or ()
                        if item.type in {"text", "code_inline", "image"}
                    ).strip(),
                )
            )
    expected = [(item["level"], f"{item['number']} {item['title']}") for item in headings_contract]
    if [(level, title) for _token, level, title in headings] != expected:
        raise ReportFailure("Markdown 标题顺序与服务端编号映射不一致")
    for (token, _level, _title), item in zip(headings, headings_contract, strict=True):
        token.attrSet("id", item["anchor"])


def _body_tokens(tokens: list[Any]) -> list[Any]:
    for index, token in enumerate(tokens[:-2]):
        if token.type == "heading_open" and token.tag == "h1":
            return [*tokens[:index], *tokens[index + 3 :]]
    return tokens


def _semantic_documents(
    body: str,
    *,
    context: dict[str, Any],
    layout: dict[str, str],
    toc_page_numbers: Mapping[str, int] | None = None,
) -> tuple[str, str]:
    theme = REPORT_VISUAL_THEME
    title = html.escape(context["title"])
    period = html.escape(context["periodLabel"])
    organization = html.escape(context["organizationName"])
    generated_label = html.escape(context["generatedByLabel"])
    generated_date = html.escape(context["generatedDate"])
    toc = "".join(
        f'<p class="toc-entry toc-level-{item["level"]}"><a href="#{item["anchor"]}">'
        f'<span class="toc-title">{html.escape(item["number"] + " " + item["title"])}</span>'
        '<span class="toc-leader"></span>'
        f'<span class="toc-page">{toc_page_numbers.get(item["anchor"], "") if toc_page_numbers is not None else ""}</span>'
        "</a></p>"
        for item in context["headingNumbers"]
    )
    shared = (
        f'<section class="report-cover"><h1>{title}</h1>'
        f'<p class="report-period">分析期间：{period}</p>'
        f'<p class="report-organization">{organization}</p>'
        f'<p class="report-generated">{generated_label}</p></section>'
        f'<section class="report-toc"><h1>目录</h1>{toc}</section>'
        f'<main class="report-body">{body}'
        f'<footer class="report-signature"><p>{organization}</p><p>{generated_date}</p>'
        "</footer></main>"
    )
    pdf_css = (
        "@page cover{size:A4;margin:20mm 18mm 22mm;}"
        "@page toc{size:A4;margin:20mm 18mm 22mm;}"
        "@page body{size:A4;margin:20mm 18mm 22mm;}"
        "body{font-family:'Noto Sans CJK SC','Noto Sans CJK JP',sans-serif;"
        "font-size:10.5pt;line-height:1.65;color:"
        f"{theme['ink']}"
        ";margin:0}"
        ".report-cover{page:cover;break-after:page;min-height:250mm;position:relative;"
        "display:flex;flex-direction:column;align-items:center;text-align:center}"
        ".report-cover h1{color:"
        f"{theme['primary']}"
        ";margin-top:58mm;font-size:28pt;border:0;"
        "padding:0;max-width:150mm}"
        ".report-period{margin-top:18mm;font-size:13pt;color:"
        f"{theme['accent']}"
        "}"
        ".report-organization{margin-top:24mm;font-size:12pt;color:"
        f"{theme['ink']}"
        "}"
        ".report-generated{position:absolute;bottom:8mm;font-size:9pt;color:"
        f"{theme['muted']}"
        "}"
        ".report-toc{page:toc;break-after:page;min-height:240mm}"
        ".report-toc h1{color:"
        f"{theme['primary']}"
        ";font-size:22pt;border-bottom:1.5pt solid "
        f"{theme['accent']}"
        ";"
        "padding-bottom:5mm;margin-bottom:8mm}"
        ".toc-entry{margin:0 0 3mm}.toc-entry a{color:"
        f"{theme['ink']}"
        ";text-decoration:none;display:flex;align-items:baseline;gap:2mm}"
        ".toc-level-3{padding-left:6mm}.toc-level-4{padding-left:12mm}"
        ".toc-title{min-width:0}.toc-leader{flex:1;border-bottom:0.5pt dotted "
        f"{theme['grid']}"
        ";transform:translateY(-1.5mm)}.toc-page{min-width:3ch;text-align:right}"
        ".report-body{page:body}"
        "h2{color:"
        f"{theme['primary']}"
        ";border-left:3pt solid "
        f"{theme['accent']}"
        ";font-size:16pt;padding-left:3mm}"
        "h3{font-size:12.5pt;color:"
        f"{theme['ink']}"
        "}h2,h3{page-break-after:avoid;break-after:avoid}"
        "p,li{orphans:3;widows:3}table{width:100%;border-collapse:collapse;margin:10px 0}"
        "thead{display:table-header-group}tr{break-inside:avoid}"
        "th,td{border:0.6pt solid "
        f"{theme['grid']}"
        ";padding:5px 7px;text-align:left}"
        "th{background:"
        f"{theme['surface']}"
        ";color:"
        f"{theme['primary']}"
        "}tbody tr:nth-child(even){background:#F9FAFB}"
        "img{display:block;max-width:100%;height:auto;margin:12px auto;break-inside:avoid}"
        "p:has(>img){break-after:avoid;margin-bottom:1mm}"
        "p:has(>img)+p{break-before:avoid;margin-top:0;text-align:center;color:"
        f"{theme['muted']}"
        "}"
        "pre,code{white-space:pre-wrap;overflow-wrap:anywhere}"
        "blockquote{border-left:3px solid "
        f"{theme['accent']}"
        ";background:"
        f"{theme['surface']}"
        ";margin-left:0;padding:3mm 4mm;color:"
        f"{theme['ink']}"
        "}"
        ".report-signature{margin-top:18mm;text-align:right;break-inside:avoid}"
        ".report-signature p{margin:0 0 2mm}"
    )
    pdf_document = (
        f"<html lang='zh-CN'><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{pdf_css}</style></head>"
        f"<body>{shared}</body></html>"
    )
    word_document = (
        "<meta charset='utf-8'><body>"
        f"<h1>{title}</h1><p>分析期间：{period}</p><p>{organization}</p>"
        f"<p>{generated_label}</p><p>{_WORD_MARKERS['cover_end']}</p>"
        f"<h1>目录</h1><p>{_WORD_MARKERS['toc_field_start']}</p>{toc}"
        f"<p>{_WORD_MARKERS['toc_field_end']}</p><p>{_WORD_MARKERS['toc_end']}</p>"
        f"<p>{_WORD_MARKERS['body_start']}</p>{body}"
        f"<p>{organization}</p><p>{generated_date}</p></body>"
    )
    return pdf_document, word_document


__all__ = [
    "REPORT_VISUAL_THEME",
    "_WORD_MARKERS",
    "_bind_heading_anchors",
    "_body_tokens",
    "_document_context",
    "_markdown_title",
    "_normalize_cjk_strong_markers",
    "_normalize_report_markdown_segments",
    "_normalize_strong_spacing_line",
    "_semantic_documents",
    "normalize_report_markdown_strong_spacing",
]
