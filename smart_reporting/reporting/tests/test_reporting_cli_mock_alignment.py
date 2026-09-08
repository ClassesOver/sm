from __future__ import annotations

from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from agno.run import RunContext
from agno.workflow.types import StepOutput

from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
from smart_reporting.reporting.cli import drive_workflow, parse_report_input
from smart_reporting.reporting.delivery.acceptance import build_report_phase_acceptance_contract
from smart_reporting.reporting.tools import build_reporting_tools
from smart_reporting.reporting.tools.context import ReportingOutputPolicy
from smart_reporting.reporting.tools.mock_workspace import MockReportingToolRuntime
from smart_reporting.reporting.workflow.execution import (
    ReportingTaskCoordinator,
)
from smart_reporting.reporting.workflow.repository import ReportingStateRepository
from smart_reporting.reporting.workflow.runtime.reporting_draft_workflow import (
    ReportingDraftWorkflow,
)
from smart_reporting.task_execution import (
    TASK_EXECUTION_DEPENDENCY,
    AttemptSnapshot,
    AttemptState,
    Lease,
    TaskExecutionKernel,
    TaskExecutionRepository,
    TaskExecutionScope,
    TaskSnapshot,
    TaskState,
)


class _Runtime:
    def __init__(self) -> None:
        self.state_repository = self
        self.cleaned = False

    @asynccontextmanager
    async def workflow_execution_lock(self, _run_id: str):
        yield

    async def cleanup_terminal(self, *_args: Any) -> None:
        self.cleaned = True


class _TaskRepository:
    def __init__(self) -> None:
        self.tasks: dict[str, TaskSnapshot] = {}
        self.instructions: dict[str, str] = {}

    async def create_task_with_initial_attempt(
        self,
        scope: TaskExecutionScope,
        instruction: str,
        *,
        acceptance_contract: dict[str, Any],
        max_instruction_bytes: int,
    ) -> None:
        assert len(instruction.encode()) <= max_instruction_bytes
        self.instructions[scope.external_run_id] = instruction
        self.tasks[scope.external_run_id] = TaskSnapshot(
            scope=scope,
            state=TaskState.NEW,
            state_version=1,
            lease_epoch=0,
            continuation_count=0,
            instruction_sequence=1,
            current_internal_run_id=f"internal-{scope.external_run_id}",
            current_attempt_no=0,
            deadline_at=datetime.now(UTC) + timedelta(hours=1),
            acceptance_contract=acceptance_contract,
        )

    async def cleanup_expired(self, *, lease_owner: str) -> None:
        assert lease_owner

    async def claim_lease(self, external_run_id: str, owner: str, *, ttl: timedelta) -> Lease:
        assert external_run_id in self.tasks
        return Lease(owner, 1, datetime.now(UTC) + ttl)

    async def release_lease(self, external_run_id: str, owner: str) -> None:
        assert external_run_id in self.tasks
        assert owner

    async def get_task_snapshot(self, external_run_id: str) -> TaskSnapshot | None:
        return self.tasks.get(external_run_id)

    async def open_initial(
        self, external_run_id: str, lease: Lease, expected_state_version: int
    ) -> tuple[TaskSnapshot, AttemptSnapshot]:
        task = self.tasks[external_run_id]
        assert task.state is TaskState.NEW
        assert task.state_version == expected_state_version
        task = replace(
            task,
            state=TaskState.ACTIVE,
            state_version=expected_state_version + 1,
            lease_epoch=lease.epoch,
        )
        self.tasks[external_run_id] = task
        return task, AttemptSnapshot(
            internal_run_id=task.current_internal_run_id,
            external_run_id=external_run_id,
            attempt_no=0,
            state=AttemptState.RUNNING,
            resume_count=0,
            lease_epoch=lease.epoch,
        )

    async def attempt_instruction(self, external_run_id: str, attempt_no: int) -> str:
        assert attempt_no == 0
        return self.instructions[external_run_id]

    async def finalize_finish(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
        *,
        agno_status: str,
    ) -> TaskSnapshot:
        task = self.tasks[external_run_id]
        assert task.state is TaskState.FINISHING
        assert task.state_version == expected_state_version
        assert task.lease_epoch == lease.epoch
        assert agno_status == "completed"
        task = replace(task, state=TaskState.COMPLETED, state_version=expected_state_version + 1)
        self.tasks[external_run_id] = task
        return task

    async def cancel_and_reject(self, scope: TaskExecutionScope) -> None:
        task = self.tasks[scope.external_run_id]
        self.tasks[scope.external_run_id] = replace(task, state=TaskState.CANCELLED)

    def finish(self, external_run_id: str, task_kind: str) -> None:
        task = self.tasks[external_run_id]
        self.tasks[external_run_id] = replace(
            task,
            state=TaskState.FINISHING,
            state_version=task.state_version + 1,
            finish_receipt={"summary": f"{task_kind} completed", "artifactPaths": []},
        )


class _CliDraftAdapter:
    def __init__(self) -> None:
        self.received_input: dict[str, Any] | None = None
        self.received_scope: dict[str, Any] | None = None
        self.contexts: list[RunContext] = []
        self.tool_projections: list[tuple[str, tuple[str, ...]]] = []
        self.repository = _TaskRepository()
        self.execution_kernel = SimpleNamespace(
            cleanup_old_epoch=AsyncMock(), cleanup_disconnect=AsyncMock()
        )
        self.coordinator = ReportingTaskCoordinator(
            cast(TaskExecutionRepository, self.repository),
            cast(TaskExecutionKernel, self.execution_kernel),
            model_profiles=DEFAULT_MODEL_PROFILES,
        )
        self.production_draft_workflow_called = False

    def _project_tools(self, task_kind: str, run_context: RunContext) -> None:
        toolkit = build_reporting_tools(
            cast(Any, object()),
            self.repository,
            state_repository=cast(ReportingStateRepository, object()),
            run_context=run_context,
        )[0]
        self.tool_projections.append((task_kind, tuple(sorted(toolkit.async_functions))))

    async def _run_task(
        self, task_kind: str, payload: Mapping[str, Any], parent_context: RunContext
    ) -> StepOutput:
        task_id = f"{parent_context.run_id}:{task_kind}"
        scope = TaskExecutionScope(
            external_run_id=task_id,
            owner_user_id=str(parent_context.user_id),
            thread_id=str(parent_context.session_id),
            sandbox_id=f"sandbox-{task_kind}",
            executor_id=f"reporting-{task_kind}",
        )
        phase = "analysis" if task_kind != "section" else "section"
        phase_contract: dict[str, Any] = {
            "reportRunId": str(parent_context.run_id),
            "taskKind": task_kind,
        }
        output_options: dict[str, str] = {}
        if task_kind == "analysis_item":
            phase_contract.update(
                {
                    "analysisIds": ["analysis-1"],
                    "analysisOutputRoot": "reports/analysis-1",
                }
            )
        elif task_kind == "visualization_section":
            phase_contract.update(
                {
                    "visualizationBudgetVersion": 1,
                    "visualizationEvidenceReadUnits": 0,
                    "visualizationReadLimit": 12,
                    "visualizationFactQueryLimit": 4,
                    "visualizationAttemptToolLimit": 48,
                    "visualizationTotalToolLimit": 64,
                    "visualizationReadUnitsUsed": 0,
                    "visualizationFactQueriesUsed": 0,
                    "visualizationToolCalls": 0,
                    "visualizationScriptFailures": 0,
                }
            )
            output_options["analysis_output_path"] = "reports/section-1/charts.json"
        else:
            output_options.update(
                {
                    "section_output_path": "reports/section-1/section.json",
                    "rework_request_path": "reports/section-1/rework.json",
                }
            )
        contract = build_report_phase_acceptance_contract(
            phase=phase,
            validation_context_file={
                "path": "reports/validation.json",
                "size": 2,
                "sha256": "a" * 64,
            },
            phase_contract=phase_contract,
            **output_options,
        )
        await self.coordinator.start(scope, str(payload), acceptance_contract=contract)

        async def analysis_executor(invocation: Any) -> Any:
            self.contexts.append(invocation.run_context)
            self._project_tools(task_kind, invocation.run_context)
            self.repository.finish(task_id, task_kind)
            return SimpleNamespace(status="completed")

        executor = analysis_executor
        receipt = await self.coordinator.run(
            scope, parent_run_id=str(parent_context.run_id), executor=executor
        )
        return StepOutput(content=receipt)

    async def arun(self, report_input: dict[str, Any], **kwargs: Any) -> Any:
        self.received_input = report_input
        self.received_scope = kwargs["dependencies"]["AgentOS 报表工作流"]
        context = RunContext(
            run_id=kwargs["run_id"],
            session_id=kwargs["session_id"],
            user_id=kwargs["user_id"],
            session_state=kwargs["session_state"],
            dependencies=kwargs["dependencies"],
        )

        async def analysis(payload: Mapping[str, Any], run_context: RunContext) -> StepOutput:
            return await self._run_task("analysis_item", payload, run_context)

        async def visualization(payload: Mapping[str, Any], run_context: RunContext) -> StepOutput:
            return await self._run_task("visualization_section", payload, run_context)

        async def section(payload: Mapping[str, Any], run_context: RunContext) -> StepOutput:
            return await self._run_task("section", payload, run_context)

        workflow = ReportingDraftWorkflow(
            report_goal=report_input["prompt"],
            section_goal={"sectionCode": "section-1"},
            analysis_ids=("analysis-1",),
            run_analysis=analysis,
            submit_visualization=visualization,
            draft_section=section,
        )
        self.production_draft_workflow_called = True
        await workflow.execute_section(context)
        return SimpleNamespace(status="completed", content={"sectionCode": "section-1"})

    async def acontinue_run(self, **_kwargs: Any) -> Any:
        raise AssertionError("正常 CLI mock 闭环不应调用 continuation")


def _mock_tool_runtime() -> MockReportingToolRuntime:
    return MockReportingToolRuntime(
        input_snapshot={"version": "1"},
        inputs={"inputs/report.json": b"{}"},
        output_policy=ReportingOutputPolicy(("reports",)),
    )


@pytest.mark.anyio
async def test_cli_input_reaches_production_draft_workflow() -> None:
    raw = "生成 2025 年运营报告，重点分析收入同比和区域贡献"
    parsed = parse_report_input(raw)
    adapter = _CliDraftAdapter()

    result = await drive_workflow(
        adapter,
        _Runtime(),
        parsed,
        run_id="cli-run-1",
        session_id="cli-session-1",
        user_id="cli-user-1",
        database="odoo",
        company_id="company-1",
    )

    assert adapter.received_input == parsed
    assert adapter.received_scope == {
        "externalRunId": "cli-run-1",
        "threadId": "cli-session-1",
        "userId": "cli-user-1",
        "database": "odoo",
        "companyId": "company-1",
    }
    assert result["status"] == "completed"
    assert adapter.production_draft_workflow_called is True
    assert len(adapter.contexts) == 3
    assert all(context.user_id == "cli-user-1" for context in adapter.contexts)
    assert all(context.dependencies is not None for context in adapter.contexts)
    assert all(
        cast(dict[str, Any], context.dependencies)[TASK_EXECUTION_DEPENDENCY]["threadId"]
        == "cli-session-1"
        for context in adapter.contexts
    )
    assert adapter.tool_projections == [
        (
            "analysis_item",
            (
                "apply_analysis_patch",
                "complete_analysis_item",
                "query_analysis_context",
                "query_analysis_facts",
                "query_profile",
                "read_file",
                "read_tool_output",
                "run_python_script",
            ),
        ),
        (
            "visualization_section",
            (
                "apply_analysis_patch",
                "read_file",
                "read_tool_output",
                "run_python_script",
                "submit_visualization_charts",
            ),
        ),
        (
            "section",
            (
                "read_file",
                "read_tool_output",
                "render_report_section",
                "request_analysis_rework",
            ),
        ),
    ]


@pytest.mark.anyio
async def test_cli_mock_repeated_ten_times_is_deterministic() -> None:
    observations: list[tuple[dict[str, Any], tuple[tuple[str, Any], ...]]] = []
    for index in range(10):
        adapter = _CliDraftAdapter()
        runtime = _Runtime()
        parsed = parse_report_input("生成 2025 年运营报告")
        result = await drive_workflow(
            adapter,
            runtime,
            parsed,
            run_id=f"cli-run-{index}",
            session_id=f"cli-session-{index}",
            user_id="cli-user-1",
        )
        observations.append(
            (
                result,
                tuple(("run", "session") for _context in adapter.contexts),
            )
        )
        assert runtime.cleaned is False
    assert all(item[0]["status"] == "completed" for item in observations)
    assert all(item[1] == observations[0][1] for item in observations)


def test_mock_runtime_isolated_for_each_cli_case() -> None:
    first = _mock_tool_runtime()
    second = _mock_tool_runtime()
    assert first is not second
    assert first.workspace is not second.workspace
    assert first.calls == second.calls == []


@pytest.mark.anyio
async def test_mock_workspace_script_and_sha_recovery_boundaries() -> None:
    runtime = _mock_tool_runtime()
    completed = await runtime.workspace.execute_script("reports/script.py", timeout=30)
    assert completed == {
        "ok": True,
        "status": "completed",
        "exitCode": 0,
        "exit_code": 0,
    }
    assert runtime.workspace.calls == [
        {"operation": "execute_script", "script_path": "reports/script.py", "timeout": 30}
    ]

    identity = await runtime.workspace.write_text("reports/script.py", "print('v1')")
    runtime.workspace._outputs["reports/script.py"] = b"print('v2')"
    with pytest.raises(Exception, match="哈希已变化"):
        await runtime.workspace.write_text(
            "reports/script.py", "print('repair')", overwrite=True, expected_sha256=identity.sha256
        )
