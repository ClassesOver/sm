"""冻结 CSV 快照内的受限单维度下钻（B7）。

本服务不接受路径、列名、过滤条件或聚合算法；调用方必须先从当前 revision
授权索引解析 ``TraceDatasetFile`` 与 ``DrilldownMetricV1``。读取只针对该快照，
不会查询源库，也不会扩大生成报告时的固定范围。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from functools import lru_cache

import polars as pl

from ..hospital_operation.deterministic_analysis import _parse_period
from ..models import ReportingError
from .contracts_v1 import (
    TRACE_BUDGETS_V1,
    DrilldownMetricV1,
    canonical_json_bytes,
)
from .dataset_service import TraceDatasetFile

@lru_cache(maxsize=4096)
def _period_date(label: str):
    """与冻结事实共用期间口径；缓存快照内重复的日期标签。"""
    parsed = _parse_period(label)
    return parsed.value if parsed is not None else None


def _period_expression(field: str) -> pl.Expr:
    return pl.col(field).cast(pl.String).map_elements(_period_date, return_dtype=pl.Date)


_DEFAULT_LIMIT = 50
_MAX_GROUPS = TRACE_BUDGETS_V1["drilldown_max_groups"]
_MAX_RESPONSE_BYTES = TRACE_BUDGETS_V1["drilldown_max_response_bytes"]
_CURSOR_TTL_SECONDS = 3600
_MAX_GROUP_LABEL_BYTES = 4096

_CALCULATION_DESCRIPTIONS = {
    "sum": "按登记范围对数值求和",
    "count": "按登记范围计算非空记录数",
    "count_distinct": "按登记范围计算去重值数",
    "average": "按登记范围计算算术平均值",
    "ratio": "按登记范围分别汇总分子与分母后相除",
    "semi_additive_last": "在全部分组共同的最新登记期间求和",
}


@dataclass(frozen=True)
class DrilldownPage:
    metric_code: str
    dataset_id: str
    dimension_code: str
    aggregation: str
    rows: tuple[tuple[str | None, float | int | None], ...]
    group_count_total: int
    offset: int
    limit: int
    next_cursor: str | None
    expected_value: float | None
    observed_value: float | int | None
    difference: float | None
    reconciled: bool | None
    unit: str | None
    snapshot_sha256: str
    fixed_scope: tuple[tuple[str, str], ...]
    period_start: str | None
    period_end: str | None
    truncated_labels: int = 0

    def to_payload(self) -> dict:
        return {
            "metricCode": self.metric_code,
            "datasetId": self.dataset_id,
            "dimensionCode": self.dimension_code,
            "aggregation": self.aggregation,
            "rows": [
                {"group": group, "value": value} for group, value in self.rows
            ],
            "groupCountTotal": self.group_count_total,
            "offset": self.offset,
            "limit": self.limit,
            "nextCursor": self.next_cursor,
            "unit": self.unit,
            "reconciliation": {
                "expectedValue": self.expected_value,
                "observedValue": self.observed_value,
                "difference": self.difference,
                "passed": self.reconciled,
            },
            "truncatedLabels": self.truncated_labels,
            "snapshot": {
                "datasetId": self.dataset_id,
                "sha256": self.snapshot_sha256,
            },
            "scope": {
                "kind": "registered_snapshot",
                "fixed": dict(self.fixed_scope),
                "period": (
                    {"start": self.period_start, "end": self.period_end}
                    if self.period_start is not None
                    else None
                ),
            },
            "calculation": {
                "aggregation": self.aggregation,
                "description": _CALCULATION_DESCRIPTIONS[self.aggregation],
            },
        }


class TraceDrilldownService:
    def __init__(self, *, secret: bytes) -> None:
        if not secret:
            raise ValueError("下钻游标签名密钥不能为空")
        self._secret = secret

    def drilldown(
        self,
        file: TraceDatasetFile,
        declaration: DrilldownMetricV1,
        *,
        dimension_code: str,
        report_id: str,
        revision: int,
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> DrilldownPage:
        if declaration.dataset_id != file.dataset_id:
            raise ReportingError("drilldown_unavailable", "下钻声明与数据集不匹配。")
        if not file.local_path.is_file():
            raise ReportingError("source_missing", "数据集快照文件不存在。")
        if not 1 <= limit <= _MAX_GROUPS:
            raise ReportingError(
                "request_invalid", f"每页分组数必须在 1~{_MAX_GROUPS} 之间。"
            )
        dimensions = {item.code: item for item in declaration.dimensions}
        dimension = dimensions.get(dimension_code)
        if dimension is None:
            raise ReportingError("drilldown_unavailable", "该指标未登记此下钻维度。")

        offset = 0
        if cursor is not None:
            payload = self._verify_cursor(cursor)
            expected = {
                "r": f"{report_id}#{revision}",
                "d": file.dataset_id,
                "h": file.sha256[:16],
                "m": declaration.metric_code,
                "x": dimension_code,
                "l": limit,
            }
            if any(payload.get(key) != value for key, value in expected.items()):
                raise ReportingError("cursor_invalid", "下钻游标与当前请求不匹配。")
            offset = payload.get("o", -1)
            if not isinstance(offset, int) or offset < 0:
                raise ReportingError("cursor_invalid", "下钻游标偏移无效。")

        lazy = self._validated_scan(file, declaration, dimension.field)
        filtered = self._fixed_scope(lazy, declaration)
        grouped = self._aggregate(filtered, declaration, dimension.field)
        try:
            page_query = (
                grouped.sort("__group", nulls_last=True)
                # 分组总数在分页前广播到结果，避免为了 count 和 page 对同一
                # 大快照执行两次完整 group-by。
                .with_columns(pl.len().alias("__total"))
            )
            if declaration.aggregation != "count_distinct":
                page_query = page_query.with_columns(
                    self._group_observed_expression(declaration).alias("__observed")
                )
            page_frame = page_query.slice(offset, limit + 1).collect(
                engine="streaming"
            )
            total = (
                int(page_frame["__total"][0])
                if page_frame.height
                else int(
                    grouped.select(pl.len())
                    .collect(engine="streaming")
                    .item()
                )
            )
            observed = (
                _finite_value(page_frame["__observed"][0])
                if page_frame.height
                and declaration.aggregation != "count_distinct"
                else self._observed_value(filtered, declaration)
            )
        except (OSError, pl.exceptions.PolarsError, ValueError, TypeError) as error:
            raise ReportingError(
                "snapshot_integrity_failed", "下钻快照无法按登记规则计算。"
            ) from error

        raw_rows = page_frame.head(limit).iter_rows(named=True)
        rows: list[tuple[str | None, float | int | None]] = []
        truncated_labels = 0
        for row in raw_rows:
            label, truncated = _bounded_label(row["__group"])
            truncated_labels += int(truncated)
            rows.append((label, _finite_value(row["__value"])))

        expected_value = declaration.expected_value
        difference = None
        reconciled = None
        if expected_value is not None and observed is not None:
            difference = float(observed) - expected_value
            reconciled = abs(difference) <= declaration.tolerance

        next_cursor = None
        if offset + len(rows) < total:
            next_cursor = self._sign_cursor(
                {
                    "r": f"{report_id}#{revision}",
                    "d": file.dataset_id,
                    "h": file.sha256[:16],
                    "m": declaration.metric_code,
                    "x": dimension_code,
                    "l": limit,
                    "o": offset + len(rows),
                    "exp": int(time.time()) + _CURSOR_TTL_SECONDS,
                }
            )
        result = DrilldownPage(
            metric_code=declaration.metric_code,
            dataset_id=file.dataset_id,
            dimension_code=dimension_code,
            aggregation=declaration.aggregation,
            rows=tuple(rows),
            group_count_total=total,
            offset=offset,
            limit=limit,
            next_cursor=next_cursor,
            expected_value=expected_value,
            observed_value=observed,
            difference=difference,
            reconciled=reconciled,
            unit=declaration.unit,
            snapshot_sha256=file.sha256,
            fixed_scope=tuple(sorted(declaration.fixed_scope.items())),
            period_start=declaration.period_start,
            period_end=declaration.period_end,
            truncated_labels=truncated_labels,
        )
        if len(canonical_json_bytes(result.to_payload())) > _MAX_RESPONSE_BYTES:
            raise ReportingError(
                "resource_limit_exceeded", "下钻响应超过资源预算，请缩小每页分组数。"
            )
        return result

    @staticmethod
    def _validated_scan(
        file: TraceDatasetFile, declaration: DrilldownMetricV1, dimension_field: str
    ) -> pl.LazyFrame:
        try:
            # 大快照只做投影后的流式聚合并启用 low-memory 解析，避免把
            # CSV 块长期保留在进程内。
            # CSV 没有字段类型；保留标识原文，数值只在聚合表达式中转换。
            lazy = pl.scan_csv(file.local_path, low_memory=True, infer_schema=False)
            columns = set(lazy.collect_schema().names())
        except (OSError, pl.exceptions.PolarsError) as error:
            raise ReportingError("snapshot_integrity_failed", "CSV 快照无法解析。") from error
        required = {dimension_field, *declaration.fixed_scope}
        for field in (
            declaration.value_field,
            declaration.numerator_field,
            declaration.denominator_field,
            declaration.period_field,
        ):
            if field is not None:
                required.add(field)
        if missing := sorted(required - columns):
            raise ReportingError(
                "drilldown_unavailable",
                "快照缺少下钻所需登记字段：" + ", ".join(missing[:5]),
            )
        return lazy

    @staticmethod
    def _fixed_scope(
        lazy: pl.LazyFrame, declaration: DrilldownMetricV1
    ) -> pl.LazyFrame:
        result = lazy
        for field, value in declaration.fixed_scope.items():
            result = result.filter(pl.col(field).cast(pl.String) == pl.lit(value))
        if declaration.period_start is not None:
            assert declaration.period_field is not None
            start = _period_date(declaration.period_start)
            end = _period_date(declaration.period_end)
            if start is None or end is None:
                raise ReportingError("drilldown_unavailable", "登记期间无法解析为日期。")
            period = _period_expression(declaration.period_field)
            result = result.filter((period >= pl.lit(start)) & (period <= pl.lit(end)))
        return result

    @classmethod
    def _aggregate(
        cls,
        lazy: pl.LazyFrame,
        declaration: DrilldownMetricV1,
        dimension_field: str,
    ) -> pl.LazyFrame:
        group = (
            pl.col(dimension_field)
            .cast(pl.String)
            .alias("__group")
        )
        frame = lazy.with_columns(group)
        if declaration.aggregation == "semi_additive_last":
            period = declaration.period_field
            assert period is not None and declaration.value_field is not None
            # 时点指标必须让所有分组使用同一个冻结报告时点；逐组各取自己的
            # “最新”会把不同日期的余额混在同一结果中，不能用于总体对账。
            latest = frame.select(
                _period_expression(period).max().alias("__latest")
            )
            frame = frame.with_columns(
                _period_expression(period).alias("__period")
            ).join(latest, how="cross")
            return frame.filter(pl.col("__period") == pl.col("__latest")).group_by(
                "__group"
            ).agg(
                pl.col(declaration.value_field)
                .cast(pl.Float64, strict=False)
                .sum()
                .alias("__value")
            )
        if declaration.aggregation == "ratio":
            assert declaration.numerator_field and declaration.denominator_field
            grouped = frame.group_by("__group").agg(
                pl.col(declaration.numerator_field)
                .cast(pl.Float64, strict=False)
                .sum()
                .alias("__numerator"),
                pl.col(declaration.denominator_field)
                .cast(pl.Float64, strict=False)
                .sum()
                .alias("__denominator"),
            )
            return grouped.with_columns(
                pl.when(pl.col("__denominator") != 0)
                .then(pl.col("__numerator") / pl.col("__denominator"))
                .otherwise(None)
                .alias("__value")
            )
        if declaration.aggregation == "average":
            assert declaration.value_field is not None
            numeric = pl.col(declaration.value_field).cast(
                pl.Float64, strict=False
            )
            grouped = frame.group_by("__group").agg(
                numeric.sum().alias("__sum"), numeric.count().alias("__count")
            )
            return grouped.with_columns(
                pl.when(pl.col("__count") != 0)
                .then(pl.col("__sum") / pl.col("__count"))
                .otherwise(None)
                .alias("__value")
            )
        return frame.group_by("__group").agg(
            cls._value_expression(declaration).alias("__value")
        )

    @staticmethod
    def _group_observed_expression(declaration: DrilldownMetricV1) -> pl.Expr:
        """从互斥完整分组的隐藏状态计算总体；去重必须独立扫原始标识。"""

        if declaration.aggregation == "ratio":
            numerator = pl.col("__numerator").sum()
            denominator = pl.col("__denominator").sum()
            return pl.when(denominator != 0).then(numerator / denominator).otherwise(None)
        if declaration.aggregation == "average":
            total = pl.col("__sum").sum()
            count = pl.col("__count").sum()
            return pl.when(count != 0).then(total / count).otherwise(None)
        return pl.col("__value").sum()

    @classmethod
    def _observed_value(
        cls, lazy: pl.LazyFrame, declaration: DrilldownMetricV1
    ) -> float | int | None:
        if declaration.aggregation == "semi_additive_last":
            assert declaration.period_field is not None
            assert declaration.value_field is not None
            latest = lazy.select(
                _period_expression(declaration.period_field).max()
            ).collect(engine="streaming").item()
            if latest is None:
                return None
            value = (
                lazy.filter(
                    _period_expression(declaration.period_field) == pl.lit(latest)
                )
                .select(cls._value_expression(declaration))
                .collect(engine="streaming")
                .item()
            )
        else:
            value = (
                lazy.select(cls._value_expression(declaration))
                .collect(engine="streaming")
                .item()
            )
        return _finite_value(value)

    @staticmethod
    def _value_expression(declaration: DrilldownMetricV1) -> pl.Expr:
        if declaration.aggregation == "ratio":
            assert declaration.numerator_field and declaration.denominator_field
            numerator = pl.col(declaration.numerator_field).cast(
                pl.Float64, strict=False
            ).sum()
            denominator = pl.col(declaration.denominator_field).cast(
                pl.Float64, strict=False
            ).sum()
            return pl.when(denominator != 0).then(numerator / denominator).otherwise(None)
        assert declaration.value_field is not None
        source = pl.col(declaration.value_field)
        if declaration.aggregation == "count":
            return source.is_not_null().sum()
        if declaration.aggregation == "count_distinct":
            return source.drop_nulls().n_unique()
        numeric = source.cast(pl.Float64, strict=False)
        if declaration.aggregation == "average":
            return numeric.mean()
        return numeric.sum()

    def _sign_cursor(self, payload: dict) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        signature = hmac.new(self._secret, raw, hashlib.sha256).digest()
        return f"{_b64(raw)}.{_b64(signature)}"

    def _verify_cursor(self, cursor: str) -> dict:
        try:
            body, signature = cursor.split(".", 1)
            raw = _unb64(body)
            provided = _unb64(signature)
        except (ValueError, UnicodeError) as error:
            raise ReportingError("cursor_invalid", "下钻游标格式无效。") from error
        expected = hmac.new(self._secret, raw, hashlib.sha256).digest()
        if not hmac.compare_digest(provided, expected):
            raise ReportingError("cursor_invalid", "下钻游标签名无效。")
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ReportingError("cursor_invalid", "下钻游标载荷无效。") from error
        expiry = payload.get("exp", 0)
        if not isinstance(expiry, int) or expiry < time.time():
            raise ReportingError("cursor_invalid", "下钻游标已过期。")
        return payload


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    encoded = value.encode("ascii")
    return base64.urlsafe_b64decode(encoded + b"=" * (-len(encoded) % 4))


def _finite_value(value: object) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("下钻结果不是数值")
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _bounded_label(value: object) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    label = str(value)
    encoded = label.encode("utf-8")
    if len(encoded) <= _MAX_GROUP_LABEL_BYTES:
        return label, False
    bounded = encoded[:_MAX_GROUP_LABEL_BYTES]
    while True:
        try:
            return bounded.decode("utf-8") + "…", True
        except UnicodeDecodeError:
            bounded = bounded[:-1]
