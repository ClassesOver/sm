import asyncio
from types import SimpleNamespace

import pytest
from agno.models.response import ModelResponse

from smart_reporting.context_management import ProjectedOpenAIChat
from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.workflow.orchestration import (
    PlannerRequestRecorder,
    bind_planner_request_recorder,
    reset_planner_request_recorder,
)


def test_planner_request_recorder_persists_provider_usage_and_params() -> None:
    recorder = PlannerRequestRecorder("report-analysis-planner", "qwen3.8-flash")
    recorder.begin()
    recorder.attach_request_params(
        {
            "reasoning_effort": "high",
            "reasoning_summary": "auto",
            "max_tokens": 8192,
            "extra_body": {"enable_thinking": True, "thinking_budget": 4096},
            "messages": ["must not persist"],
        }
    )
    recorder.finish(
        SimpleNamespace(
            id="resp-1",
            response_usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=90,
                reasoning_tokens=60,
                cache_read_tokens=10,
            ),
        )
    )

    request = recorder.requests[0]
    assert request["status"] == "completed"
    assert request["providerRequestId"] == "resp-1"
    assert request["reasoningTokens"] == 60
    assert request["requestParams"] == {
        "reasoning_effort": "high",
        "reasoning_summary": "auto",
        "max_tokens": 8192,
        "extra_body_keys": ["enable_thinking", "thinking_budget"],
        "enable_thinking": True,
        "thinking_budget": 4096,
    }
    assert "messages" not in request["requestParams"]


def test_planner_request_recorder_keeps_started_request_without_response() -> None:
    recorder = PlannerRequestRecorder("report-data-understanding-planner", "model")
    recorder.begin()

    request = recorder.requests[0]
    assert request["status"] == "started"
    assert request["providerRequestId"] == "unknown"
    assert request["durationMs"] == "unknown"
    assert request["reasoningTokens"] == "unknown"


def test_chat_planner_boundary_completes_provider_request(monkeypatch) -> None:
    monkeypatch.setattr(
        ProjectedOpenAIChat,
        "response",
        lambda *_args, **_kwargs: SimpleNamespace(
            content="{}",
            response_usage=SimpleNamespace(
                input_tokens=2,
                output_tokens=3,
                reasoning_tokens=1,
                cache_read_tokens=0,
            ),
            id="chat-resp-1",
        ),
    )
    recorder = PlannerRequestRecorder("report-analysis-planner", "model")
    token = bind_planner_request_recorder(recorder)
    try:
        ReportingPhaseOpenAIChat(id="model", api_key="test").response([])
    finally:
        reset_planner_request_recorder(token)

    assert recorder.requests[0]["status"] == "completed"
    assert recorder.requests[0]["providerRequestId"] == "chat-resp-1"


@pytest.mark.anyio
async def test_chat_cancellation_keeps_live_session_record(monkeypatch) -> None:
    sink = []
    entered = asyncio.Event()

    async def hanging(*_args, **_kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(ProjectedOpenAIChat, "aresponse", hanging)
    recorder = PlannerRequestRecorder("planner", "model", sink=sink)
    token = bind_planner_request_recorder(recorder)
    try:
        task = asyncio.create_task(ReportingPhaseOpenAIChat(id="model").aresponse([]))
        await asyncio.wait_for(entered.wait(), 2)
        assert sink[0]["status"] == "started"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        reset_planner_request_recorder(token)
    assert len(sink) == 1
    assert sink[0]["status"] == "started"
    assert sink[0]["censored"] is True
    assert sink[0]["reasoningTokens"] == "unknown"


def test_chat_native_response_id_is_recorded() -> None:
    recorder = PlannerRequestRecorder("planner", "model")
    recorder.begin()
    recorder.finish(ModelResponse(provider_data={"id": "chat-native-id"}))
    assert recorder.requests[0]["providerRequestId"] == "chat-native-id"
