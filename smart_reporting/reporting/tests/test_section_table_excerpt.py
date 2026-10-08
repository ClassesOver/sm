import json

import pytest

from smart_reporting.reporting.workflow.runtime.sections import (
    _compile_section_relevance_matcher,
    _project_json_evidence,
)


@pytest.mark.parametrize("term", ["人员支出", "total_cost"])
def test_over_budget_table_excerpt_preserves_row_columns_and_percent_metadata(term):
    table = {
        "name": "成本构成",
        "columns": ["类别", "金额", "占比"],
        "columnMeta": {"金额": {"unit": "元"}, "占比": {"unit": "%", "isPercent": True}},
        "rows": [["人员支出", 3500, 35.32], *[[f"其他类别{i}", i, 0.1] for i in range(100)]],
    }
    content = json.dumps({"findings": [table]}, ensure_ascii=False)
    projected, view = _project_json_evidence(
        content, _compile_section_relevance_matcher([term]), token_budget=350
    )
    rows = [item["value"] for item in json.loads(projected)["selected"]
            if isinstance(item["value"], dict) and "rows" in item["value"]]
    assert rows, "超限摘录不能只保留类别名而丢失同一行的金额与百分数"
    assert rows[0]["columns"] == table["columns"]
    assert rows[0]["rows"] == [["人员支出", 3500, 35.32]]
    assert rows[0]["columnMeta"] == table["columnMeta"]
    assert rows[0]["sourceRowIndex"] == 0
    assert rows[0]["sourceRowCount"] == 101
    assert view["truncated"] is True


def test_table_excerpt_does_not_inherit_parent_unit_and_keeps_null():
    table = {"columns": ["类别", "数值"], "rows": [["人员支出", None],
             *[[f"其他类别{i}", i] for i in range(100)]]}
    content = json.dumps({"findings": [{"unit": "元", "tables": [table]}]}, ensure_ascii=False)
    projected, _ = _project_json_evidence(
        content, _compile_section_relevance_matcher(["人员支出"]), token_budget=350
    )
    rows = [item["value"] for item in json.loads(projected)["selected"]
            if isinstance(item["value"], dict) and "rows" in item["value"]]
    assert rows and rows[0]["rows"] == [["人员支出", None]]
    assert "columnMeta" not in rows[0]
