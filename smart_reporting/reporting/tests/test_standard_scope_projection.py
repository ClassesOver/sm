"""固定范围字段须投影后授权，不能只凭模型声明绕过范围校验。"""

from types import SimpleNamespace

import polars as pl
from loguru import logger

from smart_reporting.reporting.contract import MeasureSemantic
from smart_reporting.reporting.workflow.query_pipeline import QueryRequirement
from smart_reporting.reporting.workflow.runtime.planning import _with_drilldown_projection
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import _standard_analysis_state
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow


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
    from smart_reporting.reporting.hospital_operation.deterministic_analysis import apply_metric_scope

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
