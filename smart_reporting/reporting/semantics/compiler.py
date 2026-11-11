"""从已登记指标生成有限SQL AST；模型文本不能成为指标公式。"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlglot import exp

from ..contract import ModelTable
from ..data_source.sql_validation import validate_starrocks_read_only_sql
from ..models import ReportingError
from .models import (
    DataReadinessPolicy,
    MetricDefinition,
    MetricRequest,
    MetricVersionRef,
    PolicyVersionRef,
    Scalar,
    SemanticIssue,
    StatisticalPolicy,
)
from .predicates import compile_filter
from .validation import validate_policy


@dataclass(frozen=True)
class SqlParameter:
    name: str
    value: Scalar | date = field(repr=False)


@dataclass(frozen=True)
class MetricQuery:
    metric_version: MetricVersionRef
    source_id: str
    database: str
    allowed_tables: tuple[str, ...]
    sql: str
    parameters: tuple[SqlParameter, ...] = field(repr=False)
    dimensions: tuple[str, ...] = ()
    join_checks: tuple[str, ...] = ()
    cumulative_snapshot: bool = False
    dimension_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricQueryPlan:
    request: MetricRequest
    policy_version: PolicyVersionRef
    metrics: tuple[MetricDefinition, ...]
    queries: tuple[MetricQuery, ...]
    issues: tuple[SemanticIssue, ...] = ()
    readiness_policy: DataReadinessPolicy = field(default_factory=DataReadinessPolicy)
    checks: tuple[MetricQuery, ...] = ()


class _Unavailable(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


def compile_metric(
    request: MetricRequest, policy: StatisticalPolicy,
    metrics: tuple[MetricDefinition, ...], catalog: tuple[ModelTable, ...],
) -> MetricQueryPlan:
    if any(metric.scope_id != policy.scope_id for metric in metrics):
        raise ReportingError("metric_scope_mismatch", "指标与统计口径组织不一致。")
    if request.metric_version not in policy.metric_versions:
        raise ReportingError("metric_not_selected", "请求指标不在本次登记口径中。")
    issues = validate_policy(policy, metrics)
    by_ref = {metric.version_ref(): metric for metric in metrics}
    roots = []
    visited = set()
    def visit(ref):
        if ref in visited:
            return
        visited.add(ref)
        metric = by_ref.get(ref)
        if metric is None:
            return
        if metric.kind == "ratio":
            visit(metric.numerator_version)
            visit(metric.denominator_version)
        else:
            roots.append(metric)
    visit(request.metric_version)
    relevant_issues = tuple(issue for issue in issues if any(issue.object_id == f"{ref.metric_id}:{ref.revision}" for ref in visited))
    plan = dict(request=request, policy_version=PolicyVersionRef(policy_id=policy.id, revision=policy.revision),
        metrics=tuple(by_ref[ref] for ref in by_ref if ref in visited), readiness_policy=policy.readiness_policy)
    if relevant_issues:
        return MetricQueryPlan(**plan, queries=(), issues=relevant_issues)
    try:
        if request.period.start < policy.valid_from or (policy.valid_to is not None and request.period.end > policy.valid_to):
            raise _Unavailable("policy_period_not_applicable", "请求期间超出口径适用期，不能自动套用整段规则。")
        if len(request.dimensions) != len(set(request.dimensions)):
            raise _Unavailable("grain_not_supported", "请求维度重复，不能形成唯一输出粒度。")
        compiled = tuple(_compile_leaf(request, policy, metric, catalog) for metric in roots)
        queries = tuple(item[0] for item in compiled)
        checks = tuple(item for _, checks in compiled for item in checks)
    except _Unavailable as error:
        return MetricQueryPlan(**plan, queries=(), issues=(SemanticIssue(code=error.code,
            object_id=f"{request.metric_version.metric_id}:{request.metric_version.revision}",
            message=error.message, impact="unavailable"),))
    return MetricQueryPlan(**plan, queries=queries, checks=checks)


def _compile_leaf(request, policy, metric, catalog):
    tables = {(table.source_id.lower(), table.database.lower(), table.name.lower()): table for table in catalog}
    def resolve(reference):
        source, database, table, column = reference.rsplit(".", 3)
        identity = (source.lower(), database.lower(), table.lower())
        registered = tables.get(identity)
        found = next((item for item in registered.columns if item.name.lower() == column.lower()), None) if registered else None
        if found is None:
            raise ReportingError("metric_field_denied", "指标引用字段不在本次允许目录中。")
        return identity, found
    identity, value_column = resolve(metric.field_ref)
    time_identity, time_column = resolve(metric.time_field)
    if identity != time_identity:
        raise _Unavailable("metric_time_not_applicable", "时间字段与事实表不一致。")
    snapshot = metric.aggregation_policy.observation_kind == "cumulative_snapshot"
    if (snapshot and (metric.kind != "sum" or metric.aggregation_policy.time_aggregation != "difference")) or (not snapshot and metric.aggregation_policy.time_aggregation != "sum"):
        raise _Unavailable("metric_aggregation_not_supported", "此时间汇总方式尚未完成计算核对。")
    if snapshot and (request.period.start.day != 1 or request.period.end.day != 1):
        raise _Unavailable("cumulative_period_not_supported", "月末累计快照差分需要完整自然月期间。")
    query_dimensions = tuple(dict.fromkeys((*request.dimensions, *metric.grain))) if snapshot else request.dimensions
    dimensions = {item.id: item for item in metric.dimensions}
    if not set(request.dimensions).issubset(dimensions):
        raise _Unavailable("grain_not_supported", "请求维度未登记，不能推导细粒度数值。")
    if not time_column.data_type.upper().startswith(("DATE", "TIMESTAMP")):
        raise _Unavailable("metric_time_type_unsupported", "时间字段类型缺少明确期间转换规则。")
    timestamp = time_column.data_type.upper().startswith(("DATETIME", "TIMESTAMP"))
    if timestamp and (metric.time_zone is None or metric.storage_time_zone is None):
        raise _Unavailable("metric_timezone_unknown", "时间戳字段须明确业务时区及存储时区。")
    if timestamp and snapshot:
        raise _Unavailable("cumulative_time_type_unsupported", "月末快照需登记日期字段，不能从时间戳猜测月末身份。")
    def boundary(value):
        if not timestamp:
            return value
        return datetime.combine(value, time.min, tzinfo=ZoneInfo(metric.time_zone)).astimezone(
            ZoneInfo(metric.storage_time_zone)).replace(tzinfo=None)
    if metric.kind == "sum" and not value_column.data_type.upper().startswith(("DECIMAL", "NUMERIC", "INT", "BIGINT", "SMALLINT", "TINYINT", "LARGEINT", "FLOAT", "DOUBLE")):
        raise _Unavailable("metric_value_type_unsupported", "汇总字段不是可核对数值类型。")
    parameters = []
    def parameter(value):
        name = f"p{len(parameters)}"
        parameters.append(SqlParameter(name, value))
        return exp.Placeholder(this=name)
    source, database, table = identity
    aliases = {identity: "f"}
    joins, checks, join_names = [], [], []
    needed_dimensions = set(query_dimensions) | {entry.dimension_id for group in policy.readiness_policy.expected_groups for entry in group}
    references = [item.field_ref for item in metric.dimensions if item.id in needed_dimensions]
    references.extend(item.field_ref for item in (*policy.filters, *request.filter_values))
    references.extend(ref for join in policy.joins for ref in (*join.left_keys, *join.right_keys))
    required_columns = {}
    for reference in references:
        ref_identity, registered = resolve(reference)
        required_columns.setdefault(ref_identity, set()).add(registered.name)
    allowed = tuple(f"{db}.{name}" for (sid, db, name) in tables if sid == source and db == database)
    pending = list(policy.joins)
    while pending:
        progress = False
        for join in tuple(pending):
            left, right = tuple(resolve(ref) for ref in join.left_keys), tuple(resolve(ref) for ref in join.right_keys)
            left_identity, right_identity = left[0][0], right[0][0]
            if left_identity not in aliases:
                continue
            if (any(item[0] != left_identity for item in left) or any(item[0] != right_identity for item in right)
                    or right_identity[:2] != identity[:2] or right_identity in aliases):
                raise _Unavailable("metric_join_not_supported", "关联键必须在同一连接数据库内形成无歧义维度路径。")
            if set(join.output_grain) != set(metric.grain):
                raise _Unavailable("grain_not_supported", "关联输出粒度与指标登记粒度不一致。")
            alias = f"d{len(joins)}"
            keys = [item[1].name for item in right]
            dimension_table = tables[right_identity]
            base = exp.Table(this=exp.to_identifier(right_identity[2], quoted=True), db=exp.to_identifier(database, quoted=True))
            duplicate = exp.select(*(exp.column(key, quoted=True) for key in keys)).from_(base.copy()).group_by(
                *(exp.column(key, quoted=True) for key in keys)).having(exp.GT(this=exp.Count(this=exp.Star()), expression=exp.Literal.number(1)))
            check_sql = exp.select(exp.alias_(exp.Count(this=exp.Star()), "violation_count", quoted=True)).from_(duplicate.subquery("duplicate_keys"))
            check_sql = validate_starrocks_read_only_sql(check_sql.sql(dialect="mysql"), database=database, allowed_tables=allowed)
            checks.append(MetricQuery(metric.version_ref(), source, database, allowed, check_sql, ()))
            # 维表先按键归并；即使预检后发生重复写入，事实金额也不会被JOIN放大。
            projections = [exp.alias_(exp.column(item.name, quoted=True) if item.name in keys else exp.Max(this=exp.column(item.name, quoted=True)), item.name, quoted=True) for item in dimension_table.columns if item.name in keys or item.name in required_columns.get(right_identity, ())]
            projections.append(exp.alias_(exp.Count(this=exp.Star()), "_join_matches", quoted=True))
            derived = exp.select(*projections).from_(base).group_by(*(exp.column(key, quoted=True) for key in keys)).subquery(alias)
            on = exp.and_(*(exp.EQ(this=exp.column(lcol.name, table=aliases[left_identity], quoted=True),
                expression=exp.column(rcol.name, table=alias, quoted=True)) for (_, lcol), (_, rcol) in zip(left, right, strict=True)))
            joins.append((derived, on))
            aliases[right_identity] = alias
            join_names.append(alias)
            pending.remove(join)
            progress = True
        if not progress:
            break
    def column(name, field_identity=identity):
        if field_identity not in aliases:
            raise _Unavailable("metric_join_not_supported", "字段未登记可核对的维度关联路径。")
        return exp.column(name, table=aliases[field_identity], quoted=True)
    value = column(value_column.name)
    aggregated = exp.Sum(this=value.copy()) if metric.kind == "sum" else exp.Count(
        this=exp.Distinct(expressions=[value.copy()]) if metric.kind == "count_distinct" else value.copy())
    projections = [exp.alias_(aggregated, "value", quoted=True),
        exp.alias_(exp.Count(this=exp.Star()), "observed_count", quoted=True),
        exp.alias_(exp.Count(this=value.copy()), "nonnull_count", quoted=True)]
    grouping, dimension_types = [], []
    for index, dimension in enumerate(query_dimensions):
        dimension_identity, registered = resolve(dimensions[dimension].field_ref)
        dimension_types.append(registered.data_type)
        grouping.append(column(registered.name, dimension_identity))
        projections.append(exp.alias_(grouping[-1].copy(), f"dimension_{index}", quoted=True))
        projections.append(exp.alias_(exp.Case(ifs=[exp.If(this=exp.Is(this=grouping[-1].copy(), expression=exp.Null()), true=exp.Literal.number(1))], default=exp.Literal.number(0)), f"dimension_{index}_is_null", quoted=True))
    window_start = (request.period.start - timedelta(days=1)).replace(day=1) if snapshot else request.period.start
    if snapshot:
        grouping.append(column(time_column.name))
        projections.append(exp.alias_(column(time_column.name), "snapshot_period", quoted=True))
    predicate = exp.and_(exp.GTE(this=column(time_column.name), expression=parameter(boundary(window_start))),
        exp.LT(this=column(time_column.name), expression=parameter(boundary(request.period.end))))
    for condition in (*policy.filters, *request.filter_values):
        filter_identity, registered = resolve(condition.field_ref)
        if filter_identity not in aliases:
            raise _Unavailable("metric_filter_not_applicable", "筛选未映射到此事实表，不能静默忽略。")
        field_column = column(registered.name, filter_identity)
        try:
            expression = compile_filter(condition, field_column, parameter)
        except ReportingError as error:
            raise _Unavailable(error.code, error.message) from error
        predicate = exp.and_(predicate, expression)
    rules = policy.readiness_policy
    observation_window = exp.and_(exp.GTE(this=column(time_column.name), expression=parameter(boundary(request.period.start))),
        exp.LT(this=column(time_column.name), expression=parameter(boundary(request.period.end)))) if snapshot and (rules.expected_periods or rules.expected_groups or rules.watermark_field) else None
    if rules.expected_periods or rules.expected_groups or rules.watermark_field:
        observed_time = exp.Case(ifs=[exp.If(this=observation_window.copy(), true=column(time_column.name))]) if observation_window is not None else column(time_column.name)
        projections.extend((exp.alias_(exp.Min(this=observed_time.copy()), "observation_start", quoted=True),
            exp.alias_(exp.Max(this=observed_time.copy()), "observation_end", quoted=True)))
    def observation_count(condition, name):
        projections.append(exp.alias_(exp.Sum(this=exp.Case(ifs=[exp.If(this=condition, true=exp.Literal.number(1))],
            default=exp.Literal.number(0))), name, quoted=True))
    for index, period in enumerate(rules.expected_periods):
        observation_count(exp.and_(exp.GTE(this=column(time_column.name), expression=parameter(boundary(period.start))),
            exp.LT(this=column(time_column.name), expression=parameter(boundary(period.end)))), f"period_count_{index}")
    for index, group in enumerate(rules.expected_groups):
        conditions = [observation_window.copy()] if observation_window is not None else []
        for entry in group:
            if entry.dimension_id not in dimensions:
                raise _Unavailable("grain_not_supported", "数据就绪对象使用了未登记维度。")
            group_identity, registered = resolve(dimensions[entry.dimension_id].field_ref)
            conditions.append(exp.Is(this=column(registered.name, group_identity), expression=exp.Null()) if entry.value is None else
                exp.EQ(this=column(registered.name, group_identity), expression=parameter(entry.value)))
        observation_count(exp.and_(*conditions), f"group_count_{index}")
    if rules.watermark_field:
        watermark_identity, watermark = resolve(rules.watermark_field)
        if watermark_identity != identity:
            raise _Unavailable("metric_watermark_not_applicable", "数据水位字段未映射到此事实表。")
        projections.append(exp.alias_(exp.Max(this=column(watermark.name)), "source_watermark", quoted=True))
    for index, alias in enumerate(join_names):
        matches = exp.column("_join_matches", table=alias, quoted=True)
        projections.append(exp.alias_(exp.Max(this=matches.copy()), f"join_max_{index}", quoted=True))
        observation_count(exp.Is(this=matches, expression=exp.Null()), f"join_unmatched_{index}")
    statement = exp.select(*projections).from_(exp.Table(this=exp.to_identifier(table, quoted=True),
        db=exp.to_identifier(database, quoted=True), alias=exp.TableAlias(this=exp.to_identifier("f")))).where(predicate)
    for derived, on in joins:
        statement = statement.join(derived, on=on, join_type="LEFT")
    if grouping:
        statement = statement.group_by(*grouping)
    allowed = tuple(f"{db}.{name}" for (sid, db, name) in tables if sid == source and db == database)
    sql = validate_starrocks_read_only_sql(statement.sql(dialect="mysql"), database=database, allowed_tables=allowed)
    return MetricQuery(metric.version_ref(), source, database, allowed, sql, tuple(parameters), query_dimensions, tuple(join_names), snapshot, tuple(dimension_types)), tuple(checks)
