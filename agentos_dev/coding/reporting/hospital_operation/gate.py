from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import Field

from .factset import HospitalOperationFactSet, OperationModel, compute_fact_set_hash

REQUIRED_DOMAINS = ("income", "workload", "budget", "full_cost", "cost_control", "funds")


class GateIssue(OperationModel):
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=1_000)
    domains: tuple[str, ...] = Field(default=(), max_length=6)
    blocking: bool = True


class PublicationGateResult(OperationModel):
    report_type: Literal["comprehensive", "topic"] = Field(alias="reportType")
    formal_release_allowed: bool = Field(alias="formalReleaseAllowed")
    internal_draft_allowed: bool = Field(default=True, alias="internalDraftAllowed")
    fact_set_hash: str = Field(alias="factSetHash", pattern=r"^[0-9a-f]{64}$")
    issues: tuple[GateIssue, ...] = Field(default=(), max_length=100)


def evaluate_publication_gate(
    fact_set: HospitalOperationFactSet,
    *,
    report_type: Literal["comprehensive", "topic"],
    selected_domains: tuple[str, ...] = (),
    referenced_fact_ids: tuple[str, ...] = (),
    chart_fact_ids: tuple[str, ...] = (),
) -> PublicationGateResult:
    """正式发布失败关闭；内部草稿保留完整门禁问题供管理确认。"""
    issues: list[GateIssue] = []
    if (
        compute_fact_set_hash(
            fact_set.facts,
            metric_facts=fact_set.metric_facts,
            issues=fact_set.issues,
            pending_confirmations=fact_set.pending_confirmations,
            period_roles=fact_set.period_roles,
        )
        != fact_set.fact_set_hash
    ):
        issues.append(GateIssue(code="fact_set_hash_mismatch", message="FactSet 哈希不一致。"))

    domains = selected_domains or (REQUIRED_DOMAINS if report_type == "comprehensive" else ())
    facts_by_domain: dict[str, list] = defaultdict(list)
    for fact in fact_set.facts:
        if fact.period_role == "current":
            facts_by_domain[fact.domain].append(fact)

    selected = set(domains)
    for fact_set_issue in fact_set.issues:
        if fact_set_issue.domains and not selected.intersection(fact_set_issue.domains):
            continue
        issues.append(
            GateIssue(
                code=fact_set_issue.code,
                message=fact_set_issue.message,
                domains=fact_set_issue.domains,
                blocking=not fact_set_issue.period_roles
                or "current" in fact_set_issue.period_roles,
            )
        )
    if fact_set.pending_confirmations:
        issues.append(
            GateIssue(
                code="pending_confirmation",
                message="；".join(fact_set.pending_confirmations),
            )
        )
    for domain in domains:
        domain_facts = facts_by_domain.get(domain, [])
        if not domain_facts:
            issues.append(
                GateIssue(
                    code="domain_unavailable",
                    message=f"业务域 {domain} 没有已确认事实。",
                    domains=(domain,),
                )
            )
            continue
        blocking = sorted(
            {
                fact.coverage
                for fact in domain_facts
                if fact.coverage in {"missing", "conflict", "unconfirmed"}
            }
        )
        if blocking:
            issues.append(
                GateIssue(
                    code="domain_coverage_blocked",
                    message=f"业务域 {domain} 覆盖状态不合格: {', '.join(blocking)}。",
                    domains=(domain,),
                )
            )

    available_roles = {
        fact.period_role
        for fact in fact_set.facts
        if fact.domain in selected and fact.coverage == "complete"
    }
    missing_comparison_roles = tuple(role for role in ("yoy", "mom") if role not in available_roles)
    if missing_comparison_roles:
        issues.append(
            GateIssue(
                code="comparison_period_unavailable",
                message=(
                    "缺少可用对比期事实："
                    + "、".join(
                        "同比" if role == "yoy" else "环比" for role in missing_comparison_roles
                    )
                    + "；正式报告保留本期分析并披露该限制。"
                ),
                domains=tuple(domains),
                blocking=False,
            )
        )

    incomplete_evidence_domains = sorted(
        {
            fact.domain
            for fact in fact_set.facts
            if fact.domain in selected
            and (
                fact.evidence.schema_hash is None
                or fact.evidence.sql_hash is None
                or fact.evidence.file_hash is None
                or not fact.evidence.references
            )
        }
    )
    if incomplete_evidence_domains:
        issues.append(
            GateIssue(
                code="fact_evidence_incomplete",
                message="正式发布事实缺少 Schema、SQL、文件哈希或引用。",
                domains=tuple(incomplete_evidence_domains),
            )
        )

    inconsistent_unit_domains = sorted(
        {
            domain
            for (domain, _metric), units in _metric_units(fact_set).items()
            if domain in selected and len(units) > 1
        }
    )
    if inconsistent_unit_domains:
        issues.append(
            GateIssue(
                code="normalized_unit_mismatch",
                message="同一指标包含不一致的规范单位。",
                domains=tuple(inconsistent_unit_domains),
            )
        )

    # 收入、预算和全成本必须在共同期间与共同组织粒度上才允许形成综合效益结论。
    common_domains = ("income", "budget", "full_cost")
    if all(facts_by_domain.get(item) for item in common_domains):
        periods = [{fact.period for fact in facts_by_domain[item]} for item in common_domains]
        grains = [{fact.grain for fact in facts_by_domain[item]} for item in common_domains]
        if len({frozenset(item) for item in periods}) != 1:
            issues.append(
                GateIssue(
                    code="common_period_mismatch",
                    message="收入、预算和全成本没有共同期间。",
                    domains=common_domains,
                )
            )
        if len({frozenset(item) for item in grains}) != 1:
            issues.append(
                GateIssue(
                    code="common_grain_mismatch",
                    message="收入、预算和全成本没有共同粒度。",
                    domains=common_domains,
                )
            )

    ids = fact_set.all_fact_ids
    metric_ids = {fact.fact_id for fact in fact_set.metric_facts if fact.publishable}
    if set(referenced_fact_ids) - ids or set(chart_fact_ids) - ids:
        issues.append(
            GateIssue(code="fact_reference_unknown", message="正文或图表引用了未知事实。")
        )
    if referenced_fact_ids and chart_fact_ids and set(chart_fact_ids) - set(referenced_fact_ids):
        issues.append(
            GateIssue(code="fact_reference_mismatch", message="图表事实未同时绑定正文事实引用。")
        )
    if not referenced_fact_ids:
        issues.append(
            GateIssue(code="fact_reference_missing", message="正文没有绑定服务端可复算业务事实。")
        )
    elif set(referenced_fact_ids) - metric_ids:
        issues.append(
            GateIssue(
                code="fact_reference_not_publishable",
                message="正文只能引用服务端生成的可展示 MetricFact。",
            )
        )

    return PublicationGateResult(
        reportType=report_type,
        formalReleaseAllowed=not any(issue.blocking for issue in issues),
        factSetHash=fact_set.fact_set_hash,
        issues=tuple(issues),
    )


def _metric_units(fact_set: HospitalOperationFactSet) -> dict[tuple[str, str], set[str]]:
    units: dict[tuple[str, str], set[str]] = defaultdict(set)
    for fact in fact_set.facts:
        units[(fact.domain, fact.metric)].add(fact.normalized_unit)
    return units
