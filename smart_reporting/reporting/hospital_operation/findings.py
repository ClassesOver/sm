"""由已核验事实投影的管理发现契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .schema import HospitalOperationSchema

FindingKind = Literal[
    "scale", "trend", "comparison", "anomaly", "attribution", "impact", "data_quality"
]
FindingPriority = Literal["high", "medium", "low"]
EvidenceLevel = Literal[
    "direct_decomposition", "rule_based", "verified_fact", "statistical_relation",
    "business_hypothesis", "evidence_missing",
]
Actionability = Literal["high", "medium", "low", "unknown"]


class FindingSourceRef(HospitalOperationSchema):
    analysis_id: str = Field(alias="analysisId", pattern=r"^analysis_[0-9]{3,6}$")
    file_sha256: str = Field(alias="fileSha256", pattern=r"^[0-9a-f]{64}$")
    path: str = Field(min_length=1, max_length=1024)
    pointer: str = Field(min_length=1, max_length=512)


class FindingRelation(HospitalOperationSchema):
    left_finding_id: str = Field(alias="leftFindingId", min_length=1, max_length=128)
    right_finding_id: str = Field(alias="rightFindingId", min_length=1, max_length=128)
    relation: Literal["explains", "contributes_to", "contrasts_with", "correlates_with"]
    score: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def distinct_endpoints(self) -> FindingRelation:
        if self.left_finding_id == self.right_finding_id:
            raise ValueError("发现关系不能连接自身")
        return self


class FindingCard(HospitalOperationSchema):
    finding_id: str = Field(alias="findingId", pattern=r"^finding_[0-9a-f]{16}$")
    analysis_ids: tuple[str, ...] = Field(alias="analysisIds", min_length=1, max_length=100)
    kind: FindingKind
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    metric_codes: tuple[str, ...] = Field(alias="metricCodes", min_length=1, max_length=100)
    period_roles: tuple[str, ...] = Field(alias="periodRoles", min_length=1, max_length=3)
    period_start: str | None = Field(default=None, alias="periodStart", max_length=128)
    period_end: str | None = Field(default=None, alias="periodEnd", max_length=128)
    grain: tuple[str, ...] = Field(default=(), max_length=30)
    scope: dict[str, str] = Field(default_factory=dict, max_length=100)
    priority: FindingPriority
    evidence_level: EvidenceLevel = Field(alias="evidenceLevel")
    impact_value: float | None = Field(default=None, alias="impactValue")
    impact_unit: str | None = Field(default=None, alias="impactUnit", max_length=64)
    actionability: Actionability
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    source_refs: tuple[FindingSourceRef, ...] = Field(alias="sourceRefs", min_length=1, max_length=100)
    related_finding_ids: tuple[str, ...] = Field(default=(), alias="relatedFindingIds", max_length=100)
    limitations: tuple[str, ...] = Field(default=(), max_length=100)

    @field_validator("analysis_ids", "metric_codes", "period_roles", "citation_ids", "related_finding_ids")
    @classmethod
    def unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("发现数组不能包含重复值")
        return value

    @model_validator(mode="after")
    def validate_impact(self) -> FindingCard:
        if self.impact_value != self.impact_value:  # NaN without importing math
            raise ValueError("发现影响值不能为 NaN")
        if self.impact_value is not None and self.impact_unit is None:
            raise ValueError("发现存在影响值时必须声明单位")
        return self


class FindingGraph(HospitalOperationSchema):
    version: Literal["1"] = "1"
    snapshot_hash: str = Field(alias="snapshotHash", pattern=r"^[0-9a-f]{64}$")
    findings: tuple[FindingCard, ...] = Field(min_length=1, max_length=2000)
    relations: tuple[FindingRelation, ...] = Field(default=(), max_length=4000)
    warnings: tuple[str, ...] = Field(default=(), max_length=500)

    @model_validator(mode="after")
    def validate_graph(self) -> FindingGraph:
        ids = [item.finding_id for item in self.findings]
        known = set(ids)
        if len(ids) != len(known):
            raise ValueError("发现 ID 不能重复")
        for item in self.findings:
            if set(item.related_finding_ids) - known:
                raise ValueError("发现引用了未登记的关联发现")
        for relation in self.relations:
            if relation.left_finding_id not in known or relation.right_finding_id not in known:
                raise ValueError("发现关系引用了未登记的发现")
        return self


__all__ = ["FindingCard", "FindingGraph", "FindingRelation", "FindingSourceRef"]
