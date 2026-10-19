"""动态叙事章节的确定性聚类与模型候选准备。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from .findings import FindingCard, FindingGraph
from .narrative_outline import NarrativeOutline, NarrativeOutlineCandidate, freeze_narrative_outline
from .outline import ReportOutline


@dataclass(frozen=True)
class NarrativeContentBudget:
    # 章节数量由管理主题决定；发现摘要仍需留在单次章节模型输入预算内。
    max_findings_per_section: int = 500


_REQUESTED_TITLE = re.compile(
    r"(?:生成|撰写|编制|形成|出具|输出|制作)(?:一份|一篇)?(?P<title>[^，。；,;：:\n“”\"《》]{4,40}?报告)"
)


def default_report_title(goal: str, start: date, end: date, report_type: str | None) -> str:
    """叙事提纲的默认报告标题：请求写明“生成××报告”时沿用，否则按期间与报告类型拼出。

    回放：占位标题“运营分析报告”在章节规划降级时原样成为封面标题，读者看不出年度与范围。
    """
    if match := _REQUESTED_TITLE.search(goal):
        title = re.sub(r"正式|完整|详细", "", match["title"]).strip()
        if len(title) >= 6 and re.search(r"\d{4}年|医院|运营|经营", title):
            return title
    if start.year != end.year:
        period = f"{start.year}—{end.year}年"
    elif (start.month, end.month) == (1, 12):
        period = f"{start.year}年"
    elif start.month == end.month:
        period = f"{start.year}年{start.month}月"
    else:
        period = f"{start.year}年{start.month}—{end.month}月"
    kind = {"comprehensive": "综合", "topic": "专题"}.get(report_type or "", "")
    return f"{period}{kind}运营分析报告"


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

    score = 0.0
    shared_metric = bool(set(left.metric_codes) & set(right.metric_codes))
    related = right.finding_id in left.related_finding_ids or left.finding_id in right.related_finding_ids
    shared_analysis = bool(set(left.analysis_ids) & set(right.analysis_ids))
    if not shared_metric and not related and not shared_analysis:
        return 0.0
    if shared_analysis:
        score += 0.2
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
            # Keep every finding; chapter selection remains a management decision.
            groups.append([finding.finding_id])
        else:
            best.append(finding.finding_id)
    return tuple(tuple(group) for group in groups)


def build_narrative_planning_context(
    graph: FindingGraph,
    report_goal: str,
    content_budget: NarrativeContentBudget | None = None,
) -> dict[str, Any]:
    budget = content_budget or NarrativeContentBudget()
    cards = sorted(graph.findings, key=rank_finding, reverse=True)
    groups = cluster_findings(graph, budget)
    body_groups = groups
    overflow: list[str] = []
    return {
        "reportGoal": report_goal,
        "snapshotHash": graph.snapshot_hash,
        "contentBudget": {"maxFindingsPerSection": budget.max_findings_per_section},
        "candidateGroups": [list(group) for group in body_groups],
        "overflowFindingIds": overflow,
        # 文件溯源身份留在服务端图谱；提纲只消费管理语义和分组边界。
        "findings": [card.model_dump(mode="json", by_alias=True, exclude={
            "source_refs", "citation_ids",
        }) for card in cards],
    }


def build_narrative_planning_batches(
    graph: FindingGraph, report_goal: str, *, max_bytes: int,
) -> tuple[dict[str, Any], ...]:
    """按调用预算分批，不截断发现内容；最终仍对完整图谱冻结归属。"""

    context = build_narrative_planning_context(graph, report_goal)

    def project(cards: list[dict[str, Any]]) -> dict[str, Any]:
        ids = {card["findingId"] for card in cards}
        return {
            **context,
            "findings": cards,
            "candidateGroups": [selected for group in context["candidateGroups"]
                                if (selected := [item for item in group if item in ids])],
            "overflowFindingIds": [item for item in context["overflowFindingIds"] if item in ids],
        }

    batches = []
    current = []
    for card in context["findings"]:
        proposed = project([*current, card])
        if len(json.dumps(proposed, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
            if not current:
                raise ValueError("单个发现与报告目标已超过提纲规划输入预算")
            batches.append(project(current))
            current = []
            proposed = project([card])
            if len(json.dumps(proposed, ensure_ascii=False, separators=(",", ":")).encode()) > max_bytes:
                raise ValueError("单个发现与报告目标已超过提纲规划输入预算")
        current.append(card)
    if current:
        batches.append(project(current))
    return tuple(batches)


def freeze_planned_sections(
    candidate: NarrativeOutlineCandidate,
    graph: FindingGraph,
    analyses: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> NarrativeOutline:
    return freeze_narrative_outline(candidate, graph=graph, analyses=analyses)


def build_fallback_narrative_candidate(
    graph: FindingGraph, title: str,
    *, analyses: Sequence[Mapping[str, str]] = (),
) -> NarrativeOutlineCandidate:
    """为附录预留容量，不截断发现或将高优先级发现移出正文。"""

    cards = {item.finding_id: item for item in graph.findings}
    names = {item["analysisId"]: item["analysisName"] for item in analyses
             if item.get("analysisId") and item.get("analysisName")}

    def display_title(card: FindingCard) -> str:
        if any("\u4e00" <= char <= "\u9fff" for char in card.title):
            return card.title
        return "；".join(dict.fromkeys(names[aid] for aid in card.analysis_ids if aid in names)) or card.title
    def group_title(group: Sequence[str]) -> str:
        # 回放中把组内全部发现标题用“；”拼接成章节名（数百字）；改用分析名称，
        # 最多两个，超过时加“等”。
        analysis_names = list(dict.fromkeys(names[aid] for item in group for aid in cards[item].analysis_ids
                                            if aid in names))
        if not analysis_names:
            return display_title(cards[group[0]])[:30]
        title = "、".join(analysis_names[:2]) + ("等" if len(analysis_names) > 2 else "")
        return title if len(title) <= 30 else analysis_names[0][:30]

    # 统计关系和常量等限制保留在附录，不占用经营主题的正文容量。
    body = tuple(card for card in graph.findings
                 if card.priority == 'high' or (card.priority != 'low'
                     and card.evidence_level != 'statistical_relation'))
    if not body:
        body = (max(graph.findings, key=rank_finding),)
    body_ids = {card.finding_id for card in body}
    appendix_ids = tuple(card.finding_id for card in graph.findings if card.finding_id not in body_ids)
    groups = cluster_findings(
        graph.model_copy(update={"findings": body}),
        NarrativeContentBudget(max_findings_per_section=max(1, len(body))),
    )
    for body_count in range(len(groups), 0, -1):
        appendix = (*appendix_ids, *(item for group in groups[body_count:] for item in group))
        if any(cards[item].priority == "high" for item in appendix):
            continue
        return NarrativeOutlineCandidate(
            title=title, snapshotHash=graph.snapshot_hash,
            sections=tuple({
                "title": group_title(group),
                "findingIds": group,
                "objective": "解释已核验发现并提出管理动作",
                "groupingReason": "依据共享指标、管理主题和已登记关系确定性分组",
                "priority": max((cards[item] for item in group), key=rank_finding).priority,
            } for group in groups[:body_count]),
            appendixFindingIds=appendix,
        )
    raise ValueError("高优先级发现分组超出章节容量，无法在保留全部发现的同时冻结提纲")


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
    "NarrativeContentBudget", "build_narrative_planning_context", "build_narrative_planning_batches", "cluster_findings",
    "freeze_planned_sections", "rank_finding", "score_finding_relation",
    "build_compatible_report_outline",
    "build_fallback_narrative_candidate",
]
