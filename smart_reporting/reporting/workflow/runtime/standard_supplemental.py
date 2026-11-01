"""服务端标准补证计算的窄接口。

输入必须已经通过当前分析的 dataset、字段和期间授权；本模块不解析自由文本公式，
也不访问数据库或工作区路径。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from statistics import median
from typing import Any, Literal, get_args

import polars as pl
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from ...hospital_operation.deterministic_analysis import (
    additive_group_totals,
    apply_metric_scope,
    metric_comparison_period_key,
    metric_period_key,
    read_analysis_csv,
    reconciliation_passes,
)
from ...units import unit_conversion_scale
from .standard_supplemental_input import BatchAnalysisInputCache

StandardSupplementalOperation = Literal[
    "group_summary", "group_period_series", "cross_group_summary",
    "period_comparison", "group_ratio", "group_period_comparison", "group_concentration",
]
STANDARD_SUPPLEMENTAL_OPERATIONS: tuple[StandardSupplementalOperation, ...] = get_args(StandardSupplementalOperation)
STANDARD_CANDIDATE_LIMIT = 40
STANDARD_CANDIDATE_BYTES = 24_000
STANDARD_GROUPING_SOURCE_BYTES = 12_000
STANDARD_RECONCILIATION_LIMIT = 100


def _require_dimension_unless_ungrouped_comparison(spec: Any) -> None:
    """目录 Spec 与执行 Request 共用：仅无交叉维度的逐期 period_comparison 可省略 dimensionField。"""
    if spec.dimension_field is None and not (
        spec.operation == "period_comparison" and spec.group_by_period
        and spec.secondary_dimension_field is None
    ):
        raise ValueError("只有无交叉维度的逐期 period_comparison 可以不提供 dimensionField")


class StandardSupplementalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    operation: StandardSupplementalOperation
    dataset_id: str = Field(min_length=1, alias="datasetId")
    baseline_dataset_id: str | None = Field(default=None, min_length=1, alias="baselineDatasetId")
    output_name: str = Field(min_length=1, alias="outputName")
    metric_codes: tuple[str, ...] = Field(default=(), alias="metricCodes")
    measure_field: str = Field(min_length=1, alias="measureField")
    denominator_field: str | None = Field(default=None, min_length=1, alias="denominatorField")
    measure_unit: str | None = Field(default=None, min_length=1, alias="measureUnit")
    dimension_field: str | None = Field(default=None, min_length=1, alias="dimensionField")
    secondary_dimension_field: str | None = Field(
        default=None, min_length=1, alias="secondaryDimensionField",
    )
    period_field: str = Field(min_length=1, alias="periodField")
    period_granularity: Literal["day", "month", "year"] | None = Field(default=None, alias="periodGranularity")
    current_periods: tuple[str, ...] = Field(min_length=1, alias="currentPeriods")
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    baseline_method: Literal["previous_period", "mean", "median"] | None = Field(
        default=None, alias="baselineMethod", exclude_if=lambda value: value is None,
    )
    change_rate_denominator: Literal["signed", "absolute"] = Field(
        default="signed", alias="changeRateDenominator", exclude_if=lambda value: value == "signed",
    )
    rank_by: Literal["absolute_change_desc", "change_desc"] = Field(
        default="absolute_change_desc", alias="rankBy", exclude_if=lambda value: value == "absolute_change_desc",
    )
    include_period_change: bool = Field(
        default=False, alias="includePeriodChange", exclude_if=lambda value: not value,
    )
    include_marginal_shares: bool = Field(
        default=False, alias="includeMarginalShares", exclude_if=lambda value: not value,
    )
    group_by_period: bool = Field(
        default=False, alias="groupByPeriod", exclude_if=lambda value: not value,
    )
    parent_total: float = Field(alias="parentTotal")
    parent_period_totals: tuple[float, ...] = Field(default=(), alias="parentPeriodTotals")
    baseline_period_totals: tuple[float, ...] = Field(
        default=(), alias="baselinePeriodTotals", exclude_if=lambda value: not value,
    )
    baseline_parent_total: float | None = Field(default=None, alias="baselineParentTotal")
    denominator_parent_total: float | None = Field(default=None, alias="denominatorParentTotal")
    denominator_period_totals: tuple[float, ...] = Field(
        default=(), alias="denominatorPeriodTotals", exclude_if=lambda value: not value,
    )
    denominator_scale: float | None = Field(default=None, gt=0, alias="denominatorScale")
    ratio_fact_id: str | None = Field(default=None, min_length=1, alias="ratioFactId")
    scope: dict[str, str] = Field(default_factory=dict)
    query_bound_scope_fields: tuple[str, ...] = Field(
        default=(), alias="queryBoundScopeFields", exclude_if=lambda value: not value,
    )
    baseline_query_bound_scope_fields: tuple[str, ...] = Field(
        default=(), alias="baselineQueryBoundScopeFields", exclude_if=lambda value: not value,
    )

    @model_validator(mode="after")
    def require_baseline_for_comparison(self) -> StandardSupplementalRequest:
        _require_dimension_unless_ungrouped_comparison(self)
        if self.change_rate_denominator != "signed" and not (
            self.operation in {"period_comparison", "group_period_comparison"}
            or self.operation == "group_period_series" and self.include_period_change
        ):
            raise ValueError("只有比较计算接受 changeRateDenominator")
        if self.rank_by != "absolute_change_desc" and self.operation not in {"group_period_comparison", "period_comparison"}:
            raise ValueError("只有期间比较接受 rankBy")
        if self.include_period_change and self.operation != "group_period_series":
            raise ValueError("只有 group_period_series 接受 includePeriodChange")
        if self.include_marginal_shares and self.operation != "cross_group_summary":
            raise ValueError("只有 cross_group_summary 接受 includeMarginalShares")
        if self.group_by_period and self.operation not in {"cross_group_summary", "group_ratio", "period_comparison"}:
            raise ValueError("只有交叉分组、分组比率和期间比较接受 groupByPeriod")
        if self.operation == "group_ratio" and self.group_by_period:
            if len(self.denominator_period_totals) != len(self.current_periods):
                raise ValueError("逐期 group_ratio 必须为每个期间提供 denominatorPeriodTotals")
        elif self.denominator_period_totals:
            raise ValueError("只有逐期 group_ratio 接受 denominatorPeriodTotals")
        if self.operation == "group_period_comparison":
            if self.baseline_method is None or not self.baseline_periods:
                raise ValueError("group_period_comparison 必须提供 baselineMethod 和 baselinePeriods")
            if len(self.baseline_period_totals) != len(self.baseline_periods):
                raise ValueError("group_period_comparison 必须提供逐期 baselinePeriodTotals")
        elif self.operation == "period_comparison" and self.group_by_period:
            if self.baseline_method is not None:
                raise ValueError("逐期期间比较不接受 baselineMethod")
            if len(self.baseline_period_totals) != len(self.baseline_periods):
                raise ValueError("逐期 period_comparison 必须提供逐期 baselinePeriodTotals")
        elif self.baseline_method is not None or self.baseline_period_totals:
            raise ValueError("只有 group_period_comparison 接受基准方法与逐期基准总额")
        if self.baseline_dataset_id is not None and self.operation != "period_comparison":
            raise ValueError("只有 period_comparison 接受 baselineDatasetId")
        if self.baseline_query_bound_scope_fields and self.baseline_dataset_id is None:
            raise ValueError("独立对照范围必须绑定 baselineDatasetId")
        if self.operation == "period_comparison" and not self.baseline_periods:
            raise ValueError("period_comparison 必须提供 baselinePeriods")
        if self.operation == "period_comparison" and self.baseline_parent_total is None:
            raise ValueError("period_comparison 必须提供 baselineParentTotal")
        if self.operation == "group_ratio" and (
            self.denominator_field is None
            or self.denominator_parent_total is None
            or self.denominator_scale is None
            or self.ratio_fact_id is None
        ):
            raise ValueError(
                "group_ratio 必须提供 denominatorField、denominatorParentTotal、denominatorScale 和 ratioFactId"
            )
        if self.operation != "group_ratio" and any(value is not None for value in (
            self.denominator_field, self.denominator_parent_total, self.denominator_scale, self.ratio_fact_id,
        )):
            raise ValueError("只有 group_ratio 接受分母参数")
        if self.operation in {"cross_group_summary", "period_comparison"}:
            if self.operation == "cross_group_summary" and self.secondary_dimension_field is None:
                raise ValueError("cross_group_summary 必须提供 secondaryDimensionField")
            if self.secondary_dimension_field is not None and self.secondary_dimension_field in {
                self.measure_field, self.dimension_field, self.period_field,
                self.denominator_field,
            }:
                raise ValueError("交叉维度必须与度量、主维度和期间字段不同")
        elif self.secondary_dimension_field is not None:
            raise ValueError("只有 cross_group_summary 和 period_comparison 接受 secondaryDimensionField")
        if self.operation in {"group_period_series", "group_period_comparison"} or self.group_by_period:
            if len(self.parent_period_totals) != len(self.current_periods):
                raise ValueError(f"{self.operation} 必须为每个期间提供 parentPeriodTotals")
        elif self.parent_period_totals:
            raise ValueError("只有逐期分组计算接受 parentPeriodTotals")
        current_keys = [metric_period_key(label, self.period_granularity) for label in self.current_periods]
        baseline_keys = ([metric_period_key(label, self.period_granularity) for label in self.baseline_periods]
                         if self.operation in {"period_comparison", "group_period_comparison"} else [])
        keys = [*current_keys, *baseline_keys]
        if None in keys or len({key[0] for key in keys if key is not None}) != 1:
            raise ValueError("标准补证期间必须可解析且粒度相同")
        duplicate_periods = (
            len(current_keys) != len(set(current_keys)) or len(baseline_keys) != len(set(baseline_keys))
            if self.operation == "group_period_comparison" else len(keys) != len(set(keys))
        )
        if duplicate_periods:
            raise ValueError("标准补证期间不能重复或重叠（含期间别名）")
        if self.operation == "period_comparison" and self.group_by_period:
            _aligned_baseline_periods(self.current_periods, self.baseline_periods, self.period_granularity)
        for fields in (self.query_bound_scope_fields, self.baseline_query_bound_scope_fields):
            if len(fields) != len(set(fields)) or not set(fields).issubset(self.scope):
                raise ValueError("查询固定范围字段必须唯一且属于 scope")
        return self


class StandardSupplementalSpec(BaseModel):
    """结构化路由声明；父总额只引用冻结 deterministic fact，不接受模型数值。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    operation: StandardSupplementalOperation
    measure_field: str = Field(min_length=1, alias="measureField")
    denominator_field: str | None = Field(default=None, min_length=1, alias="denominatorField")
    dimension_field: str | None = Field(default=None, min_length=1, alias="dimensionField")
    secondary_dimension_field: str | None = Field(
        default=None, min_length=1, alias="secondaryDimensionField",
    )
    period_field: str = Field(min_length=1, alias="periodField")
    current_periods: tuple[str, ...] = Field(min_length=1, alias="currentPeriods")
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    baseline_method: Literal["previous_period", "mean", "median"] | None = Field(
        default=None, alias="baselineMethod", exclude_if=lambda value: value is None,
    )
    change_rate_denominator: Literal["signed", "absolute"] = Field(
        default="signed", alias="changeRateDenominator", exclude_if=lambda value: value == "signed",
    )
    rank_by: Literal["absolute_change_desc", "change_desc"] = Field(
        default="absolute_change_desc", alias="rankBy", exclude_if=lambda value: value == "absolute_change_desc",
    )
    include_period_change: bool = Field(
        default=False, alias="includePeriodChange", exclude_if=lambda value: not value,
    )
    include_marginal_shares: bool = Field(
        default=False, alias="includeMarginalShares", exclude_if=lambda value: not value,
    )
    group_by_period: bool = Field(
        default=False, alias="groupByPeriod", exclude_if=lambda value: not value,
    )
    parent_fact_id: str = Field(min_length=1, alias="parentFactId")
    baseline_parent_fact_id: str | None = Field(default=None, alias="baselineParentFactId")
    baseline_dataset_id: str | None = Field(default=None, min_length=1, alias="baselineDatasetId")
    denominator_parent_fact_id: str | None = Field(
        default=None, min_length=1, alias="denominatorParentFactId",
    )
    ratio_fact_id: str | None = Field(default=None, min_length=1, alias="ratioFactId")

    @model_validator(mode="after")
    def validate_periods_and_parent_refs(self) -> StandardSupplementalSpec:
        _require_dimension_unless_ungrouped_comparison(self)
        if self.change_rate_denominator != "signed" and not (
            self.operation in {"period_comparison", "group_period_comparison"}
            or self.operation == "group_period_series" and self.include_period_change
        ):
            raise ValueError("只有比较计算接受 changeRateDenominator")
        if self.rank_by != "absolute_change_desc" and self.operation not in {"group_period_comparison", "period_comparison"}:
            raise ValueError("只有期间比较接受 rankBy")
        if self.include_period_change and self.operation != "group_period_series":
            raise ValueError("只有 group_period_series 接受 includePeriodChange")
        if self.include_marginal_shares and self.operation != "cross_group_summary":
            raise ValueError("只有 cross_group_summary 接受 includeMarginalShares")
        if self.group_by_period and self.operation not in {"cross_group_summary", "group_ratio", "period_comparison"}:
            raise ValueError("只有交叉分组、分组比率和期间比较接受 groupByPeriod")
        if self.operation == "group_period_comparison":
            if self.baseline_method is None or not self.baseline_periods:
                raise ValueError("group_period_comparison 必须提供 baselineMethod 和 baselinePeriods")
            if self.baseline_parent_fact_id is not None or self.baseline_dataset_id is not None:
                raise ValueError("逐期基准比较必须使用同一冻结父事实")
        elif self.baseline_method is not None:
            raise ValueError("只有 group_period_comparison 接受 baselineMethod")
        if len(self.current_periods) != len(set(self.current_periods)):
            raise ValueError("currentPeriods 不能重复")
        if len(self.baseline_periods) != len(set(self.baseline_periods)):
            raise ValueError("baselinePeriods 不能重复")
        if self.operation != "group_period_comparison" and set(self.current_periods) & set(self.baseline_periods):
            raise ValueError("当前期间和对照期间不能重叠")
        if self.operation == "period_comparison":
            if not self.baseline_periods:
                raise ValueError("period_comparison 必须提供 baselinePeriods")
            if len(self.current_periods) != len(self.baseline_periods):
                raise ValueError("当前期间与对照期间粒度数必须一致")
        elif self.operation != "group_period_comparison" and (
            self.baseline_periods or self.baseline_parent_fact_id is not None or self.baseline_dataset_id is not None
        ):
            raise ValueError(f"{self.operation} 不接受对照期间")
        if self.operation == "group_ratio":
            if (
                self.denominator_field is None
                or self.denominator_parent_fact_id is None
                or self.ratio_fact_id is None
            ):
                raise ValueError(
                    "group_ratio 必须提供 denominatorField、denominatorParentFactId 和 ratioFactId"
                )
            if self.denominator_field == self.measure_field:
                raise ValueError("group_ratio 的分子和分母字段不能相同")
        elif any(value is not None for value in (
            self.denominator_field, self.denominator_parent_fact_id, self.ratio_fact_id,
        )):
            raise ValueError("只有 group_ratio 接受分母字段、分母父事实和比率事实")
        if self.operation in {"cross_group_summary", "period_comparison"}:
            if self.operation == "cross_group_summary" and self.secondary_dimension_field is None:
                raise ValueError("cross_group_summary 必须提供 secondaryDimensionField")
            if self.secondary_dimension_field is not None and self.secondary_dimension_field in {
                self.measure_field, self.dimension_field, self.period_field,
                self.denominator_field,
            }:
                raise ValueError("交叉维度必须与度量、主维度和期间字段不同")
        elif self.secondary_dimension_field is not None:
            raise ValueError("只有 cross_group_summary 和 period_comparison 接受 secondaryDimensionField")
        return self


def _standard_source_fields(spec: StandardSupplementalSpec | StandardSupplementalRequest) -> tuple[str, ...]:
    if spec.operation == "group_concentration":
        return (spec.period_field,)
    dimensions: tuple[str, ...] = (spec.dimension_field,) if spec.dimension_field is not None else ()
    if spec.secondary_dimension_field is not None:
        dimensions += (spec.secondary_dimension_field,)
    if spec.operation in {"group_period_series", "group_period_comparison"} or spec.group_by_period:
        return (spec.period_field, *dimensions)
    return dimensions


def standard_output_columns(spec: StandardSupplementalSpec | StandardSupplementalRequest) -> tuple[str, ...]:
    """目录、契约与执行共用列定义；源字段碰撞时别名，不改派生列语义。"""
    derived: tuple[str, ...]
    if spec.operation == "group_concentration":
        derived = ("cr5", "hhi", "top5_amount", "total_amount", "group_count", "missing_amount")
    elif spec.operation == "group_summary":
        derived = ("value", "rank", "share")
    elif spec.operation == "group_period_series":
        derived = ("value", "rank", "share", *(
            ("previous", "change", "changeRate") if spec.include_period_change else ()
        ))
    elif spec.operation == "cross_group_summary":
        derived = (
            "value", "rank", "share",
            *(("primaryTotal", "primaryShare", "secondaryTotal", "secondaryShare")
              if spec.include_marginal_shares else ()),
        )
    elif spec.operation == "group_period_comparison":
        derived = (
            "current", "baseline", "change",
            "changeRate", "contribution", "rank", "baselineTotal", "totalChange",
        )
    elif spec.operation == "period_comparison":
        derived = ("current", "baseline", "change", "changeRate", "contribution", "rank")
        if spec.secondary_dimension_field is not None:
            derived += ("primaryChange", "primaryContribution", "primaryRank")
    else:
        derived = ("numerator", "denominator", "difference", "ratio")
    sources = _standard_source_fields(spec)
    used = set(sources) | set(derived)
    columns = []
    for field in sources:
        column = field
        if column in derived:
            role = "period" if field == spec.period_field else "dimension"
            base = f"{role}_{field}"
            column, suffix = base, 2
            while column in used:
                column, suffix = f"{base}_{suffix}", suffix + 1
            used.add(column)
        columns.append(column)
    return (*columns, *derived)


def compact_standard_reconciliations(checks: Sequence[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """仅压缩顶层数量；每项原始检查与失败原因完整保留，不放宽证据契约。"""
    if len(checks) <= STANDARD_RECONCILIATION_LIMIT:
        return list(checks)
    return [{"name": name, "passed": all(check["passed"] for check in checks), "checks": list(checks)}]


def _aligned_baseline_periods(
    current: Sequence[str], baseline: Sequence[str], grain: str | None,
) -> tuple[str, ...]:
    """按同一日历角色找完整配对，不把列表位置或相邻可用月份当成同期。"""
    labels = {metric_period_key(period, grain): period for period in baseline}
    if len(current) == len(baseline):
        for role in ("yoy", "mom"):
            keys = [metric_comparison_period_key(period, grain, role) for period in current]
            if None not in keys and len(set(keys)) == len(keys) and set(keys) == set(labels):
                return tuple(labels[key] for key in keys)
    raise ValueError("逐期期间比较必须提供完整且同角色的日历同期或相邻期间")


def _row_period_metadata(
    request: StandardSupplementalRequest, columns: Sequence[str], column_meta: dict[str, dict[str, Any]],
) -> None:
    """用显式行期间绑定精确窗口，不让单月值冒充整列累计窗口。"""
    sources = _standard_source_fields(request)
    available = (request.baseline_periods if request.operation == "group_period_comparison"
                 else request.current_periods)
    labels = {metric_period_key(period, request.period_granularity): period for period in available}

    def structured(periods: Sequence[str]) -> list[str]:
        keys = [metric_period_key(period, request.period_granularity) for period in periods]
        return list(dict.fromkeys(key[1].isoformat()[:{"year": 4, "month": 7, "day": 10}[key[0]]]
                                 for key in keys if key is not None))

    current = {period: structured((period,)) for period in request.current_periods}
    reference: dict[str, list[str]] = {}
    baseline_window = structured(request.baseline_periods)
    aligned = (dict(zip(request.current_periods, _aligned_baseline_periods(
        request.current_periods, request.baseline_periods, request.period_granularity,
    ), strict=True)) if request.operation == "period_comparison" else {})
    for period in request.current_periods:
        if aligned:
            reference[period] = structured((aligned[period],))
        elif request.operation == "group_period_comparison" and request.baseline_method != "previous_period":
            reference[period] = baseline_window
        else:
            previous = labels.get(metric_comparison_period_key(period, request.period_granularity, "mom"))
            reference[period] = structured((previous,)) if previous is not None else []
    combined = {period: list(dict.fromkeys((*current[period], *reference[period])))
                for period in request.current_periods}
    for column in columns[len(sources):]:
        if column == "rank":
            continue
        mapping = current
        if request.operation in {"group_period_comparison", "period_comparison"}:
            mapping = (current if column == "current" else reference
                       if column in {"baseline", "baselineTotal"} else combined)
            if request.operation == "period_comparison" and column == "contribution":
                mapping = {period: structured((*request.current_periods, *request.baseline_periods))
                           for period in request.current_periods}
        elif request.operation == "group_period_series":
            mapping = (reference if column == "previous" else combined
                       if column in {"change", "changeRate"} else current)
        column_meta.setdefault(column, {})["periodsByRowPeriod"] = mapping


def run_standard_supplemental(
    *,
    analysis_id: str,
    dataset_ids: Sequence[str],
    authorized_fields: Sequence[str],
    csv_content: bytes,
    request: StandardSupplementalRequest,
    authorized_query_scope: Mapping[str, str] | None = None,
    baseline_csv_content: bytes | None = None,
    baseline_authorized_fields: Sequence[str] = (),
    baseline_authorized_query_scope: Mapping[str, str] | None = None,
    _input_cache: BatchAnalysisInputCache | None = None,
) -> dict[str, Any]:
    """计算授权可加指标的分组、逐期比较、交叉构成及登记比率，不推断业务主题。"""

    if request.dataset_id not in set(dataset_ids) or (
        request.baseline_dataset_id is not None and request.baseline_dataset_id not in set(dataset_ids)
    ):
        raise ValueError("请求引用了未授权 dataset")

    def scoped_frame(content: bytes, fields: Sequence[str], bound_fields: Sequence[str],
                     query_scope: Mapping[str, str] | None) -> pl.DataFrame:
        if any((query_scope or {}).get(field) != request.scope[field] for field in bound_fields):
            raise ValueError("请求引用了未授权的查询固定范围")
        required_fields = {
            request.measure_field, request.dimension_field, request.period_field,
            *(set(request.scope) - set(bound_fields)),
        } - {None}
        if request.secondary_dimension_field is not None:
            required_fields.add(request.secondary_dimension_field)
        if request.denominator_field is not None:
            required_fields.add(request.denominator_field)
        unauthorized = required_fields - set(fields)
        if unauthorized:
            raise ValueError(f"请求引用了未授权字段: {sorted(unauthorized)}")
        try:
            frame = read_analysis_csv(content) if _input_cache is None else _input_cache.read(content)
        except (UnicodeDecodeError, pl.exceptions.PolarsError) as error:
            raise ValueError("授权 CSV 无法解析") from error
        missing = required_fields - set(frame.columns)
        if missing:
            raise ValueError(f"CSV 缺少请求字段: {sorted(missing)}")
        return apply_metric_scope(frame, {
            field: value for field, value in request.scope.items() if field not in bound_fields
        })

    frame = scoped_frame(csv_content, authorized_fields, request.query_bound_scope_fields, authorized_query_scope)

    rows, warnings = _read_rows(
        frame, request,
        periods=request.current_periods if request.baseline_dataset_id is not None else None,
    )
    baseline_rows = None
    if request.baseline_dataset_id is not None:
        if baseline_csv_content is None:
            raise ValueError("独立对照 dataset 缺少 CSV")
        baseline_frame = scoped_frame(
            baseline_csv_content, baseline_authorized_fields,
            request.baseline_query_bound_scope_fields, baseline_authorized_query_scope,
        )
        baseline_rows, baseline_warnings = _read_rows(
            baseline_frame, request, periods=request.baseline_periods,
        )
        warnings.extend(baseline_warnings)
    elif baseline_csv_content is not None:
        raise ValueError("独立对照 CSV 必须绑定 baselineDatasetId")
    cross_comparison = request.operation == "period_comparison" and request.secondary_dimension_field is not None
    if cross_comparison:
        # 复用单维比较的配对、缺失值和全窗贡献算法；JSON 元组键避免维度值拼接碰撞。
        def paired(source: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
            return [{**row, "dimension": json.dumps(
                [row["dimension"], row["secondary_dimension"]], ensure_ascii=False, separators=(",", ":"),
            )} for row in source]

        rows = paired(rows)
        baseline_rows = paired(baseline_rows) if baseline_rows is not None else None
    column_meta: dict[str, dict[str, Any]]
    amount_columns: tuple[str, ...]
    if request.operation == "group_concentration":
        # 始终读取授权期间的全量分组，不以 TopN 截断结果充当总体。
        current_rows = [row for row in rows if row["period"] in request.current_periods]
        grouped, total = _group_totals(current_rows)
        ordered = sorted(
            ((name, value) for name, value in grouped.items() if name is not None and name.strip()),
            key=lambda item: (-item[1], item[0]),
        )
        missing_amount = math.fsum(value for name, value in grouped.items() if name is None or not name.strip())
        reconciliations = [_reconciliation(request.output_name + "_total", total, request.parent_total)]
        invalid = bool(warnings)
        if invalid:
            warnings.append("存在无效数据或未归属记录，集中度保留为空")
        if len(ordered) != len(grouped):
            invalid = True
            warnings.append("存在缺失分组归属，金额保留在总额中，CR5、HHI 保留为空")
        if {row["period"] for row in current_rows} != set(request.current_periods):
            invalid = True
            warnings.append("请求期间数据不完整，不将缺失期间当作零，CR5、HHI 保留为空")
        if not reconciliations[0]["passed"]:
            invalid = True
            warnings.append("集中度总体与冻结父指标总额对账不闭合，CR5、HHI 保留为空")
        if total <= 0:
            invalid = True
            warnings.append("集中度总额非正，CR5、HHI 保留为空")
        top5_amount = math.fsum(value for _, value in ordered[:5])
        cr5 = top5_amount / total if not invalid else None
        negative = any(value < 0 for _, value in ordered)
        if negative:
            warnings.append("存在负净额分组，CR5 按原始净额计算；经典 HHI 不适用，保留为空")
        hhi = math.fsum((value / total) ** 2 for _, value in ordered) if not invalid and not negative else None
        finding_rows = [[
            "、".join(request.current_periods), cr5, hhi, top5_amount, total, len(ordered), missing_amount,
        ]]
        column_meta = {"cr5": {"unit": "%", "isPercent": False}, "hhi": {"unit": "0—1"}}
        amount_columns = ("top5_amount", "total_amount", "missing_amount")
    elif request.operation == "group_summary":
        current_periods = set(request.current_periods)
        current_rows = [row for row in rows if row["period"] in current_periods]
        if not current_rows:
            warnings.append("当前期间没有数据")
        finding_rows, total, group_total = _group_rows(current_rows, warnings)
        if not finding_rows:
            warnings.append("当前期间没有可计算的有效分组")
        if total == 0:
            warnings.append("分组占比分母为零，share 保留为空")
        reconciliations = [_reconciliation(request.output_name + "_total", group_total, request.parent_total)]
        if not reconciliations[0]["passed"]:
            warnings.append("分组结果与父指标总额不闭合，保留结果并产生软告警")
        column_meta = {"rank": {"unit": "名"}, "share": {"unit": "%", "isPercent": False}}
        amount_columns = ("value",)
    elif request.operation == "group_period_series":
        finding_rows, period_totals = _period_group_rows(
            rows, request, warnings,
        )
        if not finding_rows:
            warnings.append("当前期间没有可计算的分组趋势")
        reconciliations = [
            _reconciliation(
                f"{request.output_name}_{period}_total",
                period_totals.get(period, 0.0),
                expected,
            )
            for period, expected in zip(
                request.current_periods, request.parent_period_totals, strict=True,
            )
        ]
        reconciliations.append(_reconciliation(
            request.output_name + "_total",
            math.fsum(period_totals.values()),
            request.parent_total,
        ))
        if any(not item["passed"] for item in reconciliations):
            warnings.append("期间分组结果与冻结逐期总额不闭合，保留结果并产生软告警")
        column_meta = {"rank": {"unit": "名"}, "share": {"unit": "%", "isPercent": False}}
        amount_columns = ("value",)
        if request.include_period_change:
            amount_columns += ("previous", "change")
            column_meta["changeRate"] = {"unit": "%", "isPercent": False}
    elif request.operation == "cross_group_summary":
        assert request.secondary_dimension_field is not None
        if request.group_by_period:
            finding_rows = []
            reconciliations = []
            cross_period_totals: list[float] = []
            period_rows_by_label = _rows_by_period(rows)
            for period, expected in zip(request.current_periods, request.parent_period_totals, strict=True):
                period_rows, total = _cross_group_rows(
                    period_rows_by_label.get(period, ()), request.include_marginal_shares, warnings,
                )
                finding_rows.extend([period, *row] for row in period_rows)
                cross_period_totals.append(total)
                reconciliations.append(_reconciliation(f"{request.output_name}_{period}_total", total, expected))
            group_total = math.fsum(cross_period_totals)
        else:
            finding_rows, group_total = _cross_group_rows(rows, request.include_marginal_shares, warnings)
            reconciliations = []
        if not finding_rows:
            warnings.append("当前期间没有可计算的交叉分组")
        reconciliations.append(_reconciliation(request.output_name + "_total", group_total, request.parent_total))
        if any(not item["passed"] for item in reconciliations):
            warnings.append("交叉分组结果与父指标总额不闭合，保留结果并产生软告警")
        column_meta = {"rank": {"unit": "名"}, "share": {"unit": "%", "isPercent": False}}
        amount_columns = ("value",)
        if request.include_marginal_shares:
            amount_columns += ("primaryTotal", "secondaryTotal")
            column_meta.update({
                name: {"unit": "%", "isPercent": False}
                for name in ("primaryShare", "secondaryShare")
            })
    elif request.operation == "group_period_comparison":
        finding_rows, reconciliations = _baseline_comparison_rows(rows, request, warnings)
        column_meta = {
            "rank": {"unit": "名"},
            "changeRate": {"unit": "%", "isPercent": False},
            "contribution": {"unit": "%", "isPercent": False},
        }
        amount_columns = ("current", "baseline", "change", "baselineTotal", "totalChange")
    elif request.operation == "period_comparison" and request.group_by_period:
        finding_rows, reconciliations = _period_comparison_rows(rows, baseline_rows, request, warnings)
        column_meta = {
            "rank": {"unit": "名"},
            "changeRate": {"unit": "%", "isPercent": False},
            "contribution": {"unit": "%", "isPercent": False},
        }
        amount_columns = ("current", "baseline", "change")
    elif request.operation == "period_comparison":
        assert request.baseline_parent_total is not None
        finding_rows, current_total, baseline_total, current_sum, baseline_sum = _comparison_rows(
            rows, request.current_periods, request.baseline_periods, warnings,
            baseline_rows=baseline_rows,
            change_rate_denominator=request.change_rate_denominator,
        )
        finding_rows.sort(key=lambda row: (
            row[3] is None, -(abs(row[3]) if request.rank_by == "absolute_change_desc" else row[3])
            if row[3] is not None else 0, row[0] is None, row[0] or "",
        ))
        finding_rows = [[*row, rank] for rank, row in enumerate(finding_rows, start=1)]
        if not finding_rows:
            warnings.append("当前期间与对照期间没有可比较的有效分组")
        reconciliations = [
            _reconciliation(request.output_name + "_current_total", current_sum, request.parent_total),
            _reconciliation(request.output_name + "_baseline_total", baseline_sum, request.baseline_parent_total),
        ]
        if any(not item["passed"] for item in reconciliations):
            warnings.append("期间比较结果与父指标总额不闭合，保留结果并产生软告警")
        column_meta = {
            "rank": {"unit": "名"},
            "changeRate": {"unit": "%", "isPercent": False},
            "contribution": {"unit": "%", "isPercent": False},
        }
        amount_columns = ("current", "baseline", "change")
    else:
        assert request.denominator_field is not None
        assert request.denominator_parent_total is not None
        assert request.denominator_scale is not None
        reconciliations = []
        if request.group_by_period:
            finding_rows = []
            period_rows_by_label = _rows_by_period(rows)
            numerator_totals: list[float] = []
            denominator_totals: list[float] = []
            for period, numerator_expected, denominator_expected in zip(
                request.current_periods, request.parent_period_totals,
                request.denominator_period_totals, strict=True,
            ):
                ratio_rows, numerator_period_total, denominator_period_total = _ratio_rows(
                    period_rows_by_label.get(period, ()), (period,), request.denominator_scale, warnings,
                )
                finding_rows.extend([period, *row] for row in ratio_rows)
                numerator_totals.append(numerator_period_total)
                denominator_totals.append(denominator_period_total)
                reconciliations.extend((
                    _reconciliation(f"{request.output_name}_{period}_numerator_total",
                                    numerator_period_total, numerator_expected),
                    _reconciliation(f"{request.output_name}_{period}_denominator_total",
                                    denominator_period_total, denominator_expected),
                ))
                if not ratio_rows:
                    warnings.append(f"期间 {period} 没有可计算的有效分组比率")
            numerator_total = math.fsum(numerator_totals)
            denominator_total = math.fsum(denominator_totals)
        else:
            finding_rows, numerator_total, denominator_total = _ratio_rows(
                rows, request.current_periods, request.denominator_scale, warnings,
            )
        if not finding_rows:
            warnings.append("当前期间没有可计算的有效分组比率")
        reconciliations.extend((
            _reconciliation(request.output_name + "_numerator_total", numerator_total, request.parent_total),
            _reconciliation(
                request.output_name + "_denominator_total",
                denominator_total,
                request.denominator_parent_total,
            ),
        ))
        if any(not item["passed"] for item in reconciliations):
            warnings.append("分组比率结果与分子或分母父指标总额不闭合，保留结果并产生软告警")
        column_meta = {"ratio": {"unit": "%", "isPercent": False}}
        amount_columns = ("numerator", "denominator", "difference")

    if cross_comparison:
        finding_rows = _cross_comparison_columns(finding_rows, request, warnings)
        amount_columns += ("primaryChange",)
        column_meta.update({
            "primaryContribution": {"unit": "%", "isPercent": False},
            "primaryRank": {"unit": "名"},
        })
    columns = list(standard_output_columns(request))
    source_columns = columns[:len(_standard_source_fields(request))]
    for field, column in zip(_standard_source_fields(request), source_columns, strict=True):
        if field != column:
            column_meta[column] = {"sourceField": field}
    if request.measure_unit is not None:
        column_meta.update({column: {"unit": request.measure_unit} for column in amount_columns})
    # 此补证执行器只接受已授权可加量；仅给真正分组求和列登记维度，
    # 份额、均值基准和逐行重复的边际合计不能继承这份证明。
    if request.operation in {"group_summary", "group_period_series", "cross_group_summary"}:
        column_meta.setdefault("value", {})["measureSemantic"] = {
            "aggregation": "sum", "additiveAcross": list(source_columns),
        }
    periods = list(request.current_periods)
    if request.operation in {"period_comparison", "group_period_comparison"}:
        periods = list(dict.fromkeys((*periods, *request.baseline_periods)))
    if request.operation in {"period_comparison", "group_period_comparison"}:
        reference_periods = request.baseline_periods
        if request.baseline_method == "previous_period":
            prior_keys = {metric_comparison_period_key(period, request.period_granularity, "mom")
                          for period in request.current_periods}
            reference_periods = tuple(period for period in reference_periods
                                      if metric_period_key(period, request.period_granularity) in prior_keys)
        comparison_periods = list(dict.fromkeys((*request.current_periods, *reference_periods)))
        for column in columns:
            if column in {*source_columns, "rank"}:
                continue
            selected_periods = (request.current_periods if column == "current" else
                                reference_periods if column in {"baseline", "baselineTotal"} else comparison_periods)
            column_meta.setdefault(column, {}).update(periods=list(selected_periods))
        column_meta["current"]["periodRoles"] = ["current"]
        column_meta["baseline"]["periodRoles"] = ["prior"]
    has_row_period = request.operation in {"group_period_series", "group_period_comparison"} or request.group_by_period
    if has_row_period:
        _row_period_metadata(request, columns, column_meta)

    logger.bind(analysis_id=analysis_id, operation=request.operation).info(
        "report_standard_supplemental_completed rows={} warnings={}",
        len(finding_rows), len(warnings),
    )
    finding: dict[str, Any] = {
        "name": request.output_name, "columns": columns, "columnMeta": column_meta,
        "scope": dict(request.scope), "periodGranularity": request.period_granularity,
        "periods": periods, "rows": finding_rows, "rowKeyColumns": list(source_columns),
    }
    if request.metric_codes:
        finding["metricCodes"] = list(request.metric_codes)
    if request.operation == "group_concentration":
        finding["top5Units"] = [name for name, _ in ordered[:5]]
        finding["formula"] = "CR5=前五名分组净额合计/全量总额；HHI=Σ(各分组净额/全量总额)^2（未乘10000）"
    if has_row_period:
        finding["rowPeriodColumn"] = columns[0]
    if request.operation == "group_period_comparison":
        finding["comparison"] = {
            "baselineMethod": request.baseline_method,
            "baselinePeriods": list(request.baseline_periods),
            "currentPeriods": list(request.current_periods),
            "rankBy": request.rank_by,
        }
    if request.operation == "period_comparison" and request.group_by_period:
        finding["comparison"] = {
            "groupByPeriod": True, "rankBy": request.rank_by,
            "currentPeriods": list(request.current_periods),
            "baselinePeriods": list(request.baseline_periods),
            "contributionScope": "window_total_change", "rankScope": "window",
        }
    if request.change_rate_denominator != "signed":
        finding.setdefault("comparison", {})["changeRateDenominator"] = request.change_rate_denominator
    if request.operation == "period_comparison" and not request.group_by_period and request.rank_by != "absolute_change_desc":
        finding.setdefault("comparison", {})["rankBy"] = request.rank_by
    if cross_comparison:
        finding.setdefault("comparison", {}).update(
            primaryDimensionField=request.dimension_field,
            primaryScope="row_period_primary" if request.group_by_period else "window_primary",
            primaryRankBy=request.rank_by, contributionScope="window_total_change",
        )
    return {
        "findings": [finding],
        "reconciliations": compact_standard_reconciliations(reconciliations, request.output_name + "_checks"),
        "warnings": list(dict.fromkeys(warnings))[:100],
    }


def standard_grouping_periods_supported(fact: Any, periods: Sequence[str]) -> bool:
    """单期分组不需要跨期可加证明；多期只能使用已冻结的 sum 口径。"""
    return (getattr(fact, "aggregation", None) == "sum"
            and getattr(fact, "cumulative_policy", None) is None
            and bool(periods)
            and (getattr(fact, "period_aggregation", None) == "sum" or len(periods) == 1))


def frozen_period_total(fact: Any, periods: Sequence[str]) -> float:
    """Sum explicitly selected periods from the same frozen parent fact."""
    period_values = getattr(fact, "period_values", ())
    values = {
        item.period: float(item.value)
        for item in period_values
        if getattr(item, "period", None) is not None
        and math.isfinite(float(item.value))
    }
    missing = [period for period in periods if period not in values]
    if missing:
        raise ValueError(f"冻结父指标缺少请求期间: {missing[:8]}")
    total = math.fsum(values[period] for period in periods)
    if not math.isfinite(total):
        raise ValueError("冻结父指标期间汇总结果不可表示")
    return total


def build_standard_population_proof(
    *, csv_content: bytes, dataset_sha256: str, request: StandardSupplementalRequest,
    parent_fact: Any, finding: dict[str, Any],
    _input_cache: BatchAnalysisInputCache | None = None,
) -> dict[str, Any] | None:
    """从身份已核验的全量CSV复算成员；无效/遗漏行或父事实不一致不签完整性。

    可供旧产物离线复核；调用者仍须核验父事实文件及输出文件身份，不能将模型
    声明的 request/parent 当作可信输入。金额闭合仅是附加一致性检查。
    """
    if (request.operation != "group_summary" or not request.measure_unit
            or request.query_bound_scope_fields
            or hashlib.sha256(csv_content).hexdigest() != dataset_sha256
            or getattr(parent_fact, "dataset_sha256", None) != dataset_sha256
            or getattr(parent_fact, "dataset_id", None) != request.dataset_id
            or getattr(parent_fact, "field", None) != request.measure_field
            or getattr(parent_fact, "period_field", None) != request.period_field
            or getattr(parent_fact, "period_granularity", None) != request.period_granularity
            or getattr(parent_fact, "unit", None) != request.measure_unit
            or getattr(parent_fact, "scope", None) != request.scope
            or getattr(parent_fact, "aggregation", None) != "sum"
            or getattr(parent_fact, "period_aggregation", None) != "sum"
            or getattr(parent_fact, "cumulative_policy", None) is not None
            or not getattr(parent_fact, "fact_id", None)):
        return None
    frame = read_analysis_csv(csv_content) if _input_cache is None else _input_cache.read(csv_content)
    parent_periods = tuple(item.period for item in getattr(parent_fact, "period_values", ()))
    if (len(parent_periods) != len(request.current_periods)
            or set(parent_periods) != set(request.current_periods)):
        return None
    fields = {request.measure_field, request.dimension_field, request.period_field, *request.scope}
    if fields - set(frame.columns):
        return None
    scoped = apply_metric_scope(frame, request.scope)
    rows, warnings = _read_rows(scoped, request)
    if warnings:
        return None
    selected = [row for row in rows if row["period"] in request.current_periods]
    computed, total, _ = _group_rows(selected, [])
    if (not computed or finding.get("columns") != list(standard_output_columns(request))
            or finding.get("rows") != computed
            or finding.get("scope") != request.scope
            or finding.get("periods") != list(request.current_periods)
            or finding.get("columnMeta", {}).get("value", {}).get("unit") != request.measure_unit
            or request.parent_total != frozen_period_total(parent_fact, request.current_periods)
            or not reconciliation_passes(total, frozen_period_total(parent_fact, request.current_periods),
                                         absolute_tolerance=1e-9, relative_tolerance=1e-12)):
        return None
    members = sorted(row[0] for row in computed)
    encoded = json.dumps(members, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "version": "standard-population-v1", "tablePointer": "/findings/0",
        "datasetId": request.dataset_id, "datasetSha256": dataset_sha256,
        "populationFactId": parent_fact.fact_id, "scope": dict(request.scope),
        "periodGranularity": request.period_granularity,
        "periods": list(request.current_periods), "dimensionField": standard_output_columns(request)[0],
        "measureField": request.measure_field, "unit": request.measure_unit,
        "members": members, "membersSha256": hashlib.sha256(encoded).hexdigest(),
        "memberCount": len(members), "sourceRowCount": frame.height,
        "selectedRowCount": len(selected), "invalidRowCount": 0, "completePopulation": True,
    }


def _read_rows(
    frame: pl.DataFrame, request: StandardSupplementalRequest,
    *, periods: Sequence[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    # 同一 select 中按角色投影，不在原 frame 上覆盖可能同名的合法源字段。
    expressions = [
        pl.col(request.period_field).alias("__period"),
        (pl.col(request.dimension_field) if request.dimension_field is not None else pl.lit("")).alias("__dimension"),
        pl.col(request.measure_field).cast(pl.Float64, strict=False).alias("__value"),
    ]
    if request.secondary_dimension_field is not None:
        expressions.append(pl.col(request.secondary_dimension_field).alias("__secondary_dimension"))
    if request.denominator_field is not None:
        expressions.append(
            pl.col(request.denominator_field).cast(pl.Float64, strict=False).alias("__denominator")
        )
    rows: list[dict[str, Any]] = []
    baseline_periods = (request.baseline_periods
                        if request.operation in {"period_comparison", "group_period_comparison"} else ())
    selected_periods = {
        metric_period_key(label, request.period_granularity): label
        for label in (periods if periods is not None else (*request.current_periods, *baseline_periods))
    }
    for item in frame.select(*expressions).iter_rows(named=True):
        period = item.get("__period")
        dimension = item.get("__dimension")
        secondary_dimension = item.get("__secondary_dimension")
        value = item.get("__value")
        denominator = item.get("__denominator")
        if period is None:
            warnings.append("期间为空的行已跳过")
            continue
        key = metric_period_key(str(period), request.period_granularity)
        if key is None:
            warnings.append("期间无法按冻结指标粒度解析的行已跳过")
            continue
        period = selected_periods.get(key)
        if period is None:
            continue
        if dimension is None:
            warnings.append("分组为空的行保留在 null 分组")
        if request.secondary_dimension_field is not None and secondary_dimension is None:
            warnings.append("交叉分组为空的行保留在 null 分组")
        if value is None or not math.isfinite(float(value)):
            warnings.append(f"分组 {dimension if dimension is not None else 'null'} 存在不可解析分子")
            if request.operation != "group_ratio":
                continue
            value = None
        if request.denominator_field is not None and (
            denominator is None or not math.isfinite(float(denominator))
        ):
            warnings.append(
                f"分组 {dimension if dimension is not None else 'null'} 存在不可解析分母，已跳过分母值"
            )
            denominator = None
        rows.append({
            "period": str(period),
            "dimension": str(dimension) if dimension is not None else None,
            **({
                "secondary_dimension": (
                    str(secondary_dimension) if secondary_dimension is not None else None
                ),
            } if request.secondary_dimension_field is not None else {}),
            "value": float(value) if value is not None else None,
            **({"denominator": float(denominator) if denominator is not None else None}
               if request.denominator_field is not None else {}),
        })
    return rows, warnings


def _rows_by_period(rows: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """单次分桶，避免逐期分析反复扫描全部明细。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["period"], []).append(row)
    return grouped


def _period_group_rows(
    rows: Iterable[dict[str, Any]],
    request: StandardSupplementalRequest,
    warnings: list[str],
) -> tuple[list[list[Any]], dict[str, float]]:
    period_rows = _rows_by_period(rows)
    result: list[list[Any]] = []
    totals: dict[str, float] = {}
    grouped_periods = {
        period: _group_totals(period_rows.get(period, ()))
        for period in request.current_periods
    }
    labels = {metric_period_key(period, request.period_granularity): period for period in request.current_periods}
    for period in request.current_periods:
        grouped, total = grouped_periods[period]
        totals[period] = total
        if not grouped:
            warnings.append(f"期间 {period} 没有可计算的有效分组")
            continue
        ordered = sorted(
            grouped.items(), key=lambda item: (-item[1], item[0] is None, item[0] or ""),
        )
        previous_period = labels.get(metric_comparison_period_key(period, request.period_granularity, "mom"))
        previous_groups = grouped_periods[previous_period][0] if previous_period is not None else {}
        for index, (dimension, value) in enumerate(ordered, start=1):
            item = [period, dimension, value, index, value / total if total else None]
            if request.include_period_change:
                previous = previous_groups.get(dimension)
                change = value - previous if previous is not None else None
                denominator = abs(previous) if previous is not None and request.change_rate_denominator == "absolute" else previous
                rate = change / denominator if change is not None and denominator else None
                item.extend((previous, change, rate))
                if previous is None or previous == 0:
                    warnings.append(f"期间 {period} 分组 {dimension} 的前期缺失或为零，保留未知环比")
            result.append(item)
        if total == 0:
            warnings.append(f"期间 {period} 分组占比分母为零，share 保留为空")
    return result, totals


def _cross_group_rows(
    rows: Iterable[dict[str, Any]], include_marginal_shares: bool, warnings: list[str],
) -> tuple[list[list[Any]], float]:
    encoded_rows = [{
        "dimension": json.dumps(
            [row["dimension"], row.get("secondary_dimension")],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        "value": row["value"],
    } for row in rows]
    grouped, total = _group_totals(encoded_rows)
    decoded = [
        (*json.loads(key), value)
        for key, value in grouped.items()
        if key is not None
    ]
    ordered = sorted(
        decoded,
        key=lambda item: (
            -item[2], item[0] is None, item[0] or "",
            item[1] is None, item[1] or "",
        ),
    )
    primary_totals: dict[str | None, list[float]] = {}
    secondary_totals: dict[str | None, list[float]] = {}
    if include_marginal_shares:
        for primary, secondary, value in ordered:
            primary_totals.setdefault(primary, []).append(value)
            secondary_totals.setdefault(secondary, []).append(value)
    primary_sums = {key: math.fsum(values) for key, values in primary_totals.items()}
    secondary_sums = {key: math.fsum(values) for key, values in secondary_totals.items()}
    result: list[list[Any]] = []
    for index, (primary, secondary, value) in enumerate(ordered, start=1):
        item = [primary, secondary, value, index, value / total if total else None]
        if include_marginal_shares:
            primary_total = primary_sums[primary]
            secondary_total = secondary_sums[secondary]
            item.extend((primary_total, value / primary_total if primary_total else None,
                         secondary_total, value / secondary_total if secondary_total else None))
            if primary_total == 0 or secondary_total == 0:
                warnings.append("交叉分组的边际合计为零，对应占比保留为空")
        result.append(item)
    return result, total


def _baseline_comparison_rows(
    rows: Iterable[dict[str, Any]], request: StandardSupplementalRequest, warnings: list[str],
) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """独立计算总体与各组基准；中位数不可加时如实保留差额，不强行配平。"""
    rows_by_period = _rows_by_period(rows)
    periods = tuple(dict.fromkeys((*request.current_periods, *request.baseline_periods)))
    grouped = {period: _group_totals(rows_by_period.get(period, ())) for period in periods}
    checks = [
        _reconciliation(f"{request.output_name}_{role}_{period}_total", grouped[period][1], expected)
        for role, labels, totals in (
            ("current", request.current_periods, request.parent_period_totals),
            ("baseline", request.baseline_periods, request.baseline_period_totals),
        )
        for period, expected in zip(labels, totals, strict=True)
    ]
    checks.append(_reconciliation(
        request.output_name + "_total",
        math.fsum(grouped[period][1] for period in request.current_periods), request.parent_total,
    ))
    baseline_labels = {
        metric_period_key(period, request.period_granularity): period for period in request.baseline_periods
    }

    def statistic(values: Sequence[float]) -> float:
        return float(median(values)) if request.baseline_method == "median" else math.fsum(values) / len(values)

    result: list[list[Any]] = []
    for period in request.current_periods:
        current, total = grouped[period]
        selected = request.baseline_periods
        if request.baseline_method == "previous_period":
            previous = baseline_labels.get(metric_comparison_period_key(period, request.period_granularity, "mom"))
            selected = (previous,) if previous is not None else ()
        complete = bool(selected) and all(grouped[label][0] for label in selected)
        baseline_total = statistic([grouped[label][1] for label in selected]) if complete else None
        total_change = total - baseline_total if baseline_total is not None else None
        dimensions = set(current).union(*(set(grouped[label][0]) for label in selected))
        period_rows: list[list[Any]] = []
        changes = []
        for dimension in dimensions:
            values = [grouped[label][0].get(dimension) for label in selected]
            baseline = statistic([value for value in values if value is not None]) if (
                values and all(value is not None for value in values)
            ) else None
            value = current.get(dimension)
            change = value - baseline if value is not None and baseline is not None else None
            denominator = abs(baseline) if baseline is not None and request.change_rate_denominator == "absolute" else baseline
            rate = change / denominator if change is not None and denominator else None
            contribution = change / total_change if change is not None and total_change else None
            if change is not None:
                changes.append(change)
            if value is None or baseline is None:
                warnings.append(f"期间 {period} 分组 {dimension} 缺少完整本期或基准，变化保留为空")
            elif baseline == 0:
                warnings.append(f"期间 {period} 分组 {dimension} 基准为零，changeRate 保留为空")
            period_rows.append([period, dimension, value, baseline, change, rate, contribution])
        period_rows.sort(key=lambda item: (
            item[4] is None, -(abs(item[4]) if request.rank_by == "absolute_change_desc" else item[4])
            if item[4] is not None else 0,
            item[1] is None, item[1] or "",
        ))
        result.extend([*item, rank, baseline_total, total_change]
                      for rank, item in enumerate(period_rows, start=1))
        if total_change is not None:
            checks.append(_reconciliation(
                f"{request.output_name}_{period}_change", math.fsum(changes), total_change,
            ))
        if total_change is None or total_change == 0:
            warnings.append(f"期间 {period} 的总体基准缺失或总变化为零，贡献保留为空")
    if any(not check["passed"] for check in checks):
        warnings.append("逐期基准比较存在对账差异（中位数可能不可加或分组缺失），保留结果与真实差额")
    return result, checks


def _ratio_rows(
    rows: Iterable[dict[str, Any]],
    current_periods: Sequence[str],
    denominator_scale: float,
    warnings: list[str],
) -> tuple[list[list[Any]], float, float]:
    selected_periods = set(current_periods)
    selected = [row for row in rows if row["period"] in selected_periods]
    numerator_rows = [
        {"dimension": row["dimension"], "value": row["value"]}
        for row in selected
        if row.get("value") is not None
    ]
    numerator, numerator_total = _group_totals(numerator_rows)
    denominator_rows = [
        {"dimension": row["dimension"], "value": row["denominator"]}
        for row in selected
        if row.get("denominator") is not None
    ]
    denominator, denominator_total = _group_totals(denominator_rows)
    result: list[list[Any]] = []
    for dimension in sorted(
        set(numerator) | set(denominator),
        key=lambda item: (-numerator.get(item, 0.0), item is None, item or ""),
    ):
        numerator_value = numerator.get(dimension)
        raw_denominator = denominator.get(dimension)
        scaled_denominator = (
            raw_denominator * denominator_scale if raw_denominator is not None else None
        )
        if numerator_value is None or raw_denominator is None:
            missing_role = "分子" if numerator_value is None else "分母"
            warnings.append(f"分组 {dimension if dimension is not None else 'null'} 缺少{missing_role}数据")
            difference = ratio = None
        else:
            assert scaled_denominator is not None
            difference = numerator_value - scaled_denominator
            ratio = numerator_value / scaled_denominator if scaled_denominator != 0 else None
            if not math.isfinite(scaled_denominator) or not math.isfinite(difference) or (
                ratio is not None and not math.isfinite(ratio)
            ):
                warnings.append(
                    f"分组 {dimension if dimension is not None else 'null'} 比率结果不可表示，派生值保留为空"
                )
                scaled_denominator = difference = ratio = None
            elif scaled_denominator == 0:
                warnings.append(
                    f"分组 {dimension if dimension is not None else 'null'} 分母为零，ratio 保留为空"
                )
        result.append([dimension, numerator_value, scaled_denominator, difference, ratio])
    return result, numerator_total, denominator_total


def _group_rows(rows: Iterable[dict[str, Any]], warnings: list[str]) -> tuple[list[list[Any]], float, float]:
    grouped, total = _group_totals(rows)
    ordered = sorted(grouped.items(), key=lambda item: (-item[1], item[0] is None, item[0] or ""))
    result = [
        [dimension, value, index, value / total if total else None]
        for index, (dimension, value) in enumerate(ordered, start=1)
    ]
    return result, total, math.fsum(item[1] for item in ordered)


def _group_totals(rows: Iterable[dict[str, Any]]) -> tuple[dict[str | None, float], float]:
    frame = pl.DataFrame(
        [{"dimension": row["dimension"], "value": row["value"]} for row in rows],
        schema={"dimension": pl.String, "value": pl.Float64},
    )
    return additive_group_totals(frame, "value", "dimension")


def _comparison_rows(
    rows: Iterable[dict[str, Any]],
    current_periods: Sequence[str],
    baseline_periods: Sequence[str],
    warnings: list[str],
    *, baseline_rows: Iterable[dict[str, Any]] | None = None,
    change_rate_denominator: Literal["signed", "absolute"] = "signed",
) -> tuple[list[list[Any]], float, float, float, float]:
    current_period_set = set(current_periods)
    baseline_period_set = set(baseline_periods)
    rows = list(rows)
    current, current_total = _group_totals(row for row in rows if row["period"] in current_period_set)
    baseline, baseline_total = _group_totals(
        row for row in (rows if baseline_rows is None else baseline_rows) if row["period"] in baseline_period_set
    )
    result: list[list[Any]] = []
    for dimension in sorted(
        set(current) | set(baseline),
        key=lambda item: (-current.get(item, 0.0), item is None, item or ""),
    ):
        current_value = current.get(dimension)
        baseline_value = baseline.get(dimension)
        if current_value is None or baseline_value is None:
            missing_role = "本期" if current_value is None else "对照期间"
            warnings.append(f"分组 {dimension if dimension is not None else 'null'} 缺少{missing_role}数据")
            change = change_rate = None
        else:
            change = current_value - baseline_value if current_value is not None else None
            change_rate = (
                change / (abs(baseline_value) if change_rate_denominator == "absolute" else baseline_value)
                if change is not None and baseline_value != 0
                else None
            )
            if baseline_value == 0:
                warnings.append(f"分组 {dimension if dimension is not None else 'null'} 对照值为零，changeRate 保留为空")
        total_change = current_total - baseline_total
        contribution = change / total_change if change is not None and total_change != 0 else None
        result.append([dimension, current_value, baseline_value, change, change_rate, contribution])
    return result, current_total, baseline_total, math.fsum(current.values()), math.fsum(baseline.values())


def _cross_comparison_columns(
    rows: Sequence[list[Any]], request: StandardSupplementalRequest, warnings: list[str],
) -> list[list[Any]]:
    """展开两维来源键，组内仅在配对完整时给出变动贡献与排名。"""
    offset = int(request.group_by_period)
    expanded = [[*row[:offset], *json.loads(row[offset]), *row[offset + 1:]] for row in rows]
    groups: dict[tuple[Any, ...], list[list[Any]]] = {}
    for row in expanded:
        groups.setdefault(tuple(row[:offset + 1]), []).append(row)
    for key, members in groups.items():
        changes = [row[offset + 4] for row in members]
        if any(change is None for change in changes):
            warnings.append(f"主维度 {key} 存在缺失配对，组内变动、贡献与排名保留为空")
            for row in members:
                row.extend((None, None, None))
            continue
        primary_change = math.fsum(changes)
        if primary_change == 0:
            warnings.append(f"主维度 {key} 总变化为零，primaryContribution 保留为空")
        # members 已沿用全窗变化排序；限制到同一主维度后即为稳定的组内排名。
        for rank, row in enumerate(members, start=1):
            row.extend((primary_change, row[offset + 4] / primary_change if primary_change else None, rank))
    return expanded


def _period_comparison_rows(
    rows: Sequence[dict[str, Any]], baseline_rows: Sequence[dict[str, Any]] | None,
    request: StandardSupplementalRequest, warnings: list[str],
) -> tuple[list[list[Any]], list[dict[str, Any]]]:
    """逐期取同日历基期，贡献和排名仍回答整个请求窗口的增减集中程度。"""
    aligned = _aligned_baseline_periods(
        request.current_periods, request.baseline_periods, request.period_granularity,
    )
    current_by_period = _rows_by_period(rows)
    baseline_by_period = current_by_period if baseline_rows is None else _rows_by_period(baseline_rows)
    baseline_expected = dict(zip(request.baseline_periods, request.baseline_period_totals, strict=True))
    result: list[list[Any]] = []
    checks: list[dict[str, Any]] = []
    current_totals: list[float] = []
    baseline_totals: list[float] = []
    for period, prior, expected in zip(request.current_periods, aligned, request.parent_period_totals, strict=True):
        period_rows, current_total, baseline_total, _, _ = _comparison_rows(
            current_by_period.get(period, ()), (period,), (prior,), warnings,
            baseline_rows=baseline_by_period.get(prior, ()),
            change_rate_denominator=request.change_rate_denominator,
        )
        result.extend([period, *row] for row in period_rows)
        current_totals.append(current_total)
        baseline_totals.append(baseline_total)
        checks.extend((
            _reconciliation(f"{request.output_name}_current_{period}_total", current_total, expected),
            _reconciliation(f"{request.output_name}_baseline_{prior}_total", baseline_total, baseline_expected[prior]),
        ))
        if not period_rows:
            warnings.append(f"期间 {period} 与 {prior} 没有可比较的有效分组")
            if request.dimension_field is None:
                result.append([period, "", None, None, None, None, None])
    current_total = math.fsum(current_totals)
    baseline_total = math.fsum(baseline_totals)
    total_change = current_total - baseline_total
    assert request.baseline_parent_total is not None
    checks.extend((
        _reconciliation(request.output_name + "_current_total", current_total, request.parent_total),
        _reconciliation(request.output_name + "_baseline_total", baseline_total, request.baseline_parent_total),
        _reconciliation(request.output_name + "_change",
                        math.fsum(row[4] for row in result if row[4] is not None), total_change),
    ))
    for row in result:
        row[6] = row[4] / total_change if row[4] is not None and total_change else None
    result.sort(key=lambda row: (
        row[4] is None, -(abs(row[4]) if request.rank_by == "absolute_change_desc" else row[4])
        if row[4] is not None else 0, row[0], row[1] is None, row[1] or "",
    ))
    if total_change == 0:
        warnings.append("全窗总变化为零，contribution 保留为空")
    if any(not check["passed"] for check in checks):
        warnings.append("逐期期间比较与冻结总额或可比较分组不闭合，保留结果并产生软告警")
    return [
        [*(row if request.dimension_field is not None else [row[0], *row[2:]]), rank]
        for rank, row in enumerate(result, start=1)
    ], checks


def _reconciliation(name: str, left: float, right: float) -> dict[str, Any]:
    passed = reconciliation_passes(left, right, absolute_tolerance=1e-9, relative_tolerance=1e-12)
    return {"name": name, "passed": passed, "left": left, "right": right}


def query_bound_scope_fields(
    dataset: Mapping[str, Any], scope: Mapping[str, str],
) -> frozenset[str]:
    """Return scope fields fixed by the signed materialization query.

    Only direct equality predicates in the top-level AND chain are accepted. The
    query must be the exact SQL bound by ``sqlHash`` on a server-materialized
    dataset; free text and URL CSV provenance never grant scope authorization.
    """

    provenance = dataset.get("provenance")
    if dataset.get("sourceType") != "starrocks_materialized" or not isinstance(provenance, Mapping):
        return frozenset()
    query, sql_hash = provenance.get("querySql"), provenance.get("sqlHash")
    if (
        not isinstance(query, str)
        or not query
        or not isinstance(sql_hash, str)
        or hashlib.sha256(query.encode("utf-8")).hexdigest() != sql_hash
    ):
        return frozenset()
    try:
        statements = parse(query, read="mysql")
    except SqlglotError:
        return frozenset()
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return frozenset()
    statement = statements[0]
    if any(True for _ in statement.find_all(exp.Join)):
        return frozenset()
    where = statement.args.get("where")
    if not isinstance(where, exp.Where):
        return frozenset()

    def conjuncts(node: exp.Expression) -> Iterable[exp.Expression]:
        while isinstance(node, exp.Paren):
            node = node.this
        if isinstance(node, exp.And):
            yield from conjuncts(node.this)
            yield from conjuncts(node.expression)
        else:
            yield node

    values: dict[str, set[str]] = {}
    for predicate in conjuncts(where.this):
        if not isinstance(predicate, exp.EQ):
            continue
        left, right = predicate.this, predicate.expression
        if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
            left, right = right, left
        if not isinstance(left, exp.Column) or not isinstance(right, exp.Literal):
            continue
        values.setdefault(left.name, set()).add(str(right.this))
    return frozenset(
        field
        for field, expected in scope.items()
        if values.get(field) == {expected}
    )


def standard_input_matches_fact(fact: Any, dataset: Mapping[str, Any]) -> bool:
    """清单与实际字节之外，还须绑定计算使用的冻结事实身份。"""
    return (
        bool(dataset.get("sha256"))
        and getattr(fact, "dataset_id", None) == dataset.get("datasetId")
        and getattr(fact, "dataset_sha256", None) == dataset.get("sha256")
    )


def comparison_period_windows(
    parent: Any, baseline: Any, current_periods: Sequence[str],
) -> list[tuple[str, ...]]:
    """用冻结期间角色和日历寻找完整同期，不依赖 CSV 行序或两侧总月数。"""
    if (
        "current" not in getattr(parent, "period_roles", ())
        or getattr(parent, "period_granularity", None) != getattr(baseline, "period_granularity", None)
    ):
        return []
    available: dict[Any, str] = {}
    for item in baseline.period_values:
        key = metric_period_key(item.period, getattr(baseline, "period_granularity", None))
        if key is None or key in available:
            return []
        available[key] = item.period
    windows: list[tuple[str, ...]] = []
    grain = getattr(baseline, "period_granularity", None)
    current_keys = {metric_period_key(label, grain) for label in current_periods}
    for role in sorted(set(getattr(baseline, "period_roles", ())) & {"yoy", "mom"}):
        keys = [metric_comparison_period_key(label, grain, role) for label in current_periods]
        if keys and all(key in available for key in keys) and not set(keys) & current_keys:
            window = tuple(available[key] for key in keys)
            if window not in windows:
                windows.append(window)
    return windows


def standard_computation_candidates(
    facts: Any,
    datasets: Sequence[Any],
    requested_periods: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Advertise bounded, fully bound choices; never infer an operation from prose."""
    return standard_computation_catalog(
        facts, datasets, requested_periods, _include_grouping_sources=False,
    )["candidates"]


def standard_computation_catalog(
    facts: Any,
    datasets: Sequence[Any],
    requested_periods: Sequence[str] = (),
    *, _include_grouping_sources: bool = True,
) -> dict[str, Any]:
    """共用源资格计算；紧凑索引不依赖有界候选中是否展示某个维度组合。"""
    metrics = tuple(getattr(facts, "metrics", ()))
    datasets_by_id = {item.get("datasetId"): item for item in datasets if isinstance(item, dict)}
    metrics_by_id = {item.fact_id: item for item in metrics if getattr(item, "fact_id", None)}
    measures_by_dataset = {
        dataset.get("datasetId"): {
            item.field for item in metrics if item.dataset_id == dataset.get("datasetId")
        }
        for dataset in datasets
        if isinstance(dataset, dict)
    }
    buckets: dict[str, list[dict[str, Any]]] = {operation: [] for operation in STANDARD_SUPPLEMENTAL_OPERATIONS}
    seen: set[str] = set()
    candidate_sizes: dict[str, int] = {}
    grouping_sources: list[dict[str, Any]] = []

    def period_selection(parent: Any) -> tuple[str, ...] | None:
        available_periods = tuple(item.period for item in parent.period_values)
        available_keys = tuple(
            metric_period_key(label, getattr(parent, "period_granularity", None))
            for label in available_periods
        )
        valid_keys = tuple(key for key in available_keys if key is not None)
        if (
            len(valid_keys) != len(available_keys)
            or len(set(valid_keys)) != len(valid_keys)
            or len({key[0] for key in valid_keys}) != 1
        ):
            return None
        if requested_periods:
            requested_keys = tuple(
                metric_period_key(str(label), getattr(parent, "period_granularity", None))
                for label in requested_periods
            )
            valid_requested = tuple(key for key in requested_keys if key is not None)
            if (
                len(valid_requested) == len(requested_keys)
                and len(set(valid_requested)) == len(valid_requested)
                and all(key in valid_keys for key in valid_requested)
            ):
                indexes = tuple(valid_keys.index(key) for key in valid_requested)
                return tuple(available_periods[index] for index in indexes)
            # 不得把缺月、重复或无法解析的请求静默缩小成已有期间。
            return None
        return available_periods

    def add_candidate(
        *, dataset_id: str, fields: set[str], label: str, spec: StandardSupplementalSpec,
    ) -> None:
        payload = spec.model_dump(mode="json", by_alias=True, exclude_none=True)
        candidate_id = "std-" + hashlib.sha256(json.dumps(
            [dataset_id, payload], sort_keys=True, ensure_ascii=False,
        ).encode()).hexdigest()[:16]
        if candidate_id in seen:
            return
        seen.add(candidate_id)
        candidate = {
            "candidateId": candidate_id,
            "datasetId": dataset_id,
            "fields": sorted(fields),
            "label": label,
            "standardComputation": payload,
            "outputColumns": list(standard_output_columns(spec)),
        }
        candidate_sizes[candidate_id] = len(json.dumps(candidate, ensure_ascii=False).encode())
        buckets[spec.operation].append(candidate)

    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        dataset_id = dataset.get("datasetId")
        columns = set(dataset.get("columns") or ())
        measures = measures_by_dataset.get(dataset_id, set())
        profile = dataset.get("columnProfile") or {}
        for parent in metrics:
            if (parent.dataset_id != dataset_id or not parent.fact_id
                    or parent.aggregation != "sum"
                    or parent.cumulative_policy is not None or not parent.period_field
                    or not parent.period_values):
                continue
            parent_scope = getattr(parent, "scope", {}) or {}
            unprojected_scope = set(parent_scope) - columns
            bound_scope = query_bound_scope_fields(dataset, parent_scope)
            if not unprojected_scope.issubset(bound_scope):
                continue
            required = {parent.field, parent.period_field, *(set(parent_scope) & columns)}
            if not required.issubset(columns):
                continue
            periods = period_selection(parent)
            if periods is None or not standard_grouping_periods_supported(parent, periods):
                continue
            dimensions = [
                dimension
                for dimension in sorted(
                    columns - measures - {parent.period_field} - set(parent_scope)
                )
                if not (
                    isinstance(profile, dict)
                    and profile.get(dimension, {}).get("role") in {"measure", "period", "empty"}
                )
            ]
            source: dict[str, Any] | None = None
            comparison_bindings: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
            if (_include_grouping_sources and (dimensions or parent.period_aggregation == "sum")
                    and standard_input_matches_fact(parent, dataset)):
                source = {
                    "datasetId": dataset_id, "parentFactId": parent.fact_id,
                    "measureField": parent.field, "periodField": parent.period_field,
                    "currentPeriods": list(periods), "dimensionFields": dimensions,
                    "periodAggregation": parent.period_aggregation,
                    "supportedOperations": (list(STANDARD_SUPPLEMENTAL_OPERATIONS) if dimensions
                                            else ["period_comparison"])
                    if parent.period_aggregation == "sum" else ["group_summary", "cross_group_summary"],
                    "projectedScopeFields": sorted(set(parent_scope) & columns),
                    "comparisonBindings": [],
                }
                grouping_sources.append(source)
            all_periods = tuple(item.period for item in parent.period_values)
            all_keys = {metric_period_key(label, getattr(parent, "period_granularity", None))
                        for label in all_periods}
            prior_keys = {metric_comparison_period_key(label, getattr(parent, "period_granularity", None), "mom")
                          for label in periods}
            prior_periods = tuple(label for label in all_periods
                                  if metric_period_key(label, getattr(parent, "period_granularity", None)) in prior_keys)
            for dimension in (*dimensions, None):
                role = profile.get(dimension, {}).get("role") if isinstance(profile, dict) else None
                if role in {"measure", "period", "empty"}:
                    continue
                operations: tuple[StandardSupplementalOperation, ...] = (
                    ("group_summary", "group_period_series", "group_concentration") if parent.period_aggregation == "sum"
                    else ("group_summary",)
                )
                specs = [
                    StandardSupplementalSpec(
                        operation=operation, measureField=parent.field,
                        dimensionField=dimension, periodField=parent.period_field,
                        currentPeriods=periods, parentFactId=parent.fact_id,
                        includePeriodChange=operation == "group_period_series",
                    )
                    for operation in operations if dimension is not None
                ]
                if dimension is not None and parent.period_aggregation == "sum" and prior_keys & all_keys:
                    specs.append(StandardSupplementalSpec(
                        operation="group_period_comparison", measureField=parent.field,
                        dimensionField=dimension, periodField=parent.period_field,
                        currentPeriods=periods, parentFactId=parent.fact_id,
                        baselineMethod="previous_period", baselinePeriods=prior_periods,
                    ))
                for baseline in metrics:
                    baseline_dataset = datasets_by_id.get(baseline.dataset_id)
                    if (parent.period_aggregation != "sum"
                            or "current" not in getattr(parent, "period_roles", ())
                            or not set(getattr(baseline, "period_roles", ())) & {"yoy", "mom"}
                            or baseline_dataset is None or not baseline.fact_id
                            or baseline.field != parent.field or baseline.aggregation != "sum"
                            or baseline.period_aggregation != "sum" or baseline.cumulative_policy is not None
                            or baseline.period_field != parent.period_field
                            or getattr(baseline, "period_granularity", None) != getattr(parent, "period_granularity", None)
                            or getattr(baseline, "unit", None) != getattr(parent, "unit", None)
                            or getattr(baseline, "scope", {}) != getattr(parent, "scope", {})):
                        continue
                    cross_dataset = baseline.dataset_id != dataset_id
                    if cross_dataset and (
                        not getattr(parent, "field_ref", None)
                        or getattr(parent, "field_ref", None) != getattr(baseline, "field_ref", None)
                    ):
                        continue
                    baseline_columns = set(baseline_dataset.get("columns") or ())
                    if (not ({parent.field, parent.period_field, dimension} - {None}).issubset(baseline_columns)
                            or not (set(parent_scope) - baseline_columns).issubset(
                                query_bound_scope_fields(baseline_dataset, parent_scope))):
                        continue
                    for prior in comparison_period_windows(parent, baseline, periods):
                        for by_period in ((False, True) if dimension is not None else (True,)):
                            specs.append(StandardSupplementalSpec(
                                operation="period_comparison", measureField=parent.field,
                                dimensionField=dimension, periodField=parent.period_field,
                                currentPeriods=periods, baselinePeriods=prior,
                                parentFactId=parent.fact_id, baselineParentFactId=baseline.fact_id,
                                baselineDatasetId=baseline.dataset_id if cross_dataset else None,
                                groupByPeriod=by_period,
                            ))
                        if standard_input_matches_fact(baseline, baseline_dataset):
                            binding_key = (baseline.fact_id, baseline.dataset_id, prior)
                            if binding_key not in comparison_bindings:
                                binding = {
                                    "baselineParentFactId": baseline.fact_id,
                                    "baselinePeriods": list(prior), "dimensionFields": [],
                                }
                                if cross_dataset:
                                    binding["baselineDatasetId"] = baseline.dataset_id
                                comparison_bindings[binding_key] = binding
                                if source is not None:
                                    source["comparisonBindings"].append(binding)
                            if dimension is not None:
                                comparison_bindings[binding_key]["dimensionFields"].append(dimension)
                for spec in specs:
                    add_candidate(
                        dataset_id=dataset_id,
                        fields=required | ({dimension} if dimension is not None else set()),
                        label=getattr(parent, "display_name", None) or parent.field,
                        spec=spec,
                    )
            # 无分组来源只服务逐期比较；没有可绑定的基期时不发布，避免目录承诺不可执行的计算。
            if source is not None and not dimensions and not source["comparisonBindings"]:
                grouping_sources.remove(source)
            # 有界轮转维度配对，避免字典序前8列永久挤掉其他主题的业务维度。
            pairs: set[tuple[str, str]] = set()
            for offset in range(1, len(dimensions)):
                for index, dimension in enumerate(dimensions):
                    primary, secondary = sorted((dimension, dimensions[(index + offset) % len(dimensions)]))
                    if (primary, secondary) in pairs:
                        continue
                    pairs.add((primary, secondary))
                    for by_period in (False, True):
                        add_candidate(
                            dataset_id=dataset_id,
                            fields=required | {primary, secondary},
                            label=getattr(parent, "display_name", None) or parent.field,
                            spec=StandardSupplementalSpec(
                                operation="cross_group_summary", measureField=parent.field,
                                dimensionField=primary, secondaryDimensionField=secondary,
                                periodField=parent.period_field, currentPeriods=periods,
                                parentFactId=parent.fact_id, includeMarginalShares=True,
                                groupByPeriod=by_period,
                            ),
                        )
                    for binding in comparison_bindings.values():
                        if not {primary, secondary}.issubset(binding["dimensionFields"]):
                            continue
                        for by_period in (False, True):
                            add_candidate(
                                dataset_id=dataset_id, fields=required | {primary, secondary},
                                label=getattr(parent, "display_name", None) or parent.field,
                                spec=StandardSupplementalSpec(
                                    operation="period_comparison", measureField=parent.field,
                                    dimensionField=primary, secondaryDimensionField=secondary,
                                    periodField=parent.period_field, currentPeriods=periods,
                                    parentFactId=parent.fact_id,
                                    baselinePeriods=binding["baselinePeriods"],
                                    baselineParentFactId=binding["baselineParentFactId"],
                                    baselineDatasetId=binding.get("baselineDatasetId"),
                                    groupByPeriod=by_period,
                                ),
                            )
                    if len(pairs) >= 28:
                        break
                if len(pairs) >= 28:
                    break

        for ratio_fact in tuple(getattr(facts, "derived_metrics", ())):
            input_ids = tuple(getattr(ratio_fact, "input_fact_ids", ()))
            if (
                not getattr(ratio_fact, "fact_id", None)
                or len(input_ids) != 2
                or tuple(getattr(ratio_fact, "dataset_ids", ())) != (dataset_id,)
            ):
                continue
            numerator = metrics_by_id.get(input_ids[0])
            denominator = metrics_by_id.get(input_ids[1])
            if numerator is None or denominator is None:
                continue
            numerator_scope = getattr(numerator, "scope", {}) or {}
            denominator_scope = getattr(denominator, "scope", {}) or {}
            if (
                numerator.dataset_id != dataset_id
                or denominator.dataset_id != dataset_id
                or numerator.aggregation != "sum"
                or denominator.aggregation != "sum"
                or numerator.period_aggregation != "sum"
                or denominator.period_aggregation != "sum"
                or numerator.cumulative_policy is not None
                or denominator.cumulative_policy is not None
                or not numerator.period_field
                or numerator.period_field != denominator.period_field
                or getattr(numerator, "period_granularity", None)
                != getattr(denominator, "period_granularity", None)
                or numerator_scope != denominator_scope
                or (getattr(ratio_fact, "scope", {}) or {}) != numerator_scope
                or getattr(ratio_fact, "period_role", None)
                not in getattr(numerator, "period_roles", ())
                or getattr(ratio_fact, "period_role", None)
                not in getattr(denominator, "period_roles", ())
                or not numerator.period_values
                or not denominator.period_values
                or getattr(ratio_fact, "difference", None) is None
                or (
                    getattr(ratio_fact, "percentage", None) is None
                    and getattr(ratio_fact, "denominator", None) != 0
                )
            ):
                continue
            scale = unit_conversion_scale(
                getattr(denominator, "unit", None), getattr(numerator, "unit", None)
            )
            if scale is None or not math.isclose(
                float(scale), float(getattr(ratio_fact, "denominator_scale", 0)),
                rel_tol=1e-12, abs_tol=1e-12,
            ):
                continue
            all_numerator_periods = tuple(item.period for item in numerator.period_values)
            denominator_periods = tuple(item.period for item in denominator.period_values)
            grain = getattr(numerator, "period_granularity", None)
            numerator_keys = [metric_period_key(label, grain) for label in all_numerator_periods]
            denominator_keys = [metric_period_key(label, grain) for label in denominator_periods]
            if (
                None in numerator_keys
                or None in denominator_keys
                or len(set(numerator_keys)) != len(numerator_keys)
                or len(set(denominator_keys)) != len(denominator_keys)
                or set(numerator_keys) != set(denominator_keys)
                or all_numerator_periods != denominator_periods
                or len({key[0] for key in numerator_keys if key is not None}) != 1
                or (
                    getattr(ratio_fact, "period_granularity", None) is not None
                    and numerator_keys
                    and numerator_keys[0] is not None
                    and getattr(ratio_fact, "period_granularity", None) != numerator_keys[0][0]
                )
            ):
                continue
            numerator_periods = period_selection(numerator)
            if numerator_periods is None:
                continue
            unprojected_scope = set(numerator_scope) - columns
            bound_scope = query_bound_scope_fields(dataset, numerator_scope)
            if not unprojected_scope.issubset(bound_scope):
                continue
            required = {
                numerator.field,
                denominator.field,
                numerator.period_field,
                *(set(numerator_scope) & columns),
            }
            if not required.issubset(columns):
                continue
            excluded = measures | {numerator.period_field} | set(numerator_scope)
            for dimension in sorted(columns - excluded):
                role = profile.get(dimension, {}).get("role") if isinstance(profile, dict) else None
                if role in {"measure", "period", "empty"}:
                    continue
                for by_period in (False, True):
                    add_candidate(
                        dataset_id=dataset_id,
                        fields=required | {dimension},
                        label=getattr(ratio_fact, "code", None) or "登记比率",
                        spec=StandardSupplementalSpec(
                            operation="group_ratio",
                            measureField=numerator.field,
                            denominatorField=denominator.field,
                            dimensionField=dimension,
                            periodField=numerator.period_field,
                            currentPeriods=numerator_periods,
                            parentFactId=numerator.fact_id,
                            denominatorParentFactId=denominator.fact_id,
                            ratioFactId=ratio_fact.fact_id,
                            groupByPeriod=by_period,
                        ),
                    )

    candidates: list[dict[str, Any]] = []
    used_bytes = 0
    dimension_uses: dict[tuple[str, str], int] = {}
    measure_uses: dict[tuple[str, str], int] = {}
    variant_uses: dict[tuple[str, str, str, bool], int] = {}

    def coverage_key(candidate: Mapping[str, Any]) -> tuple[int, int, int]:
        spec = candidate["standardComputation"]
        dimensions = [spec["dimensionField"]] if spec.get("dimensionField") is not None else []
        if spec.get("secondaryDimensionField"):
            dimensions.append(spec["secondaryDimensionField"])
        return (
            measure_uses.get((candidate["datasetId"], spec["measureField"]), 0),
            variant_uses.get((candidate["datasetId"], spec["operation"],
                              spec["measureField"], spec.get("groupByPeriod", False)), 0),
            max((dimension_uses.get((candidate["datasetId"], field), 0) for field in dimensions), default=0),
        )

    while len(candidates) < STANDARD_CANDIDATE_LIMIT:
        added = False
        for operation in STANDARD_SUPPLEMENTAL_OPERATIONS:
            # 余量只会减小，放不下的候选无需反复全桶排名后再逐个丢弃。
            bucket = [item for item in buckets[operation]
                      if candidate_sizes[item["candidateId"]] <= STANDARD_CANDIDATE_BYTES - used_bytes]
            buckets[operation] = bucket
            if not bucket:
                continue
            position = min(range(len(bucket)), key=lambda index: coverage_key(bucket[index]))
            candidate = bucket.pop(position)
            size = candidate_sizes[candidate["candidateId"]]
            candidates.append(candidate)
            used_bytes += size
            spec = candidate["standardComputation"]
            for field in (spec.get("dimensionField"), spec.get("secondaryDimensionField")):
                if field is not None:
                    key = (candidate["datasetId"], field)
                    dimension_uses[key] = dimension_uses.get(key, 0) + 1
            measure_key = (candidate["datasetId"], spec["measureField"])
            measure_uses[measure_key] = measure_uses.get(measure_key, 0) + 1
            variant_key = (candidate["datasetId"], spec["operation"],
                           spec["measureField"], spec.get("groupByPeriod", False))
            variant_uses[variant_key] = variant_uses.get(variant_key, 0) + 1
            added = True
            if len(candidates) >= STANDARD_CANDIDATE_LIMIT:
                break
        if not added:
            break
    source_index: dict[str, Any] = {
        "items": [], "totalItems": len(grouping_sources), "truncated": False,
    }
    for source in grouping_sources:
        source_index["items"].append(source)
        if len(json.dumps(source_index, ensure_ascii=False).encode()) > STANDARD_GROUPING_SOURCE_BYTES:
            source_index["items"].pop()
    source_index["truncated"] = len(source_index["items"]) < len(grouping_sources)
    return {"candidates": candidates, "groupingSources": source_index}
