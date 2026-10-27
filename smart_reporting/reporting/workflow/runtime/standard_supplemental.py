"""服务端标准补证计算的窄接口。

输入必须已经通过当前分析的 dataset、字段和期间授权；本模块不解析自由文本公式，
也不访问数据库或工作区路径。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from typing import Any, Literal

import polars as pl
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...hospital_operation.deterministic_analysis import (
    additive_group_totals,
    apply_metric_scope,
    metric_period_key,
    read_analysis_csv,
    reconciliation_passes,
)


class StandardSupplementalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    operation: Literal["group_summary", "period_comparison"]
    dataset_id: str = Field(min_length=1, alias="datasetId")
    output_name: str = Field(min_length=1, alias="outputName")
    measure_field: str = Field(min_length=1, alias="measureField")
    measure_unit: str | None = Field(default=None, min_length=1, alias="measureUnit")
    dimension_field: str = Field(min_length=1, alias="dimensionField")
    period_field: str = Field(min_length=1, alias="periodField")
    period_granularity: Literal["day", "month", "year"] | None = Field(default=None, alias="periodGranularity")
    current_periods: tuple[str, ...] = Field(min_length=1, alias="currentPeriods")
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    parent_total: float = Field(alias="parentTotal")
    baseline_parent_total: float | None = Field(default=None, alias="baselineParentTotal")
    scope: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_baseline_for_comparison(self) -> StandardSupplementalRequest:
        if self.operation == "period_comparison" and not self.baseline_periods:
            raise ValueError("period_comparison 必须提供 baselinePeriods")
        if self.operation == "period_comparison" and self.baseline_parent_total is None:
            raise ValueError("period_comparison 必须提供 baselineParentTotal")
        current_keys = [metric_period_key(label, self.period_granularity) for label in self.current_periods]
        baseline_keys = ([metric_period_key(label, self.period_granularity) for label in self.baseline_periods]
                         if self.operation == "period_comparison" else [])
        keys = [*current_keys, *baseline_keys]
        if None in keys or len({key[0] for key in keys if key is not None}) != 1:
            raise ValueError("标准补证期间必须可解析且粒度相同")
        if len(keys) != len(set(keys)):
            raise ValueError("标准补证期间不能重复或重叠（含期间别名）")
        return self


class StandardSupplementalSpec(BaseModel):
    """结构化路由声明；父总额只引用冻结 deterministic fact，不接受模型数值。"""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    operation: Literal["group_summary", "period_comparison"]
    measure_field: str = Field(min_length=1, alias="measureField")
    dimension_field: str = Field(min_length=1, alias="dimensionField")
    period_field: str = Field(min_length=1, alias="periodField")
    current_periods: tuple[str, ...] = Field(min_length=1, alias="currentPeriods")
    baseline_periods: tuple[str, ...] = Field(default=(), alias="baselinePeriods")
    parent_fact_id: str = Field(min_length=1, alias="parentFactId")
    baseline_parent_fact_id: str | None = Field(default=None, alias="baselineParentFactId")

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
            raise ValueError("group_summary 不接受对照期间")
        return self


def run_standard_supplemental(
    *,
    analysis_id: str,
    dataset_ids: Sequence[str],
    authorized_fields: Sequence[str],
    csv_content: bytes,
    request: StandardSupplementalRequest,
) -> dict[str, Any]:
    """计算完整分组或期间变化，返回可交给 SupplementalEvidence 校验的字典。"""

    if request.dataset_id not in set(dataset_ids):
        raise ValueError("请求引用了未授权 dataset")
    required_fields = {
        request.measure_field,
        request.dimension_field,
        request.period_field,
        *request.scope,
    }
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
    frame = apply_metric_scope(frame, request.scope)

    rows, warnings = _read_rows(frame, request)
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
    else:
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

    if request.measure_unit is not None:
        column_meta.update({column: {"unit": request.measure_unit} for column in amount_columns})

    logger.bind(analysis_id=analysis_id, operation=request.operation).info(
        "report_standard_supplemental_completed rows={} warnings={}",
        len(finding_rows), len(warnings),
    )
    return {
        "findings": [{"name": request.output_name, "columns": columns,
                      "columnMeta": column_meta, "scope": dict(request.scope),
                      "periodGranularity": request.period_granularity,
                      "periods": list(request.current_periods), "rows": finding_rows}],
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
    numeric = frame.with_columns(
        pl.col(request.measure_field).cast(pl.Float64, strict=False).alias("__value"),
    )
    rows: list[dict[str, Any]] = []
    baseline_periods = request.baseline_periods if request.operation == "period_comparison" else ()
    selected_periods = {
        metric_period_key(label, request.period_granularity): label
        for label in (*request.current_periods, *baseline_periods)
    }
    for item in numeric.select(
        request.period_field, request.dimension_field, "__value"
    ).to_dicts():
        period = item.get(request.period_field)
        dimension = item.get(request.dimension_field)
        value = item.get("__value")
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
        if value is None or not math.isfinite(float(value)):
            warnings.append(f"分组 {dimension if dimension is not None else 'null'} 存在不可解析数值，已跳过")
            continue
        rows.append({"period": str(period), "dimension": str(dimension) if dimension is not None else None, "value": float(value)})
    return rows, warnings


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
