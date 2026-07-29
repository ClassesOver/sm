from __future__ import annotations

from typing import Any

from agno.db.base import BaseDb
from agno.workflow import HumanReview, OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepOutput
from agno.workflow.workflow import Workflow
from pydantic import BaseModel

StepExecutor = Any


def create_reporting_workflow(
    *,
    db: BaseDb | Any,
    confirm_source: StepExecutor,
    profile_source: StepExecutor,
    generate_outline: StepExecutor,
    generate_analysis_plan: StepExecutor,
    generate_query_candidates: StepExecutor,
    materialize_datasets: StepExecutor,
    run_coding_analysis: StepExecutor,
    validate_report: StepExecutor,
    publish_report: StepExecutor,
) -> Workflow:
    """创建可注册到现有 AgentOS 的报表 Workflow，不建立第二条传输链路。"""

    workflow = Workflow(
        id="enterprise-reporting-workflow-v1",
        name="企业智能运营报表",
        description="来源绑定、分析规划、受控取数、Coding 分析和报告发布审核。",
        db=db,
        steps=[
            Step(
                name="确认数据来源",
                executor=confirm_source,
                human_review=HumanReview(
                    requires_output_review=True,
                    output_review_message="选择报表 Agent，或确认数据源、数据库和允许表。",
                    on_reject=OnReject.retry,
                    max_retries=3,
                ),
            ),
            Step(name="受限数据画像", executor=profile_source),
            Step(
                name="生成报告提纲",
                executor=generate_outline,
                human_review=HumanReview(
                    requires_output_review=True,
                    output_review_message="审核报告提纲；拒绝时请填写修改意见。",
                    on_reject=OnReject.retry,
                    max_retries=3,
                ),
            ),
            Step(name="生成分析计划与取数需求", executor=generate_analysis_plan),
            Step(
                name="生成并审核取数方案",
                executor=generate_query_candidates,
                human_review=HumanReview(
                    requires_output_review=_requires_query_review,
                    output_review_message="审核完整规范化 SQL 和哈希。",
                    on_reject=OnReject.retry,
                    max_retries=3,
                ),
            ),
            Step(name="物化不可变数据集", executor=materialize_datasets),
            Step(name="Coding 分析与成稿", executor=run_coding_analysis),
            Step(name="PDF 验收", executor=validate_report),
            Step(
                name="发布审核",
                executor=publish_report,
                human_review=HumanReview(
                    requires_output_review=True,
                    output_review_message="审核最终报告产物，批准后正式发布。",
                    on_reject=OnReject.retry,
                    max_retries=3,
                ),
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
