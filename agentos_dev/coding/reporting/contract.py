from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlglot import exp, parse

from .models import ReportingError

CONTRACT_VERSION = "1"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CONNECTION_KEYS = frozenset(
    {
        "connection",
        "connectionstring",
        "databaseurl",
        "dsn",
        "dsnEnv",
        "host",
        "hostname",
        "password",
        "port",
        "pwd",
        "url",
        "user",
        "username",
    }
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class ReportPeriod(StrictModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_range(self) -> ReportPeriod:
        if self.start > self.end:
            raise ValueError("period.start 不能晚于 period.end")
        return self


class SchemaInput(StrictModel):
    ddl: str | None = Field(default=None, min_length=1, max_length=1_048_576)
    schema_hash: str | None = Field(default=None, alias="schemaHash", pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_value(self) -> SchemaInput:
        if self.ddl is None and self.schema_hash is None:
            raise ValueError("schemaInput 至少需要 ddl 或 schemaHash")
        return self


class ReportRequestEnvelope(StrictModel):
    version: Literal["1"] = "1"
    report_goal: str = Field(alias="reportGoal", min_length=1, max_length=20_000)
    period: ReportPeriod
    source_ids: tuple[str, ...] | None = Field(default=None, alias="sourceIds", max_length=20)
    agent_id: str | None = Field(default=None, alias="agentId", min_length=1, max_length=128)
    schema_input: SchemaInput | None = Field(default=None, alias="schemaInput")

    @field_validator("report_goal", "agent_id")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("source_ids")
    @classmethod
    def validate_sources(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        normalized = tuple(item.strip() for item in value)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("sourceIds 不能为空或重复")
        if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", item) for item in normalized):
            raise ValueError("sourceIds 包含无效值")
        return normalized

    @classmethod
    def from_untrusted(cls, value: Any) -> ReportRequestEnvelope:
        forbidden = _find_connection_input(value)
        if forbidden:
            raise ReportingError(
                "report_connection_input_forbidden",
                f"报表请求禁止包含连接字段: {', '.join(sorted(forbidden))}。",
            )
        try:
            return cls.model_validate(value)
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError("report_request_invalid", "报表请求不符合 v1 契约。") from error

    def workflow_payload(self, *, default_source_ids: tuple[str, ...]) -> dict[str, Any]:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        payload["sourceIds"] = list(self.source_ids or default_source_ids)
        return payload


class ReportingAgent(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)
    enabled: bool
    model_revision: str = Field(alias="modelRevision", min_length=1, max_length=128)


class AgentQueryRequest(StrictModel):
    contract_version: Literal["1"] = Field(default="1", alias="contractVersion")
    source_ids: tuple[str, ...] = Field(alias="sourceIds", min_length=1, max_length=20)


class AgentQueryResponse(StrictModel):
    revision: str = Field(min_length=1, max_length=128)
    agents: tuple[ReportingAgent, ...] = Field(max_length=100)


class ModelTermsRequest(StrictModel):
    contract_version: Literal["1"] = Field(default="1", alias="contractVersion")
    agent_id: str = Field(alias="agentId", min_length=1, max_length=128)
    source_ids: tuple[str, ...] = Field(alias="sourceIds", min_length=1, max_length=20)


class SourceRef(StrictModel):
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)


class ModelColumn(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    data_type: str = Field(alias="dataType", min_length=1, max_length=128)
    nullable: bool
    description: str = Field(default="", max_length=2_000)


class ModelTable(StrictModel):
    source_id: str = Field(alias="sourceId", min_length=1, max_length=64)
    database: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=4_000)
    columns: tuple[ModelColumn, ...] = Field(min_length=1, max_length=500)


class ModelTerm(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4_000)
    field_refs: tuple[str, ...] = Field(default=(), alias="fieldRefs", max_length=100)


class ModelTermsResponse(StrictModel):
    revision: str = Field(min_length=1, max_length=128)
    schema_hash: str = Field(alias="schemaHash", pattern=SHA256_PATTERN)
    source_refs: tuple[SourceRef, ...] = Field(alias="sourceRefs", min_length=1, max_length=20)
    tables: tuple[ModelTable, ...] = Field(min_length=1, max_length=200)
    terms: tuple[ModelTerm, ...] = Field(default=(), max_length=1_000)

    @model_validator(mode="after")
    def validate_schema_hash(self) -> ModelTermsResponse:
        if schema_hash(self.tables) != self.schema_hash:
            raise ValueError("schemaHash 与 tables 不一致")
        return self


class SourceSchemaSnapshot(StrictModel):
    source: Literal["metadata_api", "ddl"]
    revision: str
    schema_hash: str = Field(alias="schemaHash", pattern=SHA256_PATTERN)
    tables: tuple[ModelTable, ...]


def schema_hash(tables: tuple[ModelTable, ...] | list[ModelTable]) -> str:
    structure = [
        {
            "sourceId": table.source_id.lower(),
            "database": table.database.lower(),
            "name": table.name.lower(),
            "columns": [
                {
                    "name": column.name.lower(),
                    "dataType": _normalize_type(column.data_type),
                    "nullable": column.nullable,
                }
                for column in sorted(table.columns, key=lambda item: item.name.lower())
            ],
        }
        for table in sorted(
            tables,
            key=lambda item: (item.source_id.lower(), item.database.lower(), item.name.lower()),
        )
    ]
    encoded = json.dumps(structure, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def parse_ddl(ddl: str, *, source_id: str, default_database: str) -> tuple[ModelTable, ...]:
    if not isinstance(ddl, str) or not ddl.strip() or len(ddl.encode()) > 1_048_576:
        raise ReportingError("report_ddl_invalid", "DDL 必须为非空且不超过 1 MiB。")
    try:
        statements = parse(ddl, read="mysql")
    except Exception as error:
        raise ReportingError("report_ddl_invalid", "DDL 语法无效。") from error
    if not statements or len(statements) > 200:
        raise ReportingError("report_ddl_invalid", "DDL 表数量无效。")
    tables: list[ModelTable] = []
    seen: set[str] = set()
    for statement in statements:
        if (
            not isinstance(statement, exp.Create)
            or str(statement.args.get("kind") or "").upper() != "TABLE"
        ):
            raise ReportingError("report_ddl_invalid", "只接受 CREATE TABLE DDL。")
        schema = statement.this
        if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
            raise ReportingError("report_ddl_invalid", "DDL 必须包含明确的表和字段。")
        table_expr = schema.this
        database = str(table_expr.db or default_database).lower()
        name = str(table_expr.name or "").lower()
        key = f"{database}.{name}"
        if not name or key in seen:
            raise ReportingError("report_ddl_invalid", "DDL 表名为空或重复。")
        columns: list[ModelColumn] = []
        column_names: set[str] = set()
        for item in schema.expressions:
            if not isinstance(item, exp.ColumnDef):
                continue
            column_name = str(item.name or "").lower()
            if not column_name or column_name in column_names:
                raise ReportingError("report_ddl_invalid", "DDL 字段名为空或重复。")
            kind = item.args.get("kind")
            if not isinstance(kind, exp.DataType):
                raise ReportingError("report_ddl_invalid", "DDL 字段必须声明数据类型。")
            constraints = tuple(item.args.get("constraints") or ())
            nullable = not any(
                isinstance(constraint.args.get("kind"), exp.NotNullColumnConstraint)
                for constraint in constraints
                if isinstance(constraint, exp.ColumnConstraint)
            )
            columns.append(
                ModelColumn(name=column_name, dataType=kind.sql(dialect="mysql"), nullable=nullable)
            )
            column_names.add(column_name)
        if not columns:
            raise ReportingError("report_ddl_invalid", "DDL 表必须包含字段。")
        tables.append(
            ModelTable(
                sourceId=source_id,
                database=database,
                name=name,
                columns=tuple(columns),
            )
        )
        seen.add(key)
    return tuple(tables)


def validate_catalog(
    requested: tuple[ModelTable, ...],
    catalog: tuple[ModelTable, ...],
    *,
    allowed_tables: tuple[str, ...],
) -> None:
    allowed = {item.lower() for item in allowed_tables}
    actual = {(table.database.lower(), table.name.lower()): table for table in catalog}
    for table in requested:
        qualified = f"{table.database.lower()}.{table.name.lower()}"
        if qualified not in allowed:
            raise ReportingError(
                "report_schema_not_allowed", f"数据表 {qualified} 不在服务端白名单。"
            )
        current = actual.get((table.database.lower(), table.name.lower()))
        if current is None:
            raise ReportingError("report_catalog_drift", f"实时 catalog 缺少数据表 {qualified}。")
        current_columns = {column.name.lower(): column for column in current.columns}
        for column in table.columns:
            actual_column = current_columns.get(column.name.lower())
            if actual_column is None or (
                _normalize_type(actual_column.data_type) != _normalize_type(column.data_type)
                or actual_column.nullable != column.nullable
            ):
                raise ReportingError(
                    "report_catalog_drift", f"实时 catalog 字段 {qualified}.{column.name} 已变化。"
                )


def _normalize_type(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _find_connection_input(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = re.sub(r"[_-]", "", str(key)).lower()
            for forbidden in _CONNECTION_KEYS:
                if normalized == re.sub(r"[_-]", "", forbidden).lower():
                    found.add(str(key))
            found.update(_find_connection_input(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.update(_find_connection_input(item))
    return found
