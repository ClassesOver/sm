import csv
import hashlib
import inspect
import io
import json
import os
import re
import shlex
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol
from uuid import uuid4

from agno.run import RunContext
from agno.tools import Toolkit
from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .workspace import WORKSPACE_ROOT, WorkspaceError, WorkspaceService

sqlglot: Any
exp: Any
try:
    import sqlglot
    from sqlglot import exp
except ImportError:  # pragma: no cover - 仅用于依赖尚未安装的开发环境
    sqlglot = None
    exp = None

REPORT_DATASET_HANDLES_STATE_KEY = "report_dataset_handles"
CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY = "当前消息工作区附件"
MAX_REPORT_INPUTS = 20
MAX_DIRECTORY_ENTRIES = 200
MAX_DATASET_FILE_BYTES = 25 * 1024 * 1024
MAX_MATERIALIZED_PART_BYTES = MAX_DATASET_FILE_BYTES
SUPPORTED_FILE_FORMATS = frozenset(
    {
        "csv",
        "tsv",
        "xls",
        "xlsx",
        "json",
        "jsonl",
        "parquet",
        "pdf",
        "md",
        "markdown",
        "png",
        "jpg",
        "jpeg",
        "webp",
        "sqlite",
        "sqlite3",
        "db",
        "duckdb",
    }
)
DATABASE_FORMATS = frozenset({"sqlite", "sqlite3", "db", "duckdb"})
_SOURCE_ID_PREFIX = "workspace:"
_DANGEROUS_SQL_FUNCTIONS = frozenset(
    {
        "dblink",
        "dblink_connect",
        "lo_export",
        "lo_import",
        "pg_read_binary_file",
        "pg_read_file",
        "pg_write_binary_file",
        "pg_ls_dir",
        "pg_advisory_lock",
        "pg_advisory_lock_shared",
        "pg_advisory_xact_lock",
        "pg_advisory_xact_lock_shared",
        "pg_cancel_backend",
        "pg_create_restore_point",
        "pg_log_backend_memory_contexts",
        "pg_reload_conf",
        "pg_rotate_logfile",
        "pg_stat_file",
        "pg_switch_wal",
        "pg_terminate_backend",
        "pg_try_advisory_lock",
        "pg_try_advisory_lock_shared",
        "pg_try_advisory_xact_lock",
        "pg_try_advisory_xact_lock_shared",
    }
)
_LOCAL_DANGEROUS_SQL_FUNCTIONS = frozenset(
    {
        "attach",
        "csv_scan",
        "delta_scan",
        "glob",
        "http_get",
        "httpfs",
        "iceberg_scan",
        "install",
        "json_scan",
        "load",
        "load_extension",
        "mysql_query",
        "parquet_scan",
        "postgres_query",
        "postgres_scan",
        "query",
        "query_table",
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_ndjson",
        "read_ndjson_objects",
        "read_parquet",
        "read_text",
        "read_xlsx",
        "readfile",
        "sqlite_scan",
        "sqlite_query",
        "writefile",
    }
)


class ReportDataSourceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class WorkspaceReference(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = Field(min_length=1, max_length=1024)
    type: str = Field(pattern=r"^(file|directory)$")
    size: int | None = Field(default=None, ge=0)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class DatasetHandle:
    dataset_id: str
    source_id: str
    source_type: str
    path: str
    format: str
    schema: dict[str, Any] | None
    row_count: int | None
    size: int
    sha256: str
    sampled: bool
    provenance: dict[str, Any]

    def public_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "sourceId": self.source_id,
            "sourceType": self.source_type,
            "path": self.path,
            "format": self.format,
            "schema": self.schema,
            "rowCount": self.row_count,
            "size": self.size,
            "sha256": self.sha256,
            "sampled": self.sampled,
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_state(cls, value: Mapping[str, Any]) -> "DatasetHandle":
        try:
            return cls(
                dataset_id=str(value["datasetId"]),
                source_id=str(value["sourceId"]),
                source_type=str(value["sourceType"]),
                path=str(value["path"]),
                format=str(value["format"]),
                schema=value.get("schema") if isinstance(value.get("schema"), dict) else None,
                row_count=value.get("rowCount") if isinstance(value.get("rowCount"), int) else None,
                size=int(value["size"]),
                sha256=str(value["sha256"]),
                sampled=bool(value.get("sampled", False)),
                provenance=dict(value.get("provenance") or {}),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ReportDataSourceError(
                "dataset_invalid", "数据集句柄无效，请重新准备。"
            ) from error


class DataSourceAdapter(Protocol):
    @property
    def source_id(self) -> str: ...

    def public_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class WorkspaceFileDataSource:
    source_id: str
    path: str
    format: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "sourceType": "workspace_file",
            "path": self.path,
            "format": self.format,
            "capabilities": ["describe", "materialize"],
        }


@dataclass(frozen=True)
class WorkspaceDatabaseDataSource(WorkspaceFileDataSource):
    def public_dict(self) -> dict[str, Any]:
        value = super().public_dict()
        value.update(
            {
                "sourceType": "workspace_database",
                "databaseType": self.format,
                "capabilities": ["describe", "query", "materialize"],
            }
        )
        return value


@dataclass(frozen=True)
class WorkspaceDirectoryDataSource:
    source_id: str
    path: str

    def public_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.source_id,
            "sourceType": "workspace_directory",
            "path": self.path,
            "capabilities": ["describe", "materialize"],
        }


@dataclass(frozen=True)
class OdooExportDataSource(WorkspaceFileDataSource):
    def public_dict(self) -> dict[str, Any]:
        value = super().public_dict()
        value["sourceType"] = "odoo_export"
        return value


@dataclass(frozen=True)
class PostgresSourceConfig:
    id: str
    dsn_env: str
    dsn: str
    name: str = ""
    schemas: tuple[str, ...] = ()
    tables: tuple[str, ...] = ()
    statement_timeout_ms: int = 30_000
    max_rows: int = 1_000_000
    max_bytes: int = 256 * 1024 * 1024

    @property
    def source_id(self) -> str:
        return self.id

    def public_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.id,
            "sourceType": "postgresql",
            "name": self.name or self.id,
            "schemas": list(self.schemas),
            "tables": list(self.tables),
            "capabilities": ["describe", "query", "materialize"],
            "limits": {
                "statementTimeoutMs": self.statement_timeout_ms,
                "maxRows": self.max_rows,
                "maxBytes": self.max_bytes,
            },
        }


@dataclass(frozen=True)
class PostgresDataSource:
    config: PostgresSourceConfig

    @property
    def source_id(self) -> str:
        return self.config.id

    def public_dict(self) -> dict[str, Any]:
        return self.config.public_dict()


def _normalized_database_identity(dsn: str) -> tuple[str, str, int, str]:
    value = dsn.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        parameters = conninfo_to_dict(value)
        port = int(parameters.get("port") or 5432)
    except (TypeError, ValueError, ProgrammingError) as error:
        raise ValueError("PostgreSQL 连接地址无效。") from error
    return (
        "postgresql",
        str(parameters.get("host") or "").lower(),
        port,
        str(parameters.get("dbname") or ""),
    )


def load_postgres_sources(
    config_path: str | None,
    *,
    environ: Mapping[str, str] | None = None,
    excluded_database_url: str | None = None,
) -> dict[str, PostgresSourceConfig]:
    if not config_path:
        return {}
    try:
        with open(config_path, encoding="utf-8") as source_file:
            payload = json.load(source_file)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("报表数据源配置无法读取。") from error
    raw_sources = payload.get("sources") if isinstance(payload, dict) else None
    if not isinstance(raw_sources, list):
        raise ValueError("报表数据源配置必须包含 sources 数组。")
    values = os.environ if environ is None else environ
    excluded_identity = (
        _normalized_database_identity(excluded_database_url) if excluded_database_url else None
    )
    result: dict[str, PostgresSourceConfig] = {}
    for raw in raw_sources:
        if not isinstance(raw, dict) or raw.get("type") != "postgresql":
            raise ValueError("首版报表数据库只支持 postgresql。")
        source_id = raw.get("id")
        dsn_env = raw.get("dsnEnv")
        if (
            not isinstance(source_id, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", source_id)
            or source_id in result
            or source_id == "workspace"
            or source_id.startswith(_SOURCE_ID_PREFIX)
        ):
            raise ValueError("报表数据源 id 无效或重复。")
        if not isinstance(dsn_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", dsn_env):
            raise ValueError(f"报表数据源 {source_id} 的 dsnEnv 无效。")
        dsn = str(values.get(dsn_env) or "").strip()
        if not dsn:
            raise ValueError(f"报表数据源 {source_id} 缺少环境变量 {dsn_env}。")
        if not dsn.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError(f"报表数据源 {source_id} 的连接地址不是 PostgreSQL。")
        if (
            excluded_identity is not None
            and _normalized_database_identity(dsn) == excluded_identity
        ):
            raise ValueError("AgentOS 自身 PostgreSQL 不能注册为报表数据源。")
        schemas = _validated_identifiers(raw.get("schemas", []), "schema")
        tables = _validated_identifiers(raw.get("tables", []), "table", allow_qualified=True)
        if not schemas and not tables:
            raise ValueError(f"报表数据源 {source_id} 必须配置允许的 schema 或 table。")
        result[source_id] = PostgresSourceConfig(
            id=source_id,
            name=str(raw.get("name") or source_id)[:200],
            dsn_env=dsn_env,
            dsn=dsn,
            schemas=schemas,
            tables=tables,
            statement_timeout_ms=_bounded_config_int(
                raw.get("statementTimeoutMs"), 30_000, 1_000, 300_000, "statementTimeoutMs"
            ),
            max_rows=_bounded_config_int(raw.get("maxRows"), 1_000_000, 1, 5_000_000, "maxRows"),
            max_bytes=_bounded_config_int(
                raw.get("maxBytes"), 256 * 1024 * 1024, 1, 256 * 1024 * 1024, "maxBytes"
            ),
        )
    return result


def _bounded_config_int(value: Any, default: int, minimum: int, maximum: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须是 {minimum} 至 {maximum} 之间的整数。")
    return value


def _validated_identifiers(
    value: Any,
    label: str,
    *,
    allow_qualified: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 500:
        raise ValueError(f"允许的 {label} 必须是数组。")
    pattern = (
        r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*"
        if allow_qualified
        else r"[A-Za-z_][A-Za-z0-9_$]*"
    )
    result = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(pattern, item):
            raise ValueError(f"允许的 {label} 名称无效。")
        result.append(item.lower())
    return tuple(dict.fromkeys(result))


def validate_read_only_query(query: str, source: PostgresSourceConfig) -> str:
    normalized = str(query or "").strip().rstrip(";").strip()
    if not normalized or len(normalized.encode("utf-8")) > 256 * 1024:
        raise ReportDataSourceError("invalid_sql", "SQL 必须是非空且不超过 256 KiB 的查询。")
    if sqlglot is None or exp is None:
        raise ReportDataSourceError("sql_validator_unavailable", "SQL 校验器当前不可用。")
    try:
        statements = sqlglot.parse(query, read="postgres")
    except Exception as error:
        raise ReportDataSourceError("invalid_sql", "SQL 语法无效。") from error
    if len(statements) != 1 or statements[0] is None:
        raise ReportDataSourceError("invalid_sql", "只允许执行一条 SQL 查询。")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ReportDataSourceError("read_only_sql_required", "只允许 SELECT 或只读 CTE。")
    forbidden_types = tuple(
        item
        for name in (
            "Alter",
            "Command",
            "Commit",
            "Copy",
            "Create",
            "Delete",
            "Drop",
            "Insert",
            "Into",
            "Lock",
            "Merge",
            "Transaction",
            "TruncateTable",
            "Update",
        )
        if (item := getattr(exp, name, None)) is not None
    )
    if forbidden_types and any(isinstance(node, forbidden_types) for node in statement.walk()):
        raise ReportDataSourceError("read_only_sql_required", "SQL 包含写入或管理操作。")
    if any(isinstance(node.expression, exp.Func) for node in statement.find_all(exp.Dot)):
        raise ReportDataSourceError("sql_function_denied", "SQL 不允许调用 schema 限定函数。")
    for function in statement.find_all(exp.Func):
        name = str(getattr(function, "name", "") or "").lower()
        if not name:
            name = str(getattr(function, "sql_name", lambda: "")() or "").lower()
        if name in _DANGEROUS_SQL_FUNCTIONS:
            raise ReportDataSourceError("sql_function_denied", f"SQL 函数 {name} 不允许使用。")
    cte_names = {
        str(cte.alias_or_name).lower() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
    }
    for table in statement.find_all(exp.Table):
        table_name = str(table.name or "").lower()
        schema_name = str(table.db or "").lower()
        catalog_name = str(table.catalog or "")
        if not schema_name and table_name in cte_names:
            continue
        if catalog_name:
            raise ReportDataSourceError("sql_table_denied", "SQL 不允许跨数据库查询。")
        _validate_table_access(schema_name, table_name, source)
    return normalized


def validate_local_read_only_query(query: str, file_format: str) -> str:
    normalized = str(query or "").strip().rstrip(";").strip()
    if not normalized or len(normalized.encode("utf-8")) > 256 * 1024:
        raise ReportDataSourceError("invalid_sql", "SQL 必须是非空且不超过 256 KiB 的查询。")
    if sqlglot is None or exp is None:
        raise ReportDataSourceError("sql_validator_unavailable", "SQL 校验器当前不可用。")
    dialect = "duckdb" if file_format == "duckdb" else "sqlite"
    try:
        statements = sqlglot.parse(query, read=dialect)
    except Exception as error:
        raise ReportDataSourceError("invalid_sql", "SQL 语法无效。") from error
    if len(statements) != 1 or statements[0] is None:
        raise ReportDataSourceError("invalid_sql", "只允许执行一条 SQL 查询。")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ReportDataSourceError("read_only_sql_required", "只允许 SELECT 或只读 CTE。")
    forbidden = tuple(
        item
        for name in (
            "Alter",
            "Attach",
            "Command",
            "Copy",
            "Create",
            "Delete",
            "Detach",
            "Drop",
            "Insert",
            "Into",
            "Merge",
            "Pragma",
            "Transaction",
            "TruncateTable",
            "Update",
        )
        if (item := getattr(exp, name, None)) is not None
    )
    if forbidden and any(isinstance(node, forbidden) for node in statement.walk()):
        raise ReportDataSourceError("read_only_sql_required", "SQL 包含写入或管理操作。")
    for function in statement.find_all(exp.Func):
        name = str(getattr(function, "name", "") or "").lower()
        if not name:
            name = str(getattr(function, "sql_name", lambda: "")() or "").lower()
        if name in _LOCAL_DANGEROUS_SQL_FUNCTIONS:
            raise ReportDataSourceError("sql_function_denied", f"SQL 函数 {name} 不允许使用。")
    external_suffixes = (
        ".csv",
        ".json",
        ".jsonl",
        ".parquet",
        ".tsv",
        ".xlsx",
    )
    for table in statement.find_all(exp.Table):
        if file_format == "duckdb" and isinstance(table.this, exp.Anonymous):
            raise ReportDataSourceError("sql_function_denied", "SQL 不允许调用未识别的表函数。")
        name = str(table.name or "")
        schema = str(table.db or "").lower()
        if table.catalog or (schema and schema not in {"main", "temp"}):
            raise ReportDataSourceError("sql_table_denied", "SQL 不允许访问其他数据库。")
        lowered = name.lower()
        if "/" in name or "\\" in name or lowered.endswith(external_suffixes):
            raise ReportDataSourceError("sql_table_denied", "SQL 不允许读取数据库外部文件。")
    return normalized


def _validate_table_access(
    schema_name: str,
    table_name: str,
    source: PostgresSourceConfig,
) -> None:
    qualified = f"{schema_name}.{table_name}" if schema_name else table_name
    allowed_tables = set(source.tables)
    allowed_schemas = set(source.schemas)
    if allowed_tables:
        if qualified not in allowed_tables:
            raise ReportDataSourceError("sql_table_denied", f"数据表 {qualified} 不在允许范围内。")
        return
    if not schema_name or schema_name not in allowed_schemas:
        raise ReportDataSourceError("sql_table_denied", f"数据表 {qualified} 不在允许范围内。")


class ReportDataSourceRegistry:
    def __init__(
        self,
        workspace_service: WorkspaceService,
        *,
        config_path: str | None = None,
        environ: Mapping[str, str] | None = None,
        excluded_database_url: str | None = None,
    ):
        self.workspace_service = workspace_service
        configs = load_postgres_sources(
            config_path,
            environ=environ,
            excluded_database_url=excluded_database_url,
        )
        self.postgres_sources = {
            source_id: PostgresDataSource(config) for source_id, config in configs.items()
        }


class ReportDataSourceToolkit(Toolkit):
    def __init__(
        self,
        service: WorkspaceService,
        *,
        registry: ReportDataSourceRegistry | None = None,
        config_path: str | None = None,
        environ: Mapping[str, str] | None = None,
        excluded_database_url: str | None = None,
    ):
        self.service = service
        self.registry = registry or ReportDataSourceRegistry(
            service,
            config_path=config_path,
            environ=environ,
            excluded_database_url=excluded_database_url,
        )
        super().__init__(
            name="report_data_sources",
            tools=[
                self.report_list_data_sources,
                self.report_describe_data_source,
                self.report_materialize_dataset,
            ],
            instructions=(
                "先用 report_list_data_sources 发现当前 thread 的文件引用和已注册只读数据库；"
                "目录只描述直接子项，明确选择文件后再物化。后续报表准备只使用返回的 datasetId；"
                "数据库 SQL 只能是服务端白名单内的单条 SELECT 或只读 CTE。"
            ),
            add_instructions=True,
        )

    async def report_list_data_sources(
        self,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """列出当前消息引用、当前 thread 工作区入口及服务端注册的只读 PostgreSQL。"""
        sources: list[dict[str, Any]] = [
            {
                "sourceId": "workspace",
                "sourceType": "workspace",
                "path": "",
                "capabilities": ["describe"],
            }
        ]
        for reference in _workspace_references(run_context):
            adapter, stat, digest = await self._validated_workspace_reference(
                reference,
                run_context,
            )
            value = adapter.public_dict()
            value["size"] = int(stat.get("size", 0))
            if digest is not None:
                value["sha256"] = digest["sha256"]
            sources.append(value)
        sources.extend(source.public_dict() for source in self.registry.postgres_sources.values())
        return {"sources": sources}

    async def report_describe_data_source(
        self,
        source_id: str,
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """返回数据源类型、可用能力，以及工作区目录的受控直接子项。"""
        list_files = getattr(self.service, "alist_files", self.service.list_files)
        if source_id == "workspace":
            entries = await _maybe_await(list_files(_thread(run_context), ""))
            entries = list(entries)
            return {
                "sourceId": source_id,
                "sourceType": "workspace",
                "entries": entries[:MAX_DIRECTORY_ENTRIES],
                "truncated": len(entries) > MAX_DIRECTORY_ENTRIES,
            }
        source = await self._resolve_source(source_id, run_context)
        if isinstance(source, WorkspaceDirectoryDataSource):
            entries = await _maybe_await(list_files(_thread(run_context), source.path))
            entries = list(entries)
            return {
                **source.public_dict(),
                "entries": entries[:MAX_DIRECTORY_ENTRIES],
                "truncated": len(entries) > MAX_DIRECTORY_ENTRIES,
            }
        if isinstance(source, (WorkspaceFileDataSource, WorkspaceDatabaseDataSource)):
            stat = await self.service.astat(_thread(run_context), source.path)
            digest = await self.service.ahash_file(_thread(run_context), source.path)
            return {
                **source.public_dict(),
                "size": int(stat.get("size", digest.get("size", 0))),
                "sha256": digest.get("sha256"),
                "schemaCapability": "sql_catalog"
                if isinstance(source, WorkspaceDatabaseDataSource)
                else "deterministic_profile",
            }
        return source.public_dict()

    async def report_materialize_dataset(
        self,
        source_id: str,
        paths: list[str] | None = None,
        sql: str | None = None,
        output_format: str = "parquet",
        run_context: RunContext | None = None,
    ) -> dict[str, Any]:
        """把工作区文件或受控数据库查询登记为不可变数据集句柄。"""
        if paths is not None and sql is not None:
            raise ReportDataSourceError(
                "invalid_materialize_request", "paths 与 sql 不能同时使用。"
            )
        if paths is not None and len(paths) > MAX_REPORT_INPUTS:
            raise ReportDataSourceError(
                "invalid_dataset_count", f"单个任务最多选择 {MAX_REPORT_INPUTS} 个输入。"
            )
        if output_format not in {"parquet", "csv"}:
            raise ReportDataSourceError("invalid_output_format", "输出格式只能是 parquet 或 csv。")
        if source_id == "workspace":
            if sql is not None or not paths:
                raise ReportDataSourceError(
                    "invalid_materialize_request", "工作区入口必须通过 paths 选择具体文件。"
                )
            if not 1 <= len(paths) <= MAX_REPORT_INPUTS:
                raise ReportDataSourceError(
                    "invalid_dataset_count", f"单个任务必须选择 1 至 {MAX_REPORT_INPUTS} 个输入。"
                )
            selected = [
                _normalize_workspace_path(self.service, path) for path in dict.fromkeys(paths)
            ]
            handles = [
                await self._workspace_handle(path, source_id, run_context) for path in selected
            ]
            self._store_handles(handles, run_context)
            return {"datasets": [handle.public_dict() for handle in handles]}
        source = await self._resolve_source(source_id, run_context)
        if isinstance(source, PostgresDataSource):
            if paths is not None or not sql:
                raise ReportDataSourceError(
                    "invalid_materialize_request", "PostgreSQL 数据源必须提供 sql。"
                )
            query = validate_read_only_query(sql, source.config)
            return await self._materialize_postgres(
                source.config,
                query,
                output_format,
                run_context,
            )
        if sql is not None:
            if not isinstance(source, WorkspaceDatabaseDataSource):
                raise ReportDataSourceError(
                    "invalid_materialize_request", "文件数据源不能提供 sql。"
                )
            if paths is not None:
                raise ReportDataSourceError(
                    "invalid_materialize_request", "工作区数据库查询不能同时提供 paths。"
                )
            query = validate_local_read_only_query(sql, source.format)
            return await self._materialize_workspace_database(
                source,
                query,
                output_format,
                run_context,
            )
        selected = self._selected_workspace_paths(source, paths)
        if not 1 <= len(selected) <= MAX_REPORT_INPUTS:
            raise ReportDataSourceError(
                "invalid_dataset_count", f"单个任务必须选择 1 至 {MAX_REPORT_INPUTS} 个输入。"
            )
        handles = [await self._workspace_handle(path, source_id, run_context) for path in selected]
        self._store_handles(handles, run_context)
        return {"datasets": [handle.public_dict() for handle in handles]}

    async def resolve_dataset_paths(
        self,
        dataset_ids: Sequence[str],
        *,
        run_context: RunContext | None = None,
    ) -> list[str]:
        if not isinstance(dataset_ids, Sequence) or isinstance(dataset_ids, (str, bytes)):
            raise ReportDataSourceError("dataset_invalid", "datasetIds 必须是数组。")
        if not 1 <= len(dataset_ids) <= MAX_REPORT_INPUTS:
            raise ReportDataSourceError("invalid_dataset_count", "数据集数量超出允许范围。")
        stored = _session_state(run_context).get(REPORT_DATASET_HANDLES_STATE_KEY, {})
        if not isinstance(stored, dict):
            raise ReportDataSourceError("dataset_invalid", "数据集状态无效，请重新准备。")
        paths = []
        thread_binding = _thread_binding(_thread(run_context))
        for dataset_id in dataset_ids:
            raw = stored.get(dataset_id)
            if not isinstance(raw, dict):
                raise ReportDataSourceError("dataset_not_found", "数据集不存在，请重新准备。")
            handle = DatasetHandle.from_state(raw)
            if handle.source_type not in {
                "workspace_file",
                "workspace_database",
                "odoo_export",
                "postgresql_materialized",
            }:
                raise ReportDataSourceError("dataset_invalid", "数据集类型无效，请重新准备。")
            digest = await self.service.ahash_file(_thread(run_context), handle.path)
            if digest.get("sha256") != handle.sha256 or int(digest.get("size", -1)) != handle.size:
                raise ReportDataSourceError(
                    "stale_dataset", "数据集文件已变化，请重新物化并确认分析范围。"
                )
            if raw.get("_threadBinding") != thread_binding:
                raise ReportDataSourceError("stale_dataset", "数据集不属于当前对话，请重新物化。")
            paths.append(handle.path)
        return paths

    async def _materialize_workspace_database(
        self,
        source: WorkspaceDatabaseDataSource,
        query: str,
        output_format: str,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        thread = _thread(run_context)
        before = await self.service.ahash_file(thread, source.path)
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        materialization_id = self._materialization_id(source.source_id, query_hash, run_context)
        output_dir = f"报表/数据集/{materialization_id}/分片"
        result = await self._run_data_source_runtime(
            "materialize_local",
            {
                "source_path": source.path,
                "file_format": source.format,
                "query": query,
                "output_format": output_format,
                "output_dir": output_dir,
                "max_rows": 1_000_000,
                "max_bytes": 256 * 1024 * 1024,
            },
            run_context,
        )
        after = await self.service.ahash_file(thread, source.path)
        if before.get("sha256") != after.get("sha256") or before.get("size") != after.get("size"):
            await self._delete_materialized_output(output_dir, run_context)
            raise ReportDataSourceError(
                "stale_dataset", "工作区数据库在查询期间发生变化，请重新物化。"
            )
        return await self._store_materialized_handles(
            source_id=source.source_id,
            source_type="workspace_database",
            paths=result.get("paths"),
            file_format=output_format,
            schema=result.get("schema"),
            row_count=result.get("rowCount"),
            provenance={"workspacePath": source.path, "querySha256": query_hash},
            run_context=run_context,
        )

    async def _materialize_postgres(
        self,
        source: PostgresSourceConfig,
        query: str,
        output_format: str,
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        try:
            import psycopg
        except ImportError as error:  # pragma: no cover - requirements 固定包含 psycopg
            raise ReportDataSourceError(
                "database_driver_unavailable", "当前服务缺少 PostgreSQL 驱动。"
            ) from error
        thread = _thread(run_context)
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()
        materialization_id = self._materialization_id(source.id, query_hash, run_context)
        csv_dir = f"报表/数据集/{materialization_id}/原始分片"
        csv_paths: list[str] = []
        total_rows = 0
        total_bytes = 0
        columns: list[str] = []
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, thread)
            _relative, csv_remote = self.service.normalize_path(csv_dir)
            await self.service._aensure_directory(sandbox, csv_remote)
            try:
                connection = await psycopg.AsyncConnection.connect(source.dsn)
                async with connection:
                    async with connection.transaction():
                        await connection.execute("SET TRANSACTION READ ONLY")
                        await connection.execute("SET LOCAL search_path = pg_catalog")
                        await connection.execute(
                            f"SET LOCAL statement_timeout = {source.statement_timeout_ms}"
                        )
                        async with connection.cursor(
                            name=f"report_{materialization_id[:20]}"
                        ) as cursor:
                            await cursor.execute(query)
                            columns = [
                                str(item.name or "column") for item in cursor.description or []
                            ]
                            columns = _deduplicate_columns(columns)
                            header = self._csv_row(columns)
                            current = bytearray(header)
                            current_rows = 0
                            part = 0
                            while True:
                                rows = await cursor.fetchmany(1000)
                                if not rows:
                                    break
                                for row in rows:
                                    total_rows += 1
                                    if total_rows > source.max_rows:
                                        raise ReportDataSourceError(
                                            "dataset_too_large", "查询结果超过允许的行数。"
                                        )
                                    encoded = self._csv_row(row)
                                    if len(encoded) + len(header) > MAX_MATERIALIZED_PART_BYTES:
                                        raise ReportDataSourceError(
                                            "dataset_too_large",
                                            "查询结果包含超过单文件限制的记录。",
                                        )
                                    if (
                                        current_rows
                                        and len(current) + len(encoded)
                                        > MAX_MATERIALIZED_PART_BYTES
                                    ):
                                        part += 1
                                        path = await self._upload_postgres_part(
                                            sandbox, csv_dir, part, bytes(current)
                                        )
                                        csv_paths.append(path)
                                        total_bytes += len(current)
                                        if len(csv_paths) > MAX_REPORT_INPUTS:
                                            raise ReportDataSourceError(
                                                "dataset_too_large", "查询结果分片数量超过限制。"
                                            )
                                        current = bytearray(header)
                                        current_rows = 0
                                    current.extend(encoded)
                                    current_rows += 1
                                if total_bytes + len(current) > source.max_bytes:
                                    raise ReportDataSourceError(
                                        "dataset_too_large", "查询结果超过允许的数据量。"
                                    )
                            if current_rows or not csv_paths:
                                part += 1
                                path = await self._upload_postgres_part(
                                    sandbox, csv_dir, part, bytes(current)
                                )
                                csv_paths.append(path)
                                total_bytes += len(current)
                                if len(csv_paths) > MAX_REPORT_INPUTS:
                                    raise ReportDataSourceError(
                                        "dataset_too_large", "查询结果分片数量超过限制。"
                                    )
            except ReportDataSourceError:
                await self._best_effort_delete(sandbox, csv_remote)
                raise
            except Exception as error:
                await self._best_effort_delete(sandbox, csv_remote)
                raise ReportDataSourceError(
                    "database_query_failed", "只读 PostgreSQL 查询失败，请检查 SQL 和数据源范围。"
                ) from error
        result: dict[str, Any]
        if output_format == "parquet":
            parquet_dir = f"报表/数据集/{materialization_id}/分片"
            async with self.service._async_client() as client:
                sandbox = await self.service._asandbox_for(client, thread)
                _relative, csv_remote = self.service.normalize_path(csv_dir)
                try:
                    result = await self._run_data_source_runtime(
                        "convert_csv",
                        {
                            "paths": csv_paths,
                            "output_dir": parquet_dir,
                            "max_bytes": source.max_bytes,
                        },
                        run_context,
                    )
                finally:
                    await self._best_effort_delete(sandbox, csv_remote)
        else:
            result = {
                "paths": csv_paths,
                "rowCount": total_rows,
                "size": total_bytes,
                "schema": {"columns": columns},
            }
        return await self._store_materialized_handles(
            source_id=source.id,
            source_type="postgresql_materialized",
            paths=result.get("paths"),
            file_format=output_format,
            schema=result.get("schema"),
            row_count=result.get("rowCount", total_rows),
            provenance={"dataSourceId": source.id, "querySha256": query_hash},
            run_context=run_context,
        )

    async def _run_data_source_runtime(
        self,
        action: str,
        payload: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        from . import report_data_source_runtime

        with open(report_data_source_runtime.__file__, "rb") as source_file:
            content = source_file.read()
        digest = hashlib.sha256(content).hexdigest()
        remote = f"/tmp/report-data-source-runtime-{digest}.py"
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            await sandbox.fs.upload_file(content, remote)
            command = (
                f"python {shlex.quote(remote)} {shlex.quote(action)} "
                f"{shlex.quote(json.dumps(payload, ensure_ascii=False))}"
            )
            value = await sandbox.process.exec(command, cwd=WORKSPACE_ROOT, timeout=60)
        output = str(getattr(value, "result", "") or "")
        try:
            result = json.loads(
                next(line for line in reversed(output.splitlines()) if line.strip())
            )
        except (StopIteration, json.JSONDecodeError) as error:
            raise ReportDataSourceError(
                "materialization_failed", "数据源物化返回了无效结果。"
            ) from error
        if getattr(value, "exit_code", None) != 0 or not result.get("ok"):
            raise ReportDataSourceError(
                str(result.get("code") or "materialization_failed"),
                str(result.get("error") or "数据源物化失败。"),
            )
        return result

    async def _store_materialized_handles(
        self,
        *,
        source_id: str,
        source_type: str,
        paths: Any,
        file_format: str,
        schema: Any,
        row_count: Any,
        provenance: dict[str, Any],
        run_context: RunContext | None,
    ) -> dict[str, Any]:
        if not isinstance(paths, list) or not 1 <= len(paths) <= MAX_REPORT_INPUTS:
            raise ReportDataSourceError("materialization_failed", "数据源物化没有返回有效分片。")
        handles = []
        shard_row_count = row_count if len(paths) == 1 and isinstance(row_count, int) else None
        for path in paths:
            normalized = _normalize_workspace_path(self.service, path)
            digest = await self.service.ahash_file(_thread(run_context), normalized)
            identity = json.dumps(
                [source_id, normalized, digest.get("sha256"), digest.get("size")],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            handles.append(
                DatasetHandle(
                    dataset_id="dataset-"
                    + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32],
                    source_id=source_id,
                    source_type=source_type,
                    path=normalized,
                    format=file_format,
                    schema=schema if isinstance(schema, dict) else None,
                    row_count=shard_row_count,
                    size=int(digest["size"]),
                    sha256=str(digest["sha256"]),
                    sampled=False,
                    provenance=dict(provenance),
                )
            )
        self._store_handles(handles, run_context)
        return {
            "datasets": [handle.public_dict() for handle in handles],
            "rowCount": row_count if isinstance(row_count, int) else None,
        }

    @staticmethod
    def _store_handles(
        handles: Sequence[DatasetHandle],
        run_context: RunContext | None,
    ) -> None:
        state = _session_state(run_context)
        stored = state.setdefault(REPORT_DATASET_HANDLES_STATE_KEY, {})
        if not isinstance(stored, dict):
            stored = {}
            state[REPORT_DATASET_HANDLES_STATE_KEY] = stored
        for handle in handles:
            stored[handle.dataset_id] = {
                **handle.public_dict(),
                "_threadBinding": _thread_binding(_thread(run_context)),
            }

    @staticmethod
    def _csv_row(values: Sequence[Any]) -> bytes:
        buffer = io.StringIO(newline="")
        csv.writer(buffer).writerow(values)
        return buffer.getvalue().encode("utf-8")

    async def _upload_postgres_part(
        self,
        sandbox: Any,
        directory: str,
        part: int,
        content: bytes,
    ) -> str:
        path = f"{directory}/part-{part:04d}.csv"
        _relative, remote = self.service.normalize_path(path, allow_root=False)
        await sandbox.fs.upload_file(content, remote)
        return path

    async def _delete_materialized_output(
        self,
        path: str,
        run_context: RunContext | None,
    ) -> None:
        async with self.service._async_client() as client:
            sandbox = await self.service._asandbox_for(client, _thread(run_context))
            _relative, remote = self.service.normalize_path(path, allow_root=False)
            await self._best_effort_delete(sandbox, remote)

    @staticmethod
    async def _best_effort_delete(sandbox: Any, remote: str) -> None:
        try:
            await sandbox.fs.delete_file(remote, recursive=True)
        except Exception:
            pass

    @staticmethod
    def _materialization_id(
        source_id: str,
        query_hash: str,
        run_context: RunContext | None,
    ) -> str:
        run_id = str(run_context.run_id if run_context is not None else "")
        nonce = uuid4().hex
        return hashlib.sha256(f"{run_id}:{source_id}:{query_hash}:{nonce}".encode()).hexdigest()[
            :24
        ]

    async def _resolve_source(
        self,
        source_id: str,
        run_context: RunContext | None,
    ) -> DataSourceAdapter:
        if source_id in self.registry.postgres_sources:
            return self.registry.postgres_sources[source_id]
        for reference in _workspace_references(run_context):
            normalized = _normalize_workspace_path(self.service, reference.path)
            adapter = _workspace_adapter(normalized, reference.type)
            if adapter.source_id == source_id:
                await self._validated_workspace_reference(reference, run_context)
                return adapter
        raise ReportDataSourceError("data_source_not_found", "数据源不存在或不属于当前请求。")

    def _selected_workspace_paths(
        self,
        source: DataSourceAdapter,
        paths: list[str] | None,
    ) -> list[str]:
        if isinstance(source, (WorkspaceFileDataSource, WorkspaceDatabaseDataSource)):
            if paths not in (None, [], [source.path]):
                raise ReportDataSourceError(
                    "invalid_materialize_request", "文件数据源不接受其他路径。"
                )
            return [source.path]
        if not isinstance(source, WorkspaceDirectoryDataSource):
            raise ReportDataSourceError("invalid_materialize_request", "该数据源不能按文件物化。")
        if not paths:
            raise ReportDataSourceError(
                "invalid_materialize_request", "目录数据源必须选择具体文件。"
            )
        selected = []
        prefix = f"{source.path}/" if source.path else ""
        for path in paths:
            normalized = _normalize_workspace_path(self.service, path)
            remainder = normalized[len(prefix) :] if normalized.startswith(prefix) else ""
            if not remainder or "/" in remainder:
                raise ReportDataSourceError(
                    "path_outside_source", f"文件 {normalized} 不在所选目录的直接子项中。"
                )
            selected.append(normalized)
        return list(dict.fromkeys(selected))

    async def _workspace_handle(
        self,
        path: str,
        source_id: str,
        run_context: RunContext | None,
    ) -> DatasetHandle:
        thread = _thread(run_context)
        stat = await self.service.astat(thread, path)
        if stat.get("type") != "file":
            raise ReportDataSourceError("dataset_file_required", "数据集输入必须是普通文件。")
        digest = await self.service.ahash_file(thread, path)
        if int(digest.get("size", -1)) > MAX_DATASET_FILE_BYTES:
            raise ReportDataSourceError("dataset_too_large", "单个数据集文件不能超过 25 MiB。")
        file_format = _file_format(path)
        if path.startswith("exports/"):
            source_type = "odoo_export"
        elif file_format in DATABASE_FORMATS:
            source_type = "workspace_database"
        else:
            source_type = "workspace_file"
        identity = json.dumps(
            [thread, source_id, path, digest.get("sha256"), digest.get("size")],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        dataset_id = "dataset-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
        return DatasetHandle(
            dataset_id=dataset_id,
            source_id=source_id,
            source_type=source_type,
            path=path,
            format=file_format,
            schema=None,
            row_count=None,
            size=int(digest["size"]),
            sha256=str(digest["sha256"]),
            sampled=False,
            provenance={
                "workspacePath": path,
                **({"origin": "odoo_export"} if source_type == "odoo_export" else {}),
            },
        )

    async def _validated_workspace_reference(
        self,
        reference: WorkspaceReference,
        run_context: RunContext | None,
    ) -> tuple[DataSourceAdapter, dict[str, Any], dict[str, Any] | None]:
        normalized = _normalize_workspace_path(self.service, reference.path)
        stat = await self.service.astat(_thread(run_context), normalized)
        if stat.get("type") != reference.type:
            raise ReportDataSourceError(
                "data_source_type_mismatch", "工作区引用类型已经变化，请重新选择。"
            )
        adapter = _workspace_adapter(normalized, reference.type)
        if reference.type == "directory":
            return adapter, stat, None
        digest = await self.service.ahash_file(_thread(run_context), normalized)
        if int(digest.get("size", -1)) > MAX_DATASET_FILE_BYTES:
            raise ReportDataSourceError("dataset_too_large", "单个数据集文件不能超过 25 MiB。")
        if (reference.size is not None and reference.size != int(digest.get("size", -1))) or (
            reference.sha256 is not None and reference.sha256 != digest.get("sha256")
        ):
            raise ReportDataSourceError(
                "stale_dataset", "工作区引用文件已变化，请重新选择并确认分析范围。"
            )
        return adapter, stat, digest


def _workspace_references(run_context: RunContext | None) -> list[WorkspaceReference]:
    dependencies = run_context.dependencies if run_context is not None else None
    if not isinstance(dependencies, dict):
        return []
    combined = []
    for key in ("已选工作区引用", CURRENT_MESSAGE_WORKSPACE_FILES_DEPENDENCY):
        raw = dependencies.get(key)
        if raw is None:
            continue
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ReportDataSourceError(
                    "workspace_references_invalid", "工作区引用格式无效。"
                ) from error
        if not isinstance(raw, list):
            raise ReportDataSourceError("workspace_references_invalid", "工作区引用必须是数组。")
        combined.extend(raw)
    if len(combined) > MAX_REPORT_INPUTS:
        raise ReportDataSourceError(
            "workspace_references_invalid", f"工作区引用必须是最多 {MAX_REPORT_INPUTS} 项的数组。"
        )
    try:
        references = [WorkspaceReference.model_validate(item) for item in combined]
    except ValidationError as error:
        raise ReportDataSourceError(
            "workspace_references_invalid", "工作区引用格式无效。"
        ) from error
    return list({(item.type, item.path): item for item in references}.values())


def _workspace_adapter(path: str, reference_type: str) -> DataSourceAdapter:
    source_id = (
        _SOURCE_ID_PREFIX + hashlib.sha256(f"{reference_type}:{path}".encode()).hexdigest()[:24]
    )
    if reference_type == "directory":
        return WorkspaceDirectoryDataSource(source_id=source_id, path=path)
    file_format = _file_format(path)
    if path.startswith("exports/"):
        return OdooExportDataSource(source_id=source_id, path=path, format=file_format)
    if file_format in DATABASE_FORMATS:
        return WorkspaceDatabaseDataSource(source_id=source_id, path=path, format=file_format)
    return WorkspaceFileDataSource(source_id=source_id, path=path, format=file_format)


def _deduplicate_columns(columns: Sequence[str]) -> list[str]:
    result = []
    used: dict[str, int] = {}
    for index, raw in enumerate(columns, start=1):
        name = str(raw or f"column_{index}")
        count = used.get(name, 0) + 1
        used[name] = count
        result.append(name if count == 1 else f"{name}_{count}")
    return result


def _file_format(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower().lstrip(".")
    return suffix if suffix in SUPPORTED_FILE_FORMATS else (suffix or "binary")


def _normalize_workspace_path(service: WorkspaceService, path: str) -> str:
    normalize = getattr(service, "normalize_path", None)
    if callable(normalize):
        try:
            return str(normalize(path, allow_root=False)[0])
        except (TypeError, ValueError, WorkspaceError) as error:
            raise ReportDataSourceError("workspace_path_invalid", "工作区路径无效。") from error
    raw = str(path or "").replace("\\", "/")
    candidate = PurePosixPath(raw)
    parts = [part for part in candidate.parts if part not in {"", "."}]
    if candidate.is_absolute() or not parts or ".." in parts:
        raise ReportDataSourceError("workspace_path_invalid", "工作区路径无效。")
    return "/".join(parts)


def _thread(run_context: RunContext | None) -> str:
    if run_context is None or not run_context.session_id:
        raise ReportDataSourceError("thread_required", "当前数据源操作没有绑定对话。")
    return str(run_context.session_id)


def _thread_binding(thread: str) -> str:
    return hashlib.sha256(thread.encode()).hexdigest()


async def rebind_report_dataset_handles(
    session_data: Mapping[str, Any] | None,
    service: WorkspaceService,
    source_thread: str,
    target_thread: str,
) -> dict[str, dict[str, Any]]:
    """重新校验 branch 复制的数据集，并绑定到目标 thread。"""
    if not isinstance(session_data, Mapping):
        return {}
    session_state = session_data.get("session_state")
    if not isinstance(session_state, Mapping):
        return {}
    stored = session_state.get(REPORT_DATASET_HANDLES_STATE_KEY)
    if stored is None:
        return {}
    if not isinstance(stored, Mapping):
        raise ReportDataSourceError("dataset_invalid", "数据集状态无效，请重新准备。")

    expected_source_binding = _thread_binding(source_thread)
    target_binding = _thread_binding(target_thread)
    rebound: dict[str, dict[str, Any]] = {}
    for dataset_id, raw in stored.items():
        if not isinstance(dataset_id, str) or not isinstance(raw, Mapping):
            raise ReportDataSourceError("dataset_invalid", "数据集状态无效，请重新准备。")
        handle = DatasetHandle.from_state(raw)
        if handle.dataset_id != dataset_id or handle.source_type not in {
            "workspace_file",
            "workspace_database",
            "odoo_export",
            "postgresql_materialized",
        }:
            raise ReportDataSourceError("dataset_invalid", "数据集状态无效，请重新准备。")
        if raw.get("_threadBinding") != expected_source_binding:
            raise ReportDataSourceError("stale_dataset", "数据集不属于源对话，请重新物化。")
        if _normalize_workspace_path(service, handle.path) != handle.path:
            raise ReportDataSourceError("dataset_invalid", "数据集路径无效，请重新准备。")

        for thread in (source_thread, target_thread):
            stat = await service.astat(thread, handle.path)
            digest = await service.ahash_file(thread, handle.path)
            if (
                stat.get("type") != "file"
                or int(digest.get("size", -1)) != handle.size
                or digest.get("sha256") != handle.sha256
            ):
                raise ReportDataSourceError(
                    "stale_dataset", "数据集文件已变化，请重新物化并确认分析范围。"
                )
        rebound[dataset_id] = {
            **handle.public_dict(),
            "_threadBinding": target_binding,
        }
    return rebound


def _session_state(run_context: RunContext | None) -> MutableMapping[str, Any]:
    if run_context is None:
        raise ReportDataSourceError("thread_required", "当前数据源操作没有绑定对话。")
    if run_context.session_state is None:
        run_context.session_state = {}
    if not isinstance(run_context.session_state, MutableMapping):
        raise ReportDataSourceError("dataset_state_invalid", "当前数据集状态无效。")
    return run_context.session_state


async def _maybe_await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value
