"""固定 Reporting 阶段的模型生成契约。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import ConfigDict, Field, RootModel, TypeAdapter, field_validator, model_validator

from ...contract import StrictModel
from ...delivery.draft_v1 import ReportDraftBlock
from ..checkpoint import FileIdentity, SectionClaimSubmission

MAX_VISUALIZATION_SOURCE_BYTES = 262_144


class ChartDraft(StrictModel):
    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=1024)
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
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


class RenderSectionDecision(StrictModel):
    kind: Literal["render"] = "render"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    blocks: tuple[ReportDraftBlock, ...] = Field(min_length=1, max_length=200)
    claims: tuple[SectionClaimSubmission, ...] = Field(min_length=1, max_length=500)


class AnalysisReworkDecision(StrictModel):
    kind: Literal["rework"] = "rework"
    section_code: str = Field(alias="sectionCode", min_length=1, max_length=128)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    missing_evidence: tuple[str, ...] = Field(alias="missingEvidence", min_length=1, max_length=100)


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
    "SectionDecision",
    "SectionDecisionAdapter",
    "SectionDecisionOutput",
    "SectionEvidenceBundle",
    "SectionEvidenceFile",
    "VisualizationScriptDraft",
]
