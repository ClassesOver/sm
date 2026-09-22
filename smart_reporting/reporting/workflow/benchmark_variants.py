"""Planner/Coding 基线契约与 benchmark 变体选择。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BenchmarkVariant(StrEnum):
    LEGACY = "legacy"
    CANDIDATE = "candidate"

    @classmethod
    def parse(cls, value: str) -> BenchmarkVariant:
        try:
            return cls(value)
        except ValueError as error:
            raise ValueError("benchmark variant 必须是 legacy 或 candidate") from error


class LegacyAnalysisEvidenceDecision(BaseModel):
    """不含实验性 codingRequirements 的 evidence planner 基线输出。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    requires_supplemental_evidence: bool = Field(alias="requiresSupplementalEvidence")
    reason: str = Field(min_length=1, max_length=2_000)
    missing_facts: tuple[str, ...] = Field(alias="missingFacts", max_length=20)


class LegacyChartDraft(BaseModel):
    """R7 之前的 benchmark-only 图表项。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    chart_id: str = Field(alias="chartId", min_length=1, max_length=128)
    source_path: str = Field(alias="sourcePath", min_length=1, max_length=1024)
    renderer: Literal["matplotlib", "plotly"] = "matplotlib"
    interactive_path: str | None = Field(
        default=None, alias="interactivePath", min_length=1, max_length=1024
    )
    title: str = Field(min_length=1, max_length=200)
    alt_text: str = Field(alias="altText", min_length=1, max_length=200)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    metric_codes: tuple[str, ...] = Field(alias="metricCodes", min_length=1, max_length=100)
    current_period: str = Field(alias="currentPeriod", min_length=1, max_length=200)
    comparison_period: str | None = Field(
        default=None, alias="comparisonPeriod", max_length=200
    )
    comparison_type: Literal["none", "yoy", "mom", "period"] = Field(
        default="none", alias="comparisonType"
    )
    source_dataset_id: str = Field(alias="sourceDatasetId", min_length=1, max_length=256)
    aggregation_grain: str = Field(alias="aggregationGrain", min_length=1, max_length=128)
    comparability: Literal["strict", "reference_only"] = "strict"

    @field_validator("source_path")
    @classmethod
    def validate_source_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if "\\" in value or path.is_absolute() or ".." in path.parts or value.endswith("/"):
            raise ValueError("图表源文件必须是安全工作区相对路径")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("图表源文件必须是 PNG 或 JPEG")
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
            raise ValueError("interactivePath 必须是安全的 .plotly.json 相对路径")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_delivery_fields(self) -> LegacyChartDraft:
        if (self.renderer == "plotly") != (self.interactive_path is not None):
            raise ValueError("Plotly 图表必须且仅能声明 interactivePath")
        if self.comparison_type != "none" and not self.comparison_period:
            raise ValueError("比较图表必须声明 comparisonPeriod")
        if self.comparability == "reference_only" and self.comparison_type in {"yoy", "mom"}:
            raise ValueError("reference_only 图表不得声明严格同比或环比")
        return self


class LegacyVisualizationPlanDraft(BaseModel):
    """R7 之前的 benchmark-only 图表计划外壳。

    图表字段保持 planner 原始对象，故意不声明 R7 的 `visualForm`/`dataBindings`；
    宿主仍须在映射到生产交付模型前执行完整绑定校验。
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    charts: tuple[LegacyChartDraft, ...] = Field(max_length=100)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)

    @model_validator(mode="after")
    def validate_unique_charts(self) -> LegacyVisualizationPlanDraft:
        chart_ids = [item.chart_id for item in self.charts]
        paths = [item.source_path for item in self.charts]
        if len(chart_ids) != len(set(chart_ids)) or len(paths) != len(set(paths)):
            raise ValueError("图表 ID 和输出路径不能重复")
        return self


@dataclass(frozen=True, slots=True)
class BenchmarkProjection:
    """决定 R7 字段是否进入 benchmark 请求；既有紧凑 facts 始终保留。"""

    variant: BenchmarkVariant
    include_analysis_requirements: bool
    include_visual_bindings: bool

    @classmethod
    def for_variant(cls, variant: BenchmarkVariant) -> BenchmarkProjection:
        if not isinstance(variant, BenchmarkVariant):
            raise TypeError("variant 必须是 BenchmarkVariant")
        enabled = variant is BenchmarkVariant.CANDIDATE
        return cls(
            variant=variant,
            include_analysis_requirements=enabled,
            include_visual_bindings=enabled,
        )


@dataclass(frozen=True, slots=True)
class BenchmarkPlannerSpec:
    """冻结 benchmark 在 planner 构造前选择的变体契约。

    该类型只描述一次性 benchmark invocation，不作为生产 workflow 的 feature flag。
    """

    task_kind: Literal["analysis", "visualization"]
    variant: BenchmarkVariant
    output_schema: type[BaseModel]
    instructions: tuple[str, ...]
    project_coding_facts: Callable[[Mapping[str, Any]], Mapping[str, Any]]

    def __post_init__(self) -> None:
        if self.task_kind not in {"analysis", "visualization"}:
            raise ValueError("benchmark task_kind 必须是 analysis 或 visualization")
        if not isinstance(self.variant, BenchmarkVariant):
            raise TypeError("variant 必须是 BenchmarkVariant")
        if not isinstance(self.output_schema, type) or not issubclass(
            self.output_schema, BaseModel
        ):
            raise TypeError("output_schema 必须是 Pydantic BaseModel 类型")
        if any(not isinstance(item, str) or not item.strip() for item in self.instructions):
            raise ValueError("planner instructions 不能包含空字符串")
        if not callable(self.project_coding_facts):
            raise TypeError("project_coding_facts 必须是可调用对象")


def build_benchmark_planner_spec(
    *,
    task_kind: Literal["analysis", "visualization"],
    variant: BenchmarkVariant,
    legacy_output_schema: type[BaseModel],
    candidate_output_schema: type[BaseModel],
    legacy_instructions: tuple[str, ...],
    candidate_instructions: tuple[str, ...],
    legacy_project_coding_facts: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    candidate_project_coding_facts: Callable[[Mapping[str, Any]], Mapping[str, Any]],
) -> BenchmarkPlannerSpec:
    """在 planner 构造前固定 benchmark 变体。

    调用方负责提供各阶段的旧/新 schema 和指令；本函数只做选择与契约校验，避免
    把生产 strict schema 事后裁剪成伪 legacy。
    """

    if variant is BenchmarkVariant.LEGACY:
        return BenchmarkPlannerSpec(
            task_kind=task_kind,
            variant=variant,
            output_schema=legacy_output_schema,
            instructions=legacy_instructions,
            project_coding_facts=legacy_project_coding_facts,
        )
    if variant is BenchmarkVariant.CANDIDATE:
        return BenchmarkPlannerSpec(
            task_kind=task_kind,
            variant=variant,
            output_schema=candidate_output_schema,
            instructions=candidate_instructions,
            project_coding_facts=candidate_project_coding_facts,
        )
    raise TypeError("variant 必须是 BenchmarkVariant")
