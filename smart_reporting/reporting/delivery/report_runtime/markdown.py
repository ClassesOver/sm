"""Reporting Markdown 规范化与语义文档能力。"""

import hashlib
import html
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# 视觉主题属于服务端渲染契约，而不是模型自由生成的正文内容。PDF、Word、沙箱内
# Matplotlib/Plotly 默认样式与编辑器交互图表共同引用 theme.py 中这一份科技蓝
# 颜色事实，避免封面、正文和图表各自选色；图表类型、系列数量和强调对象仍由模型
# 根据数据决定，琥珀/绿色仅用于语义强调。
from .theme import REPORT_VISUAL_THEME
from .validation import ReportFailure


def _subject_id(section_code: str, claim_id: str) -> str:
    """装配器、追溯与独立渲染器共用的正文主体身份。"""
    return "sub-" + hashlib.sha256(f"{section_code}:{claim_id}".encode()).hexdigest()[:16]


_WORD_MARKERS = {
    "cover_end": "__REPORT_COVER_END__",
    "toc_field_start": "__REPORT_TOC_FIELD_START__",
    "toc_field_end": "__REPORT_TOC_FIELD_END__",
    "toc_end": "__REPORT_TOC_END__",
    "body_start": "__REPORT_BODY_START__",
}


def visible_heading_title(title: str) -> str:
    """追溯锚点不属于标题可见文字；兼容已保存的标题契约。"""
    return re.sub(r"\[\[claim:[^\]\r\n]+\]\]", "", title)


def format_heading_label(*, level: int, number: str, title: str) -> str:
    """返回报告正文和目录共用的标题显示文本。"""

    title = visible_heading_title(title)
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


def _is_fence_close(line: str, fence: tuple[str, int]) -> bool:
    without_ending = line.rstrip("\r\n")
    indent = len(without_ending) - len(without_ending.lstrip(" "))
    candidate = without_ending.lstrip(" ").rstrip(" \t")
    return indent <= 3 and len(candidate) >= fence[1] and set(candidate) == {fence[0]}


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
            if _is_fence_close(line, fence):
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
# 引用式链接定义行（“[1]: url "标题"”）整行是机器语法，标题必须保留半角引号。
_PUNCTUATION_PROTECTED = re.compile(
    r"\[\[[^\]\r\n]+\]\]|\{\{[^{}\r\n]+\}\}|\]\([^)\r\n]*\)"
    r"|^ {0,3}\[[^\]\r\n]+\]:[^\r\n]*"
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


# 全角标点两侧的空格（“见附表 （表1）”“（1） 门诊”）；列表标记“- ”“1. ”后与表格竖线
# 两侧的空格不动。
_SPACE_AROUND_FULL_WIDTH = re.compile(
    r"(?:(?<=[\u3400-\u9fff（）。，；：、！？“”A-Za-z0-9%])|(?<=[^\s*]\*\*))[ \t]+(?=[（）。，；：、！？“”])"
    r"|(?<=[（）。，；：、！？“”])[ \t]+(?=[^\s|])"
)


# 同一行内成对的半角引号；引号内含中文或紧邻中文时改为中文引号，英文引语不变。
_STRAIGHT_QUOTES = (
    (re.compile(r'"([^"\r\n]{1,80})"'), "“", "”"),
    (re.compile(r"'([^'\r\n]{1,80})'"), "‘", "’"),
)


def _full_width_quotes(piece: str) -> str:
    for pattern, left, right in _STRAIGHT_QUOTES:
        def replace(match: re.Match[str], left: str = left, right: str = right) -> str:
            before = piece[match.start() - 1] if match.start() > 0 else ""
            after = piece[match.end()] if match.end() < len(piece) else ""
            if (re.search(_CJK_CHAR, match[1]) or re.fullmatch(_CJK_CONTEXT, before)
                    or re.fullmatch(_CJK_CONTEXT, after)):
                return f"{left}{match[1]}{right}"
            return match[0]

        piece = pattern.sub(replace, piece)
    return piece


# 中文语境的省略号写作“……”：“等...”“等…”“。。。”都改写。
_CJK_ELLIPSIS = re.compile(
    rf"(?:(?<={_CJK_CONTEXT})(?:\.{{3,}}|…+|。{{3,}})|(?:\.{{3,}}|…+|。{{3,}})(?={_CJK_CONTEXT}))"
)


# 中文句末的半角句号、问号、叹号（“收入1.37亿元.”“增长5.03%.”“是否持续?”）：前接汉字、
# 全角收尾符号或百分号（含粗体收尾“**”），且位于行尾或后接汉字时改为全角。小数、文件名、
# 省略号与图片语法“![”不变。
_SENTENCE_END_CONTEXT = rf"(?:(?<={_CJK_CLOSING})|(?<=[%‰])|(?<={_CJK_CLOSING}\*\*)|(?<=[%‰]\*\*))"
_SENTENCE_END_FOLLOW = rf"(?=\*{{0,2}}[ \t]*(?:\r?\n|\Z|\|)|[ \t]*{_CJK_CHAR})"
_HALF_WIDTH_SENTENCE_END = re.compile(
    rf"{_SENTENCE_END_CONTEXT}(?<!\.)(?P<mark>[.?!])(?![.\[]){_SENTENCE_END_FOLLOW}"
)
# 数值占位“{{value:…}}.”渲染后是带单位的数值，其后的半角句号同样是中文句末。
_VALUE_PLACEHOLDER_PERIOD = re.compile(rf"(?P<token>\{{\{{value:[^{{}}\r\n]+\}}\}})\.{_SENTENCE_END_FOLLOW}")
# 行首的“一.”“第一.”是条目编号，不是句号。
_ENUMERATION_PREFIX = re.compile(r"[ \t]*(?:#{1,6}[ \t]+)?[*_]*第?[一二三四五六七八九十]{1,3}")
_FULL_WIDTH_SENTENCE_END = {".": "。", "?": "？", "!": "！"}


def _full_width_sentence_ends(piece: str) -> str:
    def replace(match: re.Match[str]) -> str:
        line_start = piece.rfind("\n", 0, match.start()) + 1
        line_end = piece.find("\n", match.end())
        line = piece[line_start : len(piece) if line_end < 0 else line_end]
        if (_ENUMERATION_PREFIX.fullmatch(piece, line_start, match.start())
                or not re.search(_CJK_CHAR, line)):
            return match[0]
        return _FULL_WIDTH_SENTENCE_END[match["mark"]]

    return _HALF_WIDTH_SENTENCE_END.sub(replace, piece)


def _normalize_cjk_punctuation_text(text: str) -> str:
    def convert(piece: str) -> str:
        # 括号改为全角后，紧随其后的“（表1）,”“（元）:”才具备中文上下文，需再规范一次。
        piece = _full_width_punctuation(_full_width_parentheses(_full_width_punctuation(piece)))
        piece = _full_width_sentence_ends(_CJK_ELLIPSIS.sub("……", _full_width_quotes(piece)))
        return _SPACE_AROUND_FULL_WIDTH.sub("", piece)

    return _convert_unprotected(_VALUE_PLACEHOLDER_PERIOD.sub(r"\g<token>。", text), convert)


def normalize_cjk_punctuation(markdown: str) -> str:
    """中文正文中的半角逗号、冒号、分号、括号与句末句号、问号、叹号改为全角。

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
# 中文正文中数字与汉字、单位之间的空格（“收入 3,600 万元”“增长 8.6 %”）与数值目录
# 的写法（3,600万元）不一致；英文单词两侧的空格不动。
_SPACE_AFTER_NUMBER = re.compile(r"(?<=\d)[ \t]+(?=[\u3400-\u9fff%‰])")
_SPACE_BEFORE_NUMBER = re.compile(
    r"(?:(?<=[\u3400-\u9fff])|(?<=[\u3400-\u9fff]\*\*))[ \t]+(?=[+\-]?\d)"
)
# 两个汉字之间（含粗体标记两侧）的空格在中文正文中没有意义：“2025年1月 收入”
# “**2025年1月** 收入”。
_SPACE_BETWEEN_CJK = re.compile(
    r"(?:(?<=[\u3400-\u9fff])|(?<=[\u3400-\u9fff]\*\*))[ \t]+"
    r"(?=[\u3400-\u9fff]|\*\*[\u3400-\u9fff\d])"
)
# 数字后接单位或量词时是数量（3 月、12 个、3 大举措、5 条建议），不是手写标题编号；
# 标题编号清理与这里的空格规范共用同一份字表。
HEADING_QUANTITY_WORDS = "年月日个家名张床次人天项例台季周号期级类万亿元%‰大条点种方位所批组倍成岁层栋"
# 标题行首“1 收入分析”“2.3 收入趋势”的手写编号留给标题编号清理识别，不并成
# “2.3收入趋势”；后接单位或量词的（1.5 万人次、3 月）是数量，照常去空格。
_HEADING_NUMBER_PREFIX = re.compile(
    rf"^#{{1,6}}[ \t]+\d+(?:\.\d+)*[.、．]?[ \t]+(?![{HEADING_QUANTITY_WORDS}])"
)
# 全角阿拉伯数字与百分号（“５．０３％”“5.03％”）：GB/T 15835 规定阿拉伯数字用半角；
# 全角写法还让数值核对与复核认不出数字，未登记的数值因此原样落盘。
_FULL_WIDTH_NUMERALS = str.maketrans("０１２３４５６７８９％", "0123456789%")
_FULL_WIDTH_DECIMAL_POINT = re.compile(r"(?<=[0-9])．(?=[0-9])")
# 全角千分位“１３，６５４．３２万元”：只在全角数字三位一组、以小数或金额人次单位收尾时
# 改为半角逗号；否则只改数字时“654.32万元”会被单独核对，替换后变成“13，待核实”。
# 半角数字间的全角逗号（“分别为120，135，150张”）是列举，不动。
_FULL_WIDTH_GROUPED_NUMBER = re.compile(
    r"(?<![０-９])[０-９]{1,3}(?:，[０-９]{3})+(?=．[０-９]|\s*(?:亿元|万元|元|万人次|人次))"
)


# “提高2pp”“提升2个pct”“2 ppt”是百分点的英文缩写：中文报告写“个百分点”，复核才能按
# 两项登记百分数之差核对。前接字母、连字符、点或冒号的是标识符，不改。
_PERCENT_POINT_ABBREVIATION = re.compile(
    r"(?<![A-Za-z0-9_.:\-])(?P<number>\d+(?:\.\d+)?)[ \t]*(?:个[ \t]*)?(?i:pp|ppt|pct)(?![A-Za-z0-9_])"
)


# 数字前的 Unicode 减号“−”、全角“－”“﹣”与全角“＋”：不改为半角时负号认不出，登记的负值
# （“同比−3.00%”）被当作正数核对而替换为“待核实”，成稿出现“同比−待核实”残句。
_UNICODE_SIGN = re.compile(r"[−－﹣＋](?=[0-9])")


def normalize_number_notation(text: str) -> str:
    """数字写法统一为数值核对可识别的形式。

    全角数字与百分号改为半角，数字之间的全角点改为小数点（“1．收入”等条目编号不动）；
    数字前的 Unicode 减号与全角正负号改为半角；百分点缩写 pp/ppt/pct 改为“个百分点”。
    """

    text = _FULL_WIDTH_GROUPED_NUMBER.sub(lambda match: match[0].replace("，", ","), text)
    text = _FULL_WIDTH_DECIMAL_POINT.sub(".", text.translate(_FULL_WIDTH_NUMERALS))
    text = _UNICODE_SIGN.sub(lambda match: "+" if match[0] == "＋" else "-", text)
    return _PERCENT_POINT_ABBREVIATION.sub(lambda match: f"{match['number']}个百分点", text)


_COMPARISON_TERMS = {"yoy": "同比", "mom": "环比"}
_COMPARISON_TERM = re.compile(r"(?<![A-Za-z0-9_])(?i:yoy|mom)(?![A-Za-z0-9_])")
_PADDED_CJK_DATE = re.compile(r"(?<=\d年)0(?=[1-9]月)|(?<=\d月)0(?=[1-9]日)")
# 月份区间“1-10月”“1~10月”“1月-10月”与服务端期间说明（2025年1—10月）写法不一致：同一年内
# 升序的月份区间统一为“1—10月”。跨年（12-1月）、编号（ICD-10、v1-2）与非月份区间不动。
_MONTH_RANGE = re.compile(
    r"(?<![A-Za-z0-9_.\-—])(?P<a>1[0-2]|0?[1-9])[ \t]*月?[ \t]*[-~～–][ \t]*(?P<b>1[0-2]|0?[1-9])[ \t]*月"
)


def _cjk_date(match: re.Match[str], prefix: str, *, omit_year: bool = False) -> str:
    year, month, day = (match[f"{prefix}{part}"] for part in ("y", "m", "d"))
    text = "" if omit_year else f"{year}年"
    text += f"{int(month)}月"
    return text + (f"{int(day)}日" if day else "")


# 封面标题 28pt、最宽 150mm：每行约 15 个汉字。按宽度自然折行会剩下单字孤行
# （“…运营分析报 / 告”），改为各行字数接近的均衡折行；不拆开数字和英文。
_COVER_TITLE_LINE_CHARS = 15


def _balanced_cover_title(title: str) -> str:
    if len(title) <= _COVER_TITLE_LINE_CHARS:
        return html.escape(title)
    lines = -(-len(title) // _COVER_TITLE_LINE_CHARS)
    width = -(-len(title) // lines)
    pieces, start = [], 0
    while len(title) - start > width:
        end = start + width
        while end > start + 1 and all(title[i].isascii() and title[i].isalnum() for i in (end - 1, end)):
            end -= 1
        if end == start + 1:  # 整行都是连续英文数字，无处可避，按宽度折行。
            end = start + width
        pieces.append(title[start:end])
        start = end
    pieces.append(title[start:])
    return "<br>".join(html.escape(piece) for piece in pieces)


# 服务端分期间汇总表（[[table:…]] 协议块及其上一行表名）原样追加在各章末尾，回放中第1章
# 后连续3—4页月度表格把下一章推远。渲染时统一移到正文之后的“附表”，报告 Markdown、编辑器
# 与溯源标记不变；模型自写表格没有协议标记，不受影响。
_SERVER_TABLE_BLOCK = re.compile(
    # 表名是表格上一行不含协议标记、不以句末标点结尾的短行；正文段落不能被当作表名一起移走。
    # 服务端表名自成一段（前接空行）且不是列表项：多行段落的末行、列表末项不随表格移走。
    r"(?:(?:\A|(?<=\n\n))(?![\[|#!>])(?![-*+][ \t]|\d{1,3}[.)][ \t])(?![^\n]*\[\[)"
    r"[^\n]*[^\n。！？；.!?]\n\n)?^\[\[table:(?P<id>[^\]\r\n]+)\]\]\n.*?^\[\[/table:(?P=id)\]\][ \t]*(?:\n|\Z)",
    re.MULTILINE | re.DOTALL,
)
APPENDIX_TABLES_SENTINEL = "REPORTING-APPENDIX-TABLES"
APPENDIX_TABLES_TITLE = '<p class="report-appendix-title"><strong>附表</strong></p>'


def relocate_server_tables(markdown: str) -> str:
    tables = [match[0].strip() for match in _SERVER_TABLE_BLOCK.finditer(markdown)]
    if not tables:
        return markdown
    body = re.sub(r"\n{3,}", "\n\n", _SERVER_TABLE_BLOCK.sub("", markdown)).rstrip()
    return "\n\n".join((body, APPENDIX_TABLES_SENTINEL, *tables)) + "\n"


# 附表里单一数值列的月度表（“收入金额（亿元）”逐月一行）占半页却只有一列数字：渲染时转置为
# 每行6个期间的横表；同一年份的期间写在左上角，列头只写月份。报告 Markdown 与编辑器不变。
_COMPACT_TABLE_MIN_ROWS = 8
_COMPACT_TABLE_COLUMNS = 6
_SERVER_TABLE_BODY = re.compile(
    r"^(?P<open>\[\[table:(?P<id>[^\]\r\n]+)\]\]\n)(?P<table>(?:\|[^\n]*\|[ \t]*\n)+)(?P<rest>\n*\[\[/table:(?P=id)\]\])",
    re.MULTILINE,
)


def _compact_table(match: re.Match[str]) -> str:
    lines = match["table"].strip("\n").split("\n")
    rows = [_table_cells(line) for line in lines]
    if (len(rows) < 2 + _COMPACT_TABLE_MIN_ROWS or not _TABLE_SEPARATOR.match(lines[1].strip())
            or any(len(row) != 2 for row in rows) or rows[0][0]):
        return match[0]
    header, body = rows[0][1], rows[2:]
    labels = [row[0] for row in body]
    years = {label[:5] for label in labels if re.fullmatch(r"\d{4}年\d{1,2}月", label)}
    corner = ""
    if len(years) == 1 and all(re.fullmatch(r"\d{4}年\d{1,2}月", label) for label in labels):
        corner = next(iter(years))
        labels = [label[5:] for label in labels]
    tables = []
    for start in range(0, len(body), _COMPACT_TABLE_COLUMNS):
        chunk = range(start, min(start + _COMPACT_TABLE_COLUMNS, len(body)))
        tables.append("\n".join((
            "| " + " | ".join((corner, *(labels[index] for index in chunk))) + " |",
            "| " + " | ".join(("---", *("---:",) * len(chunk))) + " |",
            "| " + " | ".join((header, *(body[index][1] for index in chunk))) + " |",
        )))
    return match["open"] + "\n\n".join(tables) + "\n" + match["rest"]


def compact_single_column_tables(markdown: str) -> str:
    return _SERVER_TABLE_BODY.sub(_compact_table, markdown)


# 核心结论只摘录完整、短小的章节表述，不按首句截断口径与限制。
# 无法完整容纳的章节不生成摘录；复制正文不代表数值已验证。
SUMMARY_SENTINEL = "REPORTING-EXECUTIVE-SUMMARY"
SUMMARY_END_SENTINEL = "REPORTING-EXECUTIVE-SUMMARY-END"
SUMMARY_TITLE = '<p class="report-summary-title"><strong>核心结论</strong></p>'
SUMMARY_END = '<div class="report-summary-end"></div>'
_SUMMARY_SKIPPED_SECTION = re.compile(r"附录|附表|补充|限制|口径|说明|统计关系")
_SECTION_START = re.compile(r"^\[\[section:([^\]\r\n]+)\]\][ \t]*$", re.MULTILINE)
_NOT_PROSE = re.compile(r"^(?:#|\||!\[|\[\[|>|\*图表|[-*+]\s|\d+[.)]\s)")


# 括号内保留的元/人次原值去掉，过长的章节名截短。
_SUMMARY_RAW_VALUE = re.compile(r"[（(]-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:元|人次)[）)]")


def _summary_title(title: str) -> str:
    if len(title) <= 30:
        return title
    first = re.split(r"[；;，,]", title, maxsplit=1)[0].strip()
    return f"{first[:28]}等"


def _section_conclusion(block: str) -> str | None:
    excerpts = []
    chapter_heading_seen = False
    for paragraph in block.split("\n\n"):
        lines = []
        for line in paragraph.splitlines():
            if re.fullmatch(r"\s*\[\[/?section:[^\]\r\n]+\]\]\s*", line):
                continue
            heading = re.match(r"\s*(#{1,6})\s+(.+)", line)
            if heading:
                if len(heading[1]) <= 2 and not chapter_heading_seen:
                    chapter_heading_seen = True
                    continue
                line = heading[2] + "："
            lines.append(line)
        paragraph = "\n".join(lines).strip()
        if not paragraph:
            continue
        # Subheadings may contain qualifications. Tables/images/code
        # may carry qualifications we cannot safely summarize, so omit the chapter.
        if _NOT_PROSE.match(paragraph) and not re.match(r"^(?:>|[-*+]\s|\d+[.)]\s)", paragraph):
            return None
        if "```" in paragraph or "~~~" in paragraph:
            return None
        # 列表或引用段落逐行去掉前缀再拼接，否则第二项起的“- ”会混进核心结论。
        text = "".join(
            re.sub(r"^\s*(?:>\s*|[-*+]\s+|\d+[.)]\s+)", "", line)
            for line in re.sub(r"\[\[[^\]\r\n]+\]\]", "", paragraph).replace("**", "").split("\n")
        )
        text = _SUMMARY_RAW_VALUE.sub("", text)
        if text:
            excerpts.append(text)
    conclusion = " ".join(excerpts)
    return conclusion if 8 <= len(conclusion) <= 400 else None


def insert_executive_summary(markdown: str, sections: Sequence[Mapping[str, Any]]) -> str:
    titles = {item["code"]: item["title"] for item in sections}
    starts = list(_SECTION_START.finditer(markdown))
    lines = []
    for index, start in enumerate(starts):
        title = titles.get(start[1])
        if not title or _SUMMARY_SKIPPED_SECTION.search(title):
            continue
        end = starts[index + 1].start() if index + 1 < len(starts) else len(markdown)
        conclusion = _section_conclusion(markdown[start.end():end])
        if conclusion:
            lines.append(f"- **{_summary_title(title)}**：{conclusion}")
    if len(lines) < 2:
        return markdown
    first = starts[0].start()
    summary = "\n\n".join((SUMMARY_SENTINEL, "\n".join(lines), SUMMARY_END_SENTINEL))
    return f"{markdown[:first]}{summary}\n\n{markdown[first:]}"


# 读者是医院领导与财务人员：正文里“药品收入3,046,407,434元”“预算人次7,275,108人次”难以读出
# 量级。渲染时把百万以上的元值按亿元/万元、人次按万人次两位小数显示（阈值与内容复核的“位数过多”
# 一致）；括号内的原值（“99.12亿元（9,911,520,144元）”）是有意保留的精确值，表格、图片与代码
# 不动。报告 Markdown 与编辑器不变。
_LARGE_YUAN = re.compile(
    r"(?<![\d.,（(])(?P<number>-?(?:\d{1,3}(?:,\d{3}){2,}|\d{7,})(?:\.\d+)?)(?P<unit>元|人次)(?!\s*[）)])"
)


def _readable_amount(match: re.Match[str]) -> str:
    value = Decimal(match["number"].replace(",", ""))
    if match["unit"] == "人次":
        return f"{(value / 10_000).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}万人次"
    if abs(value) >= 100_000_000:
        return f"{(value / 100_000_000).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}亿元"
    return f"{(value / 10_000).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,}万元"


def readable_large_amounts(markdown: str) -> str:
    lines = markdown.split("\n")
    fence = False
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence or stripped.startswith(("|", "![", "    ")):
            continue
        lines[index] = _LARGE_YUAN.sub(_readable_amount, line)
    return "\n".join(lines)


# “四项全年合计分别为0元、0元、0元、0元”：逐项相同的数值渲染时合并为“均为0元”，保留首个来源标记。
# 列举后仍以“和/及/与/或”接续其他项（“分别为10%、10%和20%”）时不是全部相同，不合并。
_REPEATED_VALUES = re.compile(
    r"分别为(?P<value>-?\d[\d,]*(?:\.\d+)?(?:亿元|万元|元|万人次|人次|床日|%))(?P<marks>(?:\[\[[^\]\r\n]+\]\])*)"
    r"(?:、(?P=value)(?:\[\[[^\]\r\n]+\]\])*)+(?![\d.,]|、|\s*(?:和|及|与|或|以及))"
)


def collapse_repeated_values(markdown: str) -> str:
    return _REPEATED_VALUES.sub(lambda match: f"均为{match['value']}{match['marks']}", markdown)


# 模型自写表格常把分隔行写成全左对齐，金额、比率列的位数与小数点对不齐。渲染时全部
# 单元格都是数值（可带单位、百分号或“—”）的列改为右对齐；已声明对齐方式的列不动。
_NUMERIC_CELL = re.compile(
    r"[+\-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:%|‰|亿元|万元|元|万人次|人次|床日|个百分点|亿|万|天|倍|例|张|人)?"
    r"|[—–\-]{1,2}|"
)
_TABLE_SEPARATOR = re.compile(r"^\|(?:\s*:?-{3,}:?\s*\|)+\s*$")
# 单元格里的加粗与来源标记（“8.9亿元[[claim:a]]”）不影响是否为数值列。
_CELL_MARKUP = re.compile(r"\*\*|\[\[[^\]\r\n]+\]\]")


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


# 表头已写单位（“2025年（亿元）”）时，单元格里由数值引用渲染出的同一单位重复，渲染时去掉。
_HEADER_UNIT = re.compile(r"[（(](亿元|万元|元|万人次|人次|床日|%)[）)]\s*$")


def _strip_header_units(header: list[str], rows: list[list[str]]) -> bool:
    changed = False
    for column, title in enumerate(header):
        unit = _HEADER_UNIT.search(title)
        if unit is None:
            continue
        pattern = re.compile(
            rf"^([+\-−]?(?:\d{{1,3}}(?:,\d{{3}})+|\d+)(?:\.\d+)?){re.escape(unit[1])}"
            r"(?=(?:\[\[[^\]\r\n]+\]\])*$)"
        )
        for row in rows:
            stripped = pattern.sub(r"\1", row[column])
            changed |= stripped != row[column]
            row[column] = stripped
    return changed


def align_numeric_table_columns(markdown: str) -> str:
    lines = markdown.split("\n")
    for index, line in enumerate(lines):
        if index == 0 or not _TABLE_SEPARATOR.match(line.strip()) or not lines[index - 1].lstrip().startswith("|"):
            continue
        rows = []
        for body in lines[index + 1:]:
            if not body.lstrip().startswith("|"):
                break
            rows.append(_table_cells(body))
        separators = _table_cells(line)
        if not rows or any(len(row) != len(separators) for row in rows):
            continue
        header = _table_cells(lines[index - 1])
        if len(header) == len(separators) and _strip_header_units(header, rows):
            for offset, row in enumerate(rows, start=1):
                lines[index + offset] = "| " + " | ".join(row) + " |"
        aligned = [
            "---:" if separator == "---" and any(row[column] for row in rows)
            and all(_NUMERIC_CELL.fullmatch(_CELL_MARKUP.sub("", row[column])) for row in rows) else separator
            for column, separator in enumerate(separators)
        ]
        lines[index] = "| " + " | ".join(aligned) + " |"
    return "\n".join(lines)


def _normalize_cjk_wording_text(text: str) -> str:
    def range_text(match: re.Match[str]) -> str:
        start = _cjk_date(match, "a")
        same_year = match["ay"] == match["by"] and bool(match["ad"]) == bool(match["bd"])
        return f"{start}至{_cjk_date(match, 'b', omit_year=same_year)}"

    def convert(piece: str) -> str:
        piece = _ISO_DATE_RANGE.sub(range_text, normalize_number_notation(piece))
        piece = _ISO_DATE_SINGLE.sub(lambda match: _cjk_date(match, "a"), piece)
        piece = _PADDED_CJK_DATE.sub("", piece)
        piece = _MONTH_RANGE.sub(
            lambda match: f"{int(match['a'])}—{int(match['b'])}月" if int(match["a"]) < int(match["b"]) else match[0],
            piece,
        )
        # 数值目录的比较口径 yoy/mom 是字段值，正文写中文“同比/环比”。
        piece = _COMPARISON_TERM.sub(lambda match: _COMPARISON_TERMS[match[0].casefold()], piece)
        heading_prefix = _HEADING_NUMBER_PREFIX.match(piece)
        prefix = heading_prefix[0] if heading_prefix else ""
        rest = _SPACE_BEFORE_NUMBER.sub("", _SPACE_AFTER_NUMBER.sub("", piece[len(prefix):]))
        return prefix + _SPACE_BETWEEN_CJK.sub("", rest)

    return _convert_unprotected(text, convert)


def normalize_cjk_wording(markdown: str) -> str:
    """正文中的 ISO 日期与期间区间改为中文写法（2025-01至2025-12 → 2025年1月至12月），
    比较口径 yoy/mom 改为同比/环比，去掉数字与汉字、单位之间的空格。

    协议标记、数值占位、链接地址与代码保持原样；文件名、版本号等紧邻字母数字的写法不改。
    """

    return _normalize_report_markdown_segments(markdown, _normalize_cjk_wording_text)


# 中文条目编号（“1、”“（1）”“一是”“第一，”“一、”）不是 Markdown 列表：与上一行之间
# 只有单个换行时会并入同一段落，渲染成一行连写。
CJK_ENUMERATION_LINE = re.compile(
    r"^[*_]*(?:\d{1,2}[、．]|[（(]\d{1,2}[）)]|[（(][一二三四五六七八九十]{1,3}[）)]"
    r"|[一二三四五六七八九十]{1,3}(?:是|、)|第[一二三四五六七八九十]{1,3}[，,、：:是])"
)
_STRUCTURAL_LINE = re.compile(r"^(?:#{1,6}\s|\||[-*+]\s|\d{1,3}[.)]\s|>|!\[|\[\[)")


def separate_enumerated_lines(markdown: str) -> str:
    """单个换行分隔的中文条目各自成段，避免渲染时并成一行。

    只在上一行是普通正文或条目时插入空行；表格、列表、标题、引用、图片、协议标记
    与代码块保持原样。
    """

    lines = markdown.split("\n")
    result: list[str] = []
    fence: tuple[str, int] | None = None
    for line in lines:
        opening = _FENCED_CODE_START.match(line)
        if fence is not None:
            if _is_fence_close(line, fence):
                fence = None
            result.append(line)
            continue
        if opening is not None:
            marker = opening["fence"]
            fence = (marker[0], len(marker))
            result.append(line)
            continue
        previous = result[-1] if result else ""
        if (CJK_ENUMERATION_LINE.match(line.strip()) and not line.startswith((" ", "\t"))
                and previous.strip() and not previous.startswith((" ", "\t"))
                and not _STRUCTURAL_LINE.match(previous.strip())):
            result.append("")
        result.append(line)
    return "\n".join(result)


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
    if not isinstance(sections, list) or len(sections) < 1:
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
    if len(codes) != len(set(codes)):
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


# 东亚宽字符（汉字与全角标点）。CSS 规定两侧均为宽字符的段内换行不产生空格，
# WeasyPrint 未实现该规则，会把“增长\n住院”渲染成“增长 住院”。
_WIDE_CHARACTER = re.compile(r"[\u2e80-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef“”‘’]")
_INLINE_MARKUP = frozenset({"strong_open", "strong_close", "em_open", "em_close", "s_open", "s_close"})


def _join_cjk_soft_breaks(tokens: list[Any]) -> list[Any]:
    """两侧均为宽字符的段内软换行渲染为空，不在中文之间留下空格。"""

    def edge(children: list[Any], start: int, step: int) -> str:
        index = start
        while 0 <= index < len(children):
            child = children[index]
            if child.type == "text" and child.content:
                return child.content[-1] if step < 0 else child.content[0]
            # 粗体/斜体标记两侧会有空文本 token，跳过后继续找相邻字符。
            if child.type not in _INLINE_MARKUP and not (child.type == "text" and not child.content):
                return ""
            index += step
        return ""

    for token in tokens:
        children = token.children or []
        for index, child in enumerate(children):
            if (child.type == "softbreak"
                    and _WIDE_CHARACTER.fullmatch(edge(children, index - 1, -1) or " ")
                    and _WIDE_CHARACTER.fullmatch(edge(children, index + 1, 1) or " ")):
                child.type = "text"
                child.content = ""
    return tokens


def _body_tokens(tokens: list[Any]) -> list[Any]:
    for index, token in enumerate(tokens[:-2]):
        if token.type == "heading_open" and token.tag == "h1":
            return [*tokens[:index], *tokens[index + 3 :]]
    return tokens


_HTML_TBODY = re.compile(r"<tbody>\n?(?P<rows>.*?)</tbody>", re.DOTALL)
_HTML_ROW = re.compile(r"<tr>.*?</tr>\n?", re.DOTALL)
_HTML_TABLE_CELL = re.compile(r"(?P<open><t[hd][^>]*>)(?P<text>[^<]*?)(?P<unit>（[^（）<]{1,12}）)(?P<close></t[hd]>)")
_TABLE_KEEP_ROWS = 2


def _paginate_pdf_tables(body: str) -> str:
    """PDF 表格分页：首尾各两行不与表格其余部分分开，表头单位不在括号中间折行。

    WeasyPrint 不支持表格行的 ``break-before/after:avoid``，长表拆页时常只剩末行
    （“2025年12月 0 0”）孤零零落到下一页，或表头加首行孤悬页底。把首尾各两行放进
    ``break-inside:avoid`` 的独立 tbody；拆分后 ``nth-child`` 的斑马纹按组重新计数，
    改由显式类名标注偶数行。单元格末尾的单位“（人次）”整体换行，不拆成“（人 / 次）”。
    """

    def split(match: re.Match[str]) -> str:
        rows = _HTML_ROW.findall(match["rows"])
        striped = [
            row.replace("<tr>", '<tr class="report-row-even">', 1) if index % 2 else row
            for index, row in enumerate(rows)
        ]
        if len(rows) <= 2 * _TABLE_KEEP_ROWS:
            return f'<tbody class="report-table-keep">\n{"".join(striped)}</tbody>'
        head, middle, tail = (
            striped[:_TABLE_KEEP_ROWS], striped[_TABLE_KEEP_ROWS:-_TABLE_KEEP_ROWS], striped[-_TABLE_KEEP_ROWS:]
        )
        return (
            f'<tbody class="report-table-keep">\n{"".join(head)}</tbody>\n'
            f'<tbody>\n{"".join(middle)}</tbody>\n'
            f'<tbody class="report-table-keep">\n{"".join(tail)}</tbody>'
        )

    body = _HTML_TBODY.sub(split, body)
    return _HTML_TABLE_CELL.sub(
        lambda match: f'{match["open"]}{match["text"]}<span class="report-unit">{match["unit"]}</span>{match["close"]}',
        body,
    )


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
        f'<section class="report-cover"><h1>{_balanced_cover_title(context["title"])}</h1>'
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
        f'{cover}{toc_section}<main class="report-body">{body_title}{_paginate_pdf_tables(body)}'
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
        "h2,.report-appendix-title{color:"
        f"{theme['primary']}"
        ";border-left:3pt solid "
        f"{theme['accent']}"
        ";font-size:16pt;padding-left:3mm}"
        ".report-appendix-title{break-before:page;page-break-before:always;margin:0.8em 0;"
        "page-break-after:avoid;break-after:avoid}"
        ".report-summary-title{color:"
        f"{theme['primary']}"
        ";border-left:3pt solid "
        f"{theme['accent']}"
        ";font-size:16pt;padding-left:3mm;margin:0.8em 0}"
        ".report-summary-end{break-after:page;page-break-after:always}"
        ".report-summary-title+ul li{font-size:11pt;line-height:1.8;margin:0 0 3mm}"
        "h3{font-size:12.5pt;color:"
        f"{theme['ink']}"
        "}h4{font-size:11pt;color:"
        f"{theme['ink']}"
        "}h2,h3,h4{page-break-after:avoid;break-after:avoid;orphans:3;widows:3}"
        "p,li{orphans:3;widows:3}table{width:100%;table-layout:fixed;border-collapse:collapse;margin:10px 0}"
        "thead{display:table-header-group}tr{break-inside:avoid}"
        "th,td{border:0.6pt solid "
        f"{theme['grid']}"
        ";padding:5px 7px;text-align:left;overflow-wrap:anywhere;word-break:break-all}"
        "td{font-variant-numeric:tabular-nums}"
        "th{background:"
        f"{theme['surface']}"
        ";color:"
        f"{theme['primary']}"
        "}tr.report-row-even{background:#F9FAFB}.report-table-keep{break-inside:avoid}"
        ".report-unit{white-space:nowrap}p:has(+table){break-after:avoid;page-break-after:avoid}"
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
        ".report-signature{margin-top:12mm;text-align:right;break-inside:avoid;break-before:avoid}"
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


_PERIOD_ROLE_LABELS = {"current": "本期", "yoy": "同比基期", "mom": "环比基期"}


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
            # 期间按正文同一规则写成中文日期（2026-01至2026-12 → 2026年1月至12月）。
            periods = (_normalize_cjk_wording_text("、".join(covered["periods"]))
                       if covered["periods"] else "未登记")
            coverage.append(f"{covered['label']}（{periods}）")
        # 旧任务保存的范围是期间角色代码（current、yoy），读者可见时换成中文名称。
        roles = item["scope"].split("、")
        scope = ("、".join(_PERIOD_ROLE_LABELS[role] for role in roles)
                 if all(role in _PERIOD_ROLE_LABELS for role in roles) else item["scope"])
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
            f'<dd>范围：{html.escape(scope)}</dd>'
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


_AGGREGATION_LABELS = {
    "sum": "求和", "average": "平均", "min": "最小值", "max": "最大值",
    "count": "计数", "count_distinct": "去重计数",
}
_FORMULA = re.compile(
    r"^(?P<aggregation>sum|average|min|max|count|count_distinct)\((?P<field>[^()]+)\)"
    r"(?: WHERE (?P<where>.+))?$"
)


_FIXED_FORMULAS = {
    "(currentTotal-baselineTotal)/abs(baselineTotal)*100%": "变化率 =（本期合计 − 基期合计）÷ 基期合计绝对值 × 100%",
}
_RATIO_FORMULA = re.compile(r"^(?P<numerator>[^/;]+)/(?P<denominator>[^/;]+); difference=\1-\2$")


def readable_formula(formula: str) -> str:
    """冻结事实的计算口径（sum(revenue) WHERE 院区='东院'）改为读者可读的中文说明。"""
    formula = formula.strip()
    if formula in _FIXED_FORMULAS:
        return _FIXED_FORMULAS[formula]
    ratio = _RATIO_FORMULA.match(formula)
    if ratio is not None:
        return f"比率 = {ratio['numerator']} ÷ {ratio['denominator']}；差额 = {ratio['numerator']} − {ratio['denominator']}"
    # 两个聚合之比（sum(revenue)/sum(visits)）：分子分母分别写成中文聚合口径。
    parts = formula.split("/")
    if len(parts) == 2 and all(_FORMULA.match(part.strip()) and " WHERE " not in part for part in parts):
        return " ÷ ".join(readable_formula(part) for part in parts)
    match = _FORMULA.match(formula)
    if match is None:
        return formula
    text = f"{match['field']} {_AGGREGATION_LABELS[match['aggregation']]}"
    if match["where"]:
        conditions = [re.sub(r"^\s*([^=]+?)\s*=\s*'(.*)'\s*$", r"\1=\2", part)
                      for part in match["where"].split(" AND ")]
        text += f"（筛选：{'、'.join(conditions)}）"
    return text


def _readable_fact_value(value: Any, unit: str | None) -> str:
    """事实值按千分位、至多两位小数显示，与正文数值写法一致。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{value}{unit or ''}"
    number = Decimal(str(value))
    if number == number.to_integral_value():
        text = f"{number.to_integral_value():,f}"
    else:
        rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        text = f"{rounded:,f}" if rounded != 0 else f"{number:f}"
    return f"{text}{unit or ''}"


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
            value_text = "未登记" if value is None else _readable_fact_value(value, entry.get("unit"))
            rows.append(f"<dd>事实值：{html.escape(value_text)}</dd>")
            # 逐个列出的冻结期间按正文规则写成中文日期（2025-09 → 2025年9月）。
            joined = "、".join(entry.get("periods") or ())
            periods = _normalize_cjk_wording_text(joined) if joined else None
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
                methods.append(readable_formula(formula))
        else:
            methods.extend(readable_formula(method) for method in entry.get("methods") or ())
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
    "_join_cjk_soft_breaks",
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
