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


def _byte_count(value):
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _grouped_metric(index):
    groups = [
        {"group": f"总部院区 / 科室{index}-{rank}", "groupValues": {"dept": f"科室{rank}"},
         "value": 1000 - rank}
        for rank in range(10)
    ]
    return {
        "displayName": f"指标{index}",
        "total": 10_000,
        "topGroups": groups,
        "bottomGroups": list(reversed(groups)),
        "periodValues": [{"period": f"2025-{month:02d}", "value": month} for month in range(1, 13)],
    }


def test_summary_trims_group_extremes_before_period_series():
    payload = {
        "deterministicFacts": {"metrics": [_grouped_metric(index) for index in range(40)]},
        "supplementalEvidence": None,
    }
    original = deepcopy(payload)
    budget = _byte_count(payload) // 2

    projected = _project_analysis_summary_payload(
        payload, max_tokens=budget, count_tokens=_byte_count
    )

    assert payload == original
    assert _byte_count(projected) <= budget
    metric = projected["deterministicFacts"]["metrics"][0]
    assert metric["total"] == 10_000
    assert len(metric["topGroups"]) < 10
    assert metric["topGroups"] == original["deterministicFacts"]["metrics"][0]["topGroups"][
        : len(metric["topGroups"])
    ]
    assert metric["topGroupsView"]["rowCount"] == 10
    # 组合明细已足够腾出预算时，期间序列保持完整。
    assert len(metric["periodValues"]) == 12


def test_summary_keeps_strongest_correlations_when_trimming_details():
    details = [
        {"leftField": f"a{index}", "rightField": f"b{index}", "value": value}
        for index, value in enumerate([0.1, -0.95, 0.3] + [0.05] * 200)
    ]
    payload = {
        "deterministicFacts": {"metrics": [], "correlationDetails": details},
        "supplementalEvidence": None,
    }
    budget = _byte_count(payload) // 3

    projected = _project_analysis_summary_payload(
        payload, max_tokens=budget, count_tokens=_byte_count
    )

    kept = projected["deterministicFacts"]["correlationDetails"]
    assert _byte_count(projected) <= budget
    assert kept[0] == details[0] and details[1] in kept
    assert projected["deterministicFacts"]["correlationDetailsView"]["rowCount"] == 203


def test_summary_series_stage_does_not_reexpand_compacted_evidence_tables():
    table = {"columns": ["month", "amount"], "rows": [[index, index] for index in range(2000)]}
    payload = {
        "supplementalEvidenceSource": {"path": "evidence.json", "sha256": "a" * 64, "size": 1},
        "supplementalEvidence": {"findings": [table]},
        "deterministicFacts": {"metrics": [{
            "total": 1,
            "periodValues": [{"period": str(index), "value": index} for index in range(3000)],
        }]},
    }

    projected = _project_analysis_summary_payload(
        payload, max_tokens=4000, count_tokens=_byte_count
    )

    assert _byte_count(projected) <= 4000
    assert len(projected["supplementalEvidence"]["findings"][0]["rows"]) <= 2


def test_summary_trims_pairwise_correlation_table_by_strength():
    rows = [[0, f"m{index}", f"n{index}", 0.01] for index in range(400)]
    rows[123][3] = -0.99
    payload = {
        "deterministicFacts": {"metrics": [], "correlations": {
            "datasets": ["dataset-1"], "columns": ["dataset", "left", "right", "value"], "rows": rows,
        }},
        "supplementalEvidence": None,
    }
    budget = _byte_count(payload) // 4

    projected = _project_analysis_summary_payload(
        payload, max_tokens=budget, count_tokens=_byte_count
    )

    table = projected["deterministicFacts"]["correlations"]
    assert _byte_count(projected) <= budget
    assert rows[123] in table["rows"] and table["datasets"] == ["dataset-1"]
    assert table["view"]["rowCount"] == 400


def test_summary_truncates_nested_record_lists_and_records_original_counts():
    items = [{"科室": f"科室{index}", "金额": index, "说明": "门诊收入变化" * 5} for index in range(500)]
    payload = {
        "supplementalEvidenceSource": {"path": "evidence.json", "sha256": "a" * 64, "size": 1},
        "supplementalEvidence": {"findings": [{"name": "科室明细", "items": items}]},
    }
    original = deepcopy(payload)
    budget = _byte_count(payload) // 10

    projected = _project_analysis_summary_payload(
        payload, max_tokens=budget, count_tokens=_byte_count
    )

    assert payload == original
    assert _byte_count(projected) <= budget
    evidence = projected["supplementalEvidence"]
    kept = evidence["findings"][0]["items"]
    assert kept == items[: len(kept)] and len(kept) < 500
    assert evidence["projection"]["truncatedLists"] == [
        {"path": "findings[0].items", "rowCount": 500, "selectedRowCount": len(kept)}
    ]
    assert evidence["sourceFile"] == payload["supplementalEvidenceSource"]


def test_summary_only_counts_tables_that_can_shrink():
    # 200 行的表在首轮 256 行上限下不会变小，只能在后续减半阶段一起压缩。
    small = {"columns": ["a"], "rows": [[index] for index in range(200)]}
    large = {"columns": ["a"], "rows": [[index] for index in range(5000)]}
    payload = {
        "supplementalEvidenceSource": {"path": "evidence.json", "sha256": "a" * 64, "size": 1},
        "supplementalEvidence": {"findings": [deepcopy(small) for _ in range(100)] + [large]},
    }
    calls = 0

    def count(value):
        nonlocal calls
        calls += 1
        return _byte_count(value)

    budget = 100_000
    projected = _project_analysis_summary_payload(payload, max_tokens=budget, count_tokens=count)

    assert _byte_count(projected) <= budget
    assert calls <= 5
