import pytest

from smart_reporting.reporting.workflow.runtime.chart_inputs import (
    ChartInputError,
    _columns_rows_table,
)


def test_bound_scalar_columns_ignore_unbound_name_lists():
    columns = ["period", "unit_names", "budget", "actual"]
    rows = [["2025-01", ["药剂科"], 10, 12], ["2025-02", [], 20, 18]]

    projected = _columns_rows_table(columns, rows, ["period", "budget", "actual"])

    assert projected == (["period", "budget", "actual"], [["2025-01", 10, 12], ["2025-02", 20, 18]])
    assert rows[0][1] == ["药剂科"]


def test_bound_nested_column_still_requires_fallback():
    with pytest.raises(ChartInputError, match="标量"):
        _columns_rows_table(["unit_names", "actual"], [[["药剂科"], 12]], ["unit_names"])


def test_unbound_columns_do_not_hide_malformed_row_width():
    with pytest.raises(ChartInputError, match="不等长"):
        _columns_rows_table(["period", "unit_names", "actual"], [["2025-01", 12]], ["actual"])
