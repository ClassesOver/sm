from __future__ import annotations

import hashlib
import ipaddress
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from sqlglot import exp, parse

from .credentials import TemporaryCredentialStore
from .data_sources import DatasetHandle
from .models import (
    DataRequirement,
    QueryCandidate,
    ReportingError,
    ReportSourceBinding,
    SourceMode,
)

MAX_QUERY_BYTES = 256 * 1024
DEFAULT_QUERY_TIMEOUT_SECONDS = 30
DEFAULT_MAX_ROWS = 1_000_000
DEFAULT_MAX_BYTES = 256 * 1024 * 1024
_ADMIN_USERS = frozenset({"root", "admin", "administrator"})
_DANGEROUS_FUNCTIONS = frozenset(
    {
        "benchmark",
        "connection_id",
        "current_user",
        "database",
        "load_file",
        "sleep",
        "system_user",
        "user",
    }
)


@dataclass(frozen=True)
class SourceDescription:
    database: str
    tables: Mapping[str, tuple[Mapping[str, Any], ...]]
    metadata_fingerprint: str


@dataclass(frozen=True)
class SourceProfile:
    tables: Mapping[str, Mapping[str, Any]]


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: Sequence[Sequence[Any]]
    byte_count: int


class DatasetMaterializer(Protocol):
    def write_query_result(
        self,
        result: QueryResult,
        *,
        source_id: str,
        provenance: Mapping[str, Any],
    ) -> DatasetHandle: ...


class StarRocksClient(Protocol):
    def verify_read_only(self, allowed_tables: tuple[str, ...]) -> bool: ...

    def describe(self, allowed_tables: tuple[str, ...]) -> SourceDescription: ...

    def profile(
        self,
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: int,
    ) -> SourceProfile: ...

    def query(self, sql: str, *, timeout_seconds: int, max_rows: int) -> QueryResult: ...

    def close(self) -> None: ...


class StarRocksClientFactory(Protocol):
    def __call__(self, credentials: Mapping[str, str | int]) -> StarRocksClient: ...


class ReportDataSourceProvider(Protocol):
    def describe(self) -> SourceDescription: ...

    def profile(self) -> SourceProfile: ...

    def validate_sql(self, sql: str) -> str: ...

    def materialize(self, candidate: QueryCandidate) -> DatasetHandle: ...

    def close(self) -> None: ...


class SqlGenerationProvider(Protocol):
    def generate_sql(self, requirement: DataRequirement, binding: ReportSourceBinding) -> str: ...


class VannaSqlGenerationProvider:
    def __init__(self, generate: Any):
        self._generate = generate

    def generate_sql(self, requirement: DataRequirement, binding: ReportSourceBinding) -> str:
        value = self._generate(requirement.model_dump(by_alias=True), binding.public_dict())
        if not isinstance(value, str) or not value.strip():
            raise ReportingError("vanna_sql_invalid", "Vanna 未返回有效 SQL。")
        return value


class AgentSqlGenerationProvider:
    def __init__(self, generate: Any):
        self._generate = generate

    def generate_sql(self, requirement: DataRequirement, binding: ReportSourceBinding) -> str:
        value = self._generate(requirement.model_dump(by_alias=True), binding.public_dict())
        if not isinstance(value, str) or not value.strip():
            raise ReportingError("agent_sql_invalid", "Agent 未返回有效 SQL。")
        return value


class DatasetHandleProvider:
    def __init__(self, handle: DatasetHandle):
        self._handle = handle

    def describe(self) -> SourceDescription:
        columns = (self._handle.schema or {}).get("columns")
        schema = tuple({"name": str(column)} for column in columns or ())
        tables = {self._handle.dataset_id: schema}
        return SourceDescription(self._handle.source_id, tables, metadata_fingerprint(tables))

    def profile(self) -> SourceProfile:
        return SourceProfile(
            {
                self._handle.dataset_id: {
                    "rowCount": self._handle.row_count,
                    "size": self._handle.size,
                    "sampled": self._handle.sampled,
                }
            }
        )

    def validate_sql(self, sql: str) -> str:
        raise ReportingError("sql_not_applicable", "已有数据集不应执行数据库 SQL。")

    def materialize(self, candidate: QueryCandidate) -> DatasetHandle:
        raise ReportingError("sql_not_applicable", "已有数据集不应重新物化。")

    def close(self) -> None:
        return None


def try_generate_vanna_sql(
    provider: SqlGenerationProvider | None,
    requirement: DataRequirement,
    binding: ReportSourceBinding,
) -> str | None:
    if provider is None:
        return None
    for _attempt in range(3):
        try:
            sql = provider.generate_sql(requirement, binding)
        except Exception:
            continue
        if sql.strip():
            return sql
    return None


def validate_network_target(host: str, allowlist: str | Sequence[str] | None) -> None:
    values = (
        [item.strip() for item in allowlist.split(",")]
        if isinstance(allowlist, str)
        else [str(item).strip() for item in allowlist or ()]
    )
    values = [item for item in values if item]
    if not values:
        raise ReportingError("source_host_denied", "临时数据库主机未配置服务端网络 allowlist。")
    normalized_host = host.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        if normalized_host not in {item.rstrip(".").lower() for item in values if "/" not in item}:
            raise ReportingError("source_host_denied", "临时数据库主机不在允许范围内。")
        return
    for item in values:
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            continue
        if address in network:
            return
    raise ReportingError("source_host_denied", "临时数据库主机不在允许范围内。")


def validate_starrocks_read_only_sql(
    sql: str, *, database: str, allowed_tables: tuple[str, ...]
) -> str:
    normalized = str(sql or "").strip().rstrip(";").strip()
    if not normalized or len(normalized.encode("utf-8")) > MAX_QUERY_BYTES:
        raise ReportingError("invalid_sql", "SQL 必须是非空且不超过 256 KiB 的查询。")
    try:
        statements = parse(sql, read="mysql")
    except Exception as error:
        raise ReportingError("invalid_sql", "SQL 语法无效。") from error
    if len(statements) != 1 or statements[0] is None:
        raise ReportingError("invalid_sql", "只允许执行一条 SQL 查询。")
    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ReportingError("read_only_sql_required", "只允许 SELECT 或只读 CTE。")
    forbidden = tuple(
        item
        for name in (
            "Alter",
            "Command",
            "Create",
            "Delete",
            "Drop",
            "Insert",
            "Into",
            "LoadData",
            "Merge",
            "Transaction",
            "TruncateTable",
            "Update",
        )
        if (item := getattr(exp, name, None)) is not None
    )
    if forbidden and any(isinstance(node, forbidden) for node in statement.walk()):
        raise ReportingError("read_only_sql_required", "SQL 包含写入或管理操作。")
    for function in statement.find_all(exp.Func):
        name = str(getattr(function, "name", "") or "").lower()
        if not name:
            name = str(getattr(function, "sql_name", lambda: "")() or "").lower()
        if name in _DANGEROUS_FUNCTIONS:
            raise ReportingError("sql_function_denied", f"SQL 函数 {name} 不允许使用。")
    allowed = {_normalize_table_name(table, database) for table in allowed_tables}
    ctes = {
        str(cte.alias_or_name).lower() for cte in statement.find_all(exp.CTE) if cte.alias_or_name
    }
    for table in statement.find_all(exp.Table):
        table_name = str(table.name or "").lower()
        table_database = str(table.db or "").lower()
        if not table_database and table_name in ctes:
            continue
        if table.catalog:
            raise ReportingError("sql_table_denied", "SQL 不允许跨数据库查询。")
        qualified = f"{table_database or database.lower()}.{table_name}"
        if table_database and table_database != database.lower():
            raise ReportingError("sql_table_denied", "SQL 不允许跨数据库查询。")
        if qualified not in allowed:
            raise ReportingError("sql_table_denied", f"数据表 {qualified} 不在允许范围内。")
    return normalized


def metadata_fingerprint(description: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    normalized = {
        table.lower(): [dict(sorted(column.items())) for column in columns]
        for table, columns in sorted(description.items())
    }
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class StarRocksProvider:
    def __init__(
        self,
        binding: ReportSourceBinding,
        credentials: TemporaryCredentialStore,
        client_factory: StarRocksClientFactory,
        materializer: DatasetMaterializer,
        *,
        user_id: str,
        thread_id: str,
        session_id: str,
        network_allowlist: str | Sequence[str] | None,
        timeout_seconds: int = DEFAULT_QUERY_TIMEOUT_SECONDS,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ):
        if binding.source_mode is not SourceMode.TEMPORARY_DATABASE:
            raise ReportingError("source_binding_invalid", "数据源绑定不是临时数据库。")
        if not binding.database or not binding.allowed_tables:
            raise ReportingError("source_binding_invalid", "临时数据库绑定范围不完整。")
        request = credentials.resolve(
            binding.binding_id,
            user_id=user_id,
            thread_id=thread_id,
            session_id=session_id,
        )
        validate_network_target(request.host, network_allowlist)
        if request.username.lower() in _ADMIN_USERS:
            raise ReportingError("source_account_privileged", "临时数据库账号不能是管理员账号。")
        self.binding = binding
        self._credentials = credentials
        self._client = client_factory(request.secret_payload())
        self._materializer = materializer
        self._timeout_seconds = timeout_seconds
        self._max_rows = max_rows
        self._max_bytes = max_bytes
        try:
            if not self._client.verify_read_only(binding.allowed_tables):
                raise ReportingError(
                    "source_account_not_read_only", "无法证明数据库账号仅具有目标表只读权限。"
                )
        except BaseException:
            self._client.close()
            raise

    def describe(self) -> SourceDescription:
        description = self._client.describe(self.binding.allowed_tables)
        if description.database.lower() != str(self.binding.database).lower():
            raise ReportingError("source_metadata_changed", "实际数据库与已批准来源不一致。")
        if description.metadata_fingerprint != self.binding.metadata_fingerprint:
            raise ReportingError("source_metadata_changed", "数据源元数据已变化，请重新确认。")
        return description

    def profile(self) -> SourceProfile:
        return self._client.profile(
            self.binding.allowed_tables, timeout_seconds=self._timeout_seconds
        )

    def validate_sql(self, sql: str) -> str:
        return validate_starrocks_read_only_sql(
            sql,
            database=str(self.binding.database),
            allowed_tables=self.binding.allowed_tables,
        )

    def materialize(self, candidate: QueryCandidate) -> DatasetHandle:
        if candidate.binding_id != self.binding.binding_id:
            raise ReportingError("query_binding_mismatch", "查询不属于当前数据源绑定。")
        sql = self.validate_sql(candidate.sql)
        result = self._client.query(
            sql, timeout_seconds=self._timeout_seconds, max_rows=self._max_rows
        )
        if len(result.rows) > self._max_rows or result.byte_count > self._max_bytes:
            raise ReportingError("query_result_too_large", "查询结果超过允许的数据量。")
        return self._materializer.write_query_result(
            result,
            source_id=self.binding.binding_id,
            provenance={
                "bindingId": self.binding.binding_id,
                "requirementId": candidate.requirement_id,
                "metadataFingerprint": self.binding.metadata_fingerprint,
                "generator": candidate.generator,
            },
        )

    def close(self) -> None:
        self._client.close()


class SqlGenerationRouter:
    def __init__(
        self,
        agent_provider: SqlGenerationProvider,
        vanna_provider: SqlGenerationProvider | None = None,
        *,
        vanna_attempts: int = 3,
    ):
        if vanna_attempts != 3:
            raise ValueError("Vanna 失败阈值固定为 3")
        self._agent = agent_provider
        self._vanna = vanna_provider

    def generate(
        self, requirement: DataRequirement, binding: ReportSourceBinding
    ) -> QueryCandidate:
        if requirement.binding_id != binding.binding_id:
            raise ReportingError("requirement_binding_mismatch", "取数需求不属于当前来源。")
        if binding.source_mode in {
            SourceMode.PROVIDED_DATASET,
            SourceMode.WORKSPACE_REFERENCE,
            SourceMode.ODOO_EXPORT,
        }:
            raise ReportingError("sql_not_applicable", "当前来源不应生成 SQL。")
        vanna_sql = try_generate_vanna_sql(self._vanna, requirement, binding)
        if vanna_sql is not None:
            return QueryCandidate(
                requirementId=requirement.requirement_id,
                bindingId=binding.binding_id,
                sql=vanna_sql,
                generator="vanna",
                requiresApproval=False,
            )
        sql = self._agent.generate_sql(requirement, binding)
        return QueryCandidate(
            requirementId=requirement.requirement_id,
            bindingId=binding.binding_id,
            sql=sql,
            generator="agent",
            requiresApproval=binding.source_mode is SourceMode.MANAGED_QUERY,
        )


def _normalize_table_name(table: str, database: str) -> str:
    parts = table.lower().split(".")
    if len(parts) == 1:
        return f"{database.lower()}.{parts[0]}"
    if len(parts) == 2 and parts[0] == database.lower():
        return table.lower()
    raise ReportingError("source_binding_invalid", "允许表必须属于已绑定数据库。")
