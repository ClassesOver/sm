"""语义层提供候选；服务端验证精确身份与能力，不按名称猜测公式。"""

from pydantic import Field

from ..models import ReportingError
from .basis import BasisExecutionContext
from .compiler import compile_metric
from .models import (
    Identity,
    MetricCandidate,
    MetricRequest,
    MetricSelection,
    MetricVersionRef,
    SemanticModel,
)


class MetricSelectionRequest(SemanticModel):
    question_id: Identity
    candidates: tuple[MetricCandidate, ...] = Field(default=(), max_length=200)
    explicit: MetricVersionRef | None = None
    clarified: MetricVersionRef | None = None


class QuestionMetricCandidates(SemanticModel):
    question_id: Identity
    candidates: tuple[MetricCandidate, ...] = Field(default=(), max_length=200)


class MetricSelectionProposal(SemanticModel):
    questions: tuple[QuestionMetricCandidates, ...] = Field(min_length=1, max_length=50)


def _candidate_reason(metric):
    if metric.kind == "ratio":
        numerator, denominator = metric.numerator_version, metric.denominator_version
        formula = f"{numerator.metric_id}:{numerator.revision} / {denominator.metric_id}:{denominator.revision}"
    else:
        formula = f"{metric.kind}({metric.field_ref})；时间字段 {metric.time_field}"
    return (f"{metric.name}，第{metric.revision}版；{formula}；单位 {metric.unit}；"
        f"粒度 {', '.join(metric.grain)}；{metric.aggregation_policy.observation_kind}/"
        f"{metric.aggregation_policy.time_aggregation}")[:2000]


def select_metric_candidates(
    question_id: str, context: BasisExecutionContext, *,
    candidates: tuple[MetricCandidate, ...] = (),
    explicit: MetricVersionRef | None = None, clarified: MetricVersionRef | None = None,
) -> MetricSelection:
    """仅消费已登记问题和语义候选；别名召回不能决定权限或覆盖明确选择。"""
    basis, policy = context.basis, context.policy
    if question_id not in {question.id for question in basis.request_summary.questions}:
        raise ReportingError("metric_question_not_registered", "问题不属于本报告已登记请求。")
    graph = {metric.version_ref(): metric for metric in context.metrics}
    if (policy.scope_id != basis.scope_id or policy.id != basis.policy_version.policy_id
        or policy.revision != basis.policy_version.revision
        or len(graph) != len(context.metrics) or set(graph) != set(basis.metric_versions)
        or any(metric.scope_id != basis.scope_id for metric in context.metrics)
        or not set(policy.metric_versions).issubset(graph)):
        raise ReportingError("metric_basis_mismatch", "候选解析上下文与已登记计算依据不一致。")
    if explicit is not None and clarified is not None and explicit != clarified:
        raise ReportingError("metric_selection_conflict", "明确选择与澄清选择冲突，请核对后再选用。")
    if len(candidates) > 200:
        raise ReportingError("metric_candidate_limit", "指标候选数量超过本次解析限制。")
    refs = tuple(dict.fromkeys(candidate.metric_version for candidate in candidates))
    selected = clarified or explicit
    if selected is not None:
        refs = tuple(dict.fromkeys((*refs, selected)))
    if any(ref not in policy.metric_versions for ref in refs):
        raise ReportingError("metric_not_selected", "候选指标版本不属于本报告已登记口径。")
    checked = tuple(MetricCandidate(metric_version=ref, reason=_candidate_reason(graph[ref])) for ref in refs)
    if not checked:
        return MetricSelection(question_id=question_id, status="unavailable",
            issue_codes=("metric_no_match",))
    if selected is None and len(checked) > 1:
        return MetricSelection(question_id=question_id, status="ambiguous", candidates=checked,
            reason="存在不同计算定义，请核对候选差异；其余问题可以继续。", issue_codes=("metric_ambiguous",))
    selected = selected or checked[0].metric_version
    allowed_sources = {ref.source_id for ref in basis.source_versions}
    if any(source_id not in allowed_sources or any(table.source_id != source_id for table in metadata.tables)
        for source_id, metadata in context.metadata.items()):
        raise ReportingError("metric_basis_mismatch", "目录来源不属于已登记计算依据。")
    catalog = tuple(table for metadata in context.metadata.values() for table in metadata.tables)
    request = MetricRequest(metric_version=selected, basis_id=basis.id, period=basis.request_summary.period)
    try:
        plan = compile_metric(request, policy, context.metrics, catalog)
    except ReportingError as error:
        if error.code != "metric_field_denied":
            raise
        return MetricSelection(question_id=question_id, status="unavailable", candidates=checked,
            reason="候选引用字段不在本报告允许目录中，不能使用该资源计算。", issue_codes=(error.code,))
    if plan.issues:
        return MetricSelection(question_id=question_id, status="unavailable", candidates=checked,
            reason="候选已定位，但本次期间、结构或计算能力不满足要求。",
            issue_codes=tuple(dict.fromkeys(issue.code for issue in plan.issues)))
    source = "clarified" if clarified is not None else ("explicit" if explicit is not None else "scenario")
    return MetricSelection(question_id=question_id, status="resolved", candidates=checked, selected=selected,
        source=source, reason="采用已确认的精确指标版本。" if selected in (explicit, clarified) else
            "本场景语义召回只有一个候选，且通过已登记期间和目录的能力检查。")
