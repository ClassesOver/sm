"""探索SQL审批使用登记指标，目录旧语义不能赋予新的计算权限。"""

from types import SimpleNamespace

import pytest

from smart_reporting.reporting.contract import ReportRequestEnvelope, SourceSchemaSnapshot
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_semantic_selection import selection_context
from smart_reporting.reporting.workflow.query_pipeline import QueryRequirement, approve_query_batch


def query_contract():
    context = selection_context()
    metadata = context.metadata['warehouse']
    snapshot = SourceSchemaSnapshot(source='metadata_api', revision=metadata.revision,
        schemaHash=metadata.schema_hash, tables=metadata.tables)
    requirement = QueryRequirement.model_validate({'requirementId': 'budget-details', 'sourceId': 'warehouse',
        'tables': [{'table': 'test.budget', 'periodColumn': 'period', 'periodGranularity': 'date',
            'measureColumns': ['amount']}],
        'dimensionColumns': ['period', 'project_id'], 'grainColumns': ['period', 'project_id'], 'relations': []})
    envelope = ReportRequestEnvelope.model_validate({'reportGoal': '核对预算',
        'period': {'start': '2026-11-01', 'end': '2026-11-30'}, 'comparisonRoles': []})
    return dict(sources={'warehouse': SimpleNamespace(id='warehouse', database='test')},
        snapshots=(snapshot,), envelope=envelope, requirements=(requirement,), registered_metrics=context.metrics)


def query_sql(aggregate='SUM(amount)', period="period BETWEEN '2026-11-01' AND '2026-11-30'",
    grain='period, project_id'):
    return f'SELECT {grain}, {aggregate} AS amount FROM test.budget WHERE {period} GROUP BY {grain}'


def approve(sql, **changes):
    config = query_contract() | changes
    return approve_query_batch([{'requirementId': 'budget-details', 'sourceId': 'warehouse', 'sql': sql}], **config)


def test_registered_sum_is_approved_without_old_catalog_semantics():
    approved = approve(query_sql())
    assert len(approved) == 1 and 'SUM(amount)' in approved[0].sql


@pytest.mark.parametrize('mutation', ['unregistered', 'snapshot', 'time', 'grain', 'average', 'expression',
    'extra_average', 'scaled_sum', 'outer_average', 'period', 'hidden'])
def test_registered_query_rejects_changed_calculation_or_scope(mutation):
    config = query_contract()
    metric = config['registered_metrics'][0]
    sql = query_sql()
    if mutation == 'unregistered':
        config['registered_metrics'] = ()
    elif mutation == 'snapshot':
        from smart_reporting.reporting.semantics.models import AggregationPolicy
        config['registered_metrics'] = (metric.model_copy(update={'aggregation_policy': AggregationPolicy(
            observationKind='cumulative_snapshot', timeAggregation='difference')}),)
    elif mutation == 'time':
        config['registered_metrics'] = (metric.model_copy(update={'time_field': 'warehouse.test.budget.approved_at'}),)
    elif mutation == 'grain':
        sql = query_sql(grain='period')
        requirement = config['requirements'][0]
        config['requirements'] = (requirement.model_copy(update={'grain_columns': ('period',),
            'dimension_columns': ('period',)}),)
    elif mutation == 'average':
        sql = query_sql('AVG(amount)')
    elif mutation == 'expression':
        sql = query_sql('SUM(amount * 2)')
    elif mutation == 'extra_average':
        sql = sql.replace(' AS amount', ' AS amount, AVG(amount) AS misleading')
    elif mutation == 'scaled_sum':
        sql = query_sql('SUM(amount) * 2')
    elif mutation == 'outer_average':
        sql = 'SELECT AVG(amount) FROM (' + sql + ') calculated'
    elif mutation == 'period':
        sql = query_sql(period="period >= '2026-11-01'")
    elif mutation == 'hidden':
        sql = sql.replace('test.budget', 'test.hidden')
    with pytest.raises(ReportingError):
        approve_query_batch([{'requirementId': 'budget-details', 'sourceId': 'warehouse', 'sql': sql}], **config)


def test_registered_single_table_compiler_needs_no_old_semantics():
    from smart_reporting.reporting.workflow.runtime.planning import (
        _approve_generated_queries,
        _compile_single_table_queries,
    )
    config = query_contract()
    generated = _compile_single_table_queries(config['requirements'], snapshots=config['snapshots'],
        envelope=config['envelope'], registered_metrics=config['registered_metrics'])
    assert generated is not None
    approved, issues = _approve_generated_queries(generated, **config)
    assert issues == [] and len(approved) == 1
    assert 'SUM(amount)' in approved[0].sql
