from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ..data_source.period import PeriodRole
from ..models import ReportingError
from .factset import (
    HospitalOperationFact,
    HospitalOperationFactSet,
    HospitalOperationMetricFact,
    OperationModel,
)

FindingType = Literal["overall", "trend", "anomaly_clue", "attribution", "data_quality"]
EvidenceKind = Literal["direct_fact", "derived_fact", "correlation", "hypothesis"]

_CAUSAL_WORDS = re.compile(r"导致|因为|由于|造成|源于|归因于|使得|引起|resulted in|caused by", re.I)
_MACHINE_ID = re.compile(r"(?:fact|metric|finding|section)[-_][A-Za-z0-9_]+")
_BUSINESS_VALUE = re.compile(
    r"(?<![A-Za-z0-9_.])-?\d+(?:,\d{3})*(?:\.\d+)?\s*(?:亿元|万元|元|人次|%|个百分点)"
)


class FindingProposal(OperationModel):
    """模型输出的发现候选；不允许提交机器发现 ID。"""

    type: FindingType
    domain: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    claim: str = Field(min_length=1, max_length=4_000)
    fact_ids: tuple[str, ...] = Field(alias="factIds", min_length=1, max_length=2_000)
    evidence_kind: EvidenceKind = Field(alias="evidenceKind")
    period_roles: tuple[PeriodRole, ...] = Field(default=(), alias="periodRoles", max_length=3)
    related_domains: tuple[str, ...] = Field(default=(), alias="relatedDomains", max_length=6)

    @field_validator("title", "claim")
    @classmethod
    def validate_natural_language(cls, value: str) -> str:
        normalized = value.strip()
        if not any(character.isalnum() for character in normalized):
            raise ValueError("发现标题和陈述必须是可展示自然语言")
        if _MACHINE_ID.search(normalized):
            raise ValueError("发现标题和陈述不得包含机器标识")
        return normalized

    @field_validator("fact_ids", "period_roles", "related_domains")
    @classmethod
    def validate_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if len(normalized) != len(set(normalized)) or any(not item for item in normalized):
            raise ValueError("发现引用不能重复或为空")
        return normalized

    @model_validator(mode="after")
    def validate_kind(self) -> FindingProposal:
        if self.evidence_kind == "correlation" and _CAUSAL_WORDS.search(self.claim):
            raise ValueError("相关性发现不得使用确定因果措辞")
        if self.evidence_kind == "hypothesis" and "待验证" not in self.claim:
            raise ValueError("待验证假设必须在陈述中明确标记待验证")
        if self.evidence_kind in {"direct_fact", "derived_fact"} and self.type == "attribution":
            # 归因可作为已验证事实，但跨域时仍需服务端再次核验；这里只拒绝明显的猜因。
            return self
        return self


class HospitalOperationFinding(OperationModel):
    finding_id: str = Field(alias="findingId", pattern=r"^finding_[0-9]{3,6}$")
    type: FindingType
    domain: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    claim: str = Field(min_length=1, max_length=4_000)
    fact_ids: tuple[str, ...] = Field(alias="factIds", min_length=1, max_length=2_000)
    citation_ids: tuple[str, ...] = Field(alias="citationIds", min_length=1, max_length=100)
    evidence_kind: EvidenceKind = Field(alias="evidenceKind")
    period_roles: tuple[PeriodRole, ...] = Field(default=(), alias="periodRoles", max_length=3)
    related_domains: tuple[str, ...] = Field(default=(), alias="relatedDomains", max_length=6)


class FindingsResult(OperationModel):
    version: Literal["1"] = "1"
    findings: tuple[HospitalOperationFinding, ...] = Field(default=(), max_length=2_000)
    issues: tuple[dict[str, object], ...] = Field(default=(), max_length=100)


def build_findings(
    proposals: Iterable[FindingProposal | dict[str, object]],
    fact_set: HospitalOperationFactSet,
    *,
    selected_domains: tuple[str, ...] = (),
) -> FindingsResult:
    """验证并冻结发现；任一候选非法时返回逐字段纠错，不生成半可信发现。"""
    parsed: list[FindingProposal] = []
    issues: list[dict[str, object]] = []
    for index, raw in enumerate(proposals):
        try:
            proposal = (
                raw if isinstance(raw, FindingProposal) else FindingProposal.model_validate(raw)
            )
        except Exception:
            issues.append(
                _issue(
                    f"findings[{index}]",
                    raw,
                    "发现候选结构无效",
                    (),
                    "只修改失败字段并按允许值重试",
                )
            )
            continue
        parsed.append(proposal)
    if issues:
        raise ReportingError(
            "report_findings_invalid", "分析发现包含无效字段。", details={"issues": issues}
        )

    # Findings 是分析目录的上游边界：基础审计事实和 support 分块只能用于服务端复算，
    # 不得被模型直接引用，否则模型可以绕过 publishable MetricFact 的单位、公式和覆盖门禁。
    fact_by_id: dict[str, HospitalOperationMetricFact] = {
        item.fact_id: item for item in fact_set.metric_facts if item.publishable
    }
    selected = set(selected_domains)
    frozen: list[HospitalOperationFinding] = []
    for index, proposal in enumerate(parsed, start=1):
        path = f"findings[{index - 1}]"
        unknown = tuple(item for item in proposal.fact_ids if item not in fact_by_id)
        if unknown:
            issues.append(
                _issue(
                    f"{path}.factIds",
                    list(unknown),
                    "factId 未在当前 FactSet 注册",
                    tuple(sorted(fact_by_id)),
                    "只替换为当前 FactSet 中已注册的 factId",
                )
            )
            continue
        if selected and proposal.domain not in selected and proposal.type != "data_quality":
            issues.append(
                _issue(
                    f"{path}.domain",
                    proposal.domain,
                    "发现超出请求领域范围",
                    tuple(sorted(selected)),
                    "将 domain 改为请求范围内领域或删除该发现",
                )
            )
            continue
        if proposal.type == "anomaly_clue" and proposal.evidence_kind == "hypothesis":
            # 异常线索可以是待验证假设，但必须清楚标记；FindingProposal 已校验标记。
            pass
        if proposal.type == "attribution":
            domains = {fact_by_id[item].domain for item in proposal.fact_ids}
            domains.add(proposal.domain)
            if len(domains) > 1:
                mismatch = _cross_domain_mismatch(
                    tuple(fact_by_id[item] for item in proposal.fact_ids)
                )
                if mismatch:
                    issues.append(
                        _issue(
                            f"{path}.factIds",
                            list(proposal.fact_ids),
                            f"跨域归因不可比：{mismatch}",
                            (),
                            "只保留期间、粒度、组织和口径一致的事实，或改为 correlation/hypothesis",
                        )
                    )
                    continue
        allowed_values = {fact_by_id[item].display_text for item in proposal.fact_ids}
        observed_values = {match.group(0) for match in _BUSINESS_VALUE.finditer(proposal.claim)}
        if observed_values - allowed_values:
            issues.append(
                _issue(
                    f"{path}.claim",
                    proposal.claim,
                    "发现陈述中的业务数值未逐字绑定 MetricFact.displayText",
                    tuple(sorted(allowed_values)),
                    "只使用所绑定可发布 MetricFact 的 displayText，或删除未绑定数值",
                )
            )
            continue
        actual_period_roles = _infer_period_roles(proposal.fact_ids, fact_by_id)
        if proposal.period_roles and set(proposal.period_roles) != set(actual_period_roles):
            issues.append(
                _issue(
                    f"{path}.periodRoles",
                    list(proposal.period_roles),
                    "periodRoles 与引用事实的期间角色不一致",
                    tuple(actual_period_roles),
                    "只保留引用事实实际携带的期间角色",
                )
            )
            continue
        citations = tuple(
            sorted(
                {
                    citation
                    for fact_id in proposal.fact_ids
                    for citation in _fact_citations(fact_by_id[fact_id])
                }
            )
        )
        if not citations:
            issues.append(
                _issue(
                    f"{path}.factIds",
                    list(proposal.fact_ids),
                    "引用事实缺少可追溯 citation",
                    (),
                    "替换为带完整证据引用的 MetricFact",
                )
            )
            continue
        period_roles = proposal.period_roles or actual_period_roles
        frozen.append(
            HospitalOperationFinding(
                findingId=f"finding_{index:03d}",
                type=proposal.type,
                domain=proposal.domain,
                title=proposal.title,
                claim=proposal.claim,
                factIds=proposal.fact_ids,
                citationIds=citations,
                evidenceKind=proposal.evidence_kind,
                periodRoles=period_roles,
                relatedDomains=tuple(
                    sorted(
                        set(proposal.related_domains)
                        | {
                            fact_by_id[item].domain
                            for item in proposal.fact_ids
                            if item in fact_by_id
                        }
                    )
                ),
            )
        )
    if issues:
        raise ReportingError(
            "report_findings_invalid",
            "分析发现未通过事实和领域边界校验。",
            details={"issues": issues},
        )
    return FindingsResult(findings=tuple(frozen))


def _issue(
    path: str,
    rejected_value: object,
    reason: str,
    allowed_values: tuple[object, ...],
    required_action: str,
) -> dict[str, object]:
    return {
        "path": path,
        "rejectedValue": rejected_value,
        "reason": reason,
        "allowedValues": list(allowed_values),
        "requiredAction": required_action,
    }


def _fact_citations(fact: HospitalOperationFact | HospitalOperationMetricFact) -> tuple[str, ...]:
    evidence = getattr(fact, "evidence", None)
    if evidence is not None:
        return tuple(evidence.references)
    return tuple(getattr(fact, "citation_ids", ()))


def _fact_periods(fact: HospitalOperationFact | HospitalOperationMetricFact) -> tuple[str, ...]:
    if isinstance(fact, HospitalOperationMetricFact):
        return fact.periods
    return (fact.period,)


def _fact_signature(
    fact: HospitalOperationFact | HospitalOperationMetricFact,
) -> tuple[object, ...]:
    if isinstance(fact, HospitalOperationMetricFact):
        return (fact.period_role, fact.periods, fact.scope, fact.hospital)
    return (
        fact.period_role,
        (fact.period,),
        fact.grain,
        fact.hospital,
        fact.campus,
        fact.department,
        fact.accounting_unit,
    )


def _cross_domain_mismatch(
    facts: tuple[HospitalOperationFact | HospitalOperationMetricFact, ...],
) -> str | None:
    if not facts:
        return "没有事实"
    periods = {_fact_periods(item) for item in facts}
    if len(periods) > 1:
        return "期间不同"
    signatures = [_fact_signature(item) for item in facts]
    # MetricFact 没有组织粒度字段；它们只能在相同 scope/期间下比较。
    if len({(item[0], item[1], item[2]) for item in signatures}) > 1:
        return "粒度或期间角色不同"
    organizations = {
        (item.campus, item.department, item.accounting_unit)
        for item in facts
        if isinstance(item, HospitalOperationFact)
    }
    if len(organizations) > 1:
        return "组织范围不同"
    return None


def _infer_period_roles(
    fact_ids: tuple[str, ...],
    facts: dict[str, HospitalOperationMetricFact],
) -> tuple[PeriodRole, ...]:
    roles: set[PeriodRole] = set()
    for fact_id in fact_ids:
        fact = facts[fact_id]
        role = getattr(fact, "period_role", None)
        if role:
            roles.add(role)
    return tuple(sorted(roles))


__all__ = [
    "EvidenceKind",
    "FindingProposal",
    "FindingType",
    "FindingsResult",
    "HospitalOperationFinding",
    "build_findings",
]
