from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace
from typing import Any

import anyio
import pytest

from agentos_dev.coding.reporting.data_source import (
    CatalogColumn,
    CatalogTable,
    QueryLimits,
    QueryResult,
    collect_data_shape,
    validate_starrocks_read_only_sql,
)
from agentos_dev.coding.reporting.models import ReportingError


class FakeAdapter:
    config: Any

    def __init__(
        self,
        *,
        fail_table: str | None = None,
        exact_distinct_max_rows: int = 5,
        statistics_column_batch_size: int = 2,
        month_counts: tuple[int, int] = (4, 6),
        period_row_count: int = 10,
        base_overrides: dict[str, object] | None = None,
        catalog_source_id: str = "operations",
    ):
        self.config = SimpleNamespace(
            id="operations",
            database="reporting",
            tables=("reporting.income", "reporting.budget"),
            limits=QueryLimits(
                statement_timeout_seconds=30,
                max_rows=1_000_000,
                max_bytes=1024 * 1024,
                exact_distinct_max_rows=exact_distinct_max_rows,
                statistics_column_batch_size=statistics_column_batch_size,
                top_values_max_columns=1,
                top_values_limit=5,
                profile_concurrency=2,
                query_concurrency=2,
            ),
        )
        self.fail_table = fail_table
        self.month_counts = month_counts
        self.period_row_count = period_row_count
        self.base_overrides = base_overrides or {}
        self.catalog_source_id = catalog_source_id
        self.queries: list[str] = []

    async def verify_read_only(self) -> None:
        return None

    async def catalog(self) -> tuple[CatalogTable, ...]:
        columns = (
            CatalogColumn("month", "DATE", False),
            CatalogColumn("amount", "DECIMAL(18,2)", True),
            CatalogColumn("department", "VARCHAR(100)", True),
        )
        return (
            CatalogTable(self.catalog_source_id, "reporting", "income", columns),
            CatalogTable(self.catalog_source_id, "reporting", "budget", columns),
        )

    async def query(self, sql: str) -> QueryResult:
        self.queries.append(sql)
        assert "SELECT *" not in sql.upper()
        validate_starrocks_read_only_sql(
            sql,
            database="reporting",
            allowed_tables=("reporting.income", "reporting.budget"),
        )
        if self.fail_table and f"`{self.fail_table}`" in sql:
            raise ReportingError("source_query_failed", "失败")
        if "AS month_count" in sql:
            if self.period_row_count == 0:
                return QueryResult(("month", "month_count"), (), 2)
            return QueryResult(
                ("month", "month_count"),
                (
                    ("2025-01", self.month_counts[0]),
                    ("2025-02", self.month_counts[1]),
                ),
                20,
            )
        if "AS value_count" in sql:
            assert "GROUP BY" in sql and "LIMIT 5" in sql
            return QueryResult(
                ("value", "value_count"), (("内科", 5), ("外科", 3), ("其他", 2)), 40
            )
        aliases = tuple(re.findall(r"\bAS\s+([a-z0-9_]+)", sql, re.IGNORECASE))
        if self.period_row_count == 0:
            zero_values: dict[str, object] = {
                alias: None
                if alias.endswith(("_min", "_max", "_average", "_stddev", "_p25", "_p50", "_p75"))
                or alias in {"first_effective_date", "last_effective_date"}
                else 0
                for alias in aliases
            }
            zero_values.update(self.base_overrides)
            return QueryResult(aliases, (tuple(zero_values[alias] for alias in aliases),), 20)
        values: dict[str, object] = {
            "total_row_count": 14,
            "period_row_count": 10,
            "outside_period_row_count": 3,
            "period_null_count": 1,
            "first_effective_date": "2025-01-01",
            "last_effective_date": "2025-02-28",
            "c0_nulls": 0,
            "c0_distinct": 2,
            "c0_min": "2025-01-01",
            "c0_max": "2025-02-28",
            "c1_nulls": 1,
            "c1_distinct": 9,
            "c1_min": 0,
            "c1_max": 900,
            "c1_zeros": 1,
            "c1_negatives": 2,
            "c1_average": 500,
            "c1_stddev": 10,
            "c1_p25": 250,
            "c1_p50": 500,
            "c1_p75": 750,
            "c2_nulls": 2,
            "c2_distinct": 3,
            "c2_min": None,
            "c2_max": None,
        }
        values.update(self.base_overrides)
        return QueryResult(aliases, (tuple(values[alias] for alias in aliases),), 100)

    async def aclose(self) -> None:
        return None


class ConcurrentFakeAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.active_queries = 0
        self.max_active_queries = 0

    async def query(self, sql: str) -> QueryResult:
        self.active_queries += 1
        self.max_active_queries = max(self.max_active_queries, self.active_queries)
        try:
            await anyio.sleep(0.01)
            return await super().query(sql)
        finally:
            self.active_queries -= 1


@pytest.mark.anyio
async def test_datashape覆盖完整质量分布血缘且不读取样本行():
    adapter = FakeAdapter()

    shape = await collect_data_shape(
        adapter,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_columns={
            "reporting.income": "month",
            "reporting.budget": "month",
        },
        metadata_revision="model-r7",
        schema_hash="a" * 64,
    )

    table = shape.tables[0]
    amount = table.columns[1]
    department = table.columns[2]
    assert shape.source_id == "operations"
    assert shape.metadata_revision == "model-r7"
    assert shape.schema_hash == "a" * 64
    assert shape.statistics_version == "1"
    assert shape.query_count == 10
    assert table.total_row_count == 14
    assert table.period_row_count == 10
    assert table.outside_period_row_count == 3
    assert table.period_null_count == 1
    assert table.first_effective_date == "2025-01-01"
    assert table.last_effective_date == "2025-02-28"
    assert table.month_coverage == ("2025-01", "2025-02")
    assert table.missing_months == tuple(f"2025-{month:02d}" for month in range(3, 13))
    assert amount.null_rate == 0.1
    assert amount.cardinality_rate == 0.9
    assert amount.unique is None
    assert amount.zero_count == 1
    assert amount.negative_count == 2
    assert amount.average == 500
    assert amount.standard_deviation == 10
    assert (amount.p25, amount.p50, amount.p75) == (250, 500, 750)
    assert amount.distinct_mode == "approximate"
    assert department.top_values[0].value == "内科"
    assert department.top_values[0].count == 5
    assert department.top_values[0].ratio == 0.5
    assert all("2025-01-01" in sql and "2025-12-31" in sql for sql in adapter.queries)
    assert sum("APPROX_COUNT_DISTINCT" in sql for sql in adapter.queries) == 4
    assert sum("COUNT(DISTINCT" in sql for sql in adapter.queries) == 0


@pytest.mark.anyio
async def test_datashape小表使用精确distinct且宽表按配置分批():
    adapter = FakeAdapter(exact_distinct_max_rows=20, statistics_column_batch_size=1)

    shape = await collect_data_shape(
        adapter,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_columns={"reporting.income": "month", "reporting.budget": "month"},
        metadata_revision="model-r7",
        schema_hash="a" * 64,
    )

    assert all(
        column.distinct_mode == "exact" for table in shape.tables for column in table.columns
    )
    assert shape.query_count == 12
    assert sum("COUNT(DISTINCT" in sql for sql in adapter.queries) == 6
    assert all(sql.count("_distinct") <= 1 for sql in adapter.queries)


@pytest.mark.anyio
async def test_datashape按配置有界并行且结果顺序稳定():
    adapter = ConcurrentFakeAdapter()

    shape = await collect_data_shape(
        adapter,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_columns={"reporting.income": "month", "reporting.budget": "month"},
        metadata_revision="model-r7",
        schema_hash="a" * 64,
    )

    assert adapter.max_active_queries == 2
    assert [table.table for table in shape.tables] == ["income", "budget"]


@pytest.mark.anyio
async def test_datashape任一表失败即终止且返回稳定错误():
    adapter = FakeAdapter(fail_table="budget")

    with pytest.raises(ReportingError) as captured:
        await collect_data_shape(
            adapter,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"reporting.income": "month", "reporting.budget": "month"},
            metadata_revision="model-r7",
            schema_hash="a" * 64,
        )

    assert captured.value.code == "report_data_shape_failed"
    assert sum("`budget`" in sql for sql in adapter.queries) == 1


@pytest.mark.anyio
async def test_datashape月份聚合与期间行数不一致时失败关闭():
    adapter = FakeAdapter(month_counts=(4, 7))

    with pytest.raises(ReportingError) as captured:
        await collect_data_shape(
            adapter,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"reporting.income": "month", "reporting.budget": "month"},
            metadata_revision="model-r7",
            schema_hash="a" * 64,
        )

    assert captured.value.code == "report_data_shape_failed"


@pytest.mark.anyio
async def test_datashape期间零行仍返回完整列画像且不生成top查询():
    adapter = FakeAdapter(
        period_row_count=0,
        base_overrides={
            "total_row_count": 14,
            "outside_period_row_count": 13,
            "period_null_count": 1,
        },
    )

    shape = await collect_data_shape(
        adapter,
        period_start=date(2025, 1, 1),
        period_end=date(2025, 12, 31),
        period_columns={"reporting.income": "month", "reporting.budget": "month"},
        metadata_revision="model-r7",
        schema_hash="a" * 64,
    )

    table = shape.tables[0]
    assert table.total_row_count == 14
    assert table.period_row_count == 0
    assert table.outside_period_row_count == 13
    assert table.period_null_count == 1
    assert table.first_effective_date is None
    assert table.last_effective_date is None
    assert table.month_coverage == ()
    assert len(table.columns) == 3
    assert all(column.null_rate == 0 for column in table.columns)
    assert all(column.distinct_count == 0 for column in table.columns)
    assert not any("AS value_count" in sql for sql in adapter.queries)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "overrides",
    (
        {"outside_period_row_count": 4},
        {"first_effective_date": None},
        {"c1_nulls": 11},
    ),
)
async def test_datashape拒绝不自洽的聚合结果(overrides: dict[str, object]):
    adapter = FakeAdapter(base_overrides=overrides)

    with pytest.raises(ReportingError) as captured:
        await collect_data_shape(
            adapter,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"reporting.income": "month", "reporting.budget": "month"},
            metadata_revision="model-r7",
            schema_hash="a" * 64,
        )

    assert captured.value.code == "report_data_shape_failed"


@pytest.mark.anyio
async def test_datashape拒绝catalog返回其他数据源():
    adapter = FakeAdapter(catalog_source_id="other-source")

    with pytest.raises(ReportingError) as captured:
        await collect_data_shape(
            adapter,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"reporting.income": "month", "reporting.budget": "month"},
            metadata_revision="model-r7",
            schema_hash="a" * 64,
        )

    assert captured.value.code == "report_data_shape_failed"
    assert adapter.queries == []


@pytest.mark.anyio
async def test_datashape期间列必须显式配置且存在于catalog():
    adapter = FakeAdapter()
    with pytest.raises(ReportingError) as missing:
        await collect_data_shape(
            adapter,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"reporting.income": "month"},
            metadata_revision="model-r7",
            schema_hash="a" * 64,
        )
    assert missing.value.code == "report_period_column_missing"

    with pytest.raises(ReportingError) as unknown:
        await collect_data_shape(
            adapter,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"reporting.income": "unknown", "reporting.budget": "month"},
            metadata_revision="model-r7",
            schema_hash="a" * 64,
        )
    assert unknown.value.code == "report_period_column_missing"
