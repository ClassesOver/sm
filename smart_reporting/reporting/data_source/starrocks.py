from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from typing import Any

import anyio
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp, parse_one

from ..models import ReportingError
from .materialization import CsvMaterializer
from .models import CatalogColumn, CatalogTable, MaterializedQueryResult, QueryLimits, QueryResult
from .sql_validation import validate_starrocks_read_only_sql

_SOURCE_FIELDS = frozenset(
    {
        "id",
        "type",
        "name",
        "dsnEnv",
        "database",
        "statementTimeoutSeconds",
        "maxRows",
        "maxBytes",
        "exactDistinctMaxRows",
        "statisticsColumnBatchSize",
        "topValuesMaxColumns",
        "topValuesLimit",
        "profileConcurrency",
        "queryConcurrency",
    }
)


@dataclass(frozen=True)
class StarRocksSourceConfig:
    id: str
    name: str
    dsn_env: str
    dsn: SecretStr
    database: str
    limits: QueryLimits
    source_type: str = "starrocks"

    @property
    def statement_timeout_seconds(self) -> int:
        return self.limits.statement_timeout_seconds

    @property
    def max_rows(self) -> int:
        return self.limits.max_rows

    @property
    def max_bytes(self) -> int:
        return self.limits.max_bytes

    def public_dict(self) -> dict[str, Any]:
        return {
            "sourceId": self.id,
            "sourceType": self.source_type,
            "name": self.name,
            "database": self.database,
            "limits": self.limits.public_dict(),
        }

    def connection_dsn(self) -> str:
        return self.dsn.get_secret_value()


def parse_starrocks_source(
    raw: Mapping[str, Any],
    environ: Mapping[str, str],
) -> StarRocksSourceConfig:
    if set(raw) - _SOURCE_FIELDS:
        raise ValueError("StarRocks 数据源配置包含未知字段。")
    source_id = raw.get("id")
    dsn_env = raw.get("dsnEnv")
    configured_database = raw.get("database")
    if not isinstance(source_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", source_id
    ):
        raise ValueError("报表数据源 id 无效。")
    if not isinstance(dsn_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", dsn_env):
        raise ValueError(f"报表数据源 {source_id} 的 dsnEnv 无效。")
    if configured_database is not None and (
        not isinstance(configured_database, str)
        or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", configured_database)
    ):
        raise ValueError(f"报表数据源 {source_id} 的 database 无效。")
    dsn = str(environ.get(dsn_env) or "").strip()
    if not dsn:
        raise ValueError(f"报表数据源 {source_id} 缺少环境变量 {dsn_env}。")
    try:
        parsed = make_url(dsn)
    except Exception as error:
        raise ValueError(f"报表数据源 {source_id} 的 DSN 无效。") from error
    if parsed.drivername.split("+", 1)[0] != "starrocks":
        raise ValueError(f"报表数据源 {source_id} 的 DSN 不是 StarRocks。")
    # DSN 是连接身份的唯一事实来源。新配置省略 database 时直接采用 DSN 路径；
    # 旧配置仍允许显式声明，但必须与 DSN 一致，避免静默连接到错误数据库。
    if configured_database is None:
        if not parsed.database or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", parsed.database):
            raise ValueError(f"报表数据源 {source_id} 的 DSN 必须包含数据库。")
        database = parsed.database
    else:
        database = configured_database
    if parsed.database and parsed.database.lower() != database.lower():
        raise ValueError(f"报表数据源 {source_id} 的 DSN 数据库与配置不一致。")
    return StarRocksSourceConfig(
        id=source_id,
        name=_name(raw.get("name"), source_id),
        dsn_env=dsn_env,
        dsn=SecretStr(dsn),
        database=database.lower(),
        limits=QueryLimits(
            statement_timeout_seconds=_bounded(raw.get("statementTimeoutSeconds"), 30, 1, 300),
            max_rows=_bounded(raw.get("maxRows"), 1_000_000, 1, 5_000_000),
            max_bytes=_bounded(raw.get("maxBytes"), 256 * 1024 * 1024, 1, 256 * 1024 * 1024),
            exact_distinct_max_rows=_bounded(
                raw.get("exactDistinctMaxRows"), 1_000_000, 1, 100_000_000
            ),
            statistics_column_batch_size=_bounded(raw.get("statisticsColumnBatchSize"), 24, 1, 50),
            top_values_max_columns=_bounded(raw.get("topValuesMaxColumns"), 20, 0, 50),
            top_values_limit=_bounded(raw.get("topValuesLimit"), 10, 1, 100),
            profile_concurrency=_bounded(raw.get("profileConcurrency"), 4, 1, 16),
            query_concurrency=_bounded(raw.get("queryConcurrency"), 2, 1, 8),
        ),
    )


def _catalog_comment(value: Any, *, max_length: int) -> str:
    description = str(value or "")
    if len(description) > max_length:
        raise ReportingError("report_catalog_drift", "实时 catalog 注释超出长度限制。")
    return description


class StarRocksDataSourceAdapter:
    """StarRocks 同步驱动的异步边界；公开结果不包含连接信息。"""

    def __init__(
        self,
        config: StarRocksSourceConfig,
        *,
        allowed_tables: tuple[str, ...] = (),
    ):
        self.config = config
        self.allowed_tables = _runtime_tables(allowed_tables, config.database)
        try:
            self._engine: Engine = create_engine(
                config.connection_dsn(),
                pool_pre_ping=True,
                pool_size=max(
                    config.limits.profile_concurrency,
                    config.limits.query_concurrency,
                ),
                max_overflow=0,
                # 客户端读超时必须长于服务端 query_timeout，否则可配置的语句超时
                # 超过 30 秒时会被驱动提前断开并误报为查询失败。
                connect_args={
                    "connect_timeout": 10,
                    "read_timeout": config.statement_timeout_seconds + 30,
                    "write_timeout": 30,
                },
            )
        except Exception as error:
            raise ReportingError(
                "starrocks_driver_unavailable", "StarRocks 数据源驱动不可用。"
            ) from error

    async def catalog(self) -> tuple[CatalogTable, ...]:
        return await anyio.to_thread.run_sync(self._catalog)

    async def query(self, sql: str) -> QueryResult:
        normalized = validate_starrocks_read_only_sql(
            sql,
            database=self.config.database,
            allowed_tables=self.allowed_tables,
        )
        return await anyio.to_thread.run_sync(partial(self._query, normalized))

    def _bound_sql(self, sql: str, parameters: Mapping[str, object]) -> str:
        normalized = validate_starrocks_read_only_sql(sql, database=self.config.database, allowed_tables=self.allowed_tables)
        placeholders = tuple(parse_one(normalized, read="mysql").find_all(exp.Placeholder))
        names = {item.name for item in placeholders}
        if (not isinstance(parameters, Mapping) or any(not name or not re.fullmatch(r"p[0-9]+", name) for name in names)
            or names != set(parameters)
            or any(not isinstance(value, (str, int, float, Decimal, date, datetime, type(None)))
                or (isinstance(value, float) and not math.isfinite(value))
                or (isinstance(value, Decimal) and not value.is_finite()) for value in parameters.values())):
            raise ReportingError("query_parameters_invalid", "查询参数与已登记SQL不一致。")
        return normalized

    async def query_bound(self, sql: str, parameters: Mapping[str, object]) -> QueryResult:
        normalized = self._bound_sql(sql, parameters)
        return await anyio.to_thread.run_sync(partial(self._query, normalized, parameters=dict(parameters)))

    async def materialize_bound(self, sql: str, parameters: Mapping[str, object], *, max_bytes: int | None = None) -> MaterializedQueryResult:
        normalized = self._bound_sql(sql, parameters)
        effective_max_bytes = min(self.config.max_bytes, self.config.max_bytes if max_bytes is None else max_bytes)
        if effective_max_bytes <= 0:
            raise ReportingError("query_result_too_large", "查询结果字节上限无效。")
        return await anyio.to_thread.run_sync(partial(self._materialize, normalized, parameters=dict(parameters), max_bytes=effective_max_bytes))

    async def materialize(
        self, sql: str, *, max_bytes: int | None = None
    ) -> MaterializedQueryResult:
        normalized = validate_starrocks_read_only_sql(
            sql,
            database=self.config.database,
            allowed_tables=self.allowed_tables,
        )
        effective_max_bytes = min(
            self.config.max_bytes,
            self.config.max_bytes if max_bytes is None else max_bytes,
        )
        if effective_max_bytes <= 0:
            raise ReportingError("query_result_too_large", "查询结果字节上限无效。")
        return await anyio.to_thread.run_sync(
            partial(self._materialize, normalized, max_bytes=effective_max_bytes)
        )

    async def aclose(self) -> None:
        await anyio.to_thread.run_sync(self._engine.dispose)

    def _catalog(self) -> tuple[CatalogTable, ...]:
        inspector = inspect(self._engine)
        result: list[CatalogTable] = []
        try:
            for qualified in self.allowed_tables:
                database, table = qualified.split(".", 1)
                columns = inspector.get_columns(table, schema=database)
                table_comment = inspector.get_table_comment(table, schema=database)
                if not columns:
                    raise ReportingError(
                        "report_catalog_drift", f"实时 catalog 缺少数据表 {qualified}。"
                    )
                result.append(
                    CatalogTable(
                        source_id=self.config.id,
                        database=database,
                        name=table,
                        columns=tuple(
                            CatalogColumn(
                                name=str(column.get("name") or ""),
                                data_type=str(column.get("type") or ""),
                                nullable=bool(column.get("nullable", True)),
                                description=_catalog_comment(
                                    column.get("comment"),
                                    max_length=2_000,
                                ),
                            )
                            for column in columns
                        ),
                        description=_catalog_comment(
                            table_comment.get("text") if table_comment else None,
                            max_length=4_000,
                        ),
                    )
                )
        except ReportingError:
            raise
        except SQLAlchemyError as error:
            raise ReportingError("report_catalog_failed", "无法读取 StarRocks catalog。") from error
        return tuple(result)

    def _query(self, sql: str, *, parameters: Mapping[str, object] | None = None) -> QueryResult:
        rows: list[tuple[Any, ...]] = []
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(f"SET query_timeout = {self.config.statement_timeout_seconds}")
                )
                # SQL 已完整校验；直接交给驱动，避免 :name 字面量被识别为绑定参数。
                # 无参数调用也防止 MySQL 驱动把字面量中的 % 作为占位符展开。
                result = (connection.execution_options(stream_results=True).execute(text(sql), parameters)
                    if parameters is not None else connection.execution_options(
                        stream_results=True, no_parameters=True).exec_driver_sql(sql))
                columns = tuple(str(name) for name in result.keys())
                byte_count = 2
                if byte_count > self.config.max_bytes:
                    raise ReportingError("query_result_too_large", "查询结果超过允许的数据量。")
                while len(rows) <= self.config.max_rows:
                    chunk = result.fetchmany(min(10_000, self.config.max_rows + 1 - len(rows)))
                    if not chunk:
                        break
                    chunk_rows = tuple(tuple(row) for row in chunk)
                    if len(rows) + len(chunk_rows) > self.config.max_rows:
                        raise ReportingError("query_result_too_large", "查询结果超过允许的行数。")
                    for row in chunk_rows:
                        encoded = json.dumps(
                            row,
                            ensure_ascii=False,
                            default=str,
                            separators=(",", ":"),
                        ).encode()
                        next_byte_count = byte_count + len(encoded) + (1 if rows else 0)
                        if next_byte_count > self.config.max_bytes:
                            raise ReportingError(
                                "query_result_too_large", "查询结果超过允许的数据量。"
                            )
                        rows.append(row)
                        byte_count = next_byte_count
        except SQLAlchemyError as error:
            raise ReportingError("source_query_failed", "StarRocks 查询执行失败。") from error
        return QueryResult(columns=columns, rows=tuple(rows), byte_count=byte_count)

    def _materialize(self, sql: str, *, max_bytes: int | None = None, parameters: Mapping[str, object] | None = None) -> MaterializedQueryResult:
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(f"SET query_timeout = {self.config.statement_timeout_seconds}")
                )
                # 与 query 使用相同的无参数执行契约，保留已校验 SQL 的原始字面量。
                result = (connection.execution_options(stream_results=True).execute(text(sql), parameters)
                    if parameters is not None else connection.execution_options(
                        stream_results=True, no_parameters=True).exec_driver_sql(sql))
                columns = tuple(str(name) for name in result.keys())
                materializer = CsvMaterializer(
                    columns,
                    max_bytes=self.config.max_bytes if max_bytes is None else max_bytes,
                )
                while materializer.row_count <= self.config.max_rows:
                    chunk = result.fetchmany(
                        min(10_000, self.config.max_rows + 1 - materializer.row_count)
                    )
                    if not chunk:
                        break
                    rows = tuple(tuple(row) for row in chunk)
                    if materializer.row_count + len(rows) > self.config.max_rows:
                        raise ReportingError("query_result_too_large", "查询结果超过允许的行数。")
                    materializer.append(rows)
        except SQLAlchemyError as error:
            raise ReportingError("source_query_failed", "StarRocks 查询执行失败。") from error
        return materializer.finish()


def _name(value: Any, source_id: str) -> str:
    if value is None:
        return source_id
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError(f"报表数据源 {source_id} 的 name 无效。")
    return value.strip()


def _runtime_tables(value: tuple[str, ...], database: str) -> tuple[str, ...]:
    if len(value) > 200:
        raise ValueError("DDL 数据表不能超过 200 项。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*", item
        ):
            raise ValueError("DDL 数据表无效。")
        if item.split(".", 1)[0].lower() != database.lower():
            raise ValueError("DDL 数据表必须属于数据源数据库。")
        result.append(item.lower())
    if len(set(result)) != len(result):
        raise ValueError("DDL 数据表不能重复。")
    return tuple(result)


def _bounded(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError("报表数据源查询限额无效。")
    return value
