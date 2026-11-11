"""已发布目录是 AI Schema 和 SQL 执行权限的共同上界。"""
from __future__ import annotations

import pytest

from smart_reporting.reporting.contract import ReportRequestEnvelope
from smart_reporting.reporting.data_source.starrocks import (
    StarRocksDataSourceAdapter,
    parse_starrocks_source,
)
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.query_pipeline import resolve_schema_snapshot
from smart_reporting.reporting.workflow.runtime.planning import _schema_scope_tables
from smart_reporting.tests.management_fixtures import business_metadata


def _source():
    return parse_starrocks_source(
        {"id": "operations", "type": "starrocks", "name": "经营", "dsnEnv": "TEST_DSN"},
        {"TEST_DSN": "starrocks://reader:secret@localhost:9030/warehouse"},
    )


@pytest.mark.parametrize("ddl", [
    "CREATE TABLE warehouse.secret_salary (amount DECIMAL(18,2) NOT NULL)",
    "CREATE TABLE warehouse.orders (amount DECIMAL(18,2) NOT NULL); "
    "CREATE TABLE warehouse.secret_salary (amount DECIMAL(18,2) NOT NULL)",
    "CREATE TABLE other.orders (amount DECIMAL(18,2) NOT NULL)",
])
def test_request_ddl_cannot_expand_frozen_ai_catalog(ddl):
    source = _source()
    metadata = business_metadata()
    envelope = ReportRequestEnvelope.model_validate({
        "reportGoal": "请读取 secret_salary", "period": {"start": "2025-01-01", "end": "2025-12-31"},
        "schemaInput": {"ddl": ddl},
    })
    assert _schema_scope_tables(envelope, source=source, metadata=metadata) == metadata.tables
    with pytest.raises(ReportingError) as caught:
        resolve_schema_snapshot(envelope, source=source, metadata=metadata,
                                catalog=metadata.tables, preserve_metadata=True)
    assert caught.value.code == "report_schema_conflict"


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["query", "materialize"])
@pytest.mark.parametrize("sql", [
    "SELECT * FROM warehouse.secret_salary",
    "SELECT * FROM warehouse.orders o JOIN warehouse.secret_salary s ON 1=1",
    "SELECT * FROM warehouse.orders WHERE amount IN (SELECT amount FROM warehouse.secret_salary)",
    "WITH hidden AS (SELECT * FROM warehouse.secret_salary) SELECT * FROM hidden",
    "WITH secret_salary AS (SELECT * FROM secret_salary) SELECT * FROM secret_salary",
    "SELECT * FROM other.orders",
    "SELECT * FROM external.warehouse.orders",
    # 发布视图允许查询视图本身，不授予视图的底层表。
    "SELECT * FROM warehouse.orders_base",
])
async def test_frozen_adapter_rejects_unpublished_tables_before_database(method, sql, monkeypatch):
    adapter = StarRocksDataSourceAdapter(_source(), allowed_tables=("warehouse.orders",))

    def forbidden_database_call(*args, **kwargs):
        pytest.fail("越权 SQL 不应到达数据库")

    monkeypatch.setattr(adapter, "_query", forbidden_database_call)
    monkeypatch.setattr(adapter, "_materialize", forbidden_database_call)
    try:
        with pytest.raises(ReportingError) as caught:
            await getattr(adapter, method)(sql)
        assert caught.value.code == "sql_table_denied"
    finally:
        await adapter.aclose()


def test_execution_adapter_uses_same_frozen_tables_as_ai_schema():
    from smart_reporting.reporting.data_source.sql_validation import (
        validate_starrocks_read_only_sql,
    )
    from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime

    source = _source()
    metadata = business_metadata()
    envelope = ReportRequestEnvelope.model_validate({
        "reportGoal": "核对订单", "period": {"start": "2025-01-01", "end": "2025-12-31"},
    })
    snapshot = resolve_schema_snapshot(envelope, source=source, metadata=metadata,
                                       catalog=metadata.tables, preserve_metadata=True)
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime._snapshots = lambda _context: (snapshot,)
    adapter = runtime._adapter(source, None)
    assert adapter.allowed_tables == ("warehouse.orders",)
    assert snapshot.tables == metadata.tables
    for sql in (
        "SELECT * FROM warehouse.orders",
        "WITH published AS (SELECT * FROM warehouse.orders) SELECT * FROM published",
    ):
        assert validate_starrocks_read_only_sql(
            sql, database=source.database, allowed_tables=adapter.allowed_tables
        ) == sql
