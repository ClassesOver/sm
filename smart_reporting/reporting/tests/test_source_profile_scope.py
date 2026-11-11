from datetime import date
from types import SimpleNamespace

import duckdb
import pytest
import sqlglot

from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable, QueryResult
from smart_reporting.reporting.data_source.profiling import collect_data_shape
from smart_reporting.reporting.semantics.models import StatisticalPolicy
from smart_reporting.reporting.tests.test_semantic_models import policy_payload


@pytest.mark.anyio
@pytest.mark.parametrize("company", ["100", "O'Reilly\\branch"])
@pytest.mark.parametrize("company_column", ["company_id", "Company_ID"])
async def test_profile_statistics_and_top_values_exclude_other_organizations(
    company, company_column
):
    """执行真实聚合 SQL；组织内全期间计数不能误变成期间内计数。"""
    table = CatalogTable(
        source_id="source",
        database="warehouse",
        name="orders",
        columns=tuple(
            CatalogColumn(name, "VARCHAR", True)
            for name in (company_column, "report_year", "label")
        ),
    )
    connection = duckdb.connect()
    connection.execute("CREATE SCHEMA warehouse")
    connection.execute(
        "CREATE TABLE warehouse.orders(company_id VARCHAR, report_year VARCHAR, label VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO warehouse.orders VALUES (?, ?, ?)",
        [
            (company, "2025", "local"),
            (company, "2024", "prior"),
            (company, None, "undated"),
            ("other", "2025", "secret"),
            ("other", "2025", "secret"),
            ("other", "2024", "foreign-prior"),
        ],
    )

    class Adapter:
        allowed_tables = ("warehouse.orders",)
        config = SimpleNamespace(
            id="source",
            database="warehouse",
            limits=SimpleNamespace(
                profile_concurrency=1,
                exact_distinct_max_rows=100,
                statistics_column_batch_size=2,
                top_values_limit=10,
                top_values_max_columns=3,
            ),
        )

        async def catalog(self):
            return (table,)

        async def query(self, sql):
            cursor = connection.execute(sqlglot.transpile(sql, read="starrocks", write="duckdb")[0])
            return QueryResult(tuple(item[0] for item in cursor.description), cursor.fetchall(), 0)

        async def query_bound(self, sql, parameters):
            cursor = connection.execute(sqlglot.transpile(sql, read="starrocks", write="duckdb")[0], parameters)
            return QueryResult(tuple(item[0] for item in cursor.description), cursor.fetchall(), 0)

    try:
        shape = await collect_data_shape(
            Adapter(),
            catalog_scope=(table,),
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            period_columns={"warehouse.orders": "report_year"},
            period_granularities={"warehouse.orders": "year"},
            metadata_revision="1",
            schema_hash="a" * 64,
            policy=StatisticalPolicy.model_validate(policy_payload(filters=[{
                "fieldRef": f"source.warehouse.orders.{company_column}",
                "operator": "eq", "values": [company]}])),
            policy_catalog=(table,),
        )
        result = shape.tables[0]
        assert (
            result.total_row_count,
            result.period_row_count,
            result.outside_period_row_count,
            result.period_null_count,
        ) == (3, 1, 1, 1)
        assert result.period_coverage == ("2025",)
        label = next(column for column in result.columns if column.name == "label")
        assert label.distinct_count == 1
        assert [(value.value, value.count) for value in label.top_values] == [("local", 1)]
    finally:
        connection.close()


def test_managed_profile_keeps_published_catalog_on_descriptive_drift():
    from dataclasses import replace

    from smart_reporting.reporting.data_source.profiling import _catalog_scope

    published = CatalogTable(
        source_id="source",
        database="warehouse",
        name="orders",
        columns=(CatalogColumn("label", "VARCHAR", False, "发布说明"),),
        description="发布表",
    )
    current = replace(
        published,
        description="新表说明",
        columns=(
            replace(
                published.columns[0],
                description="新字段说明",
                nullable=True,
                data_type="VARCHAR(128)",
            ),
        ),
    )
    adapter = SimpleNamespace(config=SimpleNamespace(id="source", database="warehouse"))
    assert _catalog_scope(adapter, (current,), (published,), preserve_metadata=True) == (published,)
