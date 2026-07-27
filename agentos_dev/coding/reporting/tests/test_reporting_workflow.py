from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.workflow import OnReject
from agno.workflow.types import StepInput, StepOutput

from agentos_dev.coding.reporting import (
    DataRequirement,
    ReportingError,
    ReportSourceBinding,
    SourceMode,
)
from agentos_dev.coding.reporting.adapters import CliReviewAdapter
from agentos_dev.coding.reporting.controller import (
    REPORT_WORKFLOW_CONTROL_STATE_KEY,
    ReportWorkflowController,
    ReportWorkflowToolkit,
)
from agentos_dev.coding.reporting.data_sources import DatasetHandle
from agentos_dev.coding.reporting.quality import (
    comparison_decisions,
    reconcile_metric,
    validate_fact_combination,
    validate_metric_aggregation,
)
from agentos_dev.coding.reporting.runtime import (
    REPORT_DATA_REQUIREMENTS_STATE_KEY,
    REPORT_QUERY_CANDIDATES_STATE_KEY,
    ReportWorkflowRuntime,
)
from agentos_dev.coding.reporting.state import (
    REPORT_ANALYSIS_PLAN_STATE_KEY,
    REPORT_ARTIFACTS_STATE_KEY,
    REPORT_OUTLINE_STATE_KEY,
    REPORT_REVIEW_STATE_KEY,
    REPORT_SOURCE_BINDING_STATE_KEY,
    bind_report_source,
    validate_hybrid_lineage,
)
from agentos_dev.coding.reporting.workflow import create_reporting_workflow


def source_binding(fingerprint="a" * 64):
    return ReportSourceBinding(
        bindingId="src_binding",
        sourceMode=SourceMode.TEMPORARY_DATABASE,
        database="hospital",
        allowedTables=("hospital.revenue",),
        metadataFingerprint=fingerprint,
        threadId="thread",
        userId="user",
        sessionId="session",
        expiresAt=datetime.now(UTC) + timedelta(hours=2),
    )


def test_来源变化使提纲计划数据集和报告产物全部失效():
    state = {
        REPORT_OUTLINE_STATE_KEY: {"approved": True},
        REPORT_ANALYSIS_PLAN_STATE_KEY: {"planId": "plan"},
        "report_dataset_handles": {"dataset": {}},
        REPORT_REVIEW_STATE_KEY: {"publication": "approved"},
        REPORT_ARTIFACTS_STATE_KEY: ["report.pdf"],
        "report_delivery": {"deliveryId": "delivery"},
        "report_jobs": {"job": {}},
    }

    assert bind_report_source(state, source_binding()) is True
    assert state[REPORT_SOURCE_BINDING_STATE_KEY]["bindingId"] == "src_binding"
    for key in (
        REPORT_OUTLINE_STATE_KEY,
        REPORT_ANALYSIS_PLAN_STATE_KEY,
        "report_dataset_handles",
        REPORT_REVIEW_STATE_KEY,
        REPORT_ARTIFACTS_STATE_KEY,
        "report_delivery",
        "report_jobs",
    ):
        assert key not in state

    state[REPORT_OUTLINE_STATE_KEY] = {"approved": True}
    assert bind_report_source(state, source_binding()) is False
    assert REPORT_OUTLINE_STATE_KEY in state
    assert bind_report_source(state, source_binding("b" * 64)) is True
    assert REPORT_OUTLINE_STATE_KEY not in state


def handle(binding_id):
    return DatasetHandle(
        dataset_id=f"dataset-{binding_id}",
        source_id=binding_id,
        source_type="starrocks",
        path=f"datasets/{binding_id}.parquet",
        format="parquet",
        schema=None,
        row_count=1,
        size=1,
        sha256="a" * 64,
        sampled=False,
        provenance={"bindingId": binding_id},
    )


def test_混合来源必须保留全部数据集血缘():
    validate_hybrid_lineage([handle("a"), handle("b")], ["a", "b"])
    with pytest.raises(ReportingError):
        validate_hybrid_lineage([handle("a")], ["a", "b"])
    with pytest.raises(ReportingError):
        validate_hybrid_lineage([handle("other")], ["a"])


def _step(step_input):
    return StepOutput(content=step_input.previous_step_content or step_input.input or "ok")


def test_agno_workflow包含来源确认提纲重试和最终发布审核():
    workflow = create_reporting_workflow(
        db=SimpleNamespace(),
        confirm_source=_step,
        profile_source=_step,
        generate_outline=_step,
        generate_analysis_plan=_step,
        generate_data_requirements=_step,
        generate_query_candidates=_step,
        materialize_datasets=_step,
        run_coding_analysis=_step,
        validate_report=_step,
        publish_report=_step,
    )

    assert workflow.id == "enterprise-reporting-workflow-v1"
    assert [step.name for step in workflow.steps] == [
        "确认数据来源",
        "受限数据画像",
        "生成报告提纲",
        "生成分析计划",
        "生成取数需求",
        "生成并审核取数方案",
        "物化不可变数据集",
        "Coding 分析与成稿",
        "PDF 验收",
        "发布审核",
    ]
    source_review = workflow.steps[0].human_review
    outline_review = workflow.steps[2].human_review
    query_review = workflow.steps[5].human_review
    publication_review = workflow.steps[-1].human_review
    assert source_review.requires_confirmation is True
    assert outline_review.requires_output_review is True
    assert outline_review.on_reject is OnReject.retry
    assert outline_review.max_retries == 3
    assert callable(query_review.requires_output_review)
    assert query_review.requires_output_review(
        StepOutput(content={"candidates": [{"requiresApproval": True}]})
    )
    assert not query_review.requires_output_review(
        StepOutput(content={"candidates": [{"requiresApproval": False}]})
    )
    assert publication_review.requires_output_review is True


@pytest.mark.anyio
async def test_runtime接入vanna成功候选且无需逐条审批():
    class VannaProvider:
        calls = 0

        def generate_sql(self, requirement, binding):
            self.calls += 1
            return "SELECT amount FROM hospital.revenue"

    current_binding = source_binding()
    requirement = DataRequirement(
        requirementId="req-1",
        bindingId=current_binding.binding_id,
        metric="收入",
        dimensions=("科室",),
        grain="月",
        period="2025-01 至 2025-12",
        comparisonPeriod="2024 可比期间",
        purpose="收入同比",
    )
    state = {
        REPORT_SOURCE_BINDING_STATE_KEY: current_binding.public_dict(),
        REPORT_DATA_REQUIREMENTS_STATE_KEY: [requirement.model_dump(mode="json", by_alias=True)],
    }
    provider = VannaProvider()
    runtime = object.__new__(ReportWorkflowRuntime)
    runtime.vanna_sql_provider = provider

    output = await runtime.generate_query_candidates(
        StepInput(),
        RunContext(run_id="run", session_id="thread", user_id="user", session_state=state),
    )

    candidate = state[REPORT_QUERY_CANDIDATES_STATE_KEY][0]
    assert output.content["generators"] == ["vanna"]
    assert candidate["generator"] == "vanna"
    assert candidate["requiresApproval"] is False
    assert provider.calls == 1


class FakeRequirement:
    def __init__(self, step_name="生成报告提纲", content=None):
        self.step_name = step_name
        self.step_index = 2
        self.requires_confirmation = step_name == "确认数据来源"
        self.requires_output_review = not self.requires_confirmation
        self.confirmed = None
        self.on_reject = OnReject.retry
        self.rejection_feedback = None
        self.step_output = SimpleNamespace(
            content=content or {"title": "经营分析", "sections": ["摘要"]}
        )
        self.step_input = SimpleNamespace(
            input={
                "source": {
                    "confirmationId": "confirm-secret",
                    "endpoint": "db.example:9030",
                    "database": "hospital",
                    "ddlTables": ["revenue"],
                }
            }
        )

    @property
    def is_resolved(self):
        return self.confirmed is not None

    def confirm(self):
        self.confirmed = True

    def reject(self, *, feedback=None):
        self.confirmed = False
        self.rejection_feedback = feedback


class FakeAsyncWorkflow:
    id = "enterprise-reporting-workflow-v1"

    def __init__(self, shared):
        self.shared = shared

    async def arun(self, *args, **kwargs):
        self.shared["calls"].append(("start", args, kwargs))
        output = SimpleNamespace(
            run_id=kwargs["run_id"],
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            status=RunStatus.paused,
            content=None,
            step_requirements=[FakeRequirement("确认数据来源")],
            active_step_requirements=[],
        )
        output.active_step_requirements = output.step_requirements
        self.shared["output"] = output
        return output

    async def aget_run(self, run_id, session_id=None):
        self.shared["calls"].append(("get", run_id, session_id))
        return self.shared.get("output")

    async def acontinue_run(self, run_response=None, **kwargs):
        self.shared["calls"].append(("continue", run_response, kwargs))
        if run_response.step_requirements[-1].confirmed is False:
            run_response.status = RunStatus.cancelled
            return run_response
        run_response.step_requirements.append(FakeRequirement())
        run_response.active_step_requirements = run_response.step_requirements[-1:]
        return run_response

    async def acancel_run(self, run_id):
        self.shared["calls"].append(("cancel", run_id))
        return True


def workflow_context():
    from agno.run import RunContext

    return RunContext(
        run_id="outer-run",
        session_id="thread",
        user_id="user",
        session_state={},
        dependencies={"AgentOS 报表工作流": {"externalRunId": "external-run"}},
    )


@pytest.mark.anyio
async def test_controller按稳定id启动并只持久化脱敏审核快照():
    shared = {"calls": []}
    controller = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))
    context = workflow_context()

    result = await controller.start("分析医院经营", None, context)

    control = context.session_state[REPORT_WORKFLOW_CONTROL_STATE_KEY]
    assert result["status"] == "paused"
    assert control["workflowId"] == "enterprise-reporting-workflow-v1"
    assert control["externalRunId"] == "external-run"
    assert control["review"]["stage"] == "source"
    assert control["review"]["preview"] == {
        "endpoint": "db.example:9030",
        "database": "hospital",
        "ddlTables": ["revenue"],
    }
    serialized = str(control).lower()
    assert "confirmationid" not in serialized
    assert "password" not in serialized
    assert "sql" not in serialized
    assert "connectionref" not in serialized

    second = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))
    resumed = await second.approve(context)

    assert resumed["status"] == "paused"
    assert resumed["review"]["stage"] == "outline"
    assert [call[0] for call in shared["calls"]] == ["start", "get", "continue"]


@pytest.mark.anyio
async def test_controller拒绝来源会把暂停workflow推进到取消终态():
    shared = {"calls": []}
    controller = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))
    context = workflow_context()
    await controller.start("分析医院经营", None, context)

    result = await controller.reject("不使用这个来源", context)

    assert result["status"] == "cancelled"
    assert context.session_state[REPORT_WORKFLOW_CONTROL_STATE_KEY]["status"] == "cancelled"


@pytest.mark.anyio
async def test_controller当前进程的活跃workflow可由外部run取消():
    shared = {"calls": []}
    controller = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))
    await controller.start("分析医院经营", None, workflow_context())

    result = await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
    )
    repeated = await controller.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
    )

    assert result == {"ok": True, "status": "cancelled"}
    assert repeated is None
    assert [call[0] for call in shared["calls"]] == ["start", "get", "continue"]


@pytest.mark.anyio
async def test_controller仅在显式探测时恢复并取消持久化workflow():
    shared = {"calls": []}
    first = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))
    await first.start("分析医院经营", None, workflow_context())
    restarted = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))

    fast_path = await restarted.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
    )
    restored = await restarted.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="user",
        probe_storage=True,
    )

    assert fast_path is None
    assert restored == {"ok": True, "status": "cancelled"}
    assert [call[0] for call in shared["calls"]] == ["start", "get", "continue"]


@pytest.mark.anyio
async def test_controller外部取消不会处理其他用户的持久化workflow():
    shared = {"calls": []}
    owner = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))
    await owner.start("分析医院经营", None, workflow_context())
    foreign = ReportWorkflowController(lambda: FakeAsyncWorkflow(shared))

    result = await foreign.cancel_external(
        external_run_id="external-run",
        thread_id="thread",
        user_id="other-user",
        probe_storage=True,
    )

    assert result is None
    assert getattr(shared["output"], "status") is RunStatus.paused
    assert [call[0] for call in shared["calls"]] == ["start", "get"]


def test_report_workflow_toolkit只有批准使用agno原生确认():
    toolkit = ReportWorkflowToolkit(ReportWorkflowController(lambda: None))
    functions = {**toolkit.functions, **toolkit.async_functions}

    assert set(functions) == {
        "report_workflow_start",
        "report_workflow_approve",
        "report_workflow_reject",
        "report_workflow_cancel",
    }
    assert functions["report_workflow_approve"].requires_confirmation is True
    assert functions["report_workflow_start"].requires_confirmation is False
    assert functions["report_workflow_reject"].requires_confirmation is False
    assert functions["report_workflow_cancel"].requires_confirmation is False


def test_cli_adapter支持批准和带反馈拒绝():
    actions = iter(["r", "需要增加科室异常章节"])
    requirement = SimpleNamespace(
        step_output=SimpleNamespace(content="提纲"),
        confirm=lambda: None,
        reject=lambda **kwargs: setattr(requirement, "feedback", kwargs.get("feedback")),
    )
    output = SimpleNamespace(steps_requiring_output_review=[requirement])

    CliReviewAdapter(
        read=lambda _prompt: next(actions), write=lambda _value: None
    ).resolve_output_reviews(output)

    assert requirement.feedback == "需要增加科室异常章节"


def test_缺少2024可比期和月份不连续时标记_not_applicable():
    yoy, mom = comparison_decisions([date(2025, 1, 1), date(2025, 3, 1)], report_year=2025)
    assert yoy.decision == "not_applicable"
    assert mom.decision == "not_applicable"


def test_2024可比期完整且月份连续时执行同比环比():
    yoy, mom = comparison_decisions(
        [
            date(2024, 1, 1),
            date(2024, 2, 1),
            date(2025, 1, 1),
            date(2025, 2, 1),
        ],
        report_year=2025,
    )
    assert yoy.decision == "execute"
    assert mom.decision == "execute"


def test_累计指标误求和和不同粒度明细连接被拒绝():
    with pytest.raises(ReportingError) as cumulative:
        validate_metric_aggregation(cumulative=True, aggregation="sum")
    with pytest.raises(ReportingError) as grain:
        validate_fact_combination(
            {"revenue": ("month", "department"), "workload": ("day", "department")}
        )
    assert cumulative.value.code == "cumulative_sum_denied"
    assert grain.value.code == "fact_grain_mismatch"


def test_空数据和指标无法对账时失败关闭():
    with pytest.raises(ReportingError) as empty:
        reconcile_metric([], Decimal("0"), tolerance=Decimal("0.01"))
    with pytest.raises(ReportingError) as mismatch:
        reconcile_metric([Decimal("10"), Decimal("20")], Decimal("35"), tolerance=Decimal("0.01"))
    assert empty.value.code == "metric_empty"
    assert mismatch.value.code == "metric_reconciliation_failed"
