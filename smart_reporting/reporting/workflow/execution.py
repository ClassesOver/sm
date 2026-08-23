"""Reporting 专属的单次 Agno worker 执行边界。"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from inspect import isawaitable
from typing import Any

import anyio
from agno.agent import Agent
from agno.run import RunContext

from ...async_utils import complete_cleanup
from ...task_execution import TaskExecutionRepository, TaskScope, TaskState
from ...task_execution.execution import TASK_EXECUTION_DEPENDENCY, TaskExecutionKernel
from ...task_execution.session import TaskSession
from ..models import ReportingError
from ..phase import (
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_EFFORT_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
    REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_REGISTERED_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    bind_reporting_run_context,
    capture_reporting_projection_metrics,
    record_reporting_tool_event,
    reporting_phase_from_acceptance_contract,
    reporting_task_kind_from_acceptance_contract,
    reporting_thinking_effort_from_acceptance_contract,
    reporting_visualization_budget_from_acceptance_contract,
    reporting_visualization_budget_from_run_context,
    reporting_visualization_recovery_from_acceptance_contract,
    reporting_visualization_registered_from_acceptance_contract,
)

WorkerEventSink = Callable[[TaskScope, str, Any], Awaitable[None]]
MAX_REPORT_INSTRUCTION_BYTES = 512 * 1024
DEFAULT_REPORT_WORKER_IDLE_TIMEOUT_SECONDS = 900
MAX_REPORT_WORKER_CONTINUATIONS = 1
logger = logging.getLogger(__name__)


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
                visualization_recovery = reporting_visualization_recovery_from_acceptance_contract(
                    acceptance_contract
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
                            }
                            if reporting_task_kind == "visualization"
                            else {}
                        ),
                        **(
                            {REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY: True}
                            if reporting_task_kind == "visualization" and visualization_recovery
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
                return self._finish_receipt(
                    completed, output=output, projection_metrics=projection_metrics
                )
            except BaseException as error:
                if reporting_task_kind == "visualization" and isinstance(error, Exception):
                    # fresh retry 可能由模型超时等非预算异常触发；异常本身必须原样上抛，
                    # 但已经发生的工具调用不能因此从零开始。
                    setattr(
                        error,
                        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
                        reporting_visualization_budget_from_run_context(worker_run_context),
                    )
                await complete_cleanup(self._cancel_and_cleanup(scope, session.lease.epoch))
                raise

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
                            "服务端已保留本 run 成功读取的证据。立即停止继续读取和推演；"
                            "证据充足时只调用 render_report_section，证据不足时只调用 "
                            "request_analysis_rework。不得输出解释性文本。"
                        )
                    elif task_kind == "analysis_item" and recovery_attempt > 0:
                        recovery_instruction = (
                            "服务端已保留本 run 成功读取和写入的事实。立即停止继续探索；"
                            "只使用已有事实调用 complete_analysis_item，不得输出解释性文本。"
                        )
                    elif task_kind == "visualization" and recovery_attempt > 0:
                        recovery_instruction = (
                            "服务端已保留本 run 成功登记的分析进度。立即停止重新读取和推演；"
                            "若图表尚未登记则最多调用一次 register_report_charts，随后立即调用 "
                            "finalize_report_analysis，不得输出解释性文本。"
                        )
                    else:
                        recovery_instruction = (
                            "从失败工具调用后的已持久化消息继续；保留服务端已经接受的 analysis "
                            "进度，只修复失败动作，不得重放原始任务或重新提交已完成 analysisId。"
                        )
                    run_result: Any = self.worker.acontinue_run(
                        run_id=internal_run_id,
                        additional_instructions=(
                            recovery_instruction if recovery_attempt > 0 else None
                        ),
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
                output = await self._consume_run(run_result, scope, parent_run_id)
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
                logger.warning(
                    "Reporting Worker 未提交终态工具，触发同一 Agno run 收敛续跑: "
                    "run_id=%s task_kind=%s required_tools=%s",
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
                    "Reporting Worker 原异常触发同一 Agno run continuation: "
                    "run_id=%s attempt=%s/%s error=%s",
                    internal_run_id,
                    recovery_attempt + 1,
                    MAX_REPORT_WORKER_CONTINUATIONS,
                    error,
                )
                use_continuation = True

        raise RuntimeError("Reporting Worker continuation 状态不可达。")

    async def _consume_run(self, run_result: Any, scope: TaskScope, parent_run_id: str) -> Any:
        with anyio.fail_after(self.idle_timeout_seconds):
            output = await run_result if isawaitable(run_result) else run_result
        if not hasattr(output, "__aiter__"):
            return output
        last_event: Any = None
        iterator = output.__aiter__()
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
            if self.event_sink is not None and parent_run_id:
                try:
                    await self.event_sink(scope, parent_run_id, event)
                except Exception:
                    pass
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
        output: Any | None = None,
        projection_metrics: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        receipt = task.finish_receipt
        if not isinstance(receipt, dict):
            raise ReportingError(
                "report_artifact_acceptance_missing",
                "报表 Coding 任务缺少正式产物验收回执。",
            )
        result = dict(receipt)
        metrics = getattr(output, "metrics", None)
        model_metrics = {
            alias: value
            for field, alias in (
                ("input_tokens", "inputTokens"),
                ("output_tokens", "outputTokens"),
                ("total_tokens", "totalTokens"),
            )
            if not isinstance((value := getattr(metrics, field, None)), bool)
            and isinstance(value, int)
            and value >= 0
        }
        if model_metrics:
            result["modelMetrics"] = model_metrics
        if projection_metrics is not None:
            result["projectionMetrics"] = dict(projection_metrics)
        return result


def _worker_session_id(scope: TaskScope) -> str:
    digest = hashlib.sha256(f"{scope.thread_id}:{scope.external_run_id}".encode()).hexdigest()[:32]
    return f"report-worker-{digest}"
