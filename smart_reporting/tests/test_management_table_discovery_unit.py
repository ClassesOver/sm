"""目录枚举直接读取 information_schema，避免驱动静默丢失视图。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import Integer, Numeric, create_engine, event
from sqlalchemy.pool import StaticPool

from smart_reporting.management import table_access


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def discovery_io(monkeypatch):
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    with engine.begin() as conn:
        conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS information_schema")
        conn.exec_driver_sql(
            "CREATE TABLE information_schema.tables "
            "(TABLE_SCHEMA TEXT, TABLE_NAME TEXT, TABLE_TYPE TEXT, TABLE_COMMENT TEXT)"
        )
        conn.exec_driver_sql(
            "INSERT INTO information_schema.tables VALUES "
            "('warehouse', 'orders', 'BASE TABLE', '真实订单'), "
            "('warehouse', 'orders_view', 'VIEW', '真实视图'), "
            "('other', 'secret', 'BASE TABLE', '其他库')"
        )
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    adapter = SimpleNamespace(_engine=engine, closed=False)

    async def close():
        adapter.closed = True

    adapter.aclose = close
    monkeypatch.setattr(table_access, "StarRocksDataSourceAdapter", lambda config: adapter)
    inspector = SimpleNamespace(
        get_table_names=lambda **kwargs: ["orders"],
        # 模拟真实 StarRocks 驱动吞掉视图读取异常。
        get_view_names=lambda **kwargs: [],
        get_columns=lambda name, **kwargs: [
            {"name": "amount", "type": Numeric(18, 2), "nullable": False, "comment": "收入金额"},
            {"name": "count", "type": Integer(), "nullable": True},
        ],
        get_table_comment=lambda *args, **kwargs: {"text": "驱动旧说明"},
    )
    monkeypatch.setattr(table_access, "inspect", lambda unused: inspector)
    service = object.__new__(table_access.TableAccessService)
    config = SimpleNamespace(id="operations", database="warehouse")
    yield service, config, adapter, engine, statements
    engine.dispose()


@pytest.mark.anyio
async def test_discovery_keeps_real_views_and_metadata_without_reading_business_rows(discovery_io):
    service, config, adapter, _, statements = discovery_io
    tables = await service._discover(config)
    assert [(t["name"], t["type"], t["description"]) for t in tables] == [
        ("orders", "table", "真实订单"),
        ("orders_view", "view", "真实视图"),
    ]
    assert tables[1]["columns"] == [
        {
            "name": "amount",
            "dataType": "NUMERIC(18, 2)",
            "nullable": False,
            "description": "收入金额",
        },
        {"name": "count", "dataType": "INTEGER", "nullable": True, "description": ""},
    ]
    assert adapter.closed
    assert len(statements) == 1
    sql, parameters = statements[0]
    assert "information_schema.tables" in sql.lower()
    assert "warehouse" not in sql
    assert parameters == ("warehouse",)


@pytest.mark.anyio
async def test_discovery_catalog_failure_does_not_return_success(discovery_io):
    from sqlalchemy.exc import OperationalError

    service, config, adapter, engine, _ = discovery_io
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE information_schema.tables")
    with pytest.raises(OperationalError):
        await service._discover(config)
    assert adapter.closed


@pytest.mark.anyio
async def test_selected_summaries_ignore_search_kind_and_pagination():
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def transaction():
        yield None

    service = object.__new__(table_access.TableAccessService)
    service.repository = SimpleNamespace(transaction=transaction)

    async def draft(*args):
        return None, "scope", {}

    async def snapshot(*args):
        return {
            "business_metadata": None,
            "tables": [
                {
                    "sourceId": "operations",
                    "database": "warehouse",
                    "name": "orders_view",
                    "type": "view",
                    "description": "订单视图",
                    "columns": [
                        {
                            "name": "amount",
                            "dataType": "DECIMAL(18,2)",
                            "nullable": False,
                            "description": "金额",
                        }
                    ],
                },
                {
                    "sourceId": "operations",
                    "database": "warehouse",
                    "name": "orders",
                    "type": "table",
                    "description": "订单",
                    "columns": [],
                },
            ],
        }

    async def access(*args):
        return {
            "draftTables": [
                {"database": "warehouse", "name": "orders_view"},
                {"database": "warehouse", "name": "missing"},
            ],
            "publishedTables": [{"database": "warehouse", "name": "orders_view"}],
        }

    service._draft, service._snapshot, service._access = draft, snapshot, access
    result = await service.tables(
        "token", None, "operations", "discovery", q="不存在", kind="table", offset=20, limit=1
    )
    assert result["items"] == []
    assert result["selectedItems"] == [
        {
            "database": "warehouse",
            "name": "orders_view",
            "type": "view",
            "description": "订单视图",
            "selected": True,
            "published": True,
        }
    ]
    assert result["missingTables"] == [{"database": "warehouse", "name": "missing"}]
