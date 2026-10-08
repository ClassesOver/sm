"""从冻结 facts、Profile 与快照列生成 B7 下钻声明。

无法唯一映射的指标或维度直接不声明（能力不可用），绝不按相似列名猜测。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts_v1 import DrilldownDimensionV1, DrilldownMetricV1

_SUPPORTED_BASE = {"sum", "count", "count_distinct", "average"}


def build_drilldown_metrics(
    *,
    bundles: Sequence[Mapping[str, Any]],
    dataset_columns: Mapping[str, Sequence[str]],
    profile_dimensions: Sequence[Mapping[str, Any]],
    profile_metrics: Sequence[Mapping[str, Any]],
    measure_semantics: Sequence[Mapping[str, Any]],
    row_preserving_dataset_ids: Sequence[str] = (),
) -> tuple[DrilldownMetricV1, ...]:
    """只为字段、范围和答案均可冻结且至少有一个维度的指标签发能力。"""

    columns_by_dataset = {
        dataset_id: tuple(dict.fromkeys(str(item) for item in columns))
        for dataset_id, columns in dataset_columns.items()
    }
    metrics_by_code = {
        str(item.get("code")): item for item in profile_metrics if item.get("code")
    }
    semantics_by_ref = {
        str(item.get("fieldRef", "")).casefold(): item
        for item in measure_semantics
        if item.get("fieldRef")
    }
    candidates: list[DrilldownMetricV1] = []
    row_preserving = set(row_preserving_dataset_ids)
    base_by_code_dataset: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    derived: list[Mapping[str, Any]] = []

    for bundle in bundles:
        for fact in _items(bundle.get("metrics")):
            dataset_id = str(fact.get("datasetId", ""))
            columns = columns_by_dataset.get(dataset_id)
            field_ref = str(fact.get("fieldRef", ""))
            value_field = str(fact.get("field", ""))
            aggregation = str(fact.get("aggregation", ""))
            if (
                not columns
                or value_field not in columns
                or aggregation not in _SUPPORTED_BASE
                or not field_ref
            ):
                continue
            if aggregation in {"average", "count", "count_distinct"} and dataset_id not in row_preserving:
                # 聚合快照只保存 AVG/COUNT 的结果时，没有权重、原始标识等可合并
                # 状态；再次 average/count/distinct 会得到错误答案，必须关闭能力。
                continue
            codes = tuple(
                str(code)
                for code in fact.get("metricCodes", ())
                if str(code) in metrics_by_code
            )
            for code in dict.fromkeys(codes):
                base_by_code_dataset.setdefault((code, dataset_id), []).append(fact)
                declaration = _base_declaration(
                    code=code,
                    fact=fact,
                    columns=columns,
                    profile_dimensions=profile_dimensions,
                    semantic=semantics_by_ref.get(field_ref.casefold()),
                )
                if declaration is not None:
                    candidates.append(declaration)
        derived.extend(_items(bundle.get("derivedMetrics")))

    for fact in derived:
        code = str(fact.get("code", ""))
        profile_metric = metrics_by_code.get(code)
        if not profile_metric or profile_metric.get("aggregation") != "ratio":
            continue
        numerator_code = str(fact.get("numeratorMetric", ""))
        denominator_code = str(fact.get("denominatorMetric", ""))
        if (
            numerator_code != str(profile_metric.get("numeratorMetric", ""))
            or denominator_code != str(profile_metric.get("denominatorMetric", ""))
        ):
            continue
        for dataset_id in dict.fromkeys(str(item) for item in fact.get("datasetIds", ())):
            numerator = base_by_code_dataset.get((numerator_code, dataset_id), ())
            denominator = base_by_code_dataset.get((denominator_code, dataset_id), ())
            if len(numerator) != 1 or len(denominator) != 1:
                continue
            declaration = _ratio_declaration(
                code=code,
                expected=fact.get("value"),
                fact_key=fact.get("factId"),
                numerator=numerator[0],
                denominator=denominator[0],
                columns=columns_by_dataset.get(dataset_id, ()),
                profile_dimensions=profile_dimensions,
                semantics_by_ref=semantics_by_ref,
                unit=fact.get("unit"),
            )
            if declaration is not None:
                candidates.append(declaration)

    # 同一 metric+dataset 只有完全相同的声明才能去重；任何冲突都关闭能力。
    by_key: dict[tuple[str, str], list[DrilldownMetricV1]] = {}
    for item in candidates:
        by_key.setdefault((item.metric_code, item.dataset_id), []).append(item)
    result: list[DrilldownMetricV1] = []
    for key in sorted(by_key):
        items = by_key[key]
        payloads = {
            item.model_dump_json(by_alias=True, exclude_none=True) for item in items
        }
        if len(payloads) == 1:
            result.append(items[0])
    return tuple(result)


def _base_declaration(
    *,
    code: str,
    fact: Mapping[str, Any],
    columns: Sequence[str],
    profile_dimensions: Sequence[Mapping[str, Any]],
    semantic: Mapping[str, Any] | None,
) -> DrilldownMetricV1 | None:
    field_ref = str(fact["fieldRef"])
    aggregation = str(fact["aggregation"])
    additive = {
        str(item).casefold() for item in (semantic or {}).get("additiveAcross", ())
    }
    period_field = _optional_column(fact.get("periodField"), columns)
    if fact.get("periodField") and period_field is None:
        return None
    if (fact.get("periodStart") is None) != (fact.get("periodEnd") is None):
        return None
    if aggregation == "sum" and period_field and additive and period_field.casefold() not in additive:
        algorithm = "semi_additive_last"
    else:
        algorithm = aggregation
    dimensions = _dimensions(
        field_ref,
        columns,
        profile_dimensions,
        allowed_fields=additive if aggregation == "sum" else None,
        excluded_field=period_field if algorithm == "semi_additive_last" else None,
    )
    scope = _scope(fact, columns)
    expected = _finite(fact.get("total"))
    if not dimensions or scope is None or expected is None:
        return None
    return DrilldownMetricV1(
        metricCode=code,
        datasetId=str(fact["datasetId"]),
        aggregation=algorithm,
        valueField=str(fact["field"]),
        periodField=period_field,
        periodStart=fact.get("periodStart") if period_field else None,
        periodEnd=fact.get("periodEnd") if period_field else None,
        dimensions=dimensions,
        fixedScope=scope,
        expectedValue=expected,
        tolerance=max(0.01, abs(expected) * 1e-9),
        unit=fact.get("unit"),
        factKeys=(str(fact["factId"]),) if fact.get("factId") else (),
    )


def _ratio_declaration(
    *,
    code: str,
    expected: object,
    fact_key: object,
    numerator: Mapping[str, Any],
    denominator: Mapping[str, Any],
    columns: Sequence[str],
    profile_dimensions: Sequence[Mapping[str, Any]],
    semantics_by_ref: Mapping[str, Mapping[str, Any]],
    unit: object,
    # 当前 ratio 声明只表达求和后相除，不支持计数、平均或跨期间时点值。
    for fact in (numerator, denominator):
        if fact.get("aggregation") != "sum":
            return None
        period = fact.get("periodField")
        additive = _additive_fields(
            semantics_by_ref.get(str(fact.get("fieldRef", "")).casefold())
        )
        if period and str(period).casefold() not in additive:
            return None
) -> DrilldownMetricV1 | None:
    value = _finite(expected)
    numerator_field = str(numerator.get("field", ""))
    denominator_field = str(denominator.get("field", ""))
    if value is None or numerator_field not in columns or denominator_field not in columns:
        return None
    if (
        numerator.get("datasetId") != denominator.get("datasetId")
        or numerator.get("scope", {}) != denominator.get("scope", {})
        or numerator.get("periodField") != denominator.get("periodField")
        or numerator.get("periodStart") != denominator.get("periodStart")
        or numerator.get("periodEnd") != denominator.get("periodEnd")
    ):
        return None
    numerator_ref = str(numerator.get("fieldRef", ""))
    denominator_ref = str(denominator.get("fieldRef", ""))
    left = _dimensions(
        numerator_ref,
        columns,
        profile_dimensions,
        allowed_fields=_additive_fields(semantics_by_ref.get(numerator_ref.casefold())),
    )
    right_codes = {
        item.code
        for item in _dimensions(
            denominator_ref,
            columns,
            profile_dimensions,
            allowed_fields=_additive_fields(
                semantics_by_ref.get(denominator_ref.casefold())
            ),
        )
    }
    dimensions = tuple(item for item in left if item.code in right_codes)
    scope = _scope(numerator, columns)
    period_field = _optional_column(numerator.get("periodField"), columns)
    if numerator.get("periodField") and period_field is None:
        return None
    if not dimensions or scope is None:
        return None
    return DrilldownMetricV1(
        metricCode=code,
        datasetId=str(numerator["datasetId"]),
        aggregation="ratio",
        numeratorField=numerator_field,
        denominatorField=denominator_field,
        periodField=period_field,
        periodStart=numerator.get("periodStart") if period_field else None,
        periodEnd=numerator.get("periodEnd") if period_field else None,
        dimensions=dimensions,
        fixedScope=scope,
        expectedValue=value,
        tolerance=max(0.01, abs(value) * 1e-9),
        unit=unit,
        factKeys=(str(fact_key),) if fact_key else (),
    )


def _dimensions(
    metric_ref: str,
    columns: Sequence[str],
    profile_dimensions: Sequence[Mapping[str, Any]],
    *,
    allowed_fields: set[str] | None = None,
    excluded_field: str | None = None,
) -> tuple[DrilldownDimensionV1, ...]:
    prefix = metric_ref.rsplit(".", 1)[0].casefold()
    available = set(columns)
    result: list[DrilldownDimensionV1] = []
    for dimension in profile_dimensions:
        code = str(dimension.get("code", ""))
        candidates = [
            str(ref).rsplit(".", 1)[-1]
            for ref in dimension.get("fieldRefs", ())
            if str(ref).rsplit(".", 1)[0].casefold() == prefix
            and str(ref).rsplit(".", 1)[-1] in available
        ]
        if len(candidates) != 1:
            continue
        field = candidates[0]
        if allowed_fields is not None and field.casefold() not in allowed_fields:
            continue
        if excluded_field is not None and field == excluded_field:
            continue
        result.append(
            DrilldownDimensionV1(
                code=code,
                field=field,
                label=str(dimension.get("description") or code),
            )
        )
    return tuple(result)


def _scope(fact: Mapping[str, Any], columns: Sequence[str]) -> dict[str, str] | None:
    raw = fact.get("scope", {})
    if not isinstance(raw, Mapping):
        return None
    available = set(columns)
    result = {str(key): str(value) for key, value in raw.items()}
    return result if set(result) <= available else None


def _optional_column(value: object, columns: Sequence[str]) -> str | None:
    return str(value) if value is not None and str(value) in set(columns) else None


def _additive_fields(semantic: Mapping[str, Any] | None) -> set[str]:
    return {
        str(item).casefold() for item in (semantic or {}).get("additiveAcross", ())
    }


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _items(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))
