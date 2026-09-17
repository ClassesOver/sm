from __future__ import annotations

import json

import httpx
import pytest
from agno.models.message import Message
from agno.run import RunContext
from agno.tools.function import Function
from openai import AsyncOpenAI
from openai.types.responses import Response

from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import bind_reporting_run_context


@pytest.mark.anyio
@pytest.mark.parametrize("task_kind", ["analysis_item", "visualization_section"])
async def test_parent_phase_preserves_code_tools_on_sdk_wire(task_kind, monkeypatch):
    requests = []

    async def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={
            "id": "resp-1", "created_at": 0, "model": "test-model",
            "object": "response", "status": "completed", "output": [],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })

    client = AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    client._platform = "Linux"
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test", async_client=client)
    monkeypatch.setattr(model, "count_tokens", lambda *args, **kwargs: 1)
    tools = [Function(name=name, parameters={"type": "object", "properties": {}})
             for name in ("write_script", "run_snippet", "run_script", "submit_script")]
    parent = RunContext(run_id="parent", session_id="session", dependencies={
        "AgentOS 任务执行": {"reportingPhase": "analysis", "reportingTaskKind": task_kind},
    })
    try:
        with bind_reporting_run_context(parent):
            await model.ainvoke([Message(role="user", content="write")], Message(role="assistant"), tools=tools)
    finally:
        await client.close()
    assert {tool["name"]: tool["type"] for tool in requests[0].get("tools", [])} == {
        "write_script": "custom", "run_snippet": "custom",
        "run_script": "function", "submit_script": "function",
    }
    assert requests[0]["tool_choice"] == "auto"


def test_bound_scope_rejects_missing_or_extra_tools():
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name=name) for name in ("write_script", "run_script", "submit_script")]
    model.configure_code_run(tools, max_model_requests=2)
    for changed in ([], tools[:-1], [*tools, Function(name="outside")]):
        with pytest.raises(ReportingError):
            model.get_request_params(messages=[], tools=changed)


def test_bound_scope_allows_read_only_instrumentation_introspection():
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name=name) for name in ("write_script", "run_script")]
    model.configure_code_run(tools, max_model_requests=2)

    introspection = model.get_request_params()

    assert "tools" not in introspection
    with pytest.raises(ReportingError):
        model.get_request_params(messages=[], tools=[])
    actual = model.get_request_params(messages=[], tools=tools)
    assert {tool["name"] for tool in actual["tools"]} == {
        "write_script",
        "run_script",
    }


@pytest.mark.parametrize("name,wire_type", [("outside", "function_call"), ("write_script", "function_call")])
def test_provider_cannot_dispatch_undeclared_or_wrong_type_call(name, wire_type):
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test")
    tools = [Function(name="write_script"), Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    model.get_request_params(messages=[], tools=tools)
    response = Response.model_validate({
        "id": "resp-1", "created_at": 0, "model": "test-model",
        "object": "response", "status": "completed",
        "output": [{"id": "item-1", "call_id": "call-1", "type": wire_type,
                    "name": name, "arguments": "{}"}],
        "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
    })
    with pytest.raises(ReportingError):
        model._parse_provider_response(response)


@pytest.mark.anyio
async def test_request_budget_stops_before_extra_provider_call(monkeypatch):
    requests = []

    async def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp-1", "created_at": 0, "model": "test-model",
            "object": "response", "status": "completed", "output": [],
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
        })

    client = AsyncOpenAI(api_key="test", http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    client._platform = "Linux"
    model = ReportingCodeOpenAIResponses(id="test-model", api_key="test", async_client=client)
    monkeypatch.setattr(model, "count_tokens", lambda *args, **kwargs: 1)
    tools = [Function(name="run_script")]
    model.configure_code_run(tools, max_model_requests=2)
    try:
        for _ in range(2):
            await model.ainvoke([Message(role="user", content="run")], Message(role="assistant"), tools=tools)
        with pytest.raises(ReportingError) as error:
            await model.ainvoke([Message(role="user", content="run")], Message(role="assistant"), tools=tools)
        assert error.value.code == "report_code_model_request_limit"
        assert len(requests) == 2
    finally:
        await client.close()
