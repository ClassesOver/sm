from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from inspect import isawaitable
from time import perf_counter
from typing import Any

from agno.db.base import BaseDb
from agno.models.metrics import RunMetrics
from agno.workflow import OnError
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow

from .contract import ReportingWorkflowInput

StepExecutor = Any
EventSink = Any
_STEP_MODEL_METRICS: ContextVar[RunMetrics | None] = ContextVar(
    "reporting_step_model_metrics", default=None
)
_TOKEN_METRIC_FIELDS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
)


def record_step_model_metrics(value: Any) -> None:
    """把步骤内部模型调用的 usage 汇总到当前异步步骤上下文。"""
    current = _STEP_MODEL_METRICS.get()
    if current is None or value is None:
        return
    incoming = RunMetrics()
    for field in _TOKEN_METRIC_FIELDS:
        metric = getattr(value, field, None)
        if isinstance(metric, int | float):
            setattr(incoming, field, metric)
    _STEP_MODEL_METRICS.set(current + incoming)


def _event_metrics(metrics: RunMetrics, duration: float) -> dict[str, int | float]:
    payload = {
        field: value
        for field in _TOKEN_METRIC_FIELDS
        if isinstance((value := getattr(metrics, field, None)), int | float) and value > 0
    }
    payload["duration"] = duration
    return payload


def _timed_step_executor(
    executor: StepExecutor,
    *,
    step_id: str,
    step_name: str,
    event_sink: EventSink | None,
) -> StepExecutor:
    # Agno 2.8.2 只自动汇总 Agent/Team executor 的 metrics；报表步骤均为 function
    # executor，因此在报表自己的边界记录墙钟耗时，并保留步骤已有的 token metrics。
    @wraps(executor)
    async def execute(*args: Any, **kwargs: Any) -> Any:
        run_context = kwargs.get("run_context") or (args[1] if len(args) > 1 else None)
        base_event = {
            "stepId": step_id,
            "stepName": step_name,
            "executorName": str(getattr(executor, "__name__", "workflow_step")),
        }
        await _emit_event(event_sink, run_context, "workflow_step_started", base_event)
        started_at = perf_counter()
        metrics_token = _STEP_MODEL_METRICS.set(RunMetrics())
        try:
            result = executor(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except BaseException as error:
            duration = perf_counter() - started_at
            metrics = _STEP_MODEL_METRICS.get() or RunMetrics()
            _STEP_MODEL_METRICS.reset(metrics_token)
            await _emit_event(
                event_sink,
                run_context,
                "workflow_step_error",
                {
                    **base_event,
                    "error": str(error)[:2000],
                    "metrics": _event_metrics(metrics, duration),
                    "terminal": True,
                },
            )
            raise
        duration = perf_counter() - started_at
        collected_metrics = _STEP_MODEL_METRICS.get() or RunMetrics()
        _STEP_MODEL_METRICS.reset(metrics_token)
        metrics = collected_metrics
        if isinstance(result, StepOutput):
            if result.metrics is not None:
                metrics = metrics + result.metrics
            metrics.duration = duration
            result.metrics = metrics
        await _emit_event(
            event_sink,
            run_context,
            "workflow_step_completed",
            {
                **base_event,
                "metrics": _event_metrics(metrics, duration),
                **({"terminal": True} if step_id == "finalize-publication" else {}),
            },
        )
        return result

    return execute


async def _emit_event(
    event_sink: EventSink | None,
    run_context: Any,
    event_type: str,
    data: dict[str, Any],
) -> None:
    if event_sink is None or run_context is None:
        return
    try:
        result = event_sink(run_context, event_type, data)
        if isawaitable(result):
            await result
    except Exception:
        # 实时事件是可恢复的观察通道，不能改变 Workflow 的业务结果。
        return


def create_reporting_workflow(
    *,
    db: BaseDb | Any,
    event_sink: EventSink | None = None,
    normalize_report_request: StepExecutor,
    confirm_source: StepExecutor,
    plan_data_scope: StepExecutor,
    profile_source: StepExecutor,
    propose_measure_semantics: StepExecutor,
    commit_measure_semantics: StepExecutor,
    resolve_capabilities: StepExecutor,
    reconcile_sources: StepExecutor,
    generate_outline: StepExecutor,
    generate_analysis_plan: StepExecutor,
    generate_query_candidates: StepExecutor,
    materialize_datasets: StepExecutor,
    run_coding_analysis: StepExecutor,
    validate_report: StepExecutor,
    publish_report: StepExecutor,
    finalize_publication: StepExecutor,
) -> Workflow:
    """创建可注册到现有 AgentOS 的报表 Workflow，不建立第二条传输链路。"""

    workflow = Workflow(
        id="enterprise-reporting-workflow-v1",
        name="企业智能运营报表",
        description="来源绑定、分析规划、受控取数、Coding 分析和报告发布审核。",
        db=db,
        input_schema=ReportingWorkflowInput,
        steps=[
            Step(
                step_id="normalize-report-request",
                name="规范化报表请求",
                executor=_timed_step_executor(
                    normalize_report_request,
                    step_id="normalize-report-request",
                    step_name="规范化报表请求",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="confirm-source",
                name="解析数据来源与 Schema",
                executor=_timed_step_executor(
                    confirm_source,
                    step_id="confirm-source",
                    step_name="解析数据来源与 Schema",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="plan-data-scope",
                name="生成数据理解计划",
                executor=_timed_step_executor(
                    plan_data_scope,
                    step_id="plan-data-scope",
                    step_name="生成数据理解计划",
                    event_sink=event_sink,
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="profile-source",
                name="受限数据画像",
                executor=_timed_step_executor(
                    profile_source,
                    step_id="profile-source",
                    step_name="受限数据画像",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            # 指标语义候选与正式提交必须拆成两个 Workflow Step。前一步只允许模型生成
            # 候选且不能修改 session_state；后一步由确定性服务端代码重新校验候选并写入
            # 结构快照，模型不能通过直接改 Workflow state 绕过服务端口径约束。
            Step(
                step_id="propose-measure-semantics",
                name="生成指标语义候选",
                executor=_timed_step_executor(
                    propose_measure_semantics,
                    step_id="propose-measure-semantics",
                    step_name="生成指标语义候选",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="commit-measure-semantics",
                name="提交已确认指标语义",
                executor=_timed_step_executor(
                    commit_measure_semantics,
                    step_id="commit-measure-semantics",
                    step_name="提交已确认指标语义",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="resolve-capabilities",
                name="解析报表能力",
                executor=_timed_step_executor(
                    resolve_capabilities,
                    step_id="resolve-capabilities",
                    step_name="解析报表能力",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="reconcile-sources",
                name="执行跨表对账",
                executor=_timed_step_executor(
                    reconcile_sources,
                    step_id="reconcile-sources",
                    step_name="执行跨表对账",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-outline",
                name="生成报告提纲",
                executor=_timed_step_executor(
                    generate_outline,
                    step_id="generate-outline",
                    step_name="生成报告提纲",
                    event_sink=event_sink,
                ),
                # 当前产品阶段要求报表全流程连续执行，提纲也不暂停等待人工确认。
                # 后续恢复提纲审核时，只重新启用原 HumanReview 配置；审批控制器和恢复协议保留不变。
                # human_review=HumanReview(
                #     requires_output_review=True,
                #     output_review_message="审核报告提纲；拒绝时请填写修改意见。",
                #     on_reject=OnReject.retry,
                #     on_error=OnError.fail,
                #     max_retries=5,
                # ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-analysis-plan",
                name="生成分析计划与取数需求",
                executor=_timed_step_executor(
                    generate_analysis_plan,
                    step_id="generate-analysis-plan",
                    step_name="生成分析计划与取数需求",
                    event_sink=event_sink,
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-query-candidates",
                name="生成并审核取数方案",
                executor=_timed_step_executor(
                    generate_query_candidates,
                    step_id="generate-query-candidates",
                    step_name="生成并审核取数方案",
                    event_sink=event_sink,
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="materialize-datasets",
                name="物化不可变数据集",
                executor=_timed_step_executor(
                    materialize_datasets,
                    step_id="materialize-datasets",
                    step_name="物化不可变数据集",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="run-coding-analysis",
                name="Coding 分析与成稿",
                executor=_timed_step_executor(
                    run_coding_analysis,
                    step_id="run-coding-analysis",
                    step_name="Coding 分析与成稿",
                    event_sink=event_sink,
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="validate-report",
                name="PDF 验收",
                executor=_timed_step_executor(
                    validate_report,
                    step_id="validate-report",
                    step_name="PDF 验收",
                    event_sink=event_sink,
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="publish-report",
                name="发布审核",
                executor=_timed_step_executor(
                    publish_report,
                    step_id="publish-report",
                    step_name="发布审核",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
            Step(
                step_id="finalize-publication",
                name="正式发布",
                executor=_timed_step_executor(
                    finalize_publication,
                    step_id="finalize-publication",
                    step_name="正式发布",
                    event_sink=event_sink,
                ),
                on_error=OnError.fail,
            ),
        ],
        telemetry=False,
    )
    return workflow
