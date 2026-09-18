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
