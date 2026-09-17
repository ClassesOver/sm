from __future__ import annotations

import asyncio
import json

import pytest
from agno.models.message import Message
from agno.tools.function import Function, FunctionCall
from loguru import logger

from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.code_agent.toolkit import _stop_after_success
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.tests.test_reporting_interactive_code_agent import (
    SOURCE,
    _batch_response,
    _custom_response,
    _function_response,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("outcome", ["success", "rejected", "exception", "submitted", "limit"])
async def test_batch_preserves_order_stopping_and_total_budget(asynchronous, outcome):
    executed = []

    def first():
        executed.append("first")
        if outcome == "exception":
            raise ValueError("invalid draft")
        return {"ok": outcome != "rejected"}

    def second():
        assert executed == ["first"]
        executed.append("second")
        return {"ok": True}

    def third():
        assert executed == ["first", "second"]
        executed.append("third")
        return {"ok": True}

    async def first_async():
        # 让出执行权，证明后续工具会等待第一个完成。
        await asyncio.sleep(0)
        return first()

    async def second_async():
        return second()

    async def third_async():
        return third()

    entrypoints = (first_async, second_async, third_async) if asynchronous else (first, second, third)
    functions = [
        Function(
            name=f"step_{index}", entrypoint=entrypoint,
            post_hook=_stop_after_success if index == 0 and outcome == "submitted" else None,
        )
        for index, entrypoint in enumerate(entrypoints)
    ]
    for function in functions:
        function.process_entrypoint()
    calls = [
        FunctionCall(function=function, call_id=f"call-{index}", arguments={})
        for index, function in enumerate(functions)
    ]
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    results: list[Message] = []
    kwargs = {
        "function_calls": calls,
        "function_call_results": results,
        "current_function_call_count": 1,
        "function_call_limit": 2 if outcome == "limit" else 4,
    }
    if asynchronous:
        events = [event async for event in model.arun_function_calls(**kwargs)]
    else:
        events = list(model.run_function_calls(**kwargs))

    assert events
    assert executed == (["first", "second", "third"] if outcome == "success" else ["first"])
    assert [result.tool_call_id for result in results] == ["call-0", "call-1", "call-2"]
    if outcome == "success":
        assert all(not result.tool_call_error for result in results)
    else:
        skipped_from = 2 if outcome == "limit" else 1
        for result in results[skipped_from:]:
            assert result.tool_call_error is True
            assert json.loads(result.content)["status"] == "skipped"
        if outcome == "submitted":
            assert results[0].stop_after_tool_call is True
        if outcome == "limit":
            assert results[1].tool_call_error is True
            assert "Tool call limit reached" in results[1].content


def test_entire_batch_is_validated_before_tools_can_execute():
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    response = _batch_response(
        _custom_response("write_script", SOURCE, 1),
        _function_response(2, "outside", {}),
    )

    with pytest.raises(ReportingError, match="未声明或类型不匹配"):
        model._parse_provider_response(response)


@pytest.mark.anyio
async def test_async_tool_execution_emits_safe_progress_and_path() -> None:
    async def write_script() -> dict[str, object]:
        return {
            "ok": True,
            "path": "evidence/analysis_001/supplement.py",
            "content": "不得输出的源码",
        }

    function = Function(name="write_script", entrypoint=write_script)
    function.process_entrypoint()
    call = FunctionCall(function=function, call_id="call-1", arguments={})
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    results: list[Message] = []
    records: list[dict[str, object]] = []
    sink_id = logger.add(
        lambda message: records.append(dict(message.record["extra"])),
        filter=lambda record: record["extra"].get("reporting_progress") == "code_tool",
    )
    try:
        _ = [
            event
            async for event in model.arun_function_calls(
                function_calls=[call],
                function_call_results=results,
                current_function_call_count=0,
                function_call_limit=2,
            )
        ]
    finally:
        logger.remove(sink_id)

    assert [
        {
            "reporting_progress": item["reporting_progress"],
            "tool_name": item["tool_name"],
            "status": item["status"],
            **({"path": item["path"]} if "path" in item else {}),
        }
        for item in records
    ] == [
        {
            "reporting_progress": "code_tool",
            "tool_name": "write_script",
            "status": "started",
        },
        {
            "reporting_progress": "code_tool",
            "tool_name": "write_script",
            "status": "completed",
            "path": "evidence/analysis_001/supplement.py",
        },
    ]
    assert "不得输出" not in json.dumps(records, ensure_ascii=False)


@pytest.mark.anyio
async def test_last_three_tool_slots_are_reserved_for_formal_delivery() -> None:
    executed: list[str] = []

    def tool(name: str) -> Function:
        def entrypoint(**_kwargs):
            executed.append(name)
            return {"ok": True}

        return Function(
            name=name,
            entrypoint=entrypoint,
        )

    functions = {
        name: tool(name)
        for name in ("run_snippet", "write_script", "run_script", "submit_script")
    }
    for function in functions.values():
        function.process_entrypoint()
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    model.configure_code_run(tuple(functions.values()), max_model_requests=4)
    rejected_results: list[Message] = []

    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(
                    function=functions["run_snippet"],
                    call_id="probe",
                    arguments={"code": "1 + 1"},
                )
            ],
            function_call_results=rejected_results,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]

    assert executed == []
    assert json.loads(rejected_results[0].content)["code"] == (
        "report_code_delivery_budget_reserved"
    )
    assert model._limit_charge_for(rejected_results, None) == 0

    delivery_results: list[Message] = []
    _ = [
        event
        async for event in model.arun_function_calls(
            function_calls=[
                FunctionCall(function=functions[name], call_id=name, arguments={})
                for name in ("write_script", "run_script", "submit_script")
            ],
            function_call_results=delivery_results,
            current_function_call_count=17,
            function_call_limit=20,
        )
    ]

    assert executed == ["write_script", "run_script", "submit_script"]
