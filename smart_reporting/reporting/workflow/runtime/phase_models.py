"""固定 Reporting 阶段的模型生成契约。"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from loguru import logger
from markdown_it import MarkdownIt
from pydantic import ConfigDict, Field, RootModel, TypeAdapter, field_validator, model_validator

from ...contract import StrictModel
from ...delivery.draft_v1 import (
    ReportDraftBlock,
    normalize_model_block_markdown,
    validate_report_block_markdown,
)
from ...models import ReportingError
from ..checkpoint import FileIdentity, SectionClaimSubmission

MAX_VISUALIZATION_SOURCE_BYTES = 262_144
MAX_SECTION_BLOCK_MARKDOWN_CHARS = 8_000
_CJK_TEXT_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_SUBORDINATE_HEADING_RE = re.compile(r"^(?P<indent> {0,3})#{5,6}(?P<spacing>[ \t]+)")


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


class VisualizationScriptDraft(StrictModel):
    script_path: str = Field(alias="scriptPath", min_length=1, max_length=1024)
    python_source: str = Field(
        alias="pythonSource", min_length=1, max_length=MAX_VISUALIZATION_SOURCE_BYTES
    )
    charts: tuple[ChartDraft, ...] = Field(min_length=1, max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("script_path")
    @classmethod
    def validate_script_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            raise ValueError("脚本路径必须是安全工作区相对 Python 文件")
        return path.as_posix()

    @field_validator("python_source")
    @classmethod
    def validate_python_source(cls, value: str) -> str:
        try:
            tree = ast.parse(value, filename="<visualization>")
            compile(tree, "<visualization>", "exec")
        except SyntaxError as error:
            raise ValueError("pythonSource 必须是合法 Python 源码") from error

        # 固定 Workflow 独占脚本写入、执行与图表提交。模型源码只负责生成图片；
        # 若把编排工具或 JSON 常量写进脚本，最早也只能在远端执行时失败，还会
        # 消耗一次脚本 mutation。这里在任何副作用前拒绝并交给结构化纠错重生成。
        forbidden_names = {
            "__file__",
            "apply_analysis_patch",
            "null",
            "run_python_script",
            "submit_visualization_charts",
            "true",
            "false",
        }
        used_forbidden = sorted(
            {
                node.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id in forbidden_names
            }
        )
        if used_forbidden:
            raise ValueError(
                "pythonSource 只能生成签发图表，不得使用编排工具、__file__ 或 JSON 常量"
            )
        return value

    @model_validator(mode="after")
    def validate_unique_charts(self) -> VisualizationScriptDraft:
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
        if not isinstance(value, Mapping) or len(value) != 1:
            return value
        kind, payload = next(iter(value.items()))
        if kind not in {"render", "rework"} or not isinstance(payload, Mapping):
            return value
        declared_kind = payload.get("kind")
        if declared_kind not in {None, kind}:
            return value
        return {**payload, "kind": kind}


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
        return _normalize_subordinate_heading_levels(markdown)

    @field_validator("markdown")
    @classmethod
    def validate_markdown(cls, markdown: str) -> str:
        try:
            # 单块生成阶段没有前序块上下文，因此这里只拒绝可独立判定的协议错误；
            # H4 的父级关系仍由整章提交校验跨 block 判定。
            validate_report_block_markdown(markdown)
        except ReportingError as error:
            raise ValueError(str(error)) from error
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
    "VisualizationScriptDraft",
]
