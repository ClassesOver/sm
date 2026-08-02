from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from agno.run import RunContext

from agentos_dev.coding.reporting.controller import (
    REPORT_WORKFLOW_CONTROL_STATE_KEY,
    REPORT_WORKFLOW_SCOPE_DEPENDENCY,
    ReportWorkflowController,
)
from agentos_dev.coding.reporting.models import (
    ReportingError,
    ReportReviewSnapshot,
    ReportWorkflowControl,
)


class _PublicationRequirement:
    def __init__(self) -> None:
        self.action: str | None = None
        self.feedback: str | None = None
        self.step_name = "发布审核"
        self.is_resolved = False
        self.step_output = SimpleNamespace(
            content={
                "status": "validated",
                "jobId": "job-1",
                "revision": 1,
                "validation": {"ok": True},
            }
        )

    def confirm(self) -> None:
        self.action = "approve"
        self.is_resolved = True

    def reject(self, *, feedback: str | None = None) -> None:
        self.action = "reject"
        self.feedback = feedback
        self.is_resolved = True


class _PublicationWorkflow:
    id = "enterprise-reporting-workflow-v1"

    def __init__(
        self, *, reject_status: str = "PAUSED", completed_content: dict[str, Any] | None = None
    ) -> None:
        self.requirement = _PublicationRequirement()
        self.continue_kwargs: dict[str, Any] | None = None
        self.output = SimpleNamespace(
            status="PAUSED",
            user_id="user-1",
            content=self.requirement.step_output.content,
            active_step_requirements=[self.requirement],
            step_requirements=[self.requirement],
        )
        self.reject_status = reject_status
        self.completed_content = completed_content or {
            "reportId": "report-1",
            "revision": 1,
            "pdf": {
                "downloadUrl": "/reports/v1/download/opaque",
                "expiresAt": "2026-07-29T00:00:00+00:00",
                "size": 123,
                "sha256": "a" * 64,
            },
        }

    async def aget_run(self, run_id: str, session_id: str | None = None) -> Any:
        assert run_id == "workflow-run-1"
        assert session_id == "workflow-session-1"
        return self.output

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any:
        self.continue_kwargs = kwargs
        assert kwargs["run_response"] is self.output
        if self.requirement.action == "approve":
            self.output.status = "COMPLETED"
            self.output.content = self.completed_content
            self.output.active_step_requirements = []
            return self.output
        self.output.status = self.reject_status
        self.requirement = _PublicationRequirement()
        self.requirement.step_output.content["revision"] = 2
        self.output.content = self.requirement.step_output.content
        self.output.active_step_requirements = [self.requirement]
        self.output.step_requirements = [self.requirement]
        return self.output

    async def arun(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("本测试不启动新 Workflow")

    async def acancel_run(self, run_id: str) -> bool:
        raise AssertionError(f"本测试不取消 Workflow: {run_id}")


class _BlockingWorkflow:
    id = "enterprise-reporting-workflow-v1"

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.arun_calls = 0
        self.cancelled_run_ids: list[str] = []
        self.output: Any = None

    async def arun(self, *_args: Any, **_kwargs: Any) -> Any:
        self.arun_calls += 1
        if self.arun_calls > 1:
            return SimpleNamespace(
                status="COMPLETED",
                user_id="user-1",
                content=None,
                active_step_requirements=[],
                step_requirements=[],
            )
        self.started.set()
        await self.release.wait()
        self.output = SimpleNamespace(
            status="CANCELLED" if self.cancelled_run_ids else "COMPLETED",
            user_id="user-1",
            content=None,
            active_step_requirements=[],
            step_requirements=[],
        )
        return self.output

    async def aget_run(self, _run_id: str, session_id: str | None = None) -> Any:
        _ = session_id
        return self.output

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"本测试不恢复 Workflow: {args!r} {kwargs!r}")

    async def acancel_run(self, run_id: str) -> bool:
        self.cancelled_run_ids.append(run_id)
        return True


def _start_context() -> RunContext:
    return RunContext(
        run_id="external-run-1",
        session_id="thread-1",
        user_id="user-1",
        session_state={},
    )


def _workflow_input() -> dict[str, str]:
    return {"version": "1", "prompt": "分析 2025 年经营情况"}


def test_controller指标语义审核仅暴露待确认决策():
    decisions = [
        {
            "fieldRef": "operations.reporting.income.amount",
            "classification": "measure",
            "reason": "金额字段表示收入发生额。",
            "measureSemantic": {
                "fieldRef": "operations.reporting.income.amount",
                "aggregation": "sum",
            },
        }
    ]
    requirement = SimpleNamespace(
        step_name="生成指标语义候选",
        is_resolved=False,
        step_output=SimpleNamespace(content={"decisions": decisions, "internalState": "不得暴露"}),
        output_review_message="请审核指标语义。",
    )
    output = SimpleNamespace(
        active_step_requirements=[requirement], step_requirements=[requirement]
    )

    review = ReportWorkflowController(lambda: _PublicationWorkflow())._review(output)

    assert review.stage == "semantic"
    assert review.title == "审核指标语义"
    assert review.message == "请审核指标语义。"
    assert review.preview == {"decisions": decisions}


def _context(
    *,
    run_id: str = "external-run-1",
    dependencies: bool = True,
    review_stage: str = "publication",
) -> RunContext:
    control = ReportWorkflowControl(
        workflowId="enterprise-reporting-workflow-v1",
        workflowRunId="workflow-run-1",
        workflowSessionId="workflow-session-1",
        externalRunId="external-run-1",
        threadId="thread-1",
        userId="user-1",
        status="paused",
        review=ReportReviewSnapshot(
            stage=review_stage,
            title="审核最终报告",
            message="请审核",
            preview={"revision": 1},
        ),
    )
    return RunContext(
        run_id=run_id,
        session_id="thread-1",
        user_id="user-1",
        session_state={REPORT_WORKFLOW_CONTROL_STATE_KEY: control.public_dict()},
        dependencies=(
            {
                REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                    "externalRunId": "external-run-1",
                    "threadId": "thread-1",
                    "userId": "user-1",
                }
            }
            if dependencies
            else None
        ),
    )


@pytest.mark.anyio
async def test_controller返回workflow正式发布结果且隐藏内部路径():
    workflow = _PublicationWorkflow()
    controller = ReportWorkflowController(lambda: workflow)

    result = await controller.approve(_context())

    assert workflow.continue_kwargs is not None
    assert workflow.continue_kwargs["dependencies"] == {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-run-1",
            "threadId": "thread-1",
            "userId": "user-1",
        }
    }
    assert result == {"ok": True, "status": "completed", "report": workflow.completed_content}
    assert "pdfPath" not in repr(result)
    assert "markdownPath" not in repr(result)


@pytest.mark.anyio
async def test_publication拒绝并进入新revision时不签发旧grant():
    workflow = _PublicationWorkflow()
    controller = ReportWorkflowController(lambda: workflow)

    result = await controller.reject("补充异常归因", _context())

    assert result["status"] == "paused"
    assert result["review"]["stage"] == "publication"
    assert result["review"]["preview"]["revision"] == 2


@pytest.mark.anyio
async def test_cli_publication结果只返回本地文件身份():
    published = {"path": "reports/result.pdf", "size": 123, "sha256": "b" * 64}
    workflow = _PublicationWorkflow(completed_content=published)

    result = await ReportWorkflowController(lambda: workflow).approve(_context())

    assert result == {
        "ok": True,
        "status": "completed",
        "report": {"path": "reports/result.pdf", "size": 123, "sha256": "b" * 64},
    }
    assert "url" not in repr(result).lower()


@pytest.mark.anyio
async def test_hitl跨agent回合沿用已持久化workflow作用域():
    workflow = _PublicationWorkflow()
    controller = ReportWorkflowController(lambda: workflow)

    result = await controller.approve(_context(run_id="next-agent-run", dependencies=False))

    assert result["status"] == "completed"


@pytest.mark.anyio
async def test_start跨agent回合返回已暂停workflow而不重复启动():
    workflow = _PublicationWorkflow()
    controller = ReportWorkflowController(lambda: workflow)

    result = await controller.start(
        _workflow_input(),
        _context(run_id="next-agent-run", dependencies=False),
    )

    assert result["status"] == "paused"
    assert result["review"]["stage"] == "publication"
    assert result["review"]["preview"]["revision"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stage", "code"),
    [
        ("request", "report_request_clarification_required"),
        ("agent", "report_agent_selection_required"),
    ],
)
async def test_request和agent审核阶段拒绝通用批准(stage, code):
    workflow = _PublicationWorkflow()
    controller = ReportWorkflowController(lambda: workflow)

    with pytest.raises(ReportingError) as captured:
        await controller.approve(_context(review_stage=stage))

    assert captured.value.code == code
    assert workflow.requirement.action is None
    assert workflow.continue_kwargs is None


@pytest.mark.anyio
async def test_controller拒绝相同scope并发启动workflow():
    workflow = _BlockingWorkflow()
    controller = ReportWorkflowController(lambda: workflow)
    first = asyncio.create_task(controller.start(_workflow_input(), _start_context()))
    await workflow.started.wait()
    try:
        with pytest.raises(ReportingError) as captured:
            await controller.start(_workflow_input(), _start_context())

        assert captured.value.code == "report_workflow_active"
        assert workflow.arun_calls == 1
    finally:
        workflow.release.set()
        await first


@pytest.mark.anyio
async def test_controller在活跃run尚未持久化时接受外部取消():
    workflow = _BlockingWorkflow()
    cleanup_calls: list[tuple[dict[str, str], str, str]] = []

    async def cleanup(scope: dict[str, str], session_id: str, run_id: str) -> None:
        cleanup_calls.append((scope, session_id, run_id))

    controller = ReportWorkflowController(lambda: workflow, cancel_cleanup=cleanup)
    running = asyncio.create_task(controller.start(_workflow_input(), _start_context()))
    await workflow.started.wait()

    try:
        result = await controller.cancel_external(
            external_run_id="external-run-1",
            thread_id="thread-1",
            user_id="user-1",
        )

        assert result == {"ok": True, "status": "cancelling"}
        assert len(workflow.cancelled_run_ids) == 1
        assert len(cleanup_calls) == 1
    finally:
        workflow.release.set()
        await running


@pytest.mark.anyio
async def test_controller接受仍处于running状态的协作式取消():
    workflow = _BlockingWorkflow()
    workflow.output = SimpleNamespace(
        status="RUNNING",
        user_id="user-1",
        content=None,
        active_step_requirements=[],
        step_requirements=[],
    )
    cleanup_calls: list[tuple[dict[str, str], str, str]] = []

    async def cleanup(scope: dict[str, str], session_id: str, run_id: str) -> None:
        cleanup_calls.append((scope, session_id, run_id))

    controller = ReportWorkflowController(lambda: workflow, cancel_cleanup=cleanup)

    result = await controller.cancel_external(
        external_run_id="external-run-1",
        thread_id="thread-1",
        user_id="user-1",
        probe_storage=True,
    )

    assert result == {"ok": True, "status": "cancelling"}
    assert len(workflow.cancelled_run_ids) == 1
    assert len(cleanup_calls) == 1
