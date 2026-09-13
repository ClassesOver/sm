"""Exercise progress across the actual Agno function-step boundary."""
import asyncio
from contextvars import Context
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agno.run import RunStatus

from agno.workflow import Step, Workflow
from agno.workflow.types import StepOutput
from sqlalchemy import create_engine

from smart_reporting.integrations.dingyi_process import DingyiProcessAdapter
from smart_reporting.reporting.workflow.controller import REPORT_PROCESS_LIFECYCLE_DEPENDENCY
from smart_reporting.reporting.workflow.orchestration import _timed_step_executor
from smart_reporting.reporting.workflow.scope import REPORT_WORKFLOW_SCOPE_DEPENDENCY
from smart_reporting.reporting.workflow.managed import (
    ManagedReportingWorkflow,
    _CONTINUATION_DEPENDENCIES,
)
from smart_reporting.reporting.tests.test_managed_reporting_workflow import Lifecycle


@pytest.mark.parametrize("stream", [False, True])
def test_persisted_workflow_continuation_publishes_step_progress(tmp_path, stream):
    from agno.db.sqlite import SqliteDb
    from agno.workflow.types import HumanReview

    async def exercise():
        adapter = DingyiProcessAdapter(create_engine(f"sqlite:///{tmp_path / 'process.db'}"))
        await adapter.start_operation(operation_id="outer", session_id="chat", run_id="outer", title="报告", execution="foreground")
        dependencies = {
            REPORT_PROCESS_LIFECYCLE_DEPENDENCY: adapter,
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {"externalRunId": "outer", "threadId": "chat"},
            "current_request": "resumed",
        }
        executions = []

        async def review(step_input, run_context):
            executions.append("review")
            return StepOutput(content="review")

        async def execute(step_input, run_context):
            executions.append("profile")
            snapshot = await adapter._snapshot("outer")
            assert snapshot["activities"][-1]["status"] == "running"
            assert run_context.dependencies["current_request"] == "resumed"
            assert run_context.dependencies["default_value"] == "retained"
            return StepOutput(content="done")

        def make_workflow():
            return ManagedReportingWorkflow(
                id="progress-resume", lifecycle=Lifecycle(),
                db=SqliteDb(db_file=str(tmp_path / "workflow.db")),
                dependencies={"default_value": "retained", "current_request": "default"},
                steps=[
                    Step(name="normalize-report-request", executor=_timed_step_executor(review, step_id="normalize-report-request"), human_review=HumanReview(requires_output_review=True)),
                    Step(name="prepare-data-profile", executor=_timed_step_executor(execute, step_id="prepare-data-profile")),
                ],
            )

        initial = make_workflow()
        paused = await initial.arun("test", run_id="native", session_id="chat", dependencies=dependencies, stream=False)
        assert paused.status is RunStatus.paused
        # Reload the persisted run through a fresh workflow, as after a restart.
        resumed = make_workflow()
        saved = await resumed.aget_run(run_id="native", session_id="chat")
        assert saved.status == RunStatus.paused
        for requirement in saved.active_step_requirements:
            requirement.confirm()
        caller_dependencies = {"caller": "must survive continuation"}
        token = _CONTINUATION_DEPENDENCIES.set(caller_dependencies)
        output = await resumed.acontinue_run(run_response=saved, dependencies=dependencies, stream=stream, stream_events=stream)
        assert _CONTINUATION_DEPENDENCIES.get() is caller_dependencies
        _CONTINUATION_DEPENDENCIES.reset(token)
        if stream:
            async def consume():
                return [event async for event in output]

            # A response stream may be consumed by a different request task.
            # Dependencies must belong to the stream, not the caller's Context.
            events = await asyncio.create_task(consume(), context=Context())
            assert any(event.event == "WorkflowCompleted" for event in events)
        else:
            assert output.status is RunStatus.completed
        snapshot = await adapter._snapshot("outer")
        assert executions == ["review", "profile"]
        assert len(snapshot["activities"]) == 2
        assert all(a["status"] == "completed" and a["startedAt"] and a["endedAt"] for a in snapshot["activities"])
        assert all(a["source"]["runId"] == "native" for a in snapshot["activities"])
        assert snapshot["operation"]["runId"] == "outer"
        assert resumed.dependencies == {"default_value": "retained", "current_request": "default"}

    asyncio.run(exercise())


def test_workflow_steps_publish_progress_with_controller_dependencies(tmp_path):
    async def exercise():
        adapter = DingyiProcessAdapter(create_engine(f"sqlite:///{tmp_path / 'process.db'}"))
        await adapter.start_operation(operation_id='outer', session_id='chat', run_id='outer', title='报告', execution='foreground')

        async def execute(step_input, run_context):
            snapshot = await adapter._snapshot('outer')
            assert snapshot['activities'][-1]['status'] == 'running'
            return StepOutput(content='ok')

        workflow = Workflow(name='progress-regression', steps=[
            Step(name=name, executor=_timed_step_executor(execute, step_id=name))
            for name in ('confirm-source', 'prepare-data-profile')
        ])
        await workflow.arun('test', run_id='native-workflow', session_id='native-session', dependencies={
            REPORT_PROCESS_LIFECYCLE_DEPENDENCY: adapter,
            REPORT_WORKFLOW_SCOPE_DEPENDENCY: {'externalRunId': 'outer', 'threadId': 'chat'},
        }, stream=False)
        await adapter.update_operation(operation_id='outer', session_id='chat', status='paused')
        snapshot = await adapter._snapshot('outer')
        assert snapshot['operation']['runId'] == 'outer'
        assert snapshot['operation']['status'] == 'waiting'
        assert len(snapshot['activities']) == 2
        assert all(a['status'] == 'completed' and a['startedAt'] and a['endedAt'] for a in snapshot['activities'])
        assert all(a['source']['runId'] == 'native-workflow' for a in snapshot['activities'])

    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["completed", "cancelled", "failed"])
def test_controller_resume_and_cancel_update_persisted_process(tmp_path, outcome):
    from smart_reporting.reporting.contract import ReportingWorkflowInput
    from smart_reporting.reporting.workflow.controller import ReportWorkflowController
    from smart_reporting.reporting.tests.test_reporting_workflow_controller import (
        _context, _ThreadOwnership,
    )

    async def exercise():
        adapter = DingyiProcessAdapter(create_engine(f"sqlite:///{tmp_path / 'resume.db'}"))

        class Requirement:
            step_name = "审核报告提纲"
            confirmation_message = "确认提纲"
            step_output = SimpleNamespace(content={"title": "报告", "sections": []})
            is_resolved = False

            def confirm(self):
                self.is_resolved = True

            def reject(self, **kwargs):
                self.is_resolved = True

        requirement = Requirement()
        paused = SimpleNamespace(status=RunStatus.paused, active_step_requirements=[requirement], step_requirements=[requirement])

        class Workflow:
            id = "enterprise-reporting-workflow-v1"
            output = None

            async def arun(self, *args, **kwargs):
                self.output = paused
                return paused

            async def aget_run(self, *args, **kwargs):
                return self.output

            async def acontinue_run(self, *args, **kwargs):
                if outcome != "cancelled":
                    snapshot = await adapter._snapshot("external-run")
                    assert snapshot["operation"]["status"] == "running"
                if outcome == "failed":
                    raise RuntimeError("business failure")
                return SimpleNamespace(status=getattr(RunStatus, outcome))

        workflow = Workflow()
        controller = ReportWorkflowController(
            lambda: workflow, thread_ownership=_ThreadOwnership(),
            terminal_cleanup=AsyncMock(), process_lifecycle=adapter,
        )
        context = _context()
        await controller.start(ReportingWorkflowInput(prompt="生成报表"), context)
        assert (await adapter._snapshot("external-run"))["operation"]["status"] == "waiting"
        if outcome == "failed":
            with pytest.raises(RuntimeError, match="business failure"):
                await controller.approve(context)
        elif outcome == "cancelled":
            await controller.cancel(context)
        else:
            await controller.approve(context)
        operation = (await adapter._snapshot("external-run"))["operation"]
        assert operation["status"] == outcome
        assert operation["endedAt"]
        assert operation["runId"] == "external-run"

    asyncio.run(exercise())
