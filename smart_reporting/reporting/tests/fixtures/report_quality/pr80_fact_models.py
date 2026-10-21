"""Pinned pr80@743b7100 fact model declarations for rollback compatibility probes.

Copied from the original model AST, without execution code or live application
imports; the original source SHA256 is 805e2cee247918236bdcd12098ca18d1f18f8f6843fe41f197ab468a57607835.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AnalysisModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


Aggregation = Literal["sum", "average", "min", "max", "count", "count_distinct"]
PeriodRole = Literal["current", "yoy", "mom"]


class PeriodValue(AnalysisModel):
    period: str = Field(min_length=1, max_length=128)
    value: float


class GroupContribution(AnalysisModel):
    group: str = Field(min_length=1, max_length=512)
    value: float
    group_values: dict[str, str | None] = Field(
        default_factory=dict, alias="groupValues", max_length=100
    )


class DeterministicMetricFact(AnalysisModel):
    fact_id: str | None = Field(default=None, alias="factId", pattern="^fact-[0-9a-f]{16}$")
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    dataset_sha256: str = Field(alias="datasetSha256", pattern="^[0-9a-f]{64}$")
    profile_hash: str | None = Field(default=None, alias="profileHash", pattern="^[0-9a-f]{64}$")
    period_roles: tuple[PeriodRole, ...] = Field(alias="periodRoles", min_length=1, max_length=3)
    metric_codes: tuple[str, ...] = Field(default=(), alias="metricCodes", max_length=100)
    field: str = Field(min_length=1, max_length=128)
    field_ref: str = Field(alias="fieldRef", min_length=1, max_length=512)
    display_name: str | None = Field(default=None, alias="displayName", max_length=2000)
    aliases: tuple[str, ...] = Field(default=(), max_length=100)
    aggregation: Aggregation
    period_aggregation: Literal["last"] | None = Field(default=None, alias="periodAggregation")
    unit: str | None = Field(default=None, max_length=64)
    formula: str = Field(min_length=1, max_length=1000)
    scope: dict[str, str] = Field(default_factory=dict, max_length=100)
    period_field: str | None = Field(default=None, alias="periodField", max_length=128)
    period_granularity: Literal["day", "month", "year"] | None = Field(
        default=None, alias="periodGranularity"
    )
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    total: float
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    missing_count: int = Field(alias="missingCount", ge=0)
    period_missing_count: int | None = Field(default=None, alias="periodMissingCount", ge=0)
    zero_count: int = Field(alias="zeroCount", ge=0)
    negative_count: int = Field(alias="negativeCount", ge=0)
    period_values: tuple[PeriodValue, ...] = Field(
        default=(), alias="periodValues", max_length=1200
    )
    top_groups: tuple[GroupContribution, ...] = Field(default=(), alias="topGroups", max_length=20)
    bottom_groups: tuple[GroupContribution, ...] = Field(
        default=(), alias="bottomGroups", max_length=20
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicComparison(AnalysisModel):
    fact_id: str | None = Field(default=None, alias="factId", pattern="^fact-[0-9a-f]{16}$")
    input_fact_ids: tuple[str, ...] = Field(default=(), alias="inputFactIds", max_length=200)
    scope: dict[str, str] = Field(default_factory=dict, max_length=100)
    comparison_type: Literal["yoy", "mom"] = Field(alias="comparisonType")
    field: str = Field(min_length=1, max_length=128)
    field_ref: str = Field(alias="fieldRef", min_length=1, max_length=512)
    current_dataset_id: str = Field(alias="currentDatasetId", min_length=1, max_length=256)
    baseline_dataset_id: str = Field(alias="baselineDatasetId", min_length=1, max_length=256)
    current_dataset_sha256: str = Field(alias="currentDatasetSha256", pattern="^[0-9a-f]{64}$")
    baseline_dataset_sha256: str = Field(alias="baselineDatasetSha256", pattern="^[0-9a-f]{64}$")
    current_total: float = Field(alias="currentTotal")
    baseline_total: float = Field(alias="baselineTotal")
    baseline_scale: float = Field(default=1, alias="baselineScale", gt=0, allow_inf_nan=False)
    change: float
    change_rate: float | None = Field(default=None, alias="changeRate")
    formula: str = Field(min_length=1, max_length=1000)
    unit: str | None = Field(default=None, max_length=64)
    period_granularity: Literal["day", "month", "year"] | None = Field(
        default=None, alias="periodGranularity"
    )
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    baseline_period_start: str | None = Field(
        default=None, alias="baselinePeriodStart", max_length=128
    )
    baseline_period_end: str | None = Field(default=None, alias="baselinePeriodEnd", max_length=128)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicDerivedMetricFact(AnalysisModel):
    fact_id: str | None = Field(default=None, alias="factId", pattern="^fact-[0-9a-f]{16}$")
    code: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    period_role: PeriodRole = Field(alias="periodRole")
    numerator_metric: str = Field(alias="numeratorMetric", min_length=1, max_length=128)
    denominator_metric: str = Field(alias="denominatorMetric", min_length=1, max_length=128)
    input_fact_ids: tuple[str, ...] = Field(default=(), alias="inputFactIds", max_length=200)
    scope: dict[str, str] = Field(default_factory=dict, max_length=100)
    numerator: float
    denominator: float
    denominator_scale: float = Field(default=1, alias="denominatorScale", gt=0, allow_inf_nan=False)
    value: float | None = None
    percentage: float | None = None
    difference: float | None = None
    unit: str | None = Field(default=None, max_length=64)
    formula: str = Field(min_length=1, max_length=1000)
    period_granularity: Literal["day", "month", "year"] | None = Field(
        default=None, alias="periodGranularity"
    )
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=20)
    dataset_sha256s: tuple[str, ...] = Field(alias="datasetSha256s", min_length=1, max_length=20)
    profile_hash: str | None = Field(default=None, alias="profileHash", pattern="^[0-9a-f]{64}$")
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicReconciliationFact(AnalysisModel):
    fact_id: str | None = Field(default=None, alias="factId", pattern="^fact-[0-9a-f]{16}$")
    input_fact_ids: tuple[str, ...] = Field(default=(), alias="inputFactIds", max_length=200)
    code: str = Field(min_length=1, max_length=128)
    period_role: PeriodRole = Field(alias="periodRole")
    period_granularity: Literal["day", "month", "year"] | None = Field(
        default=None, alias="periodGranularity"
    )
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    left_metric: str = Field(alias="leftMetric", min_length=1, max_length=128)
    right_metric: str = Field(alias="rightMetric", min_length=1, max_length=128)
    grain: tuple[str, ...] = Field(min_length=1, max_length=20)
    left_total: float = Field(alias="leftTotal")
    right_total: float = Field(alias="rightTotal")
    unit: str | None = Field(default=None, max_length=64)
    right_scale: float = Field(default=1, alias="rightScale", gt=0, allow_inf_nan=False)
    difference: float
    absolute_tolerance: float = Field(alias="absoluteTolerance", ge=0)
    relative_tolerance: float = Field(alias="relativeTolerance", ge=0)
    checked_group_count: int = Field(alias="checkedGroupCount", ge=0)
    failed_group_count: int = Field(alias="failedGroupCount", ge=0)
    passed: bool
    formula: str = Field(min_length=1, max_length=1000)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=20)
    dataset_sha256s: tuple[str, ...] = Field(alias="datasetSha256s", min_length=1, max_length=20)
    profile_hash: str | None = Field(default=None, alias="profileHash", pattern="^[0-9a-f]{64}$")
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class CorrelationDetail(AnalysisModel):
    """B4：相关性元数据（n、字段身份、方法、稳定 ID）；旧键值兼容保留。"""

    fact_id: str | None = Field(default=None, alias="factId", pattern="^fact-[0-9a-f]{16}$")
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    dataset_sha256: str = Field(alias="datasetSha256", pattern="^[0-9a-f]{64}$")
    left_field: str = Field(alias="leftField", min_length=1, max_length=128)
    right_field: str = Field(alias="rightField", min_length=1, max_length=128)
    method: Literal["pearson"] = "pearson"
    scope: dict[str, str] = Field(default_factory=dict, max_length=100)
    sample_count: int = Field(alias="sampleCount", ge=0)
    value: float
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicAnalysisBundle(AnalysisModel):
    version: str = "1"
    analysis_id: str = Field(alias="analysisId", pattern="^analysis_[0-9]{3,6}$")
    analysis_name: str | None = Field(
        default=None, alias="analysisName", min_length=1, max_length=2000
    )
    metrics: tuple[DeterministicMetricFact, ...] = Field(default=(), max_length=500)
    derived_metrics: tuple[DeterministicDerivedMetricFact, ...] = Field(
        default=(), alias="derivedMetrics", max_length=500
    )
    comparisons: tuple[DeterministicComparison, ...] = Field(default=(), max_length=400)
    reconciliations: tuple[DeterministicReconciliationFact, ...] = Field(default=(), max_length=500)
    correlations: dict[str, float] = Field(default_factory=dict)
    correlation_details: tuple[CorrelationDetail, ...] = Field(
        default=(), alias="correlationDetails", max_length=500
    )
    warnings: tuple[str, ...] = Field(default=(), max_length=500)
