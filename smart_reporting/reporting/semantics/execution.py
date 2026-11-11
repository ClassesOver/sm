"""执行登记SQL、复用不可变CSV存储，再从已核验快照计算精确结果。"""

import csv
import hashlib
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from agno.run import RunContext
from loguru import logger
from pydantic import TypeAdapter

from ...workspace import _thread
from ..data_source.starrocks import StarRocksDataSourceAdapter
from ..data_sources import DatasetHandle, ReportDatasetStore
from ..models import ReportingError
from ..trace.fact_index import _fact_id
from ..workflow.query_pipeline import ApprovedQuery, normalized_sql_hash
from .compiler import MetricQuery, MetricQueryPlan
from .models import (
    DataReadiness,
    DimensionValue,
    Identity,
    MetricResult,
    Period,
    ReadinessCheck,
    UnmatchedGroup,
)
from .readiness import ReadinessObservations, evaluate_data_readiness
from .snapshots import monthly_snapshot_values
from .values import dimension_values


@dataclass(frozen=True)
class MetricExecutionReceipt:
    results: tuple[MetricResult, ...]
    datasets: tuple[DatasetHandle, ...]
    readiness: tuple[DataReadiness, ...] = ()


class _BoundSource:
    def __init__(self, source, queries):
        self.source, self.config = source, source.config
        self.queries = {}
        for query in queries:
            previous = self.queries.get(query.sql)
            if previous is not None and previous.parameters != query.parameters:
                raise ReportingError("metric_parameter_conflict", "同一批SQL参数身份冲突。")
            self.queries[query.sql] = query

    async def materialize(self, sql, *, max_bytes=None):
        query = self.queries.get(sql)
        if query is None:
            raise ReportingError("metric_query_identity_invalid", "执行SQL与登记计划不一致。")
        return await self.source.materialize_bound(sql, {item.name: item.value for item in query.parameters}, max_bytes=max_bytes)


def _query_identity(query: MetricQuery, plan: MetricQueryPlan, calculation_id: str) -> str:
    body = {"request": plan.request.model_dump(mode="json", by_alias=True),
        "calculation": calculation_id, "metric": query.metric_version.model_dump(mode="json"),
        "sql": query.sql, "parameters": [(item.name, type(item.value).__name__, str(item.value)) for item in query.parameters]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def execute_metric(
    plan: MetricQueryPlan, adapters: Mapping[str, StarRocksDataSourceAdapter], *,
    datasets: ReportDatasetStore, run_context: RunContext, calculation_id: str,
) -> MetricExecutionReceipt:
    calculation_id = TypeAdapter(Identity).validate_python(calculation_id)
    by_ref = {metric.version_ref(): metric for metric in plan.metrics}
    root = by_ref.get(plan.request.metric_version)
    if root is None:
        raise ReportingError("metric_version_missing", "计算计划缺少精确指标定义。")
    def result(metric, group, value, issues, dataset_ids):
        dimensions = tuple(DimensionValue(dimension_id=name, value=entry) for name, entry in zip(plan.request.dimensions, group, strict=True)) if group else ()
        identity = {"basis": plan.request.basis_id, "calculation": calculation_id,
            "request": plan.request.model_dump(mode="json", by_alias=True), "metric": metric.version_ref().model_dump(mode="json"),
            "unit": metric.unit, "dimensions": [item.model_dump(mode="json") for item in dimensions],
            "datasets": dataset_ids, "value": str(value)}
        return MetricResult(metric_version=metric.version_ref(), basis_id=plan.request.basis_id,
            calculation_id=calculation_id, fact_id=_fact_id(json.dumps(identity, sort_keys=True, separators=(",", ":"))),
            period=plan.request.period, value=value, unit=metric.unit, dimensions=dimensions,
            status="computed" if value is not None else "unavailable", issue_codes=tuple(dict.fromkeys(issues)), dataset_ids=dataset_ids)
    if plan.issues:
        return MetricExecutionReceipt((result(root, (), None, tuple(issue.code for issue in plan.issues), ()),), ())
    sources = {}
    for source_id in dict.fromkeys(query.source_id for query in (*plan.checks, *plan.queries)):
        source = adapters.get(source_id)
        selected = tuple(query for query in (*plan.checks, *plan.queries) if query.source_id == source_id)
        if source is None or source.config.id != source_id or any(query.database != source.config.database.lower() for query in selected):
            raise ReportingError("metric_source_mismatch", "指标取数连接与登记计划不一致。")
        sources[source_id] = _BoundSource(source, selected)
    def approved_queries(queries):
        return tuple(ApprovedQuery(requirementId="metric-" + _query_identity(query, plan, calculation_id),
            sourceId=query.source_id, sql=query.sql, sqlHash=normalized_sql_hash(query.sql)) for query in queries)
    check_handles = ()
    try:
        if plan.checks:
            check_handles, _ = await datasets.materialize_batch(approved_queries(plan.checks), sources, run_context=run_context)
            for handle in check_handles:
                content, _ = await datasets.service.afile_bytes(_thread(run_context), handle.path)
                if len(content) != handle.size or hashlib.sha256(content).hexdigest() != handle.sha256:
                    raise ReportingError("metric_snapshot_invalid", "关联核对快照与登记身份不一致。")
                reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
                rows = list(reader)
                if reader.fieldnames != ["violation_count"] or len(rows) != 1 or not rows[0]["violation_count"].isdigit():
                    raise ReportingError("metric_snapshot_invalid", "关联核对快照结构无效。")
                if int(rows[0]["violation_count"]) > 0:
                    return MetricExecutionReceipt((result(root, (), None, ("join_fanout",), tuple(item.dataset_id for item in check_handles)),), check_handles)
        handles, _ = await datasets.materialize_batch(approved_queries(plan.queries), sources, run_context=run_context)
    except ReportingError as error:
        if error.code == "metric_snapshot_invalid":
            raise
        logger.warning("metric_materialization_unavailable code={}", error.code)
        return MetricExecutionReceipt((result(root, (), None, ("metric_query_failed", error.code), tuple(item.dataset_id for item in check_handles)),), check_handles)
    values, readiness = {}, []
    rules = plan.readiness_policy
    for query, handle in zip(plan.queries, handles, strict=True):
        content, _ = await datasets.service.afile_bytes(_thread(run_context), handle.path)
        if len(content) != handle.size or hashlib.sha256(content).hexdigest() != handle.sha256:
            raise ReportingError("metric_snapshot_invalid", "指标结果快照与登记身份不一致。")
        rows, observed_rows = {}, []
        try:
            reader = csv.DictReader(io.StringIO(content.decode("utf-8")))
            expected = {"value", "observed_count", "nonnull_count", *(name for index in range(len(query.dimensions)) for name in (f"dimension_{index}", f"dimension_{index}_is_null"))}
            if rules.expected_periods or rules.expected_groups or rules.watermark_field:
                expected.update(("observation_start", "observation_end"))
            expected.update(f"period_count_{index}" for index in range(len(rules.expected_periods)))
            expected.update(f"group_count_{index}" for index in range(len(rules.expected_groups)))
            if rules.watermark_field:
                expected.add("source_watermark")
            expected.update(name for index in range(len(query.join_checks)) for name in (f"join_max_{index}", f"join_unmatched_{index}"))
            if query.cumulative_snapshot:
                expected.add("snapshot_period")
            if reader.fieldnames is None or len(reader.fieldnames) != len(expected) or set(reader.fieldnames) != expected:
                raise ValueError("unexpected columns")
            for row in reader:
                observed_rows.append(row)
                if any(row[f"dimension_{index}_is_null"] not in ("0", "1") for index in range(len(query.dimensions))):
                    raise ValueError("invalid dimension null marker")
                group = dimension_values(query, row)
                if group in rows:
                    raise ValueError("duplicate group")
                observed, nonnull = int(row["observed_count"]), int(row["nonnull_count"])
                if observed < 0 or not 0 <= nonnull <= observed:
                    raise ValueError("invalid observation counts")
                if query.cumulative_snapshot:
                    continue
                issues = ("missing_data",) if observed == 0 else (("null_observations",) if nonnull < observed else ())
                if any(int(row[f"join_max_{index}"] or 0) > 1 for index in range(len(query.join_checks))):
                    issues += ("join_fanout",)
                warnings = ("unmatched_dimension_keys",) if any(int(row[f"join_unmatched_{index}"] or 0) > 0 for index in range(len(query.join_checks))) else ()
                value = None if issues else Decimal(row["value"])
                if value is not None and not value.is_finite():
                    raise ValueError("nonfinite value")
                rows[group] = result(by_ref[query.metric_version], group, value, (*issues, *warnings, "data_readiness_unknown"), (handle.dataset_id,))
            if query.cumulative_snapshot:
                rows = {group: result(by_ref[query.metric_version], group, value, codes, (handle.dataset_id,))
                    for group, (value, codes) in monthly_snapshot_values(query, by_ref[query.metric_version], plan.request, observed_rows).items()}
        except (UnicodeError, ValueError, TypeError, InvalidOperation, KeyError):
            raise ReportingError("metric_snapshot_invalid", "指标结果快照结构无效。") from None
        try:
            metric = by_ref[query.metric_version]
            def business_date(value):
                if len(value) > 10 and metric.time_zone is not None:
                    instant = datetime.fromisoformat(value)
                    if instant.tzinfo is None:
                        instant = instant.replace(tzinfo=ZoneInfo(metric.storage_time_zone))
                    return instant.astimezone(ZoneInfo(metric.time_zone)).date()
                return date.fromisoformat(value[:10])
            starts = [business_date(row["observation_start"]) for row in observed_rows if row.get("observation_start")]
            ends = [business_date(row["observation_end"]) for row in observed_rows if row.get("observation_end")]
            # 无源时区契约时不把数据库无时区时间假定为UTC，水位保留unknown。
            watermarks = [datetime.fromisoformat(row["source_watermark"]) for row in observed_rows if row.get("source_watermark")]
            watermark = max(watermarks) if watermarks and all(item.tzinfo is not None for item in watermarks) else None
            period_counts = [dict(period=period, observed_count=sum(int(row[f"period_count_{index}"] or 0) for row in observed_rows)) for index, period in enumerate(rules.expected_periods)]
            group_counts = [dict(dimensions=group, observed_count=sum(int(row[f"group_count_{index}"] or 0) for row in observed_rows)) for index, group in enumerate(rules.expected_groups)]
            observation = ReadinessObservations(metric_version=query.metric_version, basis_id=plan.request.basis_id,
                requested_period=plan.request.period, extracted_at=handle.materialized_at, source_watermark=watermark,
                observed_period=Period(start=min(starts), end=max(ends) + timedelta(days=1)) if starts and ends else None,
                fact_refs=tuple(item.fact_id for item in rows.values()) or (handle.dataset_id,),
                period_counts=tuple(period_counts), group_counts=tuple(group_counts))
        except (ValueError, TypeError, KeyError):
            raise ReportingError("metric_snapshot_invalid", "数据就绪观测结构无效。") from None
        receipt = evaluate_data_readiness(plan.request.model_copy(update={"metric_version": query.metric_version}), rules, observation)
        readiness.append(receipt)
        rows = {group: result(by_ref[query.metric_version], group, item.value,
            tuple(code for code in item.issue_codes if code != "data_readiness_unknown") + receipt.issue_codes, item.dataset_ids)
            for group, item in rows.items()}
        values[query.metric_version] = rows
    def calculate(ref):
        if ref in values:
            return values[ref]
        metric = by_ref[ref]
        left, right = calculate(metric.numerator_version), calculate(metric.denominator_version)
        rows, unmatched = {}, []
        for group in dict.fromkeys((*left, *right)):
            numerator, denominator = left.get(group), right.get(group)
            inputs = tuple(item for item in (numerator, denominator) if item is not None)
            ids = tuple(dict.fromkeys(identity for item in inputs for identity in item.dataset_ids))
            blocking = {"missing_period_observations", "missing_group_observations", "source_watermark_stale", "source_watermark_in_future", "unmatched_dimension_keys"}
            issues = tuple(dict.fromkeys(code for item in inputs for code in item.issue_codes if item.status == "unavailable" or code in blocking))
            warnings = tuple(dict.fromkeys(code for item in inputs for code in item.issue_codes if code not in issues))
            if numerator is None or denominator is None:
                issues += ("unmatched_groups",)
                for side, item in (("numerator", numerator), ("denominator", denominator)):
                    if item is not None and item.dimensions:
                        unmatched.append(UnmatchedGroup(side=side, dimensions=item.dimensions, value=item.value, unit=item.unit, fact_refs=(item.fact_id,)))
            elif denominator.value == 0:
                issues += ("zero_denominator",)
            value = None if issues else numerator.value / denominator.value * (100 if metric.unit == "%" else 1)
            rows[group] = result(metric, group, value, issues + warnings, ids)
        values[ref] = rows
        input_readiness = [item for item in readiness if item.metric_version in (metric.numerator_version, metric.denominator_version)]
        if input_readiness:
            codes = tuple(dict.fromkeys(code for item in input_readiness for code in item.issue_codes))
            if unmatched:
                codes += ("unmatched_groups",)
            refs = tuple(dict.fromkeys(item.fact_id for item in (*left.values(), *right.values())))
            checks = [ReadinessCheck(name="input_readiness", status="fail" if any(check.status == "fail" for item in input_readiness for check in item.checks) else
                ("unknown" if codes else "pass"), fact_refs=refs)]
            checks.append(ReadinessCheck(name="group_alignment", status="fail" if unmatched else ("pass" if refs else "unknown"), fact_refs=refs))
            if not refs and not codes:
                codes = ("data_readiness_unknown",)
            readiness.append(DataReadiness(metric_version=ref, requested_period=plan.request.period, observed_period=None,
                extracted_at=max(item.extracted_at for item in input_readiness), checks=tuple(checks),
                unmatched_groups=tuple(unmatched), issue_codes=codes))
        return rows
    calculate(plan.request.metric_version)
    results = tuple(item for rows in values.values() for item in rows.values())
    if not values[plan.request.metric_version]:
        results += (result(root, (), None, ("missing_data",), tuple(handle.dataset_id for handle in handles)),)
    return MetricExecutionReceipt(results, (*check_handles, *handles), tuple(readiness))
