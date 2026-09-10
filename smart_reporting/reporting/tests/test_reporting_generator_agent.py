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

from smart_reporting.reporting.agent import (
    ReportingCodeOpenAIResponses,
    ReportingPhaseOpenAIChat,
    create_reporting_code_agent,
    create_reporting_generator_agent,
)
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


def test_reporting_code_responses_requires_the_only_custom_source_tool() -> None:
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

    assert params["tool_choice"] == {
        "type": "custom",
        "name": "submit_python_source",
    }


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

    assert source_params["tool_choice"] == {
        "type": "custom",
        "name": "submit_python_source",
    }
    assert no_tool_params["tool_choice"] == "auto"
    assert explicit_none_params["tool_choice"] == "none"


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
