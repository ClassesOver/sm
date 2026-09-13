import asyncio
import json

import pytest
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.message import Message
from agno.models.openai import OpenAIChat, OpenAIResponses
from agno.models.response import ModelResponse
from agno.reasoning.deepseek import aget_deepseek_reasoning
from agno.reasoning.manager import ReasoningConfig, ReasoningManager
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput
from agno.tools.function import Function
from loguru import logger
from openai.types.responses import (
    Response,
    ResponseCustomToolCall,
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from smart_reporting.reporting.agent import (
    ReportingCodeOpenAIResponses,
    ReportingPhaseOpenAIChat,
    create_reporting_code_agent,
    create_reporting_generator_agent,
)
from smart_reporting.reporting.bootstrap import _VISUALIZATION_CODE_INSTRUCTIONS
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.phase import (
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_TASK_DEPENDENCY,
    bind_reporting_run_context,
)
from smart_reporting.reporting.workflow.runtime.analysis_item_workflow import (
    AnalysisEvidenceDecision,
)
from smart_reporting.reporting.workflow.runtime.phase_models import (
    SectionDecisionOutput,
    VisualizationPlanDraft,
)


def test_reporting_generator_agent_is_structured_and_has_no_tools() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=VisualizationPlanDraft,
        name="reporting-visualization-generator",
    )
    assert agent.output_schema is VisualizationPlanDraft
    assert agent.structured_outputs is True
    assert agent.use_json_mode is False
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.markdown is False
    assert agent.instructions == [
        "只返回一个严格满足 output_schema 的 JSON 对象，不得返回推理、解释、Markdown 或代码围栏。",
        "所有必填顶层字段必须各出现一次；不得把 schema 顶层字段只写入其他字段。",
        "长文本字段必须是合法 JSON 字符串，换行和引号必须按 JSON 转义。",
        "每个 charts[].sourcePath 必须是 visualizationWorkspace.chartOutputRoot 下带 "
        ".png、.jpg 或 .jpeg 后缀的具体文件。",
        "每个 charts[].sourceDatasetId 必须逐字复制 allowedDatasetIds 中的一个值，不得使用"
        "数据集名称、文件名或自行生成的标识。",
    ]


def test_visualization_generator_does_not_carry_python_source_contract() -> None:
    agent = create_reporting_generator_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        output_schema=VisualizationPlanDraft,
        name="reporting-visualization-generator",
    )

    instructions = "\n".join(agent.instructions)
    assert "pythonSource" not in instructions
    assert "Matplotlib" not in instructions


def test_reporting_section_generator_uses_agno_supported_root_model() -> None:
    model = OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost")
    agent = create_reporting_generator_agent(
        model=model,
        output_schema=SectionDecisionOutput,
        name="reporting-section-generator",
    )

    assert agent.output_schema is SectionDecisionOutput
    schema = SectionDecisionOutput.model_json_schema()
    assert schema["discriminator"]["propertyName"] == "kind"
    assert any(
        "根 JSON" in instruction and "kind" in instruction for instruction in agent.instructions
    )


def test_reporting_evidence_generator_has_no_tools_or_source_contract() -> None:
    agent = create_reporting_generator_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        output_schema=AnalysisEvidenceDecision,
        name="reporting-analysis-evidence-generator",
    )

    assert agent.tools == []
    instructions = "\n".join(agent.instructions)
    assert "script" not in instructions
    assert "pythonSource" not in instructions


def test_reporting_code_agent_is_unstructured_and_has_no_history_or_tools() -> None:
    agent = create_reporting_code_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
        role="签发分析脚本",
        instructions=["只修改签发路径。"],
    )

    assert agent.output_schema is None
    assert agent.parse_response is False
    assert agent.structured_outputs is False
    assert agent.use_json_mode is False
    assert agent.tools == []
    assert agent.retries == 0
    assert agent.add_history_to_context is False
    prompt = "\n".join(agent.instructions)
    assert "普通文本、Markdown、代码围栏和解释都不算成功" in prompt
    assert "完整原始 Python 源码" in prompt
    assert "read_file" not in prompt
    assert "readReceipt" in prompt
    assert "outputContract" in prompt
    assert "根节点" in prompt
    assert "additionalRootKeys=false" in prompt
    assert "columnTypes" in prompt
    assert "jsonShape" in prompt
    assert "sourceProtocol.authorizedPaths" in prompt
    assert "字符串常量" in prompt
    assert "__file__" in prompt
    assert "os.path" in prompt
    assert "pathlib" in prompt


def test_visualization_code_instructions_defend_structured_rows_without_masking_errors() -> None:
    instructions = "\n".join(_VISUALIZATION_CODE_INSTRUCTIONS)

    assert "rowEncoding=columns_rows" in instructions
    assert "dict(zip(columns, row))" in instructions
    assert 'row["字段名"]' in instructions
    assert ".get(..., 0)" in instructions
    assert "真实数据全零" in instructions
    assert "明确标注" in instructions
    assert "解析失败" in instructions
    assert "不同 metricIndex" in instructions
    assert "独立子图" in instructions
    assert "NaN" in instructions
    assert "禁止跨指标" in instructions


def test_reporting_code_agent_uses_chat_reasoning_and_non_thinking_responses() -> None:
    model = OpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test-key",
        base_url="http://localhost",
        extra_body={"enable_thinking": True, "thinking_budget": 2048},
        reasoning_effort="high",
    )

    agent = create_reporting_code_agent(model=model, name="reporting-code-agent")

    assert isinstance(agent.model, ReportingCodeOpenAIResponses)
    request_model = agent.model._phase_request_model([Message(role="user", content="test")])
    assert request_model.extra_body == {"enable_thinking": False}
    assert request_model.reasoning_effort is None
    assert isinstance(agent.reasoning_model, DeepSeek)
    assert agent.reasoning_model.id == "deepseek-v4-flash-0731"
    assert agent.reasoning_agent is not None
    assert isinstance(agent.reasoning_agent.model, OpenAIChat)
    assert agent.reasoning_agent.model.extra_body == {
        "enable_thinking": True,
        "thinking_budget": 2048,
    }


def test_reporting_code_responses_uses_auto_choice_for_custom_source_tool() -> None:
    model = ReportingCodeOpenAIResponses(
        id="test-model",
        api_key="test-key",
        base_url="http://localhost",
    )

    params = model.get_request_params(
        messages=[Message(role="user", content="write source")],
        tools=[
            Function(
                name="submit_python_source",
                description="submit source",
                parameters={
                    "type": "object",
                    "properties": {"source": {"type": "string"}},
                    "required": ["source"],
                },
            )
        ],
        tool_choice={"type": "function", "function": {"name": "submit_python_source"}},
    )

    assert params["tool_choice"] == "auto"


def test_reporting_code_responses_does_not_reuse_custom_choice_without_source_tool() -> None:
    model = ReportingCodeOpenAIResponses(
        id="test-model",
        api_key="test-key",
        base_url="http://localhost",
    )
    source_tool = Function(
        name="submit_python_source",
        parameters={"type": "object", "properties": {}},
    )

    source_params = model.get_request_params(
        messages=[Message(role="user", content="write source")],
        tools=[source_tool],
    )
    no_tool_params = model.get_request_params(
        messages=[Message(role="user", content="finish")],
        tools=None,
        tool_choice=None,
    )
    explicit_none_params = model.get_request_params(
        messages=[Message(role="user", content="finish")],
        tools=None,
        tool_choice="none",
    )

    assert source_params["tool_choice"] == "auto"
    assert no_tool_params["tool_choice"] == "auto"
    assert explicit_none_params["tool_choice"] == "none"


def _custom_source_response(output: list) -> Response:
    return Response(
        id="resp_test",
        created_at=0,
        model="test-model",
        object="response",
        output=output,
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
    )


def _custom_source_call() -> ResponseCustomToolCall:
    return ResponseCustomToolCall(
        id="fc_1",
        call_id="call_1",
        name="submit_python_source",
        input="value = 1\nprint(value)\n",
        type="custom_tool_call",
    )


def _text_message(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="msg_1",
        role="assistant",
        status="completed",
        type="message",
        content=[ResponseOutputText(text=text, annotations=[], type="output_text")],
    )


def _source_function() -> Function:
    return Function(
        name="submit_python_source",
        description="submit source",
        parameters={
            "type": "object",
            "properties": {"source": {"type": "string"}},
            "required": ["source"],
        },
    )


def _code_model() -> ReportingCodeOpenAIResponses:
    return ReportingCodeOpenAIResponses(
        id="test-model",
        api_key="test-key",
        base_url="http://localhost",
    )


def _arm_custom_source_tool(model: ReportingCodeOpenAIResponses) -> None:
    """通过真实请求路径激活 custom 源码工具，替代直接篡改模型内部状态。"""

    model.get_request_params(
        messages=[Message(role="user", content="write source")],
        tools=[_source_function()],
    )


def test_reporting_code_responses_accepts_text_preamble_before_custom_call() -> None:
    model = _code_model()
    _arm_custom_source_tool(model)
    response = _custom_source_response(
        [
            _text_message("I'll create the Python source code for the charts"),
            _custom_source_call(),
        ]
    )

    parsed = model._parse_provider_response(response)

    assert parsed.tool_calls is not None
    assert len(parsed.tool_calls) == 1
    call = parsed.tool_calls[0]
    assert call["function"]["name"] == "submit_python_source"
    assert json.loads(call["function"]["arguments"]) == {"source": "value = 1\nprint(value)\n"}
    assert call["id"] == "fc_1"
    assert call["call_id"] == "call_1"
    assert parsed.content is None
    assert parsed.extra is not None
    assert parsed.extra["tool_call_ids"] == ["call_1"]


def test_reporting_code_responses_rejects_text_only_custom_response() -> None:
    model = _code_model()
    _arm_custom_source_tool(model)
    response = _custom_source_response([_text_message("这是解释文本。")])

    with pytest.raises(ReportingError) as error:
        model._parse_provider_response(response)

    assert error.value.code == "report_code_source_tool_response_invalid"
    assert "必须只包含一次工具调用" in error.value.message
    assert error.value.details == {"outputItemTypes": ["message"]}


def test_reporting_code_responses_rejects_function_call_output_item() -> None:
    model = _code_model()
    _arm_custom_source_tool(model)
    response = _custom_source_response(
        [
            ResponseFunctionToolCall(
                id="fc_2",
                call_id="call_2",
                name="submit_python_source",
                arguments='{"source": "value = 1\\n"}',
                type="function_call",
            )
        ]
    )

    with pytest.raises(ReportingError) as error:
        model._parse_provider_response(response)

    assert error.value.code == "report_code_source_tool_response_invalid"
    assert "其他工具或未知输出项" in error.value.message
    assert error.value.details == {"outputItemTypes": ["function_call"]}


def test_reporting_code_responses_custom_mode_is_request_scoped() -> None:
    """custom 工具校验必须由本次请求的 tools 推导，不能依赖跨请求残留状态。"""

    model = _code_model()
    _arm_custom_source_tool(model)
    unarmed_params = model.get_request_params(
        messages=[Message(role="user", content="finish")],
        tools=None,
        tool_choice=None,
    )

    assert unarmed_params["tool_choice"] == "auto"
    with pytest.raises(ReportingError) as error:
        model._parse_provider_response(_custom_source_response([_custom_source_call()]))

    assert error.value.code == "report_code_source_tool_response_invalid"
    assert "当前阶段收到未知 custom 工具调用" in error.value.message


def test_reporting_code_responses_consumes_custom_mode_after_parsing() -> None:
    model = _code_model()
    response = _custom_source_response([_custom_source_call()])
    _arm_custom_source_tool(model)

    parsed = model._parse_provider_response(response)

    assert parsed.tool_calls is not None
    with pytest.raises(ReportingError) as error:
        model._parse_provider_response(response)

    assert error.value.code == "report_code_source_tool_response_invalid"
    assert "当前阶段收到未知 custom 工具调用" in error.value.message


def test_reporting_code_responses_consumes_custom_mode_after_parse_error() -> None:
    model = _code_model()
    _arm_custom_source_tool(model)

    with pytest.raises(ReportingError):
        model._parse_provider_response(_custom_source_response([_text_message("这是解释文本。")]))

    with pytest.raises(ReportingError) as error:
        model._parse_provider_response(_custom_source_response([_custom_source_call()]))

    assert error.value.code == "report_code_source_tool_response_invalid"
    assert "当前阶段收到未知 custom 工具调用" in error.value.message


@pytest.mark.anyio
async def test_reporting_code_responses_custom_mode_isolated_between_tasks() -> None:
    model = _code_model()
    armed = asyncio.Event()
    unarmed = asyncio.Event()

    async def parse_armed_request() -> ModelResponse:
        _arm_custom_source_tool(model)
        armed.set()
        await unarmed.wait()
        return model._parse_provider_response(_custom_source_response([_custom_source_call()]))

    async def reject_unarmed_request() -> ReportingError:
        await armed.wait()
        model.get_request_params(
            messages=[Message(role="user", content="finish")],
            tools=None,
            tool_choice=None,
        )
        unarmed.set()
        with pytest.raises(ReportingError) as error:
            model._parse_provider_response(_custom_source_response([_custom_source_call()]))
        return error.value

    parsed, error = await asyncio.gather(parse_armed_request(), reject_unarmed_request())

    assert parsed.tool_calls is not None
    assert error.code == "report_code_source_tool_response_invalid"
    assert "当前阶段收到未知 custom 工具调用" in error.message


def test_reporting_code_responses_rejects_streaming_when_custom_tool_active() -> None:
    model = _code_model()
    messages = [Message(role="user", content="write source")]
    assistant = Message(role="assistant", content="")

    with pytest.raises(ReportingError) as error:
        model.invoke_stream(messages, assistant, None, [_source_function()])

    assert error.value.code == "report_code_streaming_unsupported"

    with pytest.raises(ReportingError) as error:
        model.ainvoke_stream(messages, assistant, None, [_source_function()])

    assert error.value.code == "report_code_streaming_unsupported"


def test_reporting_code_responses_streaming_without_custom_tool_not_rejected() -> None:
    model = _code_model()
    messages = [Message(role="user", content="write source")]
    assistant = Message(role="assistant", content="")

    stream = model.invoke_stream(messages, assistant, None, None)
    assert iter(stream) is stream

    async_stream = model.ainvoke_stream(messages, assistant, None, None)
    assert hasattr(async_stream, "__aiter__")


# 字段形状来自 2026-09-11 DashScope Responses 真实捕获（deepseek-v4-flash-0731，
# temperature=0 请求）；usage 因 SDK 对 cache_write_tokens 的强校验差异不参与重放。
# 前导文本为真实捕获内容；text_only / function_call 为同形状的反例构造。
_DASHSCOPE_CODE_RESPONSE_OUTPUT = {
    "custom_call_only": [
        {
            "call_id": "call_577ce3aa68314dd684a940e1",
            "input": "value = 1\nprint(value)\n",
            "name": "submit_python_source",
            "type": "custom_tool_call",
            "id": "msg_ca516b65-87be-403d-8a5d-607c8ec589fc",
        }
    ],
    "message_preamble_then_custom_call": [
        {
            "id": "msg_9f0d5aa8-6c0a-4f65-a5d9-4c5a38b6e001",
            "role": "assistant",
            "status": "completed",
            "type": "message",
            "content": [
                {
                    "annotations": [],
                    "text": "I'll create the Python source code for generating "
                    "the three charts based on the visualization plan",
                    "type": "output_text",
                }
            ],
        },
        {
            "call_id": "call_7c1e02d4-19ab-4c8f-b2e6-83a4f90d3117",
            "input": "value = 1\nprint(value)\n",
            "name": "submit_python_source",
            "type": "custom_tool_call",
            "id": "msg_4b8c27af-90d1-4e3a-8f7b-2c6d95e10a22",
        },
    ],
    "text_only": [
        {
            "id": "msg_2e7a91cc-5b34-4d20-9a8f-1d3c60f7b445",
            "role": "assistant",
            "status": "completed",
            "type": "message",
            "content": [
                {
                    "annotations": [],
                    "text": "我将直接给出源码：\n```python\nvalue = 1\nprint(value)\n```",
                    "type": "output_text",
                }
            ],
        }
    ],
    "function_call_fallback": [
        {
            "id": "fc_3d9c1a52-8e47-4b6a-9c2d-5f1e80b7a633",
            "call_id": "call_a1b2c3d4-1111-2222-3333-444455556666",
            "name": "submit_python_source",
            "arguments": '{"source": "value = 1\\nprint(value)\\n"}',
            "type": "function_call",
        }
    ],
}


def _dashscope_response(output: list) -> Response:
    return Response.model_validate(
        {
            "id": "resp_22791810-60a9-42ea-9dfa-c566e4e9fc32",
            "created_at": 1789093577,
            "model": "deepseek-v4-flash-0731",
            "object": "response",
            "status": "completed",
            "incomplete_details": None,
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": [
                {
                    "name": "submit_python_source",
                    "type": "custom",
                    "description": "提交完整原始 Python 源码。",
                    "format": {"type": "text"},
                }
            ],
        }
    )


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("custom_call_only", "parsed"),
        ("message_preamble_then_custom_call", "parsed"),
        ("text_only", "rejected"),
        ("function_call_fallback", "rejected"),
    ],
)
def test_reporting_code_responses_replays_dashscope_response_shapes(
    fixture_name: str,
    expected: str,
) -> None:
    model = _code_model()
    _arm_custom_source_tool(model)
    response = _dashscope_response(_DASHSCOPE_CODE_RESPONSE_OUTPUT[fixture_name])

    if expected == "parsed":
        parsed = model._parse_provider_response(response)
        assert parsed.tool_calls is not None
        assert len(parsed.tool_calls) == 1
        call = parsed.tool_calls[0]
        assert call["function"]["name"] == "submit_python_source"
        assert json.loads(call["function"]["arguments"]) == {"source": "value = 1\nprint(value)\n"}
        assert parsed.content is None
    else:
        with pytest.raises(ReportingError) as error:
            model._parse_provider_response(response)
        assert error.value.code == "report_code_source_tool_response_invalid"
        assert isinstance(error.value.details, dict)
        assert "outputItemTypes" in error.value.details


def test_reporting_code_model_defaults_to_deterministic_temperature() -> None:
    default_agent = create_reporting_code_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
    )
    configured_agent = create_reporting_code_agent(
        model=OpenAIChat(
            id="test-model",
            api_key="test-key",
            base_url="http://localhost",
            temperature=0.7,
        ),
        name="reporting-code-agent",
    )

    assert default_agent.model.temperature == 0.0
    assert configured_agent.model.temperature == 0.7


def test_reporting_code_agent_forbids_text_before_tool_call() -> None:
    agent = create_reporting_code_agent(
        model=OpenAIChat(id="test-model", api_key="test-key", base_url="http://localhost"),
        name="reporting-code-agent",
    )

    instructions = "\n".join(agent.instructions)
    assert "调用 submit_python_source 之前不要输出任何文本" in instructions


@pytest.mark.parametrize(
    ("model_id", "reasoning_effort"),
    [("qwen3.8-flash", "xhigh"), ("custom-reasoning-model", "high")],
)
def test_reporting_code_agent_enables_configured_non_deepseek_reasoning_model(
    model_id: str,
    reasoning_effort: str,
) -> None:
    model = OpenAIChat(
        id=model_id,
        api_key="test-key",
        base_url="http://localhost",
        extra_body={"enable_thinking": True, "thinking_budget": 2048},
        reasoning_effort=reasoning_effort,
    )

    agent = create_reporting_code_agent(model=model, name="reporting-code-agent")

    assert isinstance(agent.reasoning_model, DeepSeek)
    assert agent.reasoning_agent is not None
    assert agent.reasoning_agent.model is model
    assert ReasoningManager(
        ReasoningConfig(reasoning_model=agent.reasoning_model)
    ).is_native_reasoning_model()


def _code_agent_with_reasoning() -> Agent:
    model = ReportingPhaseOpenAIChat(
        id="deepseek-v4-flash-0731",
        api_key="test-key",
        base_url="http://localhost",
        extra_body={"enable_thinking": True, "thinking_budget": 2048},
        reasoning_effort="high",
    )
    return create_reporting_code_agent(model=model, name="reporting-code-agent")


@pytest.mark.anyio
async def test_reporting_code_reasoning_error_status_logs_and_soft_degrades(monkeypatch) -> None:
    agent = _code_agent_with_reasoning()
    assert agent.reasoning_agent is not None
    assert agent.reasoning_model is not None
    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")

    async def failed_run(_self, *_args, **_kwargs):
        return RunOutput(
            status=RunStatus.error,
            messages=[Message(role="assistant", reasoning_content="provider secret")],
        )

    monkeypatch.setattr(Agent, "arun", failed_run)
    try:
        result = await aget_deepseek_reasoning(
            agent.reasoning_agent,
            [Message(role="user", content="write source")],
        )
    finally:
        logger.remove(sink_id)

    assert result is None
    assert len(messages) == 1
    assert "report_code_reasoning_completed" in messages[0]
    assert "model_id=deepseek-v4-flash-0731" in messages[0]
    assert "duration_ms=" in messages[0]
    assert "status=degraded" in messages[0]
    assert "degraded=true" in messages[0]
    assert "error_type=run_status_error" in messages[0]
    assert "provider secret" not in messages[0]


@pytest.mark.anyio
async def test_reporting_code_empty_reasoning_logs_and_soft_degrades(monkeypatch) -> None:
    agent = _code_agent_with_reasoning()
    assert agent.reasoning_agent is not None
    assert agent.reasoning_model is not None
    messages = []
    sink_id = logger.add(messages.append, level="WARNING", format="{message}")

    async def empty_run(_self, *_args, **_kwargs):
        return RunOutput(
            status=RunStatus.completed,
            messages=[Message(role="assistant", reasoning_content="")],
        )

    monkeypatch.setattr(Agent, "arun", empty_run)
    try:
        result = await aget_deepseek_reasoning(
            agent.reasoning_agent,
            [Message(role="user", content="write source")],
        )
    finally:
        logger.remove(sink_id)

    assert result is None
    assert len(messages) == 1
    assert "status=degraded" in messages[0]
    assert "degraded=true" in messages[0]
    assert "error_type=missing_reasoning_content" in messages[0]


@pytest.mark.anyio
async def test_reporting_code_valid_reasoning_logs_completed(monkeypatch) -> None:
    agent = _code_agent_with_reasoning()
    assert agent.reasoning_agent is not None
    assert agent.reasoning_model is not None
    messages = []
    sink_id = logger.add(messages.append, level="INFO", format="{message}")

    async def completed_run(_self, *_args, **_kwargs):
        return RunOutput(
            status=RunStatus.completed,
            messages=[Message(role="assistant", reasoning_content="reasoned plan")],
        )

    monkeypatch.setattr(Agent, "arun", completed_run)
    try:
        result = await aget_deepseek_reasoning(
            agent.reasoning_agent,
            [Message(role="user", content="write source")],
        )
    finally:
        logger.remove(sink_id)

    assert result is not None
    assert result.reasoning_content == "reasoned plan"
    started = [message for message in messages if "report_code_reasoning_started" in message]
    assert len(started) == 1
    assert "model_id=deepseek-v4-flash-0731" in started[0]
    assert "duration_ms=0" in started[0]
    assert "status=started" in started[0]
    assert "degraded=false" in started[0]
    assert "error_type=-" in started[0]
    completed = [message for message in messages if "report_code_reasoning_completed" in message]
    assert len(completed) == 1
    assert "status=completed" in completed[0]
    assert "degraded=false" in completed[0]
    assert "error_type=-" in completed[0]


@pytest.mark.anyio
async def test_reporting_code_reasoning_log_uses_runtime_routed_model_id(monkeypatch) -> None:
    agent = _code_agent_with_reasoning()
    assert agent.reasoning_agent is not None
    messages = []
    sink_id = logger.add(messages.append, level="INFO", format="{message}")
    context = RunContext(
        run_id="run-1",
        session_id="session-1",
        dependencies={
            REPORTING_TASK_DEPENDENCY: {
                REPORTING_MODEL_TIER_DEPENDENCY_KEY: "fast",
                REPORTING_MODEL_ID_DEPENDENCY_KEY: "qwen3.8-flash-routed",
            }
        },
    )

    async def completed_run(_self, *_args, **_kwargs):
        return RunOutput(
            status=RunStatus.completed,
            messages=[Message(role="assistant", reasoning_content="reasoned plan")],
        )

    monkeypatch.setattr(Agent, "arun", completed_run)
    try:
        with bind_reporting_run_context(context):
            await agent.reasoning_agent.arun("write source")
    finally:
        logger.remove(sink_id)

    assert any("model_id=qwen3.8-flash-routed" in message for message in messages)
    assert all("model_id=deepseek-v4-flash-0731" not in message for message in messages)


@pytest.mark.anyio
async def test_reporting_code_responses_logs_output_model_duration(monkeypatch) -> None:
    model = ReportingCodeOpenAIResponses(
        id="output-model",
        api_key="test-key",
        base_url="http://localhost",
    )
    messages = []
    sink_id = logger.add(messages.append, level="INFO", format="{message}")

    async def respond(_self, *_args, **_kwargs):
        return ModelResponse(content="done")

    monkeypatch.setattr(OpenAIResponses, "aresponse", respond)
    try:
        response = await model.aresponse([Message(role="user", content="write source")])
    finally:
        logger.remove(sink_id)

    assert response.content == "done"
    started = [message for message in messages if "report_code_response_started" in message]
    assert len(started) == 1
    assert "model_id=output-model" in started[0]
    assert "duration_ms=0" in started[0]
    assert "status=started" in started[0]
    assert "degraded=false" in started[0]
    assert "error_type=-" in started[0]
    completed = [message for message in messages if "report_code_response_completed" in message]
    assert len(completed) == 1
    assert "model_id=output-model" in completed[0]
    assert "duration_ms=" in completed[0]
    assert "status=completed" in completed[0]
    assert "degraded=false" in completed[0]
    assert "error_type=-" in completed[0]
