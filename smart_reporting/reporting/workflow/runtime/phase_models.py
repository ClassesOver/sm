"""固定 Reporting 阶段的模型生成契约。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from loguru import logger
from markdown_it import MarkdownIt
from pydantic import ConfigDict, Field, RootModel, TypeAdapter, field_validator, model_validator

from ...contract import StrictModel
from ...delivery.draft_v1 import (
    _ATX_HEADING,
    _MANUAL_HEADING_NUMBER,
    REPORT_HEADING_TITLE_MAX_LENGTH,
    ReportDraftBlock,
    _inline_heading_text,
    normalize_model_block_markdown,
    validate_report_block_markdown,
)
from ...models import ReportingError
from ..checkpoint import FileIdentity, SectionClaimSubmission

MAX_SECTION_BLOCK_MARKDOWN_CHARS = 8_000
_CJK_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SUBORDINATE_HEADING_RE = re.compile(r"^(?P<indent> {0,3})#{5,6}(?P<spacing>[ \t]+)")
_RUNON_HEADING_BREAK_RE = re.compile(r"[。！？；：]")


def _normalize_subordinate_heading_levels(markdown: str) -> str:
    """将模型过度细分的 H5/H6 提升到正文协议允许的 H4。"""

    lines = markdown.splitlines(keepends=True)
    normalized_count = 0
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.tag not in {"h5", "h6"} or token.map is None:
            continue
        line_index = token.map[0]
        normalized, replacements = _SUBORDINATE_HEADING_RE.subn(
            r"\g<indent>####\g<spacing>",
            lines[line_index],
            count=1,
        )
        if replacements:
            lines[line_index] = normalized
            normalized_count += 1
    if normalized_count:
        logger.bind(normalized_heading_count=normalized_count).warning(
            "report_section_heading_level_normalized"
        )
    return "".join(lines)


def _normalize_runon_heading_lines(markdown: str) -> str:
    """把正文混入标题行的超长标题按首个句末标点拆分为短标题和正文段。

    标题行契约要求可见文本不超过上限且不得包含正文；弱模型常把标题和整段正文
    写在同一行，导致纠错反馈无法自愈。句末标点（。！？；：）不可能出现在合规
    短标题内，因此按首个句末标点拆分是内容零丢失的确定性收敛；标点前缀仍超
    上限或没有句末标点时不猜测拆分点，保留原值由严格校验失败关闭。
    """

    lines = markdown.splitlines(keepends=True)
    normalized_count = 0
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.map is None or token.tag not in {"h3", "h4"}:
            continue
        line_index = token.map[0]
        if line_index >= len(lines):
            continue
        raw_line = lines[line_index].rstrip("\r\n")
        match = _ATX_HEADING.fullmatch(raw_line)
        if match is None:
            continue
        title = match.group("title").strip()
        visible_title = _inline_heading_text(_MANUAL_HEADING_NUMBER.sub("", title).strip())
        if len(visible_title) <= REPORT_HEADING_TITLE_MAX_LENGTH:
            continue
        inline_tokens = MarkdownIt("commonmark").parseInline(title)
        inline_children = inline_tokens[0].children if inline_tokens else ()
        if any(item.type != "text" for item in inline_children or ()):
            # 不在成对的行内 Markdown 中间拆分，交给严格校验纠错。
            continue
        break_match = _RUNON_HEADING_BREAK_RE.search(title)
        if break_match is None:
            continue
        prefix = title[: break_match.start()].strip()
        visible_prefix = (
            _inline_heading_text(_MANUAL_HEADING_NUMBER.sub("", prefix).strip()) if prefix else ""
        )
        if not visible_prefix or len(visible_prefix) > REPORT_HEADING_TITLE_MAX_LENGTH:
            continue
        remainder = title[break_match.end() :].strip()
        marker = "#" * int(token.tag.removeprefix("h"))
        ending = lines[line_index][len(raw_line) :]
        rebuilt = (
            f"{marker} {prefix}\n\n{remainder}{ending}"
            if remainder
            else f"{marker} {prefix}{ending}"
        )
        lines[line_index] = rebuilt
        normalized_count += 1
    if normalized_count:
        logger.bind(normalized_heading_count=normalized_count).warning(
            "report_section_runon_heading_normalized"
        )
    return "".join(lines)


_OVERLONG_HEADING_PREVIEW_CHARS = 50


def _overlong_heading_diagnostics(markdown: str) -> tuple[dict[str, Any], ...]:
    """定位可见文本超限的 H3/H4 标题行，为结构化纠错反馈提供可行动事实。

    与 _normalize_runon_heading_lines 使用同一长度判定：可按句末标点拆分修复的
    超长标题行已在 before 校验阶段收敛，这里报告的必然是归一化放弃修复、
    需要模型按反馈缩短的原始超长标题。
    """

    lines = markdown.splitlines(keepends=True)
    diagnostics: list[dict[str, Any]] = []
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "heading_open" or token.map is None or token.tag not in {"h3", "h4"}:
            continue
        line_index = token.map[0]
        if line_index >= len(lines):
            continue
        match = _ATX_HEADING.fullmatch(lines[line_index].rstrip("\r\n"))
        if match is None:
            continue
        visible = _inline_heading_text(
            _MANUAL_HEADING_NUMBER.sub("", match.group("title").strip()).strip()
        )
        if len(visible) > REPORT_HEADING_TITLE_MAX_LENGTH:
            preview = visible[:_OVERLONG_HEADING_PREVIEW_CHARS]
            if len(visible) > _OVERLONG_HEADING_PREVIEW_CHARS:
                preview = f"{preview}…"
            diagnostics.append(
                {
                    "lineNumber": line_index + 1,
                    "actualLength": len(visible),
                    "preview": preview,
                }
            )
    return tuple(diagnostics)


def _block_validation_feedback(markdown: str, error: ReportingError) -> str:
    """把正文块协议错误转成模型可定位、可修复的纠错消息。

    结构化执行器回灌 issues 时只保留 path/type/message（validation 上下文与
    input 都会被裁剪）。消息是唯一能送达模型的通道，因此把行号、实际长度和
    具体修正动作并入消息；其他错误码沿用原始 message，行为不变。
    """

    message = str(error)
    if error.code != "report_draft_heading_title_too_long":
        return message
    segments = [message]
    for item in _overlong_heading_diagnostics(markdown):
        segments.append(
            f"第 {item['lineNumber']} 行标题可见文本 {item['actualLength']} 个字符"
            f"（上限 {REPORT_HEADING_TITLE_MAX_LENGTH}）：『{item['preview']}』。"
        )
    segments.append(
        "请缩短超限标题行的可见文本；若标题行混入了正文，"
        "改写为『### 短标题』后接空行，正文另起段落。"
    )
    return "".join(segments)


class ChartDraft(StrictModel):
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=1024)
    title: str = Field(
        min_length=1,
        max_length=200,
        description="图表用户可见标题，必须使用简体中文表达业务含义。",
    )
    alt_text: str = Field(
        alias="altText",
        min_length=1,
        max_length=200,
        description="图表用户可见图注，必须使用简体中文说明图表内容。",
    )
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    metric_codes: tuple[str, ...] = Field(alias="metricCodes", min_length=1, max_length=100)
    current_period: str = Field(alias="currentPeriod", min_length=1, max_length=200)
    comparison_period: str | None = Field(default=None, alias="comparisonPeriod", max_length=200)
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    source_dataset_id: str = Field(alias="sourceDatasetId", min_length=1, max_length=256)
    aggregation_grain: str = Field(alias="aggregationGrain", min_length=1, max_length=128)
    comparability: Literal["strict", "reference_only"] = "strict"

    @field_validator("title", "alt_text")
    @classmethod
    def validate_chinese_display_text(cls, value: str) -> str:
        # 这里只检查用户可见元数据至少包含汉字；简繁体词汇、业务术语和图片内
        # 的坐标轴/图例由 Agent 指令与绘图主题负责，不能用正则或 OCR 可靠判定。
        if not _CJK_TEXT_RE.search(value):
            raise ValueError("图表 title 和 altText 必须包含简体中文用户可见文字")
        return value

    @model_validator(mode="before")
    @classmethod
    def normalize_reference_comparison(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        comparison_type = value.get("comparisonType", value.get("comparison_type"))
        if value.get("comparability") != "reference_only" or comparison_type not in {
            "yoy",
            "mom",
        }:
            return value
        # reference_only 仍可展示两个期间，但不能把不可严格比较的数据标记为同比或
        # 环比。转换为普通期间对比只收窄结论强度，不改写数值、期间或证据绑定。
        normalized = dict(value)
        key = "comparisonType" if "comparisonType" in value else "comparison_type"
        normalized[key] = "period"
        return normalized

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("图表源路径必须是安全工作区相对路径")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("图表源文件必须是 PNG 或 JPEG")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_comparison(self) -> ChartDraft:
        if self.comparison_type != "none" and not self.comparison_period:
            raise ValueError("比较图表必须声明 comparisonPeriod")
        if self.comparability == "reference_only" and self.comparison_type in {"yoy", "mom"}:
            raise ValueError("reference_only 图表不得声明严格同比或环比")
        if len(self.citation_ids) != len(set(self.citation_ids)):
            raise ValueError("图表 citationIds 不能重复")
        return self


class VisualizationPlanDraft(StrictModel):
    charts: tuple[ChartDraft, ...] = Field(max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_unique_charts(self) -> VisualizationPlanDraft:
        chart_ids = [item.chart_id for item in self.charts]
        paths = [item.source_path for item in self.charts]
        if len(chart_ids) != len(set(chart_ids)) or len(paths) != len(set(paths)):
            raise ValueError("图表 ID 和输出路径不能重复")
        return self


class SectionEvidenceFile(StrictModel):
    identity: FileIdentity
    content: str = Field(min_length=1, max_length=10 * 1024 * 1024)


class SectionEvidenceBundle(StrictModel):
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    files: tuple[SectionEvidenceFile, ...] = Field(min_length=1, max_length=200)
    fact_summaries: tuple[str, ...] = Field(default=(), alias="factSummaries", max_length=200)


class AnalysisReworkDecision(StrictModel):
    kind: Literal["rework"] = "rework"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    missing_evidence: tuple[str, ...] = Field(alias="missingEvidence", min_length=1, max_length=100)


class SectionBlockPlan(StrictModel):
    block_id: str = Field(alias="blockId", min_length=1, max_length=128)
    objective: str = Field(min_length=1, max_length=2000)
    claim_ids: tuple[str, ...] = Field(alias="claimIds", min_length=1, max_length=100)

    @field_validator("claim_ids")
    @classmethod
    def validate_unique_claim_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("block 规划的 claimIds 不能重复")
        return value


class RenderSectionPlan(StrictModel):
    kind: Literal["render"] = "render"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[SectionBlockPlan, ...] = Field(min_length=1, max_length=12)
    claims: tuple[SectionClaimSubmission, ...] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_references(self) -> RenderSectionPlan:
        block_ids = [item.block_id for item in self.blocks]
        claim_ids = [item.claim_id for item in self.claims]
        if len(block_ids) != len(set(block_ids)):
            raise ValueError("章节规划 blockId 不能重复")
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("章节规划 claimId 不能重复")
        referenced = {claim_id for block in self.blocks for claim_id in block.claim_ids}
        known = set(claim_ids)
        if referenced != known:
            raise ValueError("章节规划的每个 claim 必须存在且由至少一个 block 引用")
        return self


SectionPlanDecision = Annotated[
    RenderSectionPlan | AnalysisReworkDecision,
    Field(discriminator="kind"),
]


class SectionPlanOutput(RootModel[SectionPlanDecision]):
    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_single_decision_wrapper(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        if len(value) == 1:
            kind, payload = next(iter(value.items()))
            if kind in {"render", "rework"} and isinstance(payload, Mapping):
                declared_kind = payload.get("kind")
                if declared_kind in {None, kind}:
                    value = {**payload, "kind": kind}
        if value.get("kind") != "render":
            return value

        normalized = dict(value)
        for field in ("blocks", "claims"):
            items = value.get(field)
            if not isinstance(items, list | tuple):
                continue
            decoded_items: list[Any] = []
            changed = False
            for item in items:
                decoded = item
                if isinstance(item, str):
                    try:
                        candidate = json.loads(item)
                    except json.JSONDecodeError:
                        pass
                    else:
                        if isinstance(candidate, Mapping):
                            decoded = candidate
                            changed = True
                decoded_items.append(decoded)
            if changed:
                normalized[field] = (
                    tuple(decoded_items) if isinstance(items, tuple) else decoded_items
                )
        return normalized


class SectionBlockContent(StrictModel):
    markdown: str = Field(min_length=1, max_length=MAX_SECTION_BLOCK_MARKDOWN_CHARS)

    @field_validator("markdown", mode="before")
    @classmethod
    def normalize_protocol_residuals(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        markdown = normalize_model_block_markdown(value)
        if not markdown:
            raise ValueError("章节正文清洗后不能为空。")
        # 确定性清洗必须先于 Pydantic 长度和业务校验。否则大段内部 repair comment
        # 会让本可接受的正文先触发 max_length，并错误消耗模型业务纠错额度。
        markdown = _normalize_subordinate_heading_levels(markdown)
        return _normalize_runon_heading_lines(markdown)

    @field_validator("markdown")
    @classmethod
    def validate_markdown(cls, markdown: str) -> str:
        try:
            # 单块生成阶段没有前序块上下文，因此这里只拒绝可独立判定的协议错误；
            # H4 的父级关系仍由整章提交校验跨 block 判定。
            validate_report_block_markdown(markdown)
        except ReportingError as error:
            raise ValueError(_block_validation_feedback(markdown, error)) from error
        return markdown


class RenderSectionDecision(StrictModel):
    kind: Literal["render"] = "render"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)
    claims: tuple[SectionClaimSubmission, ...] = Field(min_length=1, max_length=500)


SectionDecision = Annotated[
    RenderSectionDecision | AnalysisReworkDecision,
    Field(discriminator="kind"),
]
SectionDecisionAdapter: TypeAdapter[SectionDecision] = TypeAdapter(SectionDecision)


class SectionDecisionOutput(RootModel[SectionDecision]):
    """Agno output_schema 只接受 BaseModel 类型，根 JSON 仍保持原判别联合形状。"""

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def normalize_single_decision_wrapper(cls, value: Any) -> Any:
        """展开模型偶发生成的单键决策包装，随后仍由原判别联合完整校验。"""

        if not isinstance(value, Mapping) or len(value) != 1:
            return value
        kind, payload = next(iter(value.items()))
        if kind not in {"render", "rework"} or not isinstance(payload, Mapping):
            return value
        declared_kind = payload.get("kind")
        if declared_kind not in {None, kind}:
            return value
        return {**payload, "kind": kind}


__all__ = [
    "AnalysisReworkDecision",
    "ChartDraft",
    "RenderSectionDecision",
    "RenderSectionPlan",
    "SectionBlockContent",
    "SectionBlockPlan",
    "SectionDecision",
    "SectionDecisionAdapter",
    "SectionDecisionOutput",
    "SectionEvidenceBundle",
    "SectionEvidenceFile",
    "SectionPlanOutput",
    "VisualizationPlanDraft",
]
