from __future__ import annotations

from contextvars import ContextVar
from functools import wraps
from inspect import isawaitable
from time import perf_counter
from typing import Any

from agno.db.base import BaseDb
from agno.models.metrics import RunMetrics
from agno.workflow import HumanReview, OnError, OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow
from loguru import logger

StepExecutor = Any
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


def _requires_request_review(output: StepOutput) -> bool:
    content = output.content
    return isinstance(content, dict) and bool(content.get("clarificationQuestion"))


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


def _timed_step_executor(executor: StepExecutor, *, step_id: str) -> StepExecutor:
    # Agno 2.8.2 只自动汇总 Agent/Team executor 的 metrics；报表步骤均为 function
    # executor，因此在报表自己的边界记录墙钟耗时，并保留步骤已有的 token metrics。
    @wraps(executor)
    async def execute(*args: Any, **kwargs: Any) -> Any:
        started_at = perf_counter()
        metrics_token = _STEP_MODEL_METRICS.set(RunMetrics())
        logger.info("report_workflow_step_started step_id={}", step_id)
        try:
            result = executor(*args, **kwargs)
            if isawaitable(result):
                result = await result
        except BaseException as error:
            logger.warning(
                "report_workflow_step_failed step_id={} duration_ms={} error_type={}",
                step_id,
                max(0, round((perf_counter() - started_at) * 1000)),
                type(error).__name__,
            )
            _STEP_MODEL_METRICS.reset(metrics_token)
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
        logger.info(
            "report_workflow_step_completed step_id={} duration_ms={} input_tokens={} "
            "output_tokens={} total_tokens={}",
            step_id,
            max(0, round(duration * 1000)),
            getattr(metrics, "input_tokens", None),
            getattr(metrics, "output_tokens", None),
            getattr(metrics, "total_tokens", None),
        )
        return result

    return execute


def create_reporting_workflow(
    *,
    db: BaseDb | Any,
    normalize_report_request: StepExecutor,
    confirm_source: StepExecutor,
    prepare_data_profile: StepExecutor,
    propose_measure_semantics: StepExecutor,
    commit_measure_semantics: StepExecutor,
    generate_outline: StepExecutor,
    generate_analysis_plan: StepExecutor,
    generate_query_candidates: StepExecutor,
    materialize_datasets: StepExecutor,
    prepare_analysis_context: StepExecutor,
    generate_detailed_analysis_plan: StepExecutor,
    run_coding_analysis: StepExecutor,
    validate_report: StepExecutor,
    finalize_publication: StepExecutor,
) -> Workflow:
    """创建可注册到现有 AgentOS 的报表 Workflow，不建立第二条传输链路。"""

    workflow = Workflow(
        id="enterprise-reporting-workflow-v1",
        name="企业智能运营报表",
        description="来源绑定、分析规划、受控取数、Coding 分析和报告发布。",
        db=db,
        # Console 的 Workflow WebSocket 只发送自然语言 message；首步骤继续使用
        # Reporting 自己的严格输入契约完成解析和校验，避免要求通用前端了解领域 Schema。
        input_schema=None,
        # 主进度只公开 Workflow/Step 事件。Agent、模型和 Daytona 工具调用仍保留在
        # Trace 中，不能混入面向用户的 14 个业务步骤列表。
        stream_executor_events=False,
        steps=[
            Step(
                step_id="normalize-report-request",
                name="规范化报表请求",
                executor=_timed_step_executor(
                    normalize_report_request, step_id="normalize-report-request"
                ),
                human_review=HumanReview(
                    requires_output_review=_requires_request_review,
                    output_review_message="补充缺失的主分析领域或分析期间。",
                    on_reject=OnReject.retry,
                    on_error=OnError.fail,
                    max_retries=5,
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="confirm-source",
                name="解析数据来源与数据结构",
                executor=_timed_step_executor(confirm_source, step_id="confirm-source"),
                max_retries=0,
                on_error=OnError.fail,
            ),
            # 数据理解计划决定画像范围，画像结果又是后续语义和分析规划的唯一输入。
            # 两者之间没有人工审核或可恢复副作用，放在同一失败关闭步骤中可以避免把
            # 同一份中间状态重复持久化；内部仍按“先计划、后画像”顺序执行，不能绕过
            # 计划对数据探查范围的限制。
            Step(
                step_id="prepare-data-profile",
                name="确定数据范围并执行受限数据画像",
                executor=_timed_step_executor(prepare_data_profile, step_id="prepare-data-profile"),
                max_retries=0,
                on_error=OnError.fail,
            ),
            # 指标语义候选与正式提交必须拆成两个 Workflow Step。前一步只允许模型生成
            # 候选且不能修改 session_state；后一步由确定性服务端代码重新校验候选并写入
            # 结构快照，模型不能通过直接改 Workflow state 绕过服务端口径约束。
            Step(
                step_id="propose-measure-semantics",
                name="生成指标语义候选",
                executor=_timed_step_executor(
                    propose_measure_semantics, step_id="propose-measure-semantics"
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="commit-measure-semantics",
                name="提交已确认指标语义",
                executor=_timed_step_executor(
                    commit_measure_semantics, step_id="commit-measure-semantics"
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-analysis-plan",
                name="生成分析计划与取数需求",
                executor=_timed_step_executor(
                    generate_analysis_plan, step_id="generate-analysis-plan"
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-query-candidates",
                name="生成并审核取数方案",
                executor=_timed_step_executor(
                    generate_query_candidates, step_id="generate-query-candidates"
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="materialize-datasets",
                name="物化不可变数据集",
                executor=_timed_step_executor(materialize_datasets, step_id="materialize-datasets"),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="prepare-analysis-context",
                name="准备分析数据上下文",
                executor=_timed_step_executor(
                    prepare_analysis_context, step_id="prepare-analysis-context"
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-detailed-analysis-plan",
                name="生成详细分析计划",
                executor=_timed_step_executor(
                    generate_detailed_analysis_plan, step_id="generate-detailed-analysis-plan"
                ),
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-outline",
                name="生成动态报告提纲",
                executor=_timed_step_executor(generate_outline, step_id="generate-outline"),
                max_retries=0,
                # 当前产品入口暂不启用提纲审核交互。这里是直接流向下一节点，不是
                # 自动批准；保留配置供审核能力上线时恢复，启用前必须补回端到端验收。
                # human_review=HumanReview(
                #     requires_output_review=True,
                #     output_review_message="审核动态报告提纲；拒绝时请填写修改意见。",
                #     on_reject=OnReject.retry,
                #     on_error=OnError.fail,
                #     max_retries=5,
                # ),
                on_error=OnError.fail,
            ),
            create_coding_analysis_step(run_coding_analysis),
            Step(
                step_id="validate-report",
                name="PDF/Word 双格式验收",
                executor=_timed_step_executor(validate_report, step_id="validate-report"),
                max_retries=0,
                # 取数、分析和章节已经在前一步完成并持久化。末端渲染或验收失败时由
                # Agno 保存 ErrorRequirement，恢复只重跑当前 Step，不能回到前序步骤。
                on_error=OnError.pause,
            ),
            Step(
                step_id="finalize-publication",
                name="发布门禁与正式发布",
                executor=_timed_step_executor(finalize_publication, step_id="finalize-publication"),
                max_retries=0,
                on_error=OnError.fail,
            ),
        ],
        telemetry=False,
    )
    return workflow


def create_coding_analysis_step(executor: StepExecutor) -> Step:
    """构造生产与历史回放共用的 Coding 分析步骤契约。"""

    return Step(
        step_id="run-coding-analysis",
        name="Coding 分析与成稿",
        executor=_timed_step_executor(executor, step_id="run-coding-analysis"),
        max_retries=0,
        on_error=OnError.fail,
    )
