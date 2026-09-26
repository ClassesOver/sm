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
    # sqlglot 的 MySQL 解析模式会把 t."column" 解析成列节点下的字符串字面量；
    # StarRocks 不接受这种标识符写法，必须在数据库执行前拒绝，避免确定性运行时失败。
    if any(
        isinstance(column.this, exp.Literal) and column.this.is_string
        for column in statement.find_all(exp.Column)
    ):
        raise ReportingError("invalid_sql", "字段引用不能使用字符串引号，请使用 StarRocks 反引号。")
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
    for table in statement.find_all(exp.Table):
        table_name = str(table.name or "").lower()
        table_database = str(table.db or "").lower()
        # 只有在该位置按 SQL 作用域确实可见的同名 CTE 才能豁免白名单：非递归 CTE 的
        # 定义体里同名或后定义的名字指向真实表，例如
        # `WITH secret AS (SELECT * FROM secret)` 会读取表 secret。
        if not table_database and table_name in _visible_cte_names(table):
            continue
        if table.catalog:
            raise ReportingError("sql_table_denied", "SQL 不允许跨数据库查询。")
        qualified = f"{table_database or database.lower()}.{table_name}"
        if table_database and table_database != database.lower():
            raise ReportingError("sql_table_denied", "SQL 不允许跨数据库查询。")
        if qualified not in allowed:
            raise ReportingError("sql_table_denied", f"数据表 {qualified} 不在允许范围内。")
    return normalized


def _visible_cte_names(node: exp.Expression) -> set[str]:
    visible: set[str] = set()
    child: exp.Expression = node
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.With):
            ctes = list(parent.expressions)
            names = ctes
            if isinstance(child, exp.CTE) and not parent.args.get("recursive"):
                # 非递归 WITH 中，CTE 定义体只能看到排在它之前的 CTE。
                names = ctes[: next(i for i, item in enumerate(ctes) if item is child)]
            visible.update(str(cte.alias_or_name).lower() for cte in names if cte.alias_or_name)
        else:
            with_clause = parent.args.get("with_") or parent.args.get("with")
            if isinstance(with_clause, exp.With) and child is not with_clause:
                visible.update(
                    str(cte.alias_or_name).lower()
                    for cte in with_clause.expressions
                    if cte.alias_or_name
                )
        child, parent = parent, parent.parent
    return visible


def _normalize_table_name(table: str, database: str) -> str:
    parts = table.lower().split(".")
    if len(parts) == 1:
        return f"{database.lower()}.{parts[0]}"
    if len(parts) == 2 and parts[0] == database.lower():
        return table.lower()
    raise ReportingError("source_binding_invalid", "允许表必须属于已配置数据库。")
