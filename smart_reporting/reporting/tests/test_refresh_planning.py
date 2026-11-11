"""重取数据须完整替换原计算，并通过原生分析契约，不能混用旧事实。"""

from hashlib import sha256

import pytest

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.semantics.basis import BasisRefreshIntent
from smart_reporting.reporting.tests.test_semantic_planning import receipts
from smart_reporting.reporting.tests.test_semantic_selection import selection_context


def refresh_inputs():
    context = selection_context()
    parent = receipts(context)
    old = parent[1]
    target_id = 'new-budget-calculation'
    revision = 'refresh-' + sha256(target_id.encode()).hexdigest()
    result = old.results[0].model_copy(update={'calculation_id': target_id, 'fact_id': 'new-budget-fact'})
    new = old.model_copy(update={'receipt_id': target_id, 'report_revision': revision, 'results': (result,)})
    intent = BasisRefreshIntent(receiptId='refresh-intent-' + sha256(target_id.encode()).hexdigest(),
        basisId=context.basis.id, reportRevision=revision, targetReceiptId=target_id,
        parentReceiptId=old.receipt_id, parentReportRevision='initial', request=old.request, createdAt=old.created_at)
    return context, parent, (intent, new)


def test_refresh_planning_uses_only_new_facts_and_keeps_original_request():
    from smart_reporting.reporting.semantics.planning import build_refreshed_metric_planning_context
    context, parent, refreshed = refresh_inputs()
    view = build_refreshed_metric_planning_context(context, parent, refreshed,
        parent_report_revision='initial', report_revision='revision-2')
    assert view.report_revision == 'revision-2'
    assert view.request == context.basis.request_summary
    assert view.selections == parent[0].selections
    assert view.calculations[0].receipt_id == refreshed[1].receipt_id
    assert view.calculations[0].results == refreshed[1].results
    assert view.calculations[0].results[0].value is None
    assert parent[1].results[0].fact_id == 'fact-budget'


@pytest.mark.parametrize('fault', ['missing_intent', 'missing_result', 'old_result', 'duplicate', 'parent',
    'parent_revision', 'basis', 'request', 'batch', 'fact', 'target_revision', 'extra'])
def test_refresh_planning_rejects_incomplete_or_rebound_batches(fault):
    from smart_reporting.reporting.semantics.planning import build_refreshed_metric_planning_context
    context, parent, (intent, result) = refresh_inputs()
    values = (intent, result)
    revision = 'revision-2'
    if fault == 'missing_intent':
        values = (result,)
    elif fault == 'missing_result':
        values = (intent,)
    elif fault == 'old_result':
        values = (intent, parent[1])
    elif fault == 'duplicate':
        values = (intent, result, result)
    elif fault == 'parent':
        values = (intent.model_copy(update={'parent_receipt_id': 'unknown'}), result)
    elif fault == 'parent_revision':
        values = (intent.model_copy(update={'parent_report_revision': 'other'}), result)
    elif fault == 'basis':
        values = (intent.model_copy(update={'basis_id': 'foreign'}), result)
    elif fault == 'request':
        from smart_reporting.reporting.semantics.models import Period
        values = (intent, result.model_copy(update={'request': result.request.model_copy(update={
            'period': Period(start='2025-11-01', end='2025-12-01')})}))
    elif fault == 'batch':
        values = (intent, result.model_copy(update={'results': (result.results[0].model_copy(update={
            'calculation_id': 'old-calculation'}),)}))
    elif fault == 'fact':
        values = (intent, result.model_copy(update={'results': parent[1].results}))
    elif fault == 'target_revision':
        revision = 'initial'
    elif fault == 'extra':
        values = (intent, result, parent[0])
    with pytest.raises(ReportingError, match='刷新'):
        build_refreshed_metric_planning_context(context, parent, values,
            parent_report_revision='initial', report_revision=revision)


@pytest.mark.parametrize('fault', [None, 'missing_comparison', 'reused_dataset'])
def test_refresh_requires_both_periods_and_preserves_parent_calculation_order(fault):
    from dataclasses import replace

    from smart_reporting.reporting.semantics.models import Period
    from smart_reporting.reporting.semantics.planning import build_refreshed_metric_planning_context

    context, (selection, old), (intent, new) = refresh_inputs()
    period = Period(start='2025-11-01', end='2025-12-01')
    context = replace(context, basis=context.basis.model_copy(update={'request_summary':
        context.basis.request_summary.model_copy(update={'comparison_period': period})}))
    previous = old.model_copy(update={'receipt_id': 'comparison-calculation',
        'request': old.request.model_copy(update={'period': period}),
        'results': (old.results[0].model_copy(update={'period': period, 'fact_id': 'previous-budget-fact',
            'calculation_id': 'comparison-calculation'}),)})
    new_id = 'new-comparison-calculation'
    revision = 'refresh-' + sha256(new_id.encode()).hexdigest()
    compare_intent = intent.model_copy(update={'receipt_id': 'refresh-intent-' + sha256(new_id.encode()).hexdigest(),
        'target_receipt_id': new_id, 'parent_receipt_id': previous.receipt_id, 'report_revision': revision,
        'request': previous.request})
    comparison = previous.model_copy(update={'receipt_id': new_id, 'report_revision': revision,
        'results': (previous.results[0].model_copy(update={'fact_id': 'new-comparison-fact', 'calculation_id': new_id}),)})
    parent = (selection, old, previous)
    refreshed = (comparison, new, compare_intent, intent)  # 数据库读取顺序不决定本期/基期位置。
    if fault == 'missing_comparison':
        refreshed = (intent, new)
    elif fault == 'reused_dataset':
        old = old.model_copy(update={'results': (old.results[0].model_copy(update={'dataset_ids': ('old-csv',)}),)})
        parent = (selection, old, previous)
        comparison = comparison.model_copy(update={'results': (comparison.results[0].model_copy(update={
            'dataset_ids': ('old-csv',)}),)})
        refreshed = (comparison, new, compare_intent, intent)
    if fault:
        with pytest.raises(ReportingError, match='刷新'):
            build_refreshed_metric_planning_context(context, parent, refreshed,
                parent_report_revision='initial', report_revision='revision-2')
    else:
        view = build_refreshed_metric_planning_context(context, parent, refreshed,
            parent_report_revision='initial', report_revision='revision-2')
        assert tuple(item.receipt_id for item in view.calculations) == (new.receipt_id, comparison.receipt_id)
        assert tuple(item.request.period for item in view.calculations) == (old.request.period, period)


def detail_plan_inputs():
    from smart_reporting.reporting.hospital_operation.detailed_analysis import DetailedAnalysisPlan
    from smart_reporting.reporting.tests.test_registered_analysis_facts import analysis_inputs

    analysis, parent, _ = analysis_inputs()
    analysis = analysis.model_copy(update={'dataset_ids': ('dataset-formal',), 'fields': ('value',),
        'metrics': ('value',), 'periods': (), 'organization_grain': ()})
    plan = DetailedAnalysisPlan(analyses=(analysis,), datasetIds=('dataset-formal',),
        reportGoal=parent.request.goal, analysisGoal='保留已批准分析意图')
    calculation = parent.calculations[0]
    result = calculation.results[0].model_copy(update={'fact_id': 'new-fact',
        'calculation_id': 'new-calculation', 'dataset_ids': ('new-dataset',)})
    child = parent.model_copy(update={'report_revision': 'revision-2', 'calculations': (
        calculation.model_copy(update={'receipt_id': 'new-calculation', 'results': (result,)}),)})
    return plan, parent, child


def test_refresh_detail_plan_retains_approved_intent_and_replaces_exact_datasets():
    from smart_reporting.reporting.semantics.planning import rebind_refresh_analysis_plan

    plan, parent, child = detail_plan_inputs()
    rebound = rebind_refresh_analysis_plan(plan, parent, child, dataset_fields={'new-dataset': ('value',)})
    assert rebound.dataset_ids == ('new-dataset',)
    assert rebound.analyses[0].dataset_ids == ('new-dataset',)
    assert rebound.analyses[0].model_copy(update={'dataset_ids': plan.analyses[0].dataset_ids,
        'evidence_summary': plan.analyses[0].evidence_summary}) == plan.analyses[0]
    assert '原数据画像和核对结论不得沿用' in rebound.analyses[0].evidence_summary
    assert rebound.report_goal == plan.report_goal and rebound.analysis_goal == plan.analysis_goal
    assert plan.dataset_ids == ('dataset-formal',)


@pytest.mark.parametrize('fault', ['request', 'basis', 'policy', 'metric_version', 'old_dataset', 'missing_field', 'exploration'])
def test_refresh_detail_plan_never_guesses_correspondence_or_uses_old_fields(fault):
    from smart_reporting.reporting.semantics.planning import rebind_refresh_analysis_plan

    plan, parent, child = detail_plan_inputs()
    fields = {'new-dataset': ('value',)}
    if fault == 'request':
        child = child.model_copy(update={'request': child.request.model_copy(update={'goal': 'different goal'})})
    elif fault == 'basis':
        child = child.model_copy(update={'basis_id': 'foreign'})
    elif fault == 'policy':
        child = child.model_copy(update={'policy': child.policy.model_copy(update={'revision': 2})})
    elif fault == 'metric_version':
        item = child.calculations[0]
        child = child.model_copy(update={'calculations': (item.model_copy(update={'request': item.request.model_copy(
            update={'metric_version': item.request.metric_version.model_copy(update={'metric_id': 'other'})})}),)})
    elif fault == 'old_dataset':
        item = child.calculations[0]
        child = child.model_copy(update={'calculations': (item.model_copy(update={'results': (
            item.results[0].model_copy(update={'dataset_ids': ('dataset-formal',)}),)}),)})
    elif fault == 'missing_field':
        fields = {'new-dataset': ('unexpected',)}
    else:
        plan = plan.model_copy(update={'dataset_ids': ('dataset-exploration',), 'analyses': (
            plan.analyses[0].model_copy(update={'dataset_ids': ('dataset-exploration',)}),)})
    with pytest.raises(ReportingError):
        rebind_refresh_analysis_plan(plan, parent, child, dataset_fields=fields)


@pytest.mark.parametrize('fault', ['partial_source', 'shared_source', 'shared_target', 'duplicate_request'])
def test_refresh_detail_plan_rejects_ambiguous_or_partial_calculation_sources(fault):
    from smart_reporting.reporting.semantics.planning import rebind_refresh_analysis_plan

    plan, parent, child = detail_plan_inputs()
    original, replacement = parent.calculations[0], child.calculations[0]
    if fault == 'partial_source':
        original = original.model_copy(update={'results': (original.results[0].model_copy(
            update={'dataset_ids': ('dataset-formal', 'other-source')}),)})
        parent = parent.model_copy(update={'calculations': (original,)})
    else:
        request = original.request if fault == 'duplicate_request' else original.request.model_copy(
            update={'dimensions': ('department',)})
        second_old = original.model_copy(update={'receipt_id': 'second-old', 'request': request,
            'results': (original.results[0].model_copy(update={'fact_id': 'second-old-fact',
                'calculation_id': 'second-old', 'dataset_ids': (
                    'dataset-formal' if fault == 'shared_source' else 'second-source',)}),)})
        second_new = replacement.model_copy(update={'receipt_id': 'second-new', 'request': request,
            'results': (replacement.results[0].model_copy(update={'fact_id': 'second-new-fact',
                'calculation_id': 'second-new', 'dataset_ids': (
                    'new-dataset' if fault == 'shared_target' else 'second-target',)}),)})
        parent = parent.model_copy(update={'calculations': (original, second_old)})
        child = child.model_copy(update={'calculations': (replacement, second_new)})
    with pytest.raises(ReportingError):
        rebind_refresh_analysis_plan(plan, parent, child,
            dataset_fields={'new-dataset': ('value',), 'second-target': ('value',)})
