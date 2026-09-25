import json

import pytest

from scripts import coding_wall_breakdown


def _write(tmp_path, name, payload):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _passed_payload(**overrides):
    payload = {
        "status": "passed",
        "seconds": 100.0,
        "plannerRequestMetrics": [{"durationMs": 10_000}],
        "requestMetrics": [
            {
                "requestIndex": 1,
                "durationMs": 5_000,
                "toolNames": ["write_script"],
                "firstToolFailure": {
                    "toolName": "write_script",
                    "code": "report_python_source_path_invalid",
                },
            },
            {"requestIndex": 2, "durationMs": 6_000, "toolNames": ["write_script"]},
            {
                "requestIndex": 3,
                "durationMs": 4_000,
                "toolNames": ["run_script"],
                "firstToolFailure": {"toolName": "run_script", "code": "KeyError"},
            },
            {"requestIndex": 4, "durationMs": 5_000, "toolNames": ["run_script"]},
        ],
        "codingMetrics": [
            {
                "executionSpans": {"script": [3_000, 17_000]},
                "visualReviewDurationMs": 30_000,
                "reasoningTokens": 1234,
                "criticalVisualDefect": False,
            }
        ],
        "reviews": [{"requires_revision": False, "issues": []}],
    }
    payload.update(overrides)
    return payload


def test_breakdown_splits_wall_clock_and_first_write_rejections(tmp_path):
    row = coding_wall_breakdown.breakdown(_write(tmp_path, "c1", _passed_payload()))

    assert row["plannerModelS"] == 10.0
    assert row["codingModelS"] == 20.0
    assert row["scriptExecS"] == 20.0
    assert row["scriptRuns"] == 2
    assert row["visionS"] == 30.0
    assert row["residualS"] == 20.0
    assert row["rejectedWrites"] == 1
    assert row["rejectedWriteS"] == 5.0
    assert row["rejectCodes"] == "report_python_source_path_invalid"
    assert row["acceptedWriteRequest"] == 2
    assert (row["runs"], row["runFailures"]) == (2, 1)
    assert row["firstSuccessfulRunRequest"] == 4
    assert row["gateTripped"] is False


def test_breakdown_keeps_missing_fields_unknown(tmp_path):
    payload = _passed_payload(
        plannerRequestMetrics=[{"durationMs": "unknown"}],
        codingMetrics=[{"executionSpans": "unknown"}],
    )
    payload.pop("reviews")

    row = coding_wall_breakdown.breakdown(_write(tmp_path, "c2", payload))

    assert row["plannerModelS"] == "unknown"
    assert row["scriptExecS"] == "unknown"
    assert row["visionS"] == "unknown"
    assert row["residualS"] == "unknown"
    assert row["gateTripped"] == "unknown"


def test_coding_only_breakdown_has_no_planner_time(tmp_path):
    payload = _passed_payload(benchmarkMode="coding-only")
    payload.pop("plannerRequestMetrics")

    row = coding_wall_breakdown.breakdown(_write(tmp_path, "c3", payload))

    assert row["plannerModelS"] == 0.0
    assert row["residualS"] == 30.0


def test_breakdown_marks_gate_tripped_passed_sample(tmp_path):
    payload = _passed_payload(
        reviews=[
            {
                "requiresRevision": True,
                "issues": [
                    {"severity": "critical", "category": "text_overlap"},
                    {"severity": "warning", "category": "color"},
                ],
            }
        ]
    )

    row = coding_wall_breakdown.breakdown(_write(tmp_path, "c4", payload))

    assert row["gateTripped"] is True
    assert row["gateCriticalCategories"] == "text_overlap"


def test_wilson_interval_matches_known_values():
    low, high = coding_wall_breakdown.wilson_interval(8, 11)

    assert low == pytest.approx(0.4344, abs=1e-3)
    assert high == pytest.approx(0.9025, abs=1e-3)


def test_expected_seconds_per_delivery_charges_failures_by_pass_rate():
    assert coding_wall_breakdown.expected_seconds_per_delivery(
        796, 833, 0.55
    ) == pytest.approx(796 + 0.45 / 0.55 * 833)
    with pytest.raises(ValueError):
        coding_wall_breakdown.expected_seconds_per_delivery(1, 1, 0)


def test_summary_excludes_censored_samples_and_reports_gate_rate(tmp_path):
    rows = [
        coding_wall_breakdown.breakdown(_write(tmp_path, "pass", _passed_payload())),
        coding_wall_breakdown.breakdown(
            _write(
                tmp_path,
                "gated",
                _passed_payload(
                    seconds=200.0,
                    reviews=[
                        {
                            "requiresRevision": True,
                            "issues": [{"severity": "critical", "category": "text_overlap"}],
                        }
                    ],
                ),
            )
        ),
        coding_wall_breakdown.breakdown(
            _write(
                tmp_path,
                "failed",
                {
                    "status": "failed",
                    "seconds": 300.0,
                    "failure": {"code": "report_code_model_request_limit"},
                },
            )
        ),
        coding_wall_breakdown.breakdown(
            _write(tmp_path, "timeout", {"status": "timed_out", "seconds": 999.0})
        ),
    ]

    lines = coding_wall_breakdown.summarize(rows)

    assert lines[0] == "samples=4 passed=2 failed=1 censored=1"
    assert lines[1].startswith("passRate=67% ")
    assert lines[1].endswith("n=3")
    assert "expectedSecondsPerDelivery=300.0" in lines
    assert any(
        line.startswith("gateTrippedRate=50% (1/2)") and "text_overlap" in line
        for line in lines
    )
