from __future__ import annotations

from sqlglot import exp, parse

from ..models import ReportingError

MAX_QUERY_BYTES = 256 * 1024
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


def validate_starrocks_read_only_sql(
    sql: str, *, database: str, allowed_tables: tuple[str, ...]
) -> str:
    normalized = str(sql or "").strip().rstrip(";").strip()
    if not normalized or len(normalized.encode()) > MAX_QUERY_BYTES:
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


def _normalize_table_name(table: str, database: str) -> str:
    parts = table.lower().split(".")
    if len(parts) == 1:
        return f"{database.lower()}.{parts[0]}"
    if len(parts) == 2 and parts[0] == database.lower():
        return table.lower()
    raise ReportingError("source_binding_invalid", "允许表必须属于已配置数据库。")
