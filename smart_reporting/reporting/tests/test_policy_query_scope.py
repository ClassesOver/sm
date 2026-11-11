"""探索SQL在真实执行前套用登记范围，CTE及子查询不能脱离范围。"""

from types import SimpleNamespace

import duckdb
import pytest
import sqlglot

from smart_reporting.reporting.data_source.materialization import CsvMaterializer
from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable, QueryResult
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.semantics.models import StatisticalPolicy
from smart_reporting.reporting.tests.test_semantic_models import policy_payload


@pytest.fixture
def query_database():
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE TABLE test.budget(project_id VARCHAR, amount INTEGER)')
        connection.execute("INSERT INTO test.budget VALUES ('A',10),('A',20),('B',900)")
        connection.execute('CREATE TABLE test.projects(project_id VARCHAR, department VARCHAR)')
        connection.execute("INSERT INTO test.projects VALUES ('A','X'),('B','Y')")
        catalog = (CatalogTable('warehouse', 'test', 'budget', (
            CatalogColumn('project_id', 'VARCHAR', False), CatalogColumn('amount', 'INT', False))),
            CatalogTable('warehouse', 'test', 'projects', (
                CatalogColumn('project_id', 'VARCHAR', False), CatalogColumn('department', 'VARCHAR', False))))

        class Adapter:
            allowed_tables = ('test.budget', 'test.projects')
            config = SimpleNamespace(database='test')
            executed = []

            async def query(self, sql):
                self.executed.append((sql, {}))
                cursor = connection.execute(sqlglot.transpile(sql, read='starrocks', write='duckdb')[0])
                return QueryResult(tuple(item[0] for item in cursor.description), cursor.fetchall(), 0)

            async def materialize_bound(self, sql, parameters, *, max_bytes=None):
                self.executed.append((sql, parameters))
                cursor = connection.execute(sqlglot.transpile(sql, read='starrocks', write='duckdb')[0], parameters)
                writer = CsvMaterializer(tuple(item[0] for item in cursor.description), max_bytes=max_bytes)
                writer.append(tuple(cursor.fetchall()))
                return writer.finish()

            async def aclose(self):
                pass

        yield connection, Adapter(), catalog


def governed(adapter, catalog, **changes):
    from smart_reporting.reporting.data_source.policy_scope import PolicyQueryAdapter
    policy = StatisticalPolicy.model_validate(policy_payload(filters=[
        {'fieldRef': 'warehouse.test.budget.project_id', 'operator': 'eq', 'values': ['A']}], **changes))
    return PolicyQueryAdapter(adapter, policy=policy, catalog=catalog)


@pytest.mark.anyio
@pytest.mark.parametrize('sql', [
    'SELECT SUM(amount) AS total FROM test.budget',
    'SELECT SUM(b.amount) AS total FROM test.budget b',
    'SELECT SUM(test.budget.amount) AS total FROM test.budget',
    'WITH b AS (SELECT amount FROM test.budget) SELECT SUM(amount) AS total FROM b',
    'SELECT SUM(amount) AS total FROM (SELECT * FROM test.budget) b',
    'SELECT SUM(b.amount) AS total FROM test.budget b JOIN test.budget c ON b.project_id=c.project_id',
])
async def test_every_physical_reference_is_scoped_before_materialization(query_database, sql):
    _, adapter, catalog = query_database
    result = await governed(adapter, catalog).materialize(sql, max_bytes=4096)
    expected = b'60' if ' JOIN ' in sql else b'30'
    assert result.content.splitlines()[1] == expected
    assert len(adapter.executed) == 1
    sent_sql, parameters = adapter.executed[0]
    assert parameters and all(value == 'A' for value in parameters.values())
    assert "'A'" not in sent_sql


@pytest.mark.anyio
@pytest.mark.parametrize('sql', [
    'SELECT * FROM test.hidden', 'SELECT * FROM other.budget',
    'WITH hidden AS (SELECT * FROM hidden) SELECT * FROM hidden',
    'SELECT * FROM test.budget UNION ALL SELECT * FROM test.hidden',
    'DELETE FROM test.budget',
])
async def test_unapproved_references_never_reach_database(query_database, sql):
    _, adapter, catalog = query_database
    with pytest.raises(ReportingError):
        await governed(adapter, catalog).materialize(sql, max_bytes=4096)
    assert adapter.executed == []


@pytest.mark.anyio
async def test_dimension_filter_checks_uniqueness_before_and_after_materialization(query_database):
    connection, adapter, catalog = query_database
    from smart_reporting.reporting.data_source.policy_scope import PolicyQueryAdapter
    policy = StatisticalPolicy.model_validate(policy_payload(filters=[
        {'fieldRef': 'warehouse.test.projects.department', 'operator': 'eq', 'values': ['X']}],
        joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
            'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}]))
    scoped = PolicyQueryAdapter(adapter, policy=policy, catalog=catalog)
    result = await scoped.materialize('SELECT SUM(amount) AS total FROM test.budget', max_bytes=4096)
    assert result.content.splitlines()[1] == b'30'
    assert len(adapter.executed) == 3
    connection.execute("INSERT INTO test.projects VALUES ('A','X')")
    adapter.executed.clear()
    with pytest.raises(ReportingError, match='join_fanout'):
        await scoped.materialize('SELECT SUM(amount) AS total FROM test.budget', max_bytes=4096)
    assert len(adapter.executed) == 1


@pytest.mark.anyio
async def test_duplicate_dimension_introduced_during_query_discards_materialization(query_database):
    connection, adapter, catalog = query_database
    from smart_reporting.reporting.data_source.policy_scope import PolicyQueryAdapter
    policy = StatisticalPolicy.model_validate(policy_payload(filters=[
        {'fieldRef': 'warehouse.test.projects.department', 'operator': 'eq', 'values': ['X']}],
        joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
            'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}]))
    original = adapter.materialize_bound

    async def materialize(sql, parameters, *, max_bytes=None):
        result = await original(sql, parameters, max_bytes=max_bytes)
        connection.execute("INSERT INTO test.projects VALUES ('A','X')")
        return result

    adapter.materialize_bound = materialize
    with pytest.raises(ReportingError, match='join_fanout'):
        await PolicyQueryAdapter(adapter, policy=policy, catalog=catalog).materialize(
            'SELECT SUM(amount) AS total FROM test.budget', max_bytes=4096)
    assert len(adapter.executed) == 3


@pytest.mark.anyio
async def test_unregistered_parameter_cannot_reuse_server_filter_binding(query_database):
    _, adapter, catalog = query_database
    with pytest.raises(ReportingError):
        await governed(adapter, catalog).materialize(
            'SELECT SUM(amount) AS total FROM test.budget WHERE project_id=:p0', max_bytes=4096)
    assert adapter.executed == []
