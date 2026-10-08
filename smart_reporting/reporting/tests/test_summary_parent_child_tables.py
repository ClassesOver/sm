import json
from copy import deepcopy

from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    _project_analysis_summary_payload,
)


def test_summary_projects_child_tables_even_when_parent_has_rows():
    rows = [[index, index * 10] for index in range(1000)]
    table = {"columns": ["month", "amount"], "rows": rows}
    payload = {
        "supplementalEvidenceSource": {"path": "evidence.json", "sha256": "a" * 64, "size": 100000},
        "supplementalEvidence": {"findings": [{**deepcopy(table), "tables": [deepcopy(table)]}]},
    }
    original = deepcopy(payload)
    def count(value):
        return len(json.dumps(value))

    projected = _project_analysis_summary_payload(payload, max_tokens=2000, count_tokens=count)

    assert payload == original
    assert count(projected) <= 2000
    parent = projected["supplementalEvidence"]["findings"][0]
    for selected in [parent, parent["tables"][0]]:
        assert len(selected["rows"]) < len(rows)
        included = sum(row[1] for row in selected["rows"])
        assert included + selected["view"]["omittedNumericSums"]["amount"] == sum(row[1] for row in rows)
    assert projected["supplementalEvidence"]["sourceFile"] == payload["supplementalEvidenceSource"]


def test_summary_compacts_long_warning_text_without_mutating_evidence():
    payload = {
        "supplementalEvidenceSource": {"path": "evidence.json", "sha256": "c" * 64},
        "supplementalEvidence": {
            "findings": [{"name": "收入汇总", "columns": ["amount"], "rows": [[1]]}],
            "warnings": ["重复告警" * 200 for _ in range(100)],
            "reconciliations": [{"name": "总量守恒", "passed": True}],
        },
    }
    original = deepcopy(payload)

    def count(value):
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    projected = _project_analysis_summary_payload(payload, max_tokens=5000, count_tokens=count)

    assert payload == original
    assert count(projected) <= 5000
    warnings = projected["supplementalEvidence"]["warnings"]
    assert len(warnings) <= 33
    assert warnings[-1].endswith("完整 evidence 文件。")
    assert projected["supplementalEvidence"]["reconciliations"] == original[
        "supplementalEvidence"
    ]["reconciliations"]
