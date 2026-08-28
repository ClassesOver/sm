"""Reporting 专属的单次 Agno worker 执行边界。"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from inspect import isawaitable
from threading import Lock
from typing import Any

import anyio
from agno.agent import Agent
from agno.run import RunContext
from loguru import logger

from ...async_utils import complete_cleanup
from ...task_execution import TaskExecutionRepository, TaskScope, TaskState
from ...task_execution.execution import TASK_EXECUTION_DEPENDENCY, TaskExecutionKernel
from ...task_execution.session import TaskSession
from ..models import ReportingError
from ..phase import (
    REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
    REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_BUDGET_VERSION_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_EVIDENCE_READ_UNITS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY,
    bind_reporting_run_context,
    capture_reporting_projection_metrics,
    record_reporting_tool_event,
    reporting_analysis_fact_budget_contract_from_acceptance_contract,
    reporting_analysis_fact_usage_from_run_context,
    reporting_phase_from_acceptance_contract,
    reporting_task_kind_from_acceptance_contract,
    reporting_thinking_effort_from_acceptance_contract,
    reporting_visual_inspection_mode_from_acceptance_contract,
    reporting_visualization_budget_contract_from_acceptance_contract,
    reporting_visualization_budget_from_acceptance_contract,
    reporting_visualization_recovery_from_acceptance_contract,
    reporting_visualization_registered_from_acceptance_contract,
    reporting_visualization_usage_from_run_context,
)
from .orchestration import record_step_model_metrics

WorkerEventSink = Callable[[TaskScope, str, Any], Awaitable[None]]
MAX_REPORT_INSTRUCTION_BYTES = 512 * 1024
DEFAULT_REPORT_WORKER_IDLE_TIMEOUT_SECONDS = 900
MAX_REPORT_WORKER_CONTINUATIONS = 1

_MODEL_TOKEN_FIELDS = (
    ("input_tokens", "inputTokens"),
    ("output_tokens", "outputTokens"),
    ("total_tokens", "totalTokens"),
    ("reasoning_tokens", "reasoningTokens"),
    ("cache_read_tokens", "cacheReadTokens"),
    ("cache_write_tokens", "cacheWriteTokens"),
)


class _TaskModelMetricsSettlement:
    """按 Task attempt 的真实模型响应统一结算指标。"""

    def __init__(self, *, task_id: str, phase_attempt: int, agno_run_id: str) -> None:
        self.task_id = task_id
        self.phase_attempt = phase_attempt
        self.agno_run_id = agno_run_id
        self._lock = Lock()
        self._seen: set[tuple[str, int, str, int]] = set()
        self._next_response_index = 0
        self._settled = False
        self._metrics: dict[str, int | float] = {
            "requestCount": 0,
            **{alias: 0 for _, alias in _MODEL_TOKEN_FIELDS},
        }

    def record(self, event: Any, *, model_response_index: int | None = None) -> None:
        raw_event = getattr(event, "event", None) or getattr(event, "type", None)
        event_type = str(getattr(raw_event, "value", raw_event) or "").replace("_", "").lower()
        if event_type != "modelrequestcompleted":
            return
        with self._lock:
            if model_response_index is None:
                model_response_index = self._next_response_index
            if model_response_index < 0:
                raise ValueError("model_response_index 必须大于等于 0")
            self._next_response_index = max(self._next_response_index, model_response_index + 1)
            identity = (
                self.task_id,
                self.phase_attempt,
                self.agno_run_id,
                model_response_index,
            )
            if identity in self._seen:
                return
            self._seen.add(identity)
            self._metrics["requestCount"] += 1
            for field, alias in _MODEL_TOKEN_FIELDS:
                value = getattr(event, field, None)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    self._metrics[alias] += value
            # Agno 3.0 的完成事件没有完整 request latency；这里只汇总它明确提供的 TTFT，
            # 步骤墙钟耗时仍由 Workflow executor 记录，不能把两者混为同一指标。
            time_to_first_token = getattr(event, "time_to_first_token", None)
            if (
                isinstance(time_to_first_token, int | float)
                and not isinstance(time_to_first_token, bool)
                and time_to_first_token >= 0
            ):
                self._metrics["timeToFirstTokenSeconds"] = (
                    self._metrics.get("timeToFirstTokenSeconds", 0) + time_to_first_token
                )

    def record_stream(self, events: list[Any]) -> None:
        """将一次 Agno stream 映射到稳定的模型响应序号。"""

        for event in events:
            self.record(event)

    def snapshot(self) -> dict[str, int | float]:
        with self._lock:
            return dict(self._metrics)

    def settle(self, *, outcome: str) -> None:
        with self._lock:
            if self._settled:
                return
            self._settled = True
            metrics = dict(self._metrics)
        record_step_model_metrics(metrics)
        logger.info(
            "report_worker_model_metrics_settled task_id={} phase_attempt={} agno_run_id={} "
            "outcome={} request_count={} total_tokens={} reasoning_tokens={} "
            "time_to_first_token_seconds={}",
            self.task_id,
            self.phase_attempt,
            self.agno_run_id,
            outcome,
            metrics["requestCount"],
            metrics["totalTokens"],
            metrics["reasoningTokens"],
            metrics.get("timeToFirstTokenSeconds"),
        )


def _raise_recorded_agent_error(agent: Agent) -> None:
    """Agno 最终以 error RunOutput 收敛时，恢复模型边界记录的原异常对象。"""

    report_run_error = getattr(agent.model, "report_run_error", None)
    error = report_run_error() if callable(report_run_error) else None
    if isinstance(error, Exception):
        raise error


class ReportTaskRunner:
    """由 Reporting Workflow 驱动一次 worker run，不复用 Coding Supervisor 状态机。"""

    def __init__(
        self,
        repository: TaskExecutionRepository,
        worker: Agent,
        execution_cleanup: TaskExecutionKernel,
        *,
        event_sink: WorkerEventSink | None = None,
        idle_timeout_seconds: float = DEFAULT_REPORT_WORKER_IDLE_TIMEOUT_SECONDS,
    ):
        if idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds 必须大于 0")
        self.repository = repository
        self.worker = worker
        self.execution_cleanup = execution_cleanup
        self.event_sink = event_sink
        self.idle_timeout_seconds = idle_timeout_seconds

    async def start(
        self,
        scope: TaskScope,
        instruction: str,
        *,
        acceptance_contract: dict[str, Any],
    ) -> None:
        await self.repository.create_task_with_initial_attempt(
            scope,
            instruction,
            acceptance_contract=acceptance_contract,
            max_instruction_bytes=MAX_REPORT_INSTRUCTION_BYTES,
        )

    async def run(
        self,
        scope: TaskScope,
        *,
        parent_run_id: str = "",
    ) -> dict[str, Any]:
        async with TaskSession(self.repository, scope) as session:
            await self.execution_cleanup.cleanup_old_epoch(scope, session.lease.epoch)
            task = await self.repository.get_task_snapshot(scope.external_run_id)
            if task is None:
                raise ReportingError("report_worker_task_missing", "报表分析任务不存在。")
            if task.state is TaskState.COMPLETED:
                return self._finish_receipt(task)
            if task.state is TaskState.FINISHING:
                completed = await self.repository.finalize_finish(
                    scope.external_run_id,
                    session.lease,
                    task.state_version,
                    agno_status="completed",
                )
                return self._finish_receipt(completed)
            continuing = task.state in {TaskState.ACTIVE, TaskState.SUSPENDED}
            reporting_phase: str | None = None
            reporting_task_kind: str | None = None
            worker_run_context: RunContext | None = None
            model_metrics_settlement: _TaskModelMetricsSettlement | None = None
            task_outcome = "failed"
            try:
                acceptance_contract = task.acceptance_contract
                if not isinstance(acceptance_contract, Mapping):
                    raise ReportingError(
                        "report_phase_contract_invalid",
                        "Reporting 内部任务缺少受信 phase 契约。",
                    )
                reporting_phase = reporting_phase_from_acceptance_contract(acceptance_contract)
                if reporting_phase is None:
                    raise ReportingError(
                        "report_phase_contract_invalid",
                        "Reporting 内部任务缺少受信 phase 契约。",
                    )
                reporting_task_kind = reporting_task_kind_from_acceptance_contract(
                    acceptance_contract
                )
                reporting_thinking_effort = reporting_thinking_effort_from_acceptance_contract(
                    acceptance_contract
                )
                visualization_registered = (
                    reporting_visualization_registered_from_acceptance_contract(acceptance_contract)
                )
                visualization_tool_calls, visualization_script_failures = (
                    reporting_visualization_budget_from_acceptance_contract(acceptance_contract)
                )
                visualization_budget = (
                    reporting_visualization_budget_contract_from_acceptance_contract(
                        acceptance_contract
                    )
                )
                visualization_recovery = reporting_visualization_recovery_from_acceptance_contract(
                    acceptance_contract
                )
                visual_inspection_mode = reporting_visual_inspection_mode_from_acceptance_contract(
                    acceptance_contract
                )
                analysis_fact_budget = (
                    reporting_analysis_fact_budget_contract_from_acceptance_contract(
                        acceptance_contract
                    )
                )
                if continuing:
                    task, attempt = await self.repository.resume_current(
                        scope.external_run_id,
                        session.lease,
                        task.state_version,
                    )
                else:
                    task, attempt = await self.repository.open_initial(
                        scope.external_run_id,
                        session.lease,
                        task.state_version,
                    )
                instruction = await self.repository.attempt_instruction(
                    scope.external_run_id,
                    attempt.attempt_no,
                )
                model_metrics_settlement = _TaskModelMetricsSettlement(
                    task_id=scope.external_run_id,
                    phase_attempt=attempt.attempt_no,
                    agno_run_id=attempt.internal_run_id,
                )
                dependencies = {
                    TASK_EXECUTION_DEPENDENCY: {
                        "externalRunId": scope.external_run_id,
                        "threadId": scope.thread_id,
                        "sandboxId": scope.sandbox_id,
                        "leaseOwner": session.lease.owner,
                        "leaseEpoch": session.lease.epoch,
                        "attemptNo": attempt.attempt_no,
                        REPORTING_PHASE_DEPENDENCY_KEY: reporting_phase,
                        **(
                            {REPORTING_TASK_KIND_DEPENDENCY_KEY: reporting_task_kind}
                            if reporting_task_kind is not None
                            else {}
                        ),
                        **(
                            {REPORTING_THINKING_EFFORT_DEPENDENCY_KEY: (reporting_thinking_effort)}
                            if reporting_thinking_effort is not None
                            else {}
                        ),
                        **(
                            {REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY: True}
                            if visualization_registered
                            else {}
                        ),
                        **(
                            {
                                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: (
                                    visualization_tool_calls
                                ),
                                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: (
                                    visualization_script_failures
                                ),
                                REPORTING_VISUALIZATION_BUDGET_VERSION_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationBudgetVersion"]
                                ),
                                REPORTING_VISUALIZATION_EVIDENCE_READ_UNITS_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationEvidenceReadUnits"]
                                ),
                                REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationReadLimit"]
                                ),
                                REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationFactQueryLimit"]
                                ),
                                REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationAttemptToolLimit"]
                                ),
                                REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationTotalToolLimit"]
                                ),
                                REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationReadUnitsUsed"]
                                ),
                                REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY: (
                                    visualization_budget["visualizationFactQueriesUsed"]
                                ),
                            }
                            if reporting_task_kind == "visualization"
                            else {}
                        ),
                        **(
                            {REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY: True}
                            if reporting_task_kind == "visualization" and visualization_recovery
                            else {}
                        ),
                        **(
                            {
                                REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY: (
                                    visual_inspection_mode
                                )
                            }
                            if reporting_task_kind == "visualization"
                            and visual_inspection_mode is not None
                            else {}
                        ),
                        **(
                            {
                                REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY: (
                                    analysis_fact_budget["analysisFactBudgetVersion"]
                                ),
                                REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY: (
                                    analysis_fact_budget["analysisFactQueryLimit"]
                                ),
                                REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY: (
                                    analysis_fact_budget["analysisFactQueriesUsed"]
                                ),
                                REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY: (
                                    analysis_fact_budget["analysisRecovery"]
                                ),
                            }
                            if reporting_task_kind == "analysis_item"
                            else {}
                        ),
                    }
                }
                initial_session_state: dict[str, Any] = {}
                worker_session_id = _worker_session_id(scope)
                worker_run_context = RunContext(
                    run_id=attempt.internal_run_id,
                    session_id=worker_session_id,
                    user_id=scope.owner_user_id,
                    session_state=(initial_session_state if not continuing else {}),
                    dependencies=dependencies,
                )
                # Agno 的流式模型请求在消费异步迭代器时才实际发生，因此捕获范围必须
                # 同时包住 run 创建与完整消费。显式 RunContext 让工具批次 checkpoint、
                # continuation 和模型投影共享同一个可持久化 session_state。
                with (
                    capture_reporting_projection_metrics() as projection_metrics,
                    bind_reporting_run_context(worker_run_context),
                ):
                    output = await self._run_worker(
                        continuing=continuing,
                        instruction=instruction,
                        internal_run_id=attempt.internal_run_id,
                        worker_session_id=worker_session_id,
                        owner_user_id=scope.owner_user_id,
                        dependencies=dependencies,
                        run_context=worker_run_context,
                        scope=scope,
                        parent_run_id=parent_run_id,
                        model_metrics_settlement=model_metrics_settlement,
                    )
                session.assert_alive()
                updated = await self.repository.get_task_snapshot(scope.external_run_id)
                if updated is None or updated.state is not TaskState.FINISHING:
                    raise ReportingError("report_worker_failed", "报表 Coding 分析未完成验收。")
                completed = await self.repository.finalize_finish(
                    scope.external_run_id,
                    session.lease,
                    updated.state_version,
                    agno_status=str(getattr(output, "status", "completed")),
                )
                if reporting_task_kind == "visualization":
                    projection_metrics.update(
                        reporting_visualization_usage_from_run_context(worker_run_context)
                    )
                task_outcome = "completed"
                return self._finish_receipt(
                    completed,
                    model_metrics=model_metrics_settlement.snapshot(),
                    projection_metrics=projection_metrics,
                )
            except BaseException as error:
                if isinstance(error, anyio.get_cancelled_exc_class()):
                    task_outcome = "cancelled"
                if reporting_task_kind == "visualization" and isinstance(error, Exception):
                    # fresh retry 可能由模型超时等非预算异常触发；异常本身必须原样上抛，
                    # 但已经发生的工具调用不能因此从零开始。
                    setattr(
                        error,
                        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
                        reporting_visualization_usage_from_run_context(worker_run_context),
                    )
                if reporting_task_kind == "analysis_item" and isinstance(error, Exception):
                    setattr(
                        error,
                        REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
                        {
                            "queryCount": reporting_analysis_fact_usage_from_run_context(
                                worker_run_context
                            )
                        },
                    )
                await complete_cleanup(self._cancel_and_cleanup(scope, session.lease.epoch))
                raise
            finally:
                if model_metrics_settlement is not None:
                    model_metrics_settlement.settle(outcome=task_outcome)

    async def _run_worker(
        self,
        *,
        continuing: bool,
        instruction: str,
        internal_run_id: str,
        worker_session_id: str,
        owner_user_id: str,
        dependencies: dict[str, Any],
        run_context: RunContext,
        scope: TaskScope,
        parent_run_id: str,
        model_metrics_settlement: _TaskModelMetricsSettlement | None = None,
    ) -> Any:
        """在同一 Agno run 上恢复非领域异常，禁止重放过期的 Reporting 指令。

        Reporting 工具会推进当前 analysis 游标并写入工作区。Agno Agent.retries 会重新
        使用原始 run input；失败 run 已启用 tool-batch checkpoint，因此只允许一次公共
        acontinue_run 从同一 analysis 的持久化消息末尾恢复。新的 analysis 使用独立 Task、
        run 和 session，不能继承这里的 continuation。
        """

        use_continuation = continuing
        binding = dependencies.get(TASK_EXECUTION_DEPENDENCY)
        task_kind = (
            binding.get(REPORTING_TASK_KIND_DEPENDENCY_KEY)
            if isinstance(binding, Mapping)
            else None
        )
        terminal_tools: tuple[str, ...]
        if task_kind == "analysis_item":
            terminal_tools = ("complete_analysis_item",)
        elif task_kind == "visualization":
            terminal_tools = ("finalize_report_analysis",)
        elif task_kind == "section":
            terminal_tools = ("render_report_section", "request_analysis_rework")
        else:
            terminal_tools = ()
        for recovery_attempt in range(MAX_REPORT_WORKER_CONTINUATIONS + 1):
            try:
                if use_continuation:
                    if task_kind == "section" and recovery_attempt > 0:
                        recovery_instruction = (
                            "先读取当前文件并确认实际内容。服务端已保留本 run 成功读取的证据。"
                            "立即停止继续读取和推演；"
                            "证据充足时只调用 render_report_section，证据不足时只调用 "
                            "request_analysis_rework。不得输出解释性文本。"
                        )
                    elif task_kind == "analysis_item" and recovery_attempt > 0:
                        recovery_instruction = (
                            "先读取当前文件并确认实际内容。服务端已保留本 run 成功读取和写入的事实。"
                            "立即停止继续探索；"
                            "只使用已有事实调用 complete_analysis_item，不得输出解释性文本。"
                        )
                    elif task_kind == "visualization" and recovery_attempt > 0:
                        recovery_instruction = (
                            "先读取当前脚本和图表并确认实际内容。服务端已保留本 run 成功登记的分析进度。"
                            "立即停止重新读取和推演；"
                            "若图表尚未登记则最多调用一次 register_report_charts，随后立即调用 "
                            "finalize_report_analysis，不得输出解释性文本。"
                        )
                    else:
                        recovery_instruction = (
                            "先读取当前文件或脚本并确认实际内容，再修正失败动作、执行、检查结果并登记；"
                            "从失败工具调用后的已持久化消息继续，保留服务端已经接受的 analysis 进度，"
                            "不得重放原始任务或重新提交已完成 analysisId。"
                        )
                    run_result: Any = self.worker.acontinue_run(
                        run_id=internal_run_id,
                        input=recovery_instruction,
                        stream=True,
                        stream_events=True,
                        session_id=worker_session_id,
                        user_id=owner_user_id,
                        dependencies=dependencies,
                        run_context=run_context,
                    )
                else:
                    run_result = self.worker.arun(
                        instruction,
                        stream=True,
                        stream_events=True,
                        run_id=internal_run_id,
                        session_id=worker_session_id,
                        user_id=owner_user_id,
                        dependencies=dependencies,
                        run_context=run_context,
                    )
                output = await self._consume_run(
                    run_result,
                    scope,
                    parent_run_id,
                    continuation=use_continuation,
                    model_metrics_settlement=model_metrics_settlement,
                )
                _raise_recorded_agent_error(self.worker)
                if not terminal_tools:
                    return output
                updated = await self.repository.get_task_snapshot(scope.external_run_id)
                if updated is not None and updated.state is TaskState.FINISHING:
                    return output
                missing_terminal = ReportingError(
                    "report_worker_terminal_tool_missing",
                    "Reporting Worker 以普通文本结束，未提交当前阶段终态工具。",
                    details={
                        "taskKind": task_kind,
                        "requiredTerminalTools": list(terminal_tools),
                    },
                )
                if recovery_attempt >= MAX_REPORT_WORKER_CONTINUATIONS:
                    raise missing_terminal
                if task_kind == "section":
                    # Section 的终态是一次性章节提交；普通文本没有推进任何持久化状态。
                    # 继续同一 Agno run 只会把完整章节历史再次带入模型，日志已证明这会
                    # 触发长 continuation。交给外层 fresh attempt，恢复原始错误和章节边界。
                    raise missing_terminal
                logger.warning(
                    "report_worker_terminal_tool_missing_continuation run_id={} task_kind={} "
                    "required_tools={}",
                    internal_run_id,
                    task_kind,
                    ",".join(terminal_tools),
                )
                use_continuation = True
            except ReportingError:
                raise
            except Exception as error:
                if recovery_attempt >= MAX_REPORT_WORKER_CONTINUATIONS:
                    raise
                logger.warning(
                    "report_worker_error_continuation run_id={} attempt={} max_attempts={} "
                    "error_type={}",
                    internal_run_id,
                    recovery_attempt + 1,
                    MAX_REPORT_WORKER_CONTINUATIONS,
                    type(error).__name__,
                )
                use_continuation = True

        raise RuntimeError("Reporting Worker continuation 状态不可达。")

    async def _consume_run(
        self,
        run_result: Any,
        scope: TaskScope,
        parent_run_id: str,
        *,
        continuation: bool = False,
        model_metrics_settlement: _TaskModelMetricsSettlement | None = None,
    ) -> Any:
        with anyio.fail_after(self.idle_timeout_seconds):
            output = await run_result if isawaitable(run_result) else run_result
        if not hasattr(output, "__aiter__"):
            return output
        last_event: Any = None
        model_response_events: list[Any] = []
        accept_model_events = not continuation
        iterator = output.__aiter__()
        try:
            while True:
                try:
                    # analysis 总时长不设硬上限；只限制相邻事件的空闲时间。这样长报告可
                    # 持续运行，而模型请求、hook 或持久化永久挂起时会进入 fresh retry。
                    with anyio.fail_after(self.idle_timeout_seconds):
                        event = await anext(iterator)
                except StopAsyncIteration:
                    break
                last_event = event
                record_reporting_tool_event(event)
                if model_metrics_settlement is not None:
                    raw_event = getattr(event, "event", None) or getattr(event, "type", None)
                    event_type = (
                        str(getattr(raw_event, "value", raw_event) or "").replace("_", "").lower()
                    )
                    if event_type == "runcontinued":
                        # Agno 3.0 的 continuation 在本轮模型请求前发出 RunContinued。
                        # 重连层可能先重印同一 run 的历史事件，边界前的完成回执必须
                        # 丢弃；边界后的响应按出现顺序追加稳定 modelResponseIndex。
                        model_response_events.clear()
                        accept_model_events = True
                    elif event_type == "modelrequestcompleted" and accept_model_events:
                        model_response_events.append(event)
                if self.event_sink is not None and parent_run_id:
                    try:
                        await self.event_sink(scope, parent_run_id, event)
                    except Exception:
                        pass
        finally:
            if model_metrics_settlement is not None:
                model_metrics_settlement.record_stream(model_response_events)
        return last_event

    async def cancel(self, scope: TaskScope) -> None:
        task = await self.repository.get_task_snapshot(scope.external_run_id)
        if task is None or task.state in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            return
        await self.repository.cancel_and_reject(scope)
        await self.execution_cleanup.cleanup_disconnect(scope, task.lease_epoch)

    async def _cancel_and_cleanup(self, scope: TaskScope, lease_epoch: int) -> None:
        try:
            await self.repository.cancel_and_reject(scope)
        finally:
            await self.execution_cleanup.cleanup_disconnect(scope, lease_epoch)

    @staticmethod
    def _finish_receipt(
        task: Any,
        *,
        model_metrics: Mapping[str, int | float] | None = None,
        projection_metrics: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        receipt = task.finish_receipt
        if not isinstance(receipt, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "报表 Coding 任务缺少正式产物验收回执。",
            )
        result = dict(receipt)
        if model_metrics:
            result["modelMetrics"] = dict(model_metrics)
        if projection_metrics is not None:
            result["projectionMetrics"] = dict(projection_metrics)
        return result


def _worker_session_id(scope: TaskScope) -> str:
    digest = hashlib.sha256(f"{scope.thread_id}:{scope.external_run_id}".encode()).hexdigest()[:32]
    return f"report-worker-{digest}"
