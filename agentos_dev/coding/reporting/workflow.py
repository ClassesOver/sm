from __future__ import annotations

from typing import Any

from agno.db.base import BaseDb
from agno.workflow import HumanReview, OnError, OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel

from .contract import ReportingWorkflowInput

StepExecutor = Any


def create_reporting_workflow(
    *,
    db: BaseDb | Any,
    normalize_report_request: StepExecutor,
    confirm_source: StepExecutor,
    plan_data_scope: StepExecutor,
    profile_source: StepExecutor,
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
                executor=normalize_report_request,
                human_review=HumanReview(
                    requires_output_review=_requires_request_clarification,
                    output_review_message="请补充报表分析期间。",
                    on_reject=OnReject.retry,
                    on_error=OnError.fail,
                    max_retries=5,
                ),
            ),
            Step(
                step_id="confirm-source",
                name="解析数据来源与 Schema",
                executor=confirm_source,
                human_review=HumanReview(
                    requires_output_review=_requires_source_review,
                    output_review_message="请选择报表 Agent。",
                    on_reject=OnReject.retry,
                    on_error=OnError.fail,
                    max_retries=5,
                ),
            ),
            Step(
                step_id="plan-data-scope",
                name="生成数据理解计划",
                executor=plan_data_scope,
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="profile-source",
                name="受限数据画像",
                executor=profile_source,
                on_error=OnError.fail,
            ),
            Step(
                step_id="resolve-capabilities",
                name="解析报表能力",
                executor=resolve_capabilities,
                on_error=OnError.fail,
            ),
            Step(
                step_id="reconcile-sources",
                name="执行跨表对账",
                executor=reconcile_sources,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-outline",
                name="生成报告提纲",
                executor=generate_outline,
                human_review=HumanReview(
                    requires_output_review=True,
                    output_review_message="审核报告提纲；拒绝时请填写修改意见。",
                    on_reject=OnReject.retry,
                    on_error=OnError.fail,
                    max_retries=5,
                ),
            ),
            Step(
                step_id="generate-analysis-plan",
                name="生成分析计划与取数需求",
                executor=generate_analysis_plan,
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-query-candidates",
                name="生成并审核取数方案",
                executor=generate_query_candidates,
                max_retries=0,
                human_review=HumanReview(
                    requires_output_review=_requires_query_review,
                    output_review_message="审核完整规范化 SQL 和哈希。",
                    on_reject=OnReject.retry,
                    on_error=OnError.fail,
                    max_retries=5,
                ),
            ),
            Step(
                step_id="materialize-datasets",
                name="物化不可变数据集",
                executor=materialize_datasets,
                on_error=OnError.fail,
            ),
            Step(
                step_id="run-coding-analysis",
                name="Coding 分析与成稿",
                executor=run_coding_analysis,
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="validate-report",
                name="PDF 验收",
                executor=validate_report,
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="publish-report",
                name="发布审核",
                executor=publish_report,
                human_review=HumanReview(
                    requires_output_review=True,
                    output_review_message="审核最终报告产物，批准后正式发布。",
                    on_reject=OnReject.retry,
                    on_error=OnError.fail,
                    max_retries=5,
                ),
            ),
            Step(
                step_id="finalize-publication",
                name="正式发布",
                executor=finalize_publication,
                on_error=OnError.fail,
            ),
        ],
        telemetry=False,
    )
    return workflow


def _requires_query_review(output: StepOutput) -> bool:
    content = output.content
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", by_alias=True)
    queries = content.get("queries") if isinstance(content, dict) else None
    return isinstance(queries, list) and bool(queries)


def _requires_source_review(output: StepOutput) -> bool:
    content = output.content
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", by_alias=True)
    agents = content.get("agents") if isinstance(content, dict) else None
    return isinstance(agents, list) and len(agents) > 1


def _requires_request_clarification(output: StepOutput) -> bool:
    content = output.content
    if isinstance(content, BaseModel):
        content = content.model_dump(mode="json", by_alias=True)
    return isinstance(content, dict) and bool(content.get("clarificationQuestion"))
