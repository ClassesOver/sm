from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any

import anyio
from pydantic import SecretStr
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import SQLAlchemyError

from ..models import ReportingError
from .models import CatalogColumn, CatalogTable, QueryLimits, QueryResult
from .sql_validation import validate_starrocks_read_only_sql

_SOURCE_FIELDS = frozenset(
    {
        "id",
        "type",
        "name",
        "dsnEnv",
        "database",
        "tables",
        "periodColumns",
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
_ALLOWED_GRANT_PRIVILEGES = frozenset({"SELECT", "USAGE"})
_ADMIN_USERS = frozenset({"root", "admin", "administrator"})


@dataclass(frozen=True)
class StarRocksSourceConfig:
    id: str
    name: str
    dsn_env: str
    dsn: SecretStr
    database: str
    tables: tuple[str, ...]
    period_columns: dict[str, str]
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
            "tables": list(self.tables),
            "periodColumns": dict(self.period_columns),
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
    database = raw.get("database")
    if not isinstance(source_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", source_id
    ):
        raise ValueError("报表数据源 id 无效。")
    if not isinstance(dsn_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", dsn_env):
        raise ValueError(f"报表数据源 {source_id} 的 dsnEnv 无效。")
    if not isinstance(database, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", database):
        raise ValueError(f"报表数据源 {source_id} 的 database 无效。")
    tables = _tables(raw.get("tables"), database)
    period_columns = _period_columns(raw.get("periodColumns"), tables)
    dsn = str(environ.get(dsn_env) or "").strip()
    if not dsn:
        raise ValueError(f"报表数据源 {source_id} 缺少环境变量 {dsn_env}。")
    try:
        parsed = make_url(dsn)
    except Exception as error:
        raise ValueError(f"报表数据源 {source_id} 的 DSN 无效。") from error
    if parsed.drivername.split("+", 1)[0] != "starrocks":
        raise ValueError(f"报表数据源 {source_id} 的 DSN 不是 StarRocks。")
    if parsed.database and parsed.database.lower() != database.lower():
        raise ValueError(f"报表数据源 {source_id} 的 DSN 数据库与配置不一致。")
    return StarRocksSourceConfig(
        id=source_id,
        name=_name(raw.get("name"), source_id),
        dsn_env=dsn_env,
        dsn=SecretStr(dsn),
        database=database.lower(),
        tables=tables,
        period_columns=period_columns,
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


class StarRocksDataSourceAdapter:
    """StarRocks 同步驱动的异步边界；公开结果不包含连接信息。"""

    def __init__(self, config: StarRocksSourceConfig):
        self.config = config
        try:
            parsed = make_url(config.connection_dsn())
            if str(parsed.username or "").lower() in _ADMIN_USERS:
                raise ReportingError("source_account_privileged", "报表数据源不能使用管理员账号。")
            self._engine: Engine = create_engine(
                config.connection_dsn(),
                pool_pre_ping=True,
                pool_size=max(
                    config.limits.profile_concurrency,
                    config.limits.query_concurrency,
                ),
                max_overflow=0,
                connect_args={"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30},
            )
        except ReportingError:
            raise
        except Exception as error:
            raise ReportingError(
                "starrocks_driver_unavailable", "StarRocks 数据源驱动不可用。"
            ) from error

    async def verify_read_only(self) -> None:
        valid = await anyio.to_thread.run_sync(self._verify_read_only)
        if not valid:
            raise ReportingError(
                "source_account_not_read_only", "无法证明数据库账号仅具有允许表的只读权限。"
            )

    async def catalog(self) -> tuple[CatalogTable, ...]:
        return await anyio.to_thread.run_sync(self._catalog)

    async def query(self, sql: str) -> QueryResult:
        normalized = validate_starrocks_read_only_sql(
            sql,
            database=self.config.database,
            allowed_tables=self.config.tables,
        )
        return await anyio.to_thread.run_sync(partial(self._query, normalized))

    async def aclose(self) -> None:
        await anyio.to_thread.run_sync(self._engine.dispose)

    def _verify_read_only(self) -> bool:
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(text("SHOW GRANTS")).fetchall()
        except SQLAlchemyError:
            return False
        grants = [str(value) for row in rows for value in row if isinstance(value, str)]
        normalized = "\n".join(grants).upper().replace("`", "")
        if not normalized or " ALL " in f" {normalized} " or "*.*" in normalized:
            return False
        for line in normalized.splitlines():
            if "GRANT " not in line or " ON " not in line:
                continue
            privileges = line.split("GRANT ", 1)[1].split(" ON ", 1)[0]
            if {item.strip() for item in privileges.split(",")} - _ALLOWED_GRANT_PRIVILEGES:
                return False
        return "SELECT" in normalized and all(
            table.upper() in normalized for table in self.config.tables
        )

    def _catalog(self) -> tuple[CatalogTable, ...]:
        inspector = inspect(self._engine)
        result: list[CatalogTable] = []
        try:
            for qualified in self.config.tables:
                database, table = qualified.split(".", 1)
                columns = inspector.get_columns(table, schema=database)
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
                            )
                            for column in columns
                        ),
                    )
                )
        except ReportingError:
            raise
        except SQLAlchemyError as error:
            raise ReportingError("report_catalog_failed", "无法读取 StarRocks catalog。") from error
        return tuple(result)

    def _query(self, sql: str) -> QueryResult:
        rows: list[tuple[Any, ...]] = []
        try:
            with self._engine.connect() as connection:
                connection.execute(
                    text(f"SET query_timeout = {self.config.statement_timeout_seconds}")
                )
                result = connection.execution_options(stream_results=True).execute(text(sql))
                columns = tuple(str(name) for name in result.keys())
                while len(rows) <= self.config.max_rows:
                    chunk = result.fetchmany(min(10_000, self.config.max_rows + 1 - len(rows)))
                    if not chunk:
                        break
                    rows.extend(tuple(row) for row in chunk)
        except SQLAlchemyError as error:
            raise ReportingError("source_query_failed", "StarRocks 查询执行失败。") from error
        if len(rows) > self.config.max_rows:
            raise ReportingError("query_result_too_large", "查询结果超过允许的行数。")
        byte_count = len(
            json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":")).encode()
        )
        if byte_count > self.config.max_bytes:
            raise ReportingError("query_result_too_large", "查询结果超过允许的数据量。")
        return QueryResult(columns=columns, rows=tuple(rows), byte_count=byte_count)


def _name(value: Any, source_id: str) -> str:
    if value is None:
        return source_id
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 200:
        raise ValueError(f"报表数据源 {source_id} 的 name 无效。")
    return value.strip()


def _tables(value: Any, database: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > 200:
        raise ValueError("报表数据源 tables 必须是非空数组。")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_$]*\.[A-Za-z_][A-Za-z0-9_$]*", item
        ):
            raise ValueError("报表数据源 table 无效。")
        if item.split(".", 1)[0].lower() != database.lower():
            raise ValueError("报表数据源 table 必须属于固定数据库。")
        result.append(item.lower())
    if len(set(result)) != len(result):
        raise ValueError("报表数据源 table 不能重复。")
    return tuple(result)


def _period_columns(value: Any, tables: tuple[str, ...]) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(tables):
        raise ValueError("报表数据源 periodColumns 必须完整覆盖 tables。")
    result: dict[str, str] = {}
    for table, column in value.items():
        if not isinstance(column, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_$]{0,127}", column
        ):
            raise ValueError(f"报表数据源 {table} 的期间字段无效。")
        result[table] = column
    return result


def _bounded(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError("报表数据源查询限额无效。")
    return value
