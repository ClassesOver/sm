from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_serializer,
    field_validator,
    model_validator,
)
from sqlglot import exp, parse

from .hospital_operation.domains import DOMAIN_CODES
from .models import ReportingError

REPORT_WORKFLOW_SCOPE_STATE_KEY = "report_workflow_scope"

SHA256_PATTERN = r"^[0-9a-f]{64}$"
FIELD_REF_PATTERN = (
    r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}\."
    r"[A-Za-z_][A-Za-z0-9_$]{0,127}$"
)
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

    @field_serializer("start", "end")
    def serialize_date(self, value: date) -> str:
        return value.isoformat()


class ReportPeriodWindow(StrictModel):
    """查询/事实中的期间角色；窗口边界使用闭区间。"""

    role: Literal["current", "yoy", "mom"]
    period: ReportPeriod
    query_window_id: str = Field(alias="queryWindowId", min_length=1, max_length=128)


class ReportPeriodWindows(StrictModel):
    windows: tuple[ReportPeriodWindow, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_roles(self) -> ReportPeriodWindows:
        roles = [item.role for item in self.windows]
        if "current" not in roles or len(roles) != len(set(roles)):
            raise ValueError("期间窗口必须包含唯一 current 角色")
        expected_order = [role for role in ("current", "yoy", "mom") if role in roles]
        if roles != expected_order:
            raise ValueError("期间窗口必须按 current、yoy、mom 稳定排序")
        ids_by_period: dict[tuple[date, date], str] = {}
        periods_by_id: dict[str, tuple[date, date]] = {}
        for item in self.windows:
            bounds = (item.period.start, item.period.end)
            if ids_by_period.setdefault(bounds, item.query_window_id) != item.query_window_id:
                raise ValueError("相同期间边界必须共享 queryWindowId")
            if periods_by_id.setdefault(item.query_window_id, bounds) != bounds:
                raise ValueError("同一 queryWindowId 不得表示不同期间边界")
        return self

    def public_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)


class SchemaInput(StrictModel):
    ddl: str | None = Field(default=None, min_length=1, max_length=1_048_576)
    schema_hash: str | None = Field(default=None, alias="schemaHash", pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def require_value(self) -> SchemaInput:
        if self.ddl is None and self.schema_hash is None:
            raise ValueError("schemaInput 至少需要 ddl 或 schemaHash")
        return self


class ReportFileInput(StrictModel):
    path: str = Field(min_length=1, max_length=1024)
    filename: str = Field(min_length=1, max_length=255)
    size: PositiveInt
    sha256: str = Field(pattern=SHA256_PATTERN)
    media_type: str | None = Field(default=None, alias="mediaType", max_length=128)


class ReportRequestEnvelope(StrictModel):
    version: Literal["1"] = "1"
    report_goal: str = Field(alias="reportGoal", min_length=1, max_length=20_000)
    report_type: Literal["comprehensive", "topic"] | None = Field(default=None, alias="reportType")
    domains: tuple[str, ...] | None = Field(default=None, max_length=6)
    period: ReportPeriod
    source_ids: tuple[str, ...] | None = Field(default=None, alias="sourceIds", max_length=20)
    schema_input: SchemaInput | None = Field(default=None, alias="schemaInput")
    comparison_roles: tuple[Literal["yoy", "mom"], ...] = Field(
        default=("yoy",), alias="comparisonRoles", max_length=2
    )
    visualization_mode: Literal["auto", "static", "interactive"] = Field(
        default="auto", alias="visualizationMode"
    )
    file_inputs: tuple[ReportFileInput, ...] = Field(default=(), alias="fileInputs", max_length=20)

    @field_validator("report_goal")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        return value.strip() if isinstance(value, str) else value

    @field_validator("domains")
    @classmethod
    def validate_domains(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        if value is None:
            return None
        normalized: list[str] = []
        for item in value:
            code = item.strip()
            if code not in DOMAIN_CODES:
                raise ValueError("domains 只能包含医院运营六域稳定代码，不接受中文别名")
            if code not in normalized:
                normalized.append(code)
        if not normalized:
            raise ValueError("domains 不能为空")
        # 对外序列化始终使用六域稳定顺序，避免模型提交顺序影响哈希和门禁。
        return tuple(code for code in DOMAIN_CODES if code in normalized)

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

    @field_validator("comparison_roles")
    @classmethod
    def validate_comparison_roles(
        cls, value: tuple[Literal["yoy", "mom"], ...]
    ) -> tuple[Literal["yoy", "mom"], ...]:
        if len(value) != len(set(value)):
            raise ValueError("comparisonRoles 不能重复")
        return tuple(role for role in ("yoy", "mom") if role in value)

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

    def period_windows(
        self, *, granularity: Literal["date", "month", "year"] = "date"
    ) -> ReportPeriodWindows:
        """按请求声明生成比较窗口；物理边界相同的角色共享 queryWindowId。"""
        from .data_source.period import build_period_windows

        generated = build_period_windows(
            self.period.start,
            self.period.end,
            include_yoy="yoy" in self.comparison_roles,
            include_mom="mom" in self.comparison_roles,
            granularity=granularity,
        )
        by_bounds: dict[tuple[date, date], str] = {}
        windows: list[ReportPeriodWindow] = []
        for item in generated.windows:
            bounds = (item.start, item.end)
            query_id = by_bounds.setdefault(
                bounds,
                "window-"
                + hashlib.sha256(
                    f"{granularity}:{item.start.isoformat()}:{item.end.isoformat()}".encode()
                ).hexdigest()[:24],
            )
            windows.append(
                ReportPeriodWindow(
                    role=item.role,
                    period=ReportPeriod(start=item.start, end=item.end),
                    queryWindowId=query_id,
                )
            )
        return ReportPeriodWindows(windows=tuple(windows))


class ReportPromptInput(StrictModel):
    version: Literal["1"] = "1"
    prompt: str = Field(min_length=1, max_length=20_000)

    @field_validator("prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        return value.strip()


class ReportingWorkflowInput(StrictModel):
    """AgentOS 可校验的 Workflow 顶层联合输入。"""

    version: Literal["1"] = "1"
    prompt: str | None = Field(default=None, min_length=1, max_length=20_000)
    report_goal: str | None = Field(
        default=None, alias="reportGoal", min_length=1, max_length=20_000
    )
    report_type: Literal["comprehensive", "topic"] | None = Field(default=None, alias="reportType")
    domains: tuple[str, ...] | None = Field(default=None, max_length=6)
    period: ReportPeriod | None = None
    source_ids: tuple[str, ...] | None = Field(default=None, alias="sourceIds", max_length=20)
    schema_input: SchemaInput | None = Field(default=None, alias="schemaInput")
    comparison_roles: tuple[Literal["yoy", "mom"], ...] | None = Field(
        default=None, alias="comparisonRoles", max_length=2
    )
    file_inputs: tuple[ReportFileInput, ...] | None = Field(
        default=None, alias="fileInputs", max_length=20
    )

    @model_validator(mode="after")
    def validate_variant(self) -> ReportingWorkflowInput:
        if self.prompt is not None:
            if any(
                value is not None
                for value in (
                    self.report_goal,
                    self.report_type,
                    self.domains,
                    self.period,
                    self.source_ids,
                    self.schema_input,
                    self.comparison_roles,
                    self.file_inputs,
                )
            ):
                raise ValueError("prompt 输入不能混用 Envelope 字段")
            return self
        if self.report_goal is None or self.period is None:
            raise ValueError("必须提供 prompt 或完整 ReportRequestEnvelope")
        ReportRequestEnvelope.from_untrusted(
            self.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        return self

    def request(self) -> ReportPromptInput | ReportRequestEnvelope:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if self.prompt is not None:
            return ReportPromptInput.model_validate(payload)
        return ReportRequestEnvelope.from_untrusted(payload)


def parse_reporting_workflow_input(value: str) -> ReportingWorkflowInput:
    """按 CLI 与 AgentOS 共用规则解析自然语言或 v1 Envelope JSON。"""

    normalized = str(value or "").strip()
    if not normalized:
        raise ReportingError("report_request_invalid", "报表请求不能为空。")
    try:
        parsed = json.loads(normalized)
    except ValueError:
        parsed = {"version": "1", "prompt": normalized}
    if not isinstance(parsed, dict):
        raise ReportingError("report_request_invalid", "报表请求不符合 v1 契约。")
    try:
        return ReportingWorkflowInput.model_validate(parsed)
    except Exception as error:
        raise ReportingError("report_request_invalid", "报表请求不符合 v1 契约。") from error


class ReportingAgent(StrictModel):
    code: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2_000)


class MetadataAgent(StrictModel):
    id: PositiveInt
    name: str = Field(min_length=1, max_length=200)
    desc: str = Field(default="", max_length=2_000)


class MetadataAgentResponse(StrictModel):
    agent_list: tuple[MetadataAgent, ...] = Field(max_length=100)


class RawDdlModel(StrictModel):
    id: PositiveInt
    model_name: str = Field(alias="modelName", min_length=1, max_length=200)
    model_desc: str = Field(default="", alias="modelDesc", max_length=4_000)
    ddl: str = Field(min_length=1, max_length=1_048_576)

    @field_validator("ddl")
    @classmethod
    def validate_ddl_bytes(cls, value: str) -> str:
        if len(value.encode()) > 1_048_576:
            raise ValueError("单项 DDL 不得超过 1 MiB")
        return value


class MetadataTerm(StrictModel):
    id: PositiveInt
    key: str = Field(min_length=1, max_length=200)
    value: str = Field(default="", max_length=4_000)


class MeasureSemantic(StrictModel):
    field_ref: str = Field(alias="fieldRef", pattern=FIELD_REF_PATTERN)
    aggregation: Literal["sum", "average", "min", "max", "count", "count_distinct"]
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    additive_across: tuple[str, ...] = Field(default=(), alias="additiveAcross", max_length=100)
    exclusive_scope: dict[str, str] = Field(
        default_factory=dict, alias="exclusiveScope", max_length=100
    )
    reconcile_with: str | None = Field(
        default=None, alias="reconcileWith", pattern=FIELD_REF_PATTERN
    )
    tolerance: float | None = Field(default=None, ge=0)

    @field_validator("additive_across")
    @classmethod
    def validate_additive_across(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip().lower() for item in value)
        if len(normalized) != len(set(normalized)) or any(
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", item) for item in normalized
        ):
            raise ValueError("additiveAcross 包含重复或无效字段")
        return normalized

    @field_validator("exclusive_scope")
    @classmethod
    def validate_exclusive_scope(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {key.strip().lower(): item.strip() for key, item in value.items()}
        if len(normalized) != len(value) or any(
            not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key) or not item
            for key, item in normalized.items()
        ):
            raise ValueError("exclusiveScope 包含无效字段或空值")
        return normalized

    @model_validator(mode="after")
    def validate_reconciliation(self) -> MeasureSemantic:
        if (self.reconcile_with is None) != (self.tolerance is None):
            raise ValueError("reconcileWith 与 tolerance 必须同时提供")
        return self


class MetadataModelResponse(StrictModel):
    ddl: tuple[RawDdlModel, ...] = Field(min_length=1, max_length=200)
    term: tuple[MetadataTerm, ...] = Field(default=(), max_length=1_000)
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )


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

    @field_validator("field_refs")
    @classmethod
    def validate_field_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value) or any(
            not re.fullmatch(FIELD_REF_PATTERN, item) for item in value
        ):
            raise ValueError("fieldRefs 包含重复或无效引用")
        return value


class ModelTermsResponse(StrictModel):
    revision: str = Field(min_length=1, max_length=128)
    schema_hash: str = Field(alias="schemaHash", pattern=SHA256_PATTERN)
    source_refs: tuple[SourceRef, ...] = Field(alias="sourceRefs", min_length=1, max_length=20)
    ddl_models: tuple[RawDdlModel, ...] = Field(alias="ddlModels", min_length=1, max_length=200)
    tables: tuple[ModelTable, ...] = Field(min_length=1, max_length=200)
    terms: tuple[ModelTerm, ...] = Field(default=(), max_length=1_000)
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )

    @model_validator(mode="after")
    def validate_schema_hash(self) -> ModelTermsResponse:
        if schema_hash(self.tables) != self.schema_hash:
            raise ValueError("schemaHash 与 tables 不一致")
        if len(self.ddl_models) != len(self.tables):
            raise ValueError("ddlModels 与 tables 数量不一致")
        source_ids = {item.source_id for item in self.source_refs}
        table_sources = {item.source_id for item in self.tables}
        if len(source_ids) != len(self.source_refs) or source_ids != table_sources:
            raise ValueError("sourceRefs 与 tables 数据源不一致")
        codes = [item.code for item in self.terms]
        available = {
            f"{table.source_id}.{table.database}.{table.name}.{column.name}".lower()
            for table in self.tables
            for column in table.columns
        }
        if len(codes) != len(set(codes)) or any(
            field_ref.lower() not in available
            for term in self.terms
            for field_ref in term.field_refs
        ):
            raise ValueError("terms 包含重复 code 或未知 fieldRef")
        _validate_measure_semantics(self.measure_semantics, self.tables)
        return self


class SourceSchemaSnapshot(StrictModel):
    source: Literal["metadata_api", "ddl"]
    revision: str
    schema_hash: str = Field(alias="schemaHash", pattern=SHA256_PATTERN)
    ddl_models: tuple[RawDdlModel, ...] = Field(default=(), alias="ddlModels", max_length=200)
    tables: tuple[ModelTable, ...]
    terms: tuple[ModelTerm, ...] = Field(default=(), max_length=1_000)
    measure_semantics: tuple[MeasureSemantic, ...] = Field(
        default=(), alias="measureSemantics", max_length=2_000
    )

    @model_validator(mode="after")
    def validate_measure_semantics(self) -> SourceSchemaSnapshot:
        _validate_measure_semantics(self.measure_semantics, self.tables)
        return self


def _validate_measure_semantics(
    semantics: tuple[MeasureSemantic, ...], tables: tuple[ModelTable, ...]
) -> None:
    available = {
        f"{table.source_id}.{table.database}.{table.name}.{column.name}".lower()
        for table in tables
        for column in table.columns
    }
    semantic_refs = [item.field_ref.lower() for item in semantics]
    if len(semantic_refs) != len(set(semantic_refs)) or any(
        field_ref not in available for field_ref in semantic_refs
    ):
        raise ValueError("measureSemantics 包含重复或未知 fieldRef")
    table_columns = {
        f"{table.source_id}.{table.database}.{table.name}".lower(): {
            column.name.lower() for column in table.columns
        }
        for table in tables
    }
    for item in semantics:
        table_ref = item.field_ref.rsplit(".", 1)[0].lower()
        columns = table_columns.get(table_ref, set())
        if set(item.additive_across) - columns or set(item.exclusive_scope) - columns:
            raise ValueError("measureSemantics 引用了指标表之外的维度字段")
        if item.reconcile_with and item.reconcile_with.lower() not in available:
            raise ValueError("measureSemantics.reconcileWith 引用了未知 fieldRef")


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


def _normalize_type(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def parse_ddl(ddl: str, *, source_id: str, default_database: str) -> tuple[ModelTable, ...]:
    if not isinstance(ddl, str) or not ddl.strip() or len(ddl.encode()) > 1_048_576:
        raise ReportingError("report_ddl_invalid", "DDL 必须为非空且不超过 1 MiB。")
    try:
        statements = parse(ddl, read="mysql")
    except Exception as error:
        raise ReportingError("report_ddl_invalid", "DDL 语法无效。") from error
    if not statements:
        raise ReportingError("report_ddl_invalid", "DDL 表数量无效。")
    creates: list[exp.Create] = []
    comments: list[exp.Comment] = []
    for statement in statements:
        if (
            isinstance(statement, exp.Create)
            and str(statement.args.get("kind") or "").upper() == "TABLE"
        ):
            creates.append(statement)
        elif isinstance(statement, exp.Comment):
            comments.append(statement)
        else:
            raise ReportingError("report_ddl_invalid", "只接受 CREATE TABLE 及其 COMMENT DDL。")
    if not creates or len(creates) > 200:
        raise ReportingError("report_ddl_invalid", "DDL 表数量无效。")

    tables: list[ModelTable] = []
    seen: set[str] = set()
    table_comments: dict[tuple[str, str], str | None] = {}
    column_comments: dict[tuple[str, str, str], str | None] = {}
    for statement in creates:
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
                and not bool(constraint.args["kind"].args.get("allow_null"))
                for constraint in constraints
                if isinstance(constraint, exp.ColumnConstraint)
            )
            description = _column_comment(constraints)
            columns.append(
                ModelColumn(
                    name=column_name,
                    dataType=kind.sql(dialect="mysql"),
                    nullable=nullable,
                    description=description or "",
                )
            )
            column_names.add(column_name)
            column_comments[(database, name, column_name)] = description
        if not columns:
            raise ReportingError("report_ddl_invalid", "DDL 表必须包含字段。")
        description = _table_comment(statement)
        table_key = (database, name)
        table_comments[table_key] = description
        tables.append(
            ModelTable(
                sourceId=source_id,
                database=database,
                name=name,
                description=description or "",
                columns=tuple(columns),
            )
        )
        seen.add(key)

    # COMMENT ON 只能补充同一批 CREATE TABLE 的描述，不能成为独立修改语句。
    # 目标必须存在且与内联 COMMENT 一致，避免两种语法互转时发生错绑或覆盖。
    external_targets: set[tuple[str, str, str, str]] = set()
    for statement in comments:
        database, table_name, comment_column_name, comment_description = _separate_comment(
            statement,
            default_database=default_database,
        )
        target = (
            "COLUMN" if comment_column_name is not None else "TABLE",
            database,
            table_name,
            comment_column_name or "",
        )
        if target in external_targets:
            raise ReportingError("report_ddl_invalid", "COMMENT 目标重复。")
        external_targets.add(target)
        table_key = (database, table_name)
        if table_key not in table_comments:
            raise ReportingError("report_ddl_invalid", "COMMENT 引用了未知数据表。")
        if comment_column_name is None:
            inline = table_comments[table_key]
            if inline is not None and inline != comment_description:
                raise ReportingError("report_ddl_invalid", "表 COMMENT 与内联注释冲突。")
            table_comments[table_key] = comment_description
            continue
        column_key = (database, table_name, comment_column_name)
        if column_key not in column_comments:
            raise ReportingError("report_ddl_invalid", "COMMENT 引用了未知字段。")
        inline = column_comments[column_key]
        if inline is not None and inline != comment_description:
            raise ReportingError("report_ddl_invalid", "字段 COMMENT 与内联注释冲突。")
        column_comments[column_key] = comment_description

    return tuple(
        ModelTable(
            sourceId=table.source_id,
            database=table.database,
            name=table.name,
            description=table_comments[(table.database, table.name)] or "",
            columns=tuple(
                ModelColumn(
                    name=column.name,
                    dataType=column.data_type,
                    nullable=column.nullable,
                    description=(column_comments[(table.database, table.name, column.name)] or ""),
                )
                for column in table.columns
            ),
        )
        for table in tables
    )


def validate_catalog(
    requested: tuple[ModelTable, ...],
    catalog: tuple[ModelTable, ...],
    *,
    allowed_tables: tuple[str, ...],
) -> tuple[ModelTable, ...]:
    allowed = {item.lower() for item in allowed_tables}
    actual = {(table.database.lower(), table.name.lower()): table for table in catalog}
    resolved: list[ModelTable] = []
    for table in requested:
        qualified = f"{table.database.lower()}.{table.name.lower()}"
        if qualified not in allowed:
            raise ReportingError(
                "report_schema_not_allowed", f"数据表 {qualified} 不在本次 DDL 快照范围。"
            )
        current = actual.get((table.database.lower(), table.name.lower()))
        if current is None:
            raise ReportingError("report_catalog_drift", f"实时 catalog 缺少数据表 {qualified}。")
        current_columns = {column.name.lower(): column for column in current.columns}
        requested_columns = {column.name.lower() for column in table.columns}
        if not requested_columns.issubset(current_columns):
            raise ReportingError(
                "report_catalog_drift", f"实时 catalog 数据表 {qualified} 字段已变化。"
            )
        resolved.append(
            table.model_copy(
                update={
                    "description": current.description or table.description,
                    "columns": tuple(
                        column.model_copy(
                            update={
                                "data_type": current_columns[column.name.lower()].data_type,
                                "nullable": current_columns[column.name.lower()].nullable,
                                "description": (
                                    current_columns[column.name.lower()].description
                                    or column.description
                                ),
                            }
                        )
                        for column in table.columns
                    ),
                }
            )
        )
    return tuple(resolved)


def _table_comment(statement: exp.Create) -> str | None:
    properties = statement.args.get("properties")
    if not isinstance(properties, exp.Properties):
        return None
    values = [
        _comment_literal(item.this)
        for item in properties.expressions
        if isinstance(item, exp.SchemaCommentProperty)
    ]
    if len(values) > 1:
        raise ReportingError("report_ddl_invalid", "表内联 COMMENT 重复。")
    return values[0] if values else None


def _column_comment(constraints: tuple[exp.Expression, ...]) -> str | None:
    values = [
        _comment_literal(comment.this)
        for constraint in constraints
        if isinstance(constraint, exp.ColumnConstraint)
        and isinstance((comment := constraint.args.get("kind")), exp.CommentColumnConstraint)
    ]
    if len(values) > 1:
        raise ReportingError("report_ddl_invalid", "字段内联 COMMENT 重复。")
    return values[0] if values else None


def _separate_comment(
    statement: exp.Comment,
    *,
    default_database: str,
) -> tuple[str, str, str | None, str]:
    kind = str(statement.args.get("kind") or "").upper()
    target = statement.this
    description = _comment_literal(statement.args.get("expression"))
    if kind == "TABLE" and isinstance(target, exp.Table):
        if target.catalog:
            raise ReportingError("report_ddl_invalid", "COMMENT 不允许使用 catalog 限定名。")
        database = str(target.db or default_database).lower()
        table_name = str(target.name or "").lower()
        column_name = None
    elif kind == "COLUMN" and isinstance(target, exp.Column):
        if target.catalog:
            raise ReportingError("report_ddl_invalid", "COMMENT 不允许使用 catalog 限定名。")
        database = str(target.db or default_database).lower()
        table_name = str(target.table or "").lower()
        column_name = str(target.name or "").lower()
    else:
        raise ReportingError("report_ddl_invalid", "只接受 TABLE 或 COLUMN COMMENT。")
    if not database or not table_name or (kind == "COLUMN" and not column_name):
        raise ReportingError("report_ddl_invalid", "COMMENT 目标无效。")
    return database, table_name, column_name, description


def _comment_literal(value: exp.Expression | None) -> str:
    if not isinstance(value, exp.Literal) or not value.is_string:
        raise ReportingError("report_ddl_invalid", "COMMENT 必须是字符串。")
    return str(value.this)


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


def interactive_spec_path(image_path: str) -> str:
    """图表静态图对应的 Plotly 交互产物路径；交付校验、归档与 Coding 回执共用。"""

    return PurePosixPath(image_path).with_suffix(".plotly.json").as_posix()
