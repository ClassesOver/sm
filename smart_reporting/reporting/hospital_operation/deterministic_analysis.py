"""按冻结分析计划生成通用、不可变的确定性事实。"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Literal

import pandas as pd
from pydantic import Field

from .detailed_analysis import AnalysisModel, DatasetAnalysisContext, DetailedAnalysisItem

Aggregation = Literal["sum", "average", "min", "max", "count", "count_distinct"]
PeriodRole = Literal["current", "yoy", "mom"]


class PeriodValue(AnalysisModel):
    period: str = Field(min_length=1, max_length=128)
    value: float


class GroupContribution(AnalysisModel):
    group: str = Field(min_length=1, max_length=512)
    value: float


class DeterministicMetricFact(AnalysisModel):
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=256)
    dataset_sha256: str = Field(alias="datasetSha256", pattern=r"^[0-9a-f]{64}$")
    profile_hash: str | None = Field(default=None, alias="profileHash", pattern=r"^[0-9a-f]{64}$")
    metric_codes: tuple[str, ...] = Field(default=(), alias="metricCodes", max_length=100)
    field: str = Field(min_length=1, max_length=128)
    field_ref: str = Field(alias="fieldRef", min_length=1, max_length=512)
    aggregation: Aggregation
    unit: str | None = Field(default=None, max_length=64)
    formula: str = Field(min_length=1, max_length=1000)
    scope: dict[str, str] = Field(default_factory=dict, max_length=100)
    period_field: str | None = Field(default=None, alias="periodField", max_length=128)
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    total: float
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    missing_count: int = Field(alias="missingCount", ge=0)
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
    comparison_type: Literal["yoy", "mom"] = Field(alias="comparisonType")
    field: str = Field(min_length=1, max_length=128)
    field_ref: str = Field(alias="fieldRef", min_length=1, max_length=512)
    current_dataset_id: str = Field(alias="currentDatasetId", min_length=1, max_length=256)
    baseline_dataset_id: str = Field(alias="baselineDatasetId", min_length=1, max_length=256)
    current_dataset_sha256: str = Field(alias="currentDatasetSha256", pattern=r"^[0-9a-f]{64}$")
    baseline_dataset_sha256: str = Field(alias="baselineDatasetSha256", pattern=r"^[0-9a-f]{64}$")
    current_total: float = Field(alias="currentTotal")
    baseline_total: float = Field(alias="baselineTotal")
    change: float
    change_rate: float | None = Field(default=None, alias="changeRate")
    formula: str = Field(min_length=1, max_length=1000)
    unit: str | None = Field(default=None, max_length=64)
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicDerivedMetricFact(AnalysisModel):
    code: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    period_role: PeriodRole = Field(alias="periodRole")
    numerator_metric: str = Field(alias="numeratorMetric", min_length=1, max_length=128)
    denominator_metric: str = Field(alias="denominatorMetric", min_length=1, max_length=128)
    numerator: float
    denominator: float
    value: float | None = None
    percentage: float | None = None
    difference: float
    unit: str | None = Field(default=None, max_length=64)
    formula: str = Field(min_length=1, max_length=1000)
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=20)
    dataset_sha256s: tuple[str, ...] = Field(alias="datasetSha256s", min_length=1, max_length=20)
    profile_hash: str | None = Field(default=None, alias="profileHash", pattern=r"^[0-9a-f]{64}$")
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicReconciliationFact(AnalysisModel):
    code: str = Field(min_length=1, max_length=128)
    period_role: PeriodRole = Field(alias="periodRole")
    left_metric: str = Field(alias="leftMetric", min_length=1, max_length=128)
    right_metric: str = Field(alias="rightMetric", min_length=1, max_length=128)
    grain: tuple[str, ...] = Field(min_length=1, max_length=20)
    left_total: float = Field(alias="leftTotal")
    right_total: float = Field(alias="rightTotal")
    difference: float
    absolute_tolerance: float = Field(alias="absoluteTolerance", ge=0)
    relative_tolerance: float = Field(alias="relativeTolerance", ge=0)
    checked_group_count: int = Field(alias="checkedGroupCount", ge=0)
    failed_group_count: int = Field(alias="failedGroupCount", ge=0)
    passed: bool
    formula: str = Field(min_length=1, max_length=1000)
    dataset_ids: tuple[str, ...] = Field(alias="datasetIds", min_length=1, max_length=20)
    dataset_sha256s: tuple[str, ...] = Field(alias="datasetSha256s", min_length=1, max_length=20)
    profile_hash: str | None = Field(default=None, alias="profileHash", pattern=r"^[0-9a-f]{64}$")
    warnings: tuple[str, ...] = Field(default=(), max_length=100)


class DeterministicAnalysisBundle(AnalysisModel):
    version: str = "1"
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    metrics: tuple[DeterministicMetricFact, ...] = Field(default=(), max_length=500)
    derived_metrics: tuple[DeterministicDerivedMetricFact, ...] = Field(
        default=(), alias="derivedMetrics", max_length=500
    )
    comparisons: tuple[DeterministicComparison, ...] = Field(default=(), max_length=400)
    reconciliations: tuple[DeterministicReconciliationFact, ...] = Field(default=(), max_length=500)
    correlations: dict[str, float] = Field(default_factory=dict)
    warnings: tuple[str, ...] = Field(default=(), max_length=500)


@dataclass(frozen=True)
class _Dataset:
    dataset_id: str
    frame: pd.DataFrame
    context: DatasetAnalysisContext
    period_roles: tuple[PeriodRole, ...]


def build_deterministic_analysis_bundle(
    analysis: DetailedAnalysisItem,
    datasets: tuple[tuple[str, bytes, DatasetAnalysisContext, tuple[PeriodRole, ...]], ...],
    *,
    profile_metrics: tuple[Mapping[str, Any], ...] = (),
    profile_reconciliations: tuple[Mapping[str, Any], ...] = (),
    profile_dimensions: tuple[Mapping[str, Any], ...] = (),
    profile_hash: str | None = None,
) -> DeterministicAnalysisBundle:
    """只计算由冻结 CSV、已确认语义和 Effective Profile 唯一确定的事实。"""

    prepared: list[_Dataset] = []
    warnings: list[str] = list(analysis.limitations)
    for dataset_id, content, context, period_roles in datasets:
        try:
            frame = pd.read_csv(BytesIO(content))
        except (UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError):
            warnings.append(f"Dataset {dataset_id} 无法解析为 CSV，未生成确定性事实。")
            continue
        prepared.append(_Dataset(dataset_id, frame, context, period_roles))

    metric_codes_by_ref = _metric_codes_by_ref(profile_metrics)
    facts: list[DeterministicMetricFact] = []
    semantics_by_dataset: dict[tuple[str, str], Mapping[str, Any]] = {}
    for dataset in prepared:
        dataset_facts, dataset_semantics, dataset_warnings = _dataset_facts(
            dataset,
            analysis,
            metric_codes_by_ref=metric_codes_by_ref,
            profile_hash=profile_hash,
        )
        facts.extend(dataset_facts)
        semantics_by_dataset.update(dataset_semantics)
        warnings.extend(dataset_warnings)

    comparisons = _comparisons(facts, prepared)
    derived_metrics, derived_warnings = _derived_metrics(
        facts,
        prepared,
        profile_metrics,
        profile_hash=profile_hash,
    )
    reconciliations, reconciliation_warnings = _reconciliations(
        facts,
        prepared,
        semantics_by_dataset,
        profile_metrics,
        profile_reconciliations,
        profile_dimensions,
        profile_hash=profile_hash,
    )
    warnings.extend(derived_warnings)
    warnings.extend(reconciliation_warnings)
    correlations = _correlations(prepared, facts)
    return DeterministicAnalysisBundle(
        analysisId=analysis.analysis_id,
        metrics=tuple(facts),
        derivedMetrics=derived_metrics,
        comparisons=comparisons,
        reconciliations=reconciliations,
        correlations=correlations,
        warnings=tuple(dict.fromkeys(warnings))[:500],
    )


def _dataset_facts(
    dataset: _Dataset,
    analysis: DetailedAnalysisItem,
    *,
    metric_codes_by_ref: Mapping[str, tuple[str, ...]],
    profile_hash: str | None,
) -> tuple[
    list[DeterministicMetricFact],
    dict[tuple[str, str], Mapping[str, Any]],
    list[str],
]:
    facts: list[DeterministicMetricFact] = []
    selected_semantics: dict[tuple[str, str], Mapping[str, Any]] = {}
    warnings = _coverage_warnings(dataset)
    requested_fields = {field.rsplit(".", 1)[-1].casefold() for field in analysis.fields}
    semantics_by_field: dict[str, list[Mapping[str, Any]]] = {}
    for raw_semantic in dataset.context.metric_semantics:
        field_ref = str(raw_semantic.get("fieldRef", ""))
        field = field_ref.rsplit(".", 1)[-1]
        if field not in dataset.frame or (
            requested_fields and field.casefold() not in requested_fields
        ):
            continue
        semantics_by_field.setdefault(field.casefold(), []).append(raw_semantic)
    if not semantics_by_field:
        warnings.append(
            f"Dataset {dataset.dataset_id} 没有已确认指标语义，未对数值字段猜测固定指标。"
        )
        return facts, selected_semantics, warnings

    period_field = _period_field(dataset.frame, dataset.context)
    group_fields = tuple(field for field in analysis.organization_grain if field in dataset.frame)
    if not group_fields:
        group_fields = tuple(
            field for field in dataset.context.organization_grain if field in dataset.frame
        )
    for field_key, candidates in semantics_by_field.items():
        if len(candidates) != 1:
            warnings.append(
                f"Dataset {dataset.dataset_id} 的字段 {field_key} 对应多个完整 fieldRef，未生成固定指标。"
            )
            continue
        semantic = candidates[0]
        field_ref = str(semantic["fieldRef"])
        field = field_ref.rsplit(".", 1)[-1]
        aggregation = _aggregation(semantic)
        scoped_frame, scope_warnings = _apply_scope(dataset, semantic)
        series = scoped_frame[field]
        value = _aggregate(series, aggregation)
        if value is None:
            warnings.append(f"Dataset {dataset.dataset_id} 的 {field} 没有可计算值。")
            continue
        numeric = pd.to_numeric(series, errors="coerce")
        valid_numeric = numeric.dropna()
        periods = _period_values(scoped_frame, field, period_field, aggregation)
        top, bottom = _group_contributions(scoped_frame, field, group_fields, aggregation)
        period_labels = [item.period for item in periods]
        fact_warnings = tuple(
            dict.fromkeys(
                (
                    *dataset.context.source_warnings,
                    *dataset.context.quality_warnings,
                    *scope_warnings,
                )
            )
        )[:100]
        scope = _scope(semantic)
        facts.append(
            DeterministicMetricFact(
                datasetId=dataset.dataset_id,
                datasetSha256=dataset.context.sha256,
                profileHash=profile_hash,
                metricCodes=metric_codes_by_ref.get(field_ref.casefold(), ()),
                field=field,
                fieldRef=field_ref,
                aggregation=aggregation,
                unit=_metric_unit(semantic),
                formula=_formula(field, aggregation, scope),
                scope=scope,
                periodField=period_field,
                periodStart=period_labels[0] if period_labels else None,
                periodEnd=period_labels[-1] if period_labels else None,
                total=value,
                average=_optional_finite(valid_numeric.mean()) if not valid_numeric.empty else None,
                minimum=_optional_finite(valid_numeric.min()) if not valid_numeric.empty else None,
                maximum=_optional_finite(valid_numeric.max()) if not valid_numeric.empty else None,
                missingCount=int(series.isna().sum()),
                zeroCount=int((valid_numeric == 0).sum()),
                negativeCount=int((valid_numeric < 0).sum()),
                periodValues=periods,
                topGroups=top,
                bottomGroups=bottom,
                warnings=fact_warnings,
            )
        )
        selected_semantics[(dataset.dataset_id, field_ref.casefold())] = semantic
    return facts, selected_semantics, warnings


def _aggregation(semantic: Mapping[str, Any]) -> Aggregation:
    value = str(semantic.get("aggregation", ""))
    if value not in {"sum", "average", "min", "max", "count", "count_distinct"}:
        raise ValueError(f"不支持的指标聚合语义: {value}")
    return value  # type: ignore[return-value]


def _scope(semantic: Mapping[str, Any]) -> dict[str, str]:
    raw = semantic.get("exclusiveScope")
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _apply_scope(
    dataset: _Dataset, semantic: Mapping[str, Any]
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    scope = _scope(semantic)
    frame = dataset.frame
    warnings: list[str] = []
    for column, expected in scope.items():
        if column not in frame:
            warnings.append(
                f"固定范围 {column}={expected} 已由受审核 SQL 应用，CSV 未投影该范围字段。"
            )
            continue
        frame = frame.loc[frame[column].astype(str) == expected]
    return frame, tuple(warnings)


def _aggregate(series: pd.Series, aggregation: Aggregation) -> float | None:
    if aggregation == "count":
        return float(series.notna().sum())
    if aggregation == "count_distinct":
        return float(series.dropna().nunique())
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return None
    operations = {
        "sum": numeric.sum,
        "average": numeric.mean,
        "min": numeric.min,
        "max": numeric.max,
    }
    return _finite(operations[aggregation]())


def _period_values(
    frame: pd.DataFrame,
    field: str,
    period_field: str | None,
    aggregation: Aggregation,
) -> tuple[PeriodValue, ...]:
    if period_field is None or period_field not in frame:
        return ()
    values: list[PeriodValue] = []
    for period, group in frame.groupby(frame[period_field].astype(str), dropna=False, sort=True):
        value = _aggregate(group[field], aggregation)
        if value is not None:
            values.append(PeriodValue(period=str(period), value=value))
    return tuple(values)


def _group_contributions(
    frame: pd.DataFrame,
    field: str,
    group_fields: tuple[str, ...],
    aggregation: Aggregation,
) -> tuple[tuple[GroupContribution, ...], tuple[GroupContribution, ...]]:
    if not group_fields:
        return (), ()
    values: list[GroupContribution] = []
    grouper: str | list[str] = group_fields[0] if len(group_fields) == 1 else list(group_fields)
    for group, rows in frame.groupby(grouper, dropna=False, sort=False):
        value = _aggregate(rows[field], aggregation)
        if value is None:
            continue
        labels = group if isinstance(group, tuple) else (group,)
        values.append(GroupContribution(group=" / ".join(map(str, labels)), value=value))
    ordered = sorted(values, key=lambda item: item.value, reverse=True)
    return tuple(ordered[:10]), tuple(reversed(ordered[-10:]))


def _comparisons(
    facts: list[DeterministicMetricFact], datasets: list[_Dataset]
) -> tuple[DeterministicComparison, ...]:
    roles = {item.dataset_id: item.period_roles for item in datasets}
    result: list[DeterministicComparison] = []
    by_ref: dict[str, list[DeterministicMetricFact]] = {}
    for fact in facts:
        by_ref.setdefault(fact.field_ref.casefold(), []).append(fact)
    for field_facts in by_ref.values():
        current_facts = [item for item in field_facts if "current" in roles[item.dataset_id]]
        for current in current_facts:
            for comparison_type in ("yoy", "mom"):
                for baseline in (
                    item
                    for item in field_facts
                    if comparison_type in roles[item.dataset_id]
                    and item.dataset_id != current.dataset_id
                ):
                    change = current.total - baseline.total
                    rate = None if baseline.total == 0 else change / abs(baseline.total) * 100
                    result.append(
                        DeterministicComparison(
                            comparisonType=comparison_type,
                            field=current.field,
                            fieldRef=current.field_ref,
                            currentDatasetId=current.dataset_id,
                            baselineDatasetId=baseline.dataset_id,
                            currentDatasetSha256=current.dataset_sha256,
                            baselineDatasetSha256=baseline.dataset_sha256,
                            currentTotal=current.total,
                            baselineTotal=baseline.total,
                            change=_finite(change),
                            changeRate=_optional_finite(rate),
                            formula="(currentTotal-baselineTotal)/abs(baselineTotal)*100%",
                            unit=current.unit,
                            periodStart=current.period_start,
                            periodEnd=current.period_end,
                            warnings=tuple(dict.fromkeys((*current.warnings, *baseline.warnings)))[
                                :100
                            ],
                        )
                    )
    return tuple(result)


def _derived_metrics(
    facts: list[DeterministicMetricFact],
    datasets: list[_Dataset],
    profile_metrics: tuple[Mapping[str, Any], ...],
    *,
    profile_hash: str | None,
) -> tuple[tuple[DeterministicDerivedMetricFact, ...], list[str]]:
    roles = {item.dataset_id: item.period_roles for item in datasets}
    metric_map = {str(item.get("code", "")): item for item in profile_metrics}
    facts_by_code: dict[str, list[DeterministicMetricFact]] = {}
    for fact in facts:
        for code in fact.metric_codes:
            facts_by_code.setdefault(code, []).append(fact)
    result: list[DeterministicDerivedMetricFact] = []
    warnings: list[str] = []
    for metric in profile_metrics:
        if metric.get("aggregation") != "ratio":
            continue
        code = str(metric.get("code", ""))
        numerator_code = str(metric.get("numeratorMetric", ""))
        denominator_code = str(metric.get("denominatorMetric", ""))
        if numerator_code not in metric_map or denominator_code not in metric_map:
            warnings.append(f"Profile 比率指标 {code} 的依赖无效。")
            continue
        for role in ("current", "yoy", "mom"):
            numerator_facts = [
                item
                for item in facts_by_code.get(numerator_code, ())
                if role in roles[item.dataset_id]
            ]
            denominator_facts = [
                item
                for item in facts_by_code.get(denominator_code, ())
                if role in roles[item.dataset_id]
            ]
            if not numerator_facts and not denominator_facts:
                continue
            if len(numerator_facts) != 1 or len(denominator_facts) != 1:
                warnings.append(f"Profile 比率指标 {code} 在 {role} 期间没有唯一的分子和分母事实。")
                continue
            numerator_fact = numerator_facts[0]
            denominator_fact = denominator_facts[0]
            numerator = numerator_fact.total
            denominator = denominator_fact.total
            ratio_warnings = list(
                dict.fromkeys((*numerator_fact.warnings, *denominator_fact.warnings))
            )
            if denominator == 0:
                value = None
                percentage = None
                ratio_warnings.append(f"Profile 比率指标 {code} 的分母为零。")
            else:
                value = _finite(numerator / denominator)
                percentage = _finite(value * 100)
            dataset_ids = tuple(
                dict.fromkeys((numerator_fact.dataset_id, denominator_fact.dataset_id))
            )
            hashes = tuple(
                dict.fromkeys((numerator_fact.dataset_sha256, denominator_fact.dataset_sha256))
            )
            periods = tuple(
                value
                for value in (
                    numerator_fact.period_start,
                    numerator_fact.period_end,
                    denominator_fact.period_start,
                    denominator_fact.period_end,
                )
                if value is not None
            )
            result.append(
                DeterministicDerivedMetricFact(
                    code=code,
                    kind=str(metric.get("kind", "ratio")),
                    periodRole=role,
                    numeratorMetric=numerator_code,
                    denominatorMetric=denominator_code,
                    numerator=numerator,
                    denominator=denominator,
                    value=value,
                    percentage=percentage,
                    difference=_finite(numerator - denominator),
                    unit=(
                        numerator_fact.unit
                        if numerator_fact.unit == denominator_fact.unit
                        else None
                    ),
                    formula=f"{numerator_code}/{denominator_code}; difference={numerator_code}-{denominator_code}",
                    periodStart=min(periods) if periods else None,
                    periodEnd=max(periods) if periods else None,
                    datasetIds=dataset_ids,
                    datasetSha256s=hashes,
                    profileHash=profile_hash,
                    warnings=tuple(ratio_warnings)[:100],
                )
            )
    return tuple(result), warnings


def _reconciliations(
    facts: list[DeterministicMetricFact],
    datasets: list[_Dataset],
    semantics: Mapping[tuple[str, str], Mapping[str, Any]],
    profile_metrics: tuple[Mapping[str, Any], ...],
    profile_reconciliations: tuple[Mapping[str, Any], ...],
    profile_dimensions: tuple[Mapping[str, Any], ...],
    *,
    profile_hash: str | None,
) -> tuple[tuple[DeterministicReconciliationFact, ...], list[str]]:
    metric_refs = {
        str(item.get("code", "")): str(item.get("fieldRef", ""))
        for item in profile_metrics
        if item.get("aggregation") != "ratio" and item.get("fieldRef")
    }
    roles = {item.dataset_id: item.period_roles for item in datasets}
    dataset_map = {item.dataset_id: item for item in datasets}
    facts_by_ref = {(item.dataset_id, item.field_ref.casefold()): item for item in facts}
    result: list[DeterministicReconciliationFact] = []
    warnings: list[str] = []
    for rule in profile_reconciliations:
        code = str(rule.get("code", ""))
        left_code = str(rule.get("leftMetric", ""))
        right_code = str(rule.get("rightMetric", ""))
        left_ref = metric_refs.get(left_code)
        right_ref = metric_refs.get(right_code)
        if not left_ref or not right_ref:
            warnings.append(f"Profile 对账规则 {code} 缺少可计算的基础指标绑定。")
            continue
        grain = tuple(str(item) for item in rule.get("grain", ()))
        for role in ("current", "yoy", "mom"):
            left_candidates = [
                fact
                for (dataset_id, field_ref), fact in facts_by_ref.items()
                if field_ref == left_ref.casefold() and role in roles[dataset_id]
            ]
            right_candidates = [
                fact
                for (dataset_id, field_ref), fact in facts_by_ref.items()
                if field_ref == right_ref.casefold() and role in roles[dataset_id]
            ]
            if not left_candidates and not right_candidates:
                continue
            if len(left_candidates) != 1 or len(right_candidates) != 1:
                warnings.append(f"Profile 对账规则 {code} 在 {role} 期间没有唯一的左右指标事实。")
                continue
            left_fact = left_candidates[0]
            right_fact = right_candidates[0]
            left_groups = _reconciliation_groups(
                dataset_map[left_fact.dataset_id],
                left_fact,
                semantics[(left_fact.dataset_id, left_fact.field_ref.casefold())],
                grain,
                profile_dimensions,
            )
            right_groups = _reconciliation_groups(
                dataset_map[right_fact.dataset_id],
                right_fact,
                semantics[(right_fact.dataset_id, right_fact.field_ref.casefold())],
                grain,
                profile_dimensions,
            )
            if left_groups is None or right_groups is None:
                warnings.append(f"Profile 对账规则 {code} 无法按声明粒度 {grain} 映射动态字段。")
                continue
            absolute_tolerance = float(rule.get("absoluteTolerance", 0))
            relative_tolerance = float(rule.get("relativeTolerance", 0))
            keys = set(left_groups) | set(right_groups)
            failed = 0
            for key in keys:
                left = left_groups.get(key, 0.0)
                right = right_groups.get(key, 0.0)
                tolerance = max(
                    absolute_tolerance,
                    relative_tolerance * max(abs(left), abs(right)),
                )
                if abs(left - right) > tolerance:
                    failed += 1
            dataset_ids = tuple(dict.fromkeys((left_fact.dataset_id, right_fact.dataset_id)))
            hashes = tuple(dict.fromkeys((left_fact.dataset_sha256, right_fact.dataset_sha256)))
            result.append(
                DeterministicReconciliationFact(
                    code=code,
                    periodRole=role,
                    leftMetric=left_code,
                    rightMetric=right_code,
                    grain=grain,
                    leftTotal=left_fact.total,
                    rightTotal=right_fact.total,
                    difference=_finite(left_fact.total - right_fact.total),
                    absoluteTolerance=absolute_tolerance,
                    relativeTolerance=relative_tolerance,
                    checkedGroupCount=len(keys),
                    failedGroupCount=failed,
                    passed=failed == 0,
                    formula="abs(left-right) <= max(absoluteTolerance, relativeTolerance*max(abs(left),abs(right)))",
                    datasetIds=dataset_ids,
                    datasetSha256s=hashes,
                    profileHash=profile_hash,
                    warnings=tuple(dict.fromkeys((*left_fact.warnings, *right_fact.warnings)))[
                        :100
                    ],
                )
            )
    return tuple(result), warnings


def _reconciliation_groups(
    dataset: _Dataset,
    fact: DeterministicMetricFact,
    semantic: Mapping[str, Any],
    grain: tuple[str, ...],
    profile_dimensions: tuple[Mapping[str, Any], ...],
) -> dict[tuple[str, ...], float] | None:
    frame, _warnings = _apply_scope(dataset, semantic)
    columns = _grain_columns(fact.field_ref, frame, grain, profile_dimensions)
    if columns is None:
        return None
    grouper: str | list[str] = columns[0] if len(columns) == 1 else list(columns)
    result: dict[tuple[str, ...], float] = {}
    for key, rows in frame.groupby(grouper, dropna=False, sort=False):
        value = _aggregate(rows[fact.field], fact.aggregation)
        if value is None:
            continue
        labels = key if isinstance(key, tuple) else (key,)
        result[tuple(map(str, labels))] = value
    return result


def _grain_columns(
    metric_ref: str,
    frame: pd.DataFrame,
    grain: tuple[str, ...],
    profile_dimensions: tuple[Mapping[str, Any], ...],
) -> tuple[str, ...] | None:
    prefix = metric_ref.rsplit(".", 1)[0].casefold()
    dimensions = {str(item.get("code", "")): item for item in profile_dimensions}
    result: list[str] = []
    for code in grain:
        dimension = dimensions.get(code)
        refs = dimension.get("fieldRefs", ()) if dimension is not None else ()
        candidates = [
            str(ref).rsplit(".", 1)[-1]
            for ref in refs
            if str(ref).rsplit(".", 1)[0].casefold() == prefix
            and str(ref).rsplit(".", 1)[-1] in frame
        ]
        if len(candidates) == 1:
            result.append(candidates[0])
        elif code in frame:
            result.append(code)
        else:
            return None
    return tuple(result)


def _correlations(
    datasets: list[_Dataset], facts: list[DeterministicMetricFact]
) -> dict[str, float]:
    result: dict[str, float] = {}
    fields_by_dataset: dict[str, list[str]] = {}
    for fact in facts:
        fields_by_dataset.setdefault(fact.dataset_id, []).append(fact.field)
    for dataset in datasets:
        fields = tuple(dict.fromkeys(fields_by_dataset.get(dataset.dataset_id, ())))
        if len(fields) < 2:
            continue
        numeric = dataset.frame.loc[:, list(fields)].apply(pd.to_numeric, errors="coerce")
        correlation = numeric.corr(min_periods=3)
        for left_index, left in enumerate(fields):
            for right in fields[left_index + 1 :]:
                value = correlation.loc[left, right]
                if pd.notna(value):
                    result[f"{dataset.dataset_id}:{left}~{right}"] = _finite(value)
    return result


def _coverage_warnings(dataset: _Dataset) -> list[str]:
    warnings = [*dataset.context.source_warnings, *dataset.context.quality_warnings]
    period_field = _period_field(dataset.frame, dataset.context)
    if period_field is None:
        warnings.append(f"Dataset {dataset.dataset_id} 未唯一识别期间字段，未计算趋势。")
    elif dataset.frame[period_field].isna().any():
        warnings.append(f"Dataset {dataset.dataset_id} 的期间字段 {period_field} 存在缺失值。")
    return warnings


def _period_field(frame: pd.DataFrame, context: DatasetAnalysisContext) -> str | None:
    if context.time_series_sort_field in frame.columns:
        return context.time_series_sort_field
    candidates = (
        "data_date",
        "date",
        "month",
        "period",
        "year_month",
        "年月",
        "月份",
        "期间",
        "日期",
    )
    by_casefold = {str(column).casefold(): str(column) for column in frame.columns}
    return next(
        (by_casefold[item.casefold()] for item in candidates if item.casefold() in by_casefold),
        None,
    )


def _metric_codes_by_ref(
    profile_metrics: tuple[Mapping[str, Any], ...],
) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for metric in profile_metrics:
        field_ref = metric.get("fieldRef")
        code = metric.get("code")
        if field_ref and code and metric.get("aggregation") != "ratio":
            result.setdefault(str(field_ref).casefold(), []).append(str(code))
    return {key: tuple(values) for key, values in result.items()}


def _metric_unit(semantic: Mapping[str, Any]) -> str | None:
    unit = semantic.get("unit")
    return str(unit) if unit not in {None, ""} else None


def _formula(field: str, aggregation: Aggregation, scope: Mapping[str, str]) -> str:
    predicate = " AND ".join(f"{column}='{value}'" for column, value in sorted(scope.items()))
    return f"{aggregation}({field})" + (f" WHERE {predicate}" if predicate else "")


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("确定性指标出现非有限数值")
    return number


def _optional_finite(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None
