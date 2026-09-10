"""Reporting 专属的 Agno 结构化输出执行边界。"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from copy import copy
from dataclasses import dataclass, replace
from hashlib import sha256
from inspect import isawaitable
from typing import Any, Protocol

import anyio
from agno.agent import Agent
from agno.models.message import Message
from agno.run import RunContext
from loguru import logger
from pydantic import BaseModel, TypeAdapter, ValidationError

from ...task_execution import TaskExecutionScope
from ..model_policy import (
    ThinkingFailureKind,
    ThinkingRequest,
    bind_reporting_thinking,
    select_reporting_thinking,
)
from ..models import ReportingError
from ..phase import bind_reporting_run_context, reporting_model_route_from_run_context
from .policy import (
    REPORTING_STRUCTURED_MODES_MODEL_ATTR,
    REPORTING_STRUCTURED_REQUEST_MODEL_ATTR,
    REPORTING_VERIFIED_STRUCTURED_MODES_MODEL_ATTR,
    StructuredOutputMode,
    VerifiedModelCapabilityResolver,
)
from .wire_schema import (
    REPORTING_WIRE_DECODER_MODEL_ATTR,
    REPORTING_WIRE_DIALECT_MODEL_ATTR,
    REPORTING_WIRE_DOMAIN_SCHEMA_MODEL_ATTR,
    REPORTING_WIRE_FINGERPRINT_MODEL_ATTR,
    REPORTING_WIRE_SCHEMA_MODEL_ATTR,
    StructuredOutputWireContract,
    StructuredOutputWireSchemaResolver,
)

_MAX_CORRECTIONS = 5
_MAX_MODEL_CALLS = _MAX_CORRECTIONS + 1
_MAX_CORRECTION_CANDIDATE_BYTES = 32 * 1024


class _TaskInvocation(Protocol):
    instruction: str
    run_context: RunContext
    scope: TaskExecutionScope


@dataclass(frozen=True, slots=True)
class StructuredOutputResult:
    content: Any
    run_output: Any
    mode: StructuredOutputMode
    model_id: str


@dataclass(slots=True)
class StructuredOutputCallBudget:
    """跨结构解析和领域纠错共享的模型业务调用预算。"""

    max_model_calls: int = _MAX_MODEL_CALLS
    model_calls: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.max_model_calls, bool) or self.max_model_calls < 1:
            raise ValueError("max_model_calls 必须是正整数")

    @property
    def exhausted(self) -> bool:
        return self.model_calls >= self.max_model_calls

    def record_model_call(self) -> None:
        self.model_calls += 1


class ReportingStructuredOutputExecutor:
    """使用 Agno 执行结构化 Agent，并协调 Reporting 的有界纠错策略。"""

    def __init__(
        self,
        agent: Agent,
        *,
        idle_timeout_seconds: float = 900,
        capability_resolver: VerifiedModelCapabilityResolver | None = None,
        wire_schema_resolver: StructuredOutputWireSchemaResolver | None = None,
    ) -> None:
        self.agent = agent
        self.idle_timeout_seconds = idle_timeout_seconds
        self.capability_resolver = capability_resolver or VerifiedModelCapabilityResolver()
        self.wire_schema_resolver = wire_schema_resolver or StructuredOutputWireSchemaResolver()

    async def __call__(self, invocation: _TaskInvocation) -> Any:
        return await self.run(
            invocation.instruction,
            scope=invocation.scope,
            run_context=invocation.run_context,
        )

    async def run(
        self,
        instruction: str,
        *,
        scope: TaskExecutionScope,
        run_context: RunContext,
        thinking_request: ThinkingRequest | None = None,
    ) -> Any:
        result = await self.execute(
            instruction,
            routing_context=run_context,
            agent_run_context=run_context,
            session_id=f"task-execution:{scope.external_run_id}:attempt:0",
            user_id=scope.owner_user_id,
            thinking_request=thinking_request,
        )
        return result.content

    async def execute(
        self,
        instruction: str,
        *,
        routing_context: RunContext | None,
        session_id: str,
        user_id: str,
        agent_run_context: RunContext | None = None,
        call_budget: StructuredOutputCallBudget | None = None,
        thinking_request: ThinkingRequest | None = None,
    ) -> StructuredOutputResult:
        schema = getattr(self.agent, "output_schema", None)
        schema_name = _schema_name(schema)
        model_tier, model_id = _selected_model_route(self.agent, routing_context)
        configured_modes = getattr(self.agent.model, REPORTING_STRUCTURED_MODES_MODEL_ATTR, None)
        configured_mode = (
            configured_modes.get(model_tier) if isinstance(configured_modes, dict) else None
        )
        model_endpoint = getattr(getattr(self.agent, "model", None), "base_url", None)
        wire_contract = self.wire_schema_resolver.resolve(
            schema,
            model_id=model_id,
            endpoint=model_endpoint if isinstance(model_endpoint, str) else None,
        )
        capability_key = _runtime_capability_key(model_tier, wire_contract)
        capabilities = self.capability_resolver.resolve(
            model_id,
            configured_mode=configured_mode,
            verified_mode=_runtime_verified_mode(self.agent, capability_key),
            endpoint=model_endpoint if isinstance(model_endpoint, str) else None,
        )
        mode = capabilities.primary
        fallback = capabilities.fallback
        mode_source = capabilities.source
        route_binding = (
            bind_reporting_run_context(routing_context)
            if routing_context is not None
            else nullcontext()
        )
        # 模型协议解析和 ReportingPhaseOpenAIChat 的实际 request model 必须读取
        # 同一个受信路由上下文，否则日志中的 model_id 可能与真正请求的模型分离。
        current_instruction: str | list[Message] = instruction
        budget = call_budget or StructuredOutputCallBudget()
        if budget.exhausted:
            raise ReportingError(
                "report_phase_output_invalid",
                "结构化 Agent 业务调用已达到上限。",
            )
        total_call_number = 0
        business_call_number = 0
        protocol_attempt_number = 0
        thinking_attempt = min(thinking_request.attempt, 1) if thinking_request is not None else 0
        next_failure_kind: ThinkingFailureKind | None = (
            thinking_request.failure_kind if thinking_request is not None else None
        )
        with route_binding, anyio.fail_after(self.idle_timeout_seconds):
            while True:
                total_call_number += 1
                if mode is StructuredOutputMode.JSON_SCHEMA:
                    protocol_attempt_number += 1
                try:
                    thinking_binding = nullcontext()
                    if thinking_request is not None:
                        call_request = replace(
                            thinking_request,
                            attempt=thinking_attempt,
                            failure_kind=next_failure_kind,
                        )
                        thinking_binding = bind_reporting_thinking(
                            select_reporting_thinking(call_request)
                        )
                    with thinking_binding:
                        execution_agent, output = await self._execute_mode(
                            mode,
                            schema,
                            current_instruction,
                            session_id=f"{session_id}:structured:{total_call_number}",
                            user_id=user_id,
                            agent_run_context=agent_run_context,
                            model_id=model_id,
                            source=mode_source,
                            call_number=total_call_number,
                            protocol_attempt_number=protocol_attempt_number,
                            wire_contract=wire_contract,
                        )
                    _raise_recorded_agent_error(execution_agent)
                    content = _validate_content(
                        wire_contract.decode(getattr(output, "content", output)),
                        schema,
                    )
                except Exception as error:
                    validation_error = _find_validation_error(error)
                    transport_error = (
                        validation_error is None
                        and mode is StructuredOutputMode.JSON_SCHEMA
                        and fallback is not None
                        and _is_schema_transport_error(error)
                    )
                    if validation_error is None and not transport_error:
                        raise

                    previous_mode = mode
                    if transport_error:
                        # Schema 协商失败发生在模型生成业务结果之前，不属于业务纠错。
                        # 降级后必须使用原始指令重新请求，不能把端点兼容问题伪装成
                        # 模型字段错误，也不能占用五次业务纠错额度。
                        mode = fallback or mode
                        _remember_runtime_verified_mode(self.agent, capability_key, mode)
                        mode_source = "runtime_schema_fallback"
                        current_instruction = instruction
                        logger.bind(
                            model_id=model_id,
                            agent_id=getattr(self.agent, "id", None),
                            schema_name=schema_name,
                            failure_kind="transport",
                            call_number=total_call_number,
                            protocol_attempt_number=protocol_attempt_number,
                            business_call_number=business_call_number,
                            previous_mode=previous_mode.value,
                            next_mode=mode.value,
                            fallback_reason="schema_transport_error",
                        ).warning("report_structured_output_mode_downgraded")
                        continue

                    assert validation_error is not None
                    thinking_attempt = 1
                    next_failure_kind = "schema_failure"
                    candidate = (
                        getattr(validation_error, "_report_candidate", None)
                        if validation_error is not None
                        else None
                    )
                    issues = _validation_issues(validation_error)
                    fingerprint = _issues_fingerprint(issues)
                    structural_error = (
                        validation_error is not None
                        and _is_structural_validation_error(validation_error)
                    )
                    if (
                        mode is StructuredOutputMode.JSON_SCHEMA
                        and fallback is not None
                        and structural_error
                    ):
                        mode = fallback
                        _remember_runtime_verified_mode(self.agent, capability_key, mode)
                        mode_source = "runtime_schema_fallback"
                        # strict Schema 请求返回结构错误，说明当前兼容端点没有兑现
                        # 原生约束。这是协议能力事实，不占用五次领域纠错额度；
                        # 但保留精确 issues，帮助 JSON object 首次请求直接修正。
                        current_instruction = _correction_instruction(
                            instruction,
                            correction_number=1,
                            previous_output=candidate,
                            issues=issues,
                        )
                        logger.bind(
                            model_id=model_id,
                            agent_id=getattr(self.agent, "id", None),
                            schema_name=schema_name,
                            failure_kind="structure",
                            call_number=total_call_number,
                            protocol_attempt_number=protocol_attempt_number,
                            business_call_number=business_call_number,
                            correction_number=1,
                            previous_mode=previous_mode.value,
                            next_mode=mode.value,
                            fallback_reason="schema_structure_error",
                            issue_fingerprint=fingerprint,
                        ).warning("report_structured_output_mode_downgraded")
                        continue

                    business_call_number += 1
                    budget.record_model_call()
                    if budget.exhausted:
                        raise _structured_output_error(error, schema) from error
                    correction_number = business_call_number
                    current_instruction = _correction_instruction(
                        instruction,
                        correction_number=correction_number,
                        previous_output=candidate,
                        issues=issues,
                    )
                    event = (
                        "report_structured_output_mode_downgraded"
                        if mode is not previous_mode
                        else "report_structured_output_correction_requested"
                    )
                    logger.warning(
                        "report_structured_output_validation_failed schema_name={} issues={}",
                        schema_name,
                        json.dumps(issues, ensure_ascii=False, separators=(",", ":")),
                    )
                    logger.bind(
                        model_id=model_id,
                        agent_id=getattr(self.agent, "id", None),
                        schema_name=schema_name,
                        failure_kind="structure" if structural_error else "business",
                        call_number=total_call_number,
                        protocol_attempt_number=protocol_attempt_number,
                        business_call_number=business_call_number,
                        business_model_call_total=budget.model_calls,
                        correction_number=correction_number,
                        previous_mode=previous_mode.value,
                        next_mode=mode.value,
                        fallback_reason=(
                            "repeated_schema_structure_error" if mode is not previous_mode else None
                        ),
                        issue_fingerprint=fingerprint,
                        issues=issues,
                    ).warning(event)
                    continue
                business_call_number += 1
                budget.record_model_call()
                return StructuredOutputResult(
                    content=content,
                    run_output=output,
                    mode=mode,
                    model_id=model_id,
                )
        raise AssertionError("Reporting 结构化输出执行循环未终止。")

    async def _execute_mode(
        self,
        mode: StructuredOutputMode,
        schema: Any,
        instruction: str | list[Message],
        *,
        session_id: str,
        user_id: str,
        agent_run_context: RunContext | None,
        model_id: str,
        source: str,
        call_number: int,
        protocol_attempt_number: int,
        wire_contract: StructuredOutputWireContract,
    ) -> tuple[Agent, Any]:
        execution_agent = _agent_for_mode(self.agent, schema, mode, wire_contract)
        logger.bind(
            model_id=model_id,
            agent_id=execution_agent.id,
            schema_name=_schema_name(schema),
            mode=mode.value,
            strict=(
                bool(getattr(execution_agent.model, "strict_output", False))
                if mode is StructuredOutputMode.JSON_SCHEMA
                else None
            ),
            source=source,
            wire_dialect=wire_contract.dialect.value,
            wire_schema_fingerprint=wire_contract.wire_fingerprint,
            call_number=call_number,
            protocol_attempt_number=protocol_attempt_number,
        ).debug("report_structured_output_attempt")
        result = execution_agent.arun(
            instruction,
            stream=False,
            session_id=session_id,
            user_id=user_id,
            run_context=agent_run_context,
        )
        output = await result if isawaitable(result) else result
        return execution_agent, output


def _selected_model_route(agent: Agent, run_context: RunContext | None) -> tuple[str, str]:
    route = reporting_model_route_from_run_context(run_context)
    if route is not None:
        return route
    model_id = getattr(getattr(agent, "model", None), "id", None)
    return (
        "standard",
        model_id if isinstance(model_id, str) and model_id.strip() else "unknown",
    )


def _runtime_capability_key(
    model_tier: str,
    wire_contract: StructuredOutputWireContract,
) -> str:
    return f"{model_tier}:{wire_contract.cache_key}"


def _runtime_verified_mode(agent: Agent, capability_key: str) -> str | None:
    modes = getattr(
        getattr(agent, "model", None),
        REPORTING_VERIFIED_STRUCTURED_MODES_MODEL_ATTR,
        None,
    )
    if not isinstance(modes, dict):
        return None
    mode = modes.get(capability_key)
    return mode if isinstance(mode, str) else None


def _remember_runtime_verified_mode(
    agent: Agent,
    capability_key: str,
    mode: StructuredOutputMode,
) -> None:
    model = getattr(agent, "model", None)
    if model is None:
        return
    modes = getattr(model, REPORTING_VERIFIED_STRUCTURED_MODES_MODEL_ATTR, None)
    if not isinstance(modes, dict):
        modes = {}
        setattr(model, REPORTING_VERIFIED_STRUCTURED_MODES_MODEL_ATTR, modes)
    modes[capability_key] = mode.value


def _agent_for_mode(
    agent: Agent,
    schema: Any,
    mode: StructuredOutputMode,
    wire_contract: StructuredOutputWireContract,
) -> Agent:
    if not isinstance(agent, Agent) or schema is None:
        return agent
    if agent.model is None:
        return agent
    model = copy(agent.model)
    # 结构化输出同样必须继承 Reporting 的统一输出预算。清空 max_tokens 会让
    # 不同兼容端点落入各自的服务端默认值；Ark 当前默认约 4K 可见 token，复杂
    # Schema 会在对象闭合前被稳定截断，后续纠错也无法收敛。
    setattr(model, REPORTING_STRUCTURED_REQUEST_MODEL_ATTR, True)
    if mode is StructuredOutputMode.JSON_SCHEMA:
        if wire_contract.schema is not None:
            setattr(model, REPORTING_WIRE_SCHEMA_MODEL_ATTR, wire_contract.schema)
            setattr(model, REPORTING_WIRE_DECODER_MODEL_ATTR, wire_contract.decode)
            setattr(model, REPORTING_WIRE_DOMAIN_SCHEMA_MODEL_ATTR, schema)
            setattr(model, REPORTING_WIRE_DIALECT_MODEL_ATTR, wire_contract.dialect.value)
            setattr(
                model,
                REPORTING_WIRE_FINGERPRINT_MODEL_ATTR,
                wire_contract.wire_fingerprint,
            )
        instructions = agent.instructions
        if wire_contract.instruction:
            if isinstance(instructions, str):
                instructions = [instructions, wire_contract.instruction]
            elif isinstance(instructions, list):
                instructions = list(instructions)
                if wire_contract.instruction not in instructions:
                    instructions.append(wire_contract.instruction)
        return agent.deep_copy(
            update={
                "model": model,
                "instructions": instructions,
                "output_schema": schema,
                "parse_response": True,
                "structured_outputs": True,
                "use_json_mode": False,
                "tools": [],
                "tool_choice": None,
                "retries": 0,
                "exponential_backoff": False,
            }
        )
    required_fields_instruction = _required_fields_instruction(schema)
    instructions = agent.instructions
    if required_fields_instruction:
        if isinstance(instructions, str):
            instructions = [instructions, required_fields_instruction]
        elif isinstance(instructions, list):
            instructions = [*instructions, required_fields_instruction]
    return agent.deep_copy(
        update={
            "model": model,
            "instructions": instructions,
            "output_schema": schema,
            "parse_response": True,
            "structured_outputs": False,
            "use_json_mode": True,
            "tools": [],
            "tool_choice": None,
            "retries": 0,
            "exponential_backoff": False,
        }
    )


def _required_fields_instruction(schema: Any) -> str | None:
    """补足 Agno JSON mode 提示词丢失的对象 required 契约。"""

    if isinstance(schema, type) and issubclass(schema, BaseModel):
        json_schema = schema.model_json_schema(by_alias=True)
    elif isinstance(schema, dict):
        json_schema = schema
    else:
        return None

    required_fields: dict[str, list[str]] = {}
    non_empty_arrays: dict[str, list[str]] = {}
    root_required = json_schema.get("required")
    if isinstance(root_required, list) and all(isinstance(item, str) for item in root_required):
        required_fields["$"] = root_required
    root_properties = json_schema.get("properties")
    if isinstance(root_properties, dict):
        root_arrays = [
            name
            for name, property_schema in root_properties.items()
            if isinstance(name, str)
            and isinstance(property_schema, dict)
            and isinstance(property_schema.get("minItems"), int)
            and property_schema["minItems"] > 0
        ]
        if root_arrays:
            non_empty_arrays["$"] = root_arrays
    definitions = json_schema.get("$defs")
    if isinstance(definitions, dict):
        for name, definition in definitions.items():
            if not isinstance(name, str) or not isinstance(definition, dict):
                continue
            required = definition.get("required")
            if isinstance(required, list) and all(isinstance(item, str) for item in required):
                required_fields[name] = required
            properties = definition.get("properties")
            if isinstance(properties, dict):
                arrays = [
                    field_name
                    for field_name, property_schema in properties.items()
                    if isinstance(field_name, str)
                    and isinstance(property_schema, dict)
                    and isinstance(property_schema.get("minItems"), int)
                    and property_schema["minItems"] > 0
                ]
                if arrays:
                    non_empty_arrays[name] = arrays
    if not required_fields and not non_empty_arrays:
        return None

    required_contract = json.dumps(required_fields, ensure_ascii=False, separators=(",", ":"))
    array_contract = json.dumps(non_empty_arrays, ensure_ascii=False, separators=(",", ":"))
    return (
        "根响应必须是单个 JSON 对象，以 { 开始并以 } 结束；不得用数组或额外包装键包裹。"
        "嵌套对象必填字段契约（$ 表示根对象，其余键为 JSON Schema 对象类型）："
        f"{required_contract}。每个对象实例都必须逐项包含对应数组中的全部字段，不得因字段语义相近、"
        "值为空或位于数组项中而省略。非空数组约束（同样按对象类型分组）："
        f"{array_contract}。这些字段至少包含一个元素，不得返回空数组。"
    )


def _find_validation_error(error: BaseException) -> ValidationError | None:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, ValidationError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _validation_issues(error: ValidationError) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for item in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        path = "$"
        for part in item.get("loc", ()):
            path += f"[{part}]" if isinstance(part, int) else f".{part}"
        issues.append(
            {
                "path": path,
                "type": str(item.get("type", "validation_error")),
                "message": str(item.get("msg", "结构化字段无效。")),
            }
        )
    return issues


def _is_structural_validation_error(error: ValidationError) -> bool:
    """自定义 validator 属于业务契约，不能触发协议降级。"""

    issue_types = {str(item.get("type", "")) for item in error.errors()}
    return bool(issue_types) and not any(
        issue_type == "assertion_error" or issue_type.startswith("value_error")
        for issue_type in issue_types
    )


def _issues_fingerprint(issues: list[dict[str, str]]) -> str:
    encoded = json.dumps(
        issues,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return sha256(encoded).hexdigest()[:16]


def _correction_instruction(
    instruction: str,
    *,
    correction_number: int,
    previous_output: Any,
    issues: list[dict[str, str]],
) -> list[Message]:
    correction = {
        "attempt": correction_number,
        "issues": issues,
        "requiredAction": (
            "逐项修复 issues，返回满足原 output_schema 的完整 JSON 对象；"
            "不得输出解释、Markdown 或省略未报错的必填字段。"
        ),
    }
    candidate = _json_safe(previous_output)
    if candidate is not None:
        encoded_candidate = json.dumps(
            candidate,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode()
        if len(encoded_candidate) <= _MAX_CORRECTION_CANDIDATE_BYTES:
            correction["previousOutput"] = candidate
        else:
            # 截断 JSON 通常已经包含整章正文。把它同时作为 assistant 历史和
            # previousOutput 回灌会成倍放大上下文，并诱发下一轮再次截断。超限时只
            # 保留不可逆诊断事实，让模型依据原始输入和精确 issues 重新生成完整结果。
            correction["previousOutputOmitted"] = {
                "reason": "size_limit",
                "byteLength": len(encoded_candidate),
                "sha256": sha256(encoded_candidate).hexdigest(),
            }
    serialized = json.dumps(correction, ensure_ascii=False, separators=(",", ":"), default=str)
    return [
        Message(role="user", content=instruction),
        Message(
            role="user",
            content=(
                "上一响应未通过 Reporting 结构校验。下面是服务端签发的纠错事实：\n"
                f"{serialized}\n"
                "重新返回完整的业务结果 JSON，不得返回纠错事实本身。"
            ),
        ),
    ]


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value) if value is not None else None
    return value


def _is_schema_transport_error(error: BaseException) -> bool:
    evidence: list[str] = []
    status_codes: set[int] = set()
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        evidence.append(str(current).lower())
        for attribute in ("code", "param", "body"):
            value = getattr(current, attribute, None)
            if value is not None:
                evidence.append(str(value).lower())
        status_code = getattr(current, "status_code", None)
        if isinstance(status_code, int):
            status_codes.add(status_code)
        response_status = getattr(getattr(current, "response", None), "status_code", None)
        if isinstance(response_status, int):
            status_codes.add(response_status)
        current = current.__cause__ or current.__context__
    # 有权威 HTTP 状态时只接受请求语义错误。401/403/429/5xx 即使文本中出现
    # response_format，也属于鉴权、限流或服务故障，不能通过协议降级掩盖。
    if status_codes and not status_codes.issubset({400, 422}):
        return False
    combined = " ".join(evidence)
    protocol_named = any(
        marker in combined
        for marker in (
            "response_format",
            "json_schema",
            "json schema",
            "json_schema_converter",
        )
    )
    rejected = any(
        marker in combined
        for marker in (
            "not support",
            "unsupported",
            "invalid",
            "not available",
            "not allowed",
            "does not support",
            "cannot find field $defs",
        )
    )
    return protocol_named and rejected


def _schema_name(schema: Any) -> str:
    return str(getattr(schema, "__name__", type(schema).__name__))


def _structured_output_error(error: Exception, schema: Any) -> ReportingError:
    if isinstance(error, ReportingError):
        return error
    validation_error = _find_validation_error(error)
    details: dict[str, Any] = {"schema": getattr(schema, "__name__", type(schema).__name__)}
    if validation_error is not None:
        details["errors"] = validation_error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    return ReportingError(
        "report_phase_output_invalid",
        "结构化 Agent 在 5 次纠错后仍未返回声明的阶段结果。",
        details=details,
    )


def _raise_recorded_agent_error(agent: Agent) -> None:
    report_run_error = getattr(agent.model, "report_run_error", None)
    error = report_run_error() if callable(report_run_error) else None
    if isinstance(error, Exception):
        raise error


def _validate_content(content: Any, schema: Any) -> Any:
    if schema is None:
        return content
    try:
        valid_instance = isinstance(content, schema)
    except TypeError:
        valid_instance = False
    if valid_instance:
        return content
    validator = getattr(schema, "model_validate", None)
    try:
        json_validator = getattr(schema, "model_validate_json", None)
        if isinstance(content, str) and callable(json_validator):
            return _validate_structured_text(content, schema, json_validator)
        return (
            validator(content)
            if callable(validator)
            else TypeAdapter(schema).validate_python(content)
        )
    except Exception as error:
        details: dict[str, Any] = {"schema": getattr(schema, "__name__", type(schema).__name__)}
        if isinstance(error, ValidationError):
            candidate = _validation_candidate(content)
            if isinstance(candidate, dict | list | str):
                # Planner 的既有纠错循环需要原候选作为 previousOutput；这里只附加
                # 进程内诊断属性，不写日志、不进入公开错误 details，也不改变候选值。
                error._report_candidate = candidate  # type: ignore[attr-defined]
            details["errors"] = error.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
        raise ReportingError(
            "report_phase_output_invalid",
            "结构化 Agent 未返回声明的阶段结果。",
            details=details,
        ) from error


def _validation_candidate(content: Any) -> Any:
    if not isinstance(content, str):
        return content
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        # 完整保留模型的上一轮文本，仅用于下一轮 assistant 消息纠错；不得写入
        # 日志或公开错误 details，也不得尝试拼接不完整 JSON。
        return content


def _validate_structured_text(
    content: str, schema: Any, json_validator: Callable[[str], Any]
) -> Any:
    """只从完整平衡 JSON 对象恢复候选，禁止拼接或推断字段。"""

    try:
        return json_validator(content)
    except Exception as direct_error:
        for index, candidate in enumerate(_complete_json_object_candidates(content)):
            if candidate == content:
                continue
            try:
                result = json_validator(candidate)
            except Exception:
                continue
            logger.debug(
                "report_structured_output_candidate_recovered schema={} candidate_index={}",
                getattr(schema, "__name__", type(schema).__name__),
                index,
            )
            return result
        raise direct_error


def _complete_json_object_candidates(content: str) -> tuple[str, ...]:
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(content):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
            continue
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(content[start : index + 1])
                start = None
    return tuple(candidates)
