from copy import copy

import pytest

from smart_reporting.reporting.code_agent.failure_policy import failure_kind, recovery_for
from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import _function


@pytest.mark.parametrize("task", ["analysis", "visualization"])
def test_explicit_recovery_overrides_legacy_retryable(task):
    error = ReportingError("new_provider_error", "failed", details={
        "retryable": False, "recovery": "retry_then_degrade",
    })
    assert recovery_for(error, task) == "retry_then_degrade"
    assert recovery_for(ReportingError("unknown", "failed", details={"retryable": False}), task) == "fatal"
    assert recovery_for(ReportingError("report_code_generation_no_submission", "failed",
                                      details={"retryable": False}), task) == "retry_then_degrade"


@pytest.mark.parametrize("task", ["analysis", "visualization"])
def test_identity_failure_cannot_be_downgraded(task):
    error = ReportingError("report_phase_artifact_changed", "changed",
                           details={"recovery": "retry_then_degrade"})
    assert recovery_for(error, task) == "fatal"


@pytest.mark.parametrize("task", ["analysis", "visualization"])
def test_tool_protocol_mismatch_stops_without_retry(task):
    error = ReportingError("report_code_custom_tool_protocol_error", "type mismatch")
    assert recovery_for(error, task) == "fatal"


@pytest.mark.parametrize("task", ["analysis", "visualization"])
def test_missing_workspace_capability_is_fatal(task):
    error = ReportingError(
        "report_workspace_capability_missing",
        "适配缺少能力",
        details={"capability": "inspect_plotly_file", "retryable": True},
    )
    assert recovery_for(error, task) == "fatal"


def test_task_specific_recovery_and_thinking_share_policy():
    error = ReportingError("execution_output_error", "failed")
    assert recovery_for(error, "analysis") == "retry"
    assert recovery_for(error, "visualization") == "retry_then_degrade"
    assert failure_kind({"code": error.code}) == "python_execution_failure"
    assert failure_kind({"code": "report_code_exit_receipt_invalid"}) == "python_execution_failure"


def test_budget_shared_by_model_copy_but_reset_for_new_task():
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    tools = [_function("run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    sibling = copy(model)
    model._consume_code_request()
    sibling._consume_code_request()
    assert model.code_run_request_count() == sibling.code_run_request_count() == 2
    with pytest.raises(ReportingError) as caught:
        model._consume_code_request()
    assert caught.value.details["recovery"] == "retry_then_degrade"
    model.configure_code_run(tools, max_model_requests=2)
    assert model.code_run_request_count() == 0
    assert sibling.code_run_request_count() == 2
