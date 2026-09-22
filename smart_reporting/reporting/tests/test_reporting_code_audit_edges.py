import json
from ast import literal_eval

import pytest
from agno.models.message import Message
from agno.tools.function import Function, FunctionCall

from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.runtime.visualization_section_workflow import (
    _repair_diagnostic,
)


@pytest.mark.anyio
async def test_escalated_batch_receipts_share_updated_budget_and_available_tools():
    functions = [Function(name=name, entrypoint=lambda: {"ok": True})
                 for name in ("run", "run_script", "submit_script")]
    for function in functions:
        function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test", api_key="test")
    model.configure_code_run(functions, max_model_requests=4, delivery_reserve=3)
    for attempt in range(2):
        results = []
        _ = [event async for event in model.arun_function_calls(
            function_calls=[FunctionCall(function=function, call_id=f"{attempt}-{i}", arguments={})
                            for i, function in enumerate(functions)],
            function_call_results=results, current_function_call_count=17, function_call_limit=20,
        )]
        payloads = [json.loads(result.content) for result in results]
        assert payloads[0]["details"]["requiredNextTools"] == ["run_script", "submit_script"]
        assert "view_image" not in payloads[0]["message"]
        assert [payload["budget"]["used"] for payload in payloads] == [17 + attempt] * 3
        assert model._limit_charge_for(results, None) == attempt


@pytest.mark.parametrize("encode,decode", [(json.dumps, json.loads), (repr, literal_eval)])
def test_budget_attachment_preserves_format_and_byte_limit(encode, decode):
    payload = {"ok": True, "data": None}
    message = Message(role="tool", content=encode(payload))
    ReportingCodeOpenAIResponses._attach_tool_budget([message], used=2, limit=20)
    assert decode(message.content) == {**payload, "budget": {"used": 2, "limit": 20, "remaining": 18}}
    # 16 KiB wire ceiling: the payload fits before adding the budget envelope.
    large = Message(role="tool", content=encode({"data": "中" * 5450}))
    original = large.content
    ReportingCodeOpenAIResponses._attach_tool_budget([large], used=2, limit=20)
    assert large.content == original


def test_budget_attachment_tolerates_deep_json():
    message = Message(role="tool", content="[" * 2000 + "0" + "]" * 2000)
    original = message.content
    ReportingCodeOpenAIResponses._attach_tool_budget([message], used=2, limit=20)
    assert message.content == original


def test_repair_diagnostic_marks_each_truncated_stream():
    error = ReportingError("report_code_mode_execution_failed", "failed", details={
        field: "中" * 3000 for field in ("traceback", "stderr", "stdout")
    })
    details = _repair_diagnostic(None, error, "analysis/chart.py")["details"]
    for field in ("traceback", "stderr", "stdout"):
        assert details[field + "Truncated"] is True
        assert len(details[field]) < 3000


def test_budget_attachment_preserves_unencodable_json():
    message = Message(role="tool", content='{"text":"\\ud800"}')
    original = message.content
    ReportingCodeOpenAIResponses._attach_tool_budget([message], used=2, limit=20)
    assert message.content == original


def test_repair_diagnostics_keep_upstream_truncation_flags():
    from smart_reporting.reporting.workflow.runtime.code_generation import (
        ReportingCodeGenerationRunner,
    )

    details = {}
    for field in ("traceback", "stderr", "stdout"):
        details[field] = "short tail already truncated upstream"
        details[field + "Truncated"] = True
    error = ReportingError("report_code_mode_execution_failed", "failed", details=details)
    visual = _repair_diagnostic(None, error, "analysis/chart.py")
    short = ReportingCodeGenerationRunner._short_diagnostic(visual)
    for result in (visual, short):
        for field in ("traceback", "stderr", "stdout"):
            assert result["details"][field + "Truncated"] is True
