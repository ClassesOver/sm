"""原始 reasoning item 必须随完整工具轮次回放，不能由摘要重建。"""

import json

import pytest
from agno.models.message import Message
from openai.types.responses import Response

from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses


@pytest.mark.parametrize("name,kind", [("run", "custom_tool_call"), ("read_script", "function_call")])
def test_reasoning_survives_tool_projection_and_wire(name, kind):
    raw = {"id": "rs-1", "type": "reasoning", "summary": [
        {"type": "summary_text", "text": "检查后再继续"}], "encrypted_content": ""}
    call = {"id": "fc-1", "call_id": "call-1", "name": name, "type": kind}
    call.update({"input": "17 * 23"} if kind == "custom_tool_call" else {"arguments": "{}"})
    response = Response.model_validate({
        "id": "resp-1", "created_at": 0, "model": "test", "object": "response",
        "status": "completed", "output": [raw, call], "parallel_tool_calls": False,
        "tool_choice": "auto", "tools": [],
    })
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._code_declared_tools = {name: "custom" if kind == "custom_tool_call" else "function"}
    parsed = model._parse_provider_response(response)
    assert parsed.provider_data["reasoning_output"] == raw
    messages = [Message(role="user", content="完成任务")]
    for _ in range(12):
        messages.extend([Message(role="assistant", content="exploration " * 400),
                         Message(role="user", content="continue")])
    messages.extend([
        Message(role="assistant", tool_calls=parsed.tool_calls, provider_data=parsed.provider_data),
        Message(role="tool", tool_call_id="call-1", tool_name=name, content="391"),
    ])
    model._task_execution_input_token_budget = 1800
    model.count_tokens = lambda messages, *args, **kwargs: sum(len(str(m.content)) // 4 + 1 for m in messages)
    projected = model._project(messages, (), {})
    assert len(projected) < len(messages)
    wire = [x if isinstance(x, dict) else x.model_dump(exclude_none=True)
            for x in model._format_messages(projected)]
    reasoning = [x for x in wire if x.get("type") == "reasoning"]
    assert reasoning == [raw]
    pos = wire.index(raw)
    assert wire[pos + 1]["type"] == kind
    assert wire[pos + 2]["call_id"] == wire[pos + 1]["call_id"]
    if kind == "custom_tool_call":
        assert wire[pos + 1]["call_id"] == "call-1"
    assert parsed.provider_data["reasoning_output"] == raw


@pytest.mark.parametrize("model_id,host,enabled", [
    ("deepseek-v4-flash-0731", "token-plan.cn-beijing.maas.aliyuncs.com", True),
    ("qwen3.8-flash", "token-plan.cn-beijing.maas.aliyuncs.com", True),
    ("deepseek-v4-flash-0731", "localhost:8000", False),
    ("unprobed-model", "token-plan.cn-beijing.maas.aliyuncs.com", False),
])
def test_automatic_reasoning_replay_only_for_probed_routes(model_id, host, enabled):
    model = ReportingCodeOpenAIResponses(id=model_id, api_key="test", base_url=f"https://{host}/api/v2")
    request_model = model._phase_request_model([])
    assert (request_model.store is False) is enabled
    assert ("reasoning.encrypted_content" in (request_model.include or [])) is enabled
    assert request_model.max_output_tokens is None
    assert request_model.get_request_params().get("max_output_tokens") is None
    assert model.store is None
    assert model.include is None


def test_no_reasoning_final_message_does_not_fabricate_item():
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    wire = model._format_messages([Message(role="assistant", content="391")])
    assert json.dumps(wire) == '[{"role": "assistant", "content": "391"}]'


def test_unprobed_route_preserves_explicit_summary_setting():
    model = ReportingCodeOpenAIResponses(
        id="unprobed", api_key="test", base_url="http://localhost:8000/v1",
        extra_body={"enable_thinking": True, "thinking_budget": 1024},
        reasoning_effort="high",
        reasoning={"effort": "high", "summary": "detailed"},
    )
    request_model = model._phase_request_model([])
    assert request_model.get_request_params()["reasoning"]["summary"] == "detailed"
    assert "thinking_budget" not in (request_model.get_request_params().get("extra_body") or {})
