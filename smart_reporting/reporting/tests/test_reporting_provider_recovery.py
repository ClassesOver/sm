"""报告失败终态与单请求恢复。"""

import json

import httpx
import pytest
from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.exceptions import ModelProviderError
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunStatus
from openai import APIStatusError, AsyncOpenAI
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall, ChoiceDeltaToolCallFunction
from pydantic import BaseModel

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting.agent import ReportFacadeOpenAIChat, ReportingPhaseOpenAIChat
from smart_reporting.reporting.model_policy import ThinkingPolicyConfig
from smart_reporting.reporting.workflow.controller import ReportWorkflowToolkit
from smart_reporting.reporting.workflow.orchestration import _timed_step_executor
from smart_reporting.reporting.workflow.runtime import ReportWorkflowRuntime


@pytest.fixture
def anyio_backend():
    return "asyncio"


def provider_error(status=502):
    body = {"detail": "model provider unreachable" if status == 502 else "model profile not found"}
    response = httpx.Response(
        status,
        json=body,
        request=httpx.Request("POST", "https://model.invalid/v1/chat/completions"),
    )
    cause = APIStatusError("upstream error", response=response, body=body)
    error = ModelProviderError(
        "Unknown model error", status_code=status, model_id="platform-managed"
    )
    error.__cause__ = cause
    return error


@pytest.mark.anyio
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("returned_failure", [False, True])
async def test_workflow_failure_is_native_error_with_reason(monkeypatch, stream, returned_failure):
    class Controller:
        async def start(self, workflow_input, run_context):
            if returned_failure:
                return {
                    "ok": False,
                    "status": "failed",
                    "error": {
                        "code": "report_model_provider_unavailable",
                        "message": "HTTP 502: model provider unreachable",
                        "stage": "run-coding-analysis",
                        "retryable": True,
                        "statusCode": 502,
                    },
                }

            async def fail():
                raise provider_error()

            return await _timed_step_executor(fail, step_id="run-coding-analysis")()

    async def invoke(self, messages, *args, **kwargs):
        return ModelResponse(
            tool_calls=[
                {
                    "id": "start-1",
                    "type": "function",
                    "function": {"name": "report_workflow_start", "arguments": "{}"},
                }
            ]
        )

    async def invoke_stream(self, messages, *args, **kwargs):
        yield ModelResponse(
            tool_calls=[
                ChoiceDeltaToolCall(
                    index=0,
                    id="start-1",
                    type="function",
                    function=ChoiceDeltaToolCallFunction(
                        name="report_workflow_start", arguments="{}"
                    ),
                )
            ]
        )

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", invoke)
    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke_stream", invoke_stream)
    agent = Agent(
        model=ReportFacadeOpenAIChat(id="test", api_key="test"),
        tools=[ReportWorkflowToolkit(Controller())],
        db=InMemoryDb(),
        telemetry=False,
    )
    if stream:
        events = [e async for e in agent.arun("生成运营报告", session_id="failure", stream=True)]
        assert any(e.event == "RunError" for e in events)
        assert not any(e.event == "RunCompleted" for e in events)
        output = agent.get_last_run_output(session_id="failure")
    else:
        output = await agent.arun("生成运营报告", session_id="failure")
    assert output.status == RunStatus.error
    assert "502" in output.content
    assert "model provider unreachable" in output.content
    assert "run-coding-analysis" in output.content


@pytest.mark.anyio
@pytest.mark.parametrize("status, expected_calls", [(502, 2), (404, 1)])
async def test_planner_retries_only_transient_request(monkeypatch, status, expected_calls):
    class Output(BaseModel):
        ok: bool

    template = Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test"))
    stage = ReportWorkflowRuntime._planning_agent(
        template,
        "test-planner",
        Output,
        thinking_policy=ThinkingPolicyConfig(
            operation="data_understanding", thinking_enabled=False, configured_budget_cap=2048
        ),
    )
    stage.model.delay_between_retries = 0
    calls = []

    async def invoke(self, messages, *args, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            raise provider_error(status)
        return ModelResponse(content="success")

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", invoke)
    messages = [Message(role="user", content="plan")]
    if status == 404:
        with pytest.raises(ModelProviderError):
            await stage.model._ainvoke_with_retry(messages=messages)
    else:
        response = await stage.model._ainvoke_with_retry(messages=messages)
        assert response.content == "success"
    assert len(calls) == expected_calls
    assert all(m == calls[0] for m in calls)


@pytest.mark.anyio
async def test_step_failure_keeps_provider_details():
    from smart_reporting.reporting.models import reporting_failure

    async def fail():
        raise provider_error()

    with pytest.raises(ModelProviderError) as caught:
        await _timed_step_executor(fail, step_id="generate-outline")()
    failure = reporting_failure(caught.value)
    assert failure["statusCode"] == 502
    assert failure["retryable"] is True
    assert failure["stage"] == "generate-outline"
    assert failure["message"] == "model provider unreachable"


@pytest.mark.anyio
async def test_provider_502_retries_without_replaying_completed_tool():
    requests = []
    completed = []

    async def read_frozen_facts() -> str:
        completed.append("analysis_001")
        return "frozen facts, amount=10"

    async def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 2:
            return httpx.Response(502, json={"detail": "model provider unreachable"})
        message = {"role": "assistant", "content": "done"}
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "facts-1",
                        "type": "function",
                        "function": {"name": "read_frozen_facts", "arguments": "{}"},
                    }
                ],
            }
        return httpx.Response(
            200,
            json={
                "id": "response-1",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                    }
                ],
            },
        )

    class Output(BaseModel):
        ok: bool

    stage = ReportWorkflowRuntime._planning_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")),
        "planner",
        Output,
        thinking_policy=ThinkingPolicyConfig(
            operation="data_understanding", thinking_enabled=False, configured_budget_cap=2048
        ),
    )
    model = stage.model
    model.__dict__.pop("_report_response_validator", None)
    model.delay_between_retries = 0
    client = AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    model.async_client = client
    try:
        output = await Agent(
            model=model, tools=[read_frozen_facts], retries=0, telemetry=False
        ).arun("read facts and finish")
    finally:
        await client.close()
    assert output.status == RunStatus.completed
    assert output.content == "done"
    assert completed == ["analysis_001"]
    assert len(requests) == 3
    assert requests[1]["messages"] == requests[2]["messages"]
    assert any(
        m.get("role") == "tool" and "amount=10" in m.get("content", "")
        for m in requests[2]["messages"]
    )


@pytest.mark.anyio
async def test_provider_retry_stops_after_three_attempts(monkeypatch):
    class Output(BaseModel):
        ok: bool

    stage = ReportWorkflowRuntime._planning_agent(
        Agent(model=ReportingPhaseOpenAIChat(id="test", api_key="test")),
        "planner",
        Output,
        thinking_policy=ThinkingPolicyConfig(
            operation="data_understanding", thinking_enabled=False, configured_budget_cap=2048
        ),
    )
    stage.model.delay_between_retries = 0
    attempts = []

    async def fail(self, *args, **kwargs):
        attempts.append(1)
        raise provider_error()

    monkeypatch.setattr(ProjectedOpenAIChat, "ainvoke", fail)
    with pytest.raises(ModelProviderError):
        await stage.model._ainvoke_with_retry(messages=[Message(role="user", content="plan")])
    assert len(attempts) == 3


@pytest.mark.anyio
async def test_controller_keeps_failure_details_in_session_control():
    from smart_reporting.reporting.contract import ReportingWorkflowInput
    from smart_reporting.reporting.tests.test_reporting_workflow_controller import (
        _context,
        _ThreadOwnership,
    )
    from smart_reporting.reporting.workflow.controller import ReportWorkflowController

    class Workflow:
        id = "enterprise-reporting-workflow-v1"

        async def arun(self, *args, **kwargs):
            async def fail():
                raise provider_error(404)

            return await _timed_step_executor(fail, step_id="generate-outline")()

    context = _context()
    controller = ReportWorkflowController(lambda: Workflow(), thread_ownership=_ThreadOwnership())
    with pytest.raises(ModelProviderError):
        await controller.start(ReportingWorkflowInput(prompt="生成报告"), context)
    control = context.session_state["report_workflow_control"]
    assert control["status"] == "failed"
    assert control["error"]["statusCode"] == 404
    assert control["error"]["stage"] == "generate-outline"
    assert control["error"]["retryable"] is False
    assert control["error"]["message"] == "model profile not found"


@pytest.mark.anyio
async def test_failure_details_survive_workflow_output_reload():
    from types import SimpleNamespace

    from agno.run import RunContext

    from smart_reporting.reporting.workflow.controller import ReportWorkflowController

    context = RunContext(run_id="run", session_id="session", metadata={})

    async def fail(run_context):
        raise provider_error()

    with pytest.raises(ModelProviderError):
        await _timed_step_executor(fail, step_id="generate-outline")(context)
    output = SimpleNamespace(
        status=RunStatus.error, content="Unknown model error", metadata=context.metadata
    )
    controller = ReportWorkflowController(lambda: None, thread_ownership=object())
    control = controller._control_from_output(
        output,
        {"external_run_id": "run", "thread_id": "session", "user_id": "user"},
        "workflow-session",
        "workflow-run",
    )
    result = controller._result(control, output)
    assert result["error"]["statusCode"] == 502
    assert result["error"]["stage"] == "generate-outline"
    assert result["error"]["message"] == "model provider unreachable"
