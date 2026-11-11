"""正式分析输入由可信依据及追加回执投影，不把计算成功等同问题已回答。"""

from hashlib import sha256

from pydantic import TypeAdapter, ValidationError

from ..hospital_operation.detailed_analysis import DetailedAnalysisPlan
from ..models import ReportingError
from .basis import (
    BasisCalculationReceipt,
    BasisExecutionContext,
    BasisReceipt,
    BasisRefreshIntent,
    BasisSelectionReceipt,
)
from .models import MetricRequest, RunIdentity
from .planning_contracts import MetricPlanningContext, PlanningCalculation


def rebind_refresh_analysis_plan(
    plan: DetailedAnalysisPlan, parent: MetricPlanningContext, child: MetricPlanningContext,
    *, dataset_fields: dict[str, tuple[str, ...]],
) -> DetailedAnalysisPlan:
    """按完整计算请求替换来源，保留原分析意图；无法对应时要求重新规划。"""
    def reject():
        raise ReportingError('report_refresh_analysis_plan_unavailable',
            '刷新数据无法完整承接原分析计划，请核对新数据字段并重新规划。')

    if (parent.basis_id != child.basis_id or parent.request != child.request
            or parent.policy != child.policy or parent.metrics != child.metrics
            or parent.selections != child.selections or parent.report_revision == child.report_revision):
        reject()
    old = {item.request.model_dump_json(): item for item in parent.calculations}
    new = {item.request.model_dump_json(): item for item in child.calculations}
    if (not old or len(old) != len(parent.calculations) or len(new) != len(child.calculations)
            or set(old) != set(new)):
        reject()
    old_receipts = {item.receipt_id for item in old.values()}
    old_facts = {result.fact_id for item in old.values() for result in item.results}
    old_datasets = {key for item in old.values() for result in item.results for key in result.dataset_ids}
    groups = []
    assigned_sources = set()
    assigned_targets = set()
    for key, original in old.items():
        replacement = new[key]
        source = {key for result in original.results for key in result.dataset_ids}
        target = tuple(dict.fromkeys(key for result in replacement.results for key in result.dataset_ids))
        if (not source or not target or assigned_sources.intersection(source)
                or assigned_targets.intersection(target) or replacement.receipt_id in old_receipts
                or old_datasets.intersection(target)
                or any(result.fact_id in old_facts or result.calculation_id != replacement.receipt_id
                    or result.basis_id != child.basis_id or result.period != replacement.request.period
                    for result in replacement.results)):
            reject()
        assigned_sources.update(source)
        assigned_targets.update(target)
        groups.append((source, target))

    def replace(ids):
        selected = set(ids)
        if not selected or selected - old_datasets:
            reject()
        targets = []
        covered = set()
        for source, target in groups:
            if source.intersection(selected):
                if not source <= selected:
                    reject()
                covered.update(source)
                targets.extend(target)
        if covered != selected:
            reject()
        return tuple(dict.fromkeys(targets))

    analyses = []
    for item in plan.analyses:
        ids = replace(item.dataset_ids)
        if any(key not in dataset_fields for key in ids):
            reject()
        available = {field for key in ids for field in dataset_fields[key]}
        if set((*item.fields, *item.metrics, *item.organization_grain)) - available:
            reject()
        analyses.append(item.model_copy(update={'dataset_ids': ids,
            'evidence_summary': '分析意图沿用已批准计划；数据来源已替换为本次登记的新计算输出，'
                '原数据画像和核对结论不得沿用，须依据新批次重新核验。'}))
    return plan.model_copy(update={'dataset_ids': replace(plan.dataset_ids), 'analyses': tuple(analyses)})


def build_metric_planning_context(
    context: BasisExecutionContext, receipts: tuple[BasisReceipt, ...], *, report_revision: str,
) -> MetricPlanningContext:
    """只接受本修订完整选择及全部正式计算；缺回执应先恢复计算步骤。"""
    def reject():
        raise ReportingError('report_metric_planning_invalid', '分析输入与本报告登记选择或计算回执不一致。')

    basis = context.basis
    if any(item.basis_id != basis.id or item.report_revision != report_revision for item in receipts):
        reject()
    selections = [item for item in receipts if isinstance(item, BasisSelectionReceipt)]
    if len(selections) != 1 or selections[0].receipt_id != 'initial-metric-selection':
        reject()
    return _build_planning_context(context, selections[0].selections,
        tuple(item for item in receipts if isinstance(item, BasisCalculationReceipt)), report_revision=report_revision)


def _build_planning_context(context, choices, calculations, *, report_revision):
    def reject():
        raise ReportingError('report_metric_planning_invalid', '分析输入与本报告登记选择或计算回执不一致。')

    basis = context.basis
    questions = basis.request_summary.questions
    if len(choices) != len(questions) or {item.question_id for item in choices} != {item.id for item in questions}:
        reject()
    by_question = {item.question_id: item for item in choices}
    choices = tuple(by_question[item.id] for item in questions)
    graph = {item.version_ref(): item for item in context.metrics}
    if (set(graph) != set(basis.metric_versions) or len(graph) != len(context.metrics)
        or context.policy.scope_id != basis.scope_id
        or context.policy.id != basis.policy_version.policy_id
        or context.policy.revision != basis.policy_version.revision
        or any(item.scope_id != basis.scope_id for item in context.metrics)):
        reject()
    if any(item.selected not in context.policy.metric_versions for item in choices if item.status == 'resolved'):
        reject()
    periods = tuple(dict.fromkeys(item for item in (basis.request_summary.period,
        basis.request_summary.comparison_period) if item is not None))
    expected = {MetricRequest(metric_version=item.selected, basis_id=basis.id, period=period).model_dump_json()
        for item in choices if item.status == 'resolved' for period in periods}
    actual = [item.request.model_dump_json() for item in calculations]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        reject()
    fact_ids = set()
    for calculation in calculations:
        dependencies = set()
        def visit(ref):
            if ref in dependencies:
                return
            if ref not in graph:
                reject()
            dependencies.add(ref)
            metric = graph[ref]
            if metric.kind == 'ratio':
                visit(metric.numerator_version)
                visit(metric.denominator_version)
        visit(calculation.request.metric_version)
        if calculation.request.metric_version not in {item.metric_version for item in calculation.results}:
            reject()
        for result in calculation.results:
            if (result.metric_version not in dependencies or result.basis_id != basis.id
                or result.period != calculation.request.period or result.unit != graph[result.metric_version].unit
                or result.fact_id in fact_ids):
                reject()
            fact_ids.add(result.fact_id)
    return MetricPlanningContext(basis_id=basis.id, report_revision=report_revision,
        request=basis.request_summary, policy=context.policy, metrics=context.metrics, selections=choices,
        calculations=tuple(PlanningCalculation(receipt_id=item.receipt_id, request=item.request,
            results=item.results, readiness=item.readiness) for item in calculations))


def build_refreshed_metric_planning_context(
    context: BasisExecutionContext, parent_receipts: tuple[BasisReceipt, ...],
    refreshed_receipts: tuple[BasisReceipt, ...], *, parent_report_revision: str, report_revision: str,
) -> MetricPlanningContext:
    """可信回执的完整投影；不改写批次归属，不复制旧事实冒充新结果。"""
    parent = build_metric_planning_context(context, parent_receipts, report_revision=parent_report_revision)
    return build_refreshed_planning_from_parent(context, parent, refreshed_receipts, report_revision=report_revision)


def build_refreshed_planning_from_parent(
    context: BasisExecutionContext, parent: MetricPlanningContext,
    refreshed_receipts: tuple[BasisReceipt, ...], *, report_revision: str,
) -> MetricPlanningContext:
    """从已核验的父修订继续刷新；父事实可来自独立批次，无需改写历史回执。"""
    def reject():
        raise ReportingError('report_metric_refresh_planning_invalid', '刷新分析缺少完整的新计算或与原回执身份不一致。')

    if (parent.basis_id != context.basis.id or parent.request != context.basis.request_summary
            or parent.policy != context.policy or parent.metrics != context.metrics
            or _build_planning_context(context, parent.selections, parent.calculations,
                report_revision=parent.report_revision) != parent):
        reject()
    try:
        TypeAdapter(RunIdentity).validate_python(report_revision)
    except ValidationError:
        reject()
    if report_revision == parent.report_revision:
        reject()
    if any(item.basis_id != context.basis.id for item in refreshed_receipts):
        reject()
    intents = tuple(item for item in refreshed_receipts if isinstance(item, BasisRefreshIntent))
    calculations = tuple(item for item in refreshed_receipts if isinstance(item, BasisCalculationReceipt))
    old = {item.receipt_id: item for item in parent.calculations}
    new = {item.receipt_id: item for item in calculations}
    if (len(intents) != len(old) or len(new) != len(calculations) or len(calculations) != len(old)
            or len(refreshed_receipts) != len(intents) + len(calculations)
            or {item.parent_receipt_id for item in intents} != set(old)
            or {item.target_receipt_id for item in intents} != set(new)):
        reject()
    old_facts = {result.fact_id for item in old.values() for result in item.results}
    old_datasets = {dataset for item in old.values() for result in item.results for dataset in result.dataset_ids}
    by_parent = {}
    for intent in intents:
        calculation = new[intent.target_receipt_id]
        original = old[intent.parent_receipt_id]
        digest = sha256(calculation.receipt_id.encode()).hexdigest()
        if (intent.receipt_id != 'refresh-intent-' + digest or intent.report_revision != 'refresh-' + digest
                or calculation.report_revision != intent.report_revision
                or intent.parent_report_revision != parent.report_revision
                or intent.request != original.request or calculation.request != original.request
                or calculation.receipt_id in old
                or any(result.calculation_id != calculation.receipt_id or result.fact_id in old_facts
                    or old_datasets.intersection(result.dataset_ids) for result in calculation.results)):
            reject()
        by_parent[original.receipt_id] = calculation
    # 沿用原选择和顺序；新批次独立身份仍保存在原始回执，不伪造新选择回执。
    return _build_planning_context(context, parent.selections,
        tuple(by_parent[item.receipt_id] for item in parent.calculations), report_revision=report_revision)
