from __future__ import annotations

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

    def __init__(self, *, reject_status: str = "PAUSED") -> None:
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

    async def aget_run(self, run_id: str, session_id: str | None = None) -> Any:
        assert run_id == "workflow-run-1"
        assert session_id == "workflow-session-1"
        return self.output

    async def acontinue_run(self, *args: Any, **kwargs: Any) -> Any:
        self.continue_kwargs = kwargs
        assert kwargs["run_response"] is self.output
        if self.requirement.action == "approve":
            self.output.status = "COMPLETED"
            self.output.content = {
                "reportId": "report-1",
                "revision": 1,
                "pdfPath": "reports/internal.pdf",
                "markdownPath": "reports/internal.md",
            }
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


def _context() -> RunContext:
    control = ReportWorkflowControl(
        workflowId="enterprise-reporting-workflow-v1",
        workflowRunId="workflow-run-1",
        workflowSessionId="workflow-session-1",
        externalRunId="external-run-1",
        threadId="thread-1",
        userId="user-1",
        status="paused",
        review=ReportReviewSnapshot(
            stage="publication",
            title="审核最终报告",
            message="请审核",
            preview={"revision": 1},
        ),
    )
    return RunContext(
        run_id="external-run-1",
        session_id="thread-1",
        user_id="user-1",
        session_state={REPORT_WORKFLOW_CONTROL_STATE_KEY: control.public_dict()},
        dependencies={
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
                "externalRunId": "external-run-1",
                "threadId": "thread-1",
                "userId": "user-1",
            }
        },
    )


@pytest.mark.anyio
async def test_publication只在批准且workflow完成后签发且隐藏内部路径():
    workflow = _PublicationWorkflow()
    issued: list[dict[str, Any]] = []

    async def issue(
        scope: dict[str, str],
        workflow_session_id: str,
        workflow_run_id: str,
        output: Any,
    ) -> dict[str, Any]:
        assert scope["thread_id"] == "thread-1"
        assert workflow_session_id == "workflow-session-1"
        assert workflow_run_id == "workflow-run-1"
        assert output.status == "COMPLETED"
        result = {
            "reportId": "report-1",
            "revision": 1,
            "pdf": {
                "downloadUrl": "/reports/v1/download/opaque",
                "expiresAt": "2026-07-29T00:00:00+00:00",
                "size": 123,
                "sha256": "a" * 64,
            },
        }
        issued.append(result)
        return result

    controller = ReportWorkflowController(lambda: workflow, publication_issuer=issue)
    assert issued == []

    result = await controller.approve(_context())

    assert len(issued) == 1
    assert workflow.continue_kwargs is not None
    assert workflow.continue_kwargs["dependencies"] == {
        REPORT_WORKFLOW_SCOPE_DEPENDENCY: {
            "externalRunId": "external-run-1",
            "threadId": "thread-1",
            "userId": "user-1",
        }
    }
    assert result == {"ok": True, "status": "completed", "report": issued[0]}
    assert "pdfPath" not in repr(result)
    assert "markdownPath" not in repr(result)


@pytest.mark.anyio
async def test_publication拒绝并进入新revision时不签发旧grant():
    workflow = _PublicationWorkflow()
    issued = False

    async def issue(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        nonlocal issued
        issued = True
        return {}

    controller = ReportWorkflowController(lambda: workflow, publication_issuer=issue)

    result = await controller.reject("补充异常归因", _context())

    assert issued is False
    assert result["status"] == "paused"
    assert result["review"]["stage"] == "publication"
    assert result["review"]["preview"]["revision"] == 2


@pytest.mark.anyio
async def test_cli_publication结果只返回本地文件身份():
    workflow = _PublicationWorkflow()

    async def issue(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"path": "reports/result.pdf", "size": 123, "sha256": "b" * 64}

    result = await ReportWorkflowController(lambda: workflow, publication_issuer=issue).approve(
        _context()
    )

    assert result == {
        "ok": True,
        "status": "completed",
        "report": {"path": "reports/result.pdf", "size": 123, "sha256": "b" * 64},
    }
    assert "url" not in repr(result).lower()


@pytest.mark.anyio
async def test_publication未配置issuer时失败关闭():
    workflow = _PublicationWorkflow()
    controller = ReportWorkflowController(lambda: workflow)

    with pytest.raises(ReportingError) as captured:
        await controller.approve(_context())

    assert captured.value.code == "report_publication_unavailable"
