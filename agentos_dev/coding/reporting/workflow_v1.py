from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any

from pydantic import Field, field_validator, model_validator
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, traverse_scope

from .contract import (
    ModelTable,
    ModelTermsResponse,
    ReportPeriod,
    ReportRequestEnvelope,
    SourceSchemaSnapshot,
    StrictModel,
    parse_ddl,
    schema_hash,
    validate_catalog,
)
from .data_source.models import ColumnShape, DataShape, TableDataShape
from .data_source.sql_validation import validate_starrocks_read_only_sql
from .data_source.starrocks import StarRocksSourceConfig
from .models import ReportingError

__all__ = [
    "ApprovedQuery",
    "ColumnShape",
    "DataShape",
    "DatasetLineage",
    "QueryRequirement",
    "RequirementRelation",
    "RequirementTable",
    "TableDataShape",
    "approve_query_batch",
    "coding_task_key",
    "normalized_sql_hash",
    "require_approved_sql",
    "resolve_schema_snapshot",
    "state_contains_connection_data",
    "validate_lineage",
]


class ApprovedQuery(StrictModel):
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    sql: str = Field(min_length=1, max_length=262_144)
    sql_hash: str = Field(alias="sqlHash", pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_hash(self) -> ApprovedQuery:
        if normalized_sql_hash(self.sql) != self.sql_hash:
            raise ValueError("sqlHash 与 SQL 不一致")
        return self


class DatasetLineage(StrictModel):
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    sql_hash: str = Field(alias="sqlHash", pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(alias="rowCount", ge=0)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RequirementTable(StrictModel):
    table: str = Field(min_length=1, max_length=256)
    period_column: str = Field(alias="periodColumn", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    measure_columns: tuple[str, ...] = Field(alias="measureColumns", min_length=1, max_length=100)

    @field_validator("table")
    @classmethod
    def normalize_table(cls, value: str) -> str:
        normalized = value.strip().lower()
        parts = normalized.split(".")
        if len(parts) not in {1, 2} or any(
            not part or not part.replace("_", "a").isalnum() for part in parts
        ):
            raise ValueError("table 必须是普通表名或 database.table")
        return normalized

    @field_validator("measure_columns")
    @classmethod
    def validate_measure_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_identifiers(value, "measureColumns")


class RequirementRelation(StrictModel):
    left_table: str = Field(alias="leftTable", min_length=1, max_length=256)
    right_table: str = Field(alias="rightTable", min_length=1, max_length=256)
    join_columns: tuple[str, ...] = Field(alias="joinColumns", min_length=1, max_length=30)

    @field_validator("left_table", "right_table")
    @classmethod
    def normalize_table(cls, value: str) -> str:
        return RequirementTable.normalize_table(value)

    @field_validator("join_columns")
    @classmethod
    def validate_join_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_identifiers(value, "joinColumns")

    @model_validator(mode="after")
    def validate_pair(self) -> RequirementRelation:
        if self.left_table == self.right_table:
            raise ValueError("relation 不能连接同一张表")
        return self


class QueryRequirement(StrictModel):
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    tables: tuple[RequirementTable, ...] = Field(min_length=1, max_length=20)
    dimension_columns: tuple[str, ...] = Field(alias="dimensionColumns", max_length=30)
    grain_columns: tuple[str, ...] = Field(alias="grainColumns", max_length=30)
    relations: tuple[RequirementRelation, ...] = Field(default=(), max_length=100)

    @field_validator("dimension_columns", "grain_columns")
    @classmethod
    def validate_grain_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_identifiers(value, "维度或粒度字段")

    @model_validator(mode="after")
    def validate_tables(self) -> QueryRequirement:
        if len({item.table for item in self.tables}) != len(self.tables):
            raise ValueError("tables 不能重复")
        if not set(self.grain_columns).issubset(self.dimension_columns):
            raise ValueError("grainColumns 必须属于 dimensionColumns")
        table_names = {item.table for item in self.tables}
        if len(self.tables) == 1 and self.relations:
            raise ValueError("单表 requirement 不得声明 relations")
        if len(self.tables) > 1:
            if not self.relations:
                raise ValueError("多表 requirement 必须声明 relations")
            edges: set[frozenset[str]] = set()
            connected = {self.tables[0].table}
            for relation in self.relations:
                if {relation.left_table, relation.right_table} - table_names:
                    raise ValueError("relation 引用了 requirement 之外的数据表")
                edge = frozenset((relation.left_table, relation.right_table))
                if edge in edges:
                    raise ValueError("relations 不能重复")
                if set(relation.join_columns) != set(self.grain_columns):
                    raise ValueError("relation.joinColumns 必须覆盖完整共同粒度")
                edges.add(edge)
            while True:
                expanded = connected | {
                    table for edge in edges if edge & connected for table in edge
                }
                if expanded == connected:
                    break
                connected = expanded
            if connected != table_names:
                raise ValueError("relations 必须连接全部 requirement 数据表")
        return self


def _normalized_identifiers(value: tuple[str, ...], label: str) -> tuple[str, ...]:
    normalized = tuple(item.strip().lower() for item in value)
    if len(normalized) != len(set(normalized)) or any(
        not item or not item.replace("_", "a").isalnum() for item in normalized
    ):
        raise ValueError(f"{label} 包含空值、重复值或非法标识符")
    return normalized


def resolve_schema_snapshot(
    envelope: ReportRequestEnvelope,
    *,
    source: StarRocksSourceConfig,
    metadata: ModelTermsResponse | None,
    catalog: tuple[ModelTable, ...],
) -> SourceSchemaSnapshot:
    ddl_tables: tuple[ModelTable, ...] | None = None
    if envelope.schema_input and envelope.schema_input.ddl:
        ddl_tables = parse_ddl(
            envelope.schema_input.ddl,
            source_id=source.id,
            default_database=source.database,
        )
    if metadata is None and ddl_tables is None:
        raise ReportingError("report_schema_required", "没有可用元数据模型，请提供 DDL。")
    if metadata is not None:
        metadata_tables = tuple(table for table in metadata.tables if table.source_id == source.id)
        if not metadata_tables:
            raise ReportingError("report_metadata_model_invalid", "元数据模型不包含当前数据源。")
        if ddl_tables is not None and schema_hash(ddl_tables) != schema_hash(metadata_tables):
            raise ReportingError("report_schema_conflict", "API 模型与输入 DDL 的结构不一致。")
        requested = metadata_tables
        snapshot = SourceSchemaSnapshot(
            source="metadata_api",
            revision=metadata.revision,
            schemaHash=schema_hash(requested),
            tables=requested,
        )
    else:
        assert ddl_tables is not None
        snapshot = SourceSchemaSnapshot(
            source="ddl",
            revision="ddl-v1",
            schemaHash=schema_hash(ddl_tables),
            tables=ddl_tables,
        )
    if envelope.schema_input and envelope.schema_input.schema_hash:
        if envelope.schema_input.schema_hash != snapshot.schema_hash:
            raise ReportingError(
                "report_schema_conflict", "schemaInput.schemaHash 与实际结构不一致。"
            )
    validate_catalog(snapshot.tables, catalog, allowed_tables=source.tables)
    return snapshot


def approve_query_batch(
    queries: list[dict[str, str]],
    *,
    sources: dict[str, StarRocksSourceConfig],
    envelope: ReportRequestEnvelope,
    requirements: tuple[QueryRequirement, ...],
) -> tuple[ApprovedQuery, ...]:
    if not queries or len(queries) > 100:
        raise ReportingError("report_query_batch_invalid", "SQL 批次必须包含 1 至 100 条查询。")
    result: list[ApprovedQuery] = []
    requirement_ids: set[str] = set()
    requirement_map = {item.requirement_id: item for item in requirements}
    if not requirements or len(requirement_map) != len(requirements):
        raise ReportingError("report_query_batch_invalid", "SQL requirements 不能为空或重复。")
    for item in queries:
        if set(item) != {"requirementId", "sourceId", "sql"}:
            raise ReportingError("report_query_batch_invalid", "SQL 批次字段无效。")
        requirement_id = item["requirementId"].strip()
        source = sources.get(item["sourceId"])
        if not requirement_id or requirement_id in requirement_ids or source is None:
            raise ReportingError("report_query_batch_invalid", "SQL requirement 或 source 无效。")
        requirement = requirement_map.get(requirement_id)
        if requirement is None or requirement.source_id != source.id:
            raise ReportingError(
                "report_query_batch_invalid", "SQL 与 requirement 或 source 不匹配。"
            )
        sql = validate_starrocks_read_only_sql(
            item["sql"], database=source.database, allowed_tables=source.tables
        )
        _validate_query_contract(
            sql,
            database=source.database,
            requirement=requirement,
            period=envelope.period,
        )
        result.append(
            ApprovedQuery(
                requirementId=requirement_id,
                sourceId=source.id,
                sql=sql,
                sqlHash=normalized_sql_hash(sql),
            )
        )
        requirement_ids.add(requirement_id)
    if requirement_ids != set(requirement_map):
        raise ReportingError("report_query_batch_invalid", "SQL 批次未覆盖全部 requirements。")
    return tuple(result)


def _validate_query_contract(
    sql: str,
    *,
    database: str,
    requirement: QueryRequirement,
    period: ReportPeriod,
) -> None:
    statement = parse_one(sql, read="mysql")
    scopes = tuple(traverse_scope(statement))
    expected_tables = {
        _qualified_requirement_table(item.table, database): item for item in requirement.tables
    }
    physical_scopes: list[tuple[Scope, str, RequirementTable]] = []
    actual_tables: set[str] = set()
    for scope in scopes:
        physical_sources = [
            (alias, source)
            for alias, (_, source) in scope.selected_sources.items()
            if isinstance(source, exp.Table)
        ]
        if len(physical_sources) > 1:
            raise ReportingError(
                "report_query_join_grain_invalid",
                "跨表查询必须先分别按 requirement 共同粒度聚合，不能直接连接明细表。",
            )
        for alias, table in physical_sources:
            qualified = _qualified_sql_table(table, database)
            actual_tables.add(qualified)
            table_requirement = expected_tables.get(qualified)
            if table_requirement is None:
                raise ReportingError(
                    "report_query_batch_invalid", "SQL 读取表与 requirement 不一致。"
                )
            physical_scopes.append((scope, alias, table_requirement))
    if actual_tables != set(expected_tables):
        raise ReportingError("report_query_batch_invalid", "SQL 未覆盖 requirement 声明的全部表。")

    for scope, alias, table_requirement in physical_scopes:
        if not _has_complete_period_filter(
            scope.expression,
            alias=alias,
            column=table_requirement.period_column.lower(),
            period=period,
        ):
            raise ReportingError(
                "report_query_period_invalid", "SQL 必须对每张表包含完整且精确的报表期间约束。"
            )
        if not _scope_has_grain(scope.expression, requirement.grain_columns):
            raise ReportingError(
                "report_query_grain_invalid", "SQL 聚合粒度与 requirement.grainColumns 不一致。"
            )
        if not _scope_has_measures(scope.expression, table_requirement.measure_columns):
            raise ReportingError(
                "report_query_measure_invalid", "SQL 未聚合 requirement 声明的全部指标字段。"
            )

    if len(actual_tables) > 1:
        for scope in scopes:
            selected = scope.selected_sources
            if len(selected) <= 1 or not scope.expression.args.get("joins"):
                continue
            if any(isinstance(source, exp.Table) for _, source in selected.values()):
                raise ReportingError(
                    "report_query_join_grain_invalid", "跨表查询禁止在聚合前连接物理表。"
                )
            _validate_aggregated_joins(scope.expression, requirement.grain_columns)


def _qualified_requirement_table(table: str, database: str) -> str:
    return table if "." in table else f"{database.lower()}.{table}"


def _qualified_sql_table(table: exp.Table, database: str) -> str:
    return f"{str(table.db or database).lower()}.{str(table.name).lower()}"


def _scope_has_grain(expression: exp.Expression, grain_columns: tuple[str, ...]) -> bool:
    group = expression.args.get("group")
    grouped = {
        str(item.name).lower()
        for item in (group.expressions if group is not None else ())
        if isinstance(item, exp.Column)
    }
    has_aggregate = any(isinstance(item, exp.AggFunc) for item in expression.walk())
    return grouped == set(grain_columns) and has_aggregate


def _scope_has_measures(expression: exp.Expression, measure_columns: tuple[str, ...]) -> bool:
    aggregated_columns = {
        str(column.name).lower()
        for aggregate in expression.find_all(exp.AggFunc)
        for column in aggregate.find_all(exp.Column)
    }
    return set(measure_columns).issubset(aggregated_columns)


def _has_complete_period_filter(
    expression: exp.Expression,
    *,
    alias: str,
    column: str,
    period: ReportPeriod,
) -> bool:
    where = expression.args.get("where")
    if where is None:
        return False
    lower = False
    upper = False
    for predicate in _and_predicates(where.this):
        if isinstance(predicate, exp.Between) and _matches_column(predicate.this, alias, column):
            if (
                _literal_date(predicate.args.get("low")) != period.start
                or _literal_date(predicate.args.get("high")) != period.end
            ):
                return False
            lower = True
            upper = True
        elif isinstance(predicate, (exp.GTE, exp.GT, exp.LTE, exp.LT)):
            left, right = predicate.this, predicate.expression
            if _matches_column(left, alias, column):
                value = _literal_date(right)
                valid_lower = isinstance(predicate, exp.GTE) and value == period.start
                valid_upper = (isinstance(predicate, exp.LTE) and value == period.end) or (
                    isinstance(predicate, exp.LT) and value == period.end + timedelta(days=1)
                )
                if not valid_lower and not valid_upper:
                    return False
                lower = lower or valid_lower
                upper = upper or valid_upper
            elif _matches_column(right, alias, column):
                value = _literal_date(left)
                valid_lower = isinstance(predicate, exp.LTE) and value == period.start
                valid_upper = (isinstance(predicate, exp.GTE) and value == period.end) or (
                    isinstance(predicate, exp.GT) and value == period.end + timedelta(days=1)
                )
                if not valid_lower and not valid_upper:
                    return False
                lower = lower or valid_lower
                upper = upper or valid_upper
        elif any(_matches_column(item, alias, column) for item in predicate.find_all(exp.Column)):
            return False
    return lower and upper


def _and_predicates(expression: exp.Expression) -> tuple[exp.Expression, ...]:
    if isinstance(expression, exp.And):
        return _and_predicates(expression.this) + _and_predicates(expression.expression)
    return (expression,)


def _matches_column(expression: exp.Expression | None, alias: str, column: str) -> bool:
    if not isinstance(expression, exp.Column) or str(expression.name).lower() != column:
        return False
    qualifier = str(expression.table or "").lower()
    return not qualifier or qualifier == alias.lower()


def _literal_date(expression: exp.Expression | None) -> date | None:
    if not isinstance(expression, exp.Literal) or not expression.is_string:
        return None
    try:
        return date.fromisoformat(str(expression.this))
    except ValueError:
        return None


def _validate_aggregated_joins(expression: exp.Expression, grain_columns: tuple[str, ...]) -> None:
    for join in expression.args.get("joins") or ():
        right_alias = str(join.this.alias_or_name or "").lower()
        keys: set[str] = set()
        on = join.args.get("on")
        if on is not None:
            for predicate in _and_predicates(on):
                if not isinstance(predicate, exp.EQ):
                    continue
                left, right = predicate.this, predicate.expression
                if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                    continue
                if (
                    str(left.name).lower() == str(right.name).lower()
                    and right_alias
                    and right_alias in {str(left.table).lower(), str(right.table).lower()}
                    and str(left.table).lower() != str(right.table).lower()
                ):
                    keys.add(str(left.name).lower())
        if not set(grain_columns).issubset(keys):
            raise ReportingError(
                "report_query_join_grain_invalid",
                "跨表聚合结果必须按 requirement 的全部共同粒度键等值连接。",
            )


def require_approved_sql(approved: ApprovedQuery, execution_sql: str) -> str:
    if normalized_sql_hash(execution_sql) != approved.sql_hash or execution_sql != approved.sql:
        raise ReportingError("report_sql_hash_mismatch", "执行 SQL 与审核原文不一致。")
    return execution_sql


def validate_lineage(
    approved: tuple[ApprovedQuery, ...], lineage: tuple[DatasetLineage, ...]
) -> None:
    expected = {(item.source_id, item.requirement_id, item.sql_hash) for item in approved}
    actual = {(item.source_id, item.requirement_id, item.sql_hash) for item in lineage}
    if expected != actual or len(lineage) != len(approved):
        raise ReportingError("report_dataset_lineage_incomplete", "不可变数据集血缘不完整。")


def normalized_sql_hash(sql: str) -> str:
    normalized = str(sql or "").strip().rstrip(";").strip()
    return hashlib.sha256(normalized.encode()).hexdigest()


def coding_task_key(workflow_run_id: str) -> str:
    """暂停、恢复和报告 revision 共用同一 CodingTask。"""

    digest = hashlib.sha256(workflow_run_id.encode()).hexdigest()[:32]
    return f"report-coding-{digest}"


def state_contains_connection_data(state: Any) -> bool:
    encoded = json.dumps(state, ensure_ascii=True, sort_keys=True, default=str).lower()
    return any(
        marker in encoded for marker in ('"host"', '"password"', '"username"', '"dsn"', "://")
    )
