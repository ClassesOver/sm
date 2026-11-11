"""数据集字段绑定使用精确指标版本和SQL血缘，不借用旧业务Profile。"""

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_registered_query_contract import (
    approve,
    query_contract,
    query_sql,
)


def test_registered_metric_binding_uses_exact_version_and_output_alias():
    from smart_reporting.reporting.workflow.query_pipeline import project_registered_metric_bindings
    metrics = query_contract()['registered_metrics']
    query = approve(query_sql().replace('AS amount', 'AS budget_total'))[0]
    bindings = project_registered_metric_bindings(query, (metrics[0],))
    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.metric_version == metrics[0].version_ref()
    assert binding.measure.field_ref == metrics[0].field_ref
    assert binding.measure.dataset_field == 'budget_total'
    assert binding.time.field_ref == metrics[0].time_field
    assert binding.time.dataset_field == 'period'
    assert [(item.field_ref, item.dataset_field) for item in binding.grain] == [
        ('warehouse.test.budget.project_id', 'project_id')]


def test_shared_field_versions_remain_separate_bindings():
    from smart_reporting.reporting.workflow.query_pipeline import project_registered_metric_bindings
    metric = query_contract()['registered_metrics'][0]
    bindings = project_registered_metric_bindings(approve(query_sql())[0],
        (metric, metric.model_copy(update={'revision': 2})))
    assert [item.metric_version.revision for item in bindings] == [1, 2]


@pytest.mark.parametrize('mutation', ['ambiguous', 'grain_missing', 'source_mismatch'])
def test_binding_rejects_ambiguous_or_missing_registered_fields(mutation):
    from smart_reporting.reporting.workflow.query_pipeline import project_registered_metric_bindings
    metric = query_contract()['registered_metrics'][0]
    query = approve(query_sql())[0]
    if mutation == 'ambiguous':
        query = query.model_copy(update={'sql': query.sql.replace(' AS amount', ' AS amount, SUM(amount) AS duplicate')})
    elif mutation == 'grain_missing':
        query = query.model_copy(update={'sql': query.sql.replace('period, project_id,', 'period,')})
    else:
        metric = metric.model_copy(update={'field_ref': 'other.test.budget.amount'})
    with pytest.raises(ReportingError):
        project_registered_metric_bindings(query, (metric,))


def test_duplicate_output_name_cannot_hide_ambiguous_binding():
    from smart_reporting.reporting.workflow.query_pipeline import project_registered_metric_bindings
    metric = query_contract()['registered_metrics'][0]
    query = approve(query_sql())[0]
    query = query.model_copy(update={'sql': query.sql.replace(' AS amount', ' AS amount, SUM(amount) AS amount')})
    with pytest.raises(ReportingError):
        project_registered_metric_bindings(query, (metric,))


def test_bindings_survive_cte_projection_aliases():
    from smart_reporting.reporting.workflow.query_pipeline import project_registered_metric_bindings
    metric = query_contract()['registered_metrics'][0]
    sql = ('WITH totals AS (' + query_sql() + ') '
        'SELECT period AS report_date, project_id AS project, amount AS budget_total FROM totals')
    query = approve(sql)[0]
    binding, = project_registered_metric_bindings(query, (metric,))
    assert binding.measure.dataset_field == 'budget_total'
    assert binding.time.dataset_field == 'report_date'
    assert binding.grain[0].dataset_field == 'project'


@pytest.mark.parametrize('mutation', ['missing_field', 'duplicate_version'])
def test_dataset_context_rejects_bindings_outside_its_fields(mutation):
    from pydantic import ValidationError

    from smart_reporting.reporting.hospital_operation.detailed_analysis import (
        DatasetAnalysisContext,
    )
    from smart_reporting.reporting.workflow.query_pipeline import project_registered_metric_bindings

    metric = query_contract()['registered_metrics'][0]
    binding, = project_registered_metric_bindings(approve(query_sql())[0], (metric,))
    fields = ('period', 'project_id') if mutation == 'missing_field' else ('period', 'project_id', 'amount')
    with pytest.raises(ValidationError):
        DatasetAnalysisContext(datasetId='dataset-test', path='test.csv', size=100, sha256='a' * 64,
            rowCount=2, profileEngineVersion='test',
            profileFile={'path': 'test.profile.json', 'size': 10, 'sha256': 'b' * 64},
            profileModelView={}, fields=fields, numericFields=('amount',), periodValues=(),
            metricBindings=(binding, binding) if mutation == 'duplicate_version' else (binding,))
