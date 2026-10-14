"""原始 reasoning item 必须随完整工具轮次回放，不能由摘要重建。"""

import json

import pytest
from agno.models.message import Message
from openai.types.responses import Response

from smart_reporting.reporting.code_agent.protocol import ReportingCodeOpenAIResponses


@pytest.mark.parametrize(
    "name,kind", [("run", "custom_tool_call"), ("read_script", "function_call")]
)
def test_reasoning_survives_tool_projection_and_wire(name, kind):
    raw = {
        "id": "rs-1",
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "检查后再继续"}],
        "encrypted_content": "",
    }
    call = {"id": "fc-1", "call_id": "call-1", "name": name, "type": kind}
    call.update({"input": "17 * 23"} if kind == "custom_tool_call" else {"arguments": "{}"})
    response = Response.model_validate(
        {
            "id": "resp-1",
            "created_at": 0,
            "model": "test",
            "object": "response",
            "status": "completed",
            "output": [raw, call],
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._code_declared_tools = {name: "custom" if kind == "custom_tool_call" else "function"}
    parsed = model._parse_provider_response(response)
    assert parsed.provider_data["reasoning_output"] == raw
    messages = [Message(role="user", content="完成任务")]
    for _ in range(12):
        messages.extend(
            [
                Message(role="assistant", content="exploration " * 400),
                Message(role="user", content="continue"),
            ]
        )
    messages.extend(
        [
            Message(
                role="assistant", tool_calls=parsed.tool_calls, provider_data=parsed.provider_data
            ),
            Message(role="tool", tool_call_id="call-1", tool_name=name, content="391"),
        ]
    )
    model._task_execution_input_token_budget = 1800
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(m.content)) // 4 + 1 for m in messages
    )
    projected = model._project(messages, (), {})
    assert len(projected) < len(messages)
    wire = [
        x if isinstance(x, dict) else x.model_dump(exclude_none=True)
        for x in model._format_messages(projected)
    ]
    reasoning = [x for x in wire if x.get("type") == "reasoning"]
    assert reasoning == [raw]
    pos = wire.index(raw)
    assert wire[pos + 1]["type"] == kind
    assert wire[pos + 2]["call_id"] == wire[pos + 1]["call_id"]
    if kind == "custom_tool_call":
        assert wire[pos + 1]["call_id"] == "call-1"
    assert parsed.provider_data["reasoning_output"] == raw


def _custom_call(call_id: str, name: str, raw_input: str) -> dict:
    argument = {"write_script": "source", "run": "code", "edit_script": "patch"}[name]
    return {
        "id": f"item-{call_id}",
        "call_id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps({argument: raw_input}, separators=(",", ":")),
        },
        "provider_data": {
            "reporting_wire_type": "custom",
            "raw_input": raw_input,
        },
    }


def _custom_history_messages(result_factory):
    messages = [Message(role="user", content="完成任务")]
    for index, (call_id, name, raw_input) in enumerate(
        [
            ("call-1", "write_script", "# Python\nprint('first')\n"),
            ("call-2", "run", "# Python\nprint('second')\n"),
            ("call-3", "run", "# Python\nprint('third')\n"),
        ]
    ):
        messages.extend(
            [
                Message(role="assistant", tool_calls=[_custom_call(call_id, name, raw_input)]),
                Message(
                    role="tool",
                    tool_name=name,
                    tool_call_id=call_id,
                    content=json.dumps(result_factory(index), ensure_ascii=False),
                ),
            ]
        )
    return messages


def _wire(model, projected):
    return [
        item if isinstance(item, dict) else item.model_dump(exclude_none=True)
        for item in model._format_messages(projected)
    ]


def test_custom_history_below_gate_keeps_full_freeform_wire():
    messages = _custom_history_messages(lambda index: {"ok": True, "index": index})
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._task_execution_input_token_budget = 50_000
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    projected = model._project(messages, (), {})
    wire = _wire(model, projected)

    custom_inputs = [item["input"] for item in wire if item.get("type") == "custom_tool_call"]
    assert custom_inputs == [
        "# Python\nprint('first')\n",
        "# Python\nprint('second')\n",
        "# Python\nprint('third')\n",
    ]
    assert [item["call_id"] for item in wire if item.get("type") == "custom_tool_call"] == [
        "call-1",
        "call-2",
        "call-3",
    ]


def test_custom_history_compaction_preserves_freeform_wire_identities():
    messages = _custom_history_messages(lambda index: {"ok": True, "stdout": "y" * 24_000})
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._task_execution_input_token_budget = 10_000
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    projected = model._project(messages, (), {})
    wire = _wire(model, projected)

    custom_calls = [item for item in wire if item.get("type") == "custom_tool_call"]
    assert [item["call_id"] for item in custom_calls] == ["call-1", "call-2", "call-3"]
    assert [item["id"] for item in custom_calls] == ["item-call-1", "item-call-2", "item-call-3"]
    summaries = [json.loads(custom_calls[0]["input"]), json.loads(custom_calls[1]["input"])]
    assert [summary["marker"] for summary in summaries] == [
        "CODING_CUSTOM_HISTORY_SUMMARY",
        "CODING_CUSTOM_HISTORY_SUMMARY",
    ]
    assert [summary["callId"] for summary in summaries] == ["call-1", "call-2"]
    assert [summary["tool"] for summary in summaries] == ["write_script", "run"]
    assert [summary["status"] for summary in summaries] == ["completed", "completed"]
    assert summaries[0]["nextTools"] == ["run"]
    assert "print('first')" not in custom_calls[0]["input"]
    assert custom_calls[2]["input"] == "# Python\nprint('third')\n"
    outputs = [item for item in wire if item.get("type") == "custom_tool_call_output"]
    assert [item["call_id"] for item in outputs] == ["call-1", "call-2", "call-3"]
    receipts = [json.loads(outputs[0]["output"]), json.loads(outputs[1]["output"])]
    assert [receipt["marker"] for receipt in receipts] == [
        "CODING_CUSTOM_HISTORY_RESULT",
        "CODING_CUSTOM_HISTORY_RESULT",
    ]
    assert "stdout" not in receipts[0]
    assert json.loads(outputs[2]["output"])["ok"] is True


@pytest.mark.parametrize("read_sha,keep_read", [("current", True), ("stale", False)])
def test_rebase_preserves_current_read_and_unresolved_failure_identity(read_sha, keep_read):
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._code_delivery_state_reader = lambda: {
        "script": {"sha256": "current"},
        "lastFailure": {"callId": "failed-call", "tool": "run_script", "code": "failed"},
    }
    model._task_execution_input_token_budget = 2000
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(m.content)) // 4 + 1 for m in messages
    )
    messages = [Message(role="user", content="task")]
    for call_id, name, result in [
        (
            "read-call",
            "read_script",
            {"ok": True, "exists": True, "sha256": read_sha, "source": "x = 1"},
        ),
        ("failed-call", "run_script", {"ok": False, "code": "failed"}),
    ]:
        messages.extend(
            [
                Message(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "item-" + call_id,
                            "call_id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": "{}"},
                        }
                    ],
                ),
                Message(
                    role="tool", tool_name=name, tool_call_id=call_id, content=json.dumps(result)
                ),
            ]
        )
    messages.extend(
        [
            Message(role="assistant", content="old exploration " * 1000),
            Message(role="assistant", content="recent"),
        ]
    )
    projected = model._project(messages, (), {})
    call_ids = {call["call_id"] for message in projected for call in message.tool_calls or ()}
    assert "failed-call" in call_ids
    assert ("read-call" in call_ids) is keep_read


@pytest.mark.parametrize(
    "model_id,host,enabled",
    [
        ("deepseek-v4-flash-0731", "token-plan.cn-beijing.maas.aliyuncs.com", True),
        ("qwen3.8-flash", "token-plan.cn-beijing.maas.aliyuncs.com", True),
        ("deepseek-v4-flash-0731", "localhost:8000", False),
        ("unprobed-model", "token-plan.cn-beijing.maas.aliyuncs.com", False),
    ],
)
def test_automatic_reasoning_replay_only_for_probed_routes(model_id, host, enabled):
    model = ReportingCodeOpenAIResponses(
        id=model_id, api_key="test", base_url=f"https://{host}/api/v2"
    )
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
        id="unprobed",
        api_key="test",
        base_url="http://localhost:8000/v1",
        extra_body={"enable_thinking": True, "thinking_budget": 1024},
        reasoning_effort="high",
        reasoning={"effort": "high", "summary": "detailed"},
    )
    request_model = model._phase_request_model([])
    assert request_model.get_request_params()["reasoning"]["summary"] == "detailed"
    assert "thinking_budget" not in (request_model.get_request_params().get("extra_body") or {})


def test_projection_metrics_snapshot_reports_compaction_and_consumed_once():
    messages = _custom_history_messages(lambda index: {"ok": True, "stdout": "y" * 24_000})
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._task_execution_input_token_budget = 10_000
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    model._project(messages, (), {})
    snapshot = model._pop_code_projection_metrics()
    assert snapshot["compaction_triggered"] is True
    assert snapshot["compacted_calls"] == 2
    assert snapshot["metadata_bytes"] > 0
    assert snapshot["truncated_calls"] == 0
    assert snapshot["compaction_tokens_before"] > snapshot["compaction_tokens_after"] > 0
    assert snapshot["projected_estimated_tokens"] > 0
    assert snapshot["window_rebased"] is False
    assert snapshot["dropped_complete_rounds"] == 0
    assert model._pop_code_projection_metrics() == {}


def test_projection_metrics_snapshot_below_gate_reports_no_compaction():
    messages = _custom_history_messages(lambda index: {"ok": True, "index": index})
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._task_execution_input_token_budget = 50_000
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    model._project(messages, (), {})
    snapshot = model._pop_code_projection_metrics()
    assert snapshot["compaction_triggered"] is False
    assert snapshot["compacted_calls"] == 0
    assert snapshot["compaction_tokens_before"] == 0
    assert snapshot["compaction_tokens_after"] == 0
    assert snapshot["window_rebased"] is False


@pytest.mark.anyio
async def test_projection_metrics_merge_into_request_metric_once(monkeypatch):
    from agno.models.openai import OpenAIResponses
    from agno.models.response import ModelResponse

    async def fake_ainvoke(self, messages, *args, **kwargs):
        return ModelResponse()

    monkeypatch.setattr(OpenAIResponses, "ainvoke", fake_ainvoke)
    messages = _custom_history_messages(lambda index: {"ok": True, "stdout": "y" * 24_000})
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._task_execution_input_token_budget = 10_000
    model._code_request_metrics = []
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    await model.ainvoke(messages)
    metric = model._code_request_metrics[-1]
    assert metric["status"] == "completed"
    assert metric["compaction_triggered"] is True
    assert metric["compacted_calls"] == 2
    assert metric["compaction_tokens_before"] > metric["compaction_tokens_after"] > 0
    assert model._code_last_projection_metrics is None


def test_projection_metrics_snapshot_with_summary_disabled_falls_back_to_rebase():
    messages = _custom_history_messages(lambda index: {"ok": True, "stdout": "y" * 24_000})
    model = ReportingCodeOpenAIResponses(id="test", api_key="test", store=False)
    model._task_execution_input_token_budget = 10_000
    model._code_disable_history_summary = True
    model.count_tokens = lambda messages, *args, **kwargs: sum(
        len(str(message.content)) // 4 + 1 for message in messages
    )
    model._project(messages, (), {})
    snapshot = model._pop_code_projection_metrics()
    assert snapshot["compaction_triggered"] is False
    assert snapshot["compacted_calls"] == 0
    assert snapshot["window_rebased"] is True


@pytest.mark.parametrize('failure', ['missing', 'duplicate', 'wrong-name', 'result-before-call'])
def test_function_replay_rejects_incomplete_or_mismatched_receipts(failure):
    from smart_reporting.reporting.models import ReportingError

    call = {'id': 'item-read', 'call_id': 'call-read', 'type': 'function',
            'function': {'name': 'read_script', 'arguments': '{}'}}
    assistant = Message(role='assistant', tool_calls=[call])
    receipt = Message(role='tool', tool_call_id='call-read', tool_name='read_script', content='ok')
    messages = {
        'missing': [assistant],
        'duplicate': [assistant, receipt, receipt.model_copy()],
        'wrong-name': [assistant, receipt.model_copy(update={'tool_name': 'submit_script'})],
        'result-before-call': [receipt, assistant],
    }[failure]
    model = ReportingCodeOpenAIResponses(id='test', api_key='test', store=False)
    with pytest.raises(ReportingError) as caught:
        model._format_messages(messages)
    assert caught.value.code == 'report_code_custom_tool_protocol_error'
    assert caught.value.details == {'retryable': False}


@pytest.mark.parametrize('tool_name', [None, 'read_script'])
def test_function_replay_retains_one_receipt_with_optional_legacy_name(tool_name):
    call = {'id': 'item-read', 'call_id': 'call-read', 'type': 'function',
            'function': {'name': 'read_script', 'arguments': '{}'}}
    messages = [Message(role='assistant', tool_calls=[call]),
                Message(role='tool', tool_call_id='call-read', tool_name=tool_name, content='ok')]
    model = ReportingCodeOpenAIResponses(id='test', api_key='test', store=False)
    wire = model._format_messages(messages)
    assert [item['type'] for item in wire] == ['function_call', 'function_call_output']
    assert wire[0]['call_id'] == wire[1]['call_id']
    assert wire[1]['output'] == 'ok'


@pytest.mark.parametrize('count', [1, 2])
def test_replay_accepts_legacy_combined_function_receipts(count):
    calls = [{'id': f'call-{index}', 'type': 'function',
              'function': {'name': 'read_script', 'arguments': '{}'}} for index in range(count)]
    messages = [Message(role='assistant', tool_calls=calls),
                Message(role='tool', tool_calls=[{'tool_call_id': call['id'], 'tool_name': 'read_script',
                                                  'content': f'result-{index}'}
                                                 for index, call in enumerate(calls)])]
    original = [message.model_dump() for message in messages]
    model = ReportingCodeOpenAIResponses(id='test', api_key='test', store=False)
    wire = model._format_messages(messages)
    requests = [item for item in wire if item.get('type') == 'function_call']
    results = [item for item in wire if item.get('type') == 'function_call_output']
    assert len(requests) == len(results) == count
    assert [item['call_id'] for item in requests] == [item['call_id'] for item in results]
    assert [item['output'] for item in results] == [f'result-{index}' for index in range(count)]
    assert [message.model_dump() for message in messages] == original


@pytest.mark.parametrize('role', ['user', 'system'])
def test_replay_rejects_tool_calls_attached_to_non_assistant_messages(role):
    from smart_reporting.reporting.models import ReportingError

    call = {'id': 'call-read', 'type': 'function',
            'function': {'name': 'read_script', 'arguments': '{}'}}
    messages = [Message(role=role, content='text', tool_calls=[call]),
                Message(role='tool', tool_call_id='call-read', tool_name='read_script', content='ok')]
    model = ReportingCodeOpenAIResponses(id='test', api_key='test', store=False)
    with pytest.raises(ReportingError) as caught:
        model._format_messages(messages)
    assert caught.value.code == 'report_code_custom_tool_protocol_error'


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('custom', [False, True])
@pytest.mark.parametrize('collision_field', ['id', 'call_id'])
def test_replay_id_normalization_avoids_native_item_id_collision(reverse, custom, collision_field):
    foreign = (_custom_call('foreign', 'run', 'print(1)') if custom else
               {'id': 'foreign-item', 'call_id': 'foreign-call', 'type': 'function',
                'function': {'name': 'read_script', 'arguments': '{}'}})
    native = {'id': 'fc_00000000', 'call_id': 'call_native', 'type': 'function',
              'function': {'name': 'read_script', 'arguments': '{}'}}
    if collision_field == 'call_id':
        native.update(id='fc_native', call_id='call_00000000')
    calls = [foreign, native]
    if reverse:
        calls.reverse()
    reasoning = {'id': 'rs-collision', 'type': 'reasoning', 'summary': []}
    messages = [Message(role='assistant', tool_calls=calls,
                        provider_data={'reasoning_output': reasoning})] + [
        Message(role='tool', tool_call_id=call['call_id'], tool_name=call['function']['name'],
                content='result-' + call['call_id']) for call in calls
    ]
    before = [message.model_dump() for message in messages]
    model = ReportingCodeOpenAIResponses(id='test', api_key='test', store=False)
    wire = [item if isinstance(item, dict) else item.model_dump(exclude_none=True)
            for item in model._format_messages(messages)]
    assert wire[0] == reasoning
    requests = [item for item in wire if item.get('type') in {'function_call', 'custom_tool_call'}]
    results = [item for item in wire if item.get('type') in {'function_call_output', 'custom_tool_call_output'}]
    assert len(requests) == len(results) == 2
    assert len({item['id'] for item in requests}) == len({item['call_id'] for item in requests}) == 2
    assert [item['call_id'] for item in requests] == [item['call_id'] for item in results]
    assert [item['output'] for item in results] == ['result-' + call['call_id'] for call in calls]
    if custom:
        replay = next(item for item in requests if item['type'] == 'custom_tool_call')
        assert replay['input'] == 'print(1)'
        assert replay['id'] == foreign['id'] and replay['call_id'] == foreign['call_id']
    assert [message.model_dump() for message in messages] == before
