"""正文复核：可读性（长句、数值堆砌、重复、段落、小标题与半句）。"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from decimal import Decimal

from ..delivery.report_runtime.markdown import CJK_ENUMERATION_LINE
from .markdown_body import trace_body
from .review_common import _VALUE


def _prose_lines(markdown: str) -> list[str]:
    """读者可见的正文行：去协议标记与加粗，跳过代码块、表格、标题和图片行。

    服务端表格的 [[table:…]] 标记紧贴表头、不隔空行，必须逐行判断而不能按段首判断。
    """
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = re.sub(r"\[\[[^\]\r\n]+\]\]", "", raw).replace("**", "").strip()
        if not line or line.startswith(("|", "#", "![")):
            continue
        lines.append(line)
    return lines


def _comparable_sentences(markdown: str) -> dict[str, str]:
    """按句归一化，保留正负号与区间符号，避免不同事实被误判为重复。"""
    sentences: dict[str, str] = {}
    for sentence in (part for line in _prose_lines(markdown) for part in re.split(r"[。！？；]", line)):
        normalized = re.sub(r"[\s，、,:：（）()“”\"'·]", "", sentence)
        # 过短的句子（过渡语、标签）重复属正常写法，不计。
        if len(normalized) >= 12:
            sentences.setdefault(normalized, sentence.strip())
    return sentences


def _displayed(markdown: str, catalog: Mapping[str, str] | None) -> str:
    """把 {{value:…}}、{{calc:…}} 占位换成显示值，使度量与比较基于读者所见文本。"""
    # 复用 CommonMark 解析，正确处理长围栏、波浪线及缩进代码；行内代码仍是可见正文。
    markdown = trace_body(markdown, mask_inline_code=False)
    if catalog is None:
        return markdown
    # 计算引用在落盘时才求值；度量时用中性占位，不当作待核实。
    return re.sub(
        r"\{\{(?:value|calc):[^{}\r\n]+\}\}",
        lambda match: catalog.get(match[0], "计算值" if match[0].startswith("{{calc:") else "数值待核实"),
        markdown,
    )


def repeated_sentence_warnings(
    markdown: str, earlier_blocks: Iterable[str], catalog: Mapping[str, str] | None = None,
) -> list[str]:
    """当前 block 与本章已写 block 逐句完全重复时给出软告警，交由纠错轮次改写。

    已采纳 block 的数值已渲染，当前 block 仍是占位，故先按冻结目录换成显示值再比较。
    """
    markdown = _displayed(markdown, catalog)
    earlier: set[str] = set()
    for block in earlier_blocks:
        # 整章生成时前文 block 同样仍是占位；已渲染文本替换后不变。
        earlier.update(_comparable_sentences(_displayed(block, catalog)))
    return [
        f"与本章前文重复：{original}。请删除重复表述，或补充前文未写的事实与解读。"
        for normalized, original in _comparable_sentences(markdown).items()
        if normalized in earlier
    ]


def earlier_section_sentences(sections: Iterable[tuple[str, str]]) -> dict[str, str]:
    """报告中排在前面、已完成章节的句子 → 章节名；已完成章节的数值已渲染，按读者所见比较。"""
    owners: dict[str, str] = {}
    for title, markdown in sections:
        for normalized in _comparable_sentences(_displayed(markdown, None)):
            owners.setdefault(normalized, title)
    return owners


def repeated_section_warnings(
    markdown: str, earlier: Mapping[str, str], catalog: Mapping[str, str] | None = None,
) -> list[str]:
    """当前 block 与前面章节逐句完全重复时给出软告警（附章节名），交由纠错轮次改写。

    章节默认串行生成，各章只看得到自己的证据：总量、口径说明常在多章原样复述。
    """
    if not earlier:
        return []
    return [
        f"与前面“{earlier[normalized]}”一章重复：{original}。请删除，或改为简要引用该章结论，只写本章新增的事实与解读。"
        for normalized, original in _comparable_sentences(_displayed(markdown, catalog)).items()
        if normalized in earlier
    ]


_READABLE_SENTENCE_CHARS = 150


_READABLE_SENTENCE_VALUES = 5


def readability_warnings(markdown: str, catalog: Mapping[str, str] | None = None) -> list[str]:
    """长句与数值堆砌的软告警：只看正文段落，不看表格、标题和代码。

    正文仍含 {{value:…}} 占位时按冻结目录换成显示值再度量，与读者所见一致。
    """
    markdown = _displayed(markdown, catalog)
    warnings: list[str] = []
    for line in _prose_lines(markdown):
        # 百万以上的元或人次直接书写难以阅读；括号内紧随万元/亿元/万人次的原始值是规范写法。
        for match in re.finditer(r"(?<![\d.,（(])([+-]?\d{1,3}(?:,\d{3}){2,}|\d{7,})(?:\.\d+)?\s*(元|人次)(?!\s*[）)])", line):
            amount = Decimal(match[1].replace(",", ""))
            if abs(amount) < 1_000_000:
                continue
            if match[2] == "人次":
                warnings.append(f"人次位数过多：{match[0]}。建议改用万人次占位表述，需保留原始人次时写在括号内。")
                continue
            suggested = "亿元" if abs(amount) >= 100_000_000 else "万元"
            warnings.append(f"金额位数过多：{match[0]}。建议改用{suggested}占位表述，需保留原始元值时写在括号内。")
        for sentence in re.split(r"[。！？；]", line):
            sentence = sentence.strip()
            values = len(_VALUE.findall(sentence))
            if values > _READABLE_SENTENCE_VALUES:
                warnings.append(f"单句数值过多（{values} 个）：{sentence[:40]}……请拆分为多句，或改用表格呈现明细。")
            elif len(sentence) >= _READABLE_SENTENCE_CHARS:
                warnings.append(f"句子过长（{len(sentence)} 字）：{sentence[:40]}……请拆分为结论句和支撑句。")
    warnings.extend(_heading_readability_warnings(markdown))
    warnings.extend(_paragraph_length_warnings(markdown))
    warnings.extend(_incomplete_paragraph_warnings(markdown))
    return warnings


_HEDGE = re.compile(r"待核实|待复核|待确认")


def prose_hedge_warnings(markdown: str) -> list[str]:
    """模型自写的“待核实/待复核/待确认”：只用于写作复核，按 block 汇总一条软告警。

    数据限制只在改变结论读法时紧跟结论说明影响；服务端渲染时插入的占位不经过这里，
    已发布正文的质量扫描也不调用本函数。
    """
    # 引用占位与代码块不是模型写给读者的提示。
    text = re.sub(r"\{\{[^{}\r\n]*\}\}", "", markdown)
    text = re.sub(r"(?ms)^\s*```.*?^\s*```", "", text)
    hits = [line.strip() for line in text.splitlines() if _HEDGE.search(line)]
    if not hits:
        return []
    example = re.sub(r"\[\[[^\]\r\n]+\]\]", "", hits[0])[:40]
    return [
        f"正文写了待核实类提示（{len(hits)} 处，如：{example}……）：数据限制只在改变某项结论的读法时，"
        "紧跟该结论用一句话说明影响和处理（如“三级科室归属缺失较多，科室排名仅作参考”），不复述记录条数、"
        "最小值等明细，不写“待核实”“待复核”“待确认”，不单设口径限制段落；与本章结论无关的限制删去。"
    ]


_READABLE_PARAGRAPH_CHARS = 360


def _paragraph_length_warnings(markdown: str) -> list[str]:
    """单个正文段落过长时提示拆分（软告警）；表格、列表、标题、代码与图片不计。

    逐句长度合格的段落仍可能堆成一整屏文字，PDF 中难以定位结论。
    """
    warnings: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        text = "".join(paragraph)
        if len(text) > _READABLE_PARAGRAPH_CHARS:
            warnings.append(
                f"段落过长（{len(text)} 字）：{text[:30]}……请按“结论—证据—建议”拆分为多个段落。"
            )
        paragraph.clear()

    for raw in markdown.splitlines():
        stripped = raw.strip()
        line = re.sub(r"\[\[[^\]\r\n]+\]\]", "", stripped).replace("**", "").strip()
        if (not line or line.startswith(("|", "#", "![", ">"))
                or _LIST_OR_TABLE_START.match(line)):
            flush()
            continue
        paragraph.append(line)
    flush()
    return warnings


_READABLE_HEADING_CHARS = 24


def _heading_readability_warnings(markdown: str) -> list[str]:
    """小标题写成整句（过长或含句号、分号）时提示压缩为主题短语（软告警）。

    小标题进入目录与 PDF 书签，结论和数值应写进正文；括号内的单位说明不计入长度。
    """
    warnings: list[str] = []
    for raw in markdown.splitlines():
        match = re.match(r"^#{3,4}[ \t]+(.+?)[ \t#]*$", raw)
        if match is None:
            continue
        title = re.sub(r"\[\[[^\]\r\n]+\]\]", "", match[1]).replace("**", "").strip()
        visible = re.sub(r"[（(][^（）()]*[）)]", "", title).strip()
        if len(visible) > _READABLE_HEADING_CHARS or re.search(r"[。；;]", visible.rstrip("。；;")):
            warnings.append(
                f"小标题过长或写成整句（{len(visible)} 字）：{title[:40]}。"
                f"请压缩为不超过 {_READABLE_HEADING_CHARS} 字的主题短语，结论与数值写进正文。"
            )
    return warnings


_PROTOCOL_MARKER = re.compile(r"\[\[[^\]\r\n]+\]\]")


_LIST_OR_TABLE_START = re.compile(r"^(?:[-*+]\s|\d{1,3}[.)、]\s?|\|)")


# 段落停在逗号、顿号、分号或连接/谓语成分上，读者看到的是半句话（输出截断或模型漏写）。
_DANGLING_TAIL = re.compile(
    r"(?:[，、；;,]|分别为|包括|以及|达到|约为|由于|因为|其中|从而|并且|呈|为|是|和|与|及|较|比|达|即|但|而|则|对|在|于)$"
)


def _incomplete_paragraph_warnings(markdown: str) -> list[str]:
    """正文段落以半句结尾的软告警；列表、表格、标题、图片和代码不计。

    以冒号收尾、后接列表/表格/图片的引导句是正常写法。
    """
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(stripped)
    if current:
        paragraphs.append(current)

    def visible(line: str) -> str:
        return _PROTOCOL_MARKER.sub("", line).replace("**", "").strip()

    warnings: list[str] = []
    for index, lines in enumerate(paragraphs):
        first = visible(lines[0])
        # 列表与“（1）”“一是”“第一，”等中文条目以分号收尾是正常写法，不算半句话。
        if (not first or first.startswith(("#", "|", "![", ">")) or _LIST_OR_TABLE_START.match(first)
                or CJK_ENUMERATION_LINE.match(first)):
            continue
        text = visible(lines[-1])
        if not text:
            continue
        if text.endswith(("：", ":")):
            following = paragraphs[index + 1][0] if index + 1 < len(paragraphs) else ""
            if (following.startswith(("[[table:", "|", "!["))
                    or _LIST_OR_TABLE_START.match(visible(following))
                    or CJK_ENUMERATION_LINE.match(visible(following))):
                # “如下：”后接列表、表格、图片或“（1）”“一是”“第一，”等中文条目是完整的引导句。
                continue
        elif not _DANGLING_TAIL.search(text):
            continue
        warnings.append(f"段落未写完：「……{text[-20:]}」。请补全这句话，或删去未完成的半句。")
    return warnings
