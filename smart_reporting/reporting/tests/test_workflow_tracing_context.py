"""使用真实 OpenInference 包装器覆盖前台工作流的追踪与取消边界。"""

import asyncio
import logging
from types import SimpleNamespace

import pytest
from agno.exceptions import RunCancelledException
from agno.run import RunContext
from agno.run.base import RunStatus
from agno.run.cancel import cancel_run, cleanup_run, register_run
from openinference.instrumentation.agno._workflow_wrapper import _WorkflowWrapper
from opentelemetry import context as context_api
from opentelemetry.trace import NoOpTracer

from smart_reporting.reporting.contract import ReportingWorkflowInput
from smart_reporting.reporting.tests.test_reporting_workflow_controller import (
    _context,
    _ThreadOwnership,
)
from smart_reporting.reporting.workflow.controller import ReportWorkflowController


class _TracedWorkflow:
    id = "enterprise-reporting-workflow-v1"
    name = "context-regression"

    def __init__(self, phase="start", *, block=False):
        self.phase = phase
        self.block = block
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()
        self.wrapper = _WorkflowWrapper(NoOpTracer())
        self.requirement = SimpleNamespace(
            step_id="validate-report", step_name="报告末端恢复", step_output=None,
            is_resolved=False, retry=lambda: None,
        )

    async def _complete(self, *_args, **_kwargs):
        self.started.set()
        try:
            if self.block:
                await asyncio.Future()
            return SimpleNamespace(status=RunStatus.completed)
        finally:
            await asyncio.sleep(0)
            self.cleaned.set()

    async def aget_run(self, *_args, **_kwargs):
        if self.phase == "continue":
            return SimpleNamespace(
                status=RunStatus.paused, active_step_requirements=[], step_requirements=[],
                error_requirements=[self.requirement],
            )
        return None

    def arun(self, *args, **kwargs):
        if self.phase == "continue":
            return self.aget_run()
        return self.wrapper.arun(self._complete, self, args, kwargs)

    def acontinue_run(self, *args, **kwargs):
        return self.wrapper.arun(self._complete, self, args, kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["start", "continue"])
async def test_instrumented_workflow_restores_caller_context_without_detach_errors(caplog, phase):
    workflow = _TracedWorkflow(phase)
    ownership = _ThreadOwnership()
    controller = ReportWorkflowController(lambda: workflow, thread_ownership=ownership)
    context = _context()
    before = context_api.get_current()
    try:
        with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
            result = await controller.start(ReportingWorkflowInput(prompt="生成报表"), context)
            if phase == "continue":
                assert result["status"] == "paused"
                result = await controller.approve(context)
        assert result["status"] == "completed"
        assert ownership.owners == {}
        assert context_api.get_current() == before
        assert not [record for record in caplog.records if record.name == "opentelemetry.context"]
    finally:
        context_api.attach(before)


@pytest.mark.anyio
async def test_chat_cancellation_drains_instrumented_workflow_before_releasing_owner(caplog):
    workflow = _TracedWorkflow(block=True)
    ownership = _ThreadOwnership()
    cleanup_observations = []

    async def cleanup(*_args):
        cleanup_observations.append((workflow.cleaned.is_set(), bool(ownership.owners)))

    controller = ReportWorkflowController(
        lambda: workflow, thread_ownership=ownership, terminal_cleanup=cleanup,
    )
    context = RunContext(run_id="tracing-cancel-run", session_id="thread", user_id="user", session_state={})
    register_run(context.run_id)
    task = asyncio.create_task(controller.start(ReportingWorkflowInput(prompt="生成报表"), context))
    try:
        with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
            await asyncio.wait_for(workflow.started.wait(), timeout=1)
            assert cancel_run(context.run_id)
            with pytest.raises(RunCancelledException):
                await asyncio.wait_for(task, timeout=2)
        assert cleanup_observations == [(True, True)]
        assert ownership.owners == {}
        assert not [record for record in caplog.records if record.name == "opentelemetry.context"]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        cleanup_run(context.run_id)
