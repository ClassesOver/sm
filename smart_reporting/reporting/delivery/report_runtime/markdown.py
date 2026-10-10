"""Reporting Markdown 规范化与语义文档能力。"""

import html
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

# 视觉主题属于服务端渲染契约，而不是模型自由生成的正文内容。PDF、Word、沙箱内
# Matplotlib/Plotly 默认样式与编辑器交互图表共同引用 theme.py 中这一份科技蓝
# 颜色事实，避免封面、正文和图表各自选色；图表类型、系列数量和强调对象仍由模型
# 根据数据决定，琥珀/绿色仅用于语义强调。
from .theme import REPORT_VISUAL_THEME
from .validation import ReportFailure

_WORD_MARKERS = {
    "cover_end": "__REPORT_COVER_END__",
    "toc_field_start": "__REPORT_TOC_FIELD_START__",
    "toc_field_end": "__REPORT_TOC_FIELD_END__",
    "toc_end": "__REPORT_TOC_END__",
    "body_start": "__REPORT_BODY_START__",
}


def format_heading_label(*, level: int, number: str, title: str) -> str:
    """返回报告正文和目录共用的标题显示文本。"""

    return f"{number}. {title}" if level == 2 else f"{number} {title}"


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
_IMAGE_PARAGRAPH_PATTERN = (
    r"(?P<image><p>\s*<img\b[^>]*?/?>"
    r"(?:[ \t]*\[来源 [0-9]{3}\])*\s*</p>)"
)
_IMAGE_WITH_CAPTION = re.compile(
    _IMAGE_PARAGRAPH_PATTERN + r"\s*"
    r"(?P<caption><p>\s*<em>图表：.*?</em>\s*</p>)",
    re.DOTALL,
)
_IMAGE_PARAGRAPH = re.compile(_IMAGE_PARAGRAPH_PATTERN)


def _figure_image_html(image_paragraph: str) -> str:
    """将 Markdown 图片段落放入稳定的 figure 容器，供 PDF/Word 共享分页语义。"""

    image = image_paragraph.strip()
    image = re.sub(r"^<p>\s*|\s*</p>$", "", image)
    return f'<p class="report-figure-image">{image}</p>'


def _prepare_figure_layout(body: str) -> str:
    """把图片及其紧邻图注包装成不可拆分的语义块。

    Markdown 渲染器会把图片和图注分别输出为两个段落。若只给图片设置
    ``break-inside``，分页器仍可能把图注或相邻解释挪到下一页；这里在最终
    HTML 边界补上 figure/figcaption，不改变权威 Markdown 或数据内容。
    """

    def with_caption(match: re.Match[str]) -> str:
        caption = re.sub(r"^\s*<p>\s*<em>|</em>\s*</p>\s*$", "", match["caption"]).strip()
        return (
            '<figure class="report-figure">'
            f"{_figure_image_html(match['image'])}"
            f'<figcaption class="report-figure-caption">{caption}</figcaption>'
            "</figure>"
        )

    prepared = _IMAGE_WITH_CAPTION.sub(with_caption, body)

    def without_caption(match: re.Match[str]) -> str:
        return f'<figure class="report-figure">{_figure_image_html(match["image"])}</figure>'

    return _IMAGE_PARAGRAPH.sub(without_caption, prepared)


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


_CJK_CHAR = r"[\u3400-\u9fff]"
# 汉字或全角收尾符号（括号、引号、书名号）之后的半角标点同样属于中文正文。
_CJK_CLOSING = r"[\u3400-\u9fff）”》】]"
# 协议标记、数值占位与 Markdown 链接/图片地址是机器文本，不参与标点规范。
_PUNCTUATION_PROTECTED = re.compile(
    r"\[\[[^\]\r\n]+\]\]|\{\{[^{}\r\n]+\}\}|\]\([^)\r\n]*\)"
)
# 前接汉字（含粗体收尾“**”）或后接汉字的半角标点改为全角。后接汉字时前面是数字
# 也不可能是千分位或时间（二者后面都是数字），“10:30,地点”同样改写。
_HALF_WIDTH_PUNCTUATION = re.compile(
    rf"(?:(?:(?<={_CJK_CLOSING})|(?<={_CJK_CLOSING}\*\*))(?P<after>[,:;])[ \t]*)"
    rf"|(?:(?P<before>[,:;])[ \t]*(?={_CJK_CHAR}))"
)
_FULL_WIDTH = {",": "，", ":": "：", ";": "；"}


# 同一行内成对、不嵌套的半角括号；括号内含中文、前接中文/全角标点，或位于行首/空白后
# 且后接中文（“(1)门诊量”）时整对改为全角。前接英文数字的 f(x) 保持原样。
_HALF_WIDTH_PARENTHESES = re.compile(r"\(([^()\r\n]{1,80})\)")
_CJK_CONTEXT = r"[\u3400-\u9fff，。；：、！？（）“”]"


def _full_width_parentheses(piece: str) -> str:
    def replace(match: re.Match[str]) -> str:
        before = piece[match.start() - 1] if match.start() > 0 else ""
        after = piece[match.end()] if match.end() < len(piece) else ""
        if (
            re.search(_CJK_CHAR, match[1])
            or re.fullmatch(_CJK_CONTEXT, before)
            or (re.fullmatch(_CJK_CHAR, after) and not re.fullmatch(r"[A-Za-z0-9_]", before))
        ):
            return f"（{match[1]}）"
        return match[0]

    return _HALF_WIDTH_PARENTHESES.sub(replace, piece)


def _full_width_punctuation(piece: str) -> str:
    return _HALF_WIDTH_PUNCTUATION.sub(
        lambda match: _FULL_WIDTH[match["after"] or match["before"]], piece
    )


def _convert_unprotected(text: str, convert: Callable[[str], str]) -> str:
    """只改写协议标记、数值占位与链接地址之外的文本。"""

    pieces: list[str] = []
    previous_end = 0
    for protected in _PUNCTUATION_PROTECTED.finditer(text):
        pieces.append(convert(text[previous_end : protected.start()]))
        pieces.append(protected[0])
        previous_end = protected.end()
    pieces.append(convert(text[previous_end:]))
    return "".join(pieces)


def _normalize_cjk_punctuation_text(text: str) -> str:
    def convert(piece: str) -> str:
        # 括号改为全角后，紧随其后的“（表1）,”“（元）:”才具备中文上下文，需再规范一次。
        return _full_width_punctuation(_full_width_parentheses(_full_width_punctuation(piece)))

    return _convert_unprotected(text, convert)


def normalize_cjk_punctuation(markdown: str) -> str:
    """中文正文中的半角逗号、冒号、分号与括号改为全角。

    只改紧邻汉字的标点与含中文的成对括号：千分位（1,234）、时间（12:30）、英文
    （A, B、f(x)）、协议标记、链接地址与代码保持原样。
    """

    return _normalize_report_markdown_segments(markdown, _normalize_cjk_punctuation_text)


# 模型从数值目录抄来的 ISO 期间（2025-01、2025-01-31）在正文中改为中文日期。
# 前后紧邻字母数字、连字符、斜杠或点时是文件名、地址或编号，不改。
_ISO_DATE = (
    r"(?P<{p}y>(?:19|20)\d{{2}})-(?P<{p}m>0[1-9]|1[0-2])"
    r"(?:-(?P<{p}d>0[1-9]|[12]\d|3[01]))?"
)
# 只看 ASCII 字母数字：Python 的 \w 含汉字，“期间2025-01”同样需要改写。
_ISO_DATE_BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_./\-])"
_ISO_DATE_BOUNDARY_AFTER = r"(?![A-Za-z0-9_./\-:])"
_ISO_DATE_RANGE = re.compile(
    _ISO_DATE_BOUNDARY_BEFORE + _ISO_DATE.format(p="a")
    + r"\s*(?:至|到|~|～|—|–|-)\s*" + _ISO_DATE.format(p="b") + _ISO_DATE_BOUNDARY_AFTER
)
_ISO_DATE_SINGLE = re.compile(
    _ISO_DATE_BOUNDARY_BEFORE + _ISO_DATE.format(p="a") + _ISO_DATE_BOUNDARY_AFTER
)
_COMPARISON_TERMS = {"yoy": "同比", "mom": "环比"}
_COMPARISON_TERM = re.compile(r"(?<![A-Za-z0-9_])(?i:yoy|mom)(?![A-Za-z0-9_])")
_PADDED_CJK_DATE = re.compile(r"(?<=\d年)0(?=[1-9]月)|(?<=\d月)0(?=[1-9]日)")


def _cjk_date(match: re.Match[str], prefix: str, *, omit_year: bool = False) -> str:
    year, month, day = (match[f"{prefix}{part}"] for part in ("y", "m", "d"))
    text = "" if omit_year else f"{year}年"
    text += f"{int(month)}月"
    return text + (f"{int(day)}日" if day else "")


def _normalize_cjk_wording_text(text: str) -> str:
    def range_text(match: re.Match[str]) -> str:
        start = _cjk_date(match, "a")
        same_year = match["ay"] == match["by"] and bool(match["ad"]) == bool(match["bd"])
        return f"{start}至{_cjk_date(match, 'b', omit_year=same_year)}"

    def convert(piece: str) -> str:
        piece = _ISO_DATE_RANGE.sub(range_text, piece)
        piece = _ISO_DATE_SINGLE.sub(lambda match: _cjk_date(match, "a"), piece)
        piece = _PADDED_CJK_DATE.sub("", piece)
        # 数值目录的比较口径 yoy/mom 是字段值，正文写中文“同比/环比”。
        return _COMPARISON_TERM.sub(lambda match: _COMPARISON_TERMS[match[0].casefold()], piece)

    return _convert_unprotected(text, convert)


def normalize_cjk_wording(markdown: str) -> str:
    """正文中的 ISO 日期与期间区间改为中文写法（2025-01至2025-12 → 2025年1月至12月），
    比较口径 yoy/mom 改为同比/环比。

    协议标记、数值占位、链接地址与代码保持原样；文件名、版本号等紧邻字母数字的写法不改。
    """

    return _normalize_report_markdown_segments(markdown, _normalize_cjk_wording_text)


def normalize_report_markdown_strong_spacing(markdown: str) -> str:
    """移除明确成对的中文或业务数值粗体标记内侧空白。"""

    return _normalize_report_markdown_segments(markdown, _normalize_strong_spacing_line)


# CommonMark 把 U+200A 视为空白，可让紧贴标点的 ** 成为合法定界符；渲染后再
# 移除，避免成品在中文与粗体之间出现可见空格。
_STRONG_BOUNDARY = " "
_STRONG_BOUNDARY_HTML = re.compile(
    f"{_STRONG_BOUNDARY}(?=<strong>)|(?<=</strong>){_STRONG_BOUNDARY}"
)
_ATX_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|\r?\n|$)")


def _normalize_cjk_strong_markers(markdown: str) -> str:
    """让报告中的中文/数值粗体文本进入 CommonMark 的强调解析路径。

    标题行只做粗体内侧空白规范：标题锚点按草稿装配时的原始解析文本绑定，
    插入定界边界会改变标题文本并导致渲染失败。
    """

    def add_boundaries(match: re.Match[str]) -> str:
        return (
            f"{match['left']}{_STRONG_BOUNDARY}{match['open']}{match['content']}"
            f"{match['close']}{_STRONG_BOUNDARY}{match['right']}"
        )

    def normalize_line(line: str) -> str:
        normalized = _CJK_STRONG_MARKER.sub(add_boundaries, line)
        return _normalize_strong_spacing_line(normalized)

    normalized = _normalize_report_markdown_segments(markdown, normalize_line)
    return "".join(
        normalize_report_markdown_strong_spacing(source)
        if source != line and _ATX_HEADING_LINE.match(source)
        else line
        for source, line in zip(
            markdown.splitlines(keepends=True),
            normalized.splitlines(keepends=True),
            strict=True,
        )
    )


def _strip_strong_boundaries(html_body: str) -> str:
    """移除 ``_normalize_cjk_strong_markers`` 为解析插入、已紧邻粗体标签的边界。"""

    return _STRONG_BOUNDARY_HTML.sub("", html_body)


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
    expected = [
        (
            item["level"],
            format_heading_label(level=item["level"], number=item["number"], title=item["title"]),
        )
        for item in headings_contract
    ]
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
    include_cover: bool = True,
    include_toc: bool = True,
    citation_presentations: list[dict[str, Any]] | None = None,
    trace_sources: dict[str, Any] | None = None,
) -> tuple[str, str]:
    theme = REPORT_VISUAL_THEME
    body = _prepare_figure_layout(body)
    title = html.escape(context["title"])
    period = html.escape(context["periodLabel"])
    organization = html.escape(context["organizationName"])
    generated_label = html.escape(context["generatedByLabel"])
    generated_date = html.escape(context["generatedDate"])
    toc = "".join(
        f'<p class="toc-entry toc-level-{item["level"]}"><a href="#{item["anchor"]}">'
        f'<span class="toc-title">{html.escape(format_heading_label(level=item["level"], number=item["number"], title=item["title"]))}</span>'
        '<span class="toc-leader"></span>'
        f'<span class="toc-page">{toc_page_numbers.get(item["anchor"], "") if toc_page_numbers is not None else ""}</span>'
        "</a></p>"
        for item in context["headingNumbers"]
    )
    cover = (
        f'<section class="report-cover"><h1>{title}</h1>'
        f'<p class="report-period">分析期间：{period}</p>'
        f'<p class="report-organization">{organization}</p>'
        f'<p class="report-generated">{generated_label}</p></section>'
        if include_cover
        else ""
    )
    toc_section = f'<section class="report-toc"><h1>目录</h1>{toc}</section>' if include_toc else ""
    # 无封面导出时报告标题随正文起始，避免成品中完全缺失标题。
    body_title = "" if include_cover else f'<h1 class="report-title">{title}</h1>'
    source_appendix = _source_appendix_html(citation_presentations or []) + (
        _trace_source_appendix_html(trace_sources) if trace_sources else ""
    )
    shared = (
        f'{cover}{toc_section}<main class="report-body">{body_title}{body}'
        f"{source_appendix}"
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
        ".report-body img{max-width:100%;height:auto}"
        ".report-title{color:"
        f"{theme['primary']}"
        ";font-size:22pt;margin:0 0 8mm}"
        "h2{color:"
        f"{theme['primary']}"
        ";border-left:3pt solid "
        f"{theme['accent']}"
        ";font-size:16pt;padding-left:3mm}"
        "h3{font-size:12.5pt;color:"
        f"{theme['ink']}"
        "}h4{font-size:11pt;color:"
        f"{theme['ink']}"
        "}h2,h3,h4{page-break-after:avoid;break-after:avoid;orphans:3;widows:3}"
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
        ".report-figure{display:block;margin:8mm auto 10mm;break-inside:avoid;"
        "page-break-inside:avoid;break-before:avoid;break-after:avoid;text-align:center}"
        ".report-figure-image{margin:0;break-inside:avoid;break-after:avoid;text-align:center}"
        ".report-figure-image img{display:block;max-width:100%;max-height:180mm;width:auto;"
        "height:auto;object-fit:contain;margin:0 auto}"
        ".report-figure-caption{margin:2mm 0 0;text-align:center;font-size:9pt;"
        "line-height:1.35;break-before:avoid;break-after:avoid;color:"
        f"{theme['muted']}"
        "}.report-figure + p{break-before:avoid;page-break-before:avoid}"
        "p:has(+.report-figure){break-after:avoid;page-break-after:avoid}"
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
        ".report-source-appendix{break-before:page;page-break-before:always}"
        ".report-source-title{color:"
        f"{theme['primary']}"
        ";font-size:16pt;font-weight:700;margin:0 0 8mm}"
        ".report-source-entry{break-inside:avoid;margin:0 0 5mm}"
        ".report-source-entry dt{font-weight:700;color:"
        f"{theme['primary']}"
        ";margin-bottom:1mm}"
        ".report-source-entry dd{margin:0 0 1mm 5mm;color:"
        f"{theme['ink']}"
        "}.report-source-status-stale,.report-source-status-unbound,"
        ".report-source-status-missing{color:#9A3412;font-weight:700}"
    )
    pdf_document = (
        f"<html lang='zh-CN'><head><meta charset='utf-8'><title>{title}</title>"
        f"<style>{pdf_css}</style></head>"
        f"<body>{shared}</body></html>"
    )
    word_cover = (
        f"<h1>{title}</h1><p>分析期间：{period}</p><p>{organization}</p><p>{generated_label}</p>"
        if include_cover
        else ""
    )
    # 版式标记始终存在，由 Word 后处理按导出设置决定是否形成封面/目录分节。
    word_toc = (
        f"{'<h1>目录</h1>' if include_toc else ''}<p>{_WORD_MARKERS['toc_field_start']}</p>"
        f"{toc if include_toc else ''}<p>{_WORD_MARKERS['toc_field_end']}</p>"
    )
    # Pandoc 将 figure 转为窄布局表，Word 图片按页宽缩放后仍会被单元格裁切。
    # Word 使用既有段落/图片分页，保留同一图注与来源文本，不创建布局表。
    word_body = (
        body.replace('<figure class="report-figure">', '<div class="report-figure">')
        .replace('</figure>', '</div>')
        .replace('<figcaption class="report-figure-caption">', '<p class="report-figure-caption">')
        .replace('</figcaption>', '</p>')
    )
    word_document = (
        "<meta charset='utf-8'><body>"
        f"{word_cover}<p>{_WORD_MARKERS['cover_end']}</p>"
        f"{word_toc}<p>{_WORD_MARKERS['toc_end']}</p>"
        f"<p>{_WORD_MARKERS['body_start']}</p>{'' if include_cover else f'<h1>{title}</h1>'}{word_body}"
        f"{source_appendix}<p>{organization}</p><p>{generated_date}</p></body>"
    )
    return pdf_document, word_document


def _source_appendix_html(presentations: list[dict[str, Any]]) -> str:
    if not presentations:
        return ""
    status_labels = {
        "valid": "有效",
        "stale": "待复核",
        "unbound": "未绑定",
        "missing": "来源缺失",
    }
    entries: list[str] = []
    for item in presentations:
        coverage = []
        for covered in item["coverageItems"]:
            periods = "、".join(covered["periods"]) if covered["periods"] else "未登记"
            coverage.append(f"{covered['label']}（{periods}）")
        status = item["status"]
        online_links = [
            f'<a href="{html.escape(link["url"], quote=True)}">'
            f'{html.escape(link["label"])} {index}</a>'
            for index, link in enumerate(item.get("links", ()), start=1)
        ]
        online = "、".join(online_links) or "未提供在线定位"
        summary = (
            f"<dd>摘要：{html.escape(item['summary'])}</dd>"
            if item.get("summary")
            else ""
        )
        entries.append(
            '<dl class="report-source-entry">'
            f'<dt>{html.escape(item["alias"])} {html.escape(item["label"])}</dt>'
            f'<dd class="report-source-status-{status}">状态：{status_labels[status]}</dd>'
            f'<dd>范围：{html.escape(item["scope"])}</dd>'
            f'<dd>期间：{html.escape("、".join(coverage) if coverage else "未登记")}</dd>'
            f'<dd>方法：{html.escape(item["method"])}</dd>'
            f"{summary}<dd>在线定位：{online}</dd></dl>"
        )
    return (
        '<section class="report-source-appendix">'
        '<p class="report-source-title">实际引用附录</p>'
        '<p>以下编号由服务端按正文首次出现顺序生成，相同来源复用同一编号。</p>'
        f'{"".join(entries)}</section>'
    )


def _trace_source_appendix_html(trace_sources: dict[str, Any] | None) -> str:
    """数据来源附录（B8）：正文事实、表格与静态图共用一个编号序列。

    摘要字段全部来自冻结追溯索引与草稿校验结果；失效状态显式标注，
    不以"有效来源"样式掩盖。链接指向 report/revision/subject，不带会话。
    """
    if not trace_sources:
        return ""
    entries = trace_sources.get("entries") or []
    if not entries:
        return ""
    datasets = trace_sources.get("datasets") or {}
    status_labels = {
        "valid": "有效",
        "stale": "待复核",
        "unbound": "未绑定",
        "missing": "来源缺失",
    }
    kind_labels = {"claim": "正文事实", "table": "结构化表格", "chart": "静态图表"}
    period_role_labels = {"current": "本期", "yoy": "同比基期", "mom": "环比基期"}

    def dataset_field(dataset_ids: list[str], key: str) -> list[str]:
        values: list[str] = []
        for dataset_id in dataset_ids:
            info = datasets.get(dataset_id)
            if not isinstance(info, dict):
                continue
            value = info.get(key)
            if isinstance(value, str) and value and value not in values:
                values.append(value)
        return values

    def dataset_period_labels(dataset_ids: list[str]) -> list[str]:
        labels: list[str] = []
        for dataset_id in dataset_ids:
            info = datasets.get(dataset_id)
            if not isinstance(info, dict):
                continue
            for role in info.get("periodRoles") or ():
                label = period_role_labels.get(role, role)
                if label not in labels:
                    labels.append(label)
        return labels

    html_entries: list[str] = []
    for entry in entries:
        kind = entry.get("kind", "claim")
        dataset_ids = entry.get("datasetIds") or []
        rows: list[str] = [
            f'<dd class="report-source-status-{entry["status"]}">'
            f'状态：{status_labels[entry["status"]]}</dd>'
        ]
        if kind == "claim":
            value = entry.get("factValue")
            unit = entry.get("unit")
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            value_text = "未登记" if value is None else f"{value} {unit or ''}".strip()
            rows.append(f"<dd>事实值：{html.escape(str(value_text))}</dd>")
            periods = "、".join(entry.get("periods") or ()) or None
        else:
            periods = "、".join(dataset_period_labels(dataset_ids)) or None
        rows.append(f"<dd>期间：{html.escape(periods or '未登记')}</dd>")
        if kind == "claim":
            scope = entry.get("scope") or {}
            scope_text = "、".join(f"{key}={item}" for key, item in scope.items()) or None
        else:
            scope_text = "、".join(dataset_field(dataset_ids, "businessLabel")) or None
        rows.append(f"<dd>范围：{html.escape(scope_text or '未登记')}</dd>")
        methods: list[str] = []
        if kind == "claim":
            formula = entry.get("formula")
            if isinstance(formula, str) and formula:
                methods.append(formula)
        else:
            methods.extend(entry.get("methods") or ())
            if kind == "chart":
                methods.extend(f"转换：{note}" for note in (entry.get("transformNotes") or ()))
        rows.append(f"<dd>方法：{html.escape('；'.join(methods) or '未登记')}</dd>")
        files = dataset_field(dataset_ids, "filename")
        rows.append(f"<dd>源文件：{html.escape('、'.join(files) or '未登记')}</dd>")
        online_links = [
            f'<a href="{html.escape(link["url"], quote=True)}">来源对象 {index}</a>'
            for index, link in enumerate(entry.get("links") or (), start=1)
        ]
        online = "、".join(online_links) or "未提供在线定位"
        omitted = entry.get("omittedCounts") or {}
        omitted_labels = {"datasetIds": "源文件", "methods": "方法", "transformNotes": "转换说明", "links": "在线定位"}
        omitted_text = "；".join(
            f"{label}省略 {omitted[field]} 项"
            for field, label in omitted_labels.items() if field in omitted
        )
        if omitted_text:
            rows.append(f"<dd>摘要省略：{omitted_text}。完整登记见在线数据来源。</dd>")
        html_entries.append(
            '<dl class="report-source-entry">'
            f'<dt>{html.escape(entry["alias"])} {kind_labels.get(kind, kind)}</dt>'
            f'{"".join(rows)}<dd>在线定位：{online}</dd></dl>'
        )
    return (
        '<section class="report-source-appendix report-trace-source-appendix">'
        '<p class="report-source-title">数据来源附录</p>'
        '<p>以下编号由服务端按正文首次出现顺序生成，相同来源复用同一编号；'
        "失效说明为软语义提示，不隐藏任何待复核或未绑定来源。</p>"
        f'{"".join(html_entries)}</section>'
    )


__all__ = [
    "REPORT_VISUAL_THEME",
    "_WORD_MARKERS",
    "_bind_heading_anchors",
    "_body_tokens",
    "_document_context",
    "format_heading_label",
    "_markdown_title",
    "_normalize_cjk_strong_markers",
    "_normalize_report_markdown_segments",
    "_normalize_strong_spacing_line",
    "_semantic_documents",
    "_source_appendix_html",
    "_trace_source_appendix_html",
    "normalize_report_markdown_strong_spacing",
]
