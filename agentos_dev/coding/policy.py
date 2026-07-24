from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .models import AttemptSnapshot, TaskSnapshot, utcnow

MAX_CONTINUATIONS = 20
SAME_ERROR_LIMIT = 3


class ContinuationAction(StrEnum):
    CANCEL = "cancel"
    FINALIZE_FINISH = "finalize_finish"
    FAIL_DEADLINE = "fail_deadline"
    FAIL_BUDGET = "fail_budget"
    APPLY_INSTRUCTIONS = "apply_instructions"
    FAIL_SAME_ERROR = "fail_same_error"
    RESUME = "resume"
    CONTINUE = "continue"


@dataclass(frozen=True)
class ContinuationDecision:
    action: ContinuationAction
    code: str


class ContinuationPolicy:
    """无 I/O 的 Coding Attempt 推进策略。"""

    def decide(
        self,
        task: TaskSnapshot,
        attempt: AttemptSnapshot,
        *,
        pending_instruction_count: int = 0,
        checkpoint_recoverable: bool = False,
        cancel_requested: bool = False,
        now: datetime | None = None,
    ) -> ContinuationDecision:
        current_time = now or utcnow()
        if cancel_requested:
            return ContinuationDecision(ContinuationAction.CANCEL, "coding_task_cancelled")
        if task.finish_receipt is not None:
            return ContinuationDecision(
                ContinuationAction.FINALIZE_FINISH, "finish_receipt_present"
            )
        if task.deadline_at <= current_time:
            return ContinuationDecision(ContinuationAction.FAIL_DEADLINE, "task_deadline_exceeded")
        if pending_instruction_count:
            if task.continuation_count >= MAX_CONTINUATIONS:
                return ContinuationDecision(
                    ContinuationAction.FAIL_BUDGET, "task_continuation_exhausted"
                )
            return ContinuationDecision(
                ContinuationAction.APPLY_INSTRUCTIONS, "instruction_pending"
            )
        if task.same_error_count >= SAME_ERROR_LIMIT:
            return ContinuationDecision(
                ContinuationAction.FAIL_SAME_ERROR, "coding_same_error_circuit_open"
            )
        if checkpoint_recoverable:
            return ContinuationDecision(ContinuationAction.RESUME, "checkpoint_recoverable")
        if task.continuation_count >= MAX_CONTINUATIONS:
            return ContinuationDecision(
                ContinuationAction.FAIL_BUDGET, "task_continuation_exhausted"
            )
        return ContinuationDecision(ContinuationAction.CONTINUE, "attempt_no_finish")
