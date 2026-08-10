import ast
import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Iterator
from copy import deepcopy
from dataclasses import fields
from functools import partial
from typing import Any, cast
from urllib.parse import urlparse
from uuid import uuid4

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.exceptions import StopAgentRun
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.run import RunContext
from openai.types.chat.chat_completion_chunk import (
    ChoiceDeltaToolCall,
    ChoiceDeltaToolCallFunction,
)
from pydantic import ValidationError

from ...agent_control import AGENT_PLAN_STATE_KEY
from ...agents import OPENAI_COMPATIBLE_ROLE_MAP
from ...agents.assistant import AgentInstructions
from ...context_management import (
    CODING_CONTEXT_TOKEN_LIMIT,
    CODING_OUTPUT_TOKEN_RESERVE,
    ContextBudgetController,
    ProjectedOpenAIChat,
    RollingSessionSummaryManager,
    clear_terminal_reasoning,
    projected_coding_model,
)
from ...settings import AgentSettings
from ...skills import (
    create_skill_script_hook,
    is_skill_script_hook,
    load_sandbox_execution_skills,
)
from ...task_execution import TaskExecutionRepository
from ...task_execution.execution import (
    create_task_tool_scheduler_hook,
    is_task_tool_scheduler_hook,
)
from ...workspace import WorkspaceService
from .delivery.acceptance import load_reporting_skills
from .tools import (
    REPORT_CHART_STATE_KEY,
    REPORT_DRAFT_STATE_KEY,
    REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY,
    build_report_worker_tools,
)
from .vision import ReportVisionReviewer
from .workflow.controller import ReportWorkflowController, ReportWorkflowToolkit

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
        "register_report_charts",
        "discard_report_charts",
        "begin_report_draft",
        "render_report_section",
        "finalize_report_draft",
    }
)
_CUMULATIVE_STREAM_USAGE_HOSTS = frozenset({"api.siliconflow.cn"})
_REPORT_TOOL_FAILURE_STATE_KEY = "agentos_reporting_tool_failures"
_REPORT_TOOL_ARGUMENT_MAX_ATTEMPTS = 5
_REPORT_TOOL_PHASE_MAX_FAILURES = 8
_REPORT_ARGUMENT_MAX_ISSUES = 8
_REPORT_ARGUMENT_MAX_TOP_LEVEL_KEYS = 32
_REPORT_ARGUMENT_MAX_LOC_LENGTH = 256
_REPORT_ARGUMENT_MAX_MESSAGE_LENGTH = 512
_REPORT_EXPECTED_CALL_SHAPES: dict[str, dict[str, Any]] = {
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
    "discard_report_charts": {"chartIds": ["cost_structure_preview"]},
    "begin_report_draft": {},
    "render_report_section": {
        "sectionCode": "executive_summary",
        "blocks": [
            {
                "blockId": "overview",
                "markdown": "### 核心结论\n\n- 医疗收入同比增长 8.2%",
                "citationIds": ["citation_001"],
                "analysisIds": ["analysis_001"],
                "chartIds": ["income_trend"],
            }
        ],
        "evidencePaths": ["analysis/evidence/executive_summary.json"],
    },
    "finalize_report_draft": {},
}


def _reporting_session_state(run_context: RunContext) -> dict[str, Any] | None:
    return run_context.session_state if isinstance(run_context.session_state, dict) else None


def _reporting_mutation_sequence(state: dict[str, Any] | None) -> int:
    progress = state.get("agentos_coding_tool_progress") if isinstance(state, dict) else None
    return int(progress.get("mutation", 0)) if isinstance(progress, dict) else 0


def _record_reporting_argument_autofix(run_context: RunContext, function_name: str) -> None:
    state = _reporting_session_state(run_context)
    if state is None:
        return
    entry = {
        "code": "report_tool_arguments_unwrapped",
        "toolName": function_name,
        "mutationSequence": _reporting_mutation_sequence(state),
    }
    stored = state.get(REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY)
    items = list(stored) if isinstance(stored, list) else []
    if not items or items[-1] != entry:
        items.append(entry)
    state[REPORT_TOOL_ARGUMENT_AUTOFIX_STATE_KEY] = items[-50:]


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
    draft = state.get(REPORT_DRAFT_STATE_KEY)
    charts = state.get(REPORT_CHART_STATE_KEY)
    coding_progress = state.get("agentos_coding_tool_progress")
    agent_plan = state.get(AGENT_PLAN_STATE_KEY)
    draft = draft if isinstance(draft, dict) else {}
    charts = charts if isinstance(charts, dict) else {}
    coding_progress = coding_progress if isinstance(coding_progress, dict) else {}
    agent_plan = agent_plan if isinstance(agent_plan, dict) else {}
    progress_entries = coding_progress.get("entries")
    progress_entries = progress_entries if isinstance(progress_entries, list) else []
    plan_steps = agent_plan.get("plan")
    plan_steps = plan_steps if isinstance(plan_steps, list) else []
    pending = draft.get("pendingChartBindings")
    pending = pending if isinstance(pending, dict) else {}
    registry = charts.get("charts")
    registry = registry if isinstance(registry, dict) else {}
    snapshot = {
        "draft": {
            "attemptNo": draft.get("attemptNo"),
            "chartAttemptNo": charts.get("attemptNo"),
            "status": draft.get("status"),
            "draftId": draft.get("draftId"),
            "pendingChartIds": sorted(str(value) for value in pending),
            "registeredPendingChartIds": sorted(set(pending) & set(registry)),
        },
        # 详细分析模式合法地经历 verify -> update_plan -> finish_task；仅查看
        # 草稿/图表会把这些真实进展误判为同一失败循环。把通用 Coding 工具进度
        # 和 AgentOS 官方计划状态纳入指纹，状态或 mutation 变化即重新计数。
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


def _enforce_reporting_no_progress(
    run_context: RunContext,
    function_name: str,
    result: Any,
) -> Any:
    if not isinstance(result, dict) or result.get("ok") is not False:
        return result
    code = result.get("code")
    state = _reporting_session_state(run_context)
    if not isinstance(code, str) or not code or state is None:
        return result

    mutation_sequence = _reporting_mutation_sequence(state)
    progress_fingerprint = _reporting_progress_fingerprint(state)
    fingerprint = f"{function_name}:{code}"
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
    if (
        count < _REPORT_TOOL_ARGUMENT_MAX_ATTEMPTS
        and phase_failure_count < _REPORT_TOOL_PHASE_MAX_FAILURES
    ):
        return result

    # Agno 官方 StopAgentRun 会在当前工具批次结束后退出模型工具循环，并完整保存
    # 已有消息和工具结果。仅返回 executionBlocking 字段不会阻止模型继续盲重试。
    blocked = dict(result)
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
    blocked.update(
        {
            "severity": "error",
            "executionBlocking": True,
            "retryable": False,
            "warnings": [],
            "details": details,
        }
    )
    raise StopAgentRun(json.dumps(blocked, ensure_ascii=False, separators=(",", ":")))


async def normalize_reporting_tool_arguments(
    run_context: RunContext,
    function_name: str,
    function_call: Any,
    arguments: dict[str, Any],
) -> Any:
    """纠正 SiliconFlow 偶发的一层 arguments 包装，并收敛 Reporting 错误。"""
    corrected = arguments
    wrapped: Any = arguments.get("arguments")
    if isinstance(wrapped, str):
        try:
            decoded = json.loads(wrapped)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, dict):
            wrapped = decoded
    if isinstance(wrapped, dict):
        siblings = {key: value for key, value in arguments.items() if key != "arguments"}
        if not wrapped.keys() & siblings.keys():
            # SiliconFlow 也可能把 command 放入 arguments、同时把 timeout 留在顶层。
            # 这里只展开一层且拒绝覆盖同名字段；冲突时沿用原始调用并保留 Agno 错误。
            corrected = {**wrapped, **siblings}
    try:
        result = function_call(**corrected)
        result = await result if inspect.isawaitable(result) else result
    except (TypeError, ValidationError) as error:
        if not _is_tool_argument_error(error):
            raise
        diagnostic_error = error
        diagnostic_arguments = corrected
        if function_name not in _REPORT_STRICT_TOOL_NAMES and corrected is not arguments:
            try:
                original_result = function_call(**arguments)
                return (
                    await original_result
                    if inspect.isawaitable(original_result)
                    else original_result
                )
            except (TypeError, ValidationError) as original_error:
                if not _is_tool_argument_error(original_error):
                    raise
                diagnostic_error = original_error
                diagnostic_arguments = arguments
        return _enforce_reporting_no_progress(
            run_context,
            function_name,
            _report_tool_argument_failure(
                function_name,
                diagnostic_error,
                diagnostic_arguments,
            ),
        )
    if corrected is not arguments:
        _record_reporting_argument_autofix(run_context, function_name)
    return _enforce_reporting_no_progress(run_context, function_name, result)


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


def _forced_report_worker_response(
    messages: list[Message], *, stream: bool = False
) -> ModelResponse | None:
    """正式验收通过后只执行服务端签发的 finish_task，不再请求模型决策。"""
    last = messages[-1] if messages else None
    if last is None or last.role != "tool" or last.tool_name != "finalize_report_draft":
        return None
    if not isinstance(last.content, str):
        return None
    try:
        payload = json.loads(last.content)
    except json.JSONDecodeError:
        try:
            payload = ast.literal_eval(last.content)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(payload, dict):
        return None
    next_call = payload.get("nextToolCall")
    if not isinstance(next_call, dict):
        return None
    arguments = next_call.get("arguments")
    if (
        payload.get("ok") is not True
        or next_call.get("name") != "finish_task"
        or not isinstance(arguments, dict)
        or set(arguments) != {"summary", "artifact_paths"}
        or not isinstance(arguments.get("summary"), str)
        or not arguments["summary"]
        or not isinstance(arguments.get("artifact_paths"), list)
        or len(arguments["artifact_paths"]) > 50
        or any(not isinstance(path, str) or not path for path in arguments["artifact_paths"])
    ):
        return None
    return _tool_response("finish_task", arguments, stream=stream)


class ReportWorkerOpenAIChat(ProjectedOpenAIChat):
    """Reporting Worker 在通过正式验收后确定性收敛到 finish_task。"""

    _report_vision_enabled = True

    def get_function_calls_to_run(
        self,
        assistant_message: Message,
        messages: list[Message],
        functions: dict[str, Any] | None = None,
    ) -> list[Any]:
        """视觉关闭时把过期的 view_image 调用转成有界工具回执。

        工具 schema 会随配置移除 view_image，但模型可能仍携带上一轮 schema 的调用。
        直接交给 Agno 会生成“Function not found”并触发无效重试；这里只拦截该单一
        工具名，保留其它调用和原始 assistant 消息，避免改变普通工具执行语义。
        """
        if getattr(self, "_report_vision_enabled", True):
            return super().get_function_calls_to_run(assistant_message, messages, functions)
        tool_calls = list(assistant_message.tool_calls or [])
        allowed_calls = []
        blocked = []
        for tool_call in tool_calls:
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            name = function.get("name") if isinstance(function, dict) else None
            if name != "view_image":
                allowed_calls.append(tool_call)
                continue
            call_id = tool_call.get("id") if isinstance(tool_call, dict) else None
            if not isinstance(call_id, str) or not call_id:
                allowed_calls.append(tool_call)
                continue
            blocked.append(
                Message(
                    role=self.tool_message_role,
                    tool_call_id=call_id,
                    tool_name="view_image",
                    content=json.dumps(
                        {
                            "ok": False,
                            "status": "skipped",
                            "code": "report_vision_disabled",
                            "message": "当前 Reporting Worker 未启用图片视觉工具，继续使用文本和文件证据。",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                )
            )
        if blocked:
            messages.extend(blocked)
        if len(allowed_calls) == len(tool_calls):
            return super().get_function_calls_to_run(assistant_message, messages, functions)
        if not allowed_calls:
            return []
        filtered_message = deepcopy(assistant_message)
        filtered_message.tool_calls = allowed_calls
        return super().get_function_calls_to_run(filtered_message, messages, functions)

    def invoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        return _forced_report_worker_response(messages) or super().invoke(messages, *args, **kwargs)

    async def ainvoke(self, messages: list[Message], *args: Any, **kwargs: Any) -> Any:
        forced = _forced_report_worker_response(messages)
        return forced if forced is not None else await super().ainvoke(messages, *args, **kwargs)

    def invoke_stream(self, messages: list[Message], *args: Any, **kwargs: Any) -> Iterator[Any]:
        forced = _forced_report_worker_response(messages, stream=True)
        if forced is not None:
            yield forced
            return
        yield from super().invoke_stream(messages, *args, **kwargs)

    async def ainvoke_stream(
        self, messages: list[Message], *args: Any, **kwargs: Any
    ) -> AsyncIterator[Any]:
        forced = _forced_report_worker_response(messages, stream=True)
        if forced is not None:
            yield forced
            return
        async for response in super().ainvoke_stream(messages, *args, **kwargs):
            yield response


class ReportFacadeOpenAIChat(ProjectedOpenAIChat):
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


def _report_model(settings: AgentSettings, *, enable_thinking: bool) -> OpenAIChat:
    return OpenAIChat(
        id=settings.model_id,
        base_url=settings.openai_base_url,
        api_key=settings.openai_api_key,
        timeout=settings.model_timeout_seconds,
        max_retries=0,
        role_map=OPENAI_COMPATIBLE_ROLE_MAP,
        extra_body={"enable_thinking": enable_thinking},
        temperature=1.0,
        top_p=1.0,
        collect_metrics_on_completion=(
            urlparse(settings.openai_base_url).hostname in _CUMULATIVE_STREAM_USAGE_HOSTS
        ),
        retries=2,
        exponential_backoff=True,
    )


def create_report_worker(
    settings: AgentSettings,
    database: AsyncBaseDb,
    workspace_service: WorkspaceService,
    task_repository: TaskExecutionRepository,
    *,
    instructions: AgentInstructions,
    report_coding_enable_thinking: bool = True,
    report_enable_vision: bool = False,
    context_token_budget: int = 262144,
    output_token_reserve: int = 32768,
) -> Agent:
    reporting_skills = load_reporting_skills(load_sandbox_execution_skills(settings.skills_dir))
    vision_reviewer = (
        ReportVisionReviewer(settings, workspace_service) if report_enable_vision else None
    )
    input_token_budget = max(
        1,
        min(context_token_budget, CODING_CONTEXT_TOKEN_LIMIT)
        - max(CODING_OUTPUT_TOKEN_RESERVE, output_token_reserve),
    )
    worker_model = _report_worker_model(
        _report_model(settings, enable_thinking=report_coding_enable_thinking),
        input_token_budget=input_token_budget,
    )
    worker_model._report_vision_enabled = report_enable_vision
    worker_model.max_tokens = output_token_reserve
    worker_model.temperature = settings.report_coding_temperature
    worker_model.top_p = 0.95
    worker_model.reasoning_effort = settings.report_coding_reasoning_effort
    extra_body = dict(worker_model.extra_body or {})
    if report_coding_enable_thinking:
        extra_body["thinking_budget"] = settings.report_coding_thinking_budget
    else:
        extra_body.pop("thinking_budget", None)
    worker_model.extra_body = extra_body
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
        instructions=instructions,
        use_instruction_tags=True,
        skills=reporting_skills,
        tools=partial(
            build_report_worker_tools,
            workspace_service,
            task_repository,
            vision_reviewer=vision_reviewer,
            context_token_budget=context_token_budget,
            output_token_reserve=output_token_reserve,
        ),
        db=database,
        checkpoint="tool-batch",
        add_history_to_context=False,
        enable_session_summaries=settings.enable_session_summaries,
        add_session_summary_to_context=False,
        session_summary_manager=(
            RollingSessionSummaryManager(model=_report_model(settings, enable_thinking=False))
            if settings.enable_session_summaries
            else None
        ),
        compress_tool_results=settings.enable_tool_result_compression,
        compression_manager=worker_compression_manager,
        retries=0,
        post_hooks=[clear_terminal_reasoning],
        tool_hooks=[
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
    facade_model.extra_body = {
        **(getattr(report_worker.model, "extra_body", None) or {}),
        "enable_thinking": False,
    }
    facade_model.extra_body.pop("thinking_budget", None)
    facade_model.temperature = 1.0
    facade_model.top_p = 0.95
    facade_model.reasoning_effort = None
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
        if not is_skill_script_hook(hook) and not is_task_tool_scheduler_hook(hook)
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
            "compression_manager": facade_compression_manager,
            "checkpoint": None,
            "instructions": [
                "新报表只调用无参数的 report_workflow_start；该工具会读取受信服务端 Envelope，或把当前"
                "最后一条用户消息原文交给 Workflow 首步。不得自行解析期间、改写目标、取数、执行 Coding "
                "或生成报告。Workflow 返回 request 阶段 paused 时，向用户"
                "展示 clarificationQuestion，并由 report_workflow_review 的 AgentOS 用户输入收集补充原文，"
                "使 Workflow 首步按官方 HumanReview retry 继续归一化。",
                "任一报表工具返回普通审核 paused 时，系统会先准确展示当前 review 预览，再在同一 "
                "run 中确定性调用 report_workflow_approve，由 AgentOS 原生确认收集批准或拒绝；"
                "拒绝备注由系统确定性交给 Workflow，不得由模型生成或改写。request 和 agent 阶段"
                "仍调用 report_workflow_review 收集对应输入；"
                "不得在文本回答中询问审批、猜测审批动作或宣称没有进行中的 Workflow。"
                "审核工具返回 paused 时重复本流程。",
                "工具返回 completed 后只返回其正式报告产物；不得把 paused、running 或 failed "
                "描述为完成。正式产物中的 downloadUrl 必须逐字保留为工具返回的相对路径，"
                "不得补充域名、协议或改写为示例地址；必须分别使用 "
                "`[下载 PDF](pdf.downloadUrl)` 和 `[下载 Word](word.downloadUrl)` 两个 Markdown "
                "链接，不得遗漏或合并；不得输出为裸路径、行内代码或代码块。",
            ],
            "tools": workflow_tools,
            "skills": None,
            "tool_hooks": facade_tool_hooks,
            "tool_choice": "auto",
        }
    )
    facade.num_history_runs = None
    return facade
