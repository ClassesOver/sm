from __future__ import annotations

import ast
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
from agno.tools.function import FunctionCall
from agno.utils.message import normalize_tool_messages, reformat_tool_call_ids
from loguru import logger

from ...context_management import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
    TaskExecutionContextProjector,
)
from ...runtime.observability import duration_ms as elapsed_ms
from ..model_policy import (
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
    current_reporting_thinking_decision,
    reporting_model_output_token_limit,
    reporting_thinking_profile_from_model,
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
    {"write_script": "source", "run_snippet": "code"}
)

_CUSTOM_TOOL_PROTOCOL_ERROR = "report_code_custom_tool_protocol_error"
_FREEFORM_TOOL_GRAMMAR = "start: SOURCE\nSOURCE: /[\\s\\S]+/"
_STREAMING_UNSUPPORTED = "report_code_streaming_unsupported"
_TEXTUAL_TOOL_MARKERS = (
    "<|recipient=",
    "<|recipient|>",
    "<|tool_call=",
    "<|tool_call|>",
    "<｜DSML｜tool_calls>",
    "<｜DSML｜invoke",
    "```run_snippet",
    "```write_script",
)
_PROFILE_RECEIPT_PROJECTION_LIMIT = 100
_PROFILE_QUERY_IDENTITY_MAX_LENGTH = 256
_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT = 128 * 1024
_SECTION_OUTPUT_TOKEN_LIMIT = 32 * 1024
_DELIVERY_TOOL_NAMES = frozenset(
    {"write_script", "run_script", "submit_script", "view_image"}
)
_DELIVERY_TOOL_RESERVE = len(_DELIVERY_TOOL_NAMES)
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
                "auto"
                if tool_name in FREEFORM_TOOL_ARGUMENTS
                else {"type": "function", "name": tool_name}
            )
    return tuple(positional), updated_kwargs


def _field(value: Any, field: str) -> Any:
    return value.get(field) if isinstance(value, Mapping) else getattr(value, field, None)


def _custom_protocol_error(message: str) -> ReportingError:
    return ReportingError(_CUSTOM_TOOL_PROTOCOL_ERROR, message, details={"retryable": False})


def _contains_textual_tool_marker(output: list[Any]) -> bool:
    for item in output:
        if _field(item, "type") != "message" or _field(item, "role") != "assistant":
            continue
        content = _field(item, "content")
        for part in content if isinstance(content, (list, tuple)) else ():
            text = _field(part, "text")
            if isinstance(text, str) and any(
                marker in text for marker in _TEXTUAL_TOOL_MARKERS
            ):
                return True
    return False


def _required_id(value: Any, field: str) -> str:
    identity = _field(value, field)
    if not isinstance(identity, str) or not identity:
        raise _custom_protocol_error("Coding Agent custom 工具调用缺少身份。")
    return identity


def _synthetic_custom_call(item: Any) -> dict[str, Any]:
    name = _field(item, "name")
    raw_input = _field(item, "input")
    if name not in FREEFORM_TOOL_ARGUMENTS or not isinstance(raw_input, str) or not raw_input:
        raise _custom_protocol_error("Coding Agent custom 工具调用无效。")
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


def _validated_custom_replay_call(call: Any) -> dict[str, Any] | None:
    provider_data = _field(call, "provider_data")
    if (
        not isinstance(provider_data, Mapping)
        or provider_data.get("reporting_wire_type") != "custom"
    ):
        return None
    function = _field(call, "function")
    name = _field(function, "name")
    raw_input = provider_data.get("raw_input")
    if name not in FREEFORM_TOOL_ARGUMENTS or not isinstance(raw_input, str) or not raw_input:
        raise _custom_protocol_error("Coding Agent custom 工具重放数据无效。")
    item_id = _required_id(call, "id")
    call_id = _required_id(call, "call_id")
    arguments = _field(function, "arguments")
    try:
        decoded_arguments = json.loads(arguments) if isinstance(arguments, str) else None
    except (TypeError, ValueError) as error:
        raise _custom_protocol_error("Coding Agent custom 工具重放参数无效。") from error
    if decoded_arguments != {FREEFORM_TOOL_ARGUMENTS[name]: raw_input}:
        raise _custom_protocol_error("Coding Agent custom 工具重放参数不匹配。")
    return {
        "id": item_id,
        "call_id": call_id,
        "name": name,
        "raw_input": raw_input,
    }


class ReportingCodeOpenAIResponses(OpenAIResponses):
    """为 Coding Agent 桥接 Responses API function/custom 混合协议。"""

    @staticmethod
    def _is_non_executed_control_result(message: Message) -> bool:
        if message.tool_call_error is not True or not isinstance(message.content, str):
            return False
        try:
            payload = json.loads(message.content)
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, Mapping):
            return False
        details = payload.get("details")
        if isinstance(details, Mapping) and details.get("escalated") is True:
            return False
        return (payload.get("code"), payload.get("status")) in {
            ("report_code_delivery_budget_reserved", "rejected"),
            ("report_code_batch_stopped", "skipped"),
        }

    @staticmethod
    def _limit_charge_for(results: list[Message], result_store: Any) -> int:
        charged = [
            item
            for item in results
            if not ReportingCodeOpenAIResponses._is_non_executed_control_result(item)
        ]
        return Model._limit_charge_for(charged, result_store)

    @staticmethod
    def _budget_payload(used: int, limit: int) -> dict[str, int]:
        bounded_used = min(limit, max(0, used))
        return {
            "used": bounded_used,
            "limit": limit,
            "remaining": max(0, limit - bounded_used),
        }

    @classmethod
    def _attach_tool_budget(
        cls, messages: list[Message], *, used: int, limit: int
    ) -> None:
        budget = cls._budget_payload(used, limit)
        for message in messages:
            if not isinstance(message.content, str):
                continue
            try:
                payload = json.loads(message.content)
            except (TypeError, ValueError):
                try:
                    payload = ast.literal_eval(message.content)
                except (SyntaxError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            payload["budget"] = budget
            message.content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _is_redundant_visual_review(call: FunctionCall) -> bool:
        if call.function.name != "view_image" or not isinstance(call.arguments, Mapping):
            return False
        path = call.arguments.get("path")
        entrypoint = getattr(call.function, "entrypoint", None)
        owner = getattr(call.function, "source_toolkit", None) or getattr(
            entrypoint, "__self__", None
        )
        checker = getattr(owner, "has_current_visual_review", None)
        return isinstance(path, str) and callable(checker) and checker(path) is True

    def configure_code_run(
        self,
        tools: Any,
        *,
        max_model_requests: int,
        delivery_reserve: int | None = None,
    ) -> None:
        """绑定本任务实际 Function 范围；浅复制模型共享同一任务请求计数。"""
        names = [report_model_tool_name(tool) for tool in tools]
        if not names or any(not name for name in names) or len(set(names)) != len(names):
            raise _custom_protocol_error("Coding Agent 任务工具声明为空或无效。")
        if isinstance(max_model_requests, bool) or not isinstance(max_model_requests, int) or max_model_requests < 1:
            raise ValueError("max_model_requests must be a positive integer")
        self._code_tool_names = frozenset(names)
        self._code_request_budget = {"limit": max_model_requests, "used": 0}
        if delivery_reserve is not None and (
            isinstance(delivery_reserve, bool)
            or not isinstance(delivery_reserve, int)
            or delivery_reserve < 1
        ):
            raise ValueError("delivery_reserve must be a positive integer")
        self._code_delivery_reserve = (
            delivery_reserve if delivery_reserve is not None else _DELIVERY_TOOL_RESERVE
        )
        self._code_reserve_rejections = 0

    def _consume_code_request(self) -> None:
        budget = getattr(self, "_code_request_budget", None)
        if budget is None:
            return
        if budget["used"] >= budget["limit"]:
            raise ReportingError(
                "report_code_model_request_limit", "Coding Agent 模型请求次数已达上限。",
                details={"retryable": False, "modelRequestCount": budget["used"], "modelRequestLimit": budget["limit"]},
            )
        budget["used"] += 1

    def code_run_request_count(self) -> int:
        """返回当前 Coding task 已实际发出的模型请求数。"""
        budget = getattr(self, "_code_request_budget", None)
        return int(budget["used"]) if isinstance(budget, dict) else 0

    def _current_code_request(self) -> tuple[int, int]:
        budget = getattr(self, "_code_request_budget", None)
        if not isinstance(budget, dict):
            return 1, 1
        limit = int(budget["limit"])
        return min(limit, max(1, int(budget["used"]))), limit

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
                    "format": {
                        "type": "grammar",
                        "syntax": "lark",
                        "definition": _FREEFORM_TOOL_GRAMMAR,
                    },
                }
            )
        return result

    def get_request_params(
        self,
        messages: list[Message] | None = None,
        response_format: Any = None,
        tools: Any = None,
        tool_choice: Any = None,
        run_response: Any = None,
    ) -> dict[str, Any]:
        params = super().get_request_params(
            messages=messages,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            run_response=run_response,
        )
        params["parallel_tool_calls"] = False
        # OpenInference 以无参调用读取静态 invocation 参数；该调用不发模型请求，
        # 不能与 Agno 随后传入 messages/tools 的真实请求范围校验混为一谈。
        if (
            messages is None
            and response_format is None
            and tools is None
            and tool_choice is None
            and run_response is None
        ):
            return params
        formatted_tools = params.get("tools") or ()
        declarations = {tool.get("name"): tool.get("type") for tool in formatted_tools}
        expected = getattr(self, "_code_tool_names", None)
        if expected is not None and set(declarations) != expected:
            raise _custom_protocol_error("Coding Agent 请求工具与任务工具范围不一致。")
        if len(declarations) != len(formatted_tools) or any(
            not name or kind != ("custom" if name in FREEFORM_TOOL_ARGUMENTS else "function")
            for name, kind in declarations.items()
        ):
            raise _custom_protocol_error("Coding Agent 请求工具声明类型无效。")
        self._code_declared_tools = declarations
        if any(tool.get("type") == "custom" for tool in formatted_tools):
            params["tool_choice"] = "auto"
        elif tools and tool_choice is None:
            params["tool_choice"] = "auto"
        return params

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
        decision = current_reporting_thinking_decision()
        if decision is not None:
            base_profile = reporting_thinking_profile_from_model(self)
            profile = (
                ReportingThinkingProfile.on(
                    reasoning_effort=decision.reasoning_effort,
                    thinking_budget=decision.thinking_budget,
                    temperature=base_profile.temperature,
                )
                if decision.enabled
                and decision.reasoning_effort is not None
                and decision.thinking_budget > 0
                else ReportingThinkingProfile.off(temperature=base_profile.temperature)
            )
            # Responses 的显式 reasoning 字典不能覆盖本轮策略或保留旧 effort。
            request_model.reasoning = None
            apply_reporting_thinking_profile(request_model, profile)
        return request_model

    def _project(
        self, messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> list[Message]:
        response_format = kwargs.get("response_format", args[1] if len(args) > 1 else None)
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        # CodeMode 使用任务签发的 Function；父阶段白名单仅适用于外层模型。
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
            item
            for item in output
            if _field(item, "type") in {"custom_tool_call", "function_call"}
        ]
        declarations = getattr(self, "_code_declared_tools", None)
        identities: set[str] = set()
        for item in actionable:
            name = _field(item, "name")
            kind = "custom" if _field(item, "type") == "custom_tool_call" else "function"
            if declarations is not None and declarations.get(name) != kind:
                raise _custom_protocol_error("Coding Agent 返回未声明或类型不匹配的工具调用。")
            call_identities = {_required_id(item, "id"), _required_id(item, "call_id")}
            if identities.intersection(call_identities):
                raise _custom_protocol_error("Coding Agent 工具调用身份重复。")
            identities.update(call_identities)
        if not actionable and _contains_textual_tool_marker(output):
            raise _custom_protocol_error("Coding Agent 将工具调用写入了 assistant 正文。")
        custom_calls = {
            _field(item, "id"): _synthetic_custom_call(item)
            for item in actionable
            if _field(item, "type") == "custom_tool_call"
        }
        parsed = super()._parse_provider_response(response, **kwargs)
        if not custom_calls:
            return parsed
        function_calls = iter(parsed.tool_calls or ())
        parsed.content = None
        parsed.tool_calls = [
            custom_calls[_field(item, "id")]
            if _field(item, "type") == "custom_tool_call"
            else next(function_calls)
            for item in actionable
        ]
        parsed.extra = parsed.extra or {}
        parsed.extra["tool_call_ids"] = [call["call_id"] for call in parsed.tool_calls]
        return parsed

    def _ordered_code_calls(
        self,
        function_calls: list[FunctionCall],
        results: list[Message],
        current_count: int,
        function_call_limit: int | None,
        result_store: Any,
    ) -> Iterator[tuple[FunctionCall, int]]:
        """保持 provider 顺序；失败或签发后为剩余调用补齐未执行回执。"""
        stopped = False
        for call in function_calls:
            tool_name = call.function.name
            if stopped:
                skipped = Message(
                    role=self.tool_message_role,
                    tool_call_id=call.call_id,
                    tool_name=call.function.name,
                    tool_args=call.arguments,
                    tool_call_error=True,
                    content=json.dumps({
                        "ok": False,
                        "status": "skipped",
                        "code": "report_code_batch_stopped",
                        "message": "前序工具失败或任务已提交；本次调用未执行。",
                    }, ensure_ascii=False),
                )
                if function_call_limit is not None:
                    self._attach_tool_budget(
                        [skipped], used=current_count, limit=function_call_limit
                    )
                results.append(skipped)
                logger.bind(
                    reporting_progress="code_tool",
                    tool_name=tool_name,
                    status="skipped",
                    code="report_code_batch_stopped",
                ).info("report_code_tool_progress tool_name={} status=skipped", tool_name)
                continue
            if (
                getattr(self, "_code_tool_names", None) is not None
                and function_call_limit is not None
                and (
                    tool_name not in _DELIVERY_TOOL_NAMES
                    or self._is_redundant_visual_review(call)
                )
                and current_count
                >= function_call_limit
                - getattr(self, "_code_delivery_reserve", _DELIVERY_TOOL_RESERVE)
            ):
                self._code_reserve_rejections = (
                    getattr(self, "_code_reserve_rejections", 0) + 1
                )
                escalated = self._code_reserve_rejections >= 2
                rejected = Message(
                    role=self.tool_message_role,
                    tool_call_id=call.call_id,
                    tool_name=tool_name,
                    tool_args=call.arguments,
                    tool_call_error=True,
                    content=json.dumps({
                        "ok": False,
                        "status": "rejected",
                        "code": "report_code_delivery_budget_reserved",
                        "message": (
                            "剩余额度仅供交付；请立即调用 write_script、run_script、"
                            "view_image 或 submit_script，不要再调用探索工具。"
                            if escalated
                            else "剩余工具调用额度仅供正式脚本写入、运行、审查和提交。"
                        ),
                        "details": {
                            "used": current_count,
                            "limit": function_call_limit,
                            "requiredNextTools": sorted(_DELIVERY_TOOL_NAMES),
                            "escalated": escalated,
                        },
                    }, ensure_ascii=False),
                )
                charged_count = current_count + (1 if escalated else 0)
                self._attach_tool_budget(
                    [rejected], used=charged_count, limit=function_call_limit
                )
                results.append(rejected)
                stopped = True
                logger.bind(
                    reporting_progress="code_tool",
                    tool_name=tool_name,
                    status="rejected",
                    code="report_code_delivery_budget_reserved",
                ).info("report_code_tool_progress tool_name={} status=rejected", tool_name)
                continue
            start = len(results)
            logger.bind(
                reporting_progress="code_tool",
                tool_name=tool_name,
                status="started",
            ).info("report_code_tool_progress tool_name={} status=started", tool_name)
            yield call, current_count
            completed = results[start:]
            current_count += self._limit_charge_for(completed, result_store)
            if function_call_limit is not None:
                if isinstance(call.result, dict):
                    call.result["budget"] = self._budget_payload(
                        current_count, function_call_limit
                    )
                self._attach_tool_budget(
                    completed, used=current_count, limit=function_call_limit
                )
            stopped = any(item.stop_after_tool_call or item.tool_call_error for item in completed)
            stopped = stopped or (
                isinstance(call.result, Mapping) and call.result.get("ok") is False
            )
            result = call.result if isinstance(call.result, Mapping) else {}
            status = (
                "rejected"
                if result.get("ok") is False
                else "failed"
                if any(item.tool_call_error for item in completed)
                else "completed"
            )
            progress: dict[str, Any] = {
                "reporting_progress": "code_tool",
                "tool_name": tool_name,
                "status": status,
            }
            path = result.get("path") or result.get("sourcePath")
            receipt = result.get("executionReceipt")
            source_file = receipt.get("sourceFile") if isinstance(receipt, Mapping) else None
            if not isinstance(path, str) and isinstance(source_file, Mapping):
                path = source_file.get("path")
            if isinstance(path, str):
                progress["path"] = path
            code = result.get("code")
            if isinstance(code, str):
                progress["code"] = code
            logger.bind(**progress).info(
                "report_code_tool_progress tool_name={} status={}", tool_name, status
            )

    def run_function_calls(
        self,
        function_calls: list[FunctionCall],
        function_call_results: list[Message],
        additional_input: list[Message] | None = None,
        current_function_call_count: int = 0,
        function_call_limit: int | None = None,
        result_store: Any = None,
    ) -> Iterator[Any]:
        for call, count in self._ordered_code_calls(
            function_calls,
            function_call_results,
            current_function_call_count,
            function_call_limit,
            result_store,
        ):
            yield from super().run_function_calls(
                [call], function_call_results,
                current_function_call_count=count,
                function_call_limit=function_call_limit,
                result_store=result_store,
            )
        if additional_input:
            function_call_results.extend(additional_input)

    async def arun_function_calls(
        self,
        function_calls: list[FunctionCall],
        function_call_results: list[Message],
        additional_input: list[Message] | None = None,
        current_function_call_count: int = 0,
        function_call_limit: int | None = None,
        skip_pause_check: bool = False,
        result_store: Any = None,
    ) -> AsyncIterator[Any]:
        # Agno 3.0.9 会 gather 一批调用；逐个委托以保留原生 hooks、计数和取消语义。
        for call, count in self._ordered_code_calls(
            function_calls,
            function_call_results,
            current_function_call_count,
            function_call_limit,
            result_store,
        ):
            async for event in super().arun_function_calls(
                [call], function_call_results,
                current_function_call_count=count,
                function_call_limit=function_call_limit,
                skip_pause_check=skip_pause_check,
                result_store=result_store,
            ):
                yield event
        if additional_input:
            function_call_results.extend(additional_input)

    def _format_messages(
        self,
        messages: list[Message],
        compress_tool_results: bool = False,
        tools: Any = None,
    ) -> list[Any]:
        normalized_messages = reformat_tool_call_ids(
            normalize_tool_messages(messages), provider="openai_responses"
        )
        original_calls = [call for message in messages for call in message.tool_calls or ()]
        normalized_calls = [
            call for message in normalized_messages for call in message.tool_calls or ()
        ]
        if len(original_calls) != len(normalized_calls):
            raise _custom_protocol_error("Coding Agent 工具重放调用数量不一致。")

        known_call_ids: set[str] = set()
        identity_owners: dict[str, int] = {}
        custom_calls: dict[str, dict[str, Any]] = {}
        custom_replays: list[dict[str, Any]] = []
        for index, (original, normalized) in enumerate(
            zip(original_calls, normalized_calls, strict=True)
        ):
            original_identities = {
                identity
                for identity in (_field(original, "id"), _field(original, "call_id"))
                if isinstance(identity, str) and identity
            }
            for identity in original_identities:
                owner = identity_owners.get(identity)
                if owner is not None and owner != index:
                    raise _custom_protocol_error("Coding Agent 工具调用身份重复。")
                identity_owners[identity] = index
            identities = {
                identity
                for identity in (_field(normalized, "id"), _field(normalized, "call_id"))
                if isinstance(identity, str) and identity
            }
            for identity in identities:
                owner = identity_owners.get(identity)
                if owner is not None and owner != index:
                    raise _custom_protocol_error("Coding Agent 工具调用身份重复。")
                identity_owners[identity] = index
            known_call_ids.update(identities)

            custom = _validated_custom_replay_call(original)
            function = _field(original, "function")
            name = _field(function, "name")
            if custom is None:
                if name in FREEFORM_TOOL_ARGUMENTS:
                    raise _custom_protocol_error("Coding Agent custom 工具调用类型不匹配。")
                continue
            custom_replays.append(custom)
            for identity in identities:
                custom_calls[identity] = custom

        custom_result_counts: dict[str, int] = {}
        for message in normalized_messages:
            if message.role != "tool":
                continue
            result_identity = message.tool_call_id
            if not isinstance(result_identity, str) or result_identity not in known_call_ids:
                raise _custom_protocol_error("Coding Agent 工具结果缺少对应调用。")
            custom = custom_calls.get(result_identity)
            if custom is not None:
                if message.tool_name != custom["name"]:
                    raise _custom_protocol_error("Coding Agent custom 工具结果与调用不匹配。")
                call_id = custom["call_id"]
                custom_result_counts[call_id] = custom_result_counts.get(call_id, 0) + 1
                if custom_result_counts[call_id] > 1:
                    raise _custom_protocol_error("Coding Agent custom 工具调用存在重复结果。")
            elif message.tool_name in FREEFORM_TOOL_ARGUMENTS:
                raise _custom_protocol_error("Coding Agent custom 工具结果类型不匹配。")
        if any(
            custom_result_counts.get(custom["call_id"], 0) != 1
            for custom in custom_replays
        ):
            raise _custom_protocol_error("Coding Agent custom 工具调用缺少对应结果。")

        formatted = super()._format_messages(messages, compress_tool_results, tools)
        for index, item in enumerate(formatted):
            if not isinstance(item, dict) or item.get("type") not in {
                "function_call",
                "function_call_output",
            }:
                continue
            if item["type"] == "function_call":
                custom = custom_calls.get(str(item.get("call_id") or "")) or custom_calls.get(
                    str(item.get("id") or "")
                )
                if custom is None:
                    continue
                formatted[index] = {
                    "type": "custom_tool_call",
                    "id": custom["id"],
                    "call_id": custom["call_id"],
                    "name": custom["name"],
                    "input": custom["raw_input"],
                    "status": "completed",
                }
            else:
                custom = custom_calls.get(str(item.get("call_id") or ""))
                if custom is None:
                    continue
                formatted[index] = {
                    "type": "custom_tool_call_output",
                    "call_id": custom["call_id"],
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
        messages = self._project(messages, args, kwargs)
        self._consume_code_request()
        try:
            return super().invoke(messages, *args, **kwargs)
        except Exception as error:
            self._raise_stable_custom_error(error)
            raise

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        messages = phase_filtered_report_messages(messages)
        messages = self._project(messages, args, kwargs)
        self._consume_code_request()
        request_index, request_limit = self._current_code_request()
        started_at = perf_counter()
        logger.bind(
            reporting_progress="code_model_request",
            model_id=self.id,
            request_index=request_index,
            request_limit=request_limit,
            duration_ms=0,
            status="started",
        ).info(
            "report_code_model_request_started model_id={} request_index={} request_limit={}",
            self.id,
            request_index,
            request_limit,
        )
        try:
            response = await super().ainvoke(messages, *args, **kwargs)
        except Exception as error:
            logger.bind(
                reporting_progress="code_model_request",
                model_id=self.id,
                request_index=request_index,
                request_limit=request_limit,
                duration_ms=elapsed_ms(started_at),
                status="failed",
            ).warning(
                "report_code_model_request_completed model_id={} request_index={} "
                "request_limit={} status=failed",
                self.id,
                request_index,
                request_limit,
            )
            self._raise_stable_custom_error(error)
            raise
        logger.bind(
            reporting_progress="code_model_request",
            model_id=self.id,
            request_index=request_index,
            request_limit=request_limit,
            duration_ms=elapsed_ms(started_at),
            status="completed",
        ).info(
            "report_code_model_request_completed model_id={} request_index={} "
            "request_limit={} status=completed",
            self.id,
            request_index,
            request_limit,
        )
        return response

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
