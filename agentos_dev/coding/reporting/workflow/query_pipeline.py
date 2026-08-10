from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator
from sqlglot import exp, parse_one
from sqlglot.optimizer.scope import Scope, traverse_scope

from ..contract import (
    MeasureSemantic,
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
from ..data_source.models import ColumnShape, DataShape, TableDataShape
from ..data_source.sql_validation import validate_starrocks_read_only_sql
from ..data_source.starrocks import StarRocksSourceConfig
from ..models import ReportingError

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
    period_roles: tuple[Literal["current", "yoy", "mom"], ...] = Field(
        default=("current",), alias="periodRoles", min_length=1, max_length=3
    )
    query_window_id: str = Field(
        default="current", alias="queryWindowId", min_length=1, max_length=128
    )

    @model_validator(mode="after")
    def validate_hash(self) -> ApprovedQuery:
        if normalized_sql_hash(self.sql) != self.sql_hash:
            raise ValueError("sqlHash 与 SQL 不一致")
        if len(self.period_roles) != len(set(self.period_roles)):
            raise ValueError("periodRoles 不能重复")
        return self


class DatasetLineage(StrictModel):
    dataset_id: str = Field(alias="datasetId", min_length=1, max_length=128)
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    requirement_id: str = Field(alias="requirementId", min_length=1, max_length=128)
    sql_hash: str = Field(alias="sqlHash", pattern=r"^[0-9a-f]{64}$")
    row_count: int = Field(alias="rowCount", ge=0)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    period_roles: tuple[Literal["current", "yoy", "mom"], ...] = Field(
        default=("current",), alias="periodRoles", min_length=1, max_length=3
    )
    query_window_id: str = Field(
        default="current", alias="queryWindowId", min_length=1, max_length=128
    )


class RequirementTable(StrictModel):
    table: str = Field(min_length=1, max_length=256)
    period_column: str = Field(alias="periodColumn", pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
    period_granularity: Literal["date", "month", "year"] = Field(alias="periodGranularity")
    measure_columns: tuple[str, ...] = Field(
        alias="measureColumns",
        min_length=1,
        max_length=100,
        description="需要聚合的物理数值字段，每个字段只出现一次；maxItems 只是上限。",
    )

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
    dimension_columns: tuple[str, ...] = Field(
        alias="dimensionColumns",
        max_length=30,
        description="分析维度物理字段，每个字段只出现一次；maxItems 只是上限。",
    )
    grain_columns: tuple[str, ...] = Field(
        alias="grainColumns",
        max_length=30,
        description="物化共同粒度字段，每个字段只出现一次；maxItems 只是上限。",
    )
    relations: tuple[RequirementRelation, ...] = Field(default=(), max_length=100)
    comparison_roles: tuple[Literal["yoy", "mom"], ...] | None = Field(
        default=None,
        alias="comparisonRoles",
        max_length=2,
        description="省略时继承请求；只能收窄，不能扩展请求比较范围。",
    )

    @field_validator("dimension_columns", "grain_columns")
    @classmethod
    def validate_grain_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalized_identifiers(value, "维度或粒度字段")

    @field_validator("comparison_roles")
    @classmethod
    def validate_comparison_roles(
        cls, value: tuple[Literal["yoy", "mom"], ...] | None
    ) -> tuple[Literal["yoy", "mom"], ...] | None:
        if value is None:
            return None
        if len(value) != len(set(value)):
            raise ValueError("comparisonRoles 不能重复")
        return tuple(role for role in ("yoy", "mom") if role in value)

    def resolved_comparison_roles(
        self, requested: tuple[Literal["yoy", "mom"], ...]
    ) -> tuple[Literal["yoy", "mom"], ...]:
        selected = requested if self.comparison_roles is None else self.comparison_roles
        if set(selected) - set(requested):
            raise ValueError("requirement comparisonRoles 不得扩展请求范围")
        if "mom" in selected and any(item.period_granularity == "year" for item in self.tables):
            raise ValueError("year 粒度 requirement 不支持 mom")
        return selected

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
    profile_measure_semantics: tuple[MeasureSemantic, ...] = (),
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
        source_prefix = f"{source.id}.".lower()
        source_terms = tuple(
            term.model_copy(
                update={
                    "field_refs": tuple(
                        field_ref
                        for field_ref in term.field_refs
                        if field_ref.lower().startswith(source_prefix)
                    )
                }
            )
            for term in metadata.terms
            if not term.field_refs
            or any(field_ref.lower().startswith(source_prefix) for field_ref in term.field_refs)
        )
        metadata_semantics = tuple(
            item
            for item in metadata.measure_semantics
            if item.field_ref.lower().startswith(source_prefix)
        )
        source_semantics = _merge_measure_semantics(
            metadata_semantics,
            tuple(
                item
                for item in profile_measure_semantics
                if item.field_ref.lower().startswith(source_prefix)
            ),
        )
        source_ddl_models = tuple(
            raw
            for raw, table in zip(metadata.ddl_models, metadata.tables, strict=True)
            if table.source_id == source.id
        )
        snapshot = SourceSchemaSnapshot(
            source="metadata_api",
            revision=metadata.revision,
            schemaHash=schema_hash(requested),
            ddlModels=source_ddl_models,
            tables=requested,
            terms=source_terms,
            measureSemantics=source_semantics,
        )
    else:
        assert ddl_tables is not None
        snapshot = SourceSchemaSnapshot(
            source="ddl",
            revision="ddl-v1",
            schemaHash=schema_hash(ddl_tables),
            tables=ddl_tables,
            measureSemantics=tuple(
                item
                for item in profile_measure_semantics
                if item.field_ref.lower().startswith(f"{source.id}.".lower())
            ),
        )
    if envelope.schema_input and envelope.schema_input.schema_hash:
        if envelope.schema_input.schema_hash != snapshot.schema_hash:
            raise ReportingError(
                "report_schema_conflict", "schemaInput.schemaHash 与实际结构不一致。"
            )
    resolved_tables = validate_catalog(
        snapshot.tables,
        catalog,
        allowed_tables=tuple(
            f"{table.database.lower()}.{table.name.lower()}" for table in snapshot.tables
        ),
    )
    return snapshot.model_copy(
        update={"tables": resolved_tables, "schema_hash": schema_hash(resolved_tables)}
    )


def _merge_measure_semantics(
    metadata_semantics: tuple[MeasureSemantic, ...],
    profile_semantics: tuple[MeasureSemantic, ...],
) -> tuple[MeasureSemantic, ...]:
    merged = {item.field_ref.lower(): item for item in metadata_semantics}
    order = [item.field_ref.lower() for item in metadata_semantics]
    for item in profile_semantics:
        field_ref = item.field_ref.lower()
        current = merged.get(field_ref)
        if current is not None:
            current_payload = current.model_dump(mode="json", by_alias=True)
            item_payload = item.model_dump(mode="json", by_alias=True)
            current_payload["fieldRef"] = current_payload["fieldRef"].lower()
            item_payload["fieldRef"] = item_payload["fieldRef"].lower()
            if current_payload != item_payload:
                raise ReportingError(
                    "report_measure_semantic_conflict",
                    f"metadata API 与 Profile 的指标语义冲突: {item.field_ref}",
                )
            continue
        merged[field_ref] = item
        order.append(field_ref)
    return tuple(merged[field_ref] for field_ref in order)


def approve_query_batch(
    queries: list[dict[str, Any]],
    *,
    sources: dict[str, StarRocksSourceConfig],
    snapshots: tuple[SourceSchemaSnapshot, ...],
    envelope: ReportRequestEnvelope,
    requirements: tuple[QueryRequirement, ...],
    row_preserving_requirement_ids: tuple[str, ...] = (),
    require_complete_batch: bool = True,
) -> tuple[ApprovedQuery, ...]:
    if not queries or len(queries) > 100:
        raise ReportingError("report_query_batch_invalid", "SQL 批次必须包含 1 至 100 条查询。")
    result: list[ApprovedQuery] = []
    approved_keys: set[tuple[str, str]] = set()
    requirement_map = {item.requirement_id: item for item in requirements}
    if not requirements or len(requirement_map) != len(requirements):
        raise ReportingError("report_query_batch_invalid", "SQL requirements 不能为空或重复。")
    row_preserving_ids = set(row_preserving_requirement_ids)
    if len(row_preserving_ids) != len(row_preserving_requirement_ids) or row_preserving_ids - set(
        requirement_map
    ):
        raise ReportingError(
            "report_query_batch_invalid", "原始行保留查询引用了未知或重复 requirement。"
        )
    snapshot_tables = _snapshot_tables(snapshots)
    measure_semantics = {
        item.field_ref.lower(): item
        for snapshot in snapshots
        for item in snapshot.measure_semantics
    }
    windows_by_requirement = {
        requirement.requirement_id: envelope.model_copy(
            update={
                "comparison_roles": requirement.resolved_comparison_roles(envelope.comparison_roles)
            }
        ).period_windows(granularity=requirement.tables[0].period_granularity)
        for requirement in requirements
    }
    explicit_period_mode = any(
        isinstance(item, dict)
        and any(key in item for key in ("periodRole", "periodRoles", "queryWindowId"))
        for item in queries
    )
    for item in queries:
        if not isinstance(item, dict):
            raise ReportingError("report_query_batch_invalid", "SQL 批次项目必须是对象。")
        allowed_keys = {
            "requirementId",
            "sourceId",
            "sql",
            "periodRole",
            "periodRoles",
            "queryWindowId",
        }
        if set(item) - allowed_keys or not {"requirementId", "sourceId", "sql"}.issubset(item):
            raise ReportingError("report_query_batch_invalid", "SQL 批次字段无效。")
        if not all(isinstance(item[key], str) for key in ("requirementId", "sourceId", "sql")):
            raise ReportingError("report_query_batch_invalid", "SQL 批次字段类型无效。")
        requirement_id = item["requirementId"].strip()
        requirement = requirement_map.get(requirement_id)
        if requirement is None:
            raise ReportingError("report_query_batch_invalid", "SQL requirement 不存在。")
        period_windows = windows_by_requirement[requirement_id].windows
        windows_by_role = {window.role: window for window in period_windows}
        roles_by_window: dict[str, tuple[Literal["current", "yoy", "mom"], ...]] = {}
        for period_window in period_windows:
            roles_by_window.setdefault(period_window.query_window_id, ())
            roles_by_window[period_window.query_window_id] = (
                *roles_by_window[period_window.query_window_id],
                period_window.role,
            )
        source = sources.get(item["sourceId"])
        raw_role = item.get("periodRole", "current")
        if not isinstance(raw_role, str) or raw_role not in windows_by_role:
            raise ReportingError("report_query_period_invalid", "SQL 期间角色不在请求窗口内。")
        window = windows_by_role[raw_role]
        expected_roles = roles_by_window[window.query_window_id]
        if item.get("queryWindowId", window.query_window_id) != window.query_window_id:
            raise ReportingError(
                "report_query_period_invalid", "SQL queryWindowId 与期间角色不一致。"
            )
        if "periodRoles" in item:
            raw_roles = item["periodRoles"]
            if not isinstance(raw_roles, (list, tuple)) or tuple(raw_roles) != expected_roles:
                raise ReportingError(
                    "report_query_period_invalid", "SQL periodRoles 与窗口角色不一致。"
                )
        approved_key = (requirement_id, window.query_window_id)
        if not requirement_id or approved_key in approved_keys or source is None:
            raise ReportingError("report_query_batch_invalid", "SQL requirement 或 source 无效。")
        if requirement is None or requirement.source_id != source.id:
            raise ReportingError(
                "report_query_batch_invalid", "SQL 与 requirement 或 source 不匹配。"
            )
        scoped_tables = snapshot_tables.get(source.id)
        if scoped_tables is None:
            raise ReportingError("report_query_scope_invalid", "SQL 数据源缺少结构快照。")
        _validate_requirement_scope(
            requirement,
            database=source.database,
            snapshot_tables=scoped_tables,
            measure_semantics=measure_semantics,
        )
        sql = validate_starrocks_read_only_sql(
            item["sql"],
            database=source.database,
            allowed_tables=tuple(scoped_tables),
        )
        _validate_query_contract(
            sql,
            database=source.database,
            requirement=requirement,
            period=window.period,
            snapshot_tables=scoped_tables,
            measure_semantics=measure_semantics,
            row_preserving=requirement_id in row_preserving_ids,
        )
        result.append(
            ApprovedQuery(
                requirementId=requirement_id,
                sourceId=source.id,
                sql=sql,
                sqlHash=normalized_sql_hash(sql),
                periodRoles=expected_roles,
                queryWindowId=window.query_window_id,
            )
        )
        approved_keys.add(approved_key)
    expected_keys = {
        (requirement.requirement_id, window.query_window_id)
        for requirement in requirements
        for window in (
            windows_by_requirement[requirement.requirement_id].windows
            if explicit_period_mode
            else windows_by_requirement[requirement.requirement_id].windows[:1]
        )
    }
    if require_complete_batch and approved_keys != expected_keys:
        raise ReportingError("report_query_batch_invalid", "SQL 批次未覆盖全部 requirements。")
    return tuple(result)


def _snapshot_tables(
    snapshots: tuple[SourceSchemaSnapshot, ...],
) -> dict[str, dict[str, ModelTable]]:
    result: dict[str, dict[str, ModelTable]] = {}
    for snapshot in snapshots:
        source_ids = {table.source_id for table in snapshot.tables}
        if len(source_ids) != 1:
            raise ReportingError("report_query_scope_invalid", "结构快照数据源范围无效。")
        source_id = next(iter(source_ids))
        if source_id in result:
            raise ReportingError("report_query_scope_invalid", "结构快照数据源重复。")
        tables: dict[str, ModelTable] = {}
        for table in snapshot.tables:
            qualified = f"{table.database.lower()}.{table.name.lower()}"
            if qualified in tables:
                raise ReportingError("report_query_scope_invalid", "结构快照数据表重复。")
            tables[qualified] = table
        result[source_id] = tables
    return result


def _validate_requirement_scope(
    requirement: QueryRequirement,
    *,
    database: str,
    snapshot_tables: dict[str, ModelTable],
    measure_semantics: dict[str, MeasureSemantic],
) -> None:
    available_dimensions: set[str] = set()
    table_columns: dict[str, set[str]] = {}
    for requested in requirement.tables:
        qualified = _qualified_requirement_table(requested.table, database)
        table = snapshot_tables.get(qualified)
        if table is None:
            raise ReportingError("report_query_scope_invalid", "取数需求引用了结构快照外的数据表。")
        columns = {column.name.lower() for column in table.columns}
        required = {
            requested.period_column.lower(),
            *requested.measure_columns,
            *requirement.grain_columns,
        }
        if required - columns:
            raise ReportingError("report_query_scope_invalid", "取数需求引用了结构快照外的字段。")
        table_prefix = f"{requirement.source_id}.{qualified}.".lower()
        declared_measure_columns = {
            field_ref.rsplit(".", 1)[-1]
            for field_ref in measure_semantics
            if field_ref.startswith(table_prefix)
        }
        for measure in requested.measure_columns:
            field_ref = f"{requirement.source_id}.{qualified}.{measure}".lower()
            semantic = measure_semantics.get(field_ref)
            if semantic is None:
                raise ReportingError(
                    "report_measure_semantic_missing",
                    f"指标 {field_ref} 缺少服务端聚合语义契约。",
                )
            ungoverned_dimensions = (
                columns
                - declared_measure_columns
                - set(requirement.grain_columns)
                - set(semantic.additive_across)
                - set(semantic.exclusive_scope)
            )
            if ungoverned_dimensions:
                raise ReportingError(
                    "report_measure_additivity_invalid",
                    "指标表存在未保留、未固定且未声明为可加的维度。",
                )
        table_columns[requested.table] = columns
        available_dimensions.update(columns)
    if set(requirement.dimension_columns) - available_dimensions:
        raise ReportingError("report_query_scope_invalid", "取数需求维度不在结构快照内。")
    for relation in requirement.relations:
        join_columns = set(relation.join_columns)
        if (
            join_columns - table_columns[relation.left_table]
            or join_columns - table_columns[relation.right_table]
        ):
            raise ReportingError("report_query_scope_invalid", "表关系引用了结构快照外的连接字段。")


def _validate_query_contract(
    sql: str,
    *,
    database: str,
    requirement: QueryRequirement,
    period: ReportPeriod,
    snapshot_tables: dict[str, ModelTable],
    measure_semantics: dict[str, MeasureSemantic],
    row_preserving: bool = False,
) -> None:
    statement = parse_one(sql, read="mysql")
    scopes = tuple(traverse_scope(statement))
    expected_tables = {
        _qualified_requirement_table(item.table, database): item for item in requirement.tables
    }
    physical_scopes: list[tuple[Scope, str, RequirementTable, ModelTable]] = []
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
            snapshot_table = snapshot_tables.get(qualified)
            if table_requirement is None or snapshot_table is None:
                raise ReportingError(
                    "report_query_batch_invalid", "SQL 读取表与 requirement 不一致。"
                )
            physical_scopes.append((scope, alias, table_requirement, snapshot_table))
    if actual_tables != set(expected_tables):
        raise ReportingError("report_query_batch_invalid", "SQL 未覆盖 requirement 声明的全部表。")
    if row_preserving and len(expected_tables) != 1:
        raise ReportingError(
            "report_query_row_preserving_invalid", "原始行冲突探测只允许单表查询。"
        )

    for scope, alias, table_requirement, snapshot_table in physical_scopes:
        _validate_scope_columns(scope, alias=alias, table=snapshot_table)
        if not _has_complete_period_filter(
            scope.expression,
            alias=alias,
            column=table_requirement.period_column.lower(),
            period=period,
            granularity=table_requirement.period_granularity,
        ):
            raise ReportingError(
                "report_query_period_invalid", "SQL 必须对每张表包含完整且精确的报表期间约束。"
            )
        if row_preserving:
            if not _scope_is_row_preserving(
                scope.expression,
                grain_columns=requirement.grain_columns,
                measure_columns=table_requirement.measure_columns,
            ):
                raise ReportingError(
                    "report_query_row_preserving_invalid",
                    "原始行冲突探测必须直接投影完整 grainColumns 和 measureColumns，"
                    "不得聚合、去重、排序截断或改写金额。",
                )
        else:
            if not _scope_has_grain(scope.expression, requirement.grain_columns):
                raise ReportingError(
                    "report_query_grain_invalid", "SQL 聚合粒度与 requirement.grainColumns 不一致。"
                )
            if not _scope_has_measures(scope.expression, table_requirement.measure_columns):
                raise ReportingError(
                    "report_query_measure_invalid", "SQL 未聚合 requirement 声明的全部指标字段。"
                )
        qualified = _qualified_requirement_table(table_requirement.table, database)
        for measure in table_requirement.measure_columns:
            field_ref = f"{requirement.source_id}.{qualified}.{measure}".lower()
            semantic = measure_semantics.get(field_ref)
            if semantic is None:
                raise ReportingError(
                    "report_measure_semantic_missing", "SQL 指标缺少服务端聚合语义契约。"
                )
            if not row_preserving and not _scope_has_semantic_measure(
                scope.expression,
                alias=alias,
                column=measure,
                aggregation=semantic.aggregation,
            ):
                raise ReportingError(
                    "report_query_aggregation_invalid",
                    "SQL 指标聚合函数与服务端语义契约不一致。",
                )
            for column, value in semantic.exclusive_scope.items():
                if not _has_exact_scope_filter(
                    scope.expression, alias=alias, column=column, value=value
                ):
                    raise ReportingError(
                        "report_query_scope_semantic_invalid",
                        "SQL 缺少指标语义契约要求的固定口径过滤。",
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
            _validate_aggregated_joins(scope.expression, requirement.relations)


def _validate_scope_columns(scope: Scope, *, alias: str, table: ModelTable) -> None:
    allowed = {column.name.lower() for column in table.columns}
    qualifiers = {"", alias.lower(), table.name.lower()}
    for column in scope.columns:
        qualifier = str(column.table or "").lower()
        if qualifier in qualifiers and str(column.name).lower() not in allowed:
            raise ReportingError("report_query_scope_invalid", "SQL 引用了结构快照外的字段。")


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


def _scope_is_row_preserving(
    expression: exp.Expression,
    *,
    grain_columns: tuple[str, ...],
    measure_columns: tuple[str, ...],
) -> bool:
    if not isinstance(expression, exp.Select):
        return False
    if (
        expression.args.get("group") is not None
        or expression.args.get("distinct")
        or expression.args.get("limit") is not None
        or expression.args.get("order") is not None
        or any(isinstance(item, (exp.AggFunc, exp.Window)) for item in expression.walk())
    ):
        return False
    projected: list[str] = []
    for item in expression.expressions:
        column = item.this if isinstance(item, exp.Alias) else item
        if not isinstance(column, exp.Column):
            return False
        if isinstance(item, exp.Alias) and item.alias.lower() != column.name.lower():
            return False
        projected.append(column.name.lower())
    expected = {*grain_columns, *measure_columns}
    return len(projected) == len(set(projected)) and set(projected) == expected


def _scope_has_measures(expression: exp.Expression, measure_columns: tuple[str, ...]) -> bool:
    aggregated_columns = {
        str(column.name).lower()
        for aggregate in expression.find_all(exp.AggFunc)
        for column in aggregate.find_all(exp.Column)
    }
    return set(measure_columns).issubset(aggregated_columns)


def _scope_has_semantic_measure(
    expression: exp.Expression,
    *,
    alias: str,
    column: str,
    aggregation: str,
) -> bool:
    for aggregate in expression.find_all(exp.AggFunc):
        if not any(_matches_column(item, alias, column) for item in aggregate.find_all(exp.Column)):
            continue
        if aggregation == "sum" and isinstance(aggregate, exp.Sum):
            return True
        if aggregation == "average" and isinstance(aggregate, exp.Avg):
            return True
        if aggregation == "min" and isinstance(aggregate, exp.Min):
            return True
        if aggregation == "max" and isinstance(aggregate, exp.Max):
            return True
        is_distinct = isinstance(aggregate.this, exp.Distinct) or bool(
            aggregate.args.get("distinct")
        )
        if aggregation == "count" and isinstance(aggregate, exp.Count) and not is_distinct:
            return True
        if aggregation == "count_distinct" and isinstance(aggregate, exp.Count) and is_distinct:
            return True
    return False


def _has_exact_scope_filter(
    expression: exp.Expression,
    *,
    alias: str,
    column: str,
    value: str,
) -> bool:
    where = expression.args.get("where")
    if where is None:
        return False
    for predicate in _and_predicates(where.this):
        if not isinstance(predicate, exp.EQ):
            continue
        left, right = predicate.this, predicate.expression
        literal = right if _matches_column(left, alias, column) else left
        if not (_matches_column(left, alias, column) or _matches_column(right, alias, column)):
            continue
        if isinstance(literal, exp.Literal) and str(literal.this) == value:
            return True
    return False


def _has_complete_period_filter(
    expression: exp.Expression,
    *,
    alias: str,
    column: str,
    period: ReportPeriod,
    granularity: str,
) -> bool:
    where = expression.args.get("where")
    if where is None:
        return False
    lower = False
    upper = False
    for predicate in _and_predicates(where.this):
        if isinstance(predicate, exp.Between) and _matches_column(predicate.this, alias, column):
            if granularity == "year":
                valid = (
                    _literal_year(predicate.args.get("low")) == period.start.year
                    and _literal_year(predicate.args.get("high")) == period.end.year
                )
            elif granularity == "month":
                valid = _literal_month(predicate.args.get("low")) == (
                    period.start.year,
                    period.start.month,
                ) and _literal_month(predicate.args.get("high")) == (
                    period.end.year,
                    period.end.month,
                )
            else:
                valid = (
                    _literal_date(predicate.args.get("low")) == period.start
                    and _literal_date(predicate.args.get("high")) == period.end
                )
            if not valid:
                return False
            lower = True
            upper = True
        elif isinstance(predicate, (exp.GTE, exp.GT, exp.LTE, exp.LT)):
            left, right = predicate.this, predicate.expression
            if _matches_column(left, alias, column):
                valid_lower, valid_upper = _period_bounds(
                    predicate, right, period=period, granularity=granularity
                )
                if not valid_lower and not valid_upper:
                    return False
                lower = lower or valid_lower
                upper = upper or valid_upper
            elif _matches_column(right, alias, column):
                valid_lower, valid_upper = _reverse_period_bounds(
                    predicate, left, period=period, granularity=granularity
                )
                if not valid_lower and not valid_upper:
                    return False
                lower = lower or valid_lower
                upper = upper or valid_upper
        elif isinstance(predicate, exp.EQ) and (
            _matches_column(predicate.this, alias, column)
            or _matches_column(predicate.expression, alias, column)
        ):
            value_expression = (
                predicate.expression
                if _matches_column(predicate.this, alias, column)
                else predicate.this
            )
            if granularity == "year":
                valid = (
                    period.start.year == period.end.year
                    and _literal_year(value_expression) == period.start.year
                )
            elif granularity == "month":
                start_month = (period.start.year, period.start.month)
                valid = (
                    start_month == (period.end.year, period.end.month)
                    and _literal_month(value_expression) == start_month
                )
            else:
                valid = (
                    period.start == period.end and _literal_date(value_expression) == period.start
                )
            if not valid:
                return False
            lower = True
            upper = True
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
    normalized = str(expression.this).replace("/", "").replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        return None
    try:
        return date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:]))
    except ValueError:
        return None


def _literal_year(expression: exp.Expression | None) -> int | None:
    if not isinstance(expression, exp.Literal):
        return None
    value = str(expression.this)
    if len(value) != 4 or not value.isdigit():
        return None
    return int(value)


def _literal_month(expression: exp.Expression | None) -> tuple[int, int] | None:
    if not isinstance(expression, exp.Literal):
        return None
    normalized = str(expression.this).replace("/", "").replace("-", "")
    if len(normalized) != 6 or not normalized.isdigit():
        return None
    year, month = int(normalized[:4]), int(normalized[4:])
    return (year, month) if 1 <= month <= 12 else None


def _next_month(value: tuple[int, int]) -> tuple[int, int]:
    year, month = value
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _period_bounds(
    predicate: exp.Expression,
    value_expression: exp.Expression | None,
    *,
    period: ReportPeriod,
    granularity: str,
) -> tuple[bool, bool]:
    if granularity == "year":
        year_value = _literal_year(value_expression)
        return (
            isinstance(predicate, exp.GTE) and year_value == period.start.year,
            (isinstance(predicate, exp.LTE) and year_value == period.end.year)
            or (isinstance(predicate, exp.LT) and year_value == period.end.year + 1),
        )
    if granularity == "month":
        month_value = _literal_month(value_expression)
        end_month = (period.end.year, period.end.month)
        return (
            isinstance(predicate, exp.GTE)
            and month_value == (period.start.year, period.start.month),
            (isinstance(predicate, exp.LTE) and month_value == end_month)
            or (isinstance(predicate, exp.LT) and month_value == _next_month(end_month)),
        )
    date_value = _literal_date(value_expression)
    return (
        isinstance(predicate, exp.GTE) and date_value == period.start,
        (isinstance(predicate, exp.LTE) and date_value == period.end)
        or (isinstance(predicate, exp.LT) and date_value == period.end + timedelta(days=1)),
    )


def _reverse_period_bounds(
    predicate: exp.Expression,
    value_expression: exp.Expression | None,
    *,
    period: ReportPeriod,
    granularity: str,
) -> tuple[bool, bool]:
    if granularity == "year":
        year_value = _literal_year(value_expression)
        return (
            isinstance(predicate, exp.LTE) and year_value == period.start.year,
            (isinstance(predicate, exp.GTE) and year_value == period.end.year)
            or (isinstance(predicate, exp.GT) and year_value == period.end.year + 1),
        )
    if granularity == "month":
        month_value = _literal_month(value_expression)
        end_month = (period.end.year, period.end.month)
        return (
            isinstance(predicate, exp.LTE)
            and month_value == (period.start.year, period.start.month),
            (isinstance(predicate, exp.GTE) and month_value == end_month)
            or (isinstance(predicate, exp.GT) and month_value == _next_month(end_month)),
        )
    date_value = _literal_date(value_expression)
    return (
        isinstance(predicate, exp.LTE) and date_value == period.start,
        (isinstance(predicate, exp.GTE) and date_value == period.end)
        or (isinstance(predicate, exp.GT) and date_value == period.end + timedelta(days=1)),
    )


def _validate_aggregated_joins(
    expression: exp.Expression, relations: tuple[RequirementRelation, ...]
) -> None:
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
        if not any(set(relation.join_columns).issubset(keys) for relation in relations):
            raise ReportingError(
                "report_query_join_grain_invalid",
                "跨表聚合结果必须按 requirement 声明的 relation 键等值连接。",
            )


def require_approved_sql(approved: ApprovedQuery, execution_sql: str) -> str:
    if normalized_sql_hash(execution_sql) != approved.sql_hash or execution_sql != approved.sql:
        raise ReportingError("report_sql_hash_mismatch", "执行 SQL 与审核原文不一致。")
    return execution_sql


def validate_lineage(
    approved: tuple[ApprovedQuery, ...], lineage: tuple[DatasetLineage, ...]
) -> None:
    expected = {
        (
            item.source_id,
            item.requirement_id,
            item.sql_hash,
            item.query_window_id,
            item.period_roles,
        )
        for item in approved
    }
    actual = {
        (
            item.source_id,
            item.requirement_id,
            item.sql_hash,
            item.query_window_id,
            item.period_roles,
        )
        for item in lineage
    }
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
