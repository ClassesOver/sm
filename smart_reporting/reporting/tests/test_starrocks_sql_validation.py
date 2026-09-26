import pytest

from smart_reporting.reporting.data_source.sql_validation import validate_starrocks_read_only_sql
from smart_reporting.reporting.models import ReportingError


def test_starrocks_validation_rejects_double_quoted_column_reference() -> None:
    sql = 'SELECT t."indicator_name" FROM rj.dwd_hdc_cost_table_view AS t'

    with pytest.raises(ReportingError, match="字段引用不能使用字符串引号"):
        validate_starrocks_read_only_sql(
            sql,
            database="rj",
            allowed_tables=("rj.dwd_hdc_cost_table_view",),
        )


def test_starrocks_validation_accepts_backtick_column_reference() -> None:
    sql = "SELECT t.`indicator_name` FROM rj.dwd_hdc_cost_table_view AS t"

    assert (
        validate_starrocks_read_only_sql(
            sql,
            database="rj",
            allowed_tables=("rj.dwd_hdc_cost_table_view",),
        )
        == sql
    )


def test_starrocks_validation_keeps_single_quoted_string_condition() -> None:
    sql = "SELECT t.`indicator_name` FROM rj.dwd_hdc_cost_table_view AS t WHERE t.`area` = '上海'"

    assert (
        validate_starrocks_read_only_sql(
            sql,
            database="rj",
            allowed_tables=("rj.dwd_hdc_cost_table_view",),
        )
        == sql
    )


_ALLOWED = ("rj.dwd_hdc_cost_table_view",)


@pytest.mark.parametrize(
    "sql",
    [
        # CTE 与未授权表同名：CTE 体内的引用指向真实表，不能被 CTE 名豁免。
        "WITH secret_salary AS (SELECT * FROM secret_salary) SELECT * FROM secret_salary",
        # 非递归 WITH 中前向引用后定义的 CTE 名，同样指向真实表。
        "WITH a AS (SELECT * FROM b), b AS (SELECT 1 AS x) SELECT * FROM a",
    ],
    ids=["cte_shadow", "forward_ref"],
)
def test_starrocks_validation_rejects_cte_names_that_do_not_scope_the_reference(sql: str) -> None:
    with pytest.raises(ReportingError) as caught:
        validate_starrocks_read_only_sql(sql, database="rj", allowed_tables=_ALLOWED)

    assert caught.value.code == "sql_table_denied"


@pytest.mark.parametrize(
    "sql",
    [
        "WITH base AS (SELECT * FROM rj.dwd_hdc_cost_table_view) SELECT * FROM base",
        "WITH a AS (SELECT * FROM rj.dwd_hdc_cost_table_view), b AS (SELECT * FROM a) SELECT * FROM b",
        "SELECT * FROM (WITH base AS (SELECT * FROM rj.dwd_hdc_cost_table_view) SELECT * FROM base) AS t",
        "WITH base AS (SELECT `area` FROM rj.dwd_hdc_cost_table_view) "
        "SELECT * FROM rj.dwd_hdc_cost_table_view WHERE `area` IN (SELECT `area` FROM base)",
    ],
    ids=["normal", "chained", "nested_subquery", "in_where"],
)
def test_starrocks_validation_accepts_visible_cte_references(sql: str) -> None:
    assert validate_starrocks_read_only_sql(sql, database="rj", allowed_tables=_ALLOWED) == sql


@pytest.mark.parametrize(
    "sql",
    ["SELECT database()", "SELECT schema()", "SELECT session_user()", "SELECT @@hostname"],
)
def test_starrocks_validation_rejects_normalized_session_functions(sql: str) -> None:
    with pytest.raises(ReportingError) as caught:
        validate_starrocks_read_only_sql(sql, database="rj", allowed_tables=_ALLOWED)

    assert caught.value.code == "sql_function_denied"
