"""基于管理发现冻结的动态章节提纲。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .findings import FindingGraph
from .outline import normalize_display_title
from .schema import HospitalOperationSchema


class NarrativeSectionCandidate(HospitalOperationSchema):
    title: str = Field(min_length=1, max_length=200)
    finding_ids: tuple[str, ...] = Field(alias="findingIds", min_length=1, max_length=2000)
    objective: str = Field(min_length=1, max_length=1000)
    grouping_reason: str = Field(alias="groupingReason", min_length=1, max_length=1000)
    narrative_role: Literal["management_finding", "risk", "limitation", "appendix"] = Field(
        default="management_finding", alias="narrativeRole"
    )
    priority: Literal["high", "medium", "low"] = "medium"
    max_charts: int = Field(default=2, alias="maxCharts", ge=0, le=20)
    max_blocks: int = Field(default=4, alias="maxBlocks", ge=1, le=20)


class NarrativeOutlineCandidate(HospitalOperationSchema):
    version: Literal["1"] = "1"
    title: str = Field(min_length=1, max_length=200)
    sections: tuple[NarrativeSectionCandidate, ...] = Field(min_length=1)
    appendix_finding_ids: tuple[str, ...] = Field(default=(), alias="appendixFindingIds", max_length=2000)
    omitted_findings: tuple[dict[str, str], ...] = Field(default=(), alias="omittedFindings", max_length=200)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=r"^[0-9a-f]{64}$")


class NarrativeSection(HospitalOperationSchema):
    code: str = Field(pattern=r"^section_[0-9]{3,6}$")
    section_number: str = Field(alias="sectionNumber", pattern=r"^[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=200)
    finding_ids: tuple[str, ...] = Field(alias="findingIds", min_length=1, max_length=2000)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=2000)
    objective: str = Field(min_length=1, max_length=1000)
    grouping_reason: str = Field(alias="groupingReason", min_length=1, max_length=1000)
    narrative_role: str = Field(alias="narrativeRole", min_length=1, max_length=64)
    priority: str = Field(min_length=1, max_length=16)
    max_charts: int = Field(alias="maxCharts", ge=0, le=20)
    max_blocks: int = Field(alias="maxBlocks", ge=1, le=20)


class NarrativeOutline(HospitalOperationSchema):
    version: Literal["1"] = "1"
    title: str = Field(min_length=1, max_length=200)
    sections: tuple[NarrativeSection, ...] = Field(min_length=1)
    appendix_finding_ids: tuple[str, ...] = Field(default=(), alias="appendixFindingIds", max_length=2000)
    omitted_findings: tuple[dict[str, str], ...] = Field(default=(), alias="omittedFindings", max_length=200)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=r"^[0-9a-f]{64}$")


class NarrativeQualityMetrics(HospitalOperationSchema):
    finding_count: int = Field(alias="findingCount", ge=0)
    assigned_finding_count: int = Field(alias="assignedFindingCount", ge=0)
    coverage_rate: float = Field(alias="coverageRate", ge=0, le=1)
    duplicate_finding_ids: tuple[str, ...] = Field(default=(), alias="duplicateFindingIds")
    unassigned_finding_ids: tuple[str, ...] = Field(default=(), alias="unassignedFindingIds")
    empty_section_codes: tuple[str, ...] = Field(default=(), alias="emptySectionCodes")
    issues: tuple[dict[str, Any], ...] = Field(default=(), max_length=500)


def evaluate_narrative_quality(
    graph: FindingGraph,
    outline: NarrativeOutline,
    *,
    rendered_section_codes: tuple[str, ...] = (),
) -> NarrativeQualityMetrics:
    """计算动态提纲质量指标；所有结果都是软告警，不改变发布决策。"""
    known = {item.finding_id for item in graph.findings}
    occurrences: dict[str, int] = {}
    for section in outline.sections:
        for finding_id in section.finding_ids:
            occurrences[finding_id] = occurrences.get(finding_id, 0) + 1
    duplicate = tuple(sorted(item for item, count in occurrences.items() if count > 1))
    assigned = set(occurrences) | set(outline.appendix_finding_ids)
    unassigned = tuple(sorted(known - assigned - {
        item.get("findingId") for item in outline.omitted_findings if item.get("findingId")
    }))
    empty = tuple(section.code for section in outline.sections if not section.finding_ids)
    issues: list[dict[str, Any]] = []
    if duplicate:
        issues.append({"code": "report_narrative_duplicate_finding", "findingIds": list(duplicate)})
    if unassigned:
        issues.append({"code": "report_narrative_unassigned_finding", "findingIds": list(unassigned)})
    if empty:
        issues.append({"code": "report_narrative_empty_section", "sectionCodes": list(empty)})
    rendered = set(rendered_section_codes)
    unrendered = tuple(section.code for section in outline.sections if section.code not in rendered)
    if unrendered:
        issues.append({"code": "report_narrative_section_unrendered", "sectionCodes": list(unrendered)})
    count = len(graph.findings)
    return NarrativeQualityMetrics(
        findingCount=count,
        assignedFindingCount=len(assigned & known),
        coverageRate=(len(assigned & known) / count if count else 1.0),
        duplicateFindingIds=duplicate,
        unassignedFindingIds=unassigned,
        emptySectionCodes=empty,
        issues=tuple(issues),
    )


def repair_narrative_candidate(
    candidate: NarrativeOutlineCandidate, *, graph: FindingGraph,
) -> tuple[NarrativeOutlineCandidate | None, dict[str, int]]:
    """模型抄错、重复或漏写个别 findingId 时就地修正，保留其章节划分与标题。

    回放中190个发现的全局统筹因抄错编号三次被拒，整份报告退回确定性分组，章节名成了
    几十个发现标题的拼接。修正只做最小处理：去掉未知与重复编号、删去因此为空的章节、
    把附录章节中的高优先级发现移回正文，遗漏发现归入分析项重合最多的正文章节（高优先级
    无处可归时进第一个正文章节，其余进附录）。修正后没有章节时返回 None。
    """
    cards = {card.finding_id: card for card in graph.findings}
    seen: set[str] = set()
    counts = {"unknown": 0, "duplicate": 0, "reassigned": 0}

    def keep(finding_id: str) -> bool:
        if finding_id not in cards:
            counts["unknown"] += 1
            return False
        if finding_id in seen:
            counts["duplicate"] += 1
            return False
        seen.add(finding_id)
        return True

    sections = []
    moved: list[str] = []
    for section in candidate.sections:
        ids = [finding_id for finding_id in section.finding_ids if keep(finding_id)]
        if section.narrative_role == "appendix":
            moved.extend(finding_id for finding_id in ids if cards[finding_id].priority == "high")
            ids = [finding_id for finding_id in ids if cards[finding_id].priority != "high"]
        if ids:
            sections.append(section.model_copy(update={"finding_ids": tuple(ids)}))
    appendix = [finding_id for finding_id in candidate.appendix_finding_ids if keep(finding_id)]
    omitted = [item for item in candidate.omitted_findings
               if item.get("reason", "").strip() and keep(item.get("findingId", ""))]
    missing = [card.finding_id for card in graph.findings if card.finding_id not in seen] + moved
    body = [index for index, section in enumerate(sections) if section.narrative_role != "appendix"]
    for finding_id in missing:
        card = cards[finding_id]
        overlap = {index: len(set(card.analysis_ids) & {aid for fid in sections[index].finding_ids
                                                          for aid in cards[fid].analysis_ids})
                   for index in body}
        target = max(overlap, key=lambda index: overlap[index]) if overlap and max(overlap.values()) else None
        if target is None and card.priority == "high" and body:
            target = body[0]
        if target is None:
            if card.priority == "high":
                return None, counts
            appendix.append(finding_id)
        else:
            sections[target] = sections[target].model_copy(
                update={"finding_ids": (*sections[target].finding_ids, finding_id)})
        counts["reassigned"] += 1
    if not sections:
        return None, counts
    return candidate.model_copy(update={
        "sections": tuple(sections), "appendix_finding_ids": tuple(appendix),
        "omitted_findings": tuple(omitted), "snapshot_hash": graph.snapshot_hash,
    }), counts


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}


def merge_repeated_sections(
    candidate: NarrativeOutlineCandidate, *, graph: FindingGraph,
) -> tuple[NarrativeOutlineCandidate, int]:
    """最终提纲中同名或分析项来源完全相同的正文章节合并到首次出现处。

    回放中跨批次统筹后仍出现两个“收入预算执行情况分析”、两个支出预算章节：来源分析项
    相同的章节只会把同一批事实各写一遍。附录章节不参与合并；分批候选不做合并，留给统筹。
    """
    cards = {card.finding_id: card for card in graph.findings}
    count = 0
    merged: list[NarrativeSectionCandidate] = []
    keys: dict[tuple[str, Any], int] = {}
    for section in candidate.sections:
        if section.narrative_role == "appendix":
            merged.append(section)
            continue
        sources = frozenset(aid for fid in section.finding_ids for aid in cards[fid].analysis_ids)
        identities = (
            ("title", normalize_display_title(section.title)),
            ("sources", (section.narrative_role, sources)),
        )
        target = next((keys[key] for key in identities if key in keys), None)
        if target is None:
            for key in identities:
                keys[key] = len(merged)
            merged.append(section)
            continue
        first = merged[target]
        merged[target] = first.model_copy(update={
            "finding_ids": (*first.finding_ids, *section.finding_ids),
            "priority": min(first.priority, section.priority, key=_PRIORITY_RANK.__getitem__),
            "max_charts": min(20, first.max_charts + section.max_charts),
            "max_blocks": min(20, first.max_blocks + section.max_blocks),
        })
        for key in identities:
            keys.setdefault(key, target)
        count += 1
    return candidate.model_copy(update={"sections": tuple(merged)}), count


def freeze_narrative_outline(
    candidate: NarrativeOutlineCandidate,
    *,
    graph: FindingGraph,
    analyses: list[dict[str, str]] | tuple[dict[str, str], ...],
) -> NarrativeOutline:
    if candidate.snapshot_hash != graph.snapshot_hash:
        raise ValueError("章节提纲快照与发现图谱快照不一致")
    findings = {item.finding_id: item for item in graph.findings}
    analysis_map = {item["analysisId"]: item for item in analyses if isinstance(item, dict)}
    assigned: list[str] = []
    sections: list[NarrativeSection] = []
    for index, item in enumerate(candidate.sections, 1):
        if len(set(item.finding_ids)) != len(item.finding_ids):
            raise ValueError("章节发现不能重复")
        unknown = set(item.finding_ids) - set(findings)
        if unknown:
            raise ValueError("章节引用未知发现")
        if set(item.finding_ids) & set(assigned):
            raise ValueError("同一发现不能重复归属章节")
        assigned.extend(item.finding_ids)
        selected = [findings[finding_id] for finding_id in item.finding_ids]
        if item.narrative_role == "appendix" and any(card.priority == "high" for card in selected):
            raise ValueError("高优先级发现必须进入正文，不能归入附录章节")
        analysis_ids = tuple(dict.fromkeys(aid for card in selected for aid in card.analysis_ids))
        if any(aid not in analysis_map for aid in analysis_ids):
            raise ValueError("章节发现引用未知分析项")
        sections.append(NarrativeSection(
            code=f"section_{index:03d}", sectionNumber=str(index), title=normalize_display_title(item.title),
            findingIds=item.finding_ids, analysisIds=analysis_ids, objective=item.objective,
            groupingReason=item.grouping_reason, narrativeRole=item.narrative_role,
            priority=item.priority, maxCharts=item.max_charts, maxBlocks=item.max_blocks,
        ))
    appendix = tuple(dict.fromkeys(candidate.appendix_finding_ids))
    if set(appendix) - set(findings) or set(appendix) & set(assigned):
        raise ValueError("附录发现引用无效或已重复归属")
    omitted: set[str] = set()
    for item in candidate.omitted_findings:
        finding_id = item.get("findingId")
        if not finding_id or finding_id not in findings:
            raise ValueError("忽略项必须引用已登记发现")
        if finding_id in omitted or finding_id in assigned or finding_id in appendix:
            raise ValueError("忽略项不能重复归属发现")
        if not item.get("reason", "").strip():
            raise ValueError("忽略发现必须说明具体理由")
        omitted.add(finding_id)
    missing = set(findings) - set(assigned) - set(appendix) - omitted
    if missing:
        raise ValueError(f"遗漏发现：{', '.join(sorted(missing))}")
    high_missing = [item.finding_id for item in graph.findings if item.priority == "high" and item.finding_id not in assigned]
    if high_missing:
        raise ValueError(f"遗漏高优先级发现：{', '.join(high_missing)}")
    appendix_groups = [appendix] if appendix else []
    for appendix_group in appendix_groups:
        appendix_cards = [findings[finding_id] for finding_id in appendix_group]
        appendix_analysis_ids = tuple(dict.fromkeys(
            analysis_id for card in appendix_cards for analysis_id in card.analysis_ids
        ))
        if any(analysis_id not in analysis_map for analysis_id in appendix_analysis_ids):
            raise ValueError("附录发现引用未知分析项")
        appendix_priority = "medium" if any(card.priority == "medium" for card in appendix_cards) else "low"
        sections.append(NarrativeSection(
            code=f"section_{len(sections) + 1:03d}",
            sectionNumber=str(len(sections) + 1),
            title="附录：补充管理发现",
            findingIds=appendix_group,
            analysisIds=appendix_analysis_ids,
            objective="列示正文未展开的补充管理发现及其限制",
            groupingReason="依据章节规划明确的附录去向保留补充发现",
            narrativeRole="appendix",
            priority=appendix_priority,
            maxCharts=0,
            maxBlocks=2,
        ))
    sections = [section.model_copy(update={"code": f"section_{index:03d}", "section_number": str(index)})
                for index, section in enumerate(sections, 1)]
    return NarrativeOutline(title=normalize_display_title(candidate.title), sections=tuple(sections), appendixFindingIds=appendix,
                            omittedFindings=candidate.omitted_findings, snapshotHash=graph.snapshot_hash)


__all__ = ["NarrativeOutline", "NarrativeOutlineCandidate", "NarrativeSection", "NarrativeSectionCandidate", "NarrativeQualityMetrics", "evaluate_narrative_quality", "freeze_narrative_outline", "merge_repeated_sections"]
