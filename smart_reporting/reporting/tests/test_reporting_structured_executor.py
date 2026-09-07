import json
from unittest.mock import AsyncMock, Mock

import pytest
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from loguru import logger
from pydantic import BaseModel, field_validator

from smart_reporting.reporting.agent import ReportingPhaseOpenAIChat
from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.structured_output import (
    ReportingStructuredOutputExecutor,
    StructuredOutputCallBudget,
)
from smart_reporting.reporting.structured_output.execution import (
    _agent_for_mode,
    _correction_instruction,
)
from smart_reporting.reporting.structured_output.policy import (
    REPORTING_STRUCTURED_MODES_MODEL_ATTR,
    StructuredOutputMode,
    VerifiedModelCapabilityResolver,
)
from smart_reporting.reporting.structured_output.wire_schema import (
    StructuredOutputWireSchemaResolver,
)
from smart_reporting.reporting.workflow.execution import ReportingTaskInvocation
from smart_reporting.reporting.workflow.runtime.phase_models import (
    SectionBlockContent,
    SectionPlanOutput,
    VisualizationScriptDraft,
)
from smart_reporting.task_execution import TaskExecutionScope


@pytest.mark.anyio
async def test_structured_executor_calls_arun_once_without_continuation() -> None:
    draft = Mock()
    draft.output_schema = VisualizationScriptDraft
    draft.arun = AsyncMock(return_value=Mock(content=VisualizationScriptDraft.model_construct()))
    executor = ReportingStructuredOutputExecutor(draft, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")

    result = await executor.run(
        "instruction", scope=scope, run_context=RunContext(run_id="r", session_id="s")
    )

    assert isinstance(result, VisualizationScriptDraft)
    draft.arun.assert_awaited_once()
    draft.acontinue_run = AsyncMock()
    draft.acontinue_run.assert_not_awaited()


@pytest.mark.anyio
async def test_structured_executor_implements_task_coordinator_protocol() -> None:
    agent = Mock()
    agent.output_schema = None
    agent.arun = AsyncMock(return_value=Mock(content={"status": "candidate"}))
    executor = ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")
    result = await executor(
        ReportingTaskInvocation(
            instruction="instruction",
            run_context=RunContext(run_id="r", session_id="s"),
            continuing=False,
            scope=scope,
            parent_run_id="",
            model_metrics_settlement=Mock(),
        )
    )
    assert result == {"status": "candidate"}
    agent.arun.assert_awaited_once()


@pytest.mark.anyio
async def test_structured_executor_extracts_complete_json_object_from_model_preamble() -> None:
    payload = {
        "scriptPath": "charts/revenue.py",
        "pythonSource": 'print(json.dumps({"charts": []}))\n',
        "charts": [
            {
                "chartId": "chart_revenue",
                "sourcePath": "charts/revenue.png",
                "title": "收入趋势",
                "altText": "2025 年收入趋势",
                "citationIds": ["citation_001"],
                "metricCodes": ["revenue"],
                "currentPeriod": "2025",
                "comparisonType": "none",
                "sourceDatasetId": "dataset_001",
                "aggregationGrain": "month",
                "comparability": "strict",
            }
        ],
        "warnings": [],
    }
    agent = Mock()
    agent.output_schema = VisualizationScriptDraft
    agent.arun = AsyncMock(
        return_value=Mock(
            content=(
                "以下是结果：\n```json\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
                "\n```\n请按 JSON 使用。"
            )
        )
    )
    executor = ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")

    result = await executor.run(
        "instruction", scope=scope, run_context=RunContext(run_id="r", session_id="s")
    )

    assert isinstance(result, VisualizationScriptDraft)
    assert result.charts[0].chart_id == "chart_revenue"


@pytest.mark.anyio
async def test_structured_executor_does_not_merge_partial_json_objects() -> None:
    agent = Mock()
    agent.output_schema = VisualizationScriptDraft
    agent.arun = AsyncMock(
        return_value=Mock(
            content=(
                '{"scriptPath":"charts/revenue.py","pythonSource":"print(1)"}\n'
                '{"charts":[],"warnings":[]}'
            )
        )
    )
    executor = ReportingStructuredOutputExecutor(agent, idle_timeout_seconds=5)
    scope = TaskExecutionScope("task-1", "user-1", "thread-1", "sandbox-1", "generator")

    with pytest.raises(ReportingError) as caught:
        await executor.run(
            "instruction", scope=scope, run_context=RunContext(run_id="r", session_id="s")
        )

    assert caught.value.code == "report_phase_output_invalid"


def test_structured_correction_includes_small_candidate_once() -> None:
    candidate = {"scriptPath": "charts/revenue.py", "charts": []}

    messages = _correction_instruction(
        "original instruction",
        correction_number=1,
        previous_output=candidate,
        issues=[{"path": "$.charts", "type": "too_short", "message": "至少一个图表"}],
    )

    serialized = "".join(str(message.content) for message in messages)
    assert len(messages) == 2
    assert serialized.count('"scriptPath":"charts/revenue.py"') == 1
    assert messages[0].content == "original instruction"


def test_structured_correction_omits_oversized_invalid_candidate() -> None:
    candidate = '{"blocks":[{"markdown":"' + ("重复内容" * 20_000)

    messages = _correction_instruction(
        "original instruction",
        correction_number=1,
        previous_output=candidate,
        issues=[
            {
                "path": "$",
                "type": "json_invalid",
                "message": "Unterminated string at line 1 column 25",
            }
        ],
    )

    serialized = "".join(str(message.content) for message in messages)
    assert len(messages) == 2
    assert candidate not in serialized
    assert "previousOutputOmitted" in serialized
    assert "json_invalid" in serialized
    assert messages[0].content == "original instruction"


class _RequiredValue(BaseModel):
    value: int


class _BusinessValue(BaseModel):
    value: int

    @field_validator("value")
    @classmethod
    def validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be positive")
        return value


class _HttpStatusError(RuntimeError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def _schema_agent(schema: type[BaseModel] = _RequiredValue) -> Agent:
    model = OpenAIChat(id="schema-test", strict_output=False)
    setattr(
        model,
        REPORTING_STRUCTURED_MODES_MODEL_ATTR,
        {"standard": StructuredOutputMode.JSON_SCHEMA.value},
    )
    return Agent(model=model, output_schema=schema, retries=0)


def test_qwen_structured_mode_follows_dashscope_supported_model_matrix() -> None:
    resolver = VerifiedModelCapabilityResolver()

    unsupported = resolver.resolve(
        "qwen3.6-flash",
        configured_mode=StructuredOutputMode.JSON_SCHEMA,
        endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    supported = resolver.resolve(
        "qwen3.8-flash",
        configured_mode=StructuredOutputMode.JSON_SCHEMA,
        endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    custom_endpoint = resolver.resolve(
        "qwen3.6-flash",
        configured_mode=StructuredOutputMode.JSON_SCHEMA,
        endpoint="http://model-gateway.internal/v1",
    )

    assert unsupported.primary is StructuredOutputMode.JSON_OBJECT
    assert unsupported.fallback is None
    assert unsupported.source == "provider_model_capability"
    assert supported.primary is StructuredOutputMode.JSON_SCHEMA
    assert custom_endpoint.primary is StructuredOutputMode.JSON_SCHEMA


def test_structured_request_preserves_output_token_budget() -> None:
    model = ReportingPhaseOpenAIChat(
        id="qwen3.8-flash",
        api_key="test-key",
        max_tokens=8192,
    )
    agent = Agent(model=model, output_schema=_RequiredValue, retries=0)
    wire_contract = StructuredOutputWireSchemaResolver().resolve(
        _RequiredValue,
        model_id=model.id,
        endpoint=model.base_url,
    )

    execution_agent = _agent_for_mode(
        agent,
        _RequiredValue,
        StructuredOutputMode.JSON_SCHEMA,
        wire_contract,
    )
    request_model = execution_agent.model._phase_request_model([])

    assert request_model.max_tokens == 8192


def test_qwen_wire_decoder_removes_non_selected_union_transport_fields() -> None:
    contract = StructuredOutputWireSchemaResolver().resolve(
        SectionPlanOutput,
        model_id="qwen3.8-flash",
        endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    )
    candidate = {
        "kind": "render",
        "sectionCode": "overview",
        "blocks": [
            {
                "blockId": "block-1",
                "objective": "说明收入趋势。",
                "claimIds": ["claim-1"],
            }
        ],
        "claims": [
            {
                "claimId": "claim-1",
                "metricCode": "revenue",
                "managementQuestionRef": "analysis_001",
                "value": "收入保持增长。",
                "citationIds": ["citation-1"],
                "chartIds": ["chart-1"],
                "comparisonType": "none",
                "comparisonPeriod": None,
                "entityGrain": None,
            }
        ],
        # 根联合扁平后，这些字段是 strict wire schema 的必填传输字段，
        # 但不属于 kind=render 的领域分支。
        "analysisIds": ["analysis_001"],
        "reason": "证据充足。",
        "missingEvidence": ["none"],
    }

    decoded = contract.decode(candidate)
    decoded_with_unknown = contract.decode({**candidate, "unexpected": "rejected"})

    assert set(decoded) == {"kind", "sectionCode", "blocks", "claims"}
    assert SectionPlanOutput.model_validate(decoded).root.kind == "render"
    assert decoded_with_unknown["unexpected"] == "rejected"
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        SectionPlanOutput.model_validate(decoded_with_unknown)


@pytest.mark.anyio
async def test_schema_transport_rejection_falls_back_with_original_instruction() -> None:
    executor = ReportingStructuredOutputExecutor(_schema_agent(), idle_timeout_seconds=5)
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            RuntimeError("invalid response_format: json_schema is not supported"),
            (executor.agent, Mock(content={"value": 7})),
        ]
    )

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-1",
        user_id="user-1",
    )

    calls = executor._execute_mode.await_args_list
    assert [call.args[0] for call in calls] == [
        StructuredOutputMode.JSON_SCHEMA,
        StructuredOutputMode.JSON_OBJECT,
    ]
    assert calls[1].args[2] == "original instruction"
    assert result.content.value == 7


@pytest.mark.anyio
async def test_schema_transport_rejection_does_not_consume_business_corrections() -> None:
    executor = ReportingStructuredOutputExecutor(_schema_agent(), idle_timeout_seconds=5)
    invalid_outputs = [(executor.agent, Mock(content={"wrong": attempt})) for attempt in range(5)]
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            RuntimeError("response_format json_schema is unsupported"),
            *invalid_outputs,
            (executor.agent, Mock(content={"value": 9})),
        ]
    )

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-2",
        user_id="user-1",
    )

    assert executor._execute_mode.await_count == 7
    assert [call.args[0] for call in executor._execute_mode.await_args_list] == [
        StructuredOutputMode.JSON_SCHEMA,
        *([StructuredOutputMode.JSON_OBJECT] * 6),
    ]
    assert result.content.value == 9


@pytest.mark.anyio
async def test_first_schema_structure_error_downgrades_and_is_remembered() -> None:
    executor = ReportingStructuredOutputExecutor(_schema_agent(), idle_timeout_seconds=5)
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            (executor.agent, Mock(content={})),
            (executor.agent, Mock(content={"value": 11})),
        ]
    )

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-3",
        user_id="user-1",
    )

    assert [call.args[0] for call in executor._execute_mode.await_args_list] == [
        StructuredOutputMode.JSON_SCHEMA,
        StructuredOutputMode.JSON_OBJECT,
    ]
    assert result.content.value == 11

    repeated = ReportingStructuredOutputExecutor(executor.agent, idle_timeout_seconds=5)
    repeated._execute_mode = AsyncMock(  # type: ignore[method-assign]
        return_value=(repeated.agent, Mock(content={"value": 12}))
    )

    repeated_result = await repeated.execute(
        "next business correction",
        routing_context=None,
        session_id="session-3-repeated",
        user_id="user-1",
    )

    repeated._execute_mode.assert_awaited_once()
    assert repeated._execute_mode.await_args.args[0] is StructuredOutputMode.JSON_OBJECT
    assert repeated_result.content.value == 12


@pytest.mark.anyio
async def test_shared_call_budget_caps_nested_business_attempts() -> None:
    executor = ReportingStructuredOutputExecutor(_schema_agent(), idle_timeout_seconds=5)
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            (executor.agent, Mock(content={})),
            (executor.agent, Mock(content={"wrong": 1})),
            (executor.agent, Mock(content={"value": 21})),
        ]
    )
    budget = StructuredOutputCallBudget(max_model_calls=2)

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-budget-1",
        user_id="user-1",
        call_budget=budget,
    )

    assert result.content.value == 21
    assert budget.model_calls == 2
    assert executor._execute_mode.await_count == 3

    repeated = ReportingStructuredOutputExecutor(executor.agent, idle_timeout_seconds=5)
    repeated._execute_mode = AsyncMock(  # type: ignore[method-assign]
        return_value=(repeated.agent, Mock(content={"value": 22}))
    )

    with pytest.raises(ReportingError, match="业务调用已达到上限"):
        await repeated.execute(
            "outer correction",
            routing_context=None,
            session_id="session-budget-2",
            user_id="user-1",
            call_budget=budget,
        )

    repeated._execute_mode.assert_not_awaited()


@pytest.mark.anyio
async def test_schema_named_auth_error_does_not_trigger_protocol_fallback() -> None:
    executor = ReportingStructuredOutputExecutor(_schema_agent(), idle_timeout_seconds=5)
    rejected = _HttpStatusError(
        "invalid credentials for json_schema request",
        status_code=401,
    )
    executor._execute_mode = AsyncMock(side_effect=rejected)  # type: ignore[method-assign]

    with pytest.raises(_HttpStatusError) as caught:
        await executor.execute(
            "original instruction",
            routing_context=None,
            session_id="session-4",
            user_id="user-1",
        )

    assert caught.value is rejected
    executor._execute_mode.assert_awaited_once()


@pytest.mark.anyio
async def test_business_validation_error_stays_in_schema_mode() -> None:
    executor = ReportingStructuredOutputExecutor(
        _schema_agent(_BusinessValue), idle_timeout_seconds=5
    )
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            (executor.agent, Mock(content={"value": -1})),
            (executor.agent, Mock(content={"value": 13})),
        ]
    )

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-5",
        user_id="user-1",
    )

    assert [call.args[0] for call in executor._execute_mode.await_args_list] == [
        StructuredOutputMode.JSON_SCHEMA,
        StructuredOutputMode.JSON_SCHEMA,
    ]
    assert result.content.value == 13


@pytest.mark.anyio
async def test_protocol_residual_cleanup_does_not_consume_business_correction() -> None:
    executor = ReportingStructuredOutputExecutor(
        _schema_agent(SectionBlockContent), idle_timeout_seconds=5
    )
    raw_markdown = "### 收入趋势\n\n收入保持增长。<!-- repair-warning:" + ("x" * 9_000) + "-->"
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        return_value=(executor.agent, Mock(content={"markdown": raw_markdown}))
    )
    budget = StructuredOutputCallBudget()

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-protocol-cleanup",
        user_id="user-1",
        call_budget=budget,
    )

    assert result.content.markdown == "### 收入趋势\n\n收入保持增长。"
    assert executor._execute_mode.await_count == 1
    assert budget.model_calls == 1


@pytest.mark.anyio
async def test_section_semantic_error_still_consumes_business_correction() -> None:
    executor = ReportingStructuredOutputExecutor(
        _schema_agent(SectionBlockContent), idle_timeout_seconds=5
    )
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            (executor.agent, Mock(content={"markdown": "## 非法章节标题\n\n正文"})),
            (executor.agent, Mock(content={"markdown": "### 合法小节标题\n\n正文"})),
        ]
    )
    budget = StructuredOutputCallBudget()

    result = await executor.execute(
        "original instruction",
        routing_context=None,
        session_id="session-semantic-correction",
        user_id="user-1",
        call_budget=budget,
    )

    assert result.content.markdown == "### 合法小节标题\n\n正文"
    assert executor._execute_mode.await_count == 2
    assert budget.model_calls == 2


@pytest.mark.anyio
async def test_schema_fallback_log_contains_stable_failure_fields() -> None:
    executor = ReportingStructuredOutputExecutor(_schema_agent(), idle_timeout_seconds=5)
    executor._execute_mode = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            _HttpStatusError(
                "invalid response_format: json_schema is unsupported",
                status_code=400,
            ),
            (executor.agent, Mock(content={"value": 17})),
        ]
    )
    records = []
    sink_id = logger.add(lambda message: records.append(message.record))
    try:
        await executor.execute(
            "original instruction",
            routing_context=None,
            session_id="session-6",
            user_id="user-1",
        )
    finally:
        logger.remove(sink_id)

    fallback = next(
        record
        for record in records
        if record["message"] == "report_structured_output_mode_downgraded"
    )
    assert fallback["extra"]["schema_name"] == "_RequiredValue"
    assert fallback["extra"]["failure_kind"] == "transport"
    assert fallback["extra"]["fallback_reason"] == "schema_transport_error"
    assert fallback["extra"]["protocol_attempt_number"] == 1
    assert fallback["extra"]["business_call_number"] == 0
