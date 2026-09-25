from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from markdown_it import MarkdownIt
from pydantic import ConfigDict, Field, field_validator, model_validator

from ..contract import StrictModel
from ..models import ReportingError
from .report_runtime.markdown import format_heading_label, normalize_report_markdown_strong_spacing

_LEADING_SECTION_HEADING = re.compile(
    r"\A#{1,2}[ \t]+(?P<title>[^\r\n]*?)(?:[ \t]+#+)?[ \t]*(?:\r?\n|\Z)"
)
_ATX_HEADING = re.compile(r"^(?P<prefix>#{1,6}[ \t]+)(?P<title>.*?)(?P<closing>[ \t]+#+)?[ \t]*$")
_MANUAL_HEADING_NUMBER = re.compile(r"^\d+(?:\.\d+)*(?:[.、．])?[ \t]+")
_MODEL_PROTOCOL_MARKER = re.compile(
    r"(?<!\\)\[\[/?(?:citation|section|analysis|table):[^\]\r\n]*\]\]"
)
_MODEL_REPAIR_COMMENT = re.compile(r"<!--\s*repair-warning:[\s\S]*?-->")
_MODEL_IMAGE = re.compile(
    r"(?<!\\)!\[(?P<alt>(?:\\.|[^\]\\\r\n])*)\]"
    r"\((?:<[^>\r\n]*>|(?:\\.|[^()\\\r\n]|\([^()\r\n]*\))*)\)"
)
_INLINE_CODE_SPAN = re.compile(r"(?P<delimiter>`+).*?(?P=delimiter)")
REPORT_HEADING_TITLE_MAX_LENGTH = 300


def _inline_heading_text(markdown: str) -> str:
    tokens = MarkdownIt("commonmark").parseInline(markdown)
    children = tokens[0].children if tokens else ()
    return "".join(
        str(item.content or "")
        for item in children or ()
        if item.type in {"text", "code_inline", "image"}
    ).strip()


class HeadingNumber(StrictModel):
    level: int = Field(ge=2, le=4)
    number: str = Field(pattern=r"^[1-9][0-9]*(?:\.[1-9][0-9]*){0,2}$")
    title: str = Field(min_length=1, max_length=REPORT_HEADING_TITLE_MAX_LENGTH)
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    anchor: str = Field(pattern=r"^report-(?:section|heading)-[a-z0-9_-]+$")


class ReportSectionDefinition(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    section_number: str = Field(alias="sectionNumber", pattern=r"^[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=200)
    protocol_marker: bool = Field(default=True, alias="protocolMarker")
    analysis_ids: tuple[str, ...] = Field(default=(), alias="analysisIds", max_length=2_000)

    @field_validator("analysis_ids")
    @classmethod
    def validate_analysis_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            not re.fullmatch(r"analysis_[0-9]{3,6}", item) for item in value
        ):
            raise ValueError("章节 analysisId 必须是服务端冻结且不重复的标识")
        return value


class ReportChartInput(StrictModel):
    """服务端归档后的图表输入；fileName 永远由服务端生成。"""

    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    file_name: str = Field(alias="fileName", min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)

    @field_validator("citation_ids")
    @classmethod
    def deduplicate_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))


class ReportChartRegistration(StrictModel):
    """模型只登记工作区源文件与展示元数据，不控制发布路径。"""

    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=512)
    renderer: Literal["matplotlib", "plotly"] = "matplotlib"
    interactive_path: str | None = Field(
        default=None, alias="interactivePath", min_length=1, max_length=512
    )
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    metric_codes: tuple[str, ...] = Field(alias="metricCodes", min_length=1, max_length=100)
    current_period: str = Field(alias="currentPeriod", min_length=1, max_length=200)
    comparison_period: str | None = Field(default=None, alias="comparisonPeriod", max_length=200)
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    source_dataset_id: str = Field(
        alias="sourceDatasetId",
        min_length=1,
        max_length=256,
        description="图表的主 Dataset；完整跨 Dataset 血缘由 citationIds 提供。",
    )
    aggregation_grain: str = Field(alias="aggregationGrain", min_length=1, max_length=128)
    comparability: Literal["strict", "reference_only"] = "strict"

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("图表源路径必须使用 POSIX 格式")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("图表源路径必须是安全工作区相对路径")
        return path.as_posix()

    @field_validator("interactive_path")
    @classmethod
    def validate_interactive_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = PurePosixPath(value)
        if (
            "\\" in value
            or path.is_absolute()
            or ".." in path.parts
            or value.endswith("/")
            or not value.endswith(".plotly.json")
        ):
            raise ValueError("interactivePath 必须是安全的 .plotly.json 工作区相对路径")
        return path.as_posix()

    @field_validator("citation_ids")
    @classmethod
    def deduplicate_citations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_comparability(self) -> ReportChartRegistration:
        if (self.renderer == "plotly") != (self.interactive_path is not None):
            raise ValueError("Plotly 图表必须且仅能声明 interactivePath")
        if self.comparison_type != "none" and not self.comparison_period:
            raise ValueError("比较图表必须声明 comparisonPeriod")
        if self.comparability == "reference_only":
            if self.comparison_type in {"yoy", "mom"}:
                raise ValueError("reference_only 图表不得声明严格同比或环比")
        return self


class ReportDraftBlock(StrictModel):
    block_id: str = Field(alias="blockId", min_length=1, max_length=128)
    markdown: str = Field(min_length=1, max_length=64_000)
    citation_ids: tuple[str, ...] = Field(default=(), alias="citationIds", max_length=100)
    chart_ids: tuple[str, ...] = Field(
        default=(),
        alias="chartIds",
        description="当前正文块实际展示的冻结图表 ID；使用图表时必须显式填写。",
    )
    claim_ids: tuple[str, ...] = Field(default=(), alias="claimIds", max_length=100)

    @field_validator("markdown")
    @classmethod
    def strip_markdown(cls, value: str) -> str:
        return value.strip()

    @field_validator("citation_ids", "chart_ids", "claim_ids")
    @classmethod
    def deduplicate_references(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value))


class ReportDraftSection(StrictModel):
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_unique_blocks(self) -> ReportDraftSection:
        block_ids = [item.block_id for item in self.blocks]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("同一章节的 blockId 不能重复")
        return self


class ReportDraft(StrictModel):
    # 标题由 Workflow 冻结，模型省略或回传不同文本都不改变最终渲染标题。
    title: str | None = Field(default=None, min_length=1, max_length=300)
    sections: tuple[ReportDraftSection, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_unique_sections(self) -> ReportDraft:
        codes = [item.section_code for item in self.sections]
        if len(codes) != len(set(codes)):
            raise ValueError("草稿章节不能重复")
        return self


class RenderedReportDraft(StrictModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        frozen=True,
        arbitrary_types_allowed=False,
    )

    markdown: str
    chart_paths: tuple[str, ...] = Field(alias="chartPaths")
    analysis_ids: tuple[str, ...] = Field(default=(), alias="analysisIds")
    section_numbers: tuple[str, ...] = Field(alias="sectionNumbers")
    heading_numbers: tuple[HeadingNumber, ...] = Field(alias="headingNumbers")
    warnings: tuple[dict[str, Any], ...] = ()
    auto_fixes: tuple[dict[str, Any], ...] = Field(default=(), alias="autoFixes")


_RESERVED_BODY_MARKERS = (
    "[[citation:",
    "[[section:",
    "[[analysis:",
    "[[table:",
    "[[/table:",
    "<!-- repair-warning:",
    "![",
)


def validate_report_body_markdown(markdown: str) -> None:
    """拒绝只能由服务端装配器生成的正文协议与图片语法。"""

    if any(marker in markdown for marker in _RESERVED_BODY_MARKERS):
        raise ReportingError(
            "report_draft_protocol_injection",
            "正文不得自行包含协议标记或图片语法；图表只能通过 chartIds 引用。",
        )


def _normalize_model_text(markdown: str) -> str:
    normalized = _MODEL_PROTOCOL_MARKER.sub("", markdown)
    # alt 文本通常包含模型对图表的业务解释，保留为普通文本；真实图片仍只由
    # chartIds 绑定并由服务端装配，模型提供的路径和 title 永远不会进入产物。
    return _MODEL_IMAGE.sub(lambda match: match.group("alt").strip(), normalized)


def _normalize_model_markdown_segment(markdown: str) -> str:
    """规范普通 Markdown 片段，完整保留行内代码中的协议示例。"""

    normalized: list[str] = []
    cursor = 0
    while cursor < len(markdown):
        code_span = _INLINE_CODE_SPAN.search(markdown, cursor)
        repair_comment = _MODEL_REPAIR_COMMENT.search(markdown, cursor)
        if code_span is None and repair_comment is None:
            normalized.append(_normalize_model_text(markdown[cursor:]))
            break
        if code_span is not None and (
            repair_comment is None or code_span.start() < repair_comment.start()
        ):
            normalized.append(_normalize_model_text(markdown[cursor : code_span.start()]))
            normalized.append(code_span[0])
            cursor = code_span.end()
            continue
        assert repair_comment is not None
        normalized.append(_normalize_model_text(markdown[cursor : repair_comment.start()]))
        cursor = repair_comment.end()
    return "".join(normalized)


def normalize_model_block_markdown(markdown: str) -> str:
    """移除模型误写的服务端协议语法，再交给正文协议校验。

    模型 block 只负责正文；citation、chart 和修复提示由服务端装配器生成。
    这里只处理完整且明确属于协议的 token，不放宽最终报告的严格校验，也不改写
    普通 Markdown 链接、代码示例或正文文字。
    """

    protected_lines: set[int] = set()
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type not in {"fence", "code_block"} or token.map is None:
            continue
        protected_lines.update(range(token.map[0], token.map[1]))

    # 代码内容属于报告正文语义，不能因为恰好包含协议示例而被静默改写。普通文本
    # 则按连续片段处理，使跨行 repair-warning comment 仍可完整、无损地移除。
    normalized: list[str] = []
    pending: list[str] = []
    for line_number, line in enumerate(markdown.splitlines(keepends=True)):
        if line_number not in protected_lines:
            pending.append(line)
            continue
        if pending:
            normalized.append(_normalize_model_markdown_segment("".join(pending)))
            pending.clear()
        normalized.append(line)
    if pending:
        normalized.append(_normalize_model_markdown_segment("".join(pending)))
    return "".join(normalized).strip()


def _safe_chart_name(
    file_name: str,
    *,
    report_parent: PurePosixPath,
) -> tuple[str, dict[str, Any] | None]:
    if "\\" in file_name:
        raise ReportingError("report_draft_chart_path_invalid", "图表路径必须使用 POSIX 格式。")
    raw = PurePosixPath(file_name)
    normalized_from: str | None = None
    if raw.is_absolute():
        expected_parent = PurePosixPath("/").joinpath(report_parent)
        if raw.parent != expected_parent:
            raise ReportingError(
                "report_draft_chart_path_invalid", "绝对图表路径必须精确位于当前报告目录。"
            )
        normalized_from = file_name
        raw = PurePosixPath(raw.name)
    if len(raw.parts) != 1 or raw.name in {"", ".", ".."}:
        raise ReportingError(
            "report_draft_chart_path_invalid", "图表只能使用当前报告目录内的文件名。"
        )
    if raw.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ReportingError("report_draft_chart_path_invalid", "图表只允许 PNG 或 JPEG。")
    auto_fix = (
        {
            "code": "chart_path_normalized",
            "from": normalized_from,
            "to": raw.as_posix(),
        }
        if normalized_from is not None
        else None
    )
    return raw.as_posix(), auto_fix


def _marker_lines(
    text: str,
    citation_ids: tuple[str, ...],
    analysis_ids: tuple[str, ...],
) -> str:
    markers = "".join(f"[[citation:{citation_id}]]" for citation_id in citation_ids)
    markers += "".join(f"[[analysis:{analysis_id}]]" for analysis_id in analysis_ids)
    return f"{text}{markers}"


def _strip_duplicate_section_heading(markdown: str, *, expected_title: str) -> tuple[str, bool]:
    match = _LEADING_SECTION_HEADING.match(markdown)
    submitted_title = (
        _MANUAL_HEADING_NUMBER.sub("", match.group("title").strip()).strip()
        if match is not None
        else ""
    )
    if match is None or submitted_title != expected_title.strip():
        return markdown, False
    # 正式章节标题以 effectiveProfile 为唯一事实来源，服务端会在所有正文块之前统一插入。
    # 这里只移除首块开头精确同名的 H1/H2，避免模型重复外层标题，同时保留其余子标题和正文。
    return markdown[match.end() :].lstrip("\r\n"), True


def _validated_block_headings(
    markdown: str,
    *,
    issue_path: str = "$.markdown",
) -> tuple[tuple[int, int, re.Match[str], str, str], ...]:
    """解析并校验最终装配支持的 CommonMark 标题语法。"""

    lines = markdown.splitlines(keepends=True)
    headings: list[tuple[int, int, re.Match[str], str, str]] = []
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.map is None:
            continue
        level = int(token.tag.removeprefix("h"))
        if level in {1, 2, 5, 6}:
            raise ReportingError(
                "report_draft_heading_level_invalid",
                "章节正文只允许 H3/H4；报告 H1 和章节 H2 由服务端生成。",
            )
        if level not in {3, 4}:
            continue
        line_index = token.map[0]
        raw_line = lines[line_index].rstrip("\r\n")
        match = _ATX_HEADING.fullmatch(raw_line)
        if match is None:
            raise ReportingError(
                "report_draft_heading_format_invalid", "章节正文标题必须使用 ATX Markdown 格式。"
            )
        markdown_title = _MANUAL_HEADING_NUMBER.sub("", match.group("title").strip()).strip()
        title = _inline_heading_text(markdown_title)
        if not markdown_title or not title:
            raise ReportingError("report_draft_heading_format_invalid", "章节正文标题不能为空。")
        if len(title) > REPORT_HEADING_TITLE_MAX_LENGTH:
            message = f"章节正文标题可见文本不得超过 {REPORT_HEADING_TITLE_MAX_LENGTH} 个字符。"
            issue = {
                "path": issue_path,
                "type": "heading_title_too_long",
                "message": message,
                "maxLength": REPORT_HEADING_TITLE_MAX_LENGTH,
                "actualLength": len(title),
            }
            raise ReportingError(
                "report_draft_heading_title_too_long",
                message,
                details={"issues": [issue]},
            )
        headings.append((level, line_index, match, markdown_title, title))
    return tuple(headings)


def validate_report_block_markdown(markdown: str) -> None:
    """校验单个正文块可独立判断的协议，跨块标题层级由章节校验负责。"""

    validate_report_body_markdown(markdown)
    _validated_block_headings(markdown)


def validate_report_draft_blocks(
    blocks: tuple[ReportDraftBlock, ...],
    *,
    expected_section_title: str | None = None,
) -> None:
    """在章节落盘前执行与最终装配一致的正文和标题协议校验。"""

    h3_count = 0
    for block_index, block in enumerate(blocks):
        markdown = block.markdown
        if block_index == 0 and expected_section_title is not None:
            markdown, _heading_removed = _strip_duplicate_section_heading(
                markdown,
                expected_title=expected_section_title,
            )
        validate_report_body_markdown(markdown)
        for level, _line_index, _match, _markdown_title, _title in _validated_block_headings(
            markdown,
            issue_path=f"$.blocks[{block_index}].markdown",
        ):
            if level == 3:
                h3_count += 1
            elif h3_count == 0:
                issue = {
                    "path": f"$.blocks[{block_index}].markdown",
                    "type": "heading_parent_missing",
                    "message": "H4 标题必须位于当前章节的 H3 标题之后。",
                }
                raise ReportingError(
                    "report_draft_heading_parent_missing",
                    issue["message"],
                    details={"issues": [issue]},
                )


def _number_block_headings(
    markdown: str,
    *,
    definition: ReportSectionDefinition,
    h3_count: int,
    h4_count: int,
) -> tuple[str, int, int, tuple[HeadingNumber, ...]]:
    """只改写 CommonMark 解析出的真实标题；围栏内容不参与标题协议。"""

    lines = markdown.splitlines(keepends=True)
    headings: list[HeadingNumber] = []
    replacements: dict[int, str] = {}
    for level, line_index, match, markdown_title, title in _validated_block_headings(markdown):
        raw_line = lines[line_index].rstrip("\r\n")
        if level == 3:
            h3_count += 1
            h4_count = 0
            number = f"{definition.section_number}.{h3_count}"
        else:
            if h3_count == 0:
                raise ReportingError(
                    "report_draft_heading_parent_missing", "H4 标题必须位于当前章节的 H3 标题之后。"
                )
            h4_count += 1
            number = f"{definition.section_number}.{h3_count}.{h4_count}"
        anchor = f"report-heading-{definition.code}-{number.replace('.', '-')}"
        headings.append(
            HeadingNumber(
                level=level,
                number=number,
                title=title,
                sectionCode=definition.code,
                anchor=anchor,
            )
        )
        ending = lines[line_index][len(raw_line) :]
        replacements[line_index] = (
            f"{match.group('prefix')}{number} {markdown_title}"
            f"{match.group('closing') or ''}{ending}"
        )
    for line_index, replacement in replacements.items():
        lines[line_index] = replacement
    return "".join(lines), h3_count, h4_count, tuple(headings)


@dataclass(frozen=True, slots=True)
class _ChartRenderPlan:
    """单张已引用图表的装配渲染计划：图片渲染位置与 citation 锚点命中情况。"""

    reference: tuple[int, int]
    render: tuple[int, int]
    render_block_id: str
    citation_anchor_missing: bool


def _chart_figure_markdown(chart: ReportChartInput, file_name: str) -> str:
    return (
        f'![{chart.alt_text}]({file_name} "{chart.title}")'
        + "".join(f"[[citation:{citation_id}]]" for citation_id in chart.citation_ids)
        + f"\n\n*图表：{chart.title}*"
    )


def _chart_citation_block_indexes(
    blocks: tuple[ReportDraftBlock, ...], chart_citation_ids: tuple[str, ...]
) -> tuple[int, ...]:
    """按章节顺序返回 citation 与图表存在交集的正文 block 索引。"""

    chart_citations = frozenset(chart_citation_ids)
    return tuple(
        index
        for index, block in enumerate(blocks)
        if chart_citations.intersection(block.citation_ids)
    )


_FENCE_LINE = re.compile(r"^[ \t]{0,3}(?P<fence>`{3,}|~{3,})")
_HEADING_LINE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]")
_LIST_ITEM_LINE = re.compile(r"^[ \t]{0,3}(?:[-*+]|\d{1,9}[.)])[ \t]")
_ASCII_TERM = re.compile(r"[A-Za-z0-9]{2,}")
_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")
# 图文匹配至少需要两个共享词元，避免“收入”“趋势”等单个泛化词把图表拉到无关段落。
_CHART_UNIT_MIN_SCORE = 2


def _block_units(markdown: str) -> list[str]:
    """把正文 block 切成可在其后插图的顶层单元。

    以空行分段；围栏代码内部不拆；仅含标题的段与后续正文合并，列表项段落合并为
    同一单元，避免图片落在标题与正文之间或打断列表。
    """

    paragraphs: list[list[str]] = [[]]
    fence: str | None = None
    for line in markdown.split("\n"):
        match = _FENCE_LINE.match(line)
        if fence is None and not line.strip():
            if paragraphs[-1]:
                paragraphs.append([])
            continue
        if match is not None:
            marker = match.group("fence")
            if fence is None:
                fence = marker[0] * len(marker)
            elif marker.startswith(fence):
                fence = None
        paragraphs[-1].append(line)
    units: list[str] = []
    pending_heading: list[str] = []
    previous_is_list = False
    for lines in (item for item in paragraphs if item):
        text = "\n".join(lines)
        if all(_HEADING_LINE.match(line) for line in lines):
            pending_heading.append(text)
            previous_is_list = False
            continue
        is_list = _LIST_ITEM_LINE.match(lines[0]) is not None or (
            previous_is_list and lines[0][:1] in {" ", "\t"}
        )
        if pending_heading:
            units.append("\n\n".join((*pending_heading, text)))
            pending_heading = []
        elif is_list and previous_is_list and units:
            units[-1] = f"{units[-1]}\n\n{text}"
        else:
            units.append(text)
        previous_is_list = is_list
    if pending_heading:
        units.append("\n\n".join(pending_heading))
    return units


def _chart_terms(text: str) -> frozenset[str]:
    terms = {item.lower() for item in _ASCII_TERM.findall(text)}
    for run in _CJK_RUN.findall(text):
        terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return frozenset(terms)


def _chart_unit_score(unit: str, chart: ReportChartInput) -> int:
    title = chart.title.strip()
    if title and title in unit:
        return 1000
    return len(_chart_terms(f"{chart.title} {chart.alt_text}") & _chart_terms(unit))


def _place_charts_in_units(
    units: list[str], charts: list[ReportChartInput]
) -> dict[int, list[str]]:
    """把同一 block 的多张图表分散到最能阐述它们的段落之后，避免图表堆叠在块尾。"""

    placements: dict[int, list[str]] = {}
    unmatched: list[str] = []
    for chart in charts:
        scores = [_chart_unit_score(unit, chart) for unit in units]
        qualified = [index for index, score in enumerate(scores) if score >= _CHART_UNIT_MIN_SCORE]
        if not qualified:
            unmatched.append(chart.chart_id)
            continue
        # 同分时优先尚未插图的单元，再取靠前位置，使多图沿正文自然分布。
        target = max(
            qualified,
            key=lambda index: (scores[index], index not in placements, -index),
        )
        placements.setdefault(target, []).append(chart.chart_id)
    # 无法按文字匹配的图表沿 block 均匀分布；单图时落在块尾，与历史行为一致。
    for position, chart_id in enumerate(unmatched):
        target = max(0, -(-(position + 1) * len(units) // len(unmatched)) - 1)
        placements.setdefault(target, []).append(chart_id)
    return placements


def assemble_report_markdown(
    draft: ReportDraft,
    *,
    expected_title: str,
    markdown_path: str,
    sections: tuple[ReportSectionDefinition, ...],
    citation_ids: tuple[str, ...],
    charts: tuple[ReportChartInput, ...] = (),
    require_table: bool = False,
) -> RenderedReportDraft:
    section_registry = {item.code: item for item in sections}
    if len(section_registry) != len(sections):
        raise ReportingError("report_draft_registry_invalid", "Workflow 章节注册表包含重复 code。")
    if tuple(item.section_number for item in sections) != tuple(
        str(index) for index in range(1, len(sections) + 1)
    ):
        raise ReportingError("report_draft_registry_invalid", "Workflow 一级章节编号必须连续。")
    draft_codes = tuple(item.section_code for item in draft.sections)
    if draft_codes != tuple(section_registry):
        raise ReportingError(
            "report_draft_section_mismatch", "草稿章节必须按 effectiveProfile 的顺序完整生成。"
        )

    citation_registry = set(citation_ids)
    if len(citation_registry) != len(citation_ids):
        raise ReportingError(
            "report_draft_registry_invalid", "Workflow citation 注册表包含重复 ID。"
        )
    chart_registry = {item.chart_id: item for item in charts}
    if len(chart_registry) != len(charts):
        raise ReportingError(
            "report_draft_registry_invalid", "Workflow 图表注册表包含重复 chartId。"
        )
    report_path = PurePosixPath(markdown_path)
    if report_path.is_absolute() or ".." in report_path.parts or "\\" in markdown_path:
        raise ReportingError("report_draft_path_invalid", "Markdown 路径必须是安全工作区相对路径。")

    normalized_charts: dict[str, tuple[ReportChartInput, str]] = {}
    auto_fixes: list[dict[str, Any]] = []
    for chart in charts:
        unknown = set(chart.citation_ids) - citation_registry
        if unknown:
            raise ReportingError("report_draft_citation_unknown", "图表引用了未注册 citation。")
        file_name, auto_fix = _safe_chart_name(
            chart.file_name,
            report_parent=report_path.parent,
        )
        if auto_fix is not None:
            auto_fixes.append(auto_fix)
        normalized_charts[chart.chart_id] = (chart, file_name)

    # 模型可能把 chartId 绑定到偏晚的正文 block，导致 PDF 图表滞后于对应结论。
    # 装配前先按 citation 交集预计算每张图的锚点：优先选同章节内第一个命中的
    # 正文 block，图片改在锚点渲染，原引用位置只保留 citation 标记；引用 block
    # 自身的 citation 子集硬校验不变，图表也不会跨章节移动。
    # 总览 block 往往引用全部 citation；若每张图都取首个命中 block，会把整章图表
    # 堆叠到同一位置。因此已被占用的锚点不再接收前移图表，且前移后的渲染顺序不得
    # 早于同章节上一张图，保持图表顺序与正文引用顺序一致。
    chart_plans: dict[str, _ChartRenderPlan] = {}
    occupied_locations: set[tuple[int, int]] = set()
    for section_index, section in enumerate(draft.sections):
        last_render_index = 0
        for block_index, block in enumerate(section.blocks):
            for chart_id in block.chart_ids:
                if chart_id in chart_plans or chart_id not in chart_registry:
                    continue
                matched_indexes = _chart_citation_block_indexes(
                    section.blocks, chart_registry[chart_id].citation_ids
                )
                # 引用 block 的 citation 必然覆盖图表 citation，因此命中 block 不会晚于
                # 引用位置；未注册 chartId 由渲染循环按原顺序硬校验拒绝。
                free_anchors = [
                    index
                    for index in matched_indexes
                    if last_render_index <= index < block_index
                    and (section_index, index) not in occupied_locations
                ]
                render_index = free_anchors[0] if free_anchors else block_index
                last_render_index = render_index
                occupied_locations.add((section_index, render_index))
                chart_plans[chart_id] = _ChartRenderPlan(
                    reference=(section_index, block_index),
                    render=(section_index, render_index),
                    render_block_id=section.blocks[render_index].block_id,
                    citation_anchor_missing=not any(
                        index != block_index for index in matched_indexes
                    ),
                )
    figures_by_render_location: dict[tuple[int, int], list[str]] = {}
    for chart_id, plan in chart_plans.items():
        figures_by_render_location.setdefault(plan.render, []).append(chart_id)

    referenced_chart_ids: list[str] = []
    rendered_chart_ids: set[str] = set()
    chart_warnings: list[dict[str, Any]] = []
    referenced_analysis_ids: list[str] = []
    heading_numbers: list[HeadingNumber] = []
    markdown_parts = [f"# {expected_title}"]
    for section_index, section in enumerate(draft.sections):
        definition = section_registry[section.section_code]
        # analysisIds 的唯一事实来源是用户批准后冻结的提纲。模型无需在每个正文块
        # 重复提交，也不能通过遗漏或替换 block.analysisIds 改变最终 manifest 绑定。
        referenced_analysis_ids.extend(definition.analysis_ids)
        heading_numbers.append(
            HeadingNumber(
                level=2,
                number=definition.section_number,
                title=definition.title,
                sectionCode=definition.code,
                anchor=f"report-section-{definition.code}",
            )
        )
        heading = _marker_lines(
            format_heading_label(
                level=2,
                number=definition.section_number,
                title=definition.title,
            ),
            (),
            definition.analysis_ids,
        )
        heading = f"## {heading}"
        markdown_parts.append(
            f"[[section:{definition.code}]]\n{heading}" if definition.protocol_marker else heading
        )
        h3_count = 0
        h4_count = 0
        for block_index, block in enumerate(section.blocks):
            block_markdown = normalize_report_markdown_strong_spacing(block.markdown)
            if block_markdown != block.markdown:
                auto_fixes.append(
                    {
                        "code": "markdown_strong_marker_normalized",
                        "sectionCode": definition.code,
                        "blockId": block.block_id,
                    }
                )
            if block_index == 0:
                block_markdown, heading_removed = _strip_duplicate_section_heading(
                    block_markdown,
                    expected_title=definition.title,
                )
                if heading_removed:
                    auto_fixes.append(
                        {
                            "code": "duplicate_section_heading_removed",
                            "sectionCode": definition.code,
                            "blockId": block.block_id,
                            "title": definition.title,
                        }
                    )
            validate_report_body_markdown(block_markdown)
            block_markdown, h3_count, h4_count, block_headings = _number_block_headings(
                block_markdown,
                definition=definition,
                h3_count=h3_count,
                h4_count=h4_count,
            )
            heading_numbers.extend(block_headings)
            unknown_citations = set(block.citation_ids) - citation_registry
            if unknown_citations:
                raise ReportingError("report_draft_citation_unknown", "草稿引用了未注册 citation。")
            unknown_charts = set(block.chart_ids) - set(chart_registry)
            if unknown_charts:
                raise ReportingError("report_draft_chart_unknown", "草稿引用了未注册图表。")
            block_text = _marker_lines(block_markdown, block.citation_ids, ())
            for chart_id in block.chart_ids:
                chart, _file_name = normalized_charts[chart_id]
                if chart_plans[chart_id].reference != (section_index, block_index):
                    # 重复引用不能再次写入 Markdown，避免同一图片在多个正文 block 中出现。
                    chart_warnings.append(
                        {
                            "code": "duplicate_chart_reference_excluded",
                            "chartId": chart_id,
                            "sectionCode": definition.code,
                            "blockId": block.block_id,
                            "message": "同一 chartId 已在前文渲染，重复引用已排除。",
                        }
                    )
                    continue
                if not set(chart.citation_ids).issubset(block.citation_ids):
                    raise ReportingError(
                        "report_draft_chart_citation_invalid",
                        f"图表 {chart_id} 的 citation（{', '.join(chart.citation_ids)}）必须属于"
                        f"正文块 {block.block_id} 的 citation 绑定"
                        f"（{', '.join(block.citation_ids)}）。",
                    )
                referenced_chart_ids.append(chart_id)
                plan = chart_plans[chart_id]
                if plan.render != plan.reference:
                    auto_fixes.append(
                        {
                            "code": "chart_reference_moved_to_anchor",
                            "chartId": chart_id,
                            "fromSectionCode": definition.code,
                            "fromBlockId": block.block_id,
                            "toSectionCode": definition.code,
                            "toBlockId": plan.render_block_id,
                        }
                    )
                elif plan.citation_anchor_missing:
                    chart_warnings.append(
                        {
                            "code": "chart_reference_anchor_missing",
                            "chartId": chart_id,
                            "sectionCode": definition.code,
                            "blockId": block.block_id,
                            "message": "图表 citation 未命中其他正文 block，保持原引用位置渲染。",
                        }
                    )
            block_figures = [
                chart_id
                for chart_id in figures_by_render_location.get((section_index, block_index), ())
                if chart_id not in rendered_chart_ids
            ]
            rendered_chart_ids.update(block_figures)
            units = _block_units(block_markdown) if block_figures else []
            placements = (
                _place_charts_in_units(
                    units, [normalized_charts[chart_id][0] for chart_id in block_figures]
                )
                if units
                else {}
            )
            if not placements or set(placements) == {len(units) - 1}:
                # 图表全部落在块尾时保留原始正文，不做任何重排。
                markdown_parts.append(block_text)
                ordered_figures = placements.get(len(units) - 1, block_figures)
                markdown_parts.extend(
                    _chart_figure_markdown(*normalized_charts[chart_id])
                    for chart_id in ordered_figures
                )
            else:
                for unit_index, unit in enumerate(units):
                    if unit_index == len(units) - 1:
                        unit = _marker_lines(unit, block.citation_ids, ())
                    markdown_parts.append(unit)
                    markdown_parts.extend(
                        _chart_figure_markdown(*normalized_charts[chart_id])
                        for chart_id in placements.get(unit_index, ())
                    )
                auto_fixes.append(
                    {
                        "code": "chart_placed_within_block",
                        "sectionCode": definition.code,
                        "blockId": block.block_id,
                        "placements": {
                            chart_id: unit_index + 1
                            for unit_index, chart_ids in sorted(placements.items())
                            for chart_id in chart_ids
                        },
                    }
                )

    if require_table and not any(
        "|" in block.markdown for section in draft.sections for block in section.blocks
    ):
        raise ReportingError("report_draft_table_missing", "当前报告至少需要一个 Markdown 表格。")

    unused = sorted(set(chart_registry) - set(referenced_chart_ids))
    warnings: list[dict[str, Any]] = list(chart_warnings)
    if unused:
        warnings.append(
            {
                "code": "unused_chart_excluded",
                "chartIds": unused,
                "message": "未被正文引用的图表已从发布包排除。",
            }
        )
    chart_paths = tuple(
        report_path.parent.joinpath(normalized_charts[chart_id][1]).as_posix()
        for chart_id in dict.fromkeys(referenced_chart_ids)
    )
    return RenderedReportDraft(
        markdown="\n\n".join(markdown_parts) + "\n",
        chartPaths=chart_paths,
        analysisIds=tuple(referenced_analysis_ids),
        sectionNumbers=tuple(item.section_number for item in sections),
        headingNumbers=tuple(heading_numbers),
        warnings=tuple(warnings),
        autoFixes=tuple(auto_fixes),
    )
