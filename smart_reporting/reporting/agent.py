import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextvars import ContextVar
from copy import copy, deepcopy
from dataclasses import fields
from functools import partial
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.exceptions import AgentRunException, StopAgentRun
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutputEvent
from agno.run.team import TeamRunOutputEvent
from openai.types.chat.chat_completion_chunk import (
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from pydantic import ValidationError

from ..agent_control import AGENT_PLAN_STATE_KEY
from ..context_management import (
    CODING_CONTEXT_TOKEN_LIMIT,
    CODING_OUTPUT_TOKEN_RESERVE,
    CodingContextProjector,
    ContextBudgetController,
    ProjectedOpenAIChat,
    clear_terminal_reasoning,
    projected_coding_model,
)
from ..model_config import OPENAI_COMPATIBLE_ROLE_MAP
from ..settings import AgentSettings
from ..skills import (
    create_skill_script_hook,
    is_skill_script_hook,
    load_sandbox_execution_skills,
)
from ..task_execution import TaskExecutionRepository
from ..task_execution.execution import (
    create_task_tool_scheduler_hook,
    is_task_tool_scheduler_hook,
)
from ..workspace import WorkspaceService
from .delivery.acceptance import load_reporting_skills
from .instructions import build_report_agent_instructions
from .model_policy import (
    ReportingReasoningEffort,
    ReportingThinkingProfile,
    apply_reporting_thinking_profile,
    reporting_thinking_profile_from_model,
)
from .models import ReportingError
from .phase import (
    REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP,
    REPORTING_SECTION_INPUT_TOKEN_HARD_CAP,
    REPORTING_TASK_DEPENDENCY,
    ReportingPhase,
    current_reporting_run_context,
    record_reporting_projection_metrics,
    reporting_phase_allows_tool,
    reporting_phase_from_run_context,
    reporting_task_kind_from_run_context,
    reporting_thinking_effort_from_run_context,
)
from .tools import build_report_worker_tools
from .vision import ReportVisionReviewer
from .workflow.controller import ReportWorkflowController, ReportWorkflowToolkit
from .workflow.repository import ReportingStateRepository

_REPORT_FACADE_TOOL_NAMES = frozenset(
    {
        "report_workflow_start",
        "report_workflow_review",
        "report_workflow_approve",
        "report_workflow_reject",
    }
)
_REPORT_STRICT_TOOL_NAMES = frozenset(
    {
        "complete_analysis_item",
        "finalize_report_analysis",
        "request_analysis_rework",
        "register_report_charts",
        "render_report_section",
    }
)
_REPORT_TOOL_ARGUMENT_ERROR_STATE_KEY = "agentos_reporting_tool_argument_errors"
_REPORT_TOOL_ARGUMENT_ERROR_CONTEXT_LENGTH = 240
_CUMULATIVE_STREAM_USAGE_HOSTS = frozenset({"api.siliconflow.cn"})
_REPORT_TOOL_FAILURE_STATE_KEY = "agentos_reporting_tool_failures"
_REPORT_TOOL_SAME_FAILURE_LIMIT = 3
_REPORT_TOOL_PHASE_FAILURE_LIMIT = 8
_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_STATE_KEY = "agentos_reporting_analysis_success_tools"
_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT = 24
_REPORT_PROFILE_EMPTY_QUERY_STATE_KEY = "agentos_reporting_empty_profile_queries"
_REPORT_ARGUMENT_MAX_ISSUES = 8
_REPORT_ARGUMENT_MAX_TOP_LEVEL_KEYS = 32
_REPORT_ARGUMENT_MAX_LOC_LENGTH = 256
_REPORT_ARGUMENT_MAX_MESSAGE_LENGTH = 512
_REPORT_PROFILE_RECEIPT_PROJECTION_LIMIT = 100
_REPORT_PROFILE_QUERY_IDENTITY_MAX_LENGTH = 256
_REPORT_TOOL_RUN_ERROR_ATTR = "_agentos_reporting_tool_run_error"
# 历史真实 Reporting CLI 中，成功模型调用 P99 约 69 秒、最长约 135 秒；单个
# 后端异常却可能持续数分钟才返回。Worker 仍保留既有一次同 run continuation，
# 这里与 900 秒模型请求配置保持一致，避免长结构化规划请求在上游返回前被截断。
_REPORT_WORKER_MODEL_TIMEOUT_CAP_SECONDS = 900
_REPORT_MODEL_RUN_ERROR: ContextVar[tuple[int, Exception] | None] = ContextVar(
    "reporting_model_run_error",
    default=None,
)
_REPORT_EXPECTED_CALL_SHAPES: dict[str, dict[str, Any]] = {
    "finalize_report_analysis": {
        "reportBrief": {
            "objective": "形成年度运营报告",
            "executiveSummary": "收入增长但成本承压",
            "managementQuestions": ["增长是否可持续"],
            "warnings": [],
        },
        "metricDefinitions": [],
        "warnings": [],
    },
    "request_analysis_rework": {
        "analysisIds": ["analysis_001"],
        "reason": "缺少同比基准",
        "missingEvidence": ["补充上年同期收入"],
    },
    "register_report_charts": {
        "charts": [
            {
                "chartId": "income_trend",
                "sourcePath": "analysis/charts/income-trend.png",
                "title": "医疗收入月度趋势",
                "altText": "2025年医疗收入月度变化",
                "citationIds": ["citation_003"],
            }
        ]
    },
    "render_report_section": {
        "sectionCode": "executive_summary",
        "blocks": [
            {
                "blockId": "overview",
                "markdown": "### 核心结论\n\n- 医疗收入同比增长 8.2%",
                "citationIds": ["citation_001"],
                "chartIds": ["income_trend"],
            }
        ],
    },
}


def _record_reporting_tool_run_error(run_context: RunContext, error: Exception) -> None:
    """把原异常绑定到当前 RunContext，跨 Agno 并行工具 Task 保留对象身份。"""

    if getattr(run_context, _REPORT_TOOL_RUN_ERROR_ATTR, None) is None:
        setattr(run_context, _REPORT_TOOL_RUN_ERROR_ATTR, error)


def _take_reporting_tool_run_error() -> Exception | None:
    run_context = current_reporting_run_context()
    if run_context is None:
        return None
    error = getattr(run_context, _REPORT_TOOL_RUN_ERROR_ATTR, None)
    if isinstance(error, Exception):
        delattr(run_context, _REPORT_TOOL_RUN_ERROR_ATTR)
        return error
    return None


async def propagate_reporting_tool_errors(
    run_context: RunContext,
    function_name: str,
    function_call: Any,
    arguments: dict[str, Any],
) -> Any:
    """记录非领域工具异常，供模型工具批次边界原样抛给 Agno retry。"""

    _ = function_name
    try:
        result = function_call(**arguments)
        return await result if inspect.isawaitable(result) else result
    except (AgentRunException, ReportingError, ValidationError):
        raise
    except Exception as error:
        # Agno 2.8.2 Function.aexecute 会把普通异常转换成失败工具消息。只抛出并不足以
        # 触发 Agent retry，因此在共享 RunContext 记录原对象，由模型批次边界立即重抛。
        _record_reporting_tool_run_error(run_context, error)
        raise


def _reporting_session_state(run_context: RunContext) -> dict[str, Any] | None:
    return run_context.session_state if isinstance(run_context.session_state, dict) else None


def _reporting_mutation_sequence(state: dict[str, Any] | None) -> int:
    progress = state.get("agentos_coding_tool_progress") if isinstance(state, dict) else None
    return int(progress.get("mutation", 0)) if isinstance(progress, dict) else 0


def _reporting_analysis_item_tool_budget(
    run_context: RunContext,
    function_name: str,
) -> tuple[dict[str, Any], str] | None:
    if (
        function_name == "complete_analysis_item"
        or reporting_phase_from_run_context(run_context) != "analysis"
        or reporting_task_kind_from_run_context(run_context) != "analysis_item"
    ):
        return None
    state = _reporting_session_state(run_context)
    if state is None:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    external_run_id = binding.get("externalRunId") if isinstance(binding, Mapping) else None
    # 每个 analysis item 尝试都有独立 externalRunId/internal run。预算身份同时绑定二者，
    # continuation 可继承当前计数，而 fresh retry、其他分析项和并发 Task 必须从零开始。
    identity = f"{external_run_id or ''}:{run_context.run_id or ''}"
    budgets = state.get(_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_STATE_KEY)
    budgets = budgets if isinstance(budgets, dict) else {}
    stored = budgets.get(identity)
    successful_count = stored.get("successfulCount", 0) if isinstance(stored, dict) else 0
    successful_count = (
        int(successful_count) if isinstance(successful_count, int) and successful_count >= 0 else 0
    )
    in_flight_count = stored.get("inFlightCount", 0) if isinstance(stored, dict) else 0
    in_flight_count = (
        int(in_flight_count) if isinstance(in_flight_count, int) and in_flight_count >= 0 else 0
    )
    if successful_count + in_flight_count >= _REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT:
        _stop_exhausted_analysis_item_tool_budget(
            run_context,
            successful_count,
            in_flight_count,
        )
    budgets[identity] = {
        "successfulCount": successful_count,
        "inFlightCount": in_flight_count + 1,
    }
    state[_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_STATE_KEY] = budgets
    return state, identity


def _finish_reporting_analysis_item_tool_budget(
    reservation: tuple[dict[str, Any], str] | None,
    *,
    succeeded: bool,
) -> None:
    if reservation is None:
        return
    state, identity = reservation
    budgets = state.get(_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_STATE_KEY)
    if not isinstance(budgets, dict):
        return
    stored = budgets.get(identity)
    if not isinstance(stored, dict):
        return
    successful_count = stored.get("successfulCount", 0)
    successful_count = (
        int(successful_count) if isinstance(successful_count, int) and successful_count >= 0 else 0
    )
    budgets[identity] = {
        "successfulCount": successful_count + int(succeeded),
        "inFlightCount": max(int(stored.get("inFlightCount", 1)) - 1, 0),
    }


def _stop_exhausted_analysis_item_tool_budget(
    run_context: RunContext,
    successful_count: int,
    in_flight_count: int,
) -> None:
    details = {
        "successfulToolCalls": successful_count,
        "inFlightToolCalls": in_flight_count,
        "limit": _REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT,
    }
    error = ReportingError(
        "report_analysis_tool_budget_exhausted",
        "当前分析项已达到成功工具调用上限，已停止本次 run。",
        details=details,
    )
    # Agno 2.8.2 会把 StopAgentRun 收敛为 completed + stop_after_tool_call，异常本身
    # 不会越过模型工具批次。同步记录领域错误，由 ReportWorkerOpenAIChat 在同一批次
    # 恢复并交给 Workflow 的 fresh retry，禁止退化成笼统的“未完成验收”。
    _record_reporting_tool_run_error(run_context, error)
    serialized = json.dumps(
        {
            "ok": False,
            "status": "rejected",
            "code": error.code,
            "message": error.message,
            "requiredActions": ["结束本次 run，交由上层按既有重试策略重新执行当前分析项。"],
            "retryable": False,
            "details": details,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raise StopAgentRun(serialized, agent_message=serialized)


def _reporting_invalid_argument_receipt(
    run_context: RunContext | None,
    function_name: Any,
    raw_arguments: Any,
    error: json.JSONDecodeError | TypeError | None,
    *,
    schema_hint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """保留有界原始诊断，并把 malformed JSON 作为可自纠工具回执返回。"""

    if isinstance(raw_arguments, str):
        raw_text = raw_arguments
        argument_bytes = raw_arguments.encode("utf-8")
    elif isinstance(raw_arguments, (bytes, bytearray)):
        argument_bytes = bytes(raw_arguments)
        raw_text = argument_bytes.decode("utf-8", errors="replace")
    else:
        try:
            raw_text = json.dumps(
                raw_arguments,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            raw_text = repr(raw_arguments)
        argument_bytes = raw_text.encode("utf-8")
    if isinstance(error, json.JSONDecodeError):
        # CPython 对未闭合字符串把 pos 指向起始引号；Reporting 的常见成因是
        # 模型输出被截断，此时 EOF 才是可执行的修正位置，也能让有界上下文保留尾部。
        reported_offset = (
            len(raw_text) if error.msg.startswith("Unterminated string") else error.pos
        )
        error_offset = max(0, min(reported_offset, len(raw_text)))
        error_message = error.msg
    elif isinstance(error, TypeError):
        error_offset = 0
        error_message = "Arguments must be a JSON string"
    else:
        error_offset = 0
        error_message = "Top-level JSON value must be an object"
    context_start = max(
        0,
        min(
            error_offset - (_REPORT_TOOL_ARGUMENT_ERROR_CONTEXT_LENGTH // 2),
            max(0, len(raw_text) - _REPORT_TOOL_ARGUMENT_ERROR_CONTEXT_LENGTH),
        ),
    )
    error_context = raw_text[
        context_start : context_start + _REPORT_TOOL_ARGUMENT_ERROR_CONTEXT_LENGTH
    ]
    tool_name = function_name if isinstance(function_name, str) and function_name else "<unknown>"
    attempt = 1
    state = _reporting_session_state(run_context) if run_context is not None else None
    if state is not None:
        stored = state.get(_REPORT_TOOL_ARGUMENT_ERROR_STATE_KEY)
        counts = dict(stored) if isinstance(stored, dict) else {}
        previous = counts.get(tool_name, 0)
        attempt = int(previous) + 1 if isinstance(previous, int) else 1
        counts[tool_name] = attempt
        state[_REPORT_TOOL_ARGUMENT_ERROR_STATE_KEY] = counts
    is_analysis_write = function_name == "write_analysis_files"
    receipt: dict[str, Any] = {
        "ok": False,
        "status": "rejected",
        "code": (
            "report_analysis_write_arguments_json_invalid"
            if is_analysis_write
            else "report_tool_arguments_json_invalid"
        ),
        "message": (
            "write_analysis_files 参数不是合法 JSON 对象；工具尚未执行，请按严格 schema 重试。"
            if is_analysis_write
            else f"{tool_name} 参数不是合法 JSON 对象；工具尚未执行，请按当前 schema 重试。"
        ),
        "retryable": True,
        "attempt": attempt,
        "schemaHint": dict(schema_hint or {"argumentsType": "object"}),
        "details": {
            "argumentBytes": len(argument_bytes),
            "argumentsSha256": hashlib.sha256(argument_bytes).hexdigest(),
            "jsonErrorOffset": error_offset,
            "jsonErrorMessage": error_message,
            "errorContextStart": context_start,
            "errorContext": error_context,
        },
        "requiredActions": [
            f"下一条响应只调用一次 {tool_name}；参数必须是完整严格 JSON 对象，不得附加 Markdown 或解释文字。",
        ],
    }
    if is_analysis_write:
        receipt["retryContract"] = {
            "operation": "create_file",
            "path": "analysis/<name>.py",
            "content": "# complete script\npass\n",
        }
        receipt["requiredActions"].append(
            "按 retryContract 使用 content 单字符串一次提交完整脚本。"
            if attempt == 1
            else "继续优先使用 content 单字符串一次提交；只有再次失败或输出截断，或服务端明确报告超过 4 MiB 后，才使用 apply_patch/replace_text 定点续写。"
        )
    else:
        receipt["requiredActions"].append(
            "按 schemaHint 重新生成参数；不要修补、猜测或隐藏无效 JSON。"
        )
    return receipt


def _clear_reporting_argument_error(
    run_context: RunContext | None,
    function_name: Any,
) -> None:
    state = _reporting_session_state(run_context) if run_context is not None else None
    if state is None or not isinstance(function_name, str):
        return
    stored = state.get(_REPORT_TOOL_ARGUMENT_ERROR_STATE_KEY)
    if not isinstance(stored, dict) or function_name not in stored:
        return
    counts = dict(stored)
    counts.pop(function_name, None)
    state[_REPORT_TOOL_ARGUMENT_ERROR_STATE_KEY] = counts


def _reporting_tool_schema_hint(
    function_name: Any,
    functions: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """返回有界 schema 摘要，避免在错误回执中复制整份工具定义。"""

    hint: dict[str, Any] = {"argumentsType": "object"}
    if not isinstance(function_name, str) or not isinstance(functions, Mapping):
        return hint
    function = functions.get(function_name)
    parameters = getattr(function, "parameters", None)
    if not isinstance(parameters, Mapping):
        return hint
    properties = parameters.get("properties")
    if isinstance(properties, Mapping):
        hint["allowedFields"] = sorted(str(key) for key in properties)[:64]
    required = parameters.get("required")
    if isinstance(required, list):
        hint["requiredFields"] = [str(key) for key in required[:64]]
    return hint


def _is_tool_argument_error(error: TypeError | ValidationError) -> bool:
    if isinstance(error, ValidationError):
        return True
    message = str(error)
    return any(
        marker in message
        for marker in (
            "unexpected keyword argument",
            "required positional argument",
            "multiple values for argument",
            "positional arguments but",
        )
    )


def _report_tool_argument_failure(
    function_name: str,
    error: TypeError | ValidationError,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "status": "rejected",
        "code": "report_tool_arguments_invalid",
        "message": (
            "Reporting 工具参数不符合严格调用 schema。"
            if function_name in _REPORT_STRICT_TOOL_NAMES
            else "工具参数不符合当前工具的调用 schema。"
        ),
        "severity": "warning",
        "executionBlocking": False,
        "warnings": [
            {
                "code": "report_tool_arguments_invalid",
                "toolName": function_name,
            }
        ],
        "autoFixes": [],
        # 工具协议错误属于执行诊断，不得污染报告事实验收的 failedRequirements。
        "failedRequirements": [],
        "requiredActions": [
            (
                "逐字使用 correctCallExample 重试；不要增加 arguments 包装或其他字段。"
                if function_name in _REPORT_STRICT_TOOL_NAMES
                else "参照当前工具描述中的示例直接传参，不要增加 arguments 包装。"
            )
        ],
        "retryable": True,
        "details": _report_tool_argument_details(error, arguments),
    }
    expected = _REPORT_EXPECTED_CALL_SHAPES.get(function_name)
    if expected is not None:
        result["expectedCallShape"] = expected
        result["correctCallExample"] = {
            "name": function_name,
            "arguments": expected,
        }
    return result


def _bounded_argument_text(value: Any, limit: int) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _report_tool_argument_details(
    error: TypeError | ValidationError,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """返回足以修正调用的结构信息，同时不回显脚本正文或业务参数值。"""
    if isinstance(error, ValidationError):
        raw_issues = error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )[:_REPORT_ARGUMENT_MAX_ISSUES]
        issues = [
            {
                "loc": _bounded_argument_text(
                    ".".join(str(part) for part in item.get("loc", ())) or "$",
                    _REPORT_ARGUMENT_MAX_LOC_LENGTH,
                ),
                "message": _bounded_argument_text(
                    item.get("msg", "参数校验失败"),
                    _REPORT_ARGUMENT_MAX_MESSAGE_LENGTH,
                ),
                "type": _bounded_argument_text(item.get("type", "validation_error"), 128),
            }
            for item in raw_issues
        ]
    else:
        issues = [
            {
                "loc": "$",
                "message": _bounded_argument_text(error, _REPORT_ARGUMENT_MAX_MESSAGE_LENGTH),
                "type": "type_error",
            }
        ]
    # 顶层类型用于识别 object/array/string 形状错误；只暴露键名和 Python 类型，
    # 不返回值、嵌套内容或 ValidationError input，避免把大型代码和业务数据带回上下文。
    top_level_types = {
        _bounded_argument_text(key, 128): _bounded_argument_text(type(value).__name__, 128)
        for key, value in sorted(arguments.items(), key=lambda item: str(item[0]))[
            :_REPORT_ARGUMENT_MAX_TOP_LEVEL_KEYS
        ]
    }
    return {"issues": issues, "topLevelTypes": top_level_types}


def _reporting_progress_fingerprint(state: dict[str, Any]) -> str:
    coding_progress = state.get("agentos_coding_tool_progress")
    agent_plan = state.get(AGENT_PLAN_STATE_KEY)
    coding_progress = coding_progress if isinstance(coding_progress, dict) else {}
    agent_plan = agent_plan if isinstance(agent_plan, dict) else {}
    progress_entries = coding_progress.get("entries")
    progress_entries = progress_entries if isinstance(progress_entries, list) else []
    plan_steps = agent_plan.get("plan")
    plan_steps = plan_steps if isinstance(plan_steps, list) else []
    snapshot = {
        # Reporting 运行会通过阶段提交、update_plan 和 finish_task 推进。
        # 工具状态或 mutation 变化即重新计数。
        "codingProgress": {
            "mutation": coding_progress.get("mutation"),
            "entries": [
                {
                    "tool": item.get("tool"),
                    "mutation": item.get("mutation"),
                    "resultHash": item.get("resultHash"),
                }
                for item in progress_entries
                if isinstance(item, dict)
            ],
        },
        "agentPlan": [
            {"step": item.get("step"), "status": item.get("status")}
            for item in plan_steps
            if isinstance(item, dict)
        ],
    }
    return hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _empty_profile_query_state(
    run_context: RunContext,
    function_name: str,
    arguments: Mapping[str, Any],
) -> tuple[dict[str, Any], str] | None:
    if (
        function_name != "query_profile"
        or reporting_phase_from_run_context(run_context) != "analysis"
        or reporting_task_kind_from_run_context(run_context) != "analysis_item"
    ):
        return None
    dataset_id = arguments.get("datasetId")
    query = arguments.get("query")
    if not isinstance(dataset_id, str) or not dataset_id or not isinstance(query, str) or not query:
        return None
    state = _reporting_session_state(run_context)
    if state is None:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    external_run_id = binding.get("externalRunId") if isinstance(binding, Mapping) else None
    attempt_identity = f"{external_run_id or ''}:{run_context.run_id or ''}"
    query_identity = hashlib.sha256(
        json.dumps(
            [dataset_id, query],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    attempts = state.get(_REPORT_PROFILE_EMPTY_QUERY_STATE_KEY)
    attempts = attempts if isinstance(attempts, dict) else {}
    empty_queries = attempts.get(attempt_identity)
    empty_queries = empty_queries if isinstance(empty_queries, dict) else {}
    attempts[attempt_identity] = empty_queries
    state[_REPORT_PROFILE_EMPTY_QUERY_STATE_KEY] = attempts
    return empty_queries, query_identity


def _repeated_empty_profile_query_failure(details: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "rejected",
        "code": "report_profile_query_repeated_empty",
        "message": "相同 Profile 快照的相同查询已确认无结果，禁止重复执行。",
        "requiredActions": [
            "不要再次提交相同查询；改用当前分析已有事实、其他合法查询，或明确记录该分布不可用。"
        ],
        "retryable": False,
        "details": dict(details),
    }


def _enforce_reporting_no_progress(
    run_context: RunContext,
    function_name: str,
    result: Any,
    arguments: Mapping[str, Any] | None = None,
) -> Any:
    if not isinstance(result, dict):
        return result
    state = _reporting_session_state(run_context)
    # 任何成功的 Reporting 工具调用都代表模型已经完成了一个可观察动作。
    # 失败计数只用于阻断“同一错误、状态不变”的死循环，不能跨越真实成功进展
    # 累积到 finalize 阶段，否则早期参数错误会误杀后续正常提交。
    if result.get("ok") is True:
        if isinstance(state, dict):
            state.pop(_REPORT_TOOL_FAILURE_STATE_KEY, None)
        return result
    if result.get("ok") is not False:
        return result
    code = result.get("code")
    if not isinstance(code, str) or not code or state is None:
        return result

    mutation_sequence = _reporting_mutation_sequence(state)
    progress_fingerprint = _reporting_progress_fingerprint(state)
    call_identity = {
        "function": function_name,
        "arguments": dict(arguments or {}),
        "code": code,
        "details": result.get("details"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            call_identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    stored = state.get(_REPORT_TOOL_FAILURE_STATE_KEY)
    counts = (
        dict(stored.get("counts", {}))
        if isinstance(stored, dict)
        and stored.get("progressFingerprint") == progress_fingerprint
        and isinstance(stored.get("counts"), dict)
        else {}
    )
    previous_total = (
        stored.get("phaseFailureCount", 0)
        if isinstance(stored, dict) and stored.get("progressFingerprint") == progress_fingerprint
        else 0
    )
    phase_failure_count = int(previous_total) + 1 if isinstance(previous_total, int) else 1
    previous_count = counts.get(fingerprint, 0)
    count = int(previous_count) + 1 if isinstance(previous_count, int) else 1
    counts[fingerprint] = count
    state[_REPORT_TOOL_FAILURE_STATE_KEY] = {
        "progressFingerprint": progress_fingerprint,
        "mutationSequence": mutation_sequence,
        "phaseFailureCount": phase_failure_count,
        "counts": counts,
    }
    if count < 2 and phase_failure_count < _REPORT_TOOL_PHASE_FAILURE_LIMIT:
        return result

    # 精确重复失败只增加 DeepSeek Harness 风格的纠错提示。重复次数是可观测指标，
    # 不是运行预算或业务门禁；模型仍可缩小查询、修改参数或选择其他合法工具继续。
    guided = dict(result)
    raw_details = result.get("details")
    details = dict(raw_details) if isinstance(raw_details, dict) else {}
    details.update(
        {
            "failureFingerprint": fingerprint,
            "progressFingerprint": progress_fingerprint,
            "mutationSequence": mutation_sequence,
            "noProgressCount": phase_failure_count,
            "phaseFailureCount": phase_failure_count,
            "sameFailureCount": count,
        }
    )
    required_actions = [
        str(item) for item in result.get("requiredActions", ()) if isinstance(item, str) and item
    ]
    progressive_action = (
        "不要原样重复当前工具调用；只修改服务端 code/details 指向的参数后重试。"
        if count == 2
        else "当前调用已精确重复失败；缩小查询或改用本阶段其他合法工具取得同一事实。"
    )
    if progressive_action not in required_actions:
        required_actions.append(progressive_action)
    terminal_no_progress = (
        count >= _REPORT_TOOL_SAME_FAILURE_LIMIT
        or phase_failure_count >= _REPORT_TOOL_PHASE_FAILURE_LIMIT
    )
    if terminal_no_progress:
        required_actions = [
            "当前 Task 在没有任何成功工具进展时重复失败；结束本次 run，交由上层按既有重试策略恢复。"
        ]
    guided.update(
        {
            "code": "tool_no_progress" if terminal_no_progress else code,
            "message": (
                "Reporting 工具连续失败且没有可观察进展，已停止当前 run。"
                if terminal_no_progress
                else result.get("message")
            ),
            "details": details,
            "requiredActions": required_actions,
            "retryable": False if terminal_no_progress else result.get("retryable", True),
        }
    )
    return guided


async def normalize_reporting_tool_arguments(
    run_context: RunContext,
    function_name: str,
    function_call: Any,
    arguments: dict[str, Any],
) -> Any:
    """执行 Reporting 工具并把参数错误收敛为可操作回执。"""
    empty_query_state = _empty_profile_query_state(run_context, function_name, arguments)
    existing_empty = (
        empty_query_state[0].get(empty_query_state[1]) if empty_query_state is not None else None
    )
    if isinstance(existing_empty, Mapping):
        repeated_empty = _repeated_empty_profile_query_failure(existing_empty)
        return _enforce_reporting_no_progress(
            run_context,
            function_name,
            repeated_empty,
            {
                "datasetId": repeated_empty["details"]["datasetId"],
                "query": repeated_empty["details"]["query"],
                "snapshotHash": repeated_empty["details"]["snapshotHash"],
            },
        )
    reservation = _reporting_analysis_item_tool_budget(run_context, function_name)
    try:
        result = function_call(**arguments)
        result = await result if inspect.isawaitable(result) else result
    except (TypeError, ValidationError) as error:
        _finish_reporting_analysis_item_tool_budget(reservation, succeeded=False)
        if not _is_tool_argument_error(error):
            raise
        failure = _report_tool_argument_failure(
            function_name,
            error,
            arguments,
        )
        return _enforce_reporting_no_progress(
            run_context,
            function_name,
            failure,
            arguments,
        )
    except BaseException:
        _finish_reporting_analysis_item_tool_budget(reservation, succeeded=False)
        raise
    if (
        empty_query_state is not None
        and isinstance(result, dict)
        and result.get("ok") is True
        and result.get("value") is None
        and isinstance((receipt := result.get("readReceipt")), Mapping)
        and isinstance((snapshot_hash := receipt.get("snapshotHash")), str)
        and snapshot_hash
        and isinstance((receipt_id := receipt.get("receiptId")), str)
        and receipt_id
        and receipt.get("datasetId") == arguments.get("datasetId")
        and receipt.get("query") == arguments.get("query")
    ):
        empty_queries, query_identity = empty_query_state
        details = {
            "datasetId": arguments["datasetId"],
            "query": arguments["query"],
            "snapshotHash": snapshot_hash,
            "receiptId": receipt_id,
        }
        existing_empty = empty_queries.get(query_identity)
        if (
            isinstance(existing_empty, Mapping)
            and existing_empty.get("snapshotHash") == snapshot_hash
        ):
            result = _repeated_empty_profile_query_failure(existing_empty)
        else:
            # purpose 和 maxItems 不改变 JMESPath 在同一不可变快照上的结果，不能用来
            # 绕过去重。首次空回执保留；串行重复会在执行前短路，并行重复在完成时拒绝。
            empty_queries[query_identity] = details
    succeeded = isinstance(result, dict) and result.get("ok") is True
    _finish_reporting_analysis_item_tool_budget(reservation, succeeded=succeeded)
    return _enforce_reporting_no_progress(run_context, function_name, result, arguments)


def _review_content(payload: dict[str, Any]) -> str | None:
    review = payload.get("review")
    if not isinstance(review, dict):
        return None
    title = str(review.get("title") or "报表审核")
    message = str(review.get("message") or "").strip()
    preview = review.get("preview")
    parts = [f"## {title}"]
    if message:
        parts.append(message)
    if preview is not None:
        parts.append(f"```json\n{json.dumps(preview, ensure_ascii=False, indent=2)}\n```")
    return "\n\n".join(parts)


def _forced_review_response(
    messages: list[Message], *, stream: bool = False
) -> ModelResponse | None:
    for message in reversed(messages):
        if message.role != "tool":
            continue
        if message.tool_name not in _REPORT_FACADE_TOOL_NAMES:
            return None
        content = message.content
        if not isinstance(content, str):
            return None
        if message.tool_name == "report_workflow_start" and message.tool_call_error:
            return ModelResponse(
                content=f"报表工作流执行失败：{content}",
            )
        if message.tool_name == "report_workflow_approve" and message.tool_call_error:
            return _tool_response(
                "report_workflow_reject",
                {"feedback": content},
                stream=stream,
            )
        try:
            payload = json.loads(content)
        except ValueError:
            return None
        if not isinstance(payload, dict) or payload.get("status") != "paused":
            return None
        review = payload.get("review")
        stage = review.get("stage") if isinstance(review, dict) else None
        tool_name = (
            "report_workflow_review" if stage in {"request", "agent"} else "report_workflow_approve"
        )
        return _tool_response(
            tool_name,
            {},
            content=_review_content(payload),
            stream=stream,
        )
    return None


def _tool_response(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    content: str | None = None,
    stream: bool,
) -> ModelResponse:
    call_id = f"call-{tool_name.replace('_', '-')}-{uuid4().hex}"
    serialized_arguments = json.dumps(arguments, ensure_ascii=False)
    if stream:
        return ModelResponse(
            content=content,
            tool_calls=[
                cast(
                    Any,
                    ChoiceDeltaToolCall(
                        index=0,
                        id=call_id,
                        type="function",
                        function=ChoiceDeltaToolCallFunction(
                            name=tool_name,
                            arguments=serialized_arguments,
                        ),
                    ),
                )
            ],
        )
    return ModelResponse(
        content=content,
        tool_calls=[
            {
                "id": call_id,
                "type": "function",
                "function": {"name": tool_name, "arguments": serialized_arguments},
            }
        ],
    )


def _reporting_phase_from_messages(messages: list[Message]) -> ReportingPhase | None:
    _ = messages
    return reporting_phase_from_run_context(current_reporting_run_context())


def _reporting_request_uses_escalation(
    messages: list[Message],
    fields: tuple[str, ...],
) -> bool:
    if not fields:
        return False
    for message in reversed(messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, dict):
            payload = content
        elif isinstance(content, str):
            try:
                payload = json.loads(content)
            except json.JSONDecodeError:
                continue
        else:
            continue
        return isinstance(payload, dict) and any(payload.get(field) for field in fields)
    return False


def _report_model_tool_name(tool: Any) -> str | None:
    if isinstance(tool, dict):
        function = tool.get("function")
        if isinstance(function, dict) and isinstance(function.get("name"), str):
            return function["name"]
        return tool.get("name") if isinstance(tool.get("name"), str) else None
    name = getattr(tool, "name", None)
    return name if isinstance(name, str) else None


def _phase_filtered_report_tools(messages: list[Message], tools: Any) -> Any:
    phase = _reporting_phase_from_messages(messages)
    task_kind = reporting_task_kind_from_run_context(current_reporting_run_context())
    if phase is None or tools is None:
        return tools
    return [
        tool
        for tool in tools
        if (name := _report_model_tool_name(tool)) is not None
        and reporting_phase_allows_tool(phase, name, task_kind=task_kind)
    ]


def _report_worker_tools_cache_key(run_context: RunContext) -> str:
    """按调用者与受信阶段隔离 Agno callable-tool 缓存。"""

    identity = run_context.user_id or run_context.session_id or str(run_context.run_id)
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    task_id = binding.get("externalRunId") if isinstance(binding, Mapping) else None
    phase = reporting_phase_from_run_context(run_context) or "unbound"
    task_kind = reporting_task_kind_from_run_context(run_context) or "unbound"
    return f"report-worker:{identity}:{task_id or run_context.run_id}:{phase}:{task_kind}"


def _phase_filtered_report_messages(messages: list[Message]) -> list[Message]:
    phase = _reporting_phase_from_messages(messages)
    task_kind = reporting_task_kind_from_run_context(current_reporting_run_context())
    # 单项分析不生成图表，也不需要通用沙箱能力说明；章节阶段更不持有 Skill 工具。
    # 只为 visualization 保留 Agno Skill 提示，避免模型看到已被阶段白名单隐藏的入口。
    if phase != "section" and not (phase == "analysis" and task_kind == "analysis_item"):
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


def _with_reporting_durable_identities(messages: list[Message]) -> list[Message]:
    """在 Analysis 投影中固定保留 Profile 回执身份，不带回查询结果正文。

    工具正文可能被压缩，完整回合也可能因输入 hard cap 被移出窗口；但 receiptId、
    Dataset、snapshot 与查询节点决定了后续 complete_analysis_item 能否准确绑定事实。
    这里仅从当前 run 已成功返回的工具回执提取身份，不读取数据库、不复制 Profile value，
    也不把已取消 child task 的回执注入新任务。
    """

    if _reporting_phase_from_messages(messages) != "analysis":
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
        if (
            not isinstance(receipt_id, str)
            or not receipt_id
            or not isinstance(dataset_id, str)
            or not dataset_id
            or not isinstance(snapshot_hash, str)
            or not snapshot_hash
            or not isinstance(query, str)
            or not query
        ):
            continue
        identity: dict[str, str] = {
            "receiptId": receipt_id,
            "datasetId": dataset_id,
            "snapshotHash": snapshot_hash,
            "querySha256": hashlib.sha256(query.encode()).hexdigest(),
        }
        if len(query) <= _REPORT_PROFILE_QUERY_IDENTITY_MAX_LENGTH:
            identity["query"] = query
        receipts[receipt_id] = identity
    if not receipts:
        return messages
    ledger = {
        "marker": "REPORTING_DURABLE_IDENTITIES",
        "version": 1,
        "profileReadReceipts": list(receipts.values())[-_REPORT_PROFILE_RECEIPT_PROJECTION_LIMIT:],
    }
    return [
        *messages,
        Message(
            role="user",
            content=json.dumps(ledger, ensure_ascii=False, separators=(",", ":")),
        ),
    ]


def _phase_filtered_model_call(
    messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> tuple[tuple[Any, ...], dict[str, Any]]:
    updated_args = args
    updated_kwargs = dict(kwargs)
    if "tools" in updated_kwargs:
        updated_kwargs["tools"] = _phase_filtered_report_tools(
            messages, updated_kwargs.get("tools")
        )
    elif len(args) >= 3:
        positional = list(args)
        positional[2] = _phase_filtered_report_tools(messages, positional[2])
        updated_args = tuple(positional)
    return updated_args, updated_kwargs


class ReportingOpenAIChat(ProjectedOpenAIChat):
    """为所有 Reporting 模型提供统一、严格的 function-call 传输边界。"""

    _report_raw_tool_argument_errors = False

    def _phase_request_model(self, messages: list[Message]) -> "ReportingOpenAIChat":
        """为单次请求生成隔离配置，禁止并发 Section 修改共享 Worker 模型。"""

        base_profile = reporting_thinking_profile_from_model(self)
        profile = base_profile
        bound_effort = reporting_thinking_effort_from_run_context(current_reporting_run_context())
        if _reporting_phase_from_messages(messages) == "section" or bound_effort == "off":
            profile = ReportingThinkingProfile.off(temperature=base_profile.temperature)
        elif bound_effort in {"high", "max"}:
            budget = base_profile.thinking_budget
            if budget is None:
                raise ValueError("Reporting Worker 缺少 thinking_budget，无法应用请求档位")
            profile = ReportingThinkingProfile.on(
                reasoning_effort=bound_effort,
                thinking_budget=budget,
                temperature=base_profile.temperature,
            )
        else:
            escalation_profile = getattr(self, "_report_escalation_thinking_profile", None)
            escalation_fields = getattr(self, "_report_thinking_escalation_fields", ())
            if isinstance(escalation_profile, ReportingThinkingProfile) and (
                isinstance(escalation_fields, tuple)
                and _reporting_request_uses_escalation(messages, escalation_fields)
            ):
                profile = escalation_profile
        request_model = copy(self)
        return apply_reporting_thinking_profile(request_model, profile)

    @staticmethod
    def _validated_reporting_response(
        model: "ReportingOpenAIChat",
        response: ModelResponse,
    ) -> ModelResponse:
        validator = getattr(model, "_report_response_validator", None)
        if callable(validator):
            response.content = validator(response.content)
        return response

    def _clear_report_run_error(self) -> None:
        _REPORT_MODEL_RUN_ERROR.set(None)

    def _record_report_run_error(self, error: Exception) -> None:
        _REPORT_MODEL_RUN_ERROR.set((id(self), error))

    def report_run_error(self) -> Exception | None:
        recorded = _REPORT_MODEL_RUN_ERROR.get()
        return recorded[1] if recorded is not None and recorded[0] == id(self) else None

    def response(
        self,
        messages: list[Message],
        *args: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        self._clear_report_run_error()
        request_model = self._phase_request_model(messages)
        try:
            response = ProjectedOpenAIChat.response(request_model, messages, *args, **kwargs)
            self._clear_report_run_error()
            return self._validated_reporting_response(request_model, response)
        except Exception as error:
            self._record_report_run_error(error)
            raise

    async def aresponse(
        self,
        messages: list[Message],
        *args: Any,
        **kwargs: Any,
    ) -> ModelResponse:
        self._clear_report_run_error()
        request_model = self._phase_request_model(messages)
        try:
            response = await ProjectedOpenAIChat.aresponse(
                request_model,
                messages,
                *args,
                **kwargs,
            )
            self._clear_report_run_error()
            return self._validated_reporting_response(request_model, response)
        except Exception as error:
            self._record_report_run_error(error)
            raise

    def response_stream(
        self,
        messages: list[Message],
        *args: Any,
        **kwargs: Any,
    ) -> Iterator[ModelResponse | RunOutputEvent | TeamRunOutputEvent]:
        self._clear_report_run_error()
        request_model = self._phase_request_model(messages)
        try:
            yield from ProjectedOpenAIChat.response_stream(
                request_model,
                messages,
                *args,
                **kwargs,
            )
            self._clear_report_run_error()
        except Exception as error:
            self._record_report_run_error(error)
            raise

    async def aresponse_stream(
        self,
        messages: list[Message],
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[ModelResponse | RunOutputEvent | TeamRunOutputEvent]:
        self._clear_report_run_error()
        request_model = self._phase_request_model(messages)
        try:
            async for response in ProjectedOpenAIChat.aresponse_stream(
                request_model,
                messages,
                *args,
                **kwargs,
            ):
                yield response
            self._clear_report_run_error()
        except Exception as error:
            self._record_report_run_error(error)
            raise

    def _format_message(
        self,
        message: Message,
        compress_tool_results: bool = False,
    ) -> dict[str, Any]:
        formatted = super()._format_message(message, compress_tool_results)
        # DeepSeek thinking 模式要求工具往返时回传本轮 reasoning_content；普通文本轮次
        # 不回传，避免扩大上下文。该字段只进入模型请求，终态仍由 post hook 清除。
        if (
            message.role == "assistant"
            and message.tool_calls
            and isinstance(message.reasoning_content, str)
            and message.reasoning_content
        ):
            formatted["reasoning_content"] = message.reasoning_content
        return formatted

    def _strict_reporting_tool_calls(
        self,
        assistant_message: Message,
        messages: list[Message],
        functions: dict[str, Any] | None,
    ) -> list[Any]:
        run_context = current_reporting_run_context()
        allowed_calls = []
        blocked = []
        for tool_call in list(assistant_message.tool_calls or []):
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, (str, bytes, bytearray)):
                try:
                    decoded = json.loads(arguments)
                    decode_error: json.JSONDecodeError | TypeError | None = None
                except json.JSONDecodeError as error:
                    decoded = None
                    decode_error = error
            else:
                decoded = None
                decode_error = TypeError("Arguments must be a JSON string")
            if isinstance(decoded, dict):
                _clear_reporting_argument_error(run_context, name)
                allowed_calls.append(tool_call)
                continue
            if self._report_raw_tool_argument_errors:
                if decode_error is not None:
                    raise decode_error
                raise TypeError("Top-level JSON value must be an object")
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if not isinstance(call_id, str) or not call_id:
                allowed_calls.append(tool_call)
                continue
            blocked.append(
                Message(
                    role=self.tool_message_role,
                    tool_call_id=call_id,
                    tool_name=name,
                    content=json.dumps(
                        _reporting_invalid_argument_receipt(
                            run_context,
                            name,
                            arguments,
                            decode_error,
                            schema_hint=_reporting_tool_schema_hint(name, functions),
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        if blocked:
            messages.extend(blocked)
        return allowed_calls

    def _run_reporting_tool_calls(
        self,
        assistant_message: Message,
        messages: list[Message],
        functions: dict[str, Any] | None,
        tool_calls: list[Any],
    ) -> list[Any]:
        if not tool_calls:
            return []
        if tool_calls == list(assistant_message.tool_calls or []):
            filtered_message = assistant_message
        else:
            filtered_message = deepcopy(assistant_message)
            filtered_message.tool_calls = tool_calls
        return super().get_function_calls_to_run(filtered_message, messages, functions)

    def get_function_calls_to_run(
        self,
        assistant_message: Message,
        messages: list[Message],
        functions: dict[str, Any] | None = None,
    ) -> list[Any]:
        return self._run_reporting_tool_calls(
            assistant_message,
            messages,
            functions,
            self._strict_reporting_tool_calls(assistant_message, messages, functions),
        )


class ReportWorkerOpenAIChat(ReportingOpenAIChat):
    """Reporting Worker 在通过正式验收后确定性收敛到 finish_task。"""

    _report_vision_enabled = True
    _report_raw_tool_argument_errors = True

    async def arun_function_calls(
        self,
        function_calls: Any,
        function_call_results: Any,
        *args: Any,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        async for event in super().arun_function_calls(
            function_calls,
            function_call_results,
            *args,
            **kwargs,
        ):
            error = _take_reporting_tool_run_error()
            if error is not None:
                raise error
            yield event
        error = _take_reporting_tool_run_error()
        if error is not None:
            raise error

    def get_function_calls_to_run(
        self,
        assistant_message: Message,
        messages: list[Message],
        functions: dict[str, Any] | None = None,
    ) -> list[Any]:
        """把 phase 外工具和过期的 view_image 调用转成有界工具回执。

        工具 schema 会按内部 run 投影，但模型仍可能生成旧 schema 中的调用。执行前必须
        同步拒绝，避免 Agno 生成 Function not found 后继续扩大无效历史。
        """
        phase = _reporting_phase_from_messages(messages)
        tool_calls = self._strict_reporting_tool_calls(
            assistant_message,
            messages,
            functions,
        )
        allowed_calls = []
        blocked = []
        for tool_call in tool_calls:
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            phase_forbidden = (
                isinstance(name, str)
                and phase in {"analysis", "section"}
                and not reporting_phase_allows_tool(
                    phase,
                    name,
                    task_kind=reporting_task_kind_from_run_context(current_reporting_run_context()),
                )
            )
            vision_disabled = name == "view_image" and not getattr(
                self, "_report_vision_enabled", True
            )
            if not phase_forbidden and not vision_disabled:
                allowed_calls.append(tool_call)
                continue
            if not isinstance(call_id, str) or not call_id:
                allowed_calls.append(tool_call)
                continue
            blocked.append(
                Message(
                    role=self.tool_message_role,
                    tool_call_id=call_id,
                    tool_name=name,
                    content=json.dumps(
                        (
                            {
                                "ok": False,
                                "status": "rejected",
                                "code": "report_phase_tool_forbidden",
                                "message": "当前 Reporting phase 不允许调用该工具，请使用本阶段已提供工具继续。",
                            }
                            if phase_forbidden
                            else {
                                "ok": False,
                                "status": "skipped",
                                "code": "report_vision_disabled",
                                "message": "当前 Reporting Worker 未启用图片视觉工具，继续使用文本和文件证据。",
                            }
                        ),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
            # phase admission 在工具执行前发生；同一模型响应可能含多个并行调用，
            # 拒绝回执仍逐项写入消息供下一轮纠正。
        if blocked:
            messages.extend(blocked)
        return self._run_reporting_tool_calls(
            assistant_message,
            messages,
            functions,
            allowed_calls,
        )

    def count_tokens(
        self,
        messages: list[Message],
        tools: Any = None,
        output_schema: Any = None,
    ) -> int:
        messages = _phase_filtered_report_messages(messages)
        return super().count_tokens(
            messages,
            _phase_filtered_report_tools(messages, tools),
            output_schema=output_schema,
        )

    def _project(self, messages: list[Message], args: tuple[Any, ...], kwargs: dict[str, Any]):
        response_format = kwargs.get("response_format", args[1] if len(args) > 1 else None)
        tools = kwargs.get("tools", args[2] if len(args) > 2 else None)
        configured_cap = getattr(self, "_coding_input_token_budget", None)
        if (
            isinstance(configured_cap, bool)
            or not isinstance(configured_cap, int)
            or configured_cap < 1
        ):
            configured_cap = CODING_CONTEXT_TOKEN_LIMIT - CODING_OUTPUT_TOKEN_RESERVE
        phase = _reporting_phase_from_messages(messages)
        phase_cap = (
            REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP
            if phase == "analysis"
            else REPORTING_SECTION_INPUT_TOKEN_HARD_CAP
            if phase == "section"
            else None
        )
        hard_cap = min(configured_cap, phase_cap) if phase_cap is not None else configured_cap

        def filter_and_bind_tools(current_tools: Any) -> Any:
            filtered = _phase_filtered_report_tools(messages, current_tools)
            if filtered is current_tools:
                return current_tools
            if "tools" in kwargs:
                kwargs["tools"] = filtered
            return filtered

        tools = filter_and_bind_tools(tools)
        identity_messages = _with_reporting_durable_identities(messages)
        projected = CodingContextProjector.project(
            identity_messages,
            model=self,
            tools=tools,
            response_format=response_format,
            hard_cap=hard_cap,
        )
        metrics = dict(CodingContextProjector.last_metrics)
        record_reporting_projection_metrics(metrics, input_token_hard_cap=hard_cap)
        return projected, metrics

    def invoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        messages = _phase_filtered_report_messages(messages)
        args, kwargs = _phase_filtered_model_call(messages, args, kwargs)
        return super().invoke(messages, *args, **kwargs)

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        messages = _phase_filtered_report_messages(messages)
        args, kwargs = _phase_filtered_model_call(messages, args, kwargs)
        return await super().ainvoke(messages, *args, **kwargs)

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        messages = _phase_filtered_report_messages(messages)
        args, kwargs = _phase_filtered_model_call(messages, args, kwargs)
        yield from super().invoke_stream(messages, *args, **kwargs)

    async def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        messages = _phase_filtered_report_messages(messages)
        args, kwargs = _phase_filtered_model_call(messages, args, kwargs)
        async for response in super().ainvoke_stream(messages, *args, **kwargs):
            yield response


class ReportFacadeOpenAIChat(ReportingOpenAIChat):
    """把内层 Workflow 暂停确定性提升为 facade Agent HITL。"""

    def invoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        return _forced_review_response(messages) or super().invoke(messages, *args, **kwargs)

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        return _forced_review_response(messages) or await super().ainvoke(messages, *args, **kwargs)

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        forced = _forced_review_response(messages, stream=True)
        if forced is not None:
            yield forced
            return
        yield from super().invoke_stream(messages, *args, **kwargs)

    async def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        forced = _forced_review_response(messages, stream=True)
        if forced is not None:
            yield forced
            return
        async for response in super().ainvoke_stream(messages, *args, **kwargs):
            yield response


def _report_facade_model(model: ProjectedOpenAIChat) -> ReportFacadeOpenAIChat:
    facade = ReportFacadeOpenAIChat(
        **{field.name: getattr(model, field.name) for field in fields(model)}
    )
    budget = getattr(model, "_coding_input_token_budget", None)
    if isinstance(budget, int) and budget > 0:
        facade._coding_input_token_budget = budget
    return facade


def _report_worker_model(
    model: OpenAIChat,
    *,
    input_token_budget: int | None = None,
) -> ReportWorkerOpenAIChat:
    projected = projected_coding_model(model, input_token_budget=input_token_budget)
    worker = ReportWorkerOpenAIChat(
        **{field.name: getattr(projected, field.name) for field in fields(projected)}
    )
    budget = getattr(projected, "_coding_input_token_budget", None)
    if isinstance(budget, int) and budget > 0:
        worker._coding_input_token_budget = budget
    return worker


def _report_model(
    settings: AgentSettings,
    *,
    enable_thinking: bool,
    retries: int = 2,
    timeout_seconds: int | None = None,
) -> OpenAIChat:
    return OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=(settings.model_timeout_seconds if timeout_seconds is None else timeout_seconds),
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": enable_thinking},
        temperature=1.0,
        top_p=1.0,
        collect_metrics_on_completion=(
            urlparse(settings.openai_base_url).hostname in _CUMULATIVE_STREAM_USAGE_HOSTS
        ),
        retries=retries,
        exponential_backoff=retries > 0,
    )


def create_report_worker(
    settings: AgentSettings,
    database: AsyncBaseDb,
    workspace_service: WorkspaceService,
    task_repository: TaskExecutionRepository,
    *,
    state_repository: ReportingStateRepository,
) -> Agent:
    # settings 是 Report Worker 的唯一配置事实源。直接构造与 AgentOS 装配必须使用
    # 同一组 Reporting 预算，不能静默退回普通 Coding Agent 的 256K/32K 默认值。
    context_token_budget = settings.report_context_token_budget
    output_token_reserve = settings.report_output_token_reserve
    reporting_skills = load_reporting_skills(load_sandbox_execution_skills(settings.skills_dir))
    vision_reviewer = (
        ReportVisionReviewer(settings, workspace_service) if settings.report_enable_vision else None
    )
    input_token_budget = max(
        1,
        min(context_token_budget, CODING_CONTEXT_TOKEN_LIMIT)
        - max(CODING_OUTPUT_TOKEN_RESERVE, output_token_reserve),
    )
    worker_model = _report_worker_model(
        _report_model(
            settings,
            enable_thinking=settings.report_coding_enable_thinking,
            retries=0,
            timeout_seconds=min(
                settings.model_timeout_seconds,
                _REPORT_WORKER_MODEL_TIMEOUT_CAP_SECONDS,
            ),
        ),
        input_token_budget=input_token_budget,
    )
    worker_model._report_vision_enabled = settings.report_enable_vision
    worker_model.max_tokens = output_token_reserve
    worker_profile = (
        ReportingThinkingProfile.on(
            reasoning_effort=cast(
                ReportingReasoningEffort,
                settings.report_coding_reasoning_effort,
            ),
            thinking_budget=settings.report_coding_thinking_budget,
            temperature=settings.report_coding_temperature,
        )
        if settings.report_coding_enable_thinking
        else ReportingThinkingProfile.off(temperature=settings.report_coding_temperature)
    )
    apply_reporting_thinking_profile(worker_model, worker_profile)
    worker_model.top_p = 0.95
    worker_compression_manager = (
        ContextBudgetController(
            model=worker_model,
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
        )
        if settings.enable_tool_result_compression
        else None
    )
    worker = Agent(
        id="report-worker",
        name="智能报表 Worker",
        role="根据已批准的分析计划和不可变数据集执行受控 Coding 分析。",
        model=worker_model,
        instructions=build_report_agent_instructions,
        use_instruction_tags=True,
        skills=reporting_skills,
        tools=partial(
            build_report_worker_tools,
            workspace_service,
            task_repository,
            state_repository=state_repository,
            vision_reviewer=vision_reviewer,
        ),
        callable_tools_cache_key=_report_worker_tools_cache_key,
        db=database,
        checkpoint="tool-batch",
        add_history_to_context=False,
        # 每个 Reporting Task 使用独立 session，恢复事实来自 durable state 和
        # Agno checkpoint；摘要既不加入上下文，也没有后续消费者。若沿用全局开关，
        # Agno 会在工具完成后再次把整份分析/图表上下文提交给摘要模型，单次超时还会
        # 按模型重试策略阻塞 Workflow，因此在 Report Worker 边界固定关闭。
        enable_session_summaries=False,
        add_session_summary_to_context=False,
        session_summary_manager=None,
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=worker_compression_manager,
        retries=0,
        exponential_backoff=False,
        post_hooks=[clear_terminal_reasoning],
        tool_hooks=[
            propagate_reporting_tool_errors,
            normalize_reporting_tool_arguments,
            create_task_tool_scheduler_hook(task_repository),
            create_skill_script_hook(workspace_service),
        ],
        debug_mode=settings.debug,
        markdown=True,
        send_media_to_model=False,
        tool_choice="auto",
    )
    worker.num_history_runs = None
    return worker


def create_report_agent(
    report_worker: Agent,
    controller: ReportWorkflowController,
) -> Agent:
    """创建公开 facade；实际分析只由 Workflow 内的 report-worker 执行。"""
    if not isinstance(report_worker.model, ProjectedOpenAIChat):
        raise TypeError("Report facade requires ProjectedOpenAIChat")
    facade_model = _report_facade_model(report_worker.model)
    apply_reporting_thinking_profile(
        facade_model,
        ReportingThinkingProfile.off(temperature=1.0),
    )
    facade_model.top_p = 0.95
    facade_model.retries = 2
    facade_model.exponential_backoff = True
    facade_compression_manager = None
    if report_worker.compress_tool_results:
        if not isinstance(report_worker.compression_manager, ContextBudgetController):
            raise TypeError("Report worker requires ContextBudgetController")
        facade_compression_manager = ContextBudgetController(
            model=facade_model,
            context_token_budget=report_worker.compression_manager.context_token_limit,
            output_token_reserve=report_worker.compression_manager.output_token_reserve,
        )
    facade_tool_hooks = [
        hook
        for hook in (report_worker.tool_hooks or [])
        if hook is not propagate_reporting_tool_errors
        and not is_skill_script_hook(hook)
        and not is_task_tool_scheduler_hook(hook)
    ]

    def workflow_tools(
        *, run_context: RunContext | None = None, agent: Agent | None = None
    ) -> list[ReportWorkflowToolkit]:
        _ = run_context, agent
        return [ReportWorkflowToolkit(controller)]

    facade = report_worker.deep_copy(
        update={
            "id": "report-agent",
            "name": "智能报表",
            "role": "通过受控 Workflow 编排来源确认、分析、验收和发布审核。",
            "model": facade_model,
            "retries": 0,
            "exponential_backoff": False,
            "compression_manager": facade_compression_manager,
            "checkpoint": None,
            "instructions": [
                "普通聊天问题直接回答，不调用报表工具；只有用户明确要求生成、分析或导出报表时，才调用"
                "无参数的 report_workflow_start。该工具会读取受信服务端 Envelope，或把当前"
                "最后一条用户消息按 CLI 相同规则解析为自然语言或 ReportRequestEnvelope JSON，再交给 "
                "Workflow 首步。不得自行解析期间、改写目标、取数、执行 Coding "
                "或生成报告。Workflow 返回 request 阶段 paused 时，向用户"
                "展示 clarificationQuestion，并由 report_workflow_review 的 AgentOS 用户输入收集补充原文，"
                "使 Workflow 首步按官方 HumanReview retry 继续归一化。",
                "任一报表工具返回普通审核 paused 时，系统会先准确展示当前 review 预览，再在同一 "
                "run 中确定性调用 report_workflow_approve，由 AgentOS 原生确认收集批准或拒绝；"
                "拒绝备注由系统确定性交给 Workflow，不得由模型生成或改写。request 阶段"
                "仍调用 report_workflow_review 收集对应输入；"
                "不得在文本回答中询问审批、猜测审批动作或宣称没有进行中的 Workflow。"
                "审核工具返回 paused 时重复本流程。",
                "工具返回 completed 后只返回其正式报告产物；不得把 paused、running 或 failed "
                "描述为完成。当前发布契约只返回已核验的 Workspace 路径：PDF 使用 `path`，Word 使用 "
                "`word.path`；必须逐字保留工具返回的相对路径，不得补充域名、协议、下载授权或改写为示例地址，"
                "也不得虚构 `downloadUrl`。",
            ],
            "tools": workflow_tools,
            "skills": None,
            "tool_hooks": facade_tool_hooks,
            "tool_choice": "auto",
        }
    )
    facade.num_history_runs = None
    return facade
