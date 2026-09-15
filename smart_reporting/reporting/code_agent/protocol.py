from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextvars import ContextVar
from copy import copy, deepcopy
from time import perf_counter
from types import MappingProxyType
from typing import Any

from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from agno.models.response import ModelResponse
from loguru import logger

from ...context_management import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
    TaskExecutionContextProjector,
)
from ...runtime.observability import duration_ms as elapsed_ms
from ..model_policy import (
    reporting_model_output_token_limit,
    resolve_reporting_input_token_hard_cap,
)
from ..models import ReportingError
from ..phase import (
    current_reporting_run_context,
    record_reporting_projection_metrics,
    reporting_model_route_from_run_context,
    reporting_phase_allows_tool,
    reporting_phase_from_run_context,
    reporting_task_kind_from_run_context,
)

FREEFORM_TOOL_ARGUMENTS: Mapping[str, str] = MappingProxyType(
    {"write_script": "source", "execute_code": "code"}
)

_CUSTOM_TOOL_PROTOCOL_ERROR = "report_code_custom_tool_protocol_error"
_STREAMING_UNSUPPORTED = "report_code_streaming_unsupported"
_PROFILE_RECEIPT_PROJECTION_LIMIT = 100
_PROFILE_QUERY_IDENTITY_MAX_LENGTH = 256
_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT = 128 * 1024
_SECTION_OUTPUT_TOKEN_LIMIT = 32 * 1024
_MODEL_RUN_ERROR: ContextVar[tuple[int, Exception] | None] = ContextVar(
    "reporting_model_run_error", default=None
)


def report_model_tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        custom = tool.get("custom")
        if isinstance(custom, dict) and isinstance(custom.get("name"), str):
            return custom["name"]
        return tool.get("name") if isinstance(tool.get("name"), str) else None
    name = getattr(tool, "name", None)
    if isinstance(name, str):
        return name
    function = getattr(tool, "function", None)
    function_name = getattr(function, "name", None)
    return function_name if isinstance(function_name, str) else None


def reporting_phase_from_messages(messages: list[Message]) -> str | None:
    _ = messages
    return reporting_phase_from_run_context(current_reporting_run_context())


def phase_filtered_report_tools(messages: list[Message], tools: Any) -> Any:
    phase = reporting_phase_from_messages(messages)
    run_context = current_reporting_run_context()
    task_kind = reporting_task_kind_from_run_context(run_context)
    if phase is None or tools is None:
        return tools
    return [
        tool
        for tool in tools
        if (name := report_model_tool_name(tool)) is not None
        and reporting_phase_allows_tool(phase, name, task_kind=task_kind)
    ]


def phase_filtered_report_messages(messages: list[Message]) -> list[Message]:
    if reporting_phase_from_messages(messages) not in {"analysis", "section"}:
        return messages
    projected: list[Message] | None = None
    opening = "<skills_system>"
    closing = "</skills_system>"
    for index, message in enumerate(messages):
        content = message.content
        if message.role != "system" or not isinstance(content, str):
            continue
        start = content.find(opening)
        end = content.find(closing, start + len(opening)) if start >= 0 else -1
        if start < 0 or end < 0:
            continue
        end += len(closing)
        before = content[:start]
        after = content[end:]
        if before.endswith("\n") and after.startswith("\n"):
            after = after[1:]
        if projected is None:
            projected = list(messages)
        updated = deepcopy(message)
        updated.content = before + after
        projected[index] = updated
    return projected if projected is not None else messages


def with_reporting_durable_identities(messages: list[Message]) -> list[Message]:
    if reporting_phase_from_messages(messages) != "analysis":
        return messages
    receipts: dict[str, dict[str, str]] = {}
    for message in messages:
        if message.role != "tool" or message.tool_name != "query_profile":
            continue
        payload: dict[str, Any] | None = None
        for content in (message.content, message.compressed_content):
            if isinstance(content, dict):
                candidate = content
            elif isinstance(content, str):
                try:
                    candidate = json.loads(content)
                except (TypeError, ValueError):
                    continue
            else:
                continue
            if isinstance(candidate, dict) and candidate.get("ok") is True:
                payload = candidate
                break
        receipt = payload.get("readReceipt") if isinstance(payload, dict) else None
        if not isinstance(receipt, dict):
            continue
        receipt_id = receipt.get("receiptId")
        dataset_id = receipt.get("datasetId")
        snapshot_hash = receipt.get("snapshotHash")
        query = receipt.get("query")
        if not all(
            isinstance(value, str) and value
            for value in (receipt_id, dataset_id, snapshot_hash, query)
        ):
            continue
        identity = {
            "receiptId": receipt_id,
            "datasetId": dataset_id,
            "snapshotHash": snapshot_hash,
            "querySha256": hashlib.sha256(query.encode()).hexdigest(),
        }
        if len(query) <= _PROFILE_QUERY_IDENTITY_MAX_LENGTH:
            identity["query"] = query
        receipts[receipt_id] = identity
    if not receipts:
        return messages
    ledger = {
        "marker": "REPORTING_DURABLE_IDENTITIES",
        "version": 1,
        "profileReadReceipts": list(receipts.values())[-_PROFILE_RECEIPT_PROJECTION_LIMIT:],
    }
    return [
        *messages,
        Message(role="user", content=json.dumps(ledger, ensure_ascii=False, separators=(",", ":"))),
    ]


def phase_filtered_model_call(
    messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    positional = list(args)
    updated_kwargs = dict(kwargs)
    if "tools" in updated_kwargs:
        updated_kwargs["tools"] = phase_filtered_report_tools(messages, updated_kwargs.get("tools"))
    elif len(args) >= 3:
        positional[2] = phase_filtered_report_tools(messages, positional[2])
    projected_tools = updated_kwargs.get("tools")
    if projected_tools is None and len(positional) >= 3:
        projected_tools = positional[2]
    if (
        reporting_task_kind_from_run_context(current_reporting_run_context())
        == "visualization_section"
    ):
        visible_names = [
            name
            for tool in projected_tools or ()
            if (name := report_model_tool_name(tool)) is not None
        ]
        if len(visible_names) == 1:
            tool_name = visible_names[0]
            updated_kwargs["tool_choice"] = (
                {"type": "custom", "custom": {"name": tool_name}}
                if tool_name in FREEFORM_TOOL_ARGUMENTS
                else {"type": "function", "function": {"name": tool_name}}
            )
    return tuple(positional), updated_kwargs


def _field(value: Any, field: str) -> Any:
    return value.get(field) if isinstance(value, Mapping) else getattr(value, field, None)


def _required_id(value: Any, field: str) -> str:
    identity = _field(value, field)
    if not isinstance(identity, str) or not identity:
        raise ReportingError(_CUSTOM_TOOL_PROTOCOL_ERROR, "Coding Agent custom 工具调用缺少身份。")
    return identity


def _synthetic_custom_call(item: Any) -> dict[str, Any]:
    name = _field(item, "name")
    raw_input = _field(item, "input")
    if name not in FREEFORM_TOOL_ARGUMENTS or not isinstance(raw_input, str) or not raw_input:
        raise ReportingError(_CUSTOM_TOOL_PROTOCOL_ERROR, "Coding Agent custom 工具调用无效。")
    item_id = _required_id(item, "id")
    call_id = _required_id(item, "call_id")
    return {
        "id": item_id,
        "call_id": call_id,
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(
                {FREEFORM_TOOL_ARGUMENTS[name]: raw_input},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        "provider_data": {"reporting_wire_type": "custom", "raw_input": raw_input},
    }


class ReportingCodeOpenAIResponses(OpenAIResponses):
    """为 Coding Agent 桥接 Responses API function/custom 混合协议。"""

    def _format_tool_params(
        self, messages: list[Message], tools: Any = None
    ) -> list[dict[str, Any]]:
        formatted = super()._format_tool_params(messages, tools)
        result: list[dict[str, Any]] = []
        for tool in formatted:
            name = str(tool.get("name") or "")
            if name not in FREEFORM_TOOL_ARGUMENTS:
                result.append(tool)
                continue
            result.append(
                {
                    "type": "custom",
                    "name": name,
                    "description": str(tool.get("description") or name),
                    "format": {"type": "text"},
                }
            )
        return result

    def count_tokens(
        self, messages: list[Message], tools: Any = None, output_schema: Any = None
    ) -> int:
        return Model.count_tokens(self, messages, tools, output_schema)

    def _phase_request_model(self, messages: list[Message]) -> ReportingCodeOpenAIResponses:
        request_model = copy(self)
        model_route = reporting_model_route_from_run_context(current_reporting_run_context())
        if model_route is not None:
            _, request_model.id = model_route
        task_kind = reporting_task_kind_from_run_context(current_reporting_run_context())
        if task_kind == "visualization_section":
            output_limit = _VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT
        elif task_kind == "section":
            output_limit = _SECTION_OUTPUT_TOKEN_LIMIT
        else:
            output_limit = None
        limits = [
            value
            for value in (
                request_model.max_output_tokens,
                output_limit,
                reporting_model_output_token_limit(request_model.id),
            )
            if isinstance(value, int) and value > 0
        ]
        request_model.max_output_tokens = min(limits) if limits else None
        return request_model

    def _project(
        self, messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> list[Message]:
        response_format = kwargs.get("response_format", args[1] if len(args) > 1 else None)
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        tools = phase_filtered_report_tools(messages, tools)
        configured_cap = getattr(self, "_task_execution_input_token_budget", None)
        if (
            not isinstance(configured_cap, int)
            or isinstance(configured_cap, bool)
            or configured_cap < 1
        ):
            configured_cap = (
                TASK_EXECUTION_CONTEXT_TOKEN_LIMIT - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE
            )
        output_reserve = (
            self.max_output_tokens
            if isinstance(self.max_output_tokens, int) and self.max_output_tokens > 0
            else 0
        )
        hard_cap = resolve_reporting_input_token_hard_cap(
            configured_input_token_cap=configured_cap,
            model_id=self.id,
            output_token_reserve=max(TASK_EXECUTION_OUTPUT_TOKEN_RESERVE, output_reserve),
            absolute_input_token_cap=TASK_EXECUTION_CONTEXT_TOKEN_LIMIT
            - TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
        )
        projected, metrics = TaskExecutionContextProjector.project_with_metrics(
            with_reporting_durable_identities(messages),
            model=self,
            tools=tools,
            response_format=response_format,
            hard_cap=hard_cap,
        )
        record_reporting_projection_metrics(metrics, input_token_hard_cap=hard_cap)
        return projected

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        if _field(response, "error") is not None:
            return super()._parse_provider_response(response, **kwargs)
        output = _field(response, "output")
        output = list(output) if isinstance(output, (list, tuple)) else []
        actionable = [
            item for item in output if _field(item, "type") in {"custom_tool_call", "function_call"}
        ]
        if len(actionable) > 1:
            raise ReportingError(
                _CUSTOM_TOOL_PROTOCOL_ERROR, "Coding Agent 每轮只允许一次工具调用。"
            )
        custom_calls = [item for item in actionable if _field(item, "type") == "custom_tool_call"]
        parsed = super()._parse_provider_response(response, **kwargs)
        if not custom_calls:
            return parsed
        call = _synthetic_custom_call(custom_calls[0])
        parsed.content = None
        parsed.tool_calls = [call]
        parsed.extra = parsed.extra or {}
        parsed.extra["tool_call_ids"] = [call["call_id"]]
        return parsed

    def _format_messages(
        self,
        messages: list[Message],
        compress_tool_results: bool = False,
        tools: Any = None,
    ) -> list[Any]:
        assistant_calls: list[dict[str, Any]] = []
        for message in messages:
            for call in message.tool_calls or ():
                assistant_calls.append(call)
        formatted = super()._format_messages(messages, compress_tool_results, tools)
        call_index = 0
        normalized_custom_calls: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(formatted):
            if not isinstance(item, dict) or item.get("type") not in {
                "function_call",
                "function_call_output",
            }:
                continue
            if item["type"] == "function_call":
                if call_index >= len(assistant_calls):
                    continue
                call = assistant_calls[call_index]
                call_index += 1
                provider_data = call.get("provider_data")
                if (
                    not isinstance(provider_data, Mapping)
                    or provider_data.get("reporting_wire_type") != "custom"
                ):
                    continue
                normalized_call_id = item.get("call_id")
                if isinstance(normalized_call_id, str):
                    normalized_custom_calls[normalized_call_id] = call
                formatted[index] = {
                    "type": "custom_tool_call",
                    "id": call["id"],
                    "call_id": call["call_id"],
                    "name": call["function"]["name"],
                    "input": provider_data["raw_input"],
                    "status": "completed",
                }
            else:
                call = normalized_custom_calls.get(str(item.get("call_id") or ""))
                if call is None:
                    continue
                formatted[index] = {
                    "type": "custom_tool_call_output",
                    "call_id": call["call_id"],
                    "output": item["output"],
                }
        return formatted

    @staticmethod
    def _raise_stable_custom_error(error: Exception) -> None:
        cause = error.__cause__
        if isinstance(cause, ReportingError) and cause.code == _CUSTOM_TOOL_PROTOCOL_ERROR:
            raise cause

    def _clear_report_run_error(self) -> None:
        _MODEL_RUN_ERROR.set(None)

    def _record_report_run_error(self, error: Exception) -> None:
        _MODEL_RUN_ERROR.set((id(self), error))

    def report_run_error(self) -> Exception | None:
        recorded = _MODEL_RUN_ERROR.get()
        return recorded[1] if recorded is not None and recorded[0] == id(self) else None

    def response(self, messages: list[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        request_model = self._phase_request_model(messages)
        self._clear_report_run_error()
        try:
            response = OpenAIResponses.response(request_model, messages, *args, **kwargs)
            self._clear_report_run_error()
            return response
        except Exception as error:
            self._record_report_run_error(error)
            raise

    async def aresponse(self, messages: list[Message], *args: Any, **kwargs: Any) -> ModelResponse:
        request_model = self._phase_request_model(messages)
        self._clear_report_run_error()
        started_at = perf_counter()
        logger.bind(
            model_id=request_model.id,
            duration_ms=0,
            status="started",
            degraded=False,
            error_type=None,
        ).info(
            "report_code_response_started model_id={} duration_ms=0 status=started degraded=false error_type=-",
            request_model.id,
        )
        try:
            response = await OpenAIResponses.aresponse(request_model, messages, *args, **kwargs)
            self._clear_report_run_error()
            duration_ms = elapsed_ms(started_at)
            logger.bind(
                model_id=request_model.id,
                duration_ms=duration_ms,
                status="completed",
                degraded=False,
                error_type=None,
            ).info(
                "report_code_response_completed model_id={} duration_ms={} status=completed degraded=false error_type=-",
                request_model.id,
                duration_ms,
            )
            return response
        except Exception as error:
            self._record_report_run_error(error)
            duration_ms = elapsed_ms(started_at)
            error_type = type(error).__name__
            logger.bind(
                model_id=request_model.id,
                duration_ms=duration_ms,
                status="failed",
                degraded=False,
                error_type=error_type,
            ).warning(
                "report_code_response_completed model_id={} duration_ms={} status=failed degraded=false error_type={}",
                request_model.id,
                duration_ms,
                error_type,
            )
            raise

    def invoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        messages = phase_filtered_report_messages(messages)
        args, kwargs = phase_filtered_model_call(messages, args, kwargs)
        messages = self._project(messages, args, kwargs)
        try:
            return super().invoke(messages, *args, **kwargs)
        except Exception as error:
            self._raise_stable_custom_error(error)
            raise

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        messages = phase_filtered_report_messages(messages)
        args, kwargs = phase_filtered_model_call(messages, args, kwargs)
        messages = self._project(messages, args, kwargs)
        try:
            return await super().ainvoke(messages, *args, **kwargs)
        except Exception as error:
            self._raise_stable_custom_error(error)
            raise

    @staticmethod
    def _freeform_tool_requested(tools: Any) -> bool:
        return bool(tools) and any(
            report_model_tool_name(tool) in FREEFORM_TOOL_ARGUMENTS for tool in tools
        )

    def _reject_streaming_freeform_tool(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> None:
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        if self._freeform_tool_requested(tools):
            raise ReportingError(
                _STREAMING_UNSUPPORTED,
                "Coding Agent free-form custom 工具仅支持非流式响应。",
            )

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        self._reject_streaming_freeform_tool(args, kwargs)
        return super().invoke_stream(messages, *args, **kwargs)

    def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        self._reject_streaming_freeform_tool(args, kwargs)
        return super().ainvoke_stream(messages, *args, **kwargs)
