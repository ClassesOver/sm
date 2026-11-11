"""参数执行通过真实SQLAlchemy/SQLite驱动验证；StarRocks方言另行集成验收。"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from smart_reporting.reporting.data_source.starrocks import StarRocksDataSourceAdapter
from smart_reporting.reporting.models import ReportingError


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def adapter():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as connection:
        connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS test")
        connection.exec_driver_sql("CREATE TABLE test.budget(project_id TEXT, amount INTEGER)")
        connection.exec_driver_sql("INSERT INTO test.budget VALUES ('A',100),('B',200)")
    events = []
    @event.listens_for(engine, "before_cursor_execute")
    def record(_connection, _cursor, statement, parameters, _context, _many):
        events.append((statement, parameters))
    class Connection:
        def __enter__(self):
            self.connection = engine.connect()
            return self
        def __exit__(self, *_args):
            self.connection.close()
        def execute(self, statement, parameters=None):
            if str(statement).startswith("SET query_timeout"):
                return None
            return self.connection.execute(statement, parameters)
        def execution_options(self, **kwargs):
            self.connection = self.connection.execution_options(**kwargs)
            return self
        def exec_driver_sql(self, statement):
            return self.connection.exec_driver_sql(statement)
    source = object.__new__(StarRocksDataSourceAdapter)
    source.config = SimpleNamespace(database="test", statement_timeout_seconds=30, max_rows=10, max_bytes=10000)
    source.allowed_tables = ("test.budget",)
    source._engine = SimpleNamespace(connect=Connection)
    try:
        yield source, events
    finally:
        engine.dispose()


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["query_bound", "materialize_bound"])
async def test_bound_query_passes_values_to_driver_without_sql_interpolation(adapter, method):
    source, events = adapter
    attack = "A' OR 1=1 -- 100% :pending"
    sql = "SELECT SUM(amount) AS value FROM test.budget WHERE project_id = :p0"
    result = await getattr(source, method)(sql, {"p0": attack})
    assert len(events) == 1
    assert attack not in events[0][0] and events[0][1] == (attack,)
    if method == "query_bound":
        assert result.rows == ((None,),)
    else:
        assert result.content == b'value\r\n\r\n'


@pytest.mark.anyio
async def test_bound_query_checks_scope_and_parameter_completeness_before_driver(adapter):
    source, events = adapter
    with pytest.raises(ReportingError) as denied:
        await source.query_bound("SELECT * FROM other.secret WHERE id = :p0", {"p0": 1})
    assert denied.value.code == "sql_table_denied"
    for parameters in ({}, {"p0": 1, "extra": 2}, {"p0": {"sql": "SELECT 1"}}):
        with pytest.raises(ReportingError) as invalid:
            await source.query_bound("SELECT amount FROM test.budget WHERE project_id = :p0", parameters)
        assert invalid.value.code == "query_parameters_invalid"
    assert events == []
