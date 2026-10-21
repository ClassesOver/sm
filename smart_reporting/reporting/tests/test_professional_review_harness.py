"""Word-grounded warning benchmark separates false alarms from missed issues."""

import json

import pytest

from scripts import check_professional_review as harness
from smart_reporting.reporting.hospital_operation.professional_review import (
    review_professional_content,
)

CASES = json.loads(harness.DEFAULT_CASES.read_text())["cases"]


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_document_policy_cases(case):
    issues = review_professional_content(case["text"])
    assert {issue.code for issue in issues} == set(case["expectedCodes"])
    assert all(set(case["reviewIds"]) & set(issue.review_ids) for issue in issues)


@pytest.mark.parametrize("subject,conclusion", [
    ("开单收入增长", "现金流充裕"),
    ("相关系数", "效率提升"),
    ("成本占比高", "管理异常"),
])
@pytest.mark.parametrize("prefix", ["不能仅凭", "无法通过", "不应根据"])
def test_governing_negation_still_limits_inference(subject, conclusion, prefix):
    assert review_professional_content(f"{prefix}{subject}说明{conclusion}。") == ()


def test_harness_does_not_pass_when_detector_returns_no_warnings(monkeypatch):
    monkeypatch.setattr(harness, "review_professional_content", lambda _: ())
    result = harness.evaluate_cases(harness.DEFAULT_CASES)
    assert not result["passed"]
    assert result["falseNegatives"] > 0 and result["recall"] == 0
    assert result["precision"] is None  # No positive predictions is not 100% precision.
    assert result["businessAcceptanceEvaluated"] is False


@pytest.mark.parametrize("cases", [[], [CASES[0], CASES[0]]])
def test_harness_rejects_empty_or_duplicate_cases(tmp_path, cases):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps({"basis": {}, "cases": cases}))
    with pytest.raises(ValueError):
        harness.evaluate_cases(path)


def test_harness_counts_false_positives(tmp_path):
    path = tmp_path / "cases.json"
    case = {**CASES[0], "expectedCodes": []}
    path.write_text(json.dumps({"basis": {}, "cases": [case]}))
    result = harness.evaluate_cases(path)
    assert not result["passed"] and result["falsePositives"] == 1
