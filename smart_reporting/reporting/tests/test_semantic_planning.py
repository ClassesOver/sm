"""规划只消费本报告登记选择和正式回执；不能混入其他版本或伪造回答完成。"""

from datetime import UTC, datetime

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.semantics.basis import BasisCalculationReceipt, BasisSelectionReceipt
from smart_reporting.reporting.semantics.models import MetricRequest, MetricResult
from smart_reporting.reporting.semantics.selection import select_metric_candidates
from smart_reporting.reporting.tests.test_semantic_selection import selection_context


def receipts(context):
    now = datetime(2026, 11, 9, tzinfo=UTC)
    selection = BasisSelectionReceipt(receiptId='initial-metric-selection', basisId=context.basis.id,
        reportRevision='initial', createdAt=now, selections=(select_metric_candidates('q-budget', context,
            explicit=context.metrics[0].version_ref()),))
    request = MetricRequest(metricVersion=context.metrics[0].version_ref(), basisId=context.basis.id,
        period=context.basis.request_summary.period)
    result = MetricResult(metricVersion=request.metric_version, basisId=context.basis.id,
        calculationId='calc-budget', factId='fact-budget', period=request.period, value=None, unit='CNY',
        status='unavailable', issueCodes=('missing_data',))
    calculation = BasisCalculationReceipt(receiptId='calc-budget', basisId=context.basis.id,
        reportRevision='initial', request=request, results=(result,), createdAt=now)
    return selection, calculation


def test_planning_preserves_unavailable_facts_without_claiming_question_answered():
    from smart_reporting.reporting.semantics.planning import build_metric_planning_context
    context = selection_context()
    view = build_metric_planning_context(context, receipts(context), report_revision='initial')
    payload = view.model_dump(mode='json', by_alias=True)
    assert payload['basisId'] == 'basis-selection'
    assert payload['selections'][0]['questionId'] == 'q-budget'
    assert payload['calculations'][0]['results'][0]['value'] is None
    assert payload['calculations'][0]['results'][0]['issueCodes'] == ['missing_data']
    assert payload['request']['questions'] == [{'id': 'q-budget', 'text': '预算是多少？'}]
    assert 'coverage' not in payload and 'workspace' not in payload['calculations'][0]


def test_unresolved_question_remains_in_planning_without_fake_calculation():
    from smart_reporting.reporting.semantics.planning import build_metric_planning_context
    context = selection_context()
    selection, _ = receipts(context)
    selection = selection.model_copy(update={'selections': (select_metric_candidates('q-budget', context),)})
    view = build_metric_planning_context(context, (selection,), report_revision='initial')
    assert view.selections[0].issue_codes == ('metric_no_match',)
    assert view.calculations == ()


@pytest.mark.parametrize('mutation', ['basis', 'revision', 'question', 'version', 'period', 'unit', 'duplicate', 'missing'])
def test_planning_rejects_receipts_outside_registered_question_and_calculation(mutation):
    from smart_reporting.reporting.semantics.planning import build_metric_planning_context
    context = selection_context()
    selection, calculation = receipts(context)
    values = (selection, calculation)
    if mutation == 'basis':
        values = (selection, calculation.model_copy(update={'basis_id': 'other-basis'}))
    elif mutation == 'revision':
        values = (selection, calculation.model_copy(update={'report_revision': 'other-revision'}))
    elif mutation == 'question':
        values = (selection.model_copy(update={'selections': ()}), calculation)
    elif mutation == 'version':
        values = (selection, calculation.model_copy(update={'request': calculation.request.model_copy(update={
            'metric_version': context.metrics[1].version_ref()})}))
    elif mutation == 'period':
        from smart_reporting.reporting.semantics.models import Period
        values = (selection, calculation.model_copy(update={'request': calculation.request.model_copy(update={
            'period': Period(start='2025-11-01', end='2025-12-01')})}))
    elif mutation == 'unit':
        values = (selection, calculation.model_copy(update={'results': (calculation.results[0].model_copy(update={'unit': 'USD'}),)}))
    elif mutation == 'duplicate':
        values = (selection, calculation, calculation.model_copy(update={'receipt_id': 'duplicate'}))
    elif mutation == 'missing':
        values = (selection,)
    with pytest.raises(ReportingError):
        build_metric_planning_context(context, values, report_revision='initial')


@pytest.mark.parametrize('mutation', ['time_field', 'shared_field_grain'])
def test_exploration_keeps_all_registered_grains_and_time_identity(mutation):
    from smart_reporting.reporting.workflow.query_pipeline import (
        QueryRequirement,
        registered_metric_requirement_issues,
    )
    context = selection_context()
    metric = context.metrics[0]
    requirement = QueryRequirement.model_validate({'requirementId': 'budget-details', 'sourceId': 'warehouse',
        'tables': [{'table': 'test.budget', 'periodColumn': 'period', 'periodGranularity': 'date',
            'measureColumns': ['amount']}],
        'dimensionColumns': ['period', 'project_id'], 'grainColumns': ['period', 'project_id'], 'relations': []})
    if mutation == 'time_field':
        metrics = (metric.model_copy(update={'time_field': 'warehouse.test.budget.approval_date'}),)
    else:
        from smart_reporting.reporting.semantics.models import DimensionDefinition
        second = metric.model_copy(update={'revision': 2, 'grain': ('department',),
            'dimensions': (DimensionDefinition(id='department', fieldRef='warehouse.test.budget.department_id'),)})
        metrics = (second, metric)
    issues = registered_metric_requirement_issues(requirement, 0, metrics)
    assert issues
    if mutation == 'shared_field_grain':
        assert any('department_id' in issue.get('missingValues', ()) for issue in issues)
