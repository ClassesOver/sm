"""Select frozen metric identities by declared use, never by display name."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DOMAIN_METRIC_PURPOSES = {
    "income": ("收入多维分析",),
    "workload": ("工作量分析",),
    "budget": ("预算或预实对比",),
    "full_cost": ("成本多维分析",),
}


@dataclass(frozen=True)
class MetricUsageSelection:
    metrics: tuple[Mapping[str, Any], ...]
    # None is a historical profile without a purpose policy; an empty set is no match.
    allowed_field_refs: frozenset[str] | None
    warnings: tuple[str, ...] = ()


def select_metrics_by_usage(
    metrics: Sequence[Mapping[str, Any]], *, domain: str, purposes: Sequence[str] = (),
) -> MetricUsageSelection:
    configured = {metric.get("purpose") for metric in metrics if metric.get("purpose")}
    if not configured:
        return MetricUsageSelection(tuple(metrics), None)
    requested = tuple(purposes) or DOMAIN_METRIC_PURPOSES.get(domain, ())
    if not requested or set(requested) - configured:
        return MetricUsageSelection((), frozenset(), (
            "指标用途未明确或未登记，未回退到其他用途的指标；需明确本分析用途后补齐事实。",
        ))
    selected = tuple(metric for metric in metrics if metric.get("purpose") in requested)
    refs = frozenset(str(metric["fieldRef"]).casefold() for metric in selected if metric.get("fieldRef"))
    return MetricUsageSelection(selected, refs)


def usage_schema_candidates(
    schemas: Sequence[Mapping[str, Any]], metrics: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep dimensions and raw schema; narrow only the planner's measure candidates."""
    if not any(metric.get("purpose") for metric in metrics):
        return [dict(schema) for schema in schemas]
    allowed = {str(metric["fieldRef"]).casefold() for metric in metrics
               if metric.get("purpose") and metric.get("fieldRef")}
    return [{**schema, "measureSemantics": [
        semantic for semantic in schema.get("measureSemantics", ())
        if str(semantic.get("fieldRef", "")).casefold() in allowed
    ]} for schema in schemas]
