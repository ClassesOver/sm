from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import URL, create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoSuchModuleError, SQLAlchemyError

from .models import ReportingError
from .providers import (
    QueryResult,
    SourceDescription,
    SourceProfile,
    metadata_fingerprint,
)

_ALLOWED_GRANT_PRIVILEGES = frozenset({"SELECT", "USAGE"})


class SqlAlchemyStarRocksClient:
    """使用 StarRocks 官方 SQLAlchemy dialect 的同步客户端。"""

    def __init__(self, credentials: Mapping[str, str | int]):
        try:
            url = URL.create(
                "starrocks",
                username=str(credentials["username"]),
                password=str(credentials["password"]),
                host=str(credentials["host"]),
                port=int(credentials["port"]),
                database=str(credentials["database"]),
            )
            self._engine: Engine = create_engine(
                url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 10, "read_timeout": 30, "write_timeout": 30},
            )
        except (KeyError, TypeError, ValueError, NoSuchModuleError) as error:
            raise ReportingError(
                "starrocks_driver_unavailable", "StarRocks 官方 SQLAlchemy dialect 不可用。"
            ) from error
        self.database = str(credentials["database"])

    def verify_read_only(self, allowed_tables: tuple[str, ...]) -> bool:
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
            values = {item.strip() for item in privileges.split(",")}
            if values - _ALLOWED_GRANT_PRIVILEGES:
                return False
        return (
            all(table.upper() in normalized for table in allowed_tables) and "SELECT" in normalized
        )

    def describe(self, allowed_tables: tuple[str, ...]) -> SourceDescription:
        inspector = inspect(self._engine)
        tables: dict[str, tuple[Mapping[str, Any], ...]] = {}
        try:
            for qualified in allowed_tables:
                database, table = _qualified_table(qualified, self.database)
                columns = inspector.get_columns(table, schema=database)
                tables[f"{database.lower()}.{table.lower()}"] = tuple(
                    {
                        "name": str(column.get("name") or ""),
                        "type": str(column.get("type") or ""),
                        "nullable": bool(column.get("nullable", True)),
                        "comment": str(column.get("comment") or "")[:1000],
                    }
                    for column in columns
                )
        except SQLAlchemyError as error:
            raise ReportingError("source_describe_failed", "无法读取 StarRocks 表结构。") from error
        return SourceDescription(self.database, tables, metadata_fingerprint(tables))

    def profile(
        self,
        allowed_tables: tuple[str, ...],
        *,
        timeout_seconds: int,
    ) -> SourceProfile:
        tables: dict[str, Mapping[str, Any]] = {}
        for qualified in allowed_tables:
            database, table = _qualified_table(qualified, self.database)
            sql = f"SELECT COUNT(*) AS row_count FROM `{database}`.`{table}`"
            result = self.query(sql, timeout_seconds=timeout_seconds, max_rows=1)
            tables[f"{database.lower()}.{table.lower()}"] = {
                "rowCount": int(result.rows[0][0]) if result.rows else 0
            }
        return SourceProfile(tables)

    def query(self, sql: str, *, timeout_seconds: int, max_rows: int) -> QueryResult:
        rows: list[tuple[Any, ...]] = []
        try:
            with self._engine.connect() as connection:
                connection.execute(text(f"SET query_timeout = {int(timeout_seconds)}"))
                result = connection.execution_options(stream_results=True).execute(text(sql))
                columns = tuple(str(name) for name in result.keys())
                while len(rows) <= max_rows:
                    chunk = result.fetchmany(min(10_000, max_rows + 1 - len(rows)))
                    if not chunk:
                        break
                    rows.extend(tuple(row) for row in chunk)
        except SQLAlchemyError as error:
            raise ReportingError("source_query_failed", "StarRocks 查询执行失败。") from error
        if len(rows) > max_rows:
            raise ReportingError("query_result_too_large", "查询结果超过允许的行数。")
        byte_count = len(
            json.dumps(rows, ensure_ascii=False, default=str, separators=(",", ":")).encode()
        )
        return QueryResult(columns, tuple(rows), byte_count)

    def close(self) -> None:
        self._engine.dispose()


def create_starrocks_client(credentials: Mapping[str, str | int]) -> SqlAlchemyStarRocksClient:
    return SqlAlchemyStarRocksClient(credentials)


def _qualified_table(value: str, database: str) -> tuple[str, str]:
    parts = value.split(".")
    if len(parts) == 1:
        return database, parts[0]
    if len(parts) == 2 and parts[0].lower() == database.lower():
        return parts[0], parts[1]
    raise ReportingError("source_binding_invalid", "允许表必须属于已绑定数据库。")
