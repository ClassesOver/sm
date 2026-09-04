from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from smart_reporting.model_routing import DEFAULT_MODEL_PROFILES
from smart_reporting.reporting.workflow.execution import (
    ReportingTaskCoordinator,
)
from smart_reporting.task_execution import (
    AttemptSnapshot,
    AttemptState,
    Lease,
    TaskExecutionScope,
    TaskSnapshot,
    TaskState,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class _Repository:
    def __init__(self, scope: TaskExecutionScope) -> None:
        self.task = TaskSnapshot(
            scope=scope,
            state=TaskState.NEW,
            state_version=1,
            lease_epoch=0,
            continuation_count=0,
            instruction_sequence=1,
            current_internal_run_id="internal-run-1",
            current_attempt_no=0,
            deadline_at=_utcnow() + timedelta(hours=1),
            acceptance_contract={
                "requirements": [
                    {
                        "id": "reporting-phase",
                        "kind": "reporting_phase",
                        "parameters": {
                            "phase": "analysis",
                            "phaseContract": {"taskKind": "analysis_item"},
                        },
                    }
                ]
            },
        )

    async def cleanup_expired(self, *, lease_owner: str) -> None:
        del lease_owner

    async def claim_lease(self, external_run_id: str, owner: str, *, ttl: timedelta) -> Lease:
        assert external_run_id == self.task.scope.external_run_id
        return Lease(owner, 1, _utcnow() + ttl)

    async def release_lease(self, external_run_id: str, owner: str) -> None:
        assert external_run_id == self.task.scope.external_run_id
        assert owner

    async def get_task_snapshot(self, external_run_id: str) -> TaskSnapshot:
        assert external_run_id == self.task.scope.external_run_id
        return self.task

    async def open_initial(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
    ) -> tuple[TaskSnapshot, AttemptSnapshot]:
        assert external_run_id == self.task.scope.external_run_id
        assert expected_state_version == self.task.state_version
        self.task = replace(
            self.task,
            state=TaskState.ACTIVE,
            state_version=self.task.state_version + 1,
            lease_epoch=lease.epoch,
        )
        return self.task, AttemptSnapshot(
            internal_run_id=self.task.current_internal_run_id,
            external_run_id=external_run_id,
            attempt_no=0,
            state=AttemptState.RUNNING,
            resume_count=0,
            lease_epoch=lease.epoch,
        )

    async def attempt_instruction(self, external_run_id: str, attempt_no: int) -> str:
        assert external_run_id == self.task.scope.external_run_id
        assert attempt_no == 0
        return '{"currentAnalysisId":"analysis-1"}'

    async def finalize_finish(
        self,
        external_run_id: str,
        lease: Lease,
        expected_state_version: int,
        *,
        agno_status: str,
    ) -> TaskSnapshot:
        assert external_run_id == self.task.scope.external_run_id
        assert expected_state_version == self.task.state_version
        assert lease.epoch == 1
        assert agno_status == "completed"
        self.task = replace(
            self.task, state=TaskState.COMPLETED, state_version=expected_state_version + 1
        )
        return self.task

    async def cancel_and_reject(self, scope: TaskExecutionScope) -> None:
        assert scope == self.task.scope


@pytest.mark.anyio
async def test_analysis_item_task_runs_without_worker_agent() -> None:
    scope = TaskExecutionScope(
        external_run_id="analysis-task-1",
        owner_user_id="user-1",
        thread_id="thread-1",
        sandbox_id="sandbox-1",
        executor_id="reporting-analysis-workflow",
    )
    repository = _Repository(scope)
    execution_kernel = SimpleNamespace(
        cleanup_old_epoch=AsyncMock(),
        cleanup_disconnect=AsyncMock(),
    )
    coordinator = ReportingTaskCoordinator(
        repository,
        execution_kernel,
        model_profiles=DEFAULT_MODEL_PROFILES,
    )
    calls: list[tuple[str, str, str]] = []

    async def executor(invocation):
        calls.append(
            (
                invocation.instruction,
                invocation.run_context.run_id,
                invocation.run_context.session_id,
            )
        )
        repository.task = replace(
            repository.task,
            state=TaskState.FINISHING,
            state_version=repository.task.state_version + 1,
            finish_receipt={"summary": "分析完成", "artifactPaths": []},
        )
        return SimpleNamespace(status="completed")

    receipt = await coordinator.run(scope, executor=executor)

    assert calls == [
        (
            '{"currentAnalysisId":"analysis-1"}',
            "internal-run-1",
            "task-execution:analysis-task-1:attempt:0",
        )
    ]
    assert receipt["summary"] == "分析完成"
    execution_kernel.cleanup_old_epoch.assert_awaited_once_with(scope, 1)
