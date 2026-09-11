"""Reporting Task 生命周期协调边界。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from threading import Lock
from typing import Any

import anyio
from agno.run import RunContext
from loguru import logger

from ...async_utils import complete_cleanup
from ...model_routing import (
    DEFAULT_TASK_POLICIES,
    ModelRouter,
    ModelRouteRequest,
    ModelTier,
    RouteFailure,
    TaskPolicy,
)
from ...task_execution import (
    TASK_EXECUTION_DEPENDENCY,
    TaskExecutionKernel,
    TaskExecutionRepository,
    TaskExecutionScope,
    TaskSession,
    TaskState,
)
from ..models import ReportingError
from ..phase import (
    REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
    REPORTING_ANALYSIS_FACT_BUDGET_VERSION_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERIES_USED_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_FACT_QUERY_LIMIT_DEPENDENCY_KEY,
    REPORTING_ANALYSIS_RECOVERY_DEPENDENCY_KEY,
    REPORTING_MODEL_ID_DEPENDENCY_KEY,
    REPORTING_MODEL_TIER_DEPENDENCY_KEY,
    REPORTING_PHASE_DEPENDENCY_KEY,
    REPORTING_TASK_KIND_DEPENDENCY_KEY,
    REPORTING_THINKING_BUDGET_DEPENDENCY_KEY,
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
    REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY,
    REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY,
    bind_reporting_run_context,
    capture_reporting_projection_metrics,
    reporting_analysis_fact_budget_contract_from_acceptance_contract,
    reporting_analysis_fact_usage_from_run_context,
    reporting_phase_from_acceptance_contract,
    reporting_task_kind_from_acceptance_contract,
    reporting_thinking_budget_from_acceptance_contract,
    reporting_thinking_effort_from_acceptance_contract,
    reporting_visual_inspection_mode_from_acceptance_contract,
    reporting_visualization_budget_contract_from_acceptance_contract,
    reporting_visualization_budget_from_acceptance_contract,
    reporting_visualization_recovery_from_acceptance_contract,
    reporting_visualization_usage_from_run_context,
)
from .orchestration import record_step_model_metrics

ReportingEventSink = Callable[[TaskExecutionScope, str, Any], Awaitable[None]]
ReportTaskExecutor = Callable[["ReportingTaskInvocation"], Awaitable[Any]]
MAX_REPORT_INSTRUCTION_BYTES = 512 * 1024

_MODEL_TOKEN_FIELDS = (
    ("input_tokens", "inputTokens"),
    ("output_tokens", "outputTokens"),
    ("total_tokens", "totalTokens"),
    ("reasoning_tokens", "reasoningTokens"),
    ("cache_read_tokens", "cacheReadTokens"),
    ("cache_write_tokens", "cacheWriteTokens"),
)


@dataclass(frozen=True, slots=True)
class ReportingTaskInvocation:
    """协调器交给具体 executor 的一次已绑定任务调用。"""

    instruction: str
    run_context: RunContext
    continuing: bool
    scope: TaskExecutionScope
    parent_run_id: str
    model_metrics_settlement: _TaskModelMetricsSettlement


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
        logger.debug(
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


class ReportingTaskCoordinator:
    """协调 Reporting Task 生命周期，不持有或构造任何 Agent。"""

    def __init__(
        self,
        repository: TaskExecutionRepository,
        execution_cleanup: TaskExecutionKernel,
        *,
        model_profiles: Mapping[ModelTier, Any],
        task_policies: Mapping[str, TaskPolicy] = DEFAULT_TASK_POLICIES,
    ):
        self.repository = repository
        self.execution_cleanup = execution_cleanup
        self._model_router = ModelRouter(model_profiles, task_policies)

    async def start(
        self,
        scope: TaskExecutionScope,
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
        scope: TaskExecutionScope,
        *,
        parent_run_id: str = "",
        executor: ReportTaskExecutor,
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
            task_run_context: RunContext | None = None
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
                requirements = acceptance_contract.get("requirements")
                phase_contract: Mapping[str, Any] = {}
                if (
                    isinstance(requirements, list)
                    and requirements
                    and isinstance(requirements[0], Mapping)
                ):
                    parameters = requirements[0].get("parameters")
                    if isinstance(parameters, Mapping) and isinstance(
                        parameters.get("phaseContract"), Mapping
                    ):
                        phase_contract = parameters["phaseContract"]
                complexity = phase_contract.get("thinkingComplexityTier", "standard")
                if complexity not in {"simple", "standard", "complex"}:
                    complexity = "standard"
                escalation_reason = str(
                    phase_contract.get("thinkingEscalationReason") or ""
                ).lower()
                failure = (
                    RouteFailure.SCHEMA
                    if "schema" in escalation_reason
                    else RouteFailure.EVIDENCE
                    if any(marker in escalation_reason for marker in ("evidence", "fact"))
                    else RouteFailure.TRANSIENT
                    if continuing
                    else None
                )
                route_task_kind = (
                    "section_generation"
                    if reporting_task_kind == "section"
                    else reporting_task_kind
                )
                route = self._model_router.select(
                    ModelRouteRequest(
                        task_kind=route_task_kind or "facade",
                        complexity=complexity,
                        failure=failure,
                        attempt=1 if failure is not None else 0,
                    )
                )
                reporting_thinking_effort = reporting_thinking_effort_from_acceptance_contract(
                    acceptance_contract
                )
                reporting_thinking_budget = reporting_thinking_budget_from_acceptance_contract(
                    acceptance_contract
                )
                visual_inspection_mode = reporting_visual_inspection_mode_from_acceptance_contract(
                    acceptance_contract
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
                        REPORTING_MODEL_TIER_DEPENDENCY_KEY: route.tier,
                        REPORTING_MODEL_ID_DEPENDENCY_KEY: route.model_id,
                        **(
                            {
                                REPORTING_VISUALIZATION_TOOL_CALLS_DEPENDENCY_KEY: visualization_tool_calls,
                                REPORTING_VISUALIZATION_SCRIPT_FAILURES_DEPENDENCY_KEY: visualization_script_failures,
                                REPORTING_VISUALIZATION_BUDGET_VERSION_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationBudgetVersion"
                                ],
                                REPORTING_VISUALIZATION_EVIDENCE_READ_UNITS_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationEvidenceReadUnits"
                                ],
                                REPORTING_VISUALIZATION_READ_LIMIT_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationReadLimit"
                                ],
                                REPORTING_VISUALIZATION_FACT_QUERY_LIMIT_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationFactQueryLimit"
                                ],
                                REPORTING_VISUALIZATION_ATTEMPT_LIMIT_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationAttemptToolLimit"
                                ],
                                REPORTING_VISUALIZATION_TOTAL_LIMIT_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationTotalToolLimit"
                                ],
                                REPORTING_VISUALIZATION_READ_UNITS_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationReadUnitsUsed"
                                ],
                                REPORTING_VISUALIZATION_FACT_QUERIES_DEPENDENCY_KEY: visualization_budget[
                                    "visualizationFactQueriesUsed"
                                ],
                                **(
                                    {REPORTING_VISUALIZATION_RECOVERY_DEPENDENCY_KEY: True}
                                    if visualization_recovery
                                    else {}
                                ),
                            }
                            if reporting_task_kind == "visualization_section"
                            else {}
                        ),
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
                            {REPORTING_THINKING_BUDGET_DEPENDENCY_KEY: reporting_thinking_budget}
                            if reporting_thinking_budget is not None
                            else {}
                        ),
                        **(
                            {
                                REPORTING_VISUAL_INSPECTION_MODE_DEPENDENCY_KEY: (
                                    visual_inspection_mode
                                )
                            }
                            if reporting_task_kind == "visualization_section"
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
                task_session_id = _task_session_id(scope, attempt.attempt_no)
                task_run_context = RunContext(
                    run_id=attempt.internal_run_id,
                    session_id=task_session_id,
                    user_id=scope.owner_user_id,
                    session_state=(initial_session_state if not continuing else {}),
                    dependencies=dependencies,
                )
                # Agno 的流式模型请求在消费异步迭代器时才实际发生，因此捕获范围必须
                # 同时包住 run 创建与完整消费。显式 RunContext 让工具批次 checkpoint、
                # continuation 和模型投影共享同一个可持久化 session_state。
                with (
                    capture_reporting_projection_metrics() as projection_metrics,
                    bind_reporting_run_context(task_run_context),
                ):
                    output = await executor(
                        ReportingTaskInvocation(
                            instruction=instruction,
                            run_context=task_run_context,
                            continuing=continuing,
                            scope=scope,
                            parent_run_id=parent_run_id,
                            model_metrics_settlement=model_metrics_settlement,
                        )
                    )
                session.assert_alive()
                updated = await self.repository.get_task_snapshot(scope.external_run_id)
                if updated is None or updated.state is not TaskState.FINISHING:
                    raise ReportingError("report_worker_failed", "Reporting Task 未完成验收。")
                completed = await self.repository.finalize_finish(
                    scope.external_run_id,
                    session.lease,
                    updated.state_version,
                    agno_status=str(getattr(output, "status", "completed")),
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
                if reporting_task_kind == "analysis_item" and isinstance(error, Exception):
                    setattr(
                        error,
                        REPORTING_ANALYSIS_FACT_BUDGET_ERROR_ATTR,
                        {
                            "queryCount": reporting_analysis_fact_usage_from_run_context(
                                task_run_context
                            )
                        },
                    )
                if reporting_task_kind == "visualization_section" and isinstance(error, Exception):
                    setattr(
                        error,
                        REPORTING_VISUALIZATION_BUDGET_ERROR_ATTR,
                        reporting_visualization_usage_from_run_context(task_run_context),
                    )
                await complete_cleanup(self._cancel_and_cleanup(scope, session.lease.epoch))
                raise
            finally:
                if model_metrics_settlement is not None:
                    model_metrics_settlement.settle(outcome=task_outcome)

    async def cancel(self, scope: TaskExecutionScope) -> None:
        task = await self.repository.get_task_snapshot(scope.external_run_id)
        if task is None or task.state in {
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }:
            return
        await self.repository.cancel_and_reject(scope)
        await self.execution_cleanup.cleanup_disconnect(scope, task.lease_epoch)

    async def _cancel_and_cleanup(self, scope: TaskExecutionScope, lease_epoch: int) -> None:
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
                "Reporting Task 缺少正式产物验收回执。",
            )
        result = dict(receipt)
        if model_metrics:
            result["modelMetrics"] = dict(model_metrics)
        if projection_metrics is not None:
            result["projectionMetrics"] = dict(projection_metrics)
        return result


def _task_session_id(scope: TaskExecutionScope, attempt_no: int) -> str:
    return f"task-execution:{scope.external_run_id}:attempt:{attempt_no}"
