from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from ..data_source.period import PeriodRole
from ..models import ReportingError
from .factset import FactEvidence, FactSetBuilder, FactSetIssue, HospitalOperationFactSet
from .metrics import build_metric_facts
from .profiles import HospitalOperationProfile
from .reconciliation import reconcile_series


@dataclass(frozen=True)
class DatasetFactInput:
    dataset_id: str
    requirement_id: str
    source_id: str
    table: str
    period_column: str
    grain: tuple[str, ...]
    rows: Sequence[Mapping[str, Any]]
    schema_hash: str
    sql_hash: str
    file_hash: str
    reference: str
    columns: tuple[str, ...] = ()
    row_preserving: bool = False
    period_roles: tuple[PeriodRole, ...] = ("current",)
    query_window_id: str = "current"

    def __post_init__(self) -> None:
        if not self.period_roles or len(self.period_roles) != len(set(self.period_roles)):
            raise ValueError("数据集期间角色不能为空或重复")
        if not self.query_window_id:
            raise ValueError("数据集 queryWindowId 不能为空")


def build_fact_set_from_datasets(
    datasets: Sequence[DatasetFactInput],
    *,
    profile: HospitalOperationProfile,
    period_start: date,
    period_end: date,
    generated_at: str,
    issues: Sequence[FactSetIssue] = (),
) -> HospitalOperationFactSet:
    """把已审核查询结果确定性冻结为业务事实，不允许模型解释列或换算金额。"""
    ordered_roles: tuple[PeriodRole, ...] = ("current", "yoy", "mom")
    period_roles: tuple[PeriodRole, ...] = tuple(
        role
        for role in ordered_roles
        if role == "current" or any(role in dataset.period_roles for dataset in datasets)
    )
    builder = FactSetBuilder(
        hospital=profile.hospital,
        period_start=period_start,
        period_end=period_end,
        generated_at=generated_at,
        pending_confirmations=profile.pending_confirmations,
        period_roles=period_roles,
    )
    for issue in issues:
        builder.add_issue(**issue.model_dump(mode="python"))
    bindings = {
        (
            binding.field_ref.rsplit(".", 2)[-2].lower(),
            binding.field_ref.rsplit(".", 1)[-1].lower(),
        ): binding
        for binding in profile.bindings
    }
    for dataset in datasets:
        table_name = dataset.table.rsplit(".", 1)[-1].lower()
        governed_duplicate_table = any(
            rule.table_ref.rsplit(".", 1)[-1].lower() == table_name
            for rule in profile.duplicate_conflicts
        )
        # 项目重复冲突只能从原始行识别；一旦上游先做 SUM/MAX/DISTINCT，任何后置
        # 规则都无法恢复被合并的版本差异。受治理物理表因此必须携带查询审核签发的
        # row_preserving 身份，不能把“恰好没有发现重复”误当成“已经证明没有重复”。
        if governed_duplicate_table and not dataset.row_preserving:
            raise ReportingError(
                "hospital_operation_duplicate_probe_not_row_preserving",
                f"数据集 {dataset.dataset_id} 未保留重复冲突探测所需的原始行。",
            )
        table_bindings = {
            column: binding
            for (binding_table, column), binding in bindings.items()
            if binding_table == table_name
        }
        projected_columns = {item.lower() for item in dataset.columns} or {
            str(key).lower() for row in dataset.rows for key in row
        }
        # 有 Profile 绑定却一个物理指标列都未投影，说明 Profile、Schema 或 SQL 已经漂移。
        # 此时继续会把“映射失败”伪装成“业务无数据”，必须在进入成稿前失败关闭。
        if table_bindings and not set(table_bindings).intersection(projected_columns):
            raise ReportingError(
                "hospital_operation_fact_binding_unresolved",
                f"数据集 {dataset.dataset_id} 未投影 Profile 已确认的业务事实字段。",
            )
        if not table_bindings:
            builder.add_issue(
                code="fact_binding_unavailable",
                status="unconfirmed",
                message=f"数据表 {table_name} 尚无已确认的医院运营 Fact 绑定。",
                dataset_ids=(dataset.dataset_id,),
            )
            continue
        duplicate_annotations = _duplicate_row_annotations(dataset, profile=profile)
        evidence = FactEvidence(
            datasetId=dataset.dataset_id,
            schemaHash=dataset.schema_hash,
            sqlHash=dataset.sql_hash,
            fileHash=dataset.file_hash,
            references=(dataset.reference,),
        )
        for row_index, row in enumerate(dataset.rows):
            normalized_row = {str(key).lower(): value for key, value in row.items()}
            period_value = normalized_row.get(dataset.period_column.lower())
            if period_value is None:
                raise ReportingError(
                    "hospital_operation_period_missing", "FactSet 数据缺少已审核期间字段。"
                )
            period = _normalize_period(period_value, profile.period_format(dataset.table))
            for (binding_table, column), binding in bindings.items():
                if binding_table != table_name or column not in normalized_row:
                    continue
                raw_value = normalized_row[column]
                if raw_value is None or raw_value == "":
                    continue
                coverage: Literal["complete", "zero_placeholder", "conflict", "unconfirmed"] = (
                    "complete"
                )
                conflicts: tuple[str, ...] = ()
                pending_confirmations: tuple[str, ...] = ()
                if reason := profile.unconfirmed_metrics.get(binding.metric):
                    coverage = "unconfirmed"
                    pending_confirmations = (reason,)
                duplicate = duplicate_annotations.get(row_index)
                if duplicate is not None:
                    duplicate_status, duplicate_message = duplicate
                    coverage = duplicate_status
                    if duplicate_status == "conflict":
                        conflicts = (duplicate_message,)
                        pending_confirmations = ()
                    else:
                        pending_confirmations = tuple(
                            dict.fromkeys((*pending_confirmations, duplicate_message))
                        )
                if period in profile.zero_placeholder_periods.get(binding.metric, ()):
                    if _is_zero(raw_value):
                        coverage = "zero_placeholder"
                    else:
                        coverage = "conflict"
                        conflicts = ("已确认零值占位期间出现非零值，必须重新确认数据覆盖。",)
                for period_role in dataset.period_roles:
                    fact = builder.add(
                        fact_id=_fact_id(
                            dataset, row_index, binding.domain, binding.metric, period_role
                        ),
                        domain=binding.domain,
                        metric=binding.metric,
                        period=period,
                        period_role=period_role,
                        value=raw_value,
                        raw_unit=binding.raw_unit,
                        evidence=evidence,
                        campus=profile.canonical_campus(str(normalized_row["area"]))
                        if normalized_row.get("area") is not None
                        and normalized_row.get("area") != ""
                        else None,
                        department=_optional_text(normalized_row, "department", "dept_name"),
                        accounting_unit=_optional_text(
                            normalized_row,
                            "detail_analytic_unit",
                            "stlevel_analytic_unit",
                            "accounting_unit",
                        ),
                        grain=dataset.grain,
                        formula=column if dataset.row_preserving else f"SUM({column})",
                        coverage=coverage,
                        conflicts=conflicts,
                        pending_confirmations=pending_confirmations,
                        parent_metric=binding.parent_metric,
                        is_subset=binding.parent_metric is not None,
                    )
                    if conflicts:
                        builder.add_issue(
                            code="zero_placeholder_value_conflict",
                            status="conflict",
                            message=conflicts[0],
                            domains=(binding.domain,),
                            periods=(period,),
                            period_roles=(period_role,),
                            dataset_ids=(dataset.dataset_id,),
                            fact_ids=(fact.fact_id,),
                        )
        _add_duplicate_issues(builder, dataset, profile=profile, bindings=bindings)
    _add_reconciliation_issues(builder, profile=profile)
    base_fact_set = builder.build()
    return builder.build(metric_facts=build_metric_facts(base_fact_set))


def _optional_text(row: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def _duplicate_row_annotations(
    dataset: DatasetFactInput,
    *,
    profile: HospitalOperationProfile,
) -> dict[int, tuple[Literal["conflict", "unconfirmed"], str]]:
    table_name = dataset.table.rsplit(".", 1)[-1].lower()
    rows = tuple({str(key).lower(): value for key, value in row.items()} for row in dataset.rows)
    annotations: dict[int, tuple[Literal["conflict", "unconfirmed"], str]] = {}
    for rule in profile.duplicate_conflicts:
        if rule.table_ref.rsplit(".", 1)[-1].lower() != table_name or not rows:
            continue
        identity_fields = tuple(item.lower() for item in rule.identity_fields)
        value_fields = tuple(item.lower() for item in rule.value_fields)
        columns = set().union(*(row.keys() for row in rows))
        if not set(identity_fields).issubset(columns) or not set(value_fields).intersection(
            columns
        ):
            continue
        grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for row_index, row in enumerate(rows):
            grouped[tuple(str(row.get(field, "")) for field in identity_fields)].append(row_index)
        for indexes in grouped.values():
            if len(indexes) < 2:
                continue
            values_differ = any(
                len({str(rows[index].get(field, "")) for index in indexes}) > 1
                for field in value_fields
                if field in columns
            )
            annotation: tuple[Literal["conflict", "unconfirmed"], str] = (
                (
                    "conflict",
                    "同一项目存在不同金额且没有版本字段，禁止 SUM、MAX 或自行去重。",
                )
                if values_differ
                else (
                    "unconfirmed",
                    "同一项目存在无版本重复行，金额相同也不能自行去重。",
                )
            )
            for row_index in indexes:
                annotations[row_index] = annotation
    return annotations


def _fact_id(
    dataset: DatasetFactInput,
    row_index: int,
    domain: str,
    metric: str,
    period_role: PeriodRole = "current",
) -> str:
    identity = (
        f"{dataset.dataset_id}:{dataset.requirement_id}:{dataset.query_window_id}:"
        f"{period_role}:{row_index}:{domain}:{metric}"
    )
    return "fact-" + hashlib.sha256(identity.encode()).hexdigest()[:32]


def _normalize_period(
    value: Any,
    period_format: Literal["year", "year_month", "date", "day_month_year"],
) -> str:
    if isinstance(value, datetime | date):
        return value.strftime("%Y-%m")
    normalized = str(value).strip()
    if period_format == "year" and re.fullmatch(r"\d{4}", normalized):
        return normalized
    if period_format in {"year_month", "date"}:
        match = re.fullmatch(r"(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?", normalized)
        if match is not None and 1 <= int(match.group(2)) <= 12:
            return f"{match.group(1)}-{int(match.group(2)):02d}"
    if period_format == "day_month_year":
        match = re.fullmatch(r"\d{1,2}/(\d{1,2})/(\d{4})", normalized)
        if match is not None and 1 <= int(match.group(1)) <= 12:
            return f"{match.group(2)}-{int(match.group(1)):02d}"
    raise ReportingError(
        "hospital_operation_period_invalid", "FactSet 数据包含不符合 Profile 的期间值。"
    )


def _is_zero(value: Any) -> bool:
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _add_duplicate_issues(
    builder: FactSetBuilder,
    dataset: DatasetFactInput,
    *,
    profile: HospitalOperationProfile,
    bindings: Mapping[tuple[str, str], Any],
) -> None:
    table_name = dataset.table.rsplit(".", 1)[-1].lower()
    normalized_rows = tuple(
        {str(key).lower(): value for key, value in row.items()} for row in dataset.rows
    )
    for rule in profile.duplicate_conflicts:
        if rule.table_ref.rsplit(".", 1)[-1].lower() != table_name or not normalized_rows:
            continue
        identity_fields = tuple(item.lower() for item in rule.identity_fields)
        value_fields = tuple(item.lower() for item in rule.value_fields)
        columns = set().union(*(row.keys() for row in normalized_rows))
        if not set(identity_fields).issubset(columns) or not set(value_fields).intersection(
            columns
        ):
            builder.add_issue(
                code=f"{rule.code}_unavailable",
                status="unconfirmed",
                message="项目预算数据集未保留重复核验所需的项目身份字段和金额字段。",
                domains=(rule.domain,),
                dataset_ids=(dataset.dataset_id,),
            )
            continue

        grouped: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for row_index, row in enumerate(normalized_rows):
            grouped[tuple(str(row.get(field, "")) for field in identity_fields)].append(row_index)
        duplicate_groups = {key: indexes for key, indexes in grouped.items() if len(indexes) > 1}
        if not duplicate_groups:
            continue

        conflicting: list[tuple[tuple[str, ...], list[int]]] = []
        unconfirmed: list[tuple[tuple[str, ...], list[int]]] = []
        for identity, indexes in duplicate_groups.items():
            values_differ = any(
                len({str(normalized_rows[index].get(field, "")) for index in indexes}) > 1
                for field in value_fields
                if field in columns
            )
            (conflicting if values_differ else unconfirmed).append((identity, indexes))

        # 没有版本字段时，即使重复行金额相同也不能自行选一行或聚合；金额不同时升级为冲突。
        status: Literal["conflict", "unconfirmed"]
        for status, groups in (("conflict", conflicting), ("unconfirmed", unconfirmed)):
            if not groups:
                continue
            row_indexes = {index for _identity, indexes in groups for index in indexes}
            fact_ids = tuple(
                _fact_id(dataset, row_index, binding.domain, binding.metric, period_role)
                for period_role in dataset.period_roles
                for row_index in sorted(row_indexes)
                for (binding_table, column), binding in bindings.items()
                if binding_table == table_name
                and column in value_fields
                and normalized_rows[row_index].get(column) not in {None, ""}
            )[:10_000]
            builder.add_issue(
                code=f"{rule.code}_{status}",
                status=status,
                message=(
                    f"项目预算存在 {len(groups)} 组重复项目且金额不一致，禁止 SUM、MAX 或自行去重。"
                    if status == "conflict"
                    else f"项目预算存在 {len(groups)} 组无版本重复项目，金额相同也不能自行去重。"
                ),
                domains=(rule.domain,),
                periods=tuple(
                    sorted(
                        {
                            _normalize_period(
                                normalized_rows[index].get(dataset.period_column.lower(), ""),
                                profile.period_format(dataset.table),
                            )
                            for index in row_indexes
                        }
                    )
                ),
                dataset_ids=(dataset.dataset_id,),
                period_roles=dataset.period_roles,
                fact_ids=fact_ids,
            )


def _add_reconciliation_issues(
    builder: FactSetBuilder, *, profile: HospitalOperationProfile
) -> None:
    # 对账只需要读取已逐条校验的基础事实；不要在最终冻结前构造完整 FactSet，
    # 否则大数据集会重复执行全量 hash/模型校验，并把中间对象误当成成稿输入。
    facts, _issues = builder.snapshot()
    values: dict[tuple[PeriodRole, str], dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )
    fact_ids: dict[tuple[PeriodRole, str], list[str]] = defaultdict(list)
    dataset_ids: dict[tuple[PeriodRole, str], set[str]] = defaultdict(set)
    for fact in facts:
        if fact.normalized_value is None:
            continue
        key = (fact.period_role, fact.metric)
        values[key][fact.period] += fact.normalized_value
        fact_ids[key].append(fact.fact_id)
        dataset_ids[key].add(fact.evidence.dataset_id)

    for period_role in ("current", "yoy", "mom"):
        if not any(role == period_role for role, _metric in values):
            continue
        for rule in profile.reconciliations:
            required_metrics = (rule.left_metric, *rule.right_metrics)
            known_fact_ids = tuple(
                fact_id
                for metric in required_metrics
                for fact_id in fact_ids.get((period_role, metric), ())
            )[:10_000]
            known_dataset_ids = tuple(
                sorted(
                    {
                        dataset_id
                        for metric in required_metrics
                        for dataset_id in dataset_ids.get((period_role, metric), set())
                    }
                )
            )
            if any(not values.get((period_role, metric)) for metric in required_metrics):
                missing_metrics = [
                    metric for metric in required_metrics if not values.get((period_role, metric))
                ]
                builder.add_issue(
                    code=f"{rule.code}_unavailable",
                    status="unconfirmed",
                    message=f"月度勾稽缺少指标: {', '.join(missing_metrics)}。",
                    domains=rule.domains,
                    period_roles=(period_role,),
                    dataset_ids=known_dataset_ids,
                    fact_ids=known_fact_ids,
                )
                continue
            right_periods = set().union(
                *(values[(period_role, metric)] for metric in rule.right_metrics)
            )
            right = {
                period: sum(
                    (
                        values[(period_role, metric)].get(period, Decimal("0"))
                        for metric in rule.right_metrics
                    ),
                    Decimal("0"),
                )
                for period in right_periods
            }
            result = reconcile_series(
                rule.code,
                values[(period_role, rule.left_metric)],
                right,
                absolute_tolerance=Decimal(rule.absolute_tolerance),
            )
            if result.status == "complete":
                continue
            builder.add_issue(
                code=rule.code,
                status="conflict" if result.status == "conflict" else "unconfirmed",
                message=_bounded_issue_message(result.issues),
                domains=rule.domains,
                periods=tuple(
                    point.period for point in result.points if point.status == "conflict"
                ),
                period_roles=(period_role,),
                dataset_ids=known_dataset_ids,
                fact_ids=known_fact_ids,
            )


def _bounded_issue_message(issues: tuple[str, ...]) -> str:
    if not issues:
        return "月度勾稽不可用。"
    selected: list[str] = []
    size = 0
    for issue in issues:
        if size + len(issue) + 1 > 1_900:
            break
        selected.append(issue)
        size += len(issue) + 1
    omitted = len(issues) - len(selected)
    suffix = f"；另有 {omitted} 项未展开。" if omitted else ""
    return "；".join(selected) + suffix
