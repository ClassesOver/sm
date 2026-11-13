"""固定范围字段须投影后授权，不能只凭模型声明绕过范围校验。"""

from types import SimpleNamespace

import polars as pl
import pytest
from loguru import logger

from smart_reporting.reporting.contract import MeasureSemantic
from smart_reporting.reporting.profile.models import EffectiveReportingProfile
from smart_reporting.reporting.tests.test_reporting_fixed_phase_workflows import (
    _standard_analysis_state,
)
from smart_reporting.reporting.workflow.query_pipeline import QueryRequirement
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import AnalysisItemWorkflow


# 仅用于构造历史范围/可加性用例，生产规划已由登记指标上下文接管。
def _with_drilldown_projection(
    requirements: tuple[QueryRequirement, ...],
    profile: EffectiveReportingProfile,
    *,
    measure_semantics: tuple[MeasureSemantic, ...] | None = None,
) -> tuple[QueryRequirement, ...]:
    """把可加维度及指标固定范围字段加入物化粒度。

    只处理单表 requirement；可加字段必须同时在该 requirement 的每个 measure
    的冻结 ``additiveAcross`` 中，不能因缺少展示维度登记而丢失时间轴证据；固定范围字段来自
    冻结语义 exclusiveScope，保留原有 SQL 范围过滤，仅投影常量以供补证复核。
    超过既有 30 列契约时保持原计划，后续能力生成器如实判定不可用。
    """

    effective_semantics = (
        getattr(profile, "measure_semantics", ())
        if measure_semantics is None
        else measure_semantics
    )
    profile_dimensions = getattr(profile, "dimensions", ())
    if not effective_semantics:
        return requirements
    semantics = {item.field_ref.casefold(): item for item in effective_semantics}
    projected: list[QueryRequirement] = []
    for requirement in requirements:
        if len(requirement.tables) != 1:
            projected.append(requirement)
            continue
        table = requirement.tables[0]
        table_name = table.table.casefold()
        semantic_items: list[MeasureSemantic] = []
        for measure in table.measure_columns:
            matches = [
                item
                for ref, item in semantics.items()
                if ref.startswith(f"{requirement.source_id.casefold()}.")
                and ref.endswith(f".{measure.casefold()}")
                and (
                    ref.rsplit(".", 1)[0].endswith(f".{table_name}")
                    or ref.rsplit(".", 1)[0].split(".", 1)[-1] == table_name
                )
            ]
            if len(matches) != 1:
                semantic_items = []
                break
            semantic_items.append(matches[0])
        if not semantic_items:
            projected.append(requirement)
            continue
        common_additive = set(semantic_items[0].additive_across)
        for semantic in semantic_items[1:]:
            common_additive.intersection_update(semantic.additive_across)
        additions: list[str] = list(dict.fromkeys(
            column for semantic in semantic_items for column in semantic.exclusive_scope
        ))
        for dimension in profile_dimensions:
            candidates = [
                ref.rsplit(".", 1)[-1]
                for ref in dimension.field_refs
                if ref.casefold().startswith(f"{requirement.source_id.casefold()}.")
                and (
                    ref.rsplit(".", 1)[0].casefold().endswith(f".{table_name}")
                    or ref.rsplit(".", 1)[0].casefold().split(".", 1)[-1]
                    == table_name
                )
                and ref.rsplit(".", 1)[-1].casefold() in common_additive
            ]
            if len(candidates) == 1:
                additions.append(candidates[0].casefold())
        # 保留源期间字段供事实层逐行核对时间轴别名；投影本身不证明同轴，
        # 也不把未确认时间可加性的指标从 last 改成 sum。
        additions.extend(sorted(common_additive))
        projected_dimensions = tuple(
            dict.fromkeys((*requirement.dimension_columns, *additions))
        )
        grain = tuple(dict.fromkeys((*requirement.grain_columns, *additions)))
        if len(projected_dimensions) > 30 or len(grain) > 30:
            projected.append(requirement)
            continue
        projected.append(
            requirement.model_copy(
                update={
                    "dimension_columns": projected_dimensions,
                    "grain_columns": grain,
                }
            )
        )
    return tuple(projected)


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
