from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.checkpoint import (
    CheckpointRetryUsage,
    attach_retry_usage,
    retry_usage_of,
)
from smart_reporting.reporting.workflow.runtime.analysis import (
    _analysis_fact_retry_usage,
    _checkpoint_retry_usage,
    _visualization_retry_usage,
)


def test_retry_usage_travels_with_error_as_typed_value():
    error = RuntimeError("task failed")
    usage = CheckpointRetryUsage(analysisFactQueriesUsed=4)

    attach_retry_usage(error, usage)

    assert retry_usage_of(error) is usage
    assert retry_usage_of(RuntimeError("no usage")) is None
    assert _analysis_fact_retry_usage(error) == 4


def test_analysis_fact_usage_falls_back_to_error_details():
    error = ReportingError("report_analysis_fact_query_budget_exhausted", "x", details={"queryCount": 3})

    assert _analysis_fact_retry_usage(error) == 3
    assert _analysis_fact_retry_usage(None) == 0


def test_visualization_usage_prefers_fresher_details_for_call_counts():
    error = ReportingError(
        "report_visualization_tool_budget_exhausted",
        "x",
        details={"totalToolCalls": 9, "scriptFailureCount": 2},
    )
    attach_retry_usage(
        error,
        CheckpointRetryUsage(
            visualizationReadUnitsUsed=5,
            visualizationFactQueriesUsed=1,
            visualizationToolCalls=7,
            visualizationScriptFailures=0,
            visualizationAttemptSuccessfulToolCalls=6,
            visualizationAttemptRejectedToolCalls=1,
        ),
    )

    assert _visualization_retry_usage(error) == {
        "visualizationReadUnitsUsed": 5,
        "visualizationFactQueriesUsed": 1,
        "visualizationToolCalls": 9,
        "visualizationScriptFailures": 2,
    }
    restored = _checkpoint_retry_usage(error, work_kind="visualization_section")
    assert restored.visualization_tool_calls == 9
    assert restored.visualization_attempt_successful_tool_calls == 6
    assert restored.visualization_attempt_rejected_tool_calls == 1
