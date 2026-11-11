"""依据声明规则和授权取数回执评估数据就绪，不从首末日期推断期间完整。"""

from pydantic import AwareDatetime, Field, model_validator

from ..models import ReportingError
from .models import (
    DataReadiness,
    DataReadinessPolicy,
    DimensionValue,
    Identity,
    MetricRequest,
    MetricVersionRef,
    Period,
    ReadinessCheck,
    SemanticModel,
    StatisticalPolicy,
)


class PeriodObservation(SemanticModel):
    period: Period
    observed_count: int = Field(ge=0, strict=True)


class GroupObservation(SemanticModel):
    dimensions: tuple[DimensionValue, ...] = Field(min_length=1)
    observed_count: int = Field(ge=0, strict=True)


class ReadinessObservations(SemanticModel):
    metric_version: MetricVersionRef
    basis_id: Identity
    requested_period: Period
    extracted_at: AwareDatetime
    observed_period: Period | None = None
    source_watermark: AwareDatetime | None = None
    fact_refs: tuple[Identity, ...] = Field(min_length=1)
    period_counts: tuple[PeriodObservation, ...] = ()
    group_counts: tuple[GroupObservation, ...] = ()

    @model_validator(mode="after")
    def unique_observations(self):
        periods = [item.period for item in self.period_counts]
        groups = [frozenset(item.dimensions) for item in self.group_counts]
        if len(set(periods)) != len(periods) or len(set(groups)) != len(groups):
            raise ValueError("同一期间或分组不能重复登记观测")
        if any(len({entry.dimension_id for entry in item.dimensions}) != len(item.dimensions) for item in self.group_counts):
            raise ValueError("观测分组的维度不能重复")
        return self


def evaluate_data_readiness(
    request: MetricRequest, policy: StatisticalPolicy | DataReadinessPolicy, observations: ReadinessObservations,
) -> DataReadiness:
    if (observations.metric_version != request.metric_version or observations.basis_id != request.basis_id
            or observations.requested_period != request.period):
        raise ReportingError("metric_observation_mismatch", "数据就绪观测与本次计算身份不一致。")
    rules = policy.readiness_policy if isinstance(policy, StatisticalPolicy) else policy
    checks, issues = [], []

    def check(name, status, code=None):
        checks.append(ReadinessCheck(name=name, status=status, fact_refs=observations.fact_refs))
        if code is not None and code not in issues:
            issues.append(code)

    expected = sorted((item for item in rules.expected_periods
        if item.start < request.period.end and item.end > request.period.start), key=lambda item: item.start)
    cursor = request.period.start
    for period in expected:
        if period.start > cursor:
            break
        cursor = max(cursor, period.end)
    counts = {item.period: item.observed_count for item in observations.period_counts}
    if not expected or cursor < request.period.end:
        check("period_coverage", "unknown", "data_readiness_unknown")
    elif any(period not in counts for period in expected):
        check("period_coverage", "unknown", "period_observations_unknown")
    elif any(counts[period] == 0 for period in expected):
        check("period_coverage", "fail", "missing_period_observations")
    else:
        check("period_coverage", "pass")

    if not rules.expected_groups:
        check("group_coverage", "unknown", "data_readiness_unknown")
    else:
        observed_groups = {frozenset(item.dimensions) for item in observations.group_counts if item.observed_count > 0}
        if any(frozenset(group) not in observed_groups for group in rules.expected_groups):
            check("group_coverage", "fail", "missing_group_observations")
        else:
            check("group_coverage", "pass")

    if rules.watermark_field is None or rules.maximum_delay_seconds is None:
        check("source_freshness", "unknown", "data_readiness_unknown")
    elif observations.source_watermark is None:
        check("source_freshness", "unknown", "source_watermark_unknown")
    else:
        delay = (observations.extracted_at - observations.source_watermark).total_seconds()
        if delay < 0:
            check("source_freshness", "fail", "source_watermark_in_future")
        elif delay > rules.maximum_delay_seconds:
            check("source_freshness", "fail", "source_watermark_stale")
        else:
            check("source_freshness", "pass")
    return DataReadiness(metric_version=request.metric_version, requested_period=request.period,
        observed_period=observations.observed_period, extracted_at=observations.extracted_at,
        source_watermark=observations.source_watermark, checks=tuple(checks), issue_codes=tuple(issues))
