import json
from copy import deepcopy

import pytest

from smart_reporting.reporting.models import ReportingError
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


@pytest.mark.parametrize("with_supplement", [False, True])
def test_summary_projects_long_fact_series_preserving_totals_and_source(with_supplement):
    payload = {
        "currentAnalysis": {"managementQuestion": "期间收入如何变化？"},
        "deterministicFactsSource": {
            "path": "facts/analysis_014.json", "sha256": "b" * 64, "size": 100000,
        },
        "deterministicFacts": {
            "metrics": [{
                "factId": "fact-0123456789abcdef",
                "unit": "元",
                "total": 1200,
                "periodGranularity": "day",
                "periodValues": [{"period": str(index), "value": 1} for index in range(1200)],
            }],
        },
        "supplementalEvidence": ({
            "findings": [{"name": "收入总额", "columns": ["amount"], "rows": [[1200]]}],
            "reconciliations": [{"name": "总额守恒", "passed": True}],
        } if with_supplement else None),
    }
    original = deepcopy(payload)

    def count(value):
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    projected = _project_analysis_summary_payload(payload, max_tokens=6000, count_tokens=count)

    assert payload == original
    assert count(projected) <= 6000
    assert projected["deterministicFactsSource"] == original["deterministicFactsSource"]
    metric = projected["deterministicFacts"]["metrics"][0]
    assert metric["factId"] == "fact-0123456789abcdef"
    assert metric["unit"] == "元"
    assert metric["total"] == 1200
    assert 2 <= len(metric["periodValues"]) < 1200
    assert metric["periodValues"][0] == {"period": "0", "value": 1}
    assert metric["periodValues"][-1] == {"period": "1199", "value": 1}
    view = metric["periodValuesView"]
    assert view["truncated"] is True
    assert view["rowCount"] == 1200
    assert sum(item["value"] for item in metric["periodValues"]) + view["omittedNumericSums"]["value"] == 1200
    assert projected["supplementalEvidence"] == original["supplementalEvidence"]


def test_summary_reports_component_sizes_when_projection_still_exceeds_budget():
    payload = {"currentAnalysis": {"managementQuestion": "问题" * 1000}, "supplementalEvidence": None}

    def count(value):
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    with pytest.raises(ReportingError) as caught:
        _project_analysis_summary_payload(payload, max_tokens=100, count_tokens=count)

    assert caught.value.code == "report_analysis_summary_context_too_large"
    details = caught.value.details
    assert details["projectedTokens"] > details["inputTokenBudget"] == 100
    assert details["componentBytes"]["currentAnalysis"] >= 6000


def test_summary_keeps_short_series_when_projection_metadata_would_increase_size():
    short = {"total": 3, "periodValues": [
        {"period": str(index), "value": 1} for index in range(3)
    ]}
    payload = {"deterministicFacts": {"metrics": [
        *[deepcopy(short) for _ in range(50)],
        {"total": 1200, "periodValues": [
            {"period": str(index), "value": 1} for index in range(1200)
        ]},
    ]}, "supplementalEvidence": None}

    def count(value):
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))

    projected = _project_analysis_summary_payload(payload, max_tokens=12000, count_tokens=count)

    assert count(projected) <= 12000
    assert projected["deterministicFacts"]["metrics"][:50] == [short] * 50
    assert len(projected["deterministicFacts"]["metrics"][-1]["periodValues"]) < 1200
