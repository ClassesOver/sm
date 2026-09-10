from __future__ import annotations

import asyncio
from typing import Any

import pytest
from agno.run import RunStatus
from agno.run.workflow import WorkflowCancelledEvent, WorkflowCompletedEvent
from agno.workflow import Step
from agno.workflow.types import HumanReview, OnError, StepInput, StepOutput

from smart_reporting.reporting.models import ReportingError
from smart_reporting.reporting.workflow.managed import ManagedReportingWorkflow


class Lifecycle:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def prepare_run(
        self,
        *,
        run_id: str,
        session_id: str,
        user_id: str | None,
        dependencies: dict[str, Any] | None,
    ) -> dict[str, Any]:
        self.events.append(("prepare", run_id))
        return {"report_workflow_scope": {"externalRunId": run_id}}

    async def start_run(self, run_id: str, _session_state: dict[str, Any]) -> None:
        self.events.append(("start", run_id))

    async def assert_resumable(self, run_id: str) -> None:
        self.events.append(("resume", run_id))

    async def settle_run(self, run_id: str, status: str) -> None:
        self.events.append(("settle", (run_id, status)))


class RejectingLifecycle(Lifecycle):
    async def start_run(self, run_id: str, _session_state: dict[str, Any]) -> None:
        raise ReportingError("report_workflow_thread_busy", run_id)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_managed_workflow_starts_before_execution_and_settles_completed() -> None:
    lifecycle = Lifecycle()

    async def execute(_step_input: StepInput) -> StepOutput:
        lifecycle.events.append(("execute", None))
        return StepOutput(content="done")

    workflow = ManagedReportingWorkflow(
        id="reporting",
        steps=[Step(name="execute", executor=execute)],
        lifecycle=lifecycle,
        overwrite_db_session_state=True,
    )

    output = await workflow.arun(
        "run",
        run_id="run-a",
        session_id="thread-a",
        user_id="user-a",
        stream=False,
    )

    assert output.status is RunStatus.completed
    assert lifecycle.events == [
        ("prepare", "run-a"),
        ("start", "run-a"),
        ("execute", None),
        ("settle", ("run-a", "completed")),
    ]


@pytest.mark.anyio
async def test_managed_workflow_rejects_before_executor_runs() -> None:
    executed = False

    async def execute(_step_input: StepInput) -> StepOutput:
        nonlocal executed
        executed = True
        return StepOutput(content="done")

    workflow = ManagedReportingWorkflow(
        id="reporting",
        steps=[Step(name="execute", executor=execute)],
        lifecycle=RejectingLifecycle(),
    )

    with pytest.raises(ReportingError) as raised:
        await workflow.arun(
            "run",
            run_id="run-b",
            session_id="thread-a",
            user_id="user-a",
            stream=False,
        )

    assert raised.value.code == "report_workflow_thread_busy"
    assert executed is False


@pytest.mark.anyio
async def test_managed_workflow_maps_ordinary_exception_to_failed() -> None:
    lifecycle = Lifecycle()

    async def fail(_step_input: StepInput) -> StepOutput:
        raise RuntimeError("broken")

    workflow = ManagedReportingWorkflow(
        id="reporting",
        steps=[
            Step(
                name="fail",
                executor=fail,
                max_retries=0,
                human_review=HumanReview(on_error=OnError.fail),
            )
        ],
        lifecycle=lifecycle,
    )

    with pytest.raises(RuntimeError, match="broken"):
        await workflow.arun(
            "run",
            run_id="run-a",
            session_id="thread-a",
            user_id="user-a",
            stream=False,
        )

    assert lifecycle.events[-1] == ("settle", ("run-a", "failed"))


@pytest.mark.anyio
async def test_managed_workflow_keeps_paused_run_non_terminal() -> None:
    lifecycle = Lifecycle()

    async def execute(_step_input: StepInput) -> StepOutput:
        return StepOutput(content="review")

    workflow = ManagedReportingWorkflow(
        id="reporting",
        steps=[
            Step(
                name="execute",
                executor=execute,
                human_review=HumanReview(requires_output_review=True),
            )
        ],
        lifecycle=lifecycle,
    )

    output = await workflow.arun(
        "run",
        run_id="run-a",
        session_id="thread-a",
        user_id="user-a",
        stream=False,
    )

    assert output.status is RunStatus.paused
    assert lifecycle.events[-1] == ("settle", ("run-a", "paused"))


def test_managed_workflow_deep_copy_preserves_lifecycle() -> None:
    lifecycle = Lifecycle()
    workflow = ManagedReportingWorkflow(id="reporting", steps=[], lifecycle=lifecycle)

    copied = workflow.deep_copy()

    assert isinstance(copied, ManagedReportingWorkflow)
    assert copied is not workflow
    assert copied.lifecycle is lifecycle


def test_managed_workflow_rejects_background_execution() -> None:
    workflow = ManagedReportingWorkflow(id="reporting", steps=[], lifecycle=Lifecycle())

    with pytest.raises(ValueError, match="background=false"):
        workflow.arun(
            "run",
            run_id="run-a",
            session_id="thread-a",
            user_id="user-a",
            background=True,
        )


@pytest.mark.anyio
async def test_cancelled_event_is_not_overwritten_by_completed_stream_marker() -> None:
    lifecycle = Lifecycle()
    workflow = ManagedReportingWorkflow(id="reporting", steps=[], lifecycle=lifecycle)

    async def events():
        yield WorkflowCancelledEvent(run_id="run-a", workflow_id="reporting")
        yield WorkflowCompletedEvent(run_id="run-a", workflow_id="reporting")

    received = [event async for event in workflow._stream(events(), "run-a")]

    assert len(received) == 2
    assert lifecycle.events == [("settle", ("run-a", "cancelled"))]


@pytest.mark.anyio
async def test_official_cancel_settles_only_the_target_run_as_cancelled() -> None:
    lifecycle = Lifecycle()
    started = asyncio.Event()
    release = asyncio.Event()

    async def execute(_step_input: StepInput) -> StepOutput:
        started.set()
        await release.wait()
        return StepOutput(content="done")

    workflow = ManagedReportingWorkflow(
        id="reporting",
        steps=[Step(name="execute", executor=execute)],
        lifecycle=lifecycle,
    )

    async def consume() -> None:
        stream = workflow.arun(
            "run",
            run_id="run-a",
            session_id="thread-a",
            user_id="user-a",
            stream=True,
            stream_events=True,
        )
        async for _event in stream:
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    assert await workflow.acancel_run("run-a") is True
    release.set()
    await task

    assert lifecycle.events[-1] == ("settle", ("run-a", "cancelled"))
