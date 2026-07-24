from __future__ import annotations

from .models import AttemptOutcome, AttemptSnapshot, Lease, TaskSnapshot
from .repository import CodingTaskRepository


class InternalRunManager:
    def __init__(self, repository: CodingTaskRepository):
        self.repository = repository

    async def open_initial(
        self, task: TaskSnapshot, lease: Lease
    ) -> tuple[TaskSnapshot, AttemptSnapshot]:
        return await self.repository.open_initial(
            task.scope.external_run_id, lease, task.state_version
        )

    async def resume_current(
        self, task: TaskSnapshot, lease: Lease
    ) -> tuple[TaskSnapshot, AttemptSnapshot]:
        return await self.repository.resume_current(
            task.scope.external_run_id, lease, task.state_version
        )

    async def close_and_advance(
        self,
        task: TaskSnapshot,
        lease: Lease,
        *,
        outcome: AttemptOutcome,
        agno_status: str | None,
        terminal_output: str = "",
        error: BaseException | str | None = None,
        create_next: bool,
    ) -> TaskSnapshot:
        return await self.repository.close_and_decide(
            task.scope.external_run_id,
            lease,
            task.state_version,
            outcome=outcome,
            agno_status=agno_status,
            terminal_output=terminal_output,
            error=error,
            create_next=create_next,
        )
