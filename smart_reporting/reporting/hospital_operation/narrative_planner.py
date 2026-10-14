"""动态叙事章节的确定性聚类与模型候选准备。"""

from __future__ import annotations

from dataclasses import dataclass

from .findings import FindingCard, FindingGraph
from .narrative_outline import NarrativeOutline, NarrativeOutlineCandidate, freeze_narrative_outline
from .outline import ReportOutline


@dataclass(frozen=True)
class NarrativeContentBudget:
    max_findings_per_section: int = 6
    max_sections: int = 30


def rank_finding(finding: FindingCard) -> tuple[int, int, int]:
    priority = {"high": 3, "medium": 2, "low": 1}[finding.priority]
    evidence = {
        "direct_decomposition": 6, "rule_based": 5, "verified_fact": 4,
        "statistical_relation": 3, "business_hypothesis": 2, "evidence_missing": 1,
    }[finding.evidence_level]
    actionability = {"high": 3, "medium": 2, "low": 1, "unknown": 0}[finding.actionability]
    return priority, evidence, actionability


def score_finding_relation(left: FindingCard, right: FindingCard) -> float:
    """计算发现是否适合放在同一管理主题中；硬冲突返回负值。"""

    if left.period_start != right.period_start or left.period_end != right.period_end:
        return -1.0
    if left.grain != right.grain or left.scope != right.scope:
        return -1.0
    score = 0.0
    shared_metric = bool(set(left.metric_codes) & set(right.metric_codes))
    related = right.finding_id in left.related_finding_ids or left.finding_id in right.related_finding_ids
    if not shared_metric and not related:
        return 0.0
    if shared_metric:
        score += 0.25
    if set(left.period_roles) & set(right.period_roles):
        score += 0.15
    if related:
        score += 0.45
    if left.kind == "attribution" or right.kind == "attribution":
        score += 0.1
    return score


def cluster_findings(
    graph: FindingGraph,
    budget: NarrativeContentBudget | None = None,
) -> tuple[tuple[str, ...], ...]:
    budget = budget or NarrativeContentBudget()
    groups: list[list[str]] = []
    ordered = sorted(graph.findings, key=rank_finding, reverse=True)
    for finding in ordered:
        best: list[str] | None = None
        best_score = 0.0
        for group in groups:
            members = [next(card for card in graph.findings if card.finding_id == item) for item in group]
            scores = [score_finding_relation(finding, member) for member in members]
            if scores and min(scores) >= 0 and sum(scores) / len(scores) > best_score and len(group) < budget.max_findings_per_section:
                best, best_score = group, sum(scores) / len(scores)
        if best is None:
            # Keep every finding. Callers may use max_sections to select body
            # groups and place the remaining groups in an appendix.
            groups.append([finding.finding_id])
        else:
            best.append(finding.finding_id)
    return tuple(tuple(group) for group in groups)


def build_narrative_planning_context(
    graph: FindingGraph,
    report_goal: str,
    content_budget: NarrativeContentBudget | None = None,
) -> dict[str, object]:
    budget = content_budget or NarrativeContentBudget()
    cards = sorted(graph.findings, key=rank_finding, reverse=True)
    groups = cluster_findings(graph, budget)
    body_groups = groups[: budget.max_sections]
    overflow = [finding_id for group in groups[budget.max_sections:] for finding_id in group]
    return {
        "reportGoal": report_goal,
        "snapshotHash": graph.snapshot_hash,
        "contentBudget": {"maxFindingsPerSection": budget.max_findings_per_section, "maxSections": budget.max_sections},
        "candidateGroups": [list(group) for group in body_groups],
        "overflowFindingIds": overflow,
        "findings": [card.model_dump(mode="json", by_alias=True) for card in cards],
    }


def freeze_planned_sections(
    candidate: NarrativeOutlineCandidate,
    graph: FindingGraph,
    analyses: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> NarrativeOutline:
    return freeze_narrative_outline(candidate, graph=graph, analyses=analyses)


def build_compatible_report_outline(
    graph: FindingGraph,
    *,
    report_type: str,
    title: str,
    narrative_outline: NarrativeOutline | None = None,
) -> ReportOutline:
    """将确定性发现分组投影为旧渲染器可消费的服务端提纲。"""

    if narrative_outline is not None:
        if narrative_outline.snapshot_hash != graph.snapshot_hash:
            raise ValueError("最终提纲与发现图谱快照不一致")
        return ReportOutline.model_validate({
            "reportType": report_type,
            "title": narrative_outline.title,
            "sections": [
                {
                    "code": section.code,
                    "sectionNumber": section.section_number,
                    "title": section.title,
                    "focus": (section.objective,),
                    "analysisIds": section.analysis_ids,
                }
                for section in narrative_outline.sections
            ],
            "assumptions": (),
        })
    cards = {item.finding_id: item for item in graph.findings}
    sections: list[dict[str, object]] = []
    for index, group in enumerate(cluster_findings(graph), 1):
        analysis_ids = tuple(
            dict.fromkeys(
                analysis_id
                for finding_id in group
                for analysis_id in cards[finding_id].analysis_ids
            )
        )
        if not analysis_ids:
            continue
        sections.append(
            {
                "code": f"section_{index:03d}",
                "sectionNumber": str(index),
                "title": "；".join(cards[finding_id].title for finding_id in group)[:300],
                "focus": tuple(
                    dict.fromkeys(
                        metric
                        for finding_id in group
                        for metric in cards[finding_id].metric_codes
                    )
                ),
                "analysisIds": analysis_ids,
            }
        )
    if not sections:
        raise ValueError("发现图谱没有可用于章节的原子分析")
    return ReportOutline.model_validate(
        {
            "reportType": report_type if report_type in {"comprehensive", "topic"} else "comprehensive",
            "title": title,
            "sections": sections,
            "assumptions": (),
        }
    )


__all__ = [
    "NarrativeContentBudget", "build_narrative_planning_context", "cluster_findings",
    "freeze_planned_sections", "rank_finding", "score_finding_relation",
    "build_compatible_report_outline",
]
