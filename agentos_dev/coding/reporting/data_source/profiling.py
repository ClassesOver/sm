from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

import anyio

from ..models import ReportingError
from .models import (
    CatalogColumn,
    CatalogTable,
    ColumnShape,
    DataShape,
    DataSourceAdapter,
    QueryResult,
    TableDataShape,
    TopValue,
)

STATISTICS_VERSION = "1"
_NUMERIC_TYPES = re.compile(
    r"^(?:TINYINT|SMALLINT|INT|INTEGER|BIGINT|LARGEINT|FLOAT|DOUBLE|DECIMAL)",
    re.IGNORECASE,
)
_BOUNDED_TYPES = re.compile(
    r"^(?:TINYINT|SMALLINT|INT|INTEGER|BIGINT|LARGEINT|FLOAT|DOUBLE|DECIMAL|"
    r"DATE|DATETIME|TIMESTAMP)",
    re.IGNORECASE,
)


async def collect_data_shape(
    adapter: DataSourceAdapter,
    *,
    catalog_scope: tuple[CatalogTable, ...],
    period_start: date,
    period_end: date,
    period_columns: Mapping[str, str],
    period_granularities: Mapping[str, Literal["date", "year"]] | None = None,
    metadata_revision: str,
    schema_hash: str,
    global_limiter: anyio.CapacityLimiter | None = None,
) -> DataShape:
    if period_start > period_end:
        raise ReportingError("report_period_invalid", "报表期间无效。")
    try:
        catalog = await adapter.catalog()
        _validate_catalog(adapter, catalog)
        catalog = _catalog_scope(adapter, catalog, catalog_scope)
        for table in catalog:
            period_column = period_columns.get(table.qualified_name)
            if not period_column or period_column not in {item.name for item in table.columns}:
                raise ReportingError(
                    "report_period_column_missing",
                    f"数据表 {table.qualified_name} 缺少有效的期间字段映射。",
                )
            granularity = (period_granularities or {}).get(table.qualified_name, "date")
            if granularity not in {"date", "year"}:
                raise ReportingError(
                    "report_period_granularity_invalid", "数据表期间粒度配置无效。"
                )
        source_limiter = anyio.CapacityLimiter(adapter.config.limits.profile_concurrency)
        results: list[tuple[TableDataShape, int] | None] = [None] * len(catalog)

        async def profile(index: int, table: CatalogTable) -> None:
            results[index] = await _profile_table(
                adapter,
                table,
                period_column=period_columns[table.qualified_name],
                period_granularity=(period_granularities or {}).get(table.qualified_name, "date"),
                period_start=period_start,
                period_end=period_end,
                source_limiter=source_limiter,
                global_limiter=global_limiter,
            )

        async with anyio.create_task_group() as task_group:
            for index, table in enumerate(catalog):
                task_group.start_soon(profile, index, table)

        completed = [item for item in results if item is not None]
        if len(completed) != len(catalog):
            raise ReportingError("report_data_shape_failed", "数据画像采集结果不完整。")
        shapes = [item[0] for item in completed]
        query_count = sum(item[1] for item in completed)
        return DataShape(
            sourceId=adapter.config.id,
            metadataRevision=metadata_revision,
            schemaHash=schema_hash,
            statisticsVersion=STATISTICS_VERSION,
            queryCount=query_count,
            periodStart=period_start.isoformat(),
            periodEnd=period_end.isoformat(),
            tables=tuple(shapes),
        )
    except ReportingError as error:
        if error.code in {"report_period_invalid", "report_period_column_missing"}:
            raise
        raise ReportingError("report_data_shape_failed", "数据画像采集失败。") from error
    except Exception as error:
        raise ReportingError("report_data_shape_failed", "数据画像采集失败。") from error


async def _profile_table(
    adapter: DataSourceAdapter,
    table: CatalogTable,
    *,
    period_column: str,
    period_granularity: Literal["date", "year"],
    period_start: date,
    period_end: date,
    source_limiter: anyio.CapacityLimiter,
    global_limiter: anyio.CapacityLimiter | None,
) -> tuple[TableDataShape, int]:
    columns = {column.name: column for column in table.columns}
    if period_column not in columns:
        raise ReportingError(
            "report_period_column_missing",
            f"数据表 {table.qualified_name} 不包含期间字段 {period_column}。",
        )
    period_identifier = _identifier(period_column)
    if period_granularity == "year":
        period_filter = (
            f"{period_identifier} >= {period_start.year} AND "
            f"{period_identifier} <= {period_end.year}"
        )
    else:
        period_filter = (
            f"{period_identifier} >= '{period_start.isoformat()}' AND "
            f"{period_identifier} <= '{period_end.isoformat()}'"
        )
    qualified = f"{_identifier(table.database)}.{_identifier(table.name)}"
    base_aliases = (
        "total_row_count",
        "period_row_count",
        "outside_period_row_count",
        "period_null_count",
        "first_effective_date",
        "last_effective_date",
    )
    base_sql = (
        "SELECT COUNT(*) AS total_row_count, "
        f"COUNT_IF({period_filter}) AS period_row_count, "
        f"COUNT_IF({period_identifier} IS NOT NULL AND NOT ({period_filter})) "
        "AS outside_period_row_count, "
        f"COUNT_IF({period_identifier} IS NULL) AS period_null_count, "
        f"MIN(IF({period_filter}, {period_identifier}, NULL)) AS first_effective_date, "
        f"MAX(IF({period_filter}, {period_identifier}, NULL)) AS last_effective_date "
        f"FROM {qualified}"
    )
    base = _single_row(
        await _limited_query(adapter, base_sql, source_limiter, global_limiter), base_aliases
    )
    total_row_count = _integer(base[0])
    period_row_count = _integer(base[1])
    outside_period_row_count = _integer(base[2])
    period_null_count = _integer(base[3])
    if period_row_count + outside_period_row_count + period_null_count != total_row_count:
        raise ReportingError("report_data_shape_failed", "数据画像行数分布不一致。")
    first_effective_date = _text(base[4])
    last_effective_date = _text(base[5])
    if (
        period_row_count == 0
        and (first_effective_date is not None or last_effective_date is not None)
    ) or (period_row_count > 0 and (first_effective_date is None or last_effective_date is None)):
        raise ReportingError("report_data_shape_failed", "数据画像有效日期范围无效。")
    distinct_mode = (
        "exact"
        if total_row_count <= adapter.config.limits.exact_distinct_max_rows
        else "approximate"
    )

    raw_statistics: dict[int, dict[str, Any]] = {}
    batch_size = adapter.config.limits.statistics_column_batch_size
    batches: list[tuple[tuple[str, ...], str]] = []
    for batch_start in range(0, len(table.columns), batch_size):
        aggregates: list[str] = []
        aliases: list[str] = []
        for index in range(batch_start, min(batch_start + batch_size, len(table.columns))):
            column = table.columns[index]
            expressions = _column_aggregates(column, index, distinct_mode)
            aggregates.extend(expression for _, expression in expressions)
            aliases.extend(alias for alias, _ in expressions)
        sql = f"SELECT {', '.join(aggregates)} FROM {qualified} WHERE {period_filter}"
        batches.append((tuple(aliases), sql))

    batch_values: list[tuple[Any, ...] | None] = [None] * len(batches)
    coverage_result: QueryResult | None = None

    async def profile_batch(index: int, aliases: tuple[str, ...], sql: str) -> None:
        batch_values[index] = _single_row(
            await _limited_query(adapter, sql, source_limiter, global_limiter), aliases
        )

    if period_granularity == "year":
        coverage_sql = (
            f"SELECT CAST({period_identifier} AS CHAR) AS year, "
            f"COUNT(*) AS year_count FROM {qualified} WHERE {period_filter} "
            "GROUP BY year ORDER BY year"
        )
        coverage_columns = ("year", "year_count")
        expected_periods = tuple(
            str(year) for year in range(period_start.year, period_end.year + 1)
        )
    else:
        coverage_sql = (
            f"SELECT DATE_FORMAT({period_identifier}, '%Y-%m') AS month, "
            f"COUNT(*) AS month_count FROM {qualified} WHERE {period_filter} "
            "GROUP BY month ORDER BY month"
        )
        coverage_columns = ("month", "month_count")
        expected_periods = _expected_months(period_start, period_end)

    async def profile_coverage() -> None:
        nonlocal coverage_result
        coverage_result = await _limited_query(
            adapter, coverage_sql, source_limiter, global_limiter
        )

    async with anyio.create_task_group() as task_group:
        for index, (batch_aliases, sql) in enumerate(batches):
            task_group.start_soon(profile_batch, index, batch_aliases, sql)
        task_group.start_soon(profile_coverage)

    for (batch_aliases, _sql), values in zip(batches, batch_values, strict=True):
        if values is None:
            raise ReportingError("report_data_shape_failed", "字段统计结果不完整。")
        for alias, value in zip(batch_aliases, values, strict=True):
            index = int(alias.split("_", 1)[0][1:])
            raw_statistics.setdefault(index, {})[alias.split("_", 1)[1]] = value
    if coverage_result is None:
        raise ReportingError("report_data_shape_failed", "期间覆盖结果缺失。")
    query_count = 2 + len(batches)
    if coverage_result.columns != coverage_columns:
        raise ReportingError("report_data_shape_failed", "期间覆盖聚合字段无效。")
    period_coverage = _period_coverage(coverage_result, expected_periods, period_row_count)

    column_shapes = [
        _column_shape(
            column,
            raw_statistics[index],
            row_count=period_row_count,
            distinct_mode=distinct_mode,
        )
        for index, column in enumerate(table.columns)
    ]
    top_candidates = [
        index
        for index, shape in enumerate(column_shapes)
        if table.columns[index].name != period_column
        and 0 < shape.distinct_count <= adapter.config.limits.top_values_limit
    ][: adapter.config.limits.top_values_max_columns]
    top_results: list[tuple[TopValue, ...] | None] = [None] * len(top_candidates)

    async def profile_top(position: int, index: int) -> None:
        identifier = _identifier(table.columns[index].name)
        top_sql = (
            f"SELECT {identifier} AS value, COUNT(*) AS value_count FROM {qualified} "
            f"WHERE {period_filter} AND {identifier} IS NOT NULL GROUP BY {identifier} "
            f"ORDER BY value_count DESC, value LIMIT {adapter.config.limits.top_values_limit}"
        )
        top_results[position] = _top_values(
            await _limited_query(adapter, top_sql, source_limiter, global_limiter),
            period_row_count,
            limit=adapter.config.limits.top_values_limit,
        )

    async with anyio.create_task_group() as task_group:
        for position, index in enumerate(top_candidates):
            task_group.start_soon(profile_top, position, index)

    for index, top_values in zip(top_candidates, top_results, strict=True):
        if top_values is None:
            raise ReportingError("report_data_shape_failed", "Top-K 统计结果不完整。")
        column_shapes[index] = column_shapes[index].model_copy(update={"top_values": top_values})
        query_count += 1

    covered = set(period_coverage)
    missing_periods = tuple(item for item in expected_periods if item not in covered)
    return (
        TableDataShape(
            sourceId=table.source_id,
            database=table.database,
            table=table.name,
            totalRowCount=total_row_count,
            periodRowCount=period_row_count,
            outsidePeriodRowCount=outside_period_row_count,
            periodNullCount=period_null_count,
            firstEffectiveDate=first_effective_date,
            lastEffectiveDate=last_effective_date,
            columnCount=len(table.columns),
            periodGranularity=period_granularity,
            periodCoverage=period_coverage,
            missingPeriods=missing_periods,
            columns=tuple(column_shapes),
        ),
        query_count,
    )


async def _limited_query(
    adapter: DataSourceAdapter,
    sql: str,
    source_limiter: anyio.CapacityLimiter,
    global_limiter: anyio.CapacityLimiter | None,
) -> QueryResult:
    if global_limiter is None:
        async with source_limiter:
            return await adapter.query(sql)
    async with global_limiter:
        async with source_limiter:
            return await adapter.query(sql)


def _column_aggregates(
    column: CatalogColumn, index: int, distinct_mode: str
) -> tuple[tuple[str, str], ...]:
    identifier = _identifier(column.name)
    prefix = f"c{index}"
    distinct = (
        f"COUNT(DISTINCT {identifier})"
        if distinct_mode == "exact"
        else f"APPROX_COUNT_DISTINCT({identifier})"
    )
    values = [
        (f"{prefix}_nulls", f"COUNT_IF({identifier} IS NULL) AS {prefix}_nulls"),
        (f"{prefix}_distinct", f"{distinct} AS {prefix}_distinct"),
        (
            f"{prefix}_min",
            f"MIN({identifier}) AS {prefix}_min"
            if _BOUNDED_TYPES.match(column.data_type)
            else f"NULL AS {prefix}_min",
        ),
        (
            f"{prefix}_max",
            f"MAX({identifier}) AS {prefix}_max"
            if _BOUNDED_TYPES.match(column.data_type)
            else f"NULL AS {prefix}_max",
        ),
    ]
    if _NUMERIC_TYPES.match(column.data_type):
        values.extend(
            (
                (f"{prefix}_zeros", f"COUNT_IF({identifier} = 0) AS {prefix}_zeros"),
                (
                    f"{prefix}_negatives",
                    f"COUNT_IF({identifier} < 0) AS {prefix}_negatives",
                ),
                (f"{prefix}_average", f"AVG({identifier}) AS {prefix}_average"),
                (f"{prefix}_stddev", f"STDDEV_POP({identifier}) AS {prefix}_stddev"),
                (
                    f"{prefix}_p25",
                    f"PERCENTILE_APPROX({identifier}, 0.25) AS {prefix}_p25",
                ),
                (
                    f"{prefix}_p50",
                    f"PERCENTILE_APPROX({identifier}, 0.5) AS {prefix}_p50",
                ),
                (
                    f"{prefix}_p75",
                    f"PERCENTILE_APPROX({identifier}, 0.75) AS {prefix}_p75",
                ),
            )
        )
    return tuple(values)


def _column_shape(
    column: CatalogColumn,
    values: Mapping[str, Any],
    *,
    row_count: int,
    distinct_mode: str,
) -> ColumnShape:
    null_count = _integer(values["nulls"])
    distinct_count = _integer(values["distinct"])
    if null_count > row_count:
        raise ReportingError("report_data_shape_failed", "数据画像列空值数无效。")
    non_null_count = row_count - null_count
    if distinct_mode == "exact" and distinct_count > non_null_count:
        raise ReportingError("report_data_shape_failed", "数据画像列基数无效。")
    is_numeric = _NUMERIC_TYPES.match(column.data_type) is not None
    zero_count = _integer(values["zeros"]) if is_numeric else None
    negative_count = _integer(values["negatives"]) if is_numeric else None
    if is_numeric and (
        zero_count is None
        or negative_count is None
        or zero_count > non_null_count
        or negative_count > non_null_count
        or zero_count + negative_count > non_null_count
    ):
        raise ReportingError("report_data_shape_failed", "数据画像数值分布无效。")
    return ColumnShape(
        name=column.name,
        dataType=column.data_type,
        nullable=column.nullable,
        nullCount=null_count,
        nullRate=_ratio(null_count, row_count),
        distinctCount=distinct_count,
        distinctMode=distinct_mode,
        cardinalityRate=_ratio(distinct_count, row_count),
        unique=(distinct_count == non_null_count) if distinct_mode == "exact" else None,
        minimum=_scalar(values["min"]),
        maximum=_scalar(values["max"]),
        zeroCount=zero_count,
        negativeCount=negative_count,
        average=_scalar(values["average"]) if is_numeric else None,
        standardDeviation=_scalar(values["stddev"]) if is_numeric else None,
        p25=_scalar(values["p25"]) if is_numeric else None,
        p50=_scalar(values["p50"]) if is_numeric else None,
        p75=_scalar(values["p75"]) if is_numeric else None,
    )


def _single_row(result: QueryResult, aliases: tuple[str, ...]) -> tuple[Any, ...]:
    if result.columns != aliases or len(result.rows) != 1:
        raise ReportingError("report_data_shape_failed", "数据画像聚合结果无效。")
    values = tuple(result.rows[0])
    if len(values) != len(aliases):
        raise ReportingError("report_data_shape_failed", "数据画像聚合字段不完整。")
    return values


def _period_coverage(
    result: QueryResult,
    expected_periods: tuple[str, ...],
    period_row_count: int,
) -> tuple[str, ...]:
    expected = set(expected_periods)
    periods: list[str] = []
    counted_rows = 0
    for row in result.rows:
        if len(row) != 2 or row[0] is None:
            raise ReportingError("report_data_shape_failed", "月份覆盖聚合结果无效。")
        period = str(row[0])
        counted_rows += _integer(row[1])
        if period not in expected or period in periods:
            raise ReportingError("report_data_shape_failed", "期间覆盖聚合结果无效。")
        periods.append(period)
    if counted_rows != period_row_count:
        raise ReportingError("report_data_shape_failed", "期间覆盖行数与期间行数不一致。")
    return tuple(sorted(periods))


def _top_values(result: QueryResult, row_count: int, *, limit: int) -> tuple[TopValue, ...]:
    if result.columns != ("value", "value_count"):
        raise ReportingError("report_data_shape_failed", "Top-K 聚合字段无效。")
    if len(result.rows) > limit:
        raise ReportingError("report_data_shape_failed", "Top-K 聚合结果超限。")
    values: list[TopValue] = []
    seen: set[str | int | float] = set()
    for row in result.rows:
        if len(row) != 2 or row[0] is None:
            raise ReportingError("report_data_shape_failed", "Top-K 聚合结果无效。")
        count = _integer(row[1])
        if count == 0:
            raise ReportingError("report_data_shape_failed", "Top-K 聚合结果无效。")
        value = _scalar(row[0])
        if value is None:
            raise ReportingError("report_data_shape_failed", "Top-K 聚合结果无效。")
        if value in seen:
            raise ReportingError("report_data_shape_failed", "Top-K 聚合结果无效。")
        seen.add(value)
        values.append(TopValue(value=value, count=count, ratio=_ratio(count, row_count)))
    if sum(item.count for item in values) > row_count:
        raise ReportingError("report_data_shape_failed", "Top-K 聚合计数无效。")
    return tuple(values)


def _validate_catalog(adapter: DataSourceAdapter, catalog: tuple[CatalogTable, ...]) -> None:
    allowed = {table.lower() for table in adapter.config.tables}
    seen: set[str] = set()
    for table in catalog:
        qualified = table.qualified_name.lower()
        if (
            table.source_id != adapter.config.id
            or table.database.lower() != adapter.config.database.lower()
            or qualified not in allowed
            or qualified in seen
            or not table.columns
        ):
            raise ReportingError("report_catalog_drift", "实时 catalog 与数据源配置不一致。")
        seen.add(qualified)
    if seen != allowed:
        raise ReportingError("report_catalog_drift", "实时 catalog 缺少允许的数据表。")


def _catalog_scope(
    adapter: DataSourceAdapter,
    catalog: tuple[CatalogTable, ...],
    requested: tuple[CatalogTable, ...],
) -> tuple[CatalogTable, ...]:
    actual = {table.qualified_name.lower(): table for table in catalog}
    seen: set[str] = set()
    scoped: list[CatalogTable] = []
    for expected in requested:
        qualified = expected.qualified_name.lower()
        if (
            expected.source_id != adapter.config.id
            or expected.database.lower() != adapter.config.database.lower()
            or qualified in seen
            or not expected.columns
        ):
            raise ReportingError("report_catalog_drift", "结构快照范围无效。")
        current = actual.get(qualified)
        if current is None:
            raise ReportingError("report_catalog_drift", "实时 catalog 缺少结构快照数据表。")
        current_columns = {column.name.lower(): column for column in current.columns}
        selected: list[CatalogColumn] = []
        selected_names: set[str] = set()
        for expected_column in expected.columns:
            name = expected_column.name.lower()
            current_column = current_columns.get(name)
            if (
                current_column is None
                or name in selected_names
                or _normalized_type(current_column.data_type)
                != _normalized_type(expected_column.data_type)
                or current_column.nullable != expected_column.nullable
            ):
                raise ReportingError("report_catalog_drift", "实时 catalog 与结构快照不一致。")
            selected.append(current_column)
            selected_names.add(name)
        scoped.append(
            CatalogTable(
                source_id=current.source_id,
                database=current.database,
                name=current.name,
                columns=tuple(selected),
            )
        )
        seen.add(qualified)
    if not scoped:
        raise ReportingError("report_catalog_drift", "结构快照范围不能为空。")
    return tuple(scoped)


def _normalized_type(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _expected_months(period_start: date, period_end: date) -> tuple[str, ...]:
    year, month = period_start.year, period_start.month
    result: list[str] = []
    while (year, month) <= (period_end.year, period_end.month):
        result.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return tuple(result)


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", value):
        raise ReportingError("report_catalog_drift", "catalog 包含无效标识符。")
    return f"`{value}`"


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ReportingError("report_data_shape_failed", "数据画像计数无效。")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ReportingError("report_data_shape_failed", "数据画像计数无效。") from error
    if result < 0:
        raise ReportingError("report_data_shape_failed", "数据画像计数无效。")
    return result


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _scalar(value: Any) -> str | int | float | None:
    if value is None or isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return value
    return str(value)
