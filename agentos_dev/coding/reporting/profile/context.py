from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field

from ..contract import SourceSchemaSnapshot
from ..data_source.models import DataShape
from ..models import ReportingError
from .models import EffectiveReportingProfile, ProfileModel, parse_field_ref

MAX_OUTLINE_CONTEXT_BYTES = 256 * 1024


class Capability(ProfileModel):
    code: str = Field(min_length=1, max_length=128)
    kind: Literal["dimension", "metric", "reconciliation", "section"]
    available: bool
    reasons: tuple[str, ...] = Field(default=(), max_length=20)


class CapabilitySet(ProfileModel):
    effective_profile_hash: str = Field(alias="effectiveProfileHash", pattern=r"^[0-9a-f]{64}$")
    capabilities: tuple[Capability, ...] = Field(max_length=2_000)

    def by_code(self) -> dict[str, Capability]:
        return {item.code: item for item in self.capabilities}


class ReconciliationShape(ProfileModel):
    code: str = Field(min_length=1, max_length=128)
    status: Literal["completed", "unavailable"]
    left_metric: str = Field(alias="leftMetric", min_length=1, max_length=128)
    right_metric: str = Field(alias="rightMetric", min_length=1, max_length=128)
    grain: tuple[str, ...] = Field(min_length=1, max_length=20)
    left_total: str | None = Field(default=None, alias="leftTotal")
    right_total: str | None = Field(default=None, alias="rightTotal")
    difference: str | None = None
    difference_rate: float | None = Field(default=None, alias="differenceRate")
    common_key_count: int = Field(default=0, alias="commonKeyCount", ge=0)
    left_only_key_count: int = Field(default=0, alias="leftOnlyKeyCount", ge=0)
    right_only_key_count: int = Field(default=0, alias="rightOnlyKeyCount", ge=0)
    zero_denominator_count: int = Field(default=0, alias="zeroDenominatorCount", ge=0)
    exceeds_tolerance: bool | None = Field(default=None, alias="exceedsTolerance")
    issues: tuple[str, ...] = Field(default=(), max_length=50)


def resolve_capabilities(
    profile: EffectiveReportingProfile,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    data_shapes: tuple[DataShape, ...],
) -> CapabilitySet:
    fields = {
        f"{table.source_id}.{table.database.lower()}.{table.name.lower()}.{column.name.lower()}"
        for snapshot in snapshots
        for table in snapshot.tables
        for column in table.columns
    }
    period_rows = {
        f"{shape.source_id}.{table.database.lower()}.{table.table.lower()}": table.period_row_count
        for shape in data_shapes
        for table in shape.tables
    }
    values: list[Capability] = []
    availability: dict[str, bool] = {}
    reasons: dict[str, tuple[str, ...]] = {}

    for dimension in profile.dimensions:
        per_ref = [
            _missing_fields((field_ref,), fields, period_rows) for field_ref in dimension.field_refs
        ]
        available = any(not item for item in per_ref)
        missing = () if available else tuple(reason for item in per_ref for reason in item)
        availability[dimension.code] = available
        reasons[dimension.code] = missing
        values.append(
            Capability(
                code=dimension.code,
                kind="dimension",
                available=available,
                reasons=missing,
            )
        )

    pending = {item.code: item for item in profile.metrics}
    while pending:
        progressed = False
        for code, metric in tuple(pending.items()):
            if metric.aggregation == "ratio":
                dependencies = (metric.numerator_metric or "", metric.denominator_metric or "")
                if any(item in pending for item in dependencies):
                    continue
                missing = tuple(item for item in dependencies if not availability.get(item, False))
                metric_reasons = tuple(f"依赖 capability 不可用: {item}" for item in missing)
            else:
                assert metric.field_ref is not None
                metric_reasons = _missing_fields((metric.field_ref,), fields, period_rows)
            available = not metric_reasons
            availability[code] = available
            reasons[code] = metric_reasons
            values.append(
                Capability(
                    code=code,
                    kind="metric",
                    available=available,
                    reasons=metric_reasons,
                )
            )
            pending.pop(code)
            progressed = True
        if not progressed:
            for code in sorted(pending):
                message = ("指标依赖存在循环。",)
                availability[code] = False
                reasons[code] = message
                values.append(
                    Capability(code=code, kind="metric", available=False, reasons=message)
                )
            break

    for rule in profile.reconciliations:
        rule_dependencies = (rule.left_metric, rule.right_metric, *rule.grain)
        missing = tuple(item for item in rule_dependencies if not availability.get(item, False))
        rule_reasons = [f"依赖 capability 不可用: {item}" for item in missing]
        if not rule_reasons:
            metric_map = {item.code: item for item in profile.metrics}
            dimension_map = {item.code: item for item in profile.dimensions}
            for metric_code in (rule.left_metric, rule.right_metric):
                metric_ref = parse_field_ref(metric_map[metric_code].field_ref or "")
                for dimension_code in rule.grain:
                    matches = [
                        field_ref
                        for field_ref in dimension_map[dimension_code].field_refs
                        if (parsed := parse_field_ref(field_ref)).source_id == metric_ref.source_id
                        and parsed.qualified_table == metric_ref.qualified_table
                        and not _missing_fields((field_ref,), fields, period_rows)
                    ]
                    if len(matches) != 1:
                        rule_reasons.append(
                            f"共同粒度 {dimension_code} 在指标表中缺少唯一有效映射。"
                        )
        rule_reason_values = tuple(rule_reasons)
        available = not rule_reason_values
        availability[rule.code] = available
        reasons[rule.code] = rule_reason_values
        values.append(
            Capability(
                code=rule.code,
                kind="reconciliation",
                available=available,
                reasons=rule_reason_values,
            )
        )

    for section in profile.sections:
        missing = tuple(
            item for item in section.required_capabilities if not availability.get(item, False)
        )
        section_reasons = tuple(f"依赖 capability 不可用: {item}" for item in missing)
        values.append(
            Capability(
                code=section.code,
                kind="section",
                available=not section_reasons,
                reasons=section_reasons,
            )
        )
    return CapabilitySet(
        effectiveProfileHash=profile.effective_profile_hash,
        capabilities=tuple(values),
    )


def build_outline_shape_view(
    profile: EffectiveReportingProfile,
    capabilities: CapabilitySet,
    snapshots: tuple[SourceSchemaSnapshot, ...],
    data_shapes: tuple[DataShape, ...],
    reconciliations: tuple[ReconciliationShape, ...],
) -> dict[str, Any]:
    shape_map = {
        (shape.source_id, table.database.lower(), table.table.lower()): table
        for shape in data_shapes
        for table in shape.tables
    }
    relevant = _relevant_fields(profile)
    tables: list[dict[str, Any]] = []
    remaining_columns = 500
    for snapshot in snapshots:
        for table in snapshot.tables:
            shape = shape_map.get((table.source_id, table.database.lower(), table.name.lower()))
            selected = [
                column
                for column in table.columns
                if not relevant
                or f"{table.source_id}.{table.database.lower()}.{table.name.lower()}.{column.name.lower()}"
                in relevant
            ][:remaining_columns]
            remaining_columns -= len(selected)
            shape_columns = {item.name.lower(): item for item in shape.columns} if shape else {}
            tables.append(
                {
                    "sourceId": table.source_id,
                    "table": f"{table.database}.{table.name}",
                    "description": table.description,
                    "periodRowCount": shape.period_row_count if shape else 0,
                    "periodGranularity": shape.period_granularity if shape else None,
                    "periodCoverage": list(shape.period_coverage) if shape else [],
                    "missingPeriods": list(shape.missing_periods) if shape else [],
                    "columns": [
                        {
                            "name": column.name,
                            "dataType": column.data_type,
                            "description": column.description,
                            "nullRate": (
                                shape_columns[column.name.lower()].null_rate
                                if column.name.lower() in shape_columns
                                else None
                            ),
                        }
                        for column in selected
                    ],
                    "omittedColumnCount": max(0, len(table.columns) - len(selected)),
                }
            )
    capability_values = [
        item.model_dump(mode="json", by_alias=True) for item in capabilities.capabilities
    ]
    terms = [
        item.model_dump(mode="json", by_alias=True)
        for snapshot in snapshots
        for item in snapshot.terms
    ]
    result = {
        "profile": profile.model_dump(mode="json", by_alias=True),
        "capabilities": capability_values,
        "tables": tables,
        "terms": terms[:1_000],
        "omittedTermCount": max(0, len(terms) - 1_000),
        "reconciliations": [
            item.model_dump(mode="json", by_alias=True) for item in reconciliations
        ],
    }
    if (
        len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
        > MAX_OUTLINE_CONTEXT_BYTES
    ):
        raise ReportingError("report_outline_context_too_large", "提纲上下文超过大小限制。")
    return result


def _missing_fields(
    field_refs: tuple[str, ...],
    fields: set[str],
    period_rows: Mapping[str, int],
) -> tuple[str, ...]:
    result: list[str] = []
    for value in field_refs:
        parsed = parse_field_ref(value)
        normalized = f"{parsed.source_id}.{parsed.database}.{parsed.table}.{parsed.column}"
        if normalized not in fields:
            result.append(f"字段不在结构快照内: {value}")
        elif period_rows.get(f"{parsed.source_id}.{parsed.database}.{parsed.table}", 0) == 0:
            result.append(f"报告期间没有数据: {parsed.source_id}.{parsed.qualified_table}")
    return tuple(result)


def _relevant_fields(profile: EffectiveReportingProfile) -> set[str]:
    values = {value.lower() for dimension in profile.dimensions for value in dimension.field_refs}
    values.update(
        metric.field_ref.lower() for metric in profile.metrics if metric.field_ref is not None
    )
    return values
