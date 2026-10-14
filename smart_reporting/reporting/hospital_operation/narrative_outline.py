"""基于管理发现冻结的动态章节提纲。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .findings import FindingGraph
from .schema import HospitalOperationSchema


class NarrativeSectionCandidate(HospitalOperationSchema):
    title: str = Field(min_length=1, max_length=200)
    finding_ids: tuple[str, ...] = Field(alias="findingIds", min_length=1, max_length=200)
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
    sections: tuple[NarrativeSectionCandidate, ...] = Field(min_length=1, max_length=30)
    appendix_finding_ids: tuple[str, ...] = Field(default=(), alias="appendixFindingIds", max_length=2000)
    omitted_findings: tuple[dict[str, str], ...] = Field(default=(), alias="omittedFindings", max_length=200)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=r"^[0-9a-f]{64}$")


class NarrativeSection(HospitalOperationSchema):
    code: str = Field(pattern=r"^section_[0-9]{3,6}$")
    section_number: str = Field(alias="sectionNumber", pattern=r"^[1-9][0-9]*$")
    title: str = Field(min_length=1, max_length=200)
    finding_ids: tuple[str, ...] = Field(alias="findingIds", min_length=1, max_length=200)
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=1000)
    grouping_reason: str = Field(alias="groupingReason", min_length=1, max_length=1000)
    narrative_role: str = Field(alias="narrativeRole", min_length=1, max_length=64)
    priority: str = Field(min_length=1, max_length=16)
    max_charts: int = Field(alias="maxCharts", ge=0, le=20)
    max_blocks: int = Field(alias="maxBlocks", ge=1, le=20)


class NarrativeOutline(HospitalOperationSchema):
    version: Literal["1"] = "1"
    title: str = Field(min_length=1, max_length=200)
    sections: tuple[NarrativeSection, ...] = Field(min_length=1, max_length=30)
    appendix_finding_ids: tuple[str, ...] = Field(default=(), alias="appendixFindingIds", max_length=2000)
    omitted_findings: tuple[dict[str, str], ...] = Field(default=(), alias="omittedFindings", max_length=200)
    snapshot_hash: str = Field(alias="snapshotHash", pattern=r"^[0-9a-f]{64}$")


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
        if any(selected[0].period_start != card.period_start or selected[0].period_end != card.period_end or selected[0].grain != card.grain or selected[0].scope != card.scope for card in selected[1:]):
            raise ValueError("章节发现的期间、粒度或口径不一致")
        analysis_ids = tuple(dict.fromkeys(aid for card in selected for aid in card.analysis_ids))
        if any(aid not in analysis_map for aid in analysis_ids):
            raise ValueError("章节发现引用未知分析项")
        sections.append(NarrativeSection(
            code=f"section_{index:03d}", sectionNumber=str(index), title=item.title,
            findingIds=item.finding_ids, analysisIds=analysis_ids, objective=item.objective,
            groupingReason=item.grouping_reason, narrativeRole=item.narrative_role,
            priority=item.priority, maxCharts=item.max_charts, maxBlocks=item.max_blocks,
        ))
    appendix = tuple(dict.fromkeys(candidate.appendix_finding_ids))
    if set(appendix) - set(findings) or set(appendix) & set(assigned):
        raise ValueError("附录发现引用无效或已重复归属")
    omitted = {item["findingId"] for item in candidate.omitted_findings if "findingId" in item}
    missing = set(findings) - set(assigned) - set(appendix) - omitted
    if missing:
        raise ValueError(f"遗漏发现：{', '.join(sorted(missing))}")
    high_missing = [item.finding_id for item in graph.findings if item.priority == "high" and item.finding_id not in assigned]
    if high_missing:
        raise ValueError(f"遗漏高优先级发现：{', '.join(high_missing)}")
    return NarrativeOutline(title=candidate.title, sections=tuple(sections), appendixFindingIds=appendix,
                            omittedFindings=candidate.omitted_findings, snapshotHash=graph.snapshot_hash)


__all__ = ["NarrativeOutline", "NarrativeOutlineCandidate", "NarrativeSection", "NarrativeSectionCandidate", "freeze_narrative_outline"]
