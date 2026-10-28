"""服务端标准补证计算的窄接口。

输入必须已经通过当前分析的 dataset、字段和期间授权；本模块不解析自由文本公式，
也不访问数据库或工作区路径。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

import polars as pl
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from ...hospital_operation.deterministic_analysis import (
    additive_group_totals,
    apply_metric_scope,
    metric_period_key,
    read_analysis_csv,
    reconciliation_passes,
)
from ...units import unit_conversion_scale


class StandardSupplementalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    operation: Literal[
        "group_summary", "group_period_series", "cross_group_summary",
        "period_comparison", "group_ratio",
    ]
    dataset_id: str = Field(min_length=1, alias="datasetId")
    output_name: str = Field(min_length=1, alias="outputName")
    measure_field: str = Field(min_length=1, alias="measureField")
    denominator_field: str | None = Field(default=None, min_length=1, alias="denominatorField")
    measure_unit: str | None = Field(default=None, min_length=1, alias="measureUnit")
    dimension_field: str = Field(min_length=1, alias="dimensionField")
    secondary_dimension_field: str | None = Field(
        default=None, min_length=1, alias="secondaryDimensionField",
    )
    period_field: str = Field(min_length=1, alias="periodField")
    period_granularity: Literal["day", "month", "year"] | None = Field(default=None, alias="periodGranularity")
    current_periods: tuple[str, ...] = Field(min_length=1, alias="currentPeriods")
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    parent_total: float = Field(alias="parentTotal")
    parent_period_totals: tuple[float, ...] = Field(default=(), alias="parentPeriodTotals")
    baseline_parent_total: float | None = Field(default=None, alias="baselineParentTotal")
    denominator_parent_total: float | None = Field(default=None, alias="denominatorParentTotal")
    denominator_scale: float | None = Field(default=None, gt=0, alias="denominatorScale")
    ratio_fact_id: str | None = Field(default=None, min_length=1, alias="ratioFactId")
    scope: dict[str, str] = Field(default_factory=dict)
    query_bound_scope_fields: tuple[str, ...] = Field(
        default=(), alias="queryBoundScopeFields", exclude_if=lambda value: not value,
    )

    @model_validator(mode="after")
    def require_baseline_for_comparison(self) -> StandardSupplementalRequest:
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
        if self.operation == "cross_group_summary":
            if self.secondary_dimension_field is None:
                raise ValueError("cross_group_summary 必须提供 secondaryDimensionField")
            if self.secondary_dimension_field in {
                self.measure_field, self.dimension_field, self.period_field,
                self.denominator_field,
            }:
                raise ValueError("交叉维度必须与度量、主维度和期间字段不同")
        elif self.secondary_dimension_field is not None:
            raise ValueError("只有 cross_group_summary 接受 secondaryDimensionField")
        if self.operation == "group_period_series":
            if len(self.parent_period_totals) != len(self.current_periods):
                raise ValueError("group_period_series 必须为每个期间提供 parentPeriodTotals")
        elif self.parent_period_totals:
            raise ValueError("只有 group_period_series 接受 parentPeriodTotals")
        current_keys = [metric_period_key(label, self.period_granularity) for label in self.current_periods]
        baseline_keys = ([metric_period_key(label, self.period_granularity) for label in self.baseline_periods]
                         if self.operation == "period_comparison" else [])
        keys = [*current_keys, *baseline_keys]
        if None in keys or len({key[0] for key in keys if key is not None}) != 1:
            raise ValueError("标准补证期间必须可解析且粒度相同")
        if len(keys) != len(set(keys)):
            raise ValueError("标准补证期间不能重复或重叠（含期间别名）")
        if (
            len(self.query_bound_scope_fields) != len(set(self.query_bound_scope_fields))
            or not set(self.query_bound_scope_fields).issubset(self.scope)
        ):
            raise ValueError("queryBoundScopeFields 必须唯一且属于 scope")
        return self


class StandardSupplementalSpec(BaseModel):
    """结构化路由声明；父总额只引用冻结 deterministic fact，不接受模型数值。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    operation: Literal[
        "group_summary", "group_period_series", "cross_group_summary",
        "period_comparison", "group_ratio",
    ]
    measure_field: str = Field(min_length=1, alias="measureField")
    denominator_field: str | None = Field(default=None, min_length=1, alias="denominatorField")
    dimension_field: str = Field(min_length=1, alias="dimensionField")
    secondary_dimension_field: str | None = Field(
        default=None, min_length=1, alias="secondaryDimensionField",
    )
    period_field: str = Field(min_length=1, alias="periodField")
    current_periods: tuple[str, ...] = Field(min_length=1, alias="currentPeriods")
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    parent_fact_id: str = Field(min_length=1, alias="parentFactId")
    baseline_parent_fact_id: str | None = Field(default=None, alias="baselineParentFactId")
    denominator_parent_fact_id: str | None = Field(
        default=None, min_length=1, alias="denominatorParentFactId",
    )
    ratio_fact_id: str | None = Field(default=None, min_length=1, alias="ratioFactId")

    @model_validator(mode="after")
    def validate_periods_and_parent_refs(self) -> StandardSupplementalSpec:
        if len(self.current_periods) != len(set(self.current_periods)):
            raise ValueError("currentPeriods 不能重复")
        if len(self.baseline_periods) != len(set(self.baseline_periods)):
            raise ValueError("baselinePeriods 不能重复")
        if set(self.current_periods) & set(self.baseline_periods):
            raise ValueError("当前期间和对照期间不能重叠")
        if self.operation == "period_comparison":
            if not self.baseline_periods:
                raise ValueError("period_comparison 必须提供 baselinePeriods")
            if len(self.current_periods) != len(self.baseline_periods):
                raise ValueError("当前期间与对照期间粒度数必须一致")
        elif self.baseline_periods or self.baseline_parent_fact_id is not None:
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
        if self.operation == "cross_group_summary":
            if self.secondary_dimension_field is None:
                raise ValueError("cross_group_summary 必须提供 secondaryDimensionField")
            if self.secondary_dimension_field in {
                self.measure_field, self.dimension_field, self.period_field,
                self.denominator_field,
            }:
                raise ValueError("交叉维度必须与度量、主维度和期间字段不同")
        elif self.secondary_dimension_field is not None:
            raise ValueError("只有 cross_group_summary 接受 secondaryDimensionField")
        return self


def run_standard_supplemental(
    *,
    analysis_id: str,
    dataset_ids: Sequence[str],
    authorized_fields: Sequence[str],
    csv_content: bytes,
    request: StandardSupplementalRequest,
    authorized_query_scope: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """计算完整分组、期间分组、交叉分组、期间变化或登记比率分组。"""

    if request.dataset_id not in set(dataset_ids):
        raise ValueError("请求引用了未授权 dataset")
    authorized_query_scope = dict(authorized_query_scope or {})
    if any(
        authorized_query_scope.get(field) != request.scope[field]
        for field in request.query_bound_scope_fields
    ):
        raise ValueError("请求引用了未授权的查询固定范围")
    required_fields = {
        request.measure_field,
        request.dimension_field,
        request.period_field,
        *(set(request.scope) - set(request.query_bound_scope_fields)),
    }
    if request.secondary_dimension_field is not None:
        required_fields.add(request.secondary_dimension_field)
    if request.denominator_field is not None:
        required_fields.add(request.denominator_field)
    unauthorized = required_fields - set(authorized_fields)
    if unauthorized:
        raise ValueError(f"请求引用了未授权字段: {sorted(unauthorized)}")
    try:
        frame = read_analysis_csv(csv_content)
    except (UnicodeDecodeError, pl.exceptions.PolarsError) as error:
        raise ValueError("授权 CSV 无法解析") from error
    missing = required_fields - set(frame.columns)
    if missing:
        raise ValueError(f"CSV 缺少请求字段: {sorted(missing)}")
    frame = apply_metric_scope(
        frame,
        {
            field: value
            for field, value in request.scope.items()
            if field not in request.query_bound_scope_fields
        },
    )

    rows, warnings = _read_rows(frame, request)
    columns: list[str]
    column_meta: dict[str, dict[str, Any]]
    amount_columns: tuple[str, ...]
    if request.operation == "group_summary":
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
        columns = [request.dimension_field, "value", "rank", "share"]
        column_meta = {"rank": {"unit": "名"}, "share": {"unit": "%", "isPercent": False}}
        amount_columns = ("value",)
    elif request.operation == "group_period_series":
        finding_rows, period_totals = _period_group_rows(
            rows, request.current_periods, warnings,
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
        columns = [request.period_field, request.dimension_field, "value", "rank", "share"]
        column_meta = {"rank": {"unit": "名"}, "share": {"unit": "%", "isPercent": False}}
        amount_columns = ("value",)
    elif request.operation == "cross_group_summary":
        assert request.secondary_dimension_field is not None
        finding_rows, group_total = _cross_group_rows(rows)
        if not finding_rows:
            warnings.append("当前期间没有可计算的交叉分组")
        reconciliations = [
            _reconciliation(request.output_name + "_total", group_total, request.parent_total),
        ]
        if not reconciliations[0]["passed"]:
            warnings.append("交叉分组结果与父指标总额不闭合，保留结果并产生软告警")
        columns = [
            request.dimension_field, request.secondary_dimension_field,
            "value", "rank", "share",
        ]
        column_meta = {"rank": {"unit": "名"}, "share": {"unit": "%", "isPercent": False}}
        amount_columns = ("value",)
    elif request.operation == "period_comparison":
        assert request.baseline_parent_total is not None
        finding_rows, current_total, baseline_total, current_sum, baseline_sum = _comparison_rows(
            rows, request.current_periods, request.baseline_periods, warnings,
        )
        if not finding_rows:
            warnings.append("当前期间与对照期间没有可比较的有效分组")
        reconciliations = [
            _reconciliation(request.output_name + "_current_total", current_sum, request.parent_total),
            _reconciliation(request.output_name + "_baseline_total", baseline_sum, request.baseline_parent_total),
        ]
        if any(not item["passed"] for item in reconciliations):
            warnings.append("期间比较结果与父指标总额不闭合，保留结果并产生软告警")
        columns = [request.dimension_field, "current", "baseline", "change", "changeRate", "contribution"]
        column_meta = {
            "changeRate": {"unit": "%", "isPercent": False},
            "contribution": {"unit": "%", "isPercent": False},
        }
        amount_columns = ("current", "baseline", "change")
    else:
        assert request.denominator_field is not None
        assert request.denominator_parent_total is not None
        assert request.denominator_scale is not None
        finding_rows, numerator_total, denominator_total = _ratio_rows(
            rows, request.current_periods, request.denominator_scale, warnings,
        )
        if not finding_rows:
            warnings.append("当前期间没有可计算的有效分组比率")
        reconciliations = [
            _reconciliation(request.output_name + "_numerator_total", numerator_total, request.parent_total),
            _reconciliation(
                request.output_name + "_denominator_total",
                denominator_total,
                request.denominator_parent_total,
            ),
        ]
        if any(not item["passed"] for item in reconciliations):
            warnings.append("分组比率结果与分子或分母父指标总额不闭合，保留结果并产生软告警")
        columns = [request.dimension_field, "numerator", "denominator", "difference", "ratio"]
        column_meta = {"ratio": {"unit": "%", "isPercent": False}}
        amount_columns = ("numerator", "denominator", "difference")

    if request.measure_unit is not None:
        column_meta.update({column: {"unit": request.measure_unit} for column in amount_columns})
    periods = list(request.current_periods)
    if request.operation == "period_comparison":
        periods.extend(request.baseline_periods)
        for column in columns[1:]:
            selected_periods = (request.current_periods if column == "current" else
                                request.baseline_periods if column == "baseline" else periods)
            column_meta.setdefault(column, {}).update(periods=list(selected_periods))
        column_meta["current"]["periodRoles"] = ["current"]
        column_meta["baseline"]["periodRoles"] = ["prior"]

    logger.bind(analysis_id=analysis_id, operation=request.operation).info(
        "report_standard_supplemental_completed rows={} warnings={}",
        len(finding_rows), len(warnings),
    )
    return {
        "findings": [{"name": request.output_name, "columns": columns,
                      "columnMeta": column_meta, "scope": dict(request.scope),
                      "periodGranularity": request.period_granularity,
                      "periods": periods, "rows": finding_rows}],
        "reconciliations": reconciliations,
        "warnings": list(dict.fromkeys(warnings))[:100],
    }


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
    frame = read_analysis_csv(csv_content)
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
    if (not computed or finding.get("columns") != [request.dimension_field, "value", "rank", "share"]
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
        "periods": list(request.current_periods), "dimensionField": request.dimension_field,
        "measureField": request.measure_field, "unit": request.measure_unit,
        "members": members, "membersSha256": hashlib.sha256(encoded).hexdigest(),
        "memberCount": len(members), "sourceRowCount": frame.height,
        "selectedRowCount": len(selected), "invalidRowCount": 0, "completePopulation": True,
    }


def _read_rows(frame: pl.DataFrame, request: StandardSupplementalRequest) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    expressions = [pl.col(request.measure_field).cast(pl.Float64, strict=False).alias("__value")]
    if request.denominator_field is not None:
        expressions.append(
            pl.col(request.denominator_field).cast(pl.Float64, strict=False).alias("__denominator")
        )
    numeric = frame.with_columns(*expressions)
    rows: list[dict[str, Any]] = []
    baseline_periods = request.baseline_periods if request.operation == "period_comparison" else ()
    selected_periods = {
        metric_period_key(label, request.period_granularity): label
        for label in (*request.current_periods, *baseline_periods)
    }
    selected_columns = [request.period_field, request.dimension_field, "__value"]
    if request.secondary_dimension_field is not None:
        selected_columns.append(request.secondary_dimension_field)
    if request.denominator_field is not None:
        selected_columns.append("__denominator")
    for item in numeric.select(*selected_columns).to_dicts():
        period = item.get(request.period_field)
        dimension = item.get(request.dimension_field)
        secondary_dimension = (
            item.get(request.secondary_dimension_field)
            if request.secondary_dimension_field is not None else None
        )
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


def _period_group_rows(
    rows: Iterable[dict[str, Any]],
    current_periods: Sequence[str],
    warnings: list[str],
) -> tuple[list[list[Any]], dict[str, float]]:
    rows = list(rows)
    result: list[list[Any]] = []
    totals: dict[str, float] = {}
    for period in current_periods:
        grouped, total = _group_totals(row for row in rows if row["period"] == period)
        totals[period] = total
        if not grouped:
            warnings.append(f"期间 {period} 没有可计算的有效分组")
            continue
        ordered = sorted(
            grouped.items(), key=lambda item: (-item[1], item[0] is None, item[0] or ""),
        )
        result.extend(
            [period, dimension, value, index, value / total if total else None]
            for index, (dimension, value) in enumerate(ordered, start=1)
        )
        if total == 0:
            warnings.append(f"期间 {period} 分组占比分母为零，share 保留为空")
    return result, totals


def _cross_group_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[list[Any]], float]:
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
    return [
        [primary, secondary, value, index, value / total if total else None]
        for index, (primary, secondary, value) in enumerate(ordered, start=1)
    ], total


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
) -> tuple[list[list[Any]], float, float, float, float]:
    current_period_set = set(current_periods)
    baseline_period_set = set(baseline_periods)
    rows = list(rows)
    current, current_total = _group_totals(row for row in rows if row["period"] in current_period_set)
    baseline, baseline_total = _group_totals(row for row in rows if row["period"] in baseline_period_set)
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
                change / baseline_value
                if change is not None and baseline_value != 0
                else None
            )
            if baseline_value == 0:
                warnings.append(f"分组 {dimension if dimension is not None else 'null'} 对照值为零，changeRate 保留为空")
        total_change = current_total - baseline_total
        contribution = change / total_change if change is not None and total_change != 0 else None
        result.append([dimension, current_value, baseline_value, change, change_rate, contribution])
    return result, current_total, baseline_total, math.fsum(current.values()), math.fsum(baseline.values())


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


def standard_computation_candidates(
    facts: Any,
    datasets: Sequence[Any],
    requested_periods: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Advertise bounded, fully bound choices; never infer an operation from prose."""
    metrics = tuple(getattr(facts, "metrics", ()))
    metrics_by_id = {item.fact_id: item for item in metrics if getattr(item, "fact_id", None)}
    measures_by_dataset = {
        dataset.get("datasetId"): {
            item.field for item in metrics if item.dataset_id == dataset.get("datasetId")
        }
        for dataset in datasets
        if isinstance(dataset, dict)
    }
    buckets: dict[str, list[dict[str, Any]]] = {
        "group_summary": [], "group_period_series": [],
        "cross_group_summary": [], "period_comparison": [], "group_ratio": [],
    }
    seen: set[str] = set()

    def period_selection(parent: Any) -> tuple[tuple[str, ...], tuple[Any, ...], tuple[int, ...]] | None:
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
                return (
                    tuple(available_periods[index] for index in indexes),
                    valid_requested,
                    indexes,
                )
        return available_periods, valid_keys, tuple(range(len(available_periods)))

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
        buckets[spec.operation].append({
            "candidateId": candidate_id,
            "datasetId": dataset_id,
            "fields": sorted(fields),
            "label": label,
            "standardComputation": payload,
        })

    for dataset in datasets:
        if not isinstance(dataset, dict):
            continue
        dataset_id = dataset.get("datasetId")
        columns = set(dataset.get("columns") or ())
        measures = measures_by_dataset.get(dataset_id, set())
        profile = dataset.get("columnProfile") or {}
        for parent in metrics:
            if (parent.dataset_id != dataset_id or not parent.fact_id
                    or parent.aggregation != "sum" or parent.period_aggregation != "sum"
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
            selection = period_selection(parent)
            if selection is None:
                continue
            periods, valid_keys, period_indexes = selection
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
            for dimension in dimensions:
                role = profile.get(dimension, {}).get("role") if isinstance(profile, dict) else None
                if role in {"measure", "period", "empty"}:
                    continue
                operations: tuple[Literal["group_summary", "group_period_series"], ...] = (
                    "group_summary", "group_period_series",
                )
                specs = [
                    StandardSupplementalSpec(
                        operation=operation, measureField=parent.field,
                        dimensionField=dimension, periodField=parent.period_field,
                        currentPeriods=periods, parentFactId=parent.fact_id,
                    )
                    for operation in operations
                ]
                for baseline in metrics:
                    if ("current" not in getattr(parent, "period_roles", ())
                            or not set(getattr(baseline, "period_roles", ())) & {"yoy", "mom"}
                            or baseline.dataset_id != dataset_id or not baseline.fact_id
                            or baseline.field != parent.field or baseline.aggregation != "sum"
                            or baseline.period_aggregation != "sum" or baseline.cumulative_policy is not None
                            or baseline.period_field != parent.period_field
                            or getattr(baseline, "period_granularity", None) != getattr(parent, "period_granularity", None)
                            or getattr(baseline, "unit", None) != getattr(parent, "unit", None)
                            or getattr(baseline, "scope", {}) != getattr(parent, "scope", {})
                            or len(baseline.period_values) != len(parent.period_values)):
                        continue
                    prior = tuple(baseline.period_values[index].period for index in period_indexes)
                    prior_keys = [metric_period_key(label, getattr(baseline, "period_granularity", None)) for label in prior]
                    valid_prior_keys = [key for key in prior_keys if key is not None]
                    if (len(valid_prior_keys) != len(prior_keys)
                            or len(set(valid_prior_keys)) != len(valid_prior_keys)
                            or set(valid_keys) & set(valid_prior_keys)
                            or any(key[0] != valid_keys[0][0] for key in valid_prior_keys)):
                        continue
                    specs.append(StandardSupplementalSpec(
                        operation="period_comparison", measureField=parent.field,
                        dimensionField=dimension, periodField=parent.period_field,
                        currentPeriods=periods, baselinePeriods=prior,
                        parentFactId=parent.fact_id, baselineParentFactId=baseline.fact_id,
                    ))
                for spec in specs:
                    add_candidate(
                        dataset_id=dataset_id,
                        fields=required | {dimension},
                        label=getattr(parent, "display_name", None) or parent.field,
                        spec=spec,
                    )
            # 交叉构成最多枚举前8个已授权维度，最终目录仍受40项/24KB总预算约束。
            for primary_index, primary in enumerate(dimensions[:8]):
                for secondary in dimensions[primary_index + 1:8]:
                    add_candidate(
                        dataset_id=dataset_id,
                        fields=required | {primary, secondary},
                        label=getattr(parent, "display_name", None) or parent.field,
                        spec=StandardSupplementalSpec(
                            operation="cross_group_summary", measureField=parent.field,
                            dimensionField=primary, secondaryDimensionField=secondary,
                            periodField=parent.period_field, currentPeriods=periods,
                            parentFactId=parent.fact_id,
                        ),
                    )

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
                or getattr(ratio_fact, "percentage", None) is None
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
            selection = period_selection(numerator)
            if selection is None:
                continue
            numerator_periods, _, _ = selection
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
                    ),
                )

    candidates: list[dict[str, Any]] = []
    used_bytes = 0
    positions = {operation: 0 for operation in buckets}
    while len(candidates) < 40:
        added = False
        for operation in (
            "group_summary", "group_period_series", "cross_group_summary",
            "period_comparison", "group_ratio",
        ):
            position = positions[operation]
            if position >= len(buckets[operation]):
                continue
            candidate = buckets[operation][position]
            positions[operation] += 1
            size = len(json.dumps(candidate, ensure_ascii=False).encode())
            if used_bytes + size > 24_000:
                continue
            candidates.append(candidate)
            used_bytes += size
            added = True
            if len(candidates) >= 40:
                break
        if not added:
            if all(positions[operation] >= len(buckets[operation]) for operation in buckets):
                break
            # Oversized entries have already advanced their bucket; continue to later candidates.
            if used_bytes >= 24_000:
                break
    return candidates
