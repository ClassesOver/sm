"""Measure finite professional-warning false positives and missed diagnoses.

Expectations are synthetic policy cases derived from the annotated Word, not
blind business adjudications and not a financial acceptance certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from smart_reporting.reporting.hospital_operation.professional_review import (
    PROFESSIONAL_REVIEW_VERSION,
    review_professional_content,
)

DEFAULT_CASES = Path(__file__).resolve().parents[1] / (
    "smart_reporting/reporting/tests/fixtures/professional_review_cases.json"
)


def evaluate_cases(path: Path) -> dict:
    raw = path.read_bytes()
    fixture = json.loads(raw)
    cases = fixture["cases"]
    ids = [case["id"] for case in cases]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Cases must be nonempty with unique identities")
    rows = []
    true_positive = false_positive = false_negative = 0
    for case in cases:
        if not case["reviewIds"] or not case["text"].strip():
            raise ValueError("Each case requires review provenance and nonempty text")
        expected = set(case["expectedCodes"])
        actual = {issue.code for issue in review_professional_content(case["text"])}
        true_positive += len(expected & actual)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        rows.append({"id": case["id"], "reviewIds": case["reviewIds"],
                     "passed": actual == expected, "expectedCodes": sorted(expected),
                     "actualCodes": sorted(actual), "falsePositives": sorted(actual - expected),
                     "missedWarnings": sorted(expected - actual)})
    return {
        "passed": all(row["passed"] for row in rows),
        "checkerVersion": PROFESSIONAL_REVIEW_VERSION,
        "fixtureSha256": hashlib.sha256(raw).hexdigest(),
        "basis": fixture["basis"], "executedCases": len(rows),
        "coveredReviewIds": sorted({ref for case in cases for ref in case["reviewIds"]}),
        "truePositives": true_positive, "falsePositives": false_positive,
        "falseNegatives": false_negative,
        "precision": true_positive / (true_positive + false_positive) if true_positive + false_positive else None,
        "recall": true_positive / (true_positive + false_negative) if true_positive + false_negative else None,
        "businessAcceptanceEvaluated": False, "cases": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate_cases(args.cases)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"{'PASS' if result['passed'] else 'FAIL'}: {result['executedCases']} cases, "
          f"FP={result['falsePositives']}, FN={result['falseNegatives']}; {args.output}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
