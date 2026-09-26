from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextvars import ContextVar
from copy import copy, deepcopy
from time import perf_counter
from types import MappingProxyType
from typing import Any
from urllib.parse import urlsplit

from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIResponses
from agno.models.response import ModelResponse
from agno.tools.function import FunctionCall
from agno.utils.message import normalize_tool_messages, reformat_tool_call_ids
from loguru import logger
from openai.types.responses import ResponseReasoningItem

from ...context_management import (
    TASK_EXECUTION_CONTEXT_TOKEN_LIMIT,
    TASK_EXECUTION_OUTPUT_TOKEN_RESERVE,
    TaskExecutionContextProjector,
)
from ...integrations.model_config import is_dashscope_endpoint
from ...runtime.observability import duration_ms as elapsed_ms
from ..model_policy import (
    current_reporting_thinking_decision,
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
from .budget import CodeBudget
from .edit_patch import EDIT_PATCH_GRAMMAR
from .metrics import bounded_failure_diagnostics

FREEFORM_TOOL_ARGUMENTS: Mapping[str, str] = MappingProxyType(
    {"write_script": "source", "run": "code", "edit_script": "patch"}
)

_CUSTOM_TOOL_PROTOCOL_ERROR = "report_code_custom_tool_protocol_error"
_VISUALIZATION_BUDGET_GATE_FORCED_SUBMIT = "report_code_visual_budget_gate_forced_submit"
_VISUALIZATION_REVIEW_ROUNDS_GATE = "report_code_visual_review_rounds_exhausted"
# provider grammar 退化时任务集内 FREEFORM 工具可能以 function 形态返回；该调用不执行，
# 只补未执行回执引导模型改用 custom 工具重发。超过上限说明 provider 持续退化，保持
# fail-closed。
_WIRE_SHAPE_REJECTION_LIMIT = 3
# provider 以 function 形态返回、已补未执行回执的 FREEFORM 调用在历史中的标记。
_WIRE_REJECTED_FUNCTION = "function_rejected"
# 用合法代码首行固定 raw input 形状，避免任意文本 grammar 接受 JSON 包装。
_FREEFORM_TOOL_GRAMMARS: Mapping[str, str] = MappingProxyType({
    "write_script": 'start: "# Python" NEWLINE SOURCE\n'
    'NEWLINE: /\\r?\\n/\nSOURCE: /[\\s\\S]+/',
    "run": 'start: ("# Python" | "%%bash") NEWLINE SOURCE\n'
    'NEWLINE: /\\r?\\n/\nSOURCE: /[\\s\\S]+/',
    "edit_script": EDIT_PATCH_GRAMMAR,
})
_STREAMING_UNSUPPORTED = "report_code_streaming_unsupported"
_TEXTUAL_TOOL_MARKERS = (
    "<|recipient=",
    "<|recipient|>",
    "<|tool_call=",
    "<|tool_call|>",
    "<｜DSML｜tool_calls>",
    "<｜DSML｜invoke",
    "```run",
    "```write_script",
    "```edit_script",
)
_PROFILE_RECEIPT_PROJECTION_LIMIT = 100
_PROFILE_QUERY_IDENTITY_MAX_LENGTH = 256
_DELIVERY_TOOL_NAMES = frozenset(
    {"write_script", "edit_script", "run_script", "submit_script", "view_image"}
)
_DELIVERY_TOOL_CANDIDATES = _DELIVERY_TOOL_NAMES | {"read_script"}
# write_script and edit_script are alternatives; retain the existing baseline
# reserve so adding the local-edit path does not reduce exploration capacity.
_DELIVERY_TOOL_RESERVE = 4
# 附加 budget 字段前的防御性上限：跳过明显不是正常工具结果的超大内容，且不让
# 附加后的消息无界增长（诊断字段自身已按硬上限精确塞满，这里再留一段宽松余量）。
_ATTACH_BUDGET_MAX_CONTENT_CHARS = 200_000


def _responses_thinking_extra_body(
    extra_body: Mapping[str, Any] | None,
    *,
    endpoint: str | None,
    enabled: bool,
) -> dict[str, Any] | None:
    """按 Responses provider 的公开契约投影思考开关。"""

    body = dict(extra_body or {})
    body.pop("thinking_budget", None)
    template_kwargs = body.get("chat_template_kwargs")
    if isinstance(template_kwargs, Mapping):
        body["chat_template_kwargs"] = {
            **template_kwargs,
            "enable_thinking": enabled,
        }
    elif is_dashscope_endpoint(endpoint):
        body["enable_thinking"] = enabled
    else:
        body.pop("enable_thinking", None)
    return body or None
_ATTACH_BUDGET_MAX_ENCODED_BYTES = 16 * 1024
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


def _unresolved_failure_call_ids(state: Mapping[str, Any]) -> frozenset[str]:
    """交付状态中未解决失败的调用身份；压缩时保护其所在轮次不被删除。"""

    failure = state.get("lastFailure")
    if not isinstance(failure, Mapping):
        return frozenset()
    call_id = failure.get("callId")
    if not isinstance(call_id, str) or not call_id:
        return frozenset()
    return frozenset({call_id})


def _read_script_result_stale(message: Message, current_sha: str) -> bool:
    try:
        payload = json.loads(str(message.content or ""))
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    sha = payload.get("sha256")
    return isinstance(sha, str) and bool(sha) and sha != current_sha


def _filter_read_script_rounds(
    messages: list[Message], state: Mapping[str, Any]
) -> tuple[list[Message], frozenset[str]]:
    """丢弃结果 SHA 已落后于当前脚本的 read_script 单调用轮次。

    返回过滤后的消息与仍代表当前源码身份的 read_script 调用身份；后者需要
    在压缩时受保护，否则 rebase 只保留最近若干轮时会丢失模型应对照的源码 SHA。
    多调用批次里的 read_script 有意不参与本过滤：批次内其他调用的结果不携带
    源码 SHA，无法证明整批结果全部过时，整轮丢弃会破坏 Responses 调用链；
    这类轮次交给 incomplete batch 保护与最近轮保留兜底，不是遗漏。
    """

    script = state.get("script")
    current_sha = script.get("sha256") if isinstance(script, Mapping) else None
    if not isinstance(current_sha, str) or not current_sha:
        return messages, frozenset()
    kept: list[Message] = []
    current_call_ids: set[str] = set()
    index = 0
    while index < len(messages):
        message = messages[index]
        calls = [call for call in (message.tool_calls or ()) if isinstance(call, dict)]
        function = calls[0].get("function") if len(calls) == 1 else None
        if (
            message.role in {"assistant", "model"}
            and isinstance(function, dict)
            and function.get("name") == "read_script"
        ):
            identities = {
                value
                for key in ("id", "call_id")
                if isinstance(value := calls[0].get(key), str)
            }
            results: list[Message] = []
            lookahead = index + 1
            while lookahead < len(messages) and messages[lookahead].role == "tool":
                if messages[lookahead].tool_call_id in identities:
                    results.append(messages[lookahead])
                lookahead += 1
            # 没有完整结果的批次交给投影层的 incomplete batch 保护；只有能确定
            # 全部结果都已过时时才整轮丢弃，避免破坏 Responses 调用链。
            if results and all(
                _read_script_result_stale(result, current_sha) for result in results
            ):
                index = lookahead
                continue
            if results and any(
                not _read_script_result_stale(result, current_sha) for result in results
            ):
                current_call_ids.update(identities)
        kept.append(message)
        index += 1
    return kept, frozenset(current_call_ids)

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


def _normalize_provider_custom_input(raw_input: str, tool_name: str) -> tuple[str, bool]:
    """兼容 provider 对 native custom input 偶发添加的单层 data 信封。"""
    if not raw_input.lstrip().startswith("{"):
        return raw_input, False
    try:
        envelope = json.loads(raw_input)
    except (TypeError, ValueError):
        return raw_input, False
    if not isinstance(envelope, dict) or set(envelope) != {"data"}:
        return raw_input, False
    source = envelope["data"]
    prefixes = _custom_input_prefixes(tool_name)
    if not isinstance(source, str) or not source.startswith(prefixes):
        return raw_input, False
    return source, True


def _custom_input_prefixes(tool_name: str) -> tuple[str, ...]:
    # 与 _FREEFORM_TOOL_GRAMMARS 一致：只有 run 接受 %%bash cell；write_script 的
    # 正式脚本必须是 Python，%%bash 首行不能被当作协议正确输入或信封解封目标。
    if tool_name == "edit_script":
        return ("*** Begin Edit\n", "*** Begin Patch\n")
    if tool_name == "run":
        return ("# Python\n", "# Python\r\n", "%%bash\n", "%%bash\r\n")
    return ("# Python\n", "# Python\r\n")


def _is_wire_shaped_freedom_call(name: Any, kind: str, task_tools: Any) -> bool:
    """任务集内 FREEFORM 工具被 provider 以 function 形态返回（grammar 退化）。

    按 AGENTS.md，只有 provider 返回的结构化 custom_tool_call 可执行，write_script/run
    等不得降级为 JSON function tool。因此这里只做识别：该调用保持 provider 原样、
    不改写、不执行，由调用循环补未执行回执，引导模型改用原生 custom 工具重发。
    """
    return (
        isinstance(name, str)
        and kind == "function"
        and name in FREEFORM_TOOL_ARGUMENTS
        and (task_tools is None or name in task_tools)
    )


def _synthetic_custom_call(item: Any) -> dict[str, Any]:
    # 只接受 provider 的结构化 custom_tool_call。单层 data 信封是已观测到的
    # provider 兼容形状；正文、嵌套信封和其他 JSON 均不在这里解释或执行。
    name = _field(item, "name")
    raw_input = _field(item, "input")
    if name not in FREEFORM_TOOL_ARGUMENTS or not isinstance(raw_input, str) or not raw_input:
        raise _custom_protocol_error("Coding Agent custom 工具调用无效。")
    provider_input_bytes = len(raw_input.encode("utf-8"))
    # 只解开已观测到的单层 data 信封；补丁内容原样进入格式、SHA 和精确匹配校验。
    raw_input, normalized = _normalize_provider_custom_input(raw_input, name)
    if normalized:
        logger.warning(
            "report_code_custom_input_normalized tool_name={} envelope_bytes={}",
            name,
            provider_input_bytes,
        )
    item_id = _required_id(item, "id")
    call_id = _required_id(item, "call_id")
    provider_data = {"reporting_wire_type": "custom", "raw_input": raw_input}
    if normalized:
        provider_data["provider_input_normalized"] = "data_envelope"
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
        "provider_data": provider_data,
    }


def _validated_custom_replay_call(call: Any) -> dict[str, Any] | None:
    # 回放还原 custom input；同时校验内部参数与原文一致，防止历史被篡改。
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


_TRACEBACK_FRAME = re.compile(
    r'File "([^"]+)", line (\d+), in (\S+)(?:\r?\n[ \t]+(\S[^\r\n]*))?'
)
_LIBRARY_FRAME_MARKERS = ("site-packages", "dist-packages", "/lib/python", "<frozen")


def _run_failure_signature(failure: Mapping[str, Any]) -> tuple[str, str] | None:
    """(errorType, 所属函数 + 出错语句)；只有脚本运行时异常才有签名。

    输出校验、预检拒绝等没有异常栈的失败不计入"同签名连续失败"。出错语句按
    源码文本而非行号比较：修复后行号漂移仍识别为同一失败，同一函数内不同语句
    的失败（模型在推进）则视为不同签名。
    """

    details = failure.get("details")
    details = details if isinstance(details, Mapping) else {}
    error_type = details.get("errorType")
    frames: list[tuple[str, str, str, str]] = []
    for key in ("traceback", "stderr", "output", "stdout"):
        text = details.get(key)
        if isinstance(text, str) and text:
            frames = _TRACEBACK_FRAME.findall(text)
            if frames:
                break
    script_frames = [
        frame for frame in frames
        if not any(marker in frame[0] for marker in _LIBRARY_FRAME_MARKERS)
    ]
    if not isinstance(error_type, str) or not error_type or not script_frames:
        return None
    _path, line, function, statement = script_frames[-1]
    location = " ".join(statement.split())[:160] if statement else f"line:{line}"
    return error_type[:128], f"{function[:96]}|{location}"


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
        return CodeBudget.exempt(payload)

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
        return CodeBudget.snapshot(used, limit)

    @classmethod
    def _attach_tool_budget(
        cls, messages: list[Message], *, used: int, limit: int
    ) -> None:
        budget = cls._budget_payload(used, limit)
        for message in messages:
            content = message.content
            if not isinstance(content, str) or len(content) > _ATTACH_BUDGET_MAX_CONTENT_CHARS:
                continue
            try:
                payload = json.loads(content)
                use_json = True
            except (TypeError, ValueError, RecursionError, MemoryError):
                try:
                    payload = ast.literal_eval(content)
                # 深嵌套或畸形文本可能让 ast.literal_eval 抛出比 SyntaxError/ValueError
                # 更广的异常；宁可跳过附加 budget，也不能让协议层崩溃。
                except (SyntaxError, ValueError, RecursionError, MemoryError, TypeError):
                    continue
                # Agno 对未包装为 ToolResult 的普通 dict 返回值默认走
                # str(function_call.result)（Python repr：单引号、True/False/None），
                # 不是 JSON；这是 Reporting 工具结果最常见的落地格式。写回时必须
                # 保持原有语法，否则把 'True' 变成 true 之类的改写会让任何按原始
                # 格式重新解析该内容的下游（包括测试对 wire 内容的还原）出错，
                # 即使模型本身能读懂两种格式。
                use_json = False
            if not isinstance(payload, dict):
                continue
            payload["budget"] = budget
            try:
                encoded = (
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                    if use_json else repr(payload)
                )
                encoded_size = len(encoded.encode("utf-8"))
            except (TypeError, ValueError, UnicodeError, RecursionError, MemoryError):
                continue
            # 诊断字段已按各自硬上限精确塞满；附加 budget 不得让消息整体突破
            # 一个宽松的兜底上限——找不到安全空间就放弃附加，而不是无界增长。
            if encoded_size > _ATTACH_BUDGET_MAX_ENCODED_BYTES:
                continue
            message.content = encoded

    def _is_redundant_visual_review(self, call: FunctionCall) -> bool:
        if call.function.name != "view_image" or not isinstance(call.arguments, Mapping):
            return False
        checker = getattr(self, "_code_redundant_review_check", None)
        if not callable(checker):
            return False
        raw_paths: list[Any] = []
        path = call.arguments.get("path")
        if isinstance(path, str) and path:
            raw_paths.append(path)
        paths = call.arguments.get("paths")
        if isinstance(paths, list):
            raw_paths.extend(item for item in paths if isinstance(item, str) and item)
        if not raw_paths:
            return False
        return all(checker(item) is True for item in raw_paths)

    def configure_code_run(
        self,
        tools: Any,
        *,
        max_model_requests: int,
        delivery_reserve: int | None = None,
        redundant_call_check: Callable[[str], bool] | None = None,
        delivery_state_reader: Callable[[], dict[str, Any]] | None = None,
        tool_call_limit: int | None = None,
        visual_budget_gate_safety_margin: int = 2,
        no_progress_request_limit: int | None = None,
        repeated_run_failure_limit: int | None = None,
        initial_run_succeeded: bool = False,
    ) -> None:
        """绑定本任务实际 Function 范围；浅复制模型共享同一任务请求计数。"""
        names = [report_model_tool_name(tool) for tool in tools]
        if not names or any(not name for name in names) or len(set(names)) != len(names):
            raise _custom_protocol_error("Coding Agent 任务工具声明为空或无效。")
        if isinstance(max_model_requests, bool) or not isinstance(max_model_requests, int) or max_model_requests < 1:
            raise ValueError("max_model_requests must be a positive integer")
        self._code_tool_names = frozenset(names)
        if delivery_reserve is not None and (
            isinstance(delivery_reserve, bool)
            or not isinstance(delivery_reserve, int)
            or delivery_reserve < 1
        ):
            raise ValueError("delivery_reserve must be a positive integer")
        if tool_call_limit is not None and (
            isinstance(tool_call_limit, bool)
            or not isinstance(tool_call_limit, int)
            or tool_call_limit < 1
        ):
            raise ValueError("tool_call_limit must be a positive integer")
        if (
            isinstance(visual_budget_gate_safety_margin, bool)
            or not isinstance(visual_budget_gate_safety_margin, int)
            or visual_budget_gate_safety_margin < 0
        ):
            raise ValueError("visual_budget_gate_safety_margin must be a non-negative integer")
        self._code_budget = CodeBudget(
            request_limit=max_model_requests,
            reserve=delivery_reserve if delivery_reserve is not None else _DELIVERY_TOOL_RESERVE,
        )
        self._code_tool_call_limit = tool_call_limit
        self._code_visual_budget_gate_safety_margin = visual_budget_gate_safety_margin
        self._code_redundant_review_check = redundant_call_check
        self._code_delivery_state_reader = delivery_state_reader
        self._code_stage_mismatch_names: frozenset[str] = frozenset()
        self._code_wire_rejected_call_ids: frozenset[str] = frozenset()
        self._code_request_metrics: list[dict[str, Any]] = []
        for name, value in (
            ("no_progress_request_limit", no_progress_request_limit),
            ("repeated_run_failure_limit", repeated_run_failure_limit),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer")
        self._code_no_progress_request_limit = no_progress_request_limit
        self._code_repeated_run_failure_limit = repeated_run_failure_limit
        # 每次请求在 copy(self) 上执行工具循环；进展状态必须放在共享可变对象中，
        # 否则续跑 arun 时会从原对象读到过期值。宿主预执行成功同样计为进展。
        self._code_progress: dict[str, Any] = {
            "runSucceeded": bool(initial_run_succeeded),
            "signature": None,
            "streak": 0,
        }

    def _record_run_outcome(
        self, succeeded: bool, failure: Mapping[str, Any] | None
    ) -> None:
        """记录 run_script 进展；只使用宿主已有回执，不新增模型请求。"""

        progress = getattr(self, "_code_progress", None)
        if not isinstance(progress, dict):
            return
        if succeeded:
            progress.update(runSucceeded=True, signature=None, streak=0)
            return
        signature = _run_failure_signature(failure or {})
        if signature is None:
            progress.update(signature=None, streak=0)
        elif signature == progress.get("signature"):
            progress["streak"] = int(progress.get("streak") or 0) + 1
        else:
            progress.update(signature=signature, streak=1)

    def _check_code_progress(self, budget: CodeBudget) -> None:
        request_limit = getattr(self, "_code_no_progress_request_limit", None)
        repeat_limit = getattr(self, "_code_repeated_run_failure_limit", None)
        progress = getattr(self, "_code_progress", None)
        if not isinstance(progress, dict):
            return
        streak = int(progress.get("streak") or 0)
        reason: str | None = None
        if (
            request_limit is not None
            and not progress.get("runSucceeded")
            and budget.requests >= request_limit
        ):
            reason = "no_successful_run"
        elif repeat_limit is not None and streak >= repeat_limit:
            reason = "repeated_run_failure"
        if reason is None:
            return
        signature = progress.get("signature")
        raise ReportingError(
            "report_code_no_progress",
            "Coding Agent 长时间没有进展，提前结束本次尝试并交由 fresh attempt 重来。",
            details={
                "retryable": False,
                "recovery": "retry_then_degrade",
                "reason": reason,
                "modelRequestCount": budget.requests,
                "noProgressRequestLimit": request_limit,
                "repeatedRunFailureLimit": repeat_limit,
                "runFailureStreak": streak,
                **(
                    {"errorType": signature[0], "function": signature[1]}
                    if isinstance(signature, tuple)
                    else {}
                ),
            },
        )

    def _consume_code_request(self) -> None:
        budget = getattr(self, "_code_budget", None)
        if budget is None:
            return
        self._check_code_progress(budget)
        if not budget.consume_request():
            raise ReportingError(
                "report_code_model_request_limit", "Coding Agent 模型请求次数已达上限。",
                details={"retryable": False, "recovery": "retry_then_degrade", "modelRequestCount": budget.requests, "modelRequestLimit": budget.request_limit},
            )

    def code_run_request_count(self) -> int:
        """返回当前 Coding task 已实际发出的模型请求数。"""
        budget = getattr(self, "_code_budget", None)
        return budget.requests if budget is not None else 0

    def code_run_request_metrics(self) -> list[dict[str, Any]]:
        """返回当前任务逐次 provider 请求的有界观测，不把缺失 usage 记为零。"""

        return [dict(item) for item in getattr(self, "_code_request_metrics", ())]

    @staticmethod
    def _response_tool_names(response: Any) -> list[str]:
        names: list[str] = []
        for call in ReportingCodeOpenAIResponses._response_tool_calls(response):
            if call["name"] not in names:
                names.append(call["name"])
        return names

    @staticmethod
    def _response_tool_calls(response: Any) -> list[dict[str, str]]:
        calls: list[dict[str, str]] = []
        for call in getattr(response, "tool_calls", None) or ():
            function = _field(call, "function")
            name = _field(function, "name") if function is not None else _field(call, "name")
            call_id = _field(call, "call_id") or _field(call, "id")
            if isinstance(call_id, str) and call_id and isinstance(name, str) and name:
                calls.append({"id": call_id[:256], "name": name[:128]})
        return calls

    @staticmethod
    def _request_fingerprint(value: Any) -> tuple[str, int | str]:
        if value is None or value == [] or value == {}:
            return "unknown", "unknown"
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError):
            return "unknown", "unknown"
        return hashlib.sha256(encoded).hexdigest(), len(encoded)

    def _request_params_observation(
        self,
        params: Mapping[str, Any],
        messages: list[Message] | None,
        tools: Any = None,
    ) -> dict[str, Any]:
        reasoning = params.get("reasoning")
        extra_body = params.get("extra_body")
        template_kwargs = (
            extra_body.get("chat_template_kwargs")
            if isinstance(extra_body, Mapping)
            else None
        )
        if isinstance(extra_body, Mapping) and isinstance(
            extra_body.get("enable_thinking"), bool
        ):
            enable_thinking = extra_body["enable_thinking"]
            enable_thinking_location = "top_level"
        elif isinstance(template_kwargs, Mapping) and isinstance(
            template_kwargs.get("enable_thinking"), bool
        ):
            enable_thinking = template_kwargs["enable_thinking"]
            enable_thinking_location = "chat_template_kwargs"
        else:
            enable_thinking = "unknown"
            enable_thinking_location = "omitted"
        tool_choice = params.get("tool_choice", "unknown")
        if isinstance(tool_choice, Mapping):
            choice_type = tool_choice.get("type")
            choice_name = tool_choice.get("name")
            tool_choice = (
                f"{choice_type}:{choice_name}"
                if isinstance(choice_type, str) and isinstance(choice_name, str)
                else "structured"
            )
        system_prefix: list[dict[str, Any]] = []
        formatted_messages = (
            self._format_messages(messages, tools=tools) if messages is not None else ()
        )
        for item in formatted_messages:
            if not isinstance(item, Mapping) or item.get("role") != self.role_map["system"]:
                break
            system_prefix.append(dict(item))
        system_sha256, system_bytes = self._request_fingerprint(system_prefix)
        tools_sha256, tools_bytes = self._request_fingerprint(params.get("tools"))
        text = params.get("text")
        schema = text.get("format") if isinstance(text, Mapping) else None
        schema_sha256, schema_bytes = self._request_fingerprint(schema)
        return {
            "model": params.get("model") or "unknown",
            "reasoningEffort": (
                reasoning.get("effort")
                if isinstance(reasoning, Mapping)
                else "unknown"
            ),
            "reasoningSummary": (
                reasoning.get("summary")
                if isinstance(reasoning, Mapping) and reasoning.get("summary")
                else "unknown"
            ),
            "enableThinking": enable_thinking,
            "enableThinkingLocation": enable_thinking_location,
            "maxOutputTokens": (
                params.get("max_output_tokens")
                if isinstance(params.get("max_output_tokens"), int)
                and not isinstance(params.get("max_output_tokens"), bool)
                else "unknown"
            ),
            "parallelToolCalls": params.get("parallel_tool_calls", "unknown"),
            "toolChoice": tool_choice,
            "extraBodyKeys": sorted(extra_body)
            if isinstance(extra_body, Mapping)
            else [],
            "systemPrefixSha256": system_sha256,
            "systemPrefixBytes": system_bytes,
            "toolDeclarationsSha256": tools_sha256,
            "toolDeclarationsBytes": tools_bytes,
            "schemaSha256": schema_sha256,
            "schemaBytes": schema_bytes,
        }

    def _current_code_request(self) -> tuple[int, int]:
        budget = getattr(self, "_code_budget", None)
        if budget is None:
            return 1, 1
        return min(budget.request_limit, max(1, budget.requests)), budget.request_limit

    def code_run_tool_count(self) -> int:
        budget = getattr(self, "_code_budget", None)
        return budget.tool_calls if budget is not None else 0

    def code_run_raw_protocol_correct(self) -> bool | str:
        budget = getattr(self, "_code_budget", None)
        return budget.raw_protocol_correct() if budget is not None else "unknown"

    def code_run_envelope_normalized_inputs(self) -> int | str:
        budget = getattr(self, "_code_budget", None)
        return budget.envelope_normalized_inputs if budget is not None else "unknown"

    def code_run_wire_shape_rejections(self) -> int | str:
        budget = getattr(self, "_code_budget", None)
        return budget.wire_shape_rejections if budget is not None else "unknown"

    def claim_delivery_continuation(self, tool_limit: int) -> int | None:
        budget = getattr(self, "_code_budget", None)
        return budget.claim_continuation(tool_limit) if budget is not None else None

    def _required_delivery_tools(self) -> frozenset[str]:
        state_reader = getattr(self, "_code_delivery_state_reader", None)
        state = state_reader() if callable(state_reader) else None
        next_tools = state.get("nextTools") if isinstance(state, Mapping) else None
        if isinstance(next_tools, list) and "read_script" in next_tools:
            return _DELIVERY_TOOL_CANDIDATES
        return _DELIVERY_TOOL_NAMES

    def _visual_budget_gate_triggered(
        self,
        state: Mapping[str, Any],
        remaining_tool_calls: int,
    ) -> bool:
        """可视化任务在剩余工具预算过低且产物已齐全时，强制进入提交阶段。"""

        if state.get("taskKind") != "visualization":
            return False
        if remaining_tool_calls > getattr(
            self, "_code_visual_budget_gate_safety_margin", 2
        ):
            return False
        execution = state.get("execution")
        if not isinstance(execution, Mapping) or execution.get("valid") is not True:
            return False
        if state.get("outputValidation") == "failed":
            return False
        if state.get("visualFailures"):
            return False
        # 仍有未审查图片时 submit_script 必然以 visual_review_required 失败；
        # 强制提交只会烧掉最后的预算，应保留 view_image → submit_script 交付链。
        if state.get("pendingReviewCount"):
            return False
        failure = state.get("lastFailure")
        if isinstance(failure, Mapping) and failure.get("resolved") is False:
            return False
        next_tools = state.get("nextTools")
        if not isinstance(next_tools, list):
            return False
        return any(name in next_tools for name in ("view_image", "edit_script"))

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
                    "description": (
                        "这是 FREEFORM custom 工具，输入就是原始文本；"
                        "不要构造参数对象、字符串引号或 Markdown 围栏。"
                        + ("补丁以 *** Begin Edit 或 *** Begin Patch 和真实换行开头。"
                           if name == "edit_script"
                           else "Python 输入以 # Python 和真实换行开头。")
                        + ("仅 run 支持以 %%bash 和真实换行开头的 Shell cell。" if name == "run" else "")
                        + str(tool.get("description") or name)
                    ),
                    "format": {
                        "type": "grammar",
                        "syntax": "lark",
                        "definition": _FREEFORM_TOOL_GRAMMARS[name],
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
        # 对齐 Codex：允许 provider 在一次响应中返回多个工具调用。
        # _ordered_code_calls 会先整体校验，再按返回顺序执行；是否实际并行由
        # Reporting 工具执行器的顺序语义决定，不能把 parallel_tool_calls 当作执行顺序保证。
        params["parallel_tool_calls"] = True
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
        state_reader = getattr(self, "_code_delivery_state_reader", None)
        state = state_reader() if callable(state_reader) else None
        if isinstance(state, Mapping):
            script = state.get("script")
            if (
                isinstance(script, Mapping)
                and script.get("sha256")
                and state.get("rewriteAllowed") is not True
            ):
                # 完整写入只用于首次创建；已有脚本只能走局部编辑，
                # 除非交付状态的重写闸门已放行（连续编辑失败死局的逃生口）。
                formatted_tools = [
                    tool for tool in formatted_tools if tool["name"] != "write_script"
                ]
                params["tools"] = formatted_tools
                declarations = {tool["name"]: tool["type"] for tool in formatted_tools}
        budget = getattr(self, "_code_budget", None)
        tool_limit = getattr(self, "_code_tool_call_limit", None)
        remaining_tool_calls = (
            max(0, tool_limit - budget.tool_calls)
            if budget is not None and isinstance(tool_limit, int)
            else None
        )
        next_tools = state.get("nextTools") if isinstance(state, Mapping) else None
        if isinstance(next_tools, list):
            allowed_tools = set(next_tools)
            if "write_script" in allowed_tools:
                # 首轮允许模型一次返回完整的正式交付链；探索 run 仍不在默认链中。
                allowed_tools.update({"run_script", "submit_script"})
                if state.get("taskKind") == "visualization":
                    allowed_tools.add("view_image")
            if (
                remaining_tool_calls is not None
                and self._visual_budget_gate_triggered(state, remaining_tool_calls)
            ):
                allowed_tools = {"submit_script"}
                view_image_rounds = sum(
                    1
                    for metric in self.code_run_request_metrics()
                    for call in (metric.get("toolCalls") or ())
                    if isinstance(call, Mapping) and call.get("name") == "view_image"
                )
                gate_event = {
                    "code": _VISUALIZATION_BUDGET_GATE_FORCED_SUBMIT,
                    "details": {
                        "remainingToolCalls": remaining_tool_calls,
                        "viewImageRounds": view_image_rounds,
                    },
                }
                request_metrics = getattr(self, "_code_request_metrics", None)
                if (
                    isinstance(request_metrics, list)
                    and request_metrics
                    and request_metrics[-1].get("status") == "started"
                ):
                    request_metrics[-1].setdefault("warnings", []).append(gate_event)
                logger.bind(
                    reporting_progress="code_visual_budget_gate",
                    **gate_event["details"],
                ).warning(
                    "report_code_visual_budget_gate_forced_submit remaining={} view_image_rounds={}",
                    remaining_tool_calls,
                    view_image_rounds,
                )
            visual_gate = state.get("visualReviewGate")
            if isinstance(visual_gate, Mapping) and visual_gate.get("tripped") is True:
                rounds_gate_event = {
                    "code": _VISUALIZATION_REVIEW_ROUNDS_GATE,
                    "details": {"criticalRounds": visual_gate.get("criticalRounds")},
                }
                request_metrics = getattr(self, "_code_request_metrics", None)
                if (
                    isinstance(request_metrics, list)
                    and request_metrics
                    and request_metrics[-1].get("status") == "started"
                ):
                    request_metrics[-1].setdefault("warnings", []).append(
                        rounds_gate_event
                    )
                logger.bind(
                    reporting_progress="code_visual_review_gate",
                    critical_rounds=visual_gate.get("criticalRounds"),
                ).warning(
                    "report_code_visual_review_rounds_exhausted critical_rounds={}",
                    visual_gate.get("criticalRounds"),
                )
            # 分析与图表都以宿主交付状态为工具白名单；空列表必须保持关闭。
            formatted_tools = [
                tool for tool in formatted_tools if tool["name"] in allowed_tools
            ]
            if allowed_tools and not formatted_tools:
                raise _custom_protocol_error("交付状态没有可用的任务工具。")
            params["tools"] = formatted_tools
            declarations = {tool["name"]: tool["type"] for tool in formatted_tools}
        self._code_declared_tools = declarations
        if not formatted_tools:
            params.pop("tool_choice", None)
        elif any(tool.get("type") == "custom" for tool in formatted_tools):
            params["tool_choice"] = "auto"
        elif tools and tool_choice is None:
            params["tool_choice"] = "auto"
        reasoning = params.get("reasoning")
        reasoning_effort = (
            reasoning.get("effort")
            if isinstance(reasoning, Mapping)
            else getattr(self, "reasoning_effort", None)
        )
        extra_body = _responses_thinking_extra_body(
            params.get("extra_body"),
            endpoint=str(self.base_url) if self.base_url is not None else None,
            enabled=bool(reasoning_effort and reasoning_effort != "none"),
        )
        if extra_body is None:
            params.pop("extra_body", None)
        else:
            params["extra_body"] = extra_body
        reasoning_fields = (
            sorted(reasoning.keys()) if isinstance(reasoning, Mapping) else []
        )
        logger.bind(
            reporting_progress="code_provider_request_params",
            model_id=self.id,
            reasoning_effort=reasoning_effort,
            reasoning_fields=reasoning_fields,
            extra_body_keys=sorted(extra_body) if isinstance(extra_body, dict) else [],
            max_output_tokens=params.get("max_output_tokens"),
            parallel_tool_calls=params.get("parallel_tool_calls"),
            tool_choice=params.get("tool_choice"),
        ).debug("report_code_provider_request_params")
        observation = self._request_params_observation(params, messages, tools)
        if observation["model"] == "unknown":
            observation["model"] = self.id or "unknown"
        if observation["reasoningEffort"] in (None, "unknown"):
            observation["reasoningEffort"] = self.reasoning_effort or "unknown"
        self._code_last_request_params = observation
        request_metrics = getattr(self, "_code_request_metrics", None)
        if (
            isinstance(request_metrics, list)
            and request_metrics
            and request_metrics[-1].get("status") == "started"
        ):
            request_metrics[-1]["requestParams"] = dict(observation)
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
        # 仅自动启用真实探针通过的 endpoint/model；其他部署保留显式配置。
        probed_reasoning_route = (
            urlsplit(str(request_model.base_url or "")).hostname
            == "token-plan.cn-beijing.maas.aliyuncs.com"
            and request_model.id in {"deepseek-v4-flash-0731", "qwen3.8-flash"}
        )
        if probed_reasoning_route:
            request_model.store = False
            request_model.include = list(dict.fromkeys([
                *(request_model.include or []), "reasoning.encrypted_content",
            ]))
        request_model.max_output_tokens = (
            request_model.max_output_tokens
            if isinstance(request_model.max_output_tokens, int)
            and request_model.max_output_tokens > 0
            else None
        )
        decision = current_reporting_thinking_decision()
        if decision is not None:
            # Responses API 只接受 reasoning.effort；内部 thinking_budget 仅用于
            # 其他兼容协议的策略选择，不能成为本路径的启用条件或 wire 字段。
            # DashScope Responses 在省略 effort 时会回退到 provider 默认思考；
            # 显式关闭必须发送标准 effort=none，不能只依赖 enable_thinking=false。
            effort = decision.reasoning_effort if decision.enabled else "none"
            if effort == "max" and str(request_model.id or "").lower().startswith("qwen"):
                effort = "xhigh"
            request_model.reasoning_effort = effort
            request_model.reasoning = None
        # Responses 使用标准 reasoning.effort/summary；provider 开关按端点契约投影。
        responses_reasoning_enabled = bool(
            request_model.reasoning_effort
            and request_model.reasoning_effort != "none"
        )
        request_model.extra_body = _responses_thinking_extra_body(
            request_model.extra_body,
            endpoint=str(request_model.base_url) if request_model.base_url is not None else None,
            enabled=responses_reasoning_enabled,
        )
        # Responses wire 使用标准 reasoning 摘要；内部 thinking_budget 不进入 wire。
        reasoning = dict(request_model.reasoning or {})
        reasoning.pop("summary", None)
        request_model.reasoning = reasoning or None
        configured_summary = self.reasoning_summary or (self.reasoning or {}).get("summary")
        request_model.reasoning_summary = (
            (configured_summary or ("auto" if probed_reasoning_route else None))
            if responses_reasoning_enabled else None
        )
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
        projected_input = with_reporting_durable_identities(messages)
        state_reader = getattr(self, "_code_delivery_state_reader", None)
        protected_call_ids: frozenset[str] = frozenset()
        if state_reader is not None:
            state = state_reader()
            if state:
                protected_call_ids = _unresolved_failure_call_ids(state)
                projected_input, current_read_ids = _filter_read_script_rounds(
                    projected_input, state
                )
                protected_call_ids = protected_call_ids | current_read_ids
                # 每轮从绑定状态生成，不依赖历史工具结果的 JSON/repr 格式。
                projected_input = [*projected_input, Message(
                    role="user", content=json.dumps(state, ensure_ascii=False, separators=(",", ":")),
                )]
        provider_input_hint = getattr(self, "_code_provider_input_hint", None)
        projected, metrics = TaskExecutionContextProjector.project_with_metrics(
            projected_input,
            model=self,
            tools=tools,
            response_format=response_format,
            hard_cap=hard_cap,
            protected_call_ids=protected_call_ids,
            # benchmark 专用开关：默认开启，生产路径不设置这两个属性。
            history_summary_enabled=not getattr(self, "_code_disable_history_summary", False),
            metadata_budget_enabled=not getattr(self, "_code_disable_metadata_budget", False),
            provider_input_hint=(
                provider_input_hint
                if isinstance(provider_input_hint, int)
                and not isinstance(provider_input_hint, bool)
                else None
            ),
        )
        if metrics.get("compaction_triggered") and metrics.get("input_inflation_detected"):
            # 膨胀触发的压缩完成后清除提示，避免本地估算恢复后仍持续强压。
            self._code_provider_input_hint = 0
        record_reporting_projection_metrics(metrics, input_token_hard_cap=hard_cap)
        # 有界投影快照：并入随后一次请求的 requestMetric，供 run 级压缩信号与回放诊断。
        self._code_last_projection_metrics = {
            "compaction_triggered": metrics.get("compaction_triggered", False),
            "compacted_calls": metrics.get("compacted_calls", 0),
            "metadata_bytes": metrics.get("metadata_bytes", 0),
            "compactable_history_bytes": metrics.get("compactable_history_bytes", 0),
            "truncated_calls": metrics.get("truncated_calls", 0),
            "dropped_summaries": metrics.get("dropped_summaries", 0),
            "metadata_budget_exceeded": metrics.get("metadata_budget_exceeded", False),
            "compaction_tokens_before": metrics.get("compaction_tokens_before", 0),
            "compaction_tokens_after": metrics.get("compaction_tokens_after", 0),
            "projected_estimated_tokens": metrics.get("projected_estimated_tokens", 0),
            "window_rebased": metrics.get("window_rebased", False),
            "dropped_complete_rounds": metrics.get("dropped_complete_rounds", 0),
        }
        return projected

    def _pop_code_projection_metrics(self) -> dict[str, int | bool]:
        snapshot = getattr(self, "_code_last_projection_metrics", None)
        self._code_last_projection_metrics = None
        return dict(snapshot) if isinstance(snapshot, dict) else {}

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        # 在协议拒绝之前保存计费事实；不采集源码、工具参数或思考正文。
        metrics = getattr(self, "_code_request_metrics", [])
        if metrics and metrics[-1].get("status") == "started":
            metric = metrics[-1]
            response_id = _field(response, "id")
            if isinstance(response_id, str):
                metric["providerRequestId"] = response_id[:256]
            usage = _field(response, "usage")
            for key, value in (
                ("inputTokens", _field(usage, "input_tokens")),
                ("outputTokens", _field(usage, "output_tokens")),
                ("reasoningTokens", _field(_field(usage, "output_tokens_details"), "reasoning_tokens")),
                ("cacheReadTokens", _field(_field(usage, "input_tokens_details"), "cached_tokens")),
            ):
                metric[key] = value if type(value) is int and value >= 0 else "unknown"
            if type(metric["outputTokens"]) is int and type(metric["reasoningTokens"]) is int:
                metric["visibleOutputTokens"] = max(0, metric["outputTokens"] - metric["reasoningTokens"])
            # 估算 vs 实报比值观测：只为校准 0.60 门禁采数据，不改变任何触发逻辑。
            provider_input = metric.get("inputTokens")
            estimated_input = metric.get("projected_estimated_tokens")
            if (
                type(provider_input) is int
                and type(estimated_input) is int
                and estimated_input > 0
            ):
                logger.bind(
                    reporting_progress="code_projection_estimate_ratio",
                    model_id=self.id,
                ).debug(
                    "code_projection_estimate_ratio estimated={} provider={} ratio_percent={}",
                    estimated_input,
                    provider_input,
                    round(provider_input * 100 / estimated_input),
                )
        if _field(response, "error") is not None:
            return super()._parse_provider_response(response, **kwargs)
        output = _field(response, "output")
        output = list(output) if isinstance(output, (list, tuple)) else []
        actionable = [
            item
            for item in output
            if _field(item, "type") in {"custom_tool_call", "function_call"}
        ]
        # 父类按 provider 原始 wire 类型解析；还原为 custom 的 function_call 仍占用
        # 父类 function 调用序列中的一个位置，重组时必须按原始类型对齐消费。
        original_kinds = [_field(item, "type") for item in actionable]
        declarations = getattr(self, "_code_declared_tools", None)
        budget = getattr(self, "_code_budget", None)
        task_tools = getattr(self, "_code_tool_names", None)
        identities: set[str] = set()
        stage_mismatch_names: list[str] = []
        wire_rejected_call_ids: list[str] = []
        for item in actionable:
            name = _field(item, "name")
            kind = "custom" if _field(item, "type") == "custom_tool_call" else "function"
            if declarations is not None and declarations.get(name) != kind:
                # 任务集内、wire 类型与该工具的任务内标准类型一致、只是不在当前交付
                # 阶段白名单：这是状态机与模型的博弈信号，走软拒绝回执继续本轮（在
                # _ordered_code_calls 中逐个补回执），不作为 provider 协议异常。
                # wire 类型错误（如 function 形态的 write_script）仍是硬违规。
                expected_task_kind = "custom" if name in FREEFORM_TOOL_ARGUMENTS else "function"
                if (
                    isinstance(name, str)
                    and task_tools is not None
                    and name in task_tools
                    and kind == expected_task_kind
                ):
                    stage_mismatch_names.append(name)
                    if budget is not None:
                        budget.record_stage_mismatch_rejection()
                    logger.warning(
                        "report_code_stage_tool_unavailable name={} kind={} declared={} required={}",
                        str(name)[:128], kind, sorted(declarations), sorted(task_tools),
                    )
                else:
                    if (
                        _is_wire_shaped_freedom_call(name, kind, task_tools)
                        and budget is not None
                        and budget.wire_shape_rejections < _WIRE_SHAPE_REJECTION_LIMIT
                    ):
                        # grammar 退化下 FREEFORM 工具以 function 形态返回：不改写为
                        # custom、不执行，保留 provider 原样历史并补未执行回执；超过
                        # 上限后按协议违规 fail-closed。
                        budget.record_wire_shape_rejection()
                        wire_rejected_call_ids.append(_required_id(item, "call_id"))
                        logger.warning(
                            "report_code_wire_shape_rejected name={} rejection={}",
                            str(name)[:128], budget.wire_shape_rejections,
                        )
                    else:
                        if budget is not None:
                            budget.record_protocol_violation()
                        logger.warning(
                            "report_code_tool_declaration_mismatch name={} kind={} declared={}",
                            str(name)[:128], kind, sorted(declarations),
                        )
                        error = _custom_protocol_error("Coding Agent 返回未声明或类型不匹配的工具调用。")
                        error.details.update({
                            "toolName": str(name)[:128],
                            "receivedType": kind,
                            "expectedType": declarations.get(name, "undeclared"),
                            "declaredTools": dict(declarations),
                            "itemId": str(_field(item, "id"))[:256],
                            "callId": str(_field(item, "call_id"))[:256],
                        })
                        raise error
            call_identities = {_required_id(item, "id"), _required_id(item, "call_id")}
            if identities.intersection(call_identities):
                if budget is not None:
                    budget.record_protocol_violation()
                raise _custom_protocol_error("Coding Agent 工具调用身份重复。")
            identities.update(call_identities)
        self._code_stage_mismatch_names = frozenset(stage_mismatch_names)
        self._code_wire_rejected_call_ids = frozenset(wire_rejected_call_ids)
        if not actionable and _contains_textual_tool_marker(output):
            if budget is not None:
                budget.record_protocol_violation()
            raise _custom_protocol_error("Coding Agent 将工具调用写入了 assistant 正文。")
        if budget is not None:
            for item in actionable:
                if _field(item, "type") != "custom_tool_call":
                    continue
                name = _field(item, "name")
                raw_input = _field(item, "input")
                protocol_correct = (
                    isinstance(name, str)
                    and isinstance(raw_input, str)
                    and raw_input.startswith(_custom_input_prefixes(name))
                )
                if not protocol_correct and isinstance(name, str) and isinstance(raw_input, str):
                    # 单层 data 信封按兼容路径解封执行：不算协议违规，单列计数。
                    _, envelope_normalized = _normalize_provider_custom_input(raw_input, name)
                    if envelope_normalized:
                        budget.record_custom_input(protocol_correct=True)
                        budget.record_envelope_normalized()
                        continue
                budget.record_custom_input(protocol_correct=protocol_correct)
        custom_calls = {
            _field(item, "id"): _synthetic_custom_call(item)
            for item in actionable
            if _field(item, "type") == "custom_tool_call"
        }
        parsed = super()._parse_provider_response(response, **kwargs)
        for call in parsed.tool_calls or ():
            if isinstance(call, dict) and call.get("call_id") in wire_rejected_call_ids:
                # 标记为“按 provider 原样回放的被拒 function 调用”，回放时不得误判为
                # 被篡改的 custom 调用，也不得还原为 custom 形态。
                call["provider_data"] = {"reporting_wire_type": _WIRE_REJECTED_FUNCTION}
        if not custom_calls:
            return parsed
        function_calls = iter(parsed.tool_calls or ())
        parsed.content = None
        tool_calls: list[Any] = []
        for original_kind, item in zip(original_kinds, actionable, strict=True):
            parent_call = next(function_calls) if original_kind == "function_call" else None
            tool_calls.append(
                custom_calls[_field(item, "id")]
                if _field(item, "type") == "custom_tool_call"
                else parent_call
            )
        parsed.tool_calls = tool_calls
        parsed.extra = parsed.extra or {}
        parsed.extra["tool_call_ids"] = [call["call_id"] for call in parsed.tool_calls]
        return parsed

    def _stage_tool_now_allowed(self, tool_name: str) -> bool:
        """解析时的阶段白名单只是请求发出时的快照。

        同批调用按 provider 顺序执行，前序调用（如 run_script 成功）会推进交付状态；
        执行到该调用时以最新 nextTools 为准，否则“先运行再提交”的正常批次会被
        误拒，白白多耗一轮请求。
        """
        reader = getattr(self, "_code_delivery_state_reader", None)
        state = reader() if callable(reader) else None
        next_tools = state.get("nextTools") if isinstance(state, Mapping) else None
        return isinstance(next_tools, list) and tool_name in next_tools

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
        request_metrics = getattr(self, "_code_request_metrics", [])
        request_metric = request_metrics[-1] if request_metrics else None
        budget = getattr(self, "_code_budget", None)
        required_delivery_tools = self._required_delivery_tools()
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
            if function_call_limit is not None and current_count >= function_call_limit:
                # Agno 的硬限额只回裸 tool_call_error（无 code，回放 requestMetrics
                # 表现为边界 tool_error）；在委托前换成编码回执，模型与指标都能
                # 看到明确的终止原因。计数口径与 Agno 一致（下一次调用即超限）。
                limited = Message(
                    role=self.tool_message_role,
                    tool_call_id=call.call_id,
                    tool_name=tool_name,
                    tool_args=call.arguments,
                    tool_call_error=True,
                    content=json.dumps({
                        "ok": False,
                        "status": "rejected",
                        "code": "report_code_tool_call_limit",
                        "message": "工具调用次数已达上限；本次调用未执行。",
                        "details": {"used": current_count, "limit": function_call_limit},
                    }, ensure_ascii=False),
                )
                self._attach_tool_budget(
                    [limited], used=current_count, limit=function_call_limit
                )
                results.append(limited)
                if request_metric is not None and "firstToolFailure" not in request_metric:
                    request_metric["firstToolFailure"] = {
                        "toolName": tool_name[:128],
                        "code": "report_code_tool_call_limit",
                        "diagnostics": {"used": current_count, "limit": function_call_limit},
                    }
                logger.bind(
                    reporting_progress="code_tool",
                    tool_name=tool_name,
                    status="rejected",
                    code="report_code_tool_call_limit",
                ).info("report_code_tool_progress tool_name={} status=rejected", tool_name)
                continue
            is_redundant_review = self._is_redundant_visual_review(call)
            if call.call_id in getattr(self, "_code_wire_rejected_call_ids", frozenset()):
                # provider 以 function 形态返回 FREEFORM 工具：按协议只执行结构化
                # custom_tool_call，这里补未执行回执并继续本批次，不消耗任务额度。
                wire_rejected = Message(
                    role=self.tool_message_role,
                    tool_call_id=call.call_id,
                    tool_name=tool_name,
                    tool_args=call.arguments,
                    tool_call_error=True,
                    content=json.dumps({
                        "ok": False,
                        "status": "rejected",
                        "code": "report_code_tool_wire_type_invalid",
                        "message": (
                            f"{tool_name} 只能以原生 custom 工具调用（free-form 原文），"
                            "不能使用 JSON function 形态；本次未执行，请用 custom 工具重新发送。"
                        ),
                        "details": {
                            "toolName": tool_name,
                            "receivedType": "function",
                            "expectedType": "custom",
                            "inputPrefixes": list(_custom_input_prefixes(tool_name)),
                        },
                    }, ensure_ascii=False),
                )
                if function_call_limit is not None:
                    self._attach_tool_budget(
                        [wire_rejected], used=current_count, limit=function_call_limit
                    )
                results.append(wire_rejected)
                logger.bind(
                    reporting_progress="code_tool",
                    tool_name=tool_name,
                    status="rejected",
                    code="report_code_tool_wire_type_invalid",
                ).info("report_code_tool_progress tool_name={} status=rejected", tool_name)
                continue
            if tool_name in getattr(
                self, "_code_stage_mismatch_names", frozenset()
            ) and not self._stage_tool_now_allowed(tool_name):
                # 上一轮校验已判定该调用不在当前交付阶段白名单（但任务集内且
                # wire 类型正确），且同批前序调用也未使其变为可用：补未执行回执并
                # 继续本批次，不消耗任务额度。
                stage_state_reader = getattr(self, "_code_delivery_state_reader", None)
                stage_state = (
                    stage_state_reader() if callable(stage_state_reader) else None
                )
                stage_next_tools = (
                    stage_state.get("nextTools") if isinstance(stage_state, Mapping) else None
                )
                stage_mismatch = Message(
                    role=self.tool_message_role,
                    tool_call_id=call.call_id,
                    tool_name=tool_name,
                    tool_args=call.arguments,
                    tool_call_error=True,
                    content=json.dumps({
                        "ok": False,
                        "status": "rejected",
                        "code": "report_code_stage_tool_unavailable",
                        "message": (
                            "该工具当前不可用；请按交付状态的 requiredAction 使用 "
                            "nextTools 中的工具继续。"
                        ),
                        "details": {
                            "nextTools": sorted(
                                set(stage_next_tools or ())
                                & (getattr(self, "_code_tool_names", None) or frozenset())
                            ),
                            "requiredAction": (
                                stage_state.get("requiredAction")
                                if isinstance(stage_state, Mapping)
                                else None
                            ),
                        },
                    }, ensure_ascii=False),
                )
                if function_call_limit is not None:
                    self._attach_tool_budget(
                        [stage_mismatch], used=current_count, limit=function_call_limit
                    )
                results.append(stage_mismatch)
                logger.bind(
                    reporting_progress="code_tool",
                    tool_name=tool_name,
                    status="rejected",
                    code="report_code_stage_tool_unavailable",
                ).info("report_code_tool_progress tool_name={} status=rejected", tool_name)
                continue
            if (
                budget is not None
                and function_call_limit is not None
                and (tool_name not in required_delivery_tools or is_redundant_review)
                and budget.reserved(current_count, function_call_limit)
            ):
                # 冗余的 view_image（图片已通过当前内容的审查）不是预算耗尽，只是
                # 一次浪费的调用；跳过它但不终止本批次，避免连带丢弃同批次里其他
                # 未审查的 view_image 或 submit_script。
                if is_redundant_review and tool_name in _DELIVERY_TOOL_NAMES:
                    skipped_redundant = Message(
                        role=self.tool_message_role,
                        tool_call_id=call.call_id,
                        tool_name=tool_name,
                        tool_args=call.arguments,
                        tool_call_error=True,
                        content=json.dumps({
                            "ok": False,
                            "status": "skipped",
                            "code": "report_code_visual_review_redundant",
                            "message": "该图片内容已通过当前审查，无需再次调用 view_image。",
                        }, ensure_ascii=False),
                    )
                    if function_call_limit is not None:
                        self._attach_tool_budget(
                            [skipped_redundant], used=current_count, limit=function_call_limit
                        )
                    results.append(skipped_redundant)
                    logger.bind(
                        reporting_progress="code_tool",
                        tool_name=tool_name,
                        status="skipped",
                        code="report_code_visual_review_redundant",
                    ).info(
                        "report_code_tool_progress tool_name={} status=skipped", tool_name
                    )
                    continue
                escalated = budget.reject_exploration()
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
                            "剩余额度仅供交付；请立即调用 requiredNextTools 中的工具，"
                            "不要再调用探索工具。"
                            if escalated
                            else "剩余工具调用额度仅供正式脚本写入、运行、审查和提交。"
                        ),
                        "details": {
                            "used": current_count,
                            "limit": function_call_limit,
                            "requiredNextTools": sorted(
                                required_delivery_tools
                                & (getattr(self, "_code_tool_names", None) or frozenset())
                            ),
                            "escalated": escalated,
                        },
                    }, ensure_ascii=False),
                )
                charge = int(escalated and current_count < function_call_limit)
                charged_count = current_count + charge
                current_count = charged_count
                if budget is not None:
                    budget.tool_calls += charge
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
            charge = self._limit_charge_for(completed, result_store)
            if budget is not None:
                # Agno 的超限回执也计数，但未执行的超限调用不再消耗任务额度。
                budget.tool_calls += (
                    charge if function_call_limit is None
                    else min(charge, max(0, function_call_limit - current_count))
                )
            current_count += charge
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
            if (
                budget is not None
                and tool_name in required_delivery_tools
                and result.get("ok") is True
            ):
                # 模型已恢复交付类调用并成功执行；升级计数不应把这次成功前的
                # 拒绝历史带到下一次预留区拒绝上，否则一次陈旧的拒绝就会让
                # 后续正常拒绝被误判为升级。
                budget.delivery_succeeded()
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
            validation = result.get("outputValidation")
            failure = validation if isinstance(validation, Mapping) else result
            if (
                request_metric is not None
                and "firstToolFailure" not in request_metric
                and (failure.get("ok") is False or any(item.tool_call_error for item in completed))
            ):
                failure_code = failure.get("code")
                tool_failure: dict[str, Any] = {
                    "toolName": tool_name[:128],
                    "code": failure_code[:128]
                    if isinstance(failure_code, str) and failure_code
                    else "tool_error",
                }
                diagnostics = bounded_failure_diagnostics(failure.get("details"))
                if diagnostics:
                    tool_failure["diagnostics"] = diagnostics
                request_metric["firstToolFailure"] = tool_failure
            if tool_name == "run_script" and budget is not None:
                self._record_run_outcome(
                    failure.get("ok") is not False
                    and not any(item.tool_call_error for item in completed),
                    failure,
                )
            if isinstance(code, str):
                progress["code"] = code
            logger.bind(**progress).info(
                "report_code_tool_progress tool_name={} status={} code={}",
                tool_name, status, code[:128] if isinstance(code, str) and code else "-",
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
        wire_rejected_ids: set[str] = set()
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
                provider_data = _field(original, "provider_data")
                wire_rejected = (
                    isinstance(provider_data, Mapping)
                    and provider_data.get("reporting_wire_type") == _WIRE_REJECTED_FUNCTION
                )
                if name in FREEFORM_TOOL_ARGUMENTS and not wire_rejected:
                    raise _custom_protocol_error("Coding Agent custom 工具调用类型不匹配。")
                if wire_rejected:
                    wire_rejected_ids.update(identities)
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
            elif (
                message.tool_name in FREEFORM_TOOL_ARGUMENTS
                and result_identity not in wire_rejected_ids
            ):
                raise _custom_protocol_error("Coding Agent custom 工具结果类型不匹配。")
        if any(
            custom_result_counts.get(custom["call_id"], 0) != 1
            for custom in custom_replays
        ):
            raise _custom_protocol_error("Coding Agent custom 工具调用缺少对应结果。")

        formatted = super()._format_messages(messages, compress_tool_results, tools)
        # Agno 已原生解析 reasoning_output，但 3.0.9 的工具调用分支未回放它。
        # 按第一条调用身份插回原始 item，同一批多个调用只插入一次。
        if self.store is False:
            reasoning_by_call = {
                message.tool_calls[0].get("call_id", message.tool_calls[0].get("id")):
                    message.provider_data["reasoning_output"]
                for message in normalized_messages
                if message.tool_calls and message.provider_data
                and message.provider_data.get("reasoning_output") is not None
            }
            replayed = []
            for item in formatted:
                if isinstance(item, dict) and item.get("type") == "function_call":
                    reasoning = reasoning_by_call.get(item.get("call_id"))
                    if reasoning is not None:
                        replayed.append(ResponseReasoningItem.model_validate(reasoning))
                replayed.append(item)
            formatted = replayed
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
        # 同步路径不生成 requestMetric，投影快照在此丢弃，避免错误归属到后续请求。
        self._code_last_projection_metrics = None
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
        request_metric: dict[str, Any] = {
            "requestIndex": request_index,
            "providerRequestId": "unknown",
            "durationMs": "unknown",
            "inputTokens": "unknown",
            "outputTokens": "unknown",
            "reasoningTokens": "unknown",
            "visibleOutputTokens": "unknown",
            "cacheReadTokens": "unknown",
            "timeToFirstTokenSeconds": "unknown",
            "toolNames": [],
            "toolCalls": [],
            "toolCallCount": 0,
            "requestParams": dict(getattr(self, "_code_last_request_params", {})),
            "status": "started",
        }
        request_metric.update(self._pop_code_projection_metrics())
        getattr(self, "_code_request_metrics", []).append(request_metric)
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
            duration_ms = elapsed_ms(started_at)
            request_metric.update(durationMs=duration_ms, status="failed")
            logger.bind(
                reporting_progress="code_model_request",
                model_id=self.id,
                request_index=request_index,
                request_limit=request_limit,
                duration_ms=duration_ms,
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
        usage = getattr(response, "response_usage", None)
        input_tokens = usage.input_tokens if usage is not None else "unknown"
        output_tokens = usage.output_tokens if usage is not None else "unknown"
        reasoning_tokens = usage.reasoning_tokens if usage is not None else "unknown"
        cache_read_tokens = usage.cache_read_tokens if usage is not None else "unknown"
        time_to_first_token = usage.time_to_first_token if usage is not None else "unknown"
        visible_output_tokens = (
            max(0, output_tokens - reasoning_tokens)
            if isinstance(output_tokens, int)
            and not isinstance(output_tokens, bool)
            and isinstance(reasoning_tokens, int)
            and not isinstance(reasoning_tokens, bool)
            else "unknown"
        )
        duration_ms = elapsed_ms(started_at)
        tool_calls = self._response_tool_calls(response)
        request_metric.update(
            {
                "providerRequestId": (
                    response.id if isinstance(getattr(response, "id", None), str)
                    else request_metric["providerRequestId"]
                ),
                "durationMs": duration_ms,
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "reasoningTokens": reasoning_tokens,
                "visibleOutputTokens": visible_output_tokens,
                "cacheReadTokens": cache_read_tokens,
                "timeToFirstTokenSeconds": (
                    time_to_first_token if time_to_first_token is not None else "unknown"
                ),
                "toolNames": list(dict.fromkeys(call["name"] for call in tool_calls)),
                "toolCalls": tool_calls,
                "toolCallCount": len(tool_calls),
                "status": "completed",
            }
        )
        if isinstance(input_tokens, int) and not isinstance(input_tokens, bool):
            # provider 实测输入是上下文膨胀的地面真值：本地估算与 provider 计数
            # 已证实会偏离（cli 复盘：本地 ~36K 时 provider 实测 172K）。
            self._code_provider_input_hint = input_tokens
        logger.bind(
            reporting_progress="code_model_request",
            model_id=self.id,
            request_index=request_index,
            request_limit=request_limit,
            duration_ms=duration_ms,
            status="completed",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens,
            visible_output_tokens=visible_output_tokens,
            cache_read_tokens=cache_read_tokens,
            cached_tokens=cache_read_tokens,
            time_to_first_token_seconds=time_to_first_token,
        ).info(
            "report_code_model_request_completed model_id={} request_index={} "
            "request_limit={} status=completed input_tokens={} output_tokens={} "
            "reasoning_tokens={} visible_output_tokens={} cache_read_tokens={}",
            self.id,
            request_index,
            request_limit,
            input_tokens,
            output_tokens,
            reasoning_tokens,
            visible_output_tokens,
            cache_read_tokens,
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
