"""分析引用正式回执，不以探索CSV或旧业务Profile重新定义正式数值。"""

from ..hospital_operation.deterministic_analysis import DeterministicAnalysisBundle
from ..models import ReportingError
from .planning_contracts import MetricPlanningContext
from .presentation import semantic_issue_message


def build_registered_analysis_bundle(analysis, context: MetricPlanningContext, datasets,
    *, report_revision: str = "initial") -> DeterministicAnalysisBundle:
    definitions = {metric.version_ref(): metric for metric in context.metrics}
    if (context.report_revision != report_revision
        or analysis.allowed_metric_codes is None or analysis.allowed_field_refs is None
        or set(analysis.allowed_metric_codes) - {metric.id for metric in context.metrics}
        or set(analysis.allowed_field_refs) - {metric.field_ref for metric in context.metrics if metric.field_ref}):
        raise ReportingError("report_analysis_metric_scope_invalid", "分析指标范围不属于本报告登记版本。")
    for _, _, dataset_context, _ in datasets:
        for binding in dataset_context.metric_bindings:
            metric = definitions.get(binding.metric_version)
            if (metric is None or binding.measure.field_ref != metric.field_ref
                or binding.time.field_ref != metric.time_field or binding.unit != metric.unit
                or {item.field_ref for item in binding.grain} != {
                    item.field_ref for item in metric.dimensions if item.id in metric.grain}):
                raise ReportingError("report_analysis_metric_binding_invalid", "分析数据列绑定与登记指标定义不一致。")
    return DeterministicAnalysisBundle(analysisId=analysis.analysis_id,
        analysisName=analysis.analysis_name or analysis.management_question,
        metricContext=context, warnings=analysis.limitations)


def build_registered_finding_graph(bundles, *, context: MetricPlanningContext, snapshot_hash: str,
    files, citations, dataset_snapshots):
    """发现引用原始计算位置；缺引用/不可计算不冒充受支持结论。"""
    from hashlib import sha256

    from ..hospital_operation.findings import FindingCard, FindingGraph, FindingSourceRef
    from .models import ClaimSupport, QuestionCoverage

    definitions = {metric.version_ref(): metric for metric in context.metrics}
    cards, supports = [], []
    by_metric = {}
    for bundle in bundles:
        if bundle.metric_context != context or bundle.analysis_id not in files:
            raise ReportingError("report_finding_basis_mismatch", "发现来源与本报告登记计算上下文不一致。")
        source = files[bundle.analysis_id]
        for calculation_index, calculation in enumerate(context.calculations):
            for result_index, result in enumerate(calculation.results):
                metric = definitions[result.metric_version]
                pointer = f"/metricContext/calculations/{calculation_index}/results/{result_index}"
                identity = sha256(f"{snapshot_hash}:{bundle.analysis_id}:{result.fact_id}".encode()).hexdigest()[:16]
                citations_for_result = tuple(item.citation_id for item in citations
                    if item.dataset_id in result.dataset_ids
                    and dataset_snapshots.get(item.dataset_id) == item.snapshot_hash)
                cited_ids = {item.dataset_id for item in citations if item.citation_id in citations_for_result}
                supported = result.status == "computed" and bool(result.dataset_ids) and cited_ids == set(result.dataset_ids)
                issues = result.issue_codes + (() if supported or result.status == "unavailable" else ("fact_citation_unavailable",))
                card = FindingCard(findingId="finding_" + identity, analysisIds=(bundle.analysis_id,),
                    kind="scale" if result.status == "computed" else "data_quality",
                    title=f"{metric.name}计算结果" if result.status == "computed" else f"{metric.name}暂不可计算",
                    summary=(f"{metric.name}为 {result.value} {result.unit}。" if result.status == "computed"
                        else f"{metric.name}无可用数值，原因：{'；'.join(semantic_issue_message(code) for code in result.issue_codes)}。"),
                    metricCodes=(metric.id,), metricVersions=(result.metric_version,), factRefs=(result.fact_id,),
                    periodRoles=("current" if result.period == context.request.period else "comparison",),
                    periodStart=result.period.start.isoformat(), periodEnd=result.period.end.isoformat(),
                    priority="medium", evidenceLevel="verified_fact" if supported else "evidence_missing",
                    actionability="unknown", citationIds=citations_for_result,
                    sourceRefs=(FindingSourceRef(analysisId=bundle.analysis_id,
                        path=source['path'], fileSha256=source['sha256'], pointer=pointer),), limitations=issues)
                cards.append(card)
                supports.append(ClaimSupport(subject_id=card.finding_id, kind="fact", fact_refs=(result.fact_id,),
                    support_status="supported" if supported else "unverified"))
                if result.period == context.request.period:
                    by_metric.setdefault(result.metric_version, []).append((result, card))
    coverage = []
    for selection in context.selections:
        matches = by_metric.get(selection.selected, ()) if selection.status == "resolved" else ()
        computed = [(result, card) for result, card in matches if result.status == "computed"]
        # 数值计算成功尚不证明管理问题已被解释完整；后续分析支持关系负责最终裁定。
        issues = tuple(dict.fromkeys(code for result, card in matches for code in result.issue_codes))
        coverage.append(QuestionCoverage(question_id=selection.question_id,
            status="partial" if computed else "unavailable",
            finding_ids=tuple(card.finding_id for result, card in matches),
            issue_codes=issues or selection.issue_codes or ("question_analysis_pending",)))
    return FindingGraph(snapshotHash=snapshot_hash, findings=tuple(cards),
        claimSupport=tuple(supports), questionCoverage=tuple(coverage))
