from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from ..data_source.period import PeriodRole
from .factset import (
    MAX_METRIC_INPUT_FACT_COUNT,
    HospitalOperationFact,
    HospitalOperationFactSet,
    HospitalOperationMetricFact,
    MetricFormula,
    MetricOperation,
)

_SUPPORT_CHUNK_SIZE = 10_000


def build_metric_facts(
    fact_set: HospitalOperationFactSet,
) -> tuple[HospitalOperationMetricFact, ...]:
    """生成医院级月度、累计和共同期间指标；任何阻断输入都不能进入派生层。"""
    blocked_fact_ids = {
        fact_id
        for issue in fact_set.issues
        if issue.status == "conflict"
        for fact_id in issue.fact_ids
    }
    # issue.factIds 为有界审计引用，不能用其截断结果决定整个月是否可展示。
    # 冲突 issue 的 domains+periods 才是派生指标的阻断范围；即使冲突行超过引用上限，
    # 同域同月的剩余事实也不能被拼成看似完整的 MetricFact。
    blocked_groups = {
        (period_role, domain, period)
        for issue in fact_set.issues
        if issue.status == "conflict"
        for period_role in (issue.period_roles or fact_set.period_roles)
        for domain in issue.domains
        for period in issue.periods
    }
    grouped: dict[tuple[PeriodRole, str, str, str], list[HospitalOperationFact]] = defaultdict(list)
    for fact in fact_set.facts:
        grouped[(fact.period_role, fact.domain, fact.metric, fact.period)].append(fact)

    result: list[HospitalOperationMetricFact] = []
    values: dict[str, tuple[Decimal, str]] = {
        fact.fact_id: (fact.normalized_value, fact.normalized_unit)
        for fact in fact_set.facts
        if fact.normalized_value is not None
    }
    citations: dict[str, tuple[str, ...]] = {
        fact.fact_id: tuple(sorted(set(fact.evidence.references))) for fact in fact_set.facts
    }

    monthly: dict[tuple[PeriodRole, str, str], dict[str, HospitalOperationMetricFact]] = (
        defaultdict(dict)
    )
    for (period_role, domain, metric, period), facts in sorted(grouped.items()):
        # 一个聚合组中只要存在冲突、待确认、缺失或零值占位，整组就不产生“可展示”指标；
        # 不能把其余正常行相加后伪装成完整月份。
        if any(
            fact.fact_id in blocked_fact_ids
            or (fact.period_role, fact.domain, fact.period) in blocked_groups
            or fact.coverage != "complete"
            or fact.normalized_value is None
            for fact in facts
        ):
            continue
        units = {fact.normalized_unit for fact in facts}
        if len(units) != 1:
            continue
        input_fact_ids = tuple(sorted(fact.fact_id for fact in facts))
        # 月度指标通常直接引用明细事实；当一个月的明细超过公式输入上限时，
        # 先由服务端生成不可发布的分块汇总事实，再由月度指标引用这些分块。
        # 这样既保持公式可复算，又不会把十万级明细 ID塞进报表模型或单个公式。
        if len(input_fact_ids) <= MAX_METRIC_INPUT_FACT_COUNT:
            metric_fact = _make_metric_fact(
                hospital=fact_set.hospital,
                period_role=period_role,
                domain=domain,
                metric=metric,
                scope="month",
                periods=(period,),
                operation="sum",
                left_fact_ids=input_fact_ids,
                right_fact_ids=(),
                normalized_unit=next(iter(units)),
                values=values,
                citations=citations,
            )
            result.append(metric_fact)
            _register_metric(metric_fact, values=values, citations=citations)
        else:
            support_ids: list[str] = []
            for chunk_index, start in enumerate(range(0, len(input_fact_ids), _SUPPORT_CHUNK_SIZE)):
                chunk = input_fact_ids[start : start + _SUPPORT_CHUNK_SIZE]
                support_fact = _make_metric_fact(
                    hospital=fact_set.hospital,
                    period_role=period_role,
                    domain=domain,
                    metric=metric,
                    scope="support",
                    periods=(period,),
                    operation="sum",
                    left_fact_ids=chunk,
                    right_fact_ids=(),
                    normalized_unit=next(iter(units)),
                    values=values,
                    citations=citations,
                    publishable=False,
                    identity_suffix=f"chunk-{chunk_index}",
                )
                result.append(support_fact)
                _register_metric(support_fact, values=values, citations=citations)
                support_ids.append(support_fact.fact_id)
            metric_fact = _make_metric_fact(
                hospital=fact_set.hospital,
                period_role=period_role,
                domain=domain,
                metric=metric,
                scope="month",
                periods=(period,),
                operation="sum",
                left_fact_ids=tuple(support_ids),
                right_fact_ids=(),
                normalized_unit=next(iter(units)),
                values=values,
                citations=citations,
            )
            result.append(metric_fact)
            _register_metric(metric_fact, values=values, citations=citations)
        monthly[(period_role, domain, metric)][period] = metric_fact

    cumulative: dict[tuple[PeriodRole, str, str], HospitalOperationMetricFact] = {}
    for (period_role, domain, metric), by_period in sorted(monthly.items()):
        periods = tuple(sorted(by_period))
        if not periods:
            continue
        inputs = tuple(by_period[period].fact_id for period in periods)
        metric_fact = _make_metric_fact(
            hospital=fact_set.hospital,
            period_role=period_role,
            domain=domain,
            metric=metric,
            scope="report_period",
            periods=periods,
            operation="sum",
            left_fact_ids=inputs,
            right_fact_ids=(),
            normalized_unit=by_period[periods[0]].normalized_unit,
            values=values,
            citations=citations,
        )
        result.append(metric_fact)
        _register_metric(metric_fact, values=values, citations=citations)
        cumulative[(period_role, domain, metric)] = metric_fact

    _add_common_period_metrics(
        result,
        monthly=monthly,
        hospital=fact_set.hospital,
        values=values,
        citations=citations,
    )
    return tuple(result)


def _add_common_period_metrics(
    result: list[HospitalOperationMetricFact],
    *,
    monthly: dict[tuple[PeriodRole, str, str], dict[str, HospitalOperationMetricFact]],
    hospital: str,
    values: dict[str, tuple[Decimal, str]],
    citations: dict[str, tuple[str, ...]],
) -> None:
    for period_role in ("current", "yoy", "mom"):
        income = monthly.get((period_role, "income", "actual_medical_income"), {})
        cost = monthly.get((period_role, "full_cost", "total_cost"), {})
        common_periods = tuple(sorted(set(income).intersection(cost)))
        if common_periods:
            income_ids = tuple(income[period].fact_id for period in common_periods)
            cost_ids = tuple(cost[period].fact_id for period in common_periods)
            operating_result = _make_metric_fact(
                hospital=hospital,
                period_role=period_role,
                domain="cross_domain",
                metric="operating_result",
                scope="common_period",
                periods=common_periods,
                operation="difference",
                left_fact_ids=income_ids,
                right_fact_ids=cost_ids,
                normalized_unit="元",
                values=values,
                citations=citations,
            )
            result.append(operating_result)
            _register_metric(operating_result, values=values, citations=citations)

            cost_income_ratio = _make_metric_fact(
                hospital=hospital,
                period_role=period_role,
                domain="cross_domain",
                metric="cost_income_ratio",
                scope="common_period",
                periods=common_periods,
                operation="ratio_percent",
                left_fact_ids=cost_ids,
                right_fact_ids=income_ids,
                normalized_unit="%",
                values=values,
                citations=citations,
            )
            result.append(cost_income_ratio)
            _register_metric(cost_income_ratio, values=values, citations=citations)

        budget = monthly.get((period_role, "budget", "budget_income"), {})
        budget_periods = tuple(sorted(set(income).intersection(budget)))
        if budget_periods:
            actual_ids = tuple(income[period].fact_id for period in budget_periods)
            budget_ids = tuple(budget[period].fact_id for period in budget_periods)
            if sum((values[fact_id][0] for fact_id in budget_ids), Decimal("0")) != 0:
                completion = _make_metric_fact(
                    hospital=hospital,
                    period_role=period_role,
                    domain="budget",
                    metric="income_budget_completion_rate",
                    scope="common_period",
                    periods=budget_periods,
                    operation="ratio_percent",
                    left_fact_ids=actual_ids,
                    right_fact_ids=budget_ids,
                    normalized_unit="%",
                    values=values,
                    citations=citations,
                )
                result.append(completion)
                _register_metric(completion, values=values, citations=citations)


def _make_metric_fact(
    *,
    hospital: str,
    period_role: PeriodRole,
    domain: str,
    metric: str,
    scope: Literal["month", "report_period", "common_period", "support"],
    periods: tuple[str, ...],
    operation: MetricOperation,
    left_fact_ids: tuple[str, ...],
    right_fact_ids: tuple[str, ...],
    normalized_unit: str,
    values: dict[str, tuple[Decimal, str]],
    citations: dict[str, tuple[str, ...]],
    publishable: bool = True,
    identity_suffix: str = "",
) -> HospitalOperationMetricFact:
    left = sum((values[fact_id][0] for fact_id in left_fact_ids), Decimal("0"))
    right = sum((values[fact_id][0] for fact_id in right_fact_ids), Decimal("0"))
    if operation == "sum":
        normalized_value = left
    elif operation == "difference":
        normalized_value = left - right
    elif operation == "ratio_percent":
        normalized_value = left / right * Decimal("100")
    else:  # pragma: no cover - 仅由本模块固定调用
        raise ValueError(f"未知 MetricFact operation: {operation}")
    input_fact_ids = (*left_fact_ids, *right_fact_ids)
    citation_ids = tuple(
        sorted({citation for fact_id in input_fact_ids for citation in citations[fact_id]})
    )
    display_factor, display_unit, display_scale = _display_spec(normalized_value, normalized_unit)
    display_value = (normalized_value / display_factor).quantize(
        Decimal(1).scaleb(-display_scale), rounding=ROUND_HALF_UP
    )
    identity = json.dumps(
        {
            "domain": domain,
            "periodRole": period_role,
            "metric": metric,
            "scope": scope,
            "periods": periods,
            "operation": operation,
            "leftFactIds": left_fact_ids,
            "rightFactIds": right_fact_ids,
            "identitySuffix": identity_suffix,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return HospitalOperationMetricFact(
        factId="metric-" + hashlib.sha256(identity.encode()).hexdigest()[:32],
        domain=domain,
        metric=metric,
        hospital=hospital,
        periodRole=period_role,
        scope=scope,
        periods=periods,
        coverage="complete",
        normalizedValue=normalized_value,
        normalizedUnit=normalized_unit,
        formula=MetricFormula(
            operation=operation,
            leftFactIds=left_fact_ids,
            rightFactIds=right_fact_ids,
        ),
        inputFactIds=input_fact_ids,
        citationIds=citation_ids,
        displayValue=display_value,
        displayUnit=display_unit,
        displayFactor=display_factor,
        displayScale=display_scale,
        displayText=f"{display_value:.{display_scale}f}{display_unit}",
        publishable=publishable,
    )


def _display_spec(value: Decimal, unit: str) -> tuple[Decimal, str, int]:
    if unit == "元":
        absolute = abs(value)
        if absolute >= Decimal("100000000"):
            return Decimal("100000000"), "亿元", 2
        if absolute >= Decimal("10000"):
            return Decimal("10000"), "万元", 2
        return Decimal("1"), "元", 2
    if unit == "%":
        return Decimal("1"), "%", 2
    if unit == "人次":
        return Decimal("1"), "人次", 0
    return Decimal("1"), unit, 2


def _register_metric(
    fact: HospitalOperationMetricFact,
    *,
    values: dict[str, tuple[Decimal, str]],
    citations: dict[str, tuple[str, ...]],
) -> None:
    values[fact.fact_id] = (fact.normalized_value, fact.normalized_unit)
    citations[fact.fact_id] = fact.citation_ids


__all__ = ["build_metric_facts"]
