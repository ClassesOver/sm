from __future__ import annotations

from typing import Any

from agno.db.base import BaseDb
from agno.workflow import OnError
from agno.workflow.step import Step
from agno.workflow.workflow import Workflow

from .contract import ReportingWorkflowInput

StepExecutor = Any


def create_reporting_workflow(
    *,
    db: BaseDb | Any,
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
                executor=normalize_report_request,
                on_error=OnError.fail,
            ),
            Step(
                step_id="confirm-source",
                name="解析数据来源与 Schema",
                executor=confirm_source,
                on_error=OnError.fail,
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
            # 指标语义候选与正式提交必须拆成两个 Workflow Step。前一步只允许模型生成
            # 候选且不能修改 session_state；后一步由确定性服务端代码重新校验候选并写入
            # 结构快照，模型不能通过直接改 Workflow state 绕过服务端口径约束。
            Step(
                step_id="propose-measure-semantics",
                name="生成指标语义候选",
                executor=propose_measure_semantics,
                on_error=OnError.fail,
            ),
            Step(
                step_id="commit-measure-semantics",
                name="提交已确认指标语义",
                executor=commit_measure_semantics,
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
                executor=generate_analysis_plan,
                max_retries=0,
                on_error=OnError.fail,
            ),
            Step(
                step_id="generate-query-candidates",
                name="生成并审核取数方案",
                executor=generate_query_candidates,
                max_retries=0,
                on_error=OnError.fail,
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
                on_error=OnError.fail,
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
