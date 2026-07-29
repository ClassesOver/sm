from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

import anyio

from ..contract import ReportPeriod
from ..data_source import DataSourceAdapter, QueryResult, StarRocksSourceConfig
from ..models import ReportingError
from .context import CapabilitySet, ReconciliationShape
from .models import (
    EffectiveDimension,
    EffectiveMetric,
    EffectiveReportingProfile,
    FieldReference,
    parse_field_ref,
)


async def collect_reconciliation_shapes(
    profile: EffectiveReportingProfile,
    capabilities: CapabilitySet,
    *,
    adapters: Mapping[str, DataSourceAdapter],
    sources: Mapping[str, StarRocksSourceConfig],
    period: ReportPeriod,
) -> tuple[ReconciliationShape, ...]:
    capability_map = capabilities.by_code()
    metrics = {item.code: item for item in profile.metrics}
    dimensions = {item.code: item for item in profile.dimensions}
    result: list[ReconciliationShape] = []
    for rule in profile.reconciliations:
        capability = capability_map[rule.code]
        if not capability.available:
            result.append(
                ReconciliationShape(
                    code=rule.code,
                    status="unavailable",
                    leftMetric=rule.left_metric,
                    rightMetric=rule.right_metric,
                    grain=rule.grain,
                    issues=capability.reasons,
                )
            )
            continue
        left_metric = metrics[rule.left_metric]
        right_metric = metrics[rule.right_metric]
        left_ref = parse_field_ref(left_metric.field_ref or "")
        right_ref = parse_field_ref(right_metric.field_ref or "")
        left_grain = _grain_refs(rule.grain, dimensions, left_ref)
        right_grain = _grain_refs(rule.grain, dimensions, right_ref)
        left: dict[tuple[str, ...], Decimal] | None = None
        right: dict[tuple[str, ...], Decimal] | None = None
        errors: list[Exception | None] = [None, None]

        async def query_left() -> None:
            nonlocal left
            try:
                left = await _query_side(
                    left_metric,
                    left_ref,
                    left_grain,
                    adapters=adapters,
                    sources=sources,
                    period=period,
                )
            except Exception as error:
                errors[0] = error

        async def query_right() -> None:
            nonlocal right
            try:
                right = await _query_side(
                    right_metric,
                    right_ref,
                    right_grain,
                    adapters=adapters,
                    sources=sources,
                    period=period,
                )
            except Exception as error:
                errors[1] = error

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(query_left)
            task_group.start_soon(query_right)
        failure = next((error for error in errors if error is not None), None)
        if failure is not None:
            if isinstance(failure, ReportingError):
                raise failure
            raise ReportingError("report_reconciliation_failed", "对账查询失败。") from failure
        if left is None or right is None:
            raise ReportingError("report_reconciliation_failed", "对账查询结果不完整。")
        common = set(left) & set(right)
        left_total = sum(left.values(), Decimal(0))
        right_total = sum(right.values(), Decimal(0))
        difference = left_total - right_total
        difference_rate = float(difference / right_total) if right_total else None
        exceeds = abs(difference) > Decimal(str(rule.absolute_tolerance)) and (
            difference_rate is None or abs(difference_rate) > rule.relative_tolerance
        )
        issues: list[str] = []
        if set(left) - set(right):
            issues.append("左侧存在右侧缺失的共同粒度键。")
        if set(right) - set(left):
            issues.append("右侧存在左侧缺失的共同粒度键。")
        if right_total == 0:
            issues.append("右侧总额为零，无法计算总体差异率。")
        if exceeds:
            issues.append("总体差异超过配置容差。")
        result.append(
            ReconciliationShape(
                code=rule.code,
                status="completed",
                leftMetric=rule.left_metric,
                rightMetric=rule.right_metric,
                grain=rule.grain,
                leftTotal=str(left_total),
                rightTotal=str(right_total),
                difference=str(difference),
                differenceRate=difference_rate,
                commonKeyCount=len(common),
                leftOnlyKeyCount=len(set(left) - set(right)),
                rightOnlyKeyCount=len(set(right) - set(left)),
                zeroDenominatorCount=sum(1 for key in common if right[key] == 0),
                exceedsTolerance=exceeds,
                issues=tuple(issues),
            )
        )
    return tuple(result)


def _grain_refs(
    grain: tuple[str, ...],
    dimensions: Mapping[str, EffectiveDimension],
    metric_ref: FieldReference,
) -> tuple[FieldReference, ...]:
    result: list[FieldReference] = []
    for code in grain:
        matches = [
            parsed
            for value in dimensions[code].field_refs
            if (parsed := parse_field_ref(value)).source_id == metric_ref.source_id
            and parsed.qualified_table == metric_ref.qualified_table
        ]
        if len(matches) != 1:
            raise ReportingError(
                "report_reconciliation_invalid",
                "对账粒度必须在每个指标表中具有唯一字段映射。",
            )
        result.append(matches[0])
    return tuple(result)


async def _query_side(
    metric: EffectiveMetric,
    metric_ref: FieldReference,
    grain: tuple[FieldReference, ...],
    *,
    adapters: Mapping[str, DataSourceAdapter],
    sources: Mapping[str, StarRocksSourceConfig],
    period: ReportPeriod,
) -> dict[tuple[str, ...], Decimal]:
    adapter = adapters.get(metric_ref.source_id)
    source = sources.get(metric_ref.source_id)
    if adapter is None or source is None:
        raise ReportingError("report_reconciliation_invalid", "对账指标数据源不存在。")
    period_column = source.period_columns.get(metric_ref.qualified_table)
    if period_column is None:
        raise ReportingError("report_reconciliation_invalid", "对账指标表缺少期间字段。")
    period_granularity = source.period_granularities.get(metric_ref.qualified_table, "date")
    aliases = tuple(f"g{index}" for index in range(len(grain)))
    dimensions = ", ".join(
        f"{_identifier(item.column)} AS {alias}" for item, alias in zip(grain, aliases, strict=True)
    )
    value = _identifier(metric_ref.column)
    aggregate = f"SUM({value})" if metric.aggregation == "sum" else f"COUNT({value})"
    group = ", ".join(_identifier(item.column) for item in grain)
    if period_granularity == "year":
        period_filter = (
            f"{_identifier(period_column)} >= {period.start.year} "
            f"AND {_identifier(period_column)} <= {period.end.year}"
        )
    else:
        period_filter = (
            f"{_identifier(period_column)} >= '{period.start.isoformat()}' "
            f"AND {_identifier(period_column)} <= '{period.end.isoformat()}'"
        )
    sql = (
        f"SELECT {dimensions}, {aggregate} AS metric_value "
        f"FROM {_identifier(metric_ref.database)}.{_identifier(metric_ref.table)} "
        f"WHERE {period_filter} "
        f"GROUP BY {group}"
    )
    query_result = await adapter.query(sql)
    return _rows(query_result, aliases)


def _rows(result: QueryResult, aliases: tuple[str, ...]) -> dict[tuple[str, ...], Decimal]:
    expected = (*aliases, "metric_value")
    if result.columns != expected:
        raise ReportingError("report_reconciliation_failed", "对账查询返回字段无效。")
    values: dict[tuple[str, ...], Decimal] = {}
    for row in result.rows:
        if len(row) != len(expected):
            raise ReportingError("report_reconciliation_failed", "对账查询返回行无效。")
        key = tuple("<null>" if value is None else str(value) for value in row[:-1])
        try:
            value = Decimal(str(row[-1] or 0))
        except InvalidOperation as error:
            raise ReportingError(
                "report_reconciliation_failed", "对账指标不是有效数值。"
            ) from error
        if not value.is_finite():
            raise ReportingError("report_reconciliation_failed", "对账指标不是有限数值。")
        if key in values:
            raise ReportingError("report_reconciliation_failed", "对账查询共同粒度不唯一。")
        values[key] = value
    return values


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
        raise ReportingError("report_reconciliation_invalid", "对账配置包含无效标识符。")
    return f"`{value}`"
