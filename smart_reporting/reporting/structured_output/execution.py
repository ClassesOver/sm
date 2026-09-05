"""Reporting 专属的 Agno 结构化输出执行边界。"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import nullcontext
from copy import copy
from dataclasses import dataclass
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
from ..models import ReportingError
from ..phase import bind_reporting_run_context, reporting_model_route_from_run_context
from .policy import (
    REPORTING_STRUCTURED_MODES_MODEL_ATTR,
    StructuredOutputMode,
    VerifiedModelCapabilityResolver,
)

_MAX_CORRECTIONS = 5
_MAX_MODEL_CALLS = _MAX_CORRECTIONS + 1


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


class ReportingStructuredOutputExecutor:
    """使用 Agno 执行结构化 Agent，并协调 Reporting 的有界纠错策略。"""

    def __init__(
        self,
        agent: Agent,
        *,
        idle_timeout_seconds: float = 900,
        capability_resolver: VerifiedModelCapabilityResolver | None = None,
    ) -> None:
        self.agent = agent
        self.idle_timeout_seconds = idle_timeout_seconds
        self.capability_resolver = capability_resolver or VerifiedModelCapabilityResolver()

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
    ) -> Any:
        result = await self.execute(
            instruction,
            routing_context=run_context,
            agent_run_context=run_context,
            session_id=f"task-execution:{scope.external_run_id}:attempt:0",
            user_id=scope.owner_user_id,
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
    ) -> StructuredOutputResult:
        schema = getattr(self.agent, "output_schema", None)
        model_tier, model_id = _selected_model_route(self.agent, routing_context)
        configured_modes = getattr(self.agent.model, REPORTING_STRUCTURED_MODES_MODEL_ATTR, None)
        configured_mode = (
            configured_modes.get(model_tier) if isinstance(configured_modes, dict) else None
        )
        capabilities = self.capability_resolver.resolve(
            model_id,
            configured_mode=configured_mode,
        )
        mode = capabilities.primary
        fallback = capabilities.fallback
        route_binding = (
            bind_reporting_run_context(routing_context)
            if routing_context is not None
            else nullcontext()
        )
        # 模型协议解析和 ReportingPhaseOpenAIChat 的实际 request model 必须读取
        # 同一个受信路由上下文，否则日志中的 model_id 可能与真正请求的模型分离。
        current_instruction: str | list[Message] = instruction
        seen_structural_errors: set[str] = set()
        with route_binding, anyio.fail_after(self.idle_timeout_seconds):
            for call_number in range(1, _MAX_MODEL_CALLS + 1):
                try:
                    execution_agent, output = await self._execute_mode(
                        mode,
                        schema,
                        current_instruction,
                        session_id=f"{session_id}:structured:{call_number}",
                        user_id=user_id,
                        agent_run_context=agent_run_context,
                        model_id=model_id,
                        source=capabilities.source,
                        call_number=call_number,
                    )
                    _raise_recorded_agent_error(execution_agent)
                    content = _validate_content(getattr(output, "content", output), schema)
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
                    if call_number >= _MAX_MODEL_CALLS:
                        raise _structured_output_error(error, schema) from error

                    candidate = (
                        getattr(validation_error, "_report_candidate", None)
                        if validation_error is not None
                        else None
                    )
                    issues = (
                        _validation_issues(validation_error)
                        if validation_error is not None
                        else [_transport_issue(error)]
                    )
                    fingerprint = _issues_fingerprint(issues)
                    repeated_structural_error = (
                        validation_error is not None
                        and _is_structural_validation_error(validation_error)
                        and fingerprint in seen_structural_errors
                    )
                    if validation_error is not None and _is_structural_validation_error(
                        validation_error
                    ):
                        seen_structural_errors.add(fingerprint)

                    previous_mode = mode
                    if transport_error or (
                        mode is StructuredOutputMode.JSON_SCHEMA
                        and fallback is not None
                        and repeated_structural_error
                    ):
                        mode = fallback
                    correction_number = call_number
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
                    logger.bind(
                        model_id=model_id,
                        agent_id=getattr(self.agent, "id", None),
                        call_number=call_number,
                        correction_number=correction_number,
                        previous_mode=previous_mode.value,
                        next_mode=mode.value,
                        issue_fingerprint=fingerprint,
                    ).warning(event)
                    continue
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
    ) -> tuple[Agent, Any]:
        execution_agent = _agent_for_mode(self.agent, schema, mode)
        logger.bind(
            model_id=model_id,
            agent_id=execution_agent.id,
            mode=mode.value,
            source=source,
            call_number=call_number,
        ).info("report_structured_output_attempt")
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


def _agent_for_mode(agent: Agent, schema: Any, mode: StructuredOutputMode) -> Agent:
    if not isinstance(agent, Agent) or schema is None:
        return agent
    model = copy(agent.model)
    if mode is StructuredOutputMode.JSON_SCHEMA:
        if hasattr(model, "strict_output"):
            model.strict_output = True
        return agent.deep_copy(
            update={
                "model": model,
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
    return agent.deep_copy(
        update={
            "model": model,
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


def _transport_issue(error: BaseException) -> dict[str, str]:
    message = " ".join(str(error).split())[:500]
    return {
        "path": "$",
        "type": "schema_transport_error",
        "message": message or "当前端点不接受 JSON Schema 响应格式。",
    }


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
        "previousOutput": _json_safe(previous_output),
        "issues": issues,
        "requiredAction": (
            "逐项修复 issues，返回满足原 output_schema 的完整 JSON 对象；"
            "不得输出解释、Markdown 或省略未报错的必填字段。"
        ),
    }
    serialized = json.dumps(correction, ensure_ascii=False, separators=(",", ":"), default=str)
    previous_content = _assistant_content(previous_output)
    messages = [Message(role="user", content=instruction)]
    if previous_content is not None:
        messages.append(Message(role="assistant", content=previous_content))
    messages.append(
        Message(
            role="user",
            content=(
                "上一响应未通过 Reporting 结构校验。下面是服务端签发的纠错事实：\n"
                f"{serialized}\n"
                "重新返回完整的业务结果 JSON，不得返回纠错事实本身。"
            ),
        )
    )
    return messages


def _assistant_content(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(_json_safe(value), ensure_ascii=False, separators=(",", ":"), default=str)


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=True)
    try:
        json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value) if value is not None else None
    return value


def _is_schema_transport_error(error: BaseException) -> bool:
    messages: list[str] = []
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        messages.append(str(current).lower())
        current = current.__cause__ or current.__context__
    combined = " ".join(messages)
    protocol_named = any(
        marker in combined for marker in ("response_format", "json_schema", "json schema")
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
        )
    )
    return protocol_named and rejected


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
            logger.info(
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
