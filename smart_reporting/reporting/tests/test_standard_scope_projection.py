"""固定范围字段须投影后授权，不能只凭模型声明绕过范围校验。"""

from types import SimpleNamespace

import polars as pl
import pytest
from loguru import logger

from smart_reporting.reporting.contract import MeasureSemantic
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.query_pipeline import QueryRequirement
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow
from smart_reporting.reporting.workflow.runtime.planning import _with_drilldown_projection


def test_frozen_scope_fields_are_projected_even_without_profile_dimensions():
    semantic = MeasureSemantic(
        fieldRef='s.db.fact.revenue', aggregation='sum',
        additiveAcross=['department'], exclusiveScope={'company': 'hospital', 'income_nature': 'ordered'},
    )
    requirement = QueryRequirement.model_validate({
        'requirementId': 'req-1', 'sourceId': 's',
        'tables': [{'table': 'db.fact', 'periodColumn': 'month',
                    'periodGranularity': 'month', 'measureColumns': ['revenue']}],
        'dimensionColumns': ['month', 'department'], 'grainColumns': ['month', 'department'],
    })

    projected, = _with_drilldown_projection(
        (requirement,), SimpleNamespace(measure_semantics=(semantic,), dimensions=()),
    )

    assert projected.dimension_columns == ('month', 'department', 'company', 'income_nature')
    assert projected.grain_columns == ('month', 'department', 'company', 'income_nature')
    assert projected.tables == requirement.tables
    assert semantic.exclusive_scope == {'company': 'hospital', 'income_nature': 'ordered'}
    # 已有过滤保留；把受审核固定范围加入 GROUP BY 不拆分原有分组。
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        apply_metric_scope,
    )

    frame = pl.DataFrame({
        'month': ['2025-01'] * 3, 'department': ['A', 'A', 'A'],
        'company': ['hospital', 'hospital', 'other'],
        'income_nature': ['ordered'] * 3, 'revenue': [10, 20, 999],
    })
    scoped = apply_metric_scope(frame, semantic.exclusive_scope)
    old = scoped.group_by(list(requirement.grain_columns)).agg(pl.col('revenue').sum())
    new = scoped.group_by(list(projected.grain_columns)).agg(pl.col('revenue').sum())
    assert old.to_dicts() == new.select(old.columns).to_dicts()
    assert new['revenue'].sum() == 30


def test_standard_preflight_records_missing_scope_columns_without_row_data():
    state = _standard_analysis_state()
    state.facts.metrics[0].scope = {'company': 'hospital'}
    events = []
    sink = logger.add(lambda message: events.append(message.record))
    try:
        assert AnalysisItemWorkflow._standard_spec(state) is None
    finally:
        logger.remove(sink)

    assert any(event['message'].startswith('report_analysis_standard_preflight ')
               and event['extra'].get('reason') == 'scope_columns_missing'
               for event in events)


def test_projection_retains_confirmed_additive_axis_without_profile_dimension():
    semantic = MeasureSemantic(
        fieldRef='s.db.fact.revenue', aggregation='sum',
        additiveAcross=['period_code', 'department'],
    )
    requirement = QueryRequirement.model_validate({
        'requirementId': 'req-1', 'sourceId': 's',
        'tables': [{'table': 'db.fact', 'periodColumn': 'data_date',
                    'periodGranularity': 'month', 'measureColumns': ['revenue']}],
        'dimensionColumns': ['data_date', 'department'],
        'grainColumns': ['data_date', 'department'],
    })

    projected, = _with_drilldown_projection(
        (requirement,), SimpleNamespace(measure_semantics=(semantic,), dimensions=()),
    )

    assert projected.dimension_columns == ('data_date', 'department', 'period_code')
    assert projected.grain_columns == ('data_date', 'department', 'period_code')
    assert projected.tables[0].period_column == 'data_date'


@pytest.mark.parametrize('matching_axis,aggregation,total', [
    (True, 'sum', 300), (False, 'last', 200),
])
def test_projected_axis_requires_row_evidence_before_enabling_period_sum(matching_axis, aggregation, total):
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import (
        build_deterministic_analysis_bundle,
    )

    from .test_deterministic_analysis import analysis, context, semantic

    confirmed = {**semantic('amount'), 'additiveAcross': ['period_code', 'department']}
    ctx = context('current', fields=('data_date', 'period_code', 'department', 'amount'),
                  semantics=(confirmed,)).model_copy(update={
        'time_series_sort_field': 'data_date', 'period_granularities': {'data_date': 'month'},
    })
    second_code = '202502' if matching_axis else '202501'
    csv = ('data_date,period_code,department,amount\n'
           '2025-01-01,202501,A,100\n'
           f'2025-02-01,{second_code},A,200\n').encode()

    bundle = build_deterministic_analysis_bundle(
        analysis(), (('current', csv, ctx, ('current',)),),
    )

    assert bundle.metrics[0].period_aggregation == aggregation
    assert bundle.metrics[0].total == total
