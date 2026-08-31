import ast
import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextvars import ContextVar
from copy import copy, deepcopy
from dataclasses import fields
from functools import partial
from time import perf_counter
from typing import Any, Literal, cast
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
from loguru import logger
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
from ..model_config import OPENAI_COMPATIBLE_ROLE_MAP, openai_compatible_extra_body
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
from .models import ReportingError, VisualizationSkillCacheEntry
from .phase import (
    REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
    REPORTING_ANALYSIS_FACT_QUERY_LIMIT,
    REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY,
    REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP,
    REPORTING_SECTION_INPUT_TOKEN_HARD_CAP,
    REPORTING_TASK_DEPENDENCY,
    REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_EXPLORATION_TOOL_NAMES,
    REPORTING_VISUALIZATION_FACT_QUERY_LIMIT,
    REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_PRODUCTION_ONLY_STATE_KEY,
    REPORTING_VISUALIZATION_PRODUCTION_TOOL_NAMES,
    REPORTING_VISUALIZATION_READ_FILE_LIMIT,
    REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY,
    REPORTING_VISUALIZATION_SKILL_CACHE_STATE_KEY,
    REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY,
    ReportingPhase,
    current_reporting_run_context,
    record_reporting_projection_metrics,
    reporting_analysis_fact_usage_from_run_context,
    reporting_analysis_recovery_from_run_context,
    reporting_phase_allows_tool,
    reporting_phase_from_run_context,
    reporting_task_kind_from_run_context,
    reporting_thinking_effort_from_run_context,
    reporting_visual_inspection_mode_from_run_context,
    reporting_visualization_exploration_budget_exhausted_from_run_context,
    reporting_visualization_exploration_count,
    reporting_visualization_production_only_from_run_context,
    reporting_visualization_recovery_from_run_context,
    reporting_visualization_registered_from_run_context,
    reporting_visualization_script_session_available_from_run_context,
    reporting_visualization_usage_from_run_context,
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
# 可视化的第一次 attempt 最多执行 48 次工具；fresh retry 从受信契约恢复累计计数，
# 两轮合计不得超过 64 次。失败调用同样消耗预算，避免通过不断更换错误参数绕过上限。
# finalize 是登记后的单向收尾，不计入预算；确定性脚本失败最多允许 3 次。
_REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT = 48
_REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT = 64
_REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT = 3
_REPORT_VISUALIZATION_REGISTERED_STATE_KEY = "agentos_reporting_visualization_registered"
_REPORT_PROFILE_EMPTY_QUERY_STATE_KEY = "agentos_reporting_empty_profile_queries"
_REPORT_ARGUMENT_MAX_ISSUES = 8
_REPORT_ARGUMENT_MAX_TOP_LEVEL_KEYS = 32
_REPORT_ARGUMENT_MAX_LOC_LENGTH = 256


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))


_REPORT_ARGUMENT_MAX_MESSAGE_LENGTH = 512
_REPORT_PROFILE_RECEIPT_PROJECTION_LIMIT = 100
_REPORT_PROFILE_QUERY_IDENTITY_MAX_LENGTH = 256
_REPORT_TOOL_RUN_ERROR_ATTR = "_agentos_reporting_tool_run_error"
# Reporting 的全局 reserve 用于上下文预算，不能直接作为每次模型请求的生成额度。
# 章节与单项分析只需提交一个有界终态工具，16K 足以覆盖工具参数；可视化汇总需要
# 更长的脚本参数和 ReportBrief。真实 CLI 已证明 32K 会在工具调用前截断，因此
# visualization 使用 64K；仍不直接放开到全局 reserve，避免兼容后端过量预分配。
_REPORT_ANALYSIS_ITEM_OUTPUT_TOKEN_LIMIT = 16 * 1024
_REPORT_VISUALIZATION_OUTPUT_TOKEN_LIMIT = 64 * 1024
_REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT = 16 * 1024
_REPORT_SECTION_OUTPUT_TOKEN_LIMIT = 16 * 1024
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


def _reporting_tool_run_error_is_terminal() -> bool:
    run_context = current_reporting_run_context()
    error = (
        getattr(run_context, _REPORT_TOOL_RUN_ERROR_ATTR, None) if run_context is not None else None
    )
    return _is_terminal_reporting_error(error)


def _is_terminal_reporting_error(error: Any) -> bool:
    return (
        isinstance(error, ReportingError)
        and isinstance(error.details, dict)
        and error.details.get("terminalReason")
        in {"tool_no_progress", "visualization_exploration_budget_exhausted"}
    )


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
        # Agno Function.aexecute 会把普通异常转换成失败工具消息。只抛出并不足以
        # 触发 Agent retry，因此在共享 RunContext 记录原对象，由模型批次边界立即重抛。
        _record_reporting_tool_run_error(run_context, error)
        raise


def _reporting_session_state(run_context: RunContext) -> dict[str, Any] | None:
    return run_context.session_state if isinstance(run_context.session_state, dict) else None


_VISUALIZATION_SKILL_CACHE_LOCKS: dict[str, asyncio.Lock] = {}
_VISUALIZATION_SKILL_CACHE_MAX_LOCKS = 128


def _visualization_skill_cache_key(
    run_context: RunContext,
    function_name: str,
    arguments: Mapping[str, Any],
) -> str | None:
    # 只读 Skill 结果可以在同一可视化 run 内复用；身份和参数必须完整参与键值，
    # 防止不同用户、任务、重试或 Skill 路径之间发生结果串用。
    if function_name not in {"get_skill_instructions", "get_skill_reference"}:
        return None
    if reporting_phase_from_run_context(run_context) != "analysis":
        return None
    if reporting_task_kind_from_run_context(run_context) not in {
        "visualization_section",
        "visualization_finalize",
    }:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    external_run_id = binding.get("externalRunId")
    if not isinstance(external_run_id, str) or not external_run_id:
        return None
    try:
        normalized = json.dumps(
            arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError):
        return None
    identity = {
        "externalRunId": external_run_id,
        "runId": str(run_context.run_id or ""),
        "sessionId": str(run_context.session_id or ""),
        "userId": str(run_context.user_id or ""),
        "tool": function_name,
        "arguments": normalized,
    }
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _cached_visualization_skill_result(
    run_context: RunContext,
    cache_key: str | None,
) -> Any:
    state = _reporting_session_state(run_context)
    if state is None or cache_key is None:
        return None
    cache = state.get(REPORTING_VISUALIZATION_SKILL_CACHE_STATE_KEY)
    if not isinstance(cache, Mapping) or cache_key not in cache:
        return None
    try:
        entry = VisualizationSkillCacheEntry.model_validate(cache[cache_key])
    except ValidationError:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    external_run_id = binding.get("externalRunId")
    expected_user_id = str(run_context.user_id or "anonymous")
    if (
        entry.run_id != str(run_context.run_id or "")
        or entry.session_id != str(run_context.session_id or "")
        or entry.user_id != expected_user_id
        or entry.external_run_id != external_run_id
        or entry.tool_name not in {"get_skill_instructions", "get_skill_reference"}
    ):
        return None
    return entry.result


def _cache_visualization_skill_result(
    run_context: RunContext,
    cache_key: str | None,
    function_name: str,
    result: Any,
) -> None:
    if cache_key is None:
        return
    state = _reporting_session_state(run_context)
    if state is None:
        return
    try:
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    external_run_id = binding.get("externalRunId")
    if not isinstance(external_run_id, str) or not external_run_id:
        return
    try:
        entry = VisualizationSkillCacheEntry(
            runId=str(run_context.run_id or ""),
            sessionId=str(run_context.session_id or ""),
            userId=str(run_context.user_id or "anonymous"),
            externalRunId=external_run_id,
            toolName=cast(Literal["get_skill_instructions", "get_skill_reference"], function_name),
            result=result,
        )
    except ValidationError:
        return
    cache = state.setdefault(REPORTING_VISUALIZATION_SKILL_CACHE_STATE_KEY, {})
    if isinstance(cache, dict):
        cache[cache_key] = entry.model_dump(mode="json", by_alias=True)
        while len(cache) > 64:
            cache.pop(next(iter(cache)))


def _reporting_mutation_sequence(state: dict[str, Any] | None) -> int:
    progress = state.get("agentos_coding_tool_progress") if isinstance(state, dict) else None
    return int(progress.get("mutation", 0)) if isinstance(progress, dict) else 0


def _reporting_analysis_item_tool_budget(
    run_context: RunContext,
    function_name: str,
) -> tuple[dict[str, Any], str, str] | None:
    if function_name != "complete_analysis_item" and (
        reporting_phase_from_run_context(run_context) == "analysis"
        and reporting_task_kind_from_run_context(run_context) == "analysis_item"
    ):
        return _reporting_success_tool_budget(
            run_context,
            task_kind="analysis_item",
            state_key=_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_STATE_KEY,
            limit=_REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT,
        )
    return None


def _reporting_success_tool_budget(
    run_context: RunContext,
    *,
    task_kind: str,
    state_key: str,
    limit: int,
) -> tuple[dict[str, Any], str, str] | None:
    """为单个内部 Reporting Task 预留成功工具调用名额。"""

    state = _reporting_session_state(run_context)
    if state is None:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    external_run_id = binding.get("externalRunId") if isinstance(binding, Mapping) else None
    # 每个 analysis item 尝试都有独立 externalRunId/internal run。预算身份同时绑定二者，
    # continuation 可继承当前计数，而 fresh retry、其他分析项和并发 Task 必须从零开始。
    identity = f"{external_run_id or ''}:{run_context.run_id or ''}"
    budgets = state.get(state_key)
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
    if successful_count + in_flight_count >= limit:
        _stop_exhausted_reporting_tool_budget(
            run_context,
            successful_count,
            in_flight_count,
            task_kind=task_kind,
            limit=limit,
        )
    budgets[identity] = {
        "successfulCount": successful_count,
        "inFlightCount": in_flight_count + 1,
    }
    state[state_key] = budgets
    return state, identity, state_key


def _visualization_exploration_limit(run_context: RunContext, function_name: str) -> int | None:
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}

    def limit(key: str, default: int) -> int:
        value = binding.get(key)
        return (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else default
        )

    counted_tool_name = "read_file" if function_name == "read_tool_output" else function_name
    if counted_tool_name == "query_analysis_facts":
        return limit(
            REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
            REPORTING_VISUALIZATION_FACT_QUERY_LIMIT,
        )
    if counted_tool_name == "read_file":
        return limit(
            REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY,
            REPORTING_VISUALIZATION_READ_FILE_LIMIT,
        )
    return None


def _analysis_fact_query_limit(run_context: RunContext) -> int:
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    value = (
        binding.get(REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY)
        if isinstance(binding, Mapping)
        else None
    )
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else REPORTING_ANALYSIS_FACT_QUERY_LIMIT
    )


def _reserve_analysis_fact_query(
    run_context: RunContext,
    function_name: str,
) -> tuple[dict[str, Any], str] | None:
    if (
        function_name != "query_analysis_facts"
        or reporting_phase_from_run_context(run_context) != "analysis"
        or reporting_task_kind_from_run_context(run_context) != "analysis_item"
    ):
        return None
    state = _reporting_session_state(run_context)
    if state is None:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
    budgets = state.get(REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY)
    budgets = budgets if isinstance(budgets, dict) else {}
    stored = budgets.get(identity)
    stored = stored if isinstance(stored, dict) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    budgets[identity] = {
        "queriesUsed": count(stored.get("queriesUsed")),
        "inFlightQueries": count(stored.get("inFlightQueries")) + 1,
    }
    state[REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY] = budgets
    return state, identity


def _finish_analysis_fact_query(
    reservation: tuple[dict[str, Any], str] | None,
) -> None:
    if reservation is None:
        return
    state, identity = reservation
    budgets = state.get(REPORTING_ANALYSIS_FACT_TOOL_BUDGET_STATE_KEY)
    if not isinstance(budgets, dict) or not isinstance((stored := budgets.get(identity)), dict):
        return

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    budgets[identity] = {
        "queriesUsed": count(stored.get("queriesUsed")) + 1,
        "inFlightQueries": max(count(stored.get("inFlightQueries")) - 1, 0),
    }


def _stop_analysis_fact_query_budget(run_context: RunContext) -> None:
    details = {
        "queryCount": reporting_analysis_fact_usage_from_run_context(run_context),
        "queryLimit": _analysis_fact_query_limit(run_context),
    }
    error = ReportingError(
        "report_analysis_fact_query_budget_exhausted",
        "当前分析项已达到 facts 查询上限，已停止本次 run。",
        details=details,
    )
    _record_reporting_tool_run_error(run_context, error)
    setattr(error, REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR, details)
    serialized = json.dumps(
        {
            "ok": False,
            "status": "rejected",
            "code": error.code,
            "message": error.message,
            "requiredActions": ["结束本次 run，使用已内联的受信 facts 完成当前分析项。"],
            "retryable": False,
            "details": details,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raise StopAgentRun(serialized, agent_message=serialized)


def _stop_analysis_recovery(run_context: RunContext) -> None:
    error = ReportingError(
        "report_analysis_recovery_closed",
        "分析项 facts 恢复任务只能调用 complete_analysis_item。",
    )
    _record_reporting_tool_run_error(run_context, error)
    serialized = json.dumps(
        {
            "ok": False,
            "status": "rejected",
            "code": error.code,
            "message": error.message,
            "requiredActions": ["使用 instruction 中已内联的受信 facts，立即完成当前分析项。"],
            "retryable": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raise StopAgentRun(serialized, agent_message=serialized)


def _visualization_exploration_budget_receipt(
    run_context: RunContext,
    function_name: str,
) -> dict[str, Any] | None:
    if reporting_phase_from_run_context(
        run_context
    ) != "analysis" or reporting_task_kind_from_run_context(run_context) not in {
        "visualization_section",
        "visualization_finalize",
    }:
        return None
    # fresh recovery 只允许 read_file/read_tool_output 恢复已提交脚本；实际路径仍由
    # Toolkit 的脚本身份门禁校验。这不是 facts/evidence 探索，不能被旧探索预算拦截。
    if reporting_visualization_recovery_from_run_context(run_context) and function_name in {
        "read_file",
        "read_tool_output",
    }:
        return None
    limit = _visualization_exploration_limit(run_context, function_name)
    is_exploration = function_name in REPORTING_VISUALIZATION_EXPLORATION_TOOL_NAMES
    if not is_exploration:
        return None
    counted_tool_name = "read_file" if function_name == "read_tool_output" else function_name
    if reporting_visualization_exploration_budget_exhausted_from_run_context(run_context):
        if reporting_visualization_exploration_count(run_context, "query_analysis_facts") >= (
            _visualization_exploration_limit(run_context, "query_analysis_facts")
            or REPORTING_VISUALIZATION_FACT_QUERY_LIMIT
        ):
            counted_tool_name = "query_analysis_facts"
            limit = _visualization_exploration_limit(run_context, counted_tool_name) or (
                REPORTING_VISUALIZATION_FACT_QUERY_LIMIT
            )
        else:
            counted_tool_name = "read_file"
            limit = _visualization_exploration_limit(run_context, counted_tool_name) or (
                REPORTING_VISUALIZATION_READ_FILE_LIMIT
            )
    current_count = reporting_visualization_exploration_count(run_context, counted_tool_name)
    if (
        not reporting_visualization_recovery_from_run_context(run_context)
        and not reporting_visualization_exploration_budget_exhausted_from_run_context(run_context)
        and (limit is None or current_count < limit)
    ):
        return None
    usage = reporting_visualization_usage_from_run_context(run_context)
    failure_fingerprint = hashlib.sha256(
        json.dumps(
            {
                "code": "report_visualization_exploration_budget_exhausted",
                "tool": counted_tool_name,
                "currentCount": current_count,
                "limit": limit,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return {
        "ok": False,
        "status": "rejected",
        "code": "report_visualization_exploration_budget_exhausted",
        "message": "可视化事实探索已达到独立上限，请立即进入图表产出阶段。",
        "requiredActions": [
            "停止读取事实和文件；复用当前上下文，直接创建或执行图表脚本。",
        ],
        "retryable": False,
        "details": {
            "tool": counted_tool_name,
            "currentCount": current_count,
            "limit": limit,
            "phaseState": "production_only",
            "terminalReason": "visualization_exploration_budget_exhausted",
            "failureFingerprint": failure_fingerprint,
            "visualizationUsage": usage,
            "allowedTerminalTools": [
                "register_report_charts",
                "finalize_report_analysis",
            ],
        },
    }


def _reporting_visualization_tool_budget(
    run_context: RunContext,
    function_name: str,
) -> tuple[dict[str, Any], str, str] | None:
    if (
        function_name in {"register_report_charts", "finalize_report_analysis"}
        or reporting_phase_from_run_context(run_context) != "analysis"
        or reporting_task_kind_from_run_context(run_context)
        not in {"visualization_section", "visualization_finalize"}
    ):
        # register/finalize 是可视化阶段的终态提交，不得被此前的探索调用挤占。
        # 图表登记仍受 durable registration 与 no-progress 门禁约束，重复提交不会绕过验收。
        return None
    state = _reporting_session_state(run_context)
    if state is None:
        return None
    dependencies = run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
    binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
    binding = binding if isinstance(binding, Mapping) else {}
    external_run_id = binding.get("externalRunId")
    identity = f"{external_run_id or ''}:{run_context.run_id or ''}"
    budgets = state.get(REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY)
    budgets = budgets if isinstance(budgets, dict) else {}
    stored = budgets.get(identity)
    stored = stored if isinstance(stored, dict) else {}

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    base_total = count(binding.get(REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY))
    base_script_failures = count(
        binding.get(REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY)
    )
    attempt_limit = count(binding.get(REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY)) or (
        _REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT
    )
    total_limit = count(binding.get(REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY)) or (
        _REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT
    )
    attempted_count = count(stored.get("attemptedCount"))
    successful_count = count(stored.get("successfulCount"))
    script_failure_count = count(stored.get("scriptFailureCount"))
    in_flight_count = count(stored.get("inFlightCount"))
    in_flight_tools = (
        dict(stored.get("inFlightToolCounts", {}))
        if isinstance(stored.get("inFlightToolCounts"), dict)
        else {}
    )
    cumulative_total = base_total + attempted_count + in_flight_count
    cumulative_script_failures = base_script_failures + script_failure_count
    if attempted_count + in_flight_count >= attempt_limit or cumulative_total >= total_limit:
        _stop_exhausted_visualization_budget(
            run_context,
            code="report_visualization_tool_budget_exhausted",
            message="当前可视化 Task 已达到工具调用上限，已停止本次 run。",
            attempted_count=attempted_count,
            successful_count=successful_count,
            in_flight_count=in_flight_count,
            total_tool_calls=cumulative_total,
            script_failure_count=cumulative_script_failures,
            attempt_limit=attempt_limit,
            total_limit=total_limit,
        )
    if (
        function_name == "terminal"
        and cumulative_script_failures >= _REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT
    ):
        _stop_exhausted_visualization_budget(
            run_context,
            code="report_visualization_script_failure_limit_exhausted",
            message="当前可视化 Task 已达到脚本执行失败上限，已停止本次 run。",
            attempted_count=attempted_count,
            successful_count=successful_count,
            in_flight_count=in_flight_count,
            total_tool_calls=cumulative_total,
            script_failure_count=cumulative_script_failures,
            attempt_limit=attempt_limit,
            total_limit=total_limit,
        )
    counted_tool_name = "read_file" if function_name == "read_tool_output" else function_name
    in_flight_read_units = count(stored.get("inFlightReadUnits"))
    in_flight_fact_queries = count(stored.get("inFlightFactQueries"))
    budgets[identity] = {
        **stored,
        "baseTotal": base_total,
        "baseScriptFailures": base_script_failures,
        "attemptedCount": attempted_count,
        "successfulCount": successful_count,
        "scriptFailureCount": script_failure_count,
        "inFlightCount": in_flight_count + 1,
        "inFlightReadUnits": in_flight_read_units + int(counted_tool_name == "read_file"),
        "inFlightFactQueries": in_flight_fact_queries
        + int(counted_tool_name == "query_analysis_facts"),
        "inFlightToolCounts": {
            **in_flight_tools,
            counted_tool_name: count(in_flight_tools.get(counted_tool_name)) + 1,
        },
    }
    state[REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY] = budgets
    return state, identity, REPORTING_VISUALIZATION_TOOL_BUDGET_STATE_KEY


def _finish_reporting_success_tool_budget(
    reservation: tuple[dict[str, Any], str, str] | None,
    *,
    succeeded: bool,
) -> None:
    if reservation is None:
        return
    state, identity, state_key = reservation
    budgets = state.get(state_key)
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


def _finish_visualization_tool_budget(
    run_context: RunContext,
    reservation: tuple[dict[str, Any], str, str] | None,
    function_name: str,
    result: Any,
    *,
    succeeded: bool,
    count_exploration: bool = True,
) -> None:
    if reservation is None:
        return
    state, identity, state_key = reservation
    raw_budgets = state.get(state_key)
    if not isinstance(raw_budgets, dict):
        return
    budgets: dict[str, Any] = raw_budgets
    stored = budgets.get(identity)
    if not isinstance(stored, dict):
        return

    def count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0

    attempted_count = count(stored.get("attemptedCount")) + 1
    successful_count = count(stored.get("successfulCount")) + int(succeeded)
    script_failure_count = count(stored.get("scriptFailureCount"))
    read_units_used = count(stored.get("readUnitsUsed"))
    fact_queries_used = count(stored.get("factQueriesUsed"))
    tool_counts = (
        dict(stored.get("toolCounts", {})) if isinstance(stored.get("toolCounts"), dict) else {}
    )
    counted_tool_name = "read_file" if function_name == "read_tool_output" else function_name
    tool_counts[counted_tool_name] = count(tool_counts.get(counted_tool_name)) + 1
    in_flight_tools = (
        dict(stored.get("inFlightToolCounts", {}))
        if isinstance(stored.get("inFlightToolCounts"), dict)
        else {}
    )
    in_flight_tools[counted_tool_name] = max(count(in_flight_tools.get(counted_tool_name)) - 1, 0)
    script_failed = _visualization_terminal_failed(function_name, result)
    script_failure_count += int(script_failed)
    if function_name == "terminal" and isinstance(result, Mapping):
        pending = state.get(REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY)
        pending = dict(pending) if isinstance(pending, Mapping) else {}
        dependencies = (
            run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
        )
        binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
        external_run_id = binding.get("externalRunId") if isinstance(binding, Mapping) else None
        if script_failed:
            diagnostics = [
                line.strip()
                for line in str(result.get("output", "")).splitlines()
                if "[FAIL]" in line
            ][:20]
            pending[identity] = {
                "lastScriptFailed": True,
                "diagnostics": diagnostics,
            }
        elif (
            isinstance(result.get("exit_code"), int)
            and not isinstance(result.get("exit_code"), bool)
            and result.get("exit_code") == 0
        ):
            pending.pop(identity, None)
            if isinstance(external_run_id, str) and external_run_id:
                prefix = f"{external_run_id}:"
                for key in tuple(pending):
                    if key == external_run_id or key.startswith(prefix):
                        pending.pop(key, None)
        state[REPORTING_VISUALIZATION_SCRIPT_FAILURE_PENDING_STATE_KEY] = pending
    read_segment_confirmed = (
        counted_tool_name == "read_file"
        and succeeded
        and isinstance(result, Mapping)
        and isinstance(result.get("content"), str)
    )
    if count_exploration:
        read_units_used += int(read_segment_confirmed)
        fact_queries_used += int(counted_tool_name == "query_analysis_facts")
    in_flight_count = max(count(stored.get("inFlightCount")) - 1, 0)
    budgets[identity] = {
        **stored,
        "attemptedCount": attempted_count,
        "successfulCount": successful_count,
        "scriptFailureCount": script_failure_count,
        "readUnitsUsed": read_units_used,
        "factQueriesUsed": fact_queries_used,
        "inFlightCount": in_flight_count,
        "inFlightReadUnits": max(
            count(stored.get("inFlightReadUnits")) - int(counted_tool_name == "read_file"), 0
        ),
        "inFlightFactQueries": max(
            count(stored.get("inFlightFactQueries"))
            - int(counted_tool_name == "query_analysis_facts"),
            0,
        ),
        "toolCounts": tool_counts,
        "inFlightToolCounts": in_flight_tools,
    }
    cumulative_total = count(stored.get("baseTotal")) + attempted_count
    cumulative_script_failures = count(stored.get("baseScriptFailures")) + script_failure_count
    if script_failed and cumulative_script_failures >= _REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT:
        _stop_exhausted_visualization_budget(
            run_context,
            code="report_visualization_script_failure_limit_exhausted",
            message="当前可视化 Task 已达到脚本执行失败上限，已停止本次 run。",
            attempted_count=attempted_count,
            successful_count=successful_count,
            in_flight_count=in_flight_count,
            total_tool_calls=cumulative_total,
            script_failure_count=cumulative_script_failures,
            attempt_limit=count(
                (
                    run_context.dependencies.get(REPORTING_TASK_DEPENDENCY, {})
                    if isinstance(run_context.dependencies, Mapping)
                    else {}
                ).get(REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY)
            )
            or _REPORT_VISUALIZATION_ATTEMPT_TOOL_LIMIT,
            total_limit=count(
                (
                    run_context.dependencies.get(REPORTING_TASK_DEPENDENCY, {})
                    if isinstance(run_context.dependencies, Mapping)
                    else {}
                ).get(REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY)
            )
            or _REPORT_VISUALIZATION_TOTAL_TOOL_LIMIT,
        )


def _visualization_terminal_failed(function_name: str, result: Any) -> bool:
    if function_name != "terminal" or not isinstance(result, Mapping):
        return False
    if result.get("ok") is False and result.get("code") == "execution_output_error":
        return True
    exit_code = result.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        return True
    output = result.get("output")
    if not isinstance(output, str):
        return False
    # 图表自检通常自行捕获异常并保持 exit_code=0；只识别逐项检查的明确
    # “对象: ERROR 原因”或 “[FAIL] 对象: 原因”行，避免普通日志中的 ERROR 单词
    # 误耗预算。
    return any(
        ": ERROR " in line.strip() or line.strip().startswith("[FAIL]")
        for line in output.splitlines()
    )


def _stop_exhausted_visualization_budget(
    run_context: RunContext,
    *,
    code: str,
    message: str,
    attempted_count: int,
    successful_count: int,
    in_flight_count: int,
    total_tool_calls: int,
    script_failure_count: int,
    attempt_limit: int,
    total_limit: int,
) -> None:
    details = {
        "attemptToolCalls": attempted_count,
        "successfulToolCalls": successful_count,
        "inFlightToolCalls": in_flight_count,
        "totalToolCalls": total_tool_calls,
        "scriptFailureCount": script_failure_count,
        "attemptLimit": attempt_limit,
        "totalLimit": total_limit,
        "scriptFailureLimit": _REPORT_VISUALIZATION_SCRIPT_FAILURE_LIMIT,
    }
    error = ReportingError(code, message, details=details)
    _record_reporting_tool_run_error(run_context, error)
    serialized = json.dumps(
        {
            "ok": False,
            "status": "rejected",
            "code": error.code,
            "message": error.message,
            "requiredActions": ["结束本次 run，交由上层按既有重试策略恢复当前 Task。"],
            "retryable": False,
            "details": details,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raise StopAgentRun(serialized, agent_message=serialized)


def _stop_exhausted_reporting_tool_budget(
    run_context: RunContext,
    successful_count: int,
    in_flight_count: int,
    *,
    task_kind: str = "analysis_item",
    limit: int = _REPORT_ANALYSIS_ITEM_SUCCESS_TOOL_LIMIT,
) -> None:
    details = {
        "successfulToolCalls": successful_count,
        "inFlightToolCalls": in_flight_count,
        "limit": limit,
    }
    code = (
        "report_visualization_tool_budget_exhausted"
        if task_kind in {"visualization_section", "visualization_finalize"}
        else "report_analysis_tool_budget_exhausted"
    )
    message = (
        "当前可视化 Task 已达到成功工具调用上限，已停止本次 run。"
        if task_kind in {"visualization_section", "visualization_finalize"}
        else "当前分析项已达到成功工具调用上限，已停止本次 run。"
    )
    error = ReportingError(
        code,
        message,
        details=details,
    )
    # Agno 会把 StopAgentRun 收敛为 completed + stop_after_tool_call，异常本身
    # 不会越过模型工具批次。同步记录领域错误，由 ReportWorkerOpenAIChat 在同一批次
    # 恢复并交给 Workflow 的 fresh retry，禁止退化成笼统的“未完成验收”。
    _record_reporting_tool_run_error(run_context, error)
    serialized = json.dumps(
        {
            "ok": False,
            "status": "rejected",
            "code": error.code,
            "message": error.message,
            "requiredActions": ["结束本次 run，交由上层按既有重试策略重新执行当前 Task。"],
            "retryable": False,
            "details": details,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raise StopAgentRun(serialized, agent_message=serialized)


def _stop_closed_visualization(run_context: RunContext) -> None:
    error = ReportingError(
        "report_chart_registration_closed",
        "图表已登记，当前 Task 只能调用 finalize_report_analysis 完成冻结。",
    )
    _record_reporting_tool_run_error(run_context, error)
    serialized = json.dumps(
        {
            "ok": False,
            "status": "rejected",
            "code": error.code,
            "message": error.message,
            "requiredActions": [
                "结束本次 run；fresh retry 必须立即且只调用 finalize_report_analysis。"
            ],
            "retryable": False,
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
    # 图表和章节 claim 的 metricCode/周期来自本次运行冻结的上下文，不能用
    # 静态示例回填，否则参数错误回执会再次诱导模型提交无效业务代码。
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
    plan_steps = agent_plan.get("plan")
    plan_steps = plan_steps if isinstance(plan_steps, list) else []
    snapshot = {
        # 通用 Coding Toolkit 会把失败回执也写入 progress.entries；若把这些 entry
        # 纳入指纹，不同参数的连续拒绝会被误判为真实进展并永久重置阶段失败计数。
        # Reporting 成功工具已在 _enforce_reporting_no_progress 中显式清空失败状态，
        # 因此这里只信任耐久 mutation 和模型计划状态，不信任失败调用生成的观测记录。
        "codingProgress": {
            "mutation": coding_progress.get("mutation"),
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

    # 第二次精确失败增加 DeepSeek Harness 风格的纠错提示；同指纹第三次或阶段累计
    # 第八次仍无成功进展时必须失败关闭当前 run，避免模型继续扩大无效工具历史。
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
        details["terminalReason"] = "tool_no_progress"
        message = result.get("message")
        if not isinstance(message, str) or not message:
            message = "Reporting 工具连续失败且没有可观察进展，已停止当前 run。"
        error = ReportingError(code, message, details=details)
        _record_reporting_tool_run_error(run_context, error)
        guided.update(
            {
                "code": error.code,
                "message": error.message,
                "details": details,
                "requiredActions": required_actions,
                "retryable": False,
            }
        )
        serialized = json.dumps(
            guided,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raise StopAgentRun(serialized, agent_message=serialized)
    guided.update(
        {
            "code": code,
            "message": result.get("message"),
            "details": details,
            "requiredActions": required_actions,
            "retryable": result.get("retryable", True),
        }
    )
    return guided


async def normalize_reporting_tool_arguments(
    run_context: RunContext,
    function_name: str,
    function_call: Any,
    arguments: dict[str, Any],
    *,
    _skip_skill_cache: bool = False,
) -> Any:
    """执行 Reporting 工具并把参数错误收敛为可操作回执。"""

    if not _skip_skill_cache:
        cache_key = _visualization_skill_cache_key(run_context, function_name, arguments)
        if cache_key is not None:
            lock = _VISUALIZATION_SKILL_CACHE_LOCKS.setdefault(cache_key, asyncio.Lock())
            if len(_VISUALIZATION_SKILL_CACHE_LOCKS) > _VISUALIZATION_SKILL_CACHE_MAX_LOCKS:
                for stale_key, stale_lock in list(_VISUALIZATION_SKILL_CACHE_LOCKS.items()):
                    if stale_key != cache_key and not stale_lock.locked():
                        _VISUALIZATION_SKILL_CACHE_LOCKS.pop(stale_key, None)
                        if (
                            len(_VISUALIZATION_SKILL_CACHE_LOCKS)
                            <= _VISUALIZATION_SKILL_CACHE_MAX_LOCKS
                        ):
                            break
            async with lock:
                cached = _cached_visualization_skill_result(run_context, cache_key)
                if cached is not None:
                    return cached
                return await normalize_reporting_tool_arguments(
                    run_context,
                    function_name,
                    function_call,
                    arguments,
                    _skip_skill_cache=True,
                )

    task_kind = reporting_task_kind_from_run_context(run_context)
    state = _reporting_session_state(run_context)
    if (
        task_kind == "analysis_item"
        and reporting_analysis_recovery_from_run_context(run_context)
        and function_name != "complete_analysis_item"
    ):
        _stop_analysis_recovery(run_context)
    if (
        task_kind == "analysis_item"
        and function_name == "query_analysis_facts"
        and reporting_analysis_fact_usage_from_run_context(run_context)
        >= _analysis_fact_query_limit(run_context)
    ):
        _stop_analysis_fact_query_budget(run_context)
    if (
        task_kind in {"visualization_section", "visualization_finalize"}
        and function_name != "finalize_report_analysis"
        and (
            (
                isinstance(state, dict)
                and state.get(_REPORT_VISUALIZATION_REGISTERED_STATE_KEY) is True
            )
            or reporting_visualization_registered_from_run_context(run_context)
        )
    ):
        _stop_closed_visualization(run_context)
    skill_cache_key = _visualization_skill_cache_key(run_context, function_name, arguments)
    if skill_cache_key is not None:
        cached = _cached_visualization_skill_result(run_context, skill_cache_key)
        if cached is not None:
            return cached
    exploration_receipt = _visualization_exploration_budget_receipt(run_context, function_name)
    if exploration_receipt is not None:
        # 超出独立探索额度的调用仍是一次真实工具尝试，但不能再次增加 read/fact 用量。
        visualization_reservation = _reporting_visualization_tool_budget(run_context, function_name)
        _finish_visualization_tool_budget(
            run_context,
            visualization_reservation,
            function_name,
            exploration_receipt,
            succeeded=False,
            count_exploration=False,
        )
        state = _reporting_session_state(run_context)
        if isinstance(state, dict):
            dependencies = (
                run_context.dependencies if isinstance(run_context.dependencies, Mapping) else {}
            )
            binding = dependencies.get(REPORTING_TASK_DEPENDENCY)
            binding = binding if isinstance(binding, Mapping) else {}
            identity = f"{binding.get('externalRunId') or ''}:{run_context.run_id or ''}"
            production_states = state.get(REPORTING_VISUALIZATION_PRODUCTION_ONLY_STATE_KEY)
            production_states = (
                dict(production_states) if isinstance(production_states, Mapping) else {}
            )
            production_states[identity] = True
            state[REPORTING_VISUALIZATION_PRODUCTION_ONLY_STATE_KEY] = production_states
        details = exploration_receipt["details"]
        if reporting_visual_inspection_mode_from_run_context(run_context) == "vision":
            details["allowedTerminalTools"] = [
                "inspect_chart",
                "register_report_charts",
                "finalize_report_analysis",
            ]
        error = ReportingError(
            exploration_receipt["code"],
            exploration_receipt["message"],
            details=details,
        )
        _record_reporting_tool_run_error(run_context, error)
        serialized = json.dumps(exploration_receipt, ensure_ascii=False, separators=(",", ":"))
        raise StopAgentRun(serialized, agent_message=serialized)
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
    analysis_reservation = _reporting_analysis_item_tool_budget(run_context, function_name)
    analysis_fact_reservation = _reserve_analysis_fact_query(run_context, function_name)
    visualization_reservation = _reporting_visualization_tool_budget(run_context, function_name)
    try:
        result = function_call(**arguments)
        result = await result if inspect.isawaitable(result) else result
    except (TypeError, ValidationError) as error:
        _finish_reporting_success_tool_budget(analysis_reservation, succeeded=False)
        _finish_analysis_fact_query(analysis_fact_reservation)
        _finish_visualization_tool_budget(
            run_context,
            visualization_reservation,
            function_name,
            None,
            succeeded=False,
        )
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
        _finish_reporting_success_tool_budget(analysis_reservation, succeeded=False)
        _finish_analysis_fact_query(analysis_fact_reservation)
        _finish_visualization_tool_budget(
            run_context,
            visualization_reservation,
            function_name,
            None,
            succeeded=False,
        )
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
    if (
        succeeded
        and task_kind in {"visualization_section", "visualization_finalize"}
        and function_name == "write_analysis_files"
        and isinstance(state, dict)
    ):
        state[REPORTING_VISUALIZATION_SCRIPT_WRITTEN_STATE_KEY] = True
    if succeeded:
        # 仅缓存成功且可序列化的只读 Skill 结果；失败必须保留真实重试机会。
        _cache_visualization_skill_result(run_context, skill_cache_key, function_name, result)
    if (
        succeeded
        and task_kind in {"visualization_section", "visualization_finalize"}
        and function_name == "register_report_charts"
        and isinstance(state, dict)
    ):
        state[_REPORT_VISUALIZATION_REGISTERED_STATE_KEY] = True
    _finish_reporting_success_tool_budget(analysis_reservation, succeeded=succeeded)
    _finish_analysis_fact_query(analysis_fact_reservation)
    _finish_visualization_tool_budget(
        run_context,
        visualization_reservation,
        function_name,
        result,
        succeeded=succeeded,
    )
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


def _completed_report_content(payload: dict[str, Any]) -> str | None:
    if payload.get("status") != "completed":
        return None
    report = payload.get("report")
    if not isinstance(report, dict):
        return None
    pdf = report.get("pdf")
    word = report.get("word")
    html = report.get("html")
    pdf_url = pdf.get("downloadUrl") if isinstance(pdf, dict) else None
    word_url = word.get("downloadUrl") if isinstance(word, dict) else None
    html_url = html.get("previewUrl") if isinstance(html, dict) else None
    urls = (pdf_url, word_url, html_url)

    def is_valid_delivery_url(url: object) -> bool:
        if (
            not isinstance(url, str)
            or not url
            or any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in url)
        ):
            return False
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            parsed.port
        except ValueError:
            return False
        hostname_text = hostname if isinstance(hostname, str) else ""
        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
            and bool(hostname_text)
            and not any(char.isspace() for char in hostname_text)
        )

    if not all(is_valid_delivery_url(url) for url in urls):
        return "## 报告发布未完成\n\n未生成有效的 PDF、Word 和 HTML 交付链接，请重试报表发布。"
    parts = ["## 报表已生成"]
    details: list[str] = []
    report_id = report.get("reportId")
    revision = report.get("revision")
    if isinstance(report_id, str) and report_id:
        details.append(f"- 报告编号：`{report_id}`")
    if isinstance(revision, int) and not isinstance(revision, bool):
        details.append(f"- 修订版本：Revision {revision}")
    if details:
        parts.append("\n".join(details))
    parts.append(
        f"### 文件下载\n\n- [下载 PDF 报告]({pdf_url})\n"
        f"- [下载 Word 报告]({word_url})\n- [预览 HTML 报告]({html_url})"
    )
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
            try:
                payload = ast.literal_eval(content)
            except (SyntaxError, ValueError):
                return None
        if not isinstance(payload, dict) or payload.get("status") != "paused":
            completed = _completed_report_content(payload) if isinstance(payload, dict) else None
            return ModelResponse(content=completed) if completed is not None else None
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


def _without_facade_tool_preamble(response: Any) -> Any:
    tool_calls = getattr(response, "tool_calls", None)
    if isinstance(tool_calls, list) and any(
        _report_model_tool_name(tool) in _REPORT_FACADE_TOOL_NAMES for tool in tool_calls
    ):
        response.content = None
    return response


def _without_streamed_facade_tool_preamble(responses: list[Any]) -> list[Any]:
    has_facade_tool_call = any(
        isinstance(tool_calls := getattr(response, "tool_calls", None), list)
        and any(_report_model_tool_name(tool) in _REPORT_FACADE_TOOL_NAMES for tool in tool_calls)
        for response in responses
    )
    if has_facade_tool_call:
        for response in responses:
            response.content = None
    return responses


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
    if isinstance(name, str):
        return name
    function = getattr(tool, "function", None)
    function_name = getattr(function, "name", None)
    return function_name if isinstance(function_name, str) else None


def _visualization_production_tool_allowed(
    run_context: RunContext | None,
    tool_name: str,
) -> bool:
    if reporting_task_kind_from_run_context(run_context) not in {
        "visualization_section",
        "visualization_finalize",
    } or not reporting_visualization_production_only_from_run_context(run_context):
        return True
    return (
        tool_name in REPORTING_VISUALIZATION_PRODUCTION_TOOL_NAMES
        or (
            reporting_visualization_recovery_from_run_context(run_context)
            and tool_name in {"read_file", "read_tool_output"}
        )
        or (
            tool_name == "process"
            and reporting_visualization_script_session_available_from_run_context(run_context)
        )
        or (
            tool_name == "inspect_chart"
            and reporting_visual_inspection_mode_from_run_context(run_context) == "vision"
        )
    )


def _visualization_lifecycle_tool_allowed(
    run_context: RunContext | None,
    tool_name: str,
) -> bool:
    """让模型 schema 与旧历史工具调用共享同一可视化生命周期门禁。"""

    if reporting_task_kind_from_run_context(run_context) not in {
        "visualization_section",
        "visualization_finalize",
    }:
        return True
    state = _reporting_session_state(run_context)
    if (
        isinstance(state, Mapping) and state.get(_REPORT_VISUALIZATION_REGISTERED_STATE_KEY) is True
    ) or reporting_visualization_registered_from_run_context(run_context):
        return tool_name == "finalize_report_analysis"
    if tool_name == "process":
        return reporting_visualization_script_session_available_from_run_context(run_context)
    if reporting_visualization_recovery_from_run_context(run_context):
        return tool_name not in REPORTING_VISUALIZATION_EXPLORATION_TOOL_NAMES or tool_name in {
            "read_file",
            "read_tool_output",
        }
    return tool_name not in {
        "query_analysis_context",
        "query_analysis_facts",
        "read_file",
        "read_tool_output",
    }


def _phase_filtered_report_tools(messages: list[Message], tools: Any) -> Any:
    phase = _reporting_phase_from_messages(messages)
    run_context = current_reporting_run_context()
    task_kind = reporting_task_kind_from_run_context(run_context)
    if phase is None or tools is None:
        return tools
    return [
        tool
        for tool in tools
        if (name := _report_model_tool_name(tool)) is not None
        and reporting_phase_allows_tool(phase, name, task_kind=task_kind)
        and _visualization_lifecycle_tool_allowed(run_context, name)
        and not (
            task_kind == "analysis_item"
            and run_context is not None
            and reporting_analysis_recovery_from_run_context(run_context)
            and name != "complete_analysis_item"
        )
        and not (
            task_kind == "analysis_item"
            and run_context is not None
            and name == "query_analysis_facts"
            and reporting_analysis_fact_usage_from_run_context(run_context)
            >= _analysis_fact_query_limit(run_context)
        )
        and not (
            task_kind in {"visualization_section", "visualization_finalize"}
            and run_context is not None
            and name in REPORTING_VISUALIZATION_EXPLORATION_TOOL_NAMES
            and not (
                reporting_visualization_recovery_from_run_context(run_context)
                and name in {"read_file", "read_tool_output"}
            )
            and (
                _visualization_exploration_budget_receipt(run_context, name) is not None
                or reporting_visualization_exploration_budget_exhausted_from_run_context(
                    run_context
                )
            )
        )
        and not (
            task_kind in {"visualization_section", "visualization_finalize"}
            and not _visualization_production_tool_allowed(run_context, name)
        )
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
        previous_error = self.report_run_error()
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
            # Planner 的 Pydantic validator 在模型响应边界失败后，Agno 会使用同一模型
            # 自动重试，但不会改写原始 user message。错误由 ContextVar 按异步任务和
            # 模型实例隔离；因此只有紧邻的 Schema 重试或显式 correction 才能升级，
            # 首次请求和并发 Planner 不会继承其他请求的 thinking 状态。
            if isinstance(escalation_profile, ReportingThinkingProfile) and (
                isinstance(previous_error, ValidationError)
                or (
                    isinstance(escalation_fields, tuple)
                    and _reporting_request_uses_escalation(messages, escalation_fields)
                )
            ):
                profile = escalation_profile
        request_model = copy(self)
        task_kind = reporting_task_kind_from_run_context(current_reporting_run_context())
        if task_kind == "analysis_item":
            output_limit = _REPORT_ANALYSIS_ITEM_OUTPUT_TOKEN_LIMIT
        elif task_kind == "visualization_section":
            output_limit = _REPORT_VISUALIZATION_SECTION_OUTPUT_TOKEN_LIMIT
        elif task_kind == "visualization_finalize":
            output_limit = _REPORT_VISUALIZATION_OUTPUT_TOKEN_LIMIT
        elif task_kind == "section":
            output_limit = _REPORT_SECTION_OUTPUT_TOKEN_LIMIT
        else:
            output_limit = None
        if output_limit is not None:
            configured = request_model.max_tokens
            request_model.max_tokens = (
                min(configured, output_limit)
                if isinstance(configured, int) and configured > 0
                else output_limit
            )
        return apply_reporting_thinking_profile(request_model, profile)

    @staticmethod
    def _phase_request_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
        if reporting_task_kind_from_run_context(current_reporting_run_context()) not in {
            "visualization_section",
            "visualization_finalize",
        }:
            return kwargs
        # visualization 没有合法的纯文本终态，每一轮都必须通过当前生命周期投影出的
        # 工具推进。使用 Agno 公共 tool_choice 契约保留工具选择自由，同时阻止模型把
        # 整个生成窗口耗在规划文本后才尝试调用工具。
        return {**kwargs, "tool_choice": "required"}

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
        request_model = self._phase_request_model(messages)
        kwargs = self._phase_request_kwargs(kwargs)
        self._clear_report_run_error()
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
        request_model = self._phase_request_model(messages)
        kwargs = self._phase_request_kwargs(kwargs)
        self._clear_report_run_error()
        try:
            response = await ProjectedOpenAIChat.aresponse(
                request_model,
                messages,
                *args,
                **kwargs,
            )
            terminal_error = _take_reporting_tool_run_error()
            if _is_terminal_reporting_error(terminal_error):
                # StopAgentRun 已由 Agno 公共模型循环转换为 stop_after_tool_call，不能在
                # Agent retry 边界重新抛普通异常；只记录原领域错误，交给 Task runner
                # 在本次 Agno run 正常停止后恢复，确保不会产生同 run continuation。
                self._record_report_run_error(cast(Exception, terminal_error))
                return self._validated_reporting_response(request_model, response)
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
        request_model = self._phase_request_model(messages)
        kwargs = self._phase_request_kwargs(kwargs)
        self._clear_report_run_error()
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
        request_model = self._phase_request_model(messages)
        kwargs = self._phase_request_kwargs(kwargs)
        self._clear_report_run_error()
        try:
            async for response in ProjectedOpenAIChat.aresponse_stream(
                request_model,
                messages,
                *args,
                **kwargs,
            ):
                yield response
            terminal_error = _take_reporting_tool_run_error()
            if _is_terminal_reporting_error(terminal_error):
                # Agno 把 StopAgentRun 收敛成 stop_after_tool_call 后会正常结束异步流。
                # 必须在清理模型错误前恢复原领域错误，Task runner 才能停止当前 Task，
                # 而不是把它误判成缺少终态工具并发起同 run continuation。
                self._record_report_run_error(cast(Exception, terminal_error))
                return
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
        additional_input: Any = None,
        current_function_call_count: int = 0,
        function_call_limit: int | None = None,
        skip_pause_check: bool = False,
        result_store: Any = None,
    ) -> AsyncIterator[Any]:
        from agno.offload.types import NEVER_OFFLOADED_TOOLS

        calls = list(function_calls)
        if not calls:
            if additional_input:
                function_call_results.extend(additional_input)
            error = _take_reporting_tool_run_error()
            if error is not None:
                raise error
            return

        # Agno 3.0.0 默认用 gather 并行执行整批工具；即使某个 hook 抛 StopAgentRun，
        # 同批其余副作用也已执行。Reporting 的 no-progress 是失败关闭边界，因此逐个
        # 委托公共实现并在每次完成后恢复领域错误，同时按公共实现的 offload 豁免规则
        # 累加调用计数，不能通过拆批改变 function_call_limit。
        call_count = current_function_call_count
        for index, function_call in enumerate(calls):
            call_additional_input = additional_input if index == len(calls) - 1 else None
            async for event in super().arun_function_calls(
                [function_call],
                function_call_results,
                additional_input=call_additional_input,
                current_function_call_count=call_count,
                function_call_limit=function_call_limit,
                skip_pause_check=skip_pause_check,
                result_store=result_store,
            ):
                if not _reporting_tool_run_error_is_terminal():
                    error = _take_reporting_tool_run_error()
                    if error is not None:
                        raise error
                yield event
            if _reporting_tool_run_error_is_terminal():
                return
            error = _take_reporting_tool_run_error()
            if error is not None:
                raise error
            if result_store is None or function_call.function.name not in NEVER_OFFLOADED_TOOLS:
                call_count += 1

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
            production_forbidden = isinstance(
                name, str
            ) and not _visualization_production_tool_allowed(current_reporting_run_context(), name)
            lifecycle_forbidden = isinstance(
                name, str
            ) and not _visualization_lifecycle_tool_allowed(current_reporting_run_context(), name)
            vision_disabled = name in {"view_image", "inspect_chart"} and not getattr(
                self, "_report_vision_enabled", True
            )
            if (
                not phase_forbidden
                and not production_forbidden
                and not lifecycle_forbidden
                and not vision_disabled
            ):
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
                            if not production_forbidden and not lifecycle_forbidden
                            else {
                                "ok": False,
                                "status": "rejected",
                                "code": "report_visualization_production_only",
                                "message": "当前可视化已进入生产态，请直接生成、登记或完成图表。",
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
        task_kind = reporting_task_kind_from_run_context(current_reporting_run_context())
        # Visualization 的首个请求已携带全局冻结 facts，随后还必须保留已读取的 Skill
        # 回合才能生成脚本。继续套用单项分析的 128K 上限会在 Skill 返回后立即 rebase，
        # 只留下可重载哈希并诱发重复读取；因此它直接使用 Reporting 已配置的输入预算。
        phase_cap = (
            REPORTING_ANALYSIS_INPUT_TOKEN_HARD_CAP
            if phase == "analysis"
            and task_kind not in {"visualization_section", "visualization_finalize"}
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
        return _forced_review_response(messages) or _without_facade_tool_preamble(
            super().invoke(messages, *args, **kwargs)
        )

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        forced = _forced_review_response(messages)
        if forced is not None:
            return forced
        return _without_facade_tool_preamble(await super().ainvoke(messages, *args, **kwargs))

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        forced = _forced_review_response(messages, stream=True)
        if forced is not None:
            yield forced
            return
        # tool call 可能到后续 chunk 才出现，已发送的前导文字无法撤回；先收齐本轮
        # 响应再统一过滤，保证任何报表工具轮次都不会向 AgentOS 泄漏解释文本。
        started_at = perf_counter()
        responses = list(super().invoke_stream(messages, *args, **kwargs))
        logger.info(
            "report_facade_stream_buffer_completed mode=sync duration_ms={} chunk_count={}",
            _duration_ms(started_at),
            len(responses),
        )
        yield from _without_streamed_facade_tool_preamble(responses)

    async def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        forced = _forced_review_response(messages, stream=True)
        if forced is not None:
            yield forced
            return
        # 与同步路径保持相同的整轮判定语义，不能根据首个文字 chunk 提前放行。
        started_at = perf_counter()
        responses = [
            response async for response in super().ainvoke_stream(messages, *args, **kwargs)
        ]
        logger.info(
            "report_facade_stream_buffer_completed mode=async duration_ms={} chunk_count={}",
            _duration_ms(started_at),
            len(responses),
        )
        for response in _without_streamed_facade_tool_preamble(responses):
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
        extra_body=openai_compatible_extra_body(
            enable_thinking=enable_thinking,
            use_vllm_reasoning=settings.model_vllm_reasoning,
        ),
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
        telemetry=False,
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
        started_at = perf_counter()
        logger.info(
            "report_facade_tools_started run_id={} session_id_present={}",
            getattr(run_context, "run_id", None) or "-",
            str(bool(getattr(run_context, "session_id", None))).lower(),
        )
        _ = agent
        tools = [ReportWorkflowToolkit(controller)]
        logger.info(
            "report_facade_tools_completed run_id={} duration_ms={} toolkit_count={} "
            "function_count={}",
            getattr(run_context, "run_id", None) or "-",
            _duration_ms(started_at),
            len(tools),
            sum(len(tool.async_functions) for tool in tools),
        )
        return tools

    facade = report_worker.deep_copy(
        update={
            "id": "smart-reporting",
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
                "描述为完成。若发布契约返回 `pdf.downloadUrl` 和 `word.downloadUrl`，必须逐字保留并分别"
                "展示为 PDF、Word Markdown 下载链接；若返回 `html.previewUrl`，必须逐字保留并展示为"
                "HTML Markdown 预览链接。调用任何报表工具的轮次不得输出前言或解释文字；"
                "CLI 契约返回 Workspace 路径时，PDF 使用 `path`，Word 使用 "
                "`word.path`。不得补充域名、协议或改写为示例地址，也不得虚构返回中不存在的字段。",
            ],
            "tools": workflow_tools,
            "skills": None,
            "tool_hooks": facade_tool_hooks,
            "tool_choice": "auto",
            "telemetry": False,
        }
    )
    facade.num_history_runs = None
    return facade
