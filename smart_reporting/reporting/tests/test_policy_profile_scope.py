"""真实聚合验证画像采用新口径，范围条件不能丢失或放大事实行。"""

from datetime import date
from types import SimpleNamespace

import duckdb
import pytest
import sqlglot

from smart_reporting.reporting.data_source.models import CatalogColumn, CatalogTable, QueryResult
from smart_reporting.reporting.data_source.profiling import collect_data_shape
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.semantics.models import StatisticalPolicy
from smart_reporting.reporting.tests.test_semantic_models import policy_payload


@pytest.fixture
def profile_database():
    with duckdb.connect() as connection:
        connection.execute('CREATE SCHEMA test')
        connection.execute('CREATE MACRO percentile_approx(value, fraction) AS quantile_cont(value, fraction)')
        connection.execute('CREATE TABLE test.budget(project_id VARCHAR, amount INTEGER, period DATE, label VARCHAR)')
        connection.execute("INSERT INTO test.budget VALUES ('A',10,'2026-01-01','local'),('A',20,'2025-12-01','prior'),('A',30,NULL,'undated'),('B',90,'2026-01-01','foreign'),('C',1,'2026-01-01','small')")
        connection.execute('CREATE TABLE test.projects(project_id VARCHAR, department VARCHAR)')
        connection.execute("INSERT INTO test.projects VALUES ('A','X'),('B','Y'),('C','X')")
        tables = (CatalogTable('warehouse', 'test', 'budget', tuple(
            CatalogColumn(name, dtype, True) for name, dtype in (
                ('project_id', 'VARCHAR'), ('amount', 'INT'), ('period', 'DATE'), ('label', 'VARCHAR')))),
            CatalogTable('warehouse', 'test', 'projects', (CatalogColumn('project_id', 'VARCHAR', False),
                CatalogColumn('department', 'VARCHAR', True))))

        class Adapter:
            allowed_tables = ('test.budget', 'test.projects')
            config = SimpleNamespace(id='warehouse', database='test', limits=SimpleNamespace(
                profile_concurrency=1, exact_distinct_max_rows=100, statistics_column_batch_size=2,
                top_values_limit=10, top_values_max_columns=4))
            queries = []

            async def catalog(self):
                return tables

            async def query_bound(self, sql, parameters):
                self.queries.append((sql, parameters))
                sql = sqlglot.transpile(sql, read='starrocks', write='duckdb')[0]
                cursor = connection.execute(sql, parameters)
                return QueryResult(tuple(item[0] for item in cursor.description), cursor.fetchall(), 0)

            async def query(self, sql):
                return await self.query_bound(sql, {})

        yield connection, Adapter(), tables


async def profile(adapter, tables, **changes):
    return await collect_data_shape(adapter, catalog_scope=(tables[0],),
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        period_columns={'test.budget': 'period'}, metadata_revision='1', schema_hash='a' * 64,
        policy=StatisticalPolicy.model_validate(policy_payload(**changes)), policy_catalog=tables)


@pytest.mark.anyio
async def test_policy_dimension_and_numeric_filters_apply_to_all_profile_queries(profile_database):
    _, adapter, tables = profile_database
    result = await profile(adapter, tables, filters=[
        {'fieldRef': 'warehouse.test.projects.department', 'operator': 'in', 'values': ['X']},
        {'fieldRef': 'warehouse.test.budget.amount', 'operator': 'ge', 'values': [10]}],
        joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
            'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}])
    table = result.tables[0]
    assert (table.total_row_count, table.period_row_count, table.outside_period_row_count,
        table.period_null_count) == (3, 1, 1, 1)
    label = next(item for item in table.columns if item.name == 'label')
    assert [(item.value, item.count) for item in label.top_values] == [('local', 1)]
    assert table.period_coverage == ('2026-01',)
    assert all("'X'" not in sql for sql, _ in adapter.queries)


@pytest.mark.anyio
async def test_unmapped_filter_is_rejected_before_any_profile_query(profile_database):
    _, adapter, tables = profile_database
    with pytest.raises(ReportingError) as caught:
        await profile(adapter, tables, filters=[
            {'fieldRef': 'warehouse.test.projects.department', 'operator': 'eq', 'values': ['X']}])
    assert caught.value.code == 'metric_filter_not_applicable'
    assert adapter.queries == []


@pytest.mark.anyio
async def test_duplicate_policy_dimension_cannot_be_profiled_as_unique(profile_database):
    connection, adapter, tables = profile_database
    connection.execute("INSERT INTO test.projects VALUES ('A','Y')")
    with pytest.raises(ReportingError) as caught:
        await profile(adapter, tables, filters=[
            {'fieldRef': 'warehouse.test.projects.department', 'operator': 'eq', 'values': ['X']}],
            joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
                'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}])
    assert caught.value.code == 'join_fanout'
    assert all('total_row_count' not in sql for sql, _ in adapter.queries)


@pytest.mark.anyio
@pytest.mark.parametrize('field,operator,values,total,current', [
    ('amount', 'eq', [10], 1, 1), ('amount', 'ne', [10], 4, 2),
    ('amount', 'lt', [20], 2, 2), ('amount', 'le', [20], 3, 2),
    ('amount', 'gt', [20], 2, 1), ('amount', 'ge', [20], 3, 1),
    ('amount', 'in', [10, 30], 2, 1), ('period', 'is_null', [], 1, 0),
    ('project_id', 'eq', ["A' OR 1=1 --"], 0, 0),
])
async def test_all_finite_policy_operators_preserve_profile_scope(
    profile_database, field, operator, values, total, current
):
    _, adapter, tables = profile_database
    result = await profile(adapter, tables, filters=[{
        'fieldRef': f'warehouse.test.budget.{field}', 'operator': operator, 'values': values}])
    assert (result.tables[0].total_row_count, result.tables[0].period_row_count) == (total, current)
    assert result.query_count == len(adapter.queries)


@pytest.mark.anyio
async def test_policy_join_does_not_read_unrelated_dimension_payload(profile_database):
    connection, adapter, tables = profile_database
    connection.execute('ALTER TABLE test.projects ADD COLUMN unrelated_payload JSON')
    from dataclasses import replace

    dimension = replace(tables[1], columns=(*tables[1].columns,
        CatalogColumn('unrelated_payload', 'JSON', True)))
    result = await profile(adapter, (tables[0], dimension), filters=[{
        'fieldRef': 'warehouse.test.projects.department', 'operator': 'eq', 'values': ['X']}],
        joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
            'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}])
    assert result.tables[0].total_row_count == 4
    assert all('unrelated_payload' not in sql for sql, _ in adapter.queries)


@pytest.mark.anyio
@pytest.mark.parametrize('condition,code', [
    ({'fieldRef': 'warehouse.test.budget.amount', 'operator': 'eq', 'values': [None]},
        'metric_filter_null_comparison'),
    ({'fieldRef': 'warehouse.test.hidden.secret', 'operator': 'eq', 'values': ['X']},
        'metric_field_denied'),
])
async def test_invalid_policy_scope_never_queries_data(profile_database, condition, code):
    _, adapter, tables = profile_database
    with pytest.raises(ReportingError) as caught:
        await profile(adapter, tables, filters=[condition])
    assert caught.value.code == code
    assert adapter.queries == []


@pytest.mark.anyio
async def test_dimension_duplicate_added_during_profile_discards_incomplete_shape(profile_database):
    connection, adapter, tables = profile_database
    original = adapter.query_bound
    inserted = False

    async def concurrent_write(sql, parameters):
        nonlocal inserted
        if 'total_row_count' in sql and not inserted:
            inserted = True
            connection.execute("INSERT INTO test.projects VALUES ('A','Y')")
        return await original(sql, parameters)

    adapter.query_bound = concurrent_write
    with pytest.raises(ReportingError) as caught:
        await profile(adapter, tables, filters=[{
            'fieldRef': 'warehouse.test.projects.department', 'operator': 'eq', 'values': ['X']}],
            joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
                'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}])
    assert inserted
    assert caught.value.code == 'join_fanout'


@pytest.mark.anyio
async def test_explicit_null_dimension_filter_retains_unmatched_facts(profile_database):
    connection, adapter, tables = profile_database
    connection.execute("DELETE FROM test.projects WHERE project_id='B'")
    shape = await profile(adapter, tables, filters=[{
        'fieldRef': 'warehouse.test.projects.department', 'operator': 'is_null'}],
        joins=[{'leftKeys': ['warehouse.test.budget.project_id'],
            'rightKeys': ['warehouse.test.projects.project_id'], 'outputGrain': ['project']}])
    assert (shape.tables[0].total_row_count, shape.tables[0].period_row_count) == (1, 1)
    label = next(item for item in shape.tables[0].columns if item.name == 'label')
    assert [(item.value, item.count) for item in label.top_values] == [('foreign', 1)]
